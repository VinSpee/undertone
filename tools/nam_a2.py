#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# OpenPocket — an independent NumPy implementation of Neural Amp Modeler's A2 network (the 2026 "A2-Lite" / "A2-Full"
# WaveNet), written from the published architecture. Used as the reference for the pedal's fixed-point engine
# (firmware/apps/gamut/engine/px_nam.c) and by the web editor's converter tests.
#
# A2 (one layer array, 23 layers, LeakyReLU 0.01, no gating, no FiLM):
#   x0 = rechannel(input)                                  1 -> C, no bias
#   per layer i (kernel K_i, dilation d_i):
#     z  = conv_dilated(x)  + bias                         C -> C, causal, taps at t - (K-1-k) d
#     z += mixin * input                                   1 -> C, no bias
#     a  = LeakyReLU(z, 0.01)
#     head_sum += a
#     x  = x + layer1x1(a) + bias                          C -> C
#   y = head_scale * (head_conv(head_sum) + bias)          C -> 1, kernel 16, causal
# Weights, in file order: rechannel [C]; per layer conv [C_out][C_in][K], conv bias [C], mixin [C],
# layer1x1 [C_out][C_in], layer1x1 bias [C]; head [C][16], head bias; head_scale (the last value).
#   nam_a2.py MODEL.nam in.wav out.wav [lite|full]        (renders at the model's rate, no resampling)
import json, sys
import numpy as np

KERNELS = [6] * 14 + [15, 15] + [6] * 7
DILATIONS = [1, 3, 7, 17, 41, 101, 239] * 2 + [1, 13] + [1, 3, 7, 17, 41, 101, 239]
HEAD_K = 16
SLOPE = 0.01


def submodels(j):
    """The WaveNet entries of a .nam: a plain WaveNet, or each submodel of a SlimmableContainer (A2 files hold
    A2-Lite, 3 channels, and A2-Full, 8 channels)."""
    if j.get("architecture") == "SlimmableContainer":
        return [s["model"] for s in j["config"]["submodels"]]
    return [j]


def is_a2(m):
    if m.get("architecture") != "WaveNet":
        return 0
    cfg = m["config"]
    if cfg.get("head") is not None or len(cfg.get("layers", [])) != 1:
        return 0
    L = cfg["layers"][0]
    c = L.get("channels")
    ok = (L.get("kernel_sizes") == KERNELS and L.get("dilations") == DILATIONS and L.get("bottleneck") == c
          and L.get("input_size") == 1 and L.get("condition_size") == 1
          and (L.get("head") or {}).get("kernel_size") == HEAD_K and (L.get("head") or {}).get("out_channels") == 1
          and (L.get("head") or {}).get("bias") is True
          and not (L.get("head1x1") or {}).get("active") and (L.get("layer1x1") or {}).get("active", True)
          and all(g in (None, "none") for g in (L.get("gating_mode") or ["none"]))
          and all((a or {}).get("type") == "LeakyReLU" and abs((a or {}).get("negative_slope", 0) - SLOPE) < 1e-9
                  for a in (L.get("activation") or [None])))
    for k in ("conv_pre_film", "conv_post_film", "input_mixin_pre_film", "input_mixin_post_film",
              "activation_pre_film", "activation_post_film", "layer1x1_post_film", "head1x1_post_film"):
        if (L.get(k) or {}).get("active"):
            ok = False
    return c if ok else 0


def pick(j, size="lite"):
    """The A2 submodel of the wanted size: (model dict, channels). Raises if the file has no A2 network."""
    found = [(m, is_a2(m)) for m in submodels(j)]
    found = [(m, c) for m, c in found if c]
    if not found:
        raise ValueError("not an A2 model")
    found.sort(key=lambda mc: mc[1])
    return found[0] if size == "lite" else found[-1]


def unpack(weights, C):
    w = np.asarray(weights, dtype=np.float64)
    i = 0

    def take(n):
        nonlocal i
        r = w[i:i + n]
        if len(r) != n:
            raise ValueError("not enough weights")
        i += n
        return r
    net = {"C": C, "rechannel": take(C), "layers": []}
    for K, d in zip(KERNELS, DILATIONS):
        conv = take(C * C * K).reshape(C, C, K)          # out, in, tap (tap K-1 = now)
        cb = take(C)
        mix = take(C)
        one = take(C * C).reshape(C, C)                  # out, in
        ob = take(C)
        net["layers"].append((K, d, conv, cb, mix, one, ob))
    net["head"] = take(C * HEAD_K).reshape(C, HEAD_K)
    net["head_b"] = float(take(1)[0])
    net["head_scale"] = float(take(1)[0])
    if i != len(w):
        raise ValueError("weights left over: %d of %d used" % (i, len(w)))
    return net


def n_weights(C):
    return C + sum(C * C * K + 3 * C + C * C for K in KERNELS) + C * HEAD_K + 2


def causal_conv(x, w, d):
    """x [C_in, T]; w [C_out, C_in, K]; y[:, t] = sum_k w[:, :, k] x[:, t - (K-1-k) d] (zeros before 0)."""
    Cout, Cin, K = w.shape
    T = x.shape[1]
    y = np.zeros((Cout, T))
    for k in range(K):
        s = (K - 1 - k) * d
        if s >= T:
            continue
        y[:, s:] += w[:, :, k] @ x[:, :T - s]
    return y


def run(net, inp, peak=False):
    """the network's output; with peak, (output, its largest internal value: the residual x, z, the head's sum and
    the head's output before head_scale), as docs/pxnam.js a2Net"""
    u = np.asarray(inp, dtype=np.float64)[None, :]
    x = net["rechannel"][:, None] * u
    hs = np.zeros_like(x)
    top = np.max(np.abs(x))
    for K, d, conv, cb, mix, one, ob in net["layers"]:
        z = causal_conv(x, conv, d) + cb[:, None] + mix[:, None] * u
        a = np.where(z >= 0, z, z * SLOPE)
        hs += a
        x = x + one @ a + ob[:, None]
        top = max(top, np.max(np.abs(z)), np.max(np.abs(x)), np.max(np.abs(hs)))
    y = causal_conv(hs, net["head"][None, :, :], 1)[0] + net["head_b"]
    top = max(top, np.max(np.abs(y)))
    return (net["head_scale"] * y, float(top)) if peak else net["head_scale"] * y


# The pedal's fixed point (px_nam.h: activations Q20) holds internal values up to +-RANGE. LeakyReLU passes a scale
# through, so the network with the input rechannel, every bias, mixin and the head bias times s, and head_scale divided
# by s, gives the same output with every internal value times s (exactly, s a power of two). fit_range halves until the
# peak on the DI clip at the level the pedal feeds the network at GAIN +12 dB is below half the range, as the web
# editor's import does (docs/pxnam.js fitRange): (weights, halvings)
RANGE = 2048.0


def fit_range(weights, di, C=3):
    x = np.asarray(di, dtype=np.float64)[:44100] * (0.5 / 0.15 * 10 ** (12 / 20))
    top = run(unpack(weights, C), x, peak=True)[1]
    h = 0
    while top / 2 ** h >= RANGE / 2:
        h += 1
    return (rescale(weights, 2.0 ** -h, C) if h else np.asarray(weights, dtype=np.float32)), h


def rescale(weights, s, C=3):
    w = np.array(weights, dtype=np.float32)
    i = C
    w[:C] *= s                                           # rechannel
    for K in KERNELS:
        i += C * C * K
        w[i:i + 2 * C] *= s                              # conv bias, mixin
        i += 2 * C + C * C
        w[i:i + C] *= s                                  # layer1x1 bias
        i += C
    i += C * HEAD_K
    w[i] *= s                                            # head bias
    w[i + 1] /= s                                        # head_scale
    return w


def load(path, size="lite"):
    j = json.load(open(path))
    m, C = pick(j, size)
    net = unpack(m["weights"], C)
    net["sr"] = float(m.get("sample_rate") or j.get("sample_rate") or 48000.0)
    net["meta"] = m.get("metadata") or j.get("metadata") or {}
    return net


if __name__ == "__main__":
    import wave
    path, src, dst = sys.argv[1:4]
    size = sys.argv[4] if len(sys.argv) > 4 else "lite"
    net = load(path, size)
    w = wave.open(src)
    n, ch, sw = w.getnframes(), w.getnchannels(), w.getsampwidth()
    raw = np.frombuffer(w.readframes(n), dtype={2: np.int16, 4: np.int32}[sw]).astype(np.float64)
    x = raw.reshape(-1, ch)[:, 0] / (32768.0 if sw == 2 else 2147483648.0)
    y = run(net, x)
    o = wave.open(dst, "wb")
    o.setnchannels(1); o.setsampwidth(2); o.setframerate(int(net["sr"]))
    o.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
    print("%s: C=%d, %d samples, peak %.3f" % (path, net["C"], len(y), np.max(np.abs(y))))
