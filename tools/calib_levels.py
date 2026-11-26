#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# OpenPocket — level calibration (v36) -> firmware/apps/gamut/engine/px_trim.h. Loudness = ITU-R BS.1770 (K-weighted, gated) of real DI
# guitar at the pedal's level (x 0.15: hard playing peaks about -17 dBFS at the converter).
#  - every type of the effect blocks (knobs at noon, in front of / after the first factory NAM model at noon): switching
#    it on keeps the loudness
# The numbers in px_trim.h were measured in v36 round the built-in TWIN amp and 1x12 cabinet, which store format 6
# removed; a new run measures them round the first factory NAM model (SUPER 65 since the TONE3000 captures), so it
# changes them.
#   python3 tools/calib_levels.py DI.wav [DI2.wav ...]      (44.1 kHz WAVs, played at the engine's rate: at_rate)
import os, re, subprocess, sys, wave
import numpy as np
from scipy import signal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import nam_level  # noqa: E402
SR = 48000                          # the engine's rate (firmware/apps/gamut/engine/px_dsp.h PX_FS), which the harnesses run at
TARGET = -23.0                      # LUFS at noon (EBU R128; engine output, before the master volume): headroom for cleans
EXE = os.path.join(ROOT, "build", "lvl_chain")
TRIM = os.path.join(ROOT, "firmware", "apps", "gamut", "engine", "px_trim.h")
B = dict(GT=0, CMP=1, PIT=2, SFX=3, DRV=4, AMP=5, CAB=6, EQ=7, MOD=8, DLY=9, REV=10, SYN=11)
NT = dict(CMP=4, PIT=5, SFX=7, DRV=4, MOD=11, DLY=8, REV=8, SYN=11)
M0 = 1                              # the AMP block's MODEL knob for the first factory NAM model (px_nam_knob(0))


def kweight(x):
    f0, G, Q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    K = np.tan(np.pi * f0 / SR); Vh = 10 ** (G / 20); Vb = Vh ** 0.4996667741545416; a0 = 1 + K / Q + K * K
    y = signal.lfilter([(Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0],
                       [1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0], x)
    f0, Q = 38.13547087602444, 0.5003270373238773; K = np.tan(np.pi * f0 / SR); a0 = 1 + K / Q + K * K
    return signal.lfilter([1, -2, 1], [1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0], y)


def lufs(x):
    y = kweight(x); blk, hop = int(0.4 * SR), int(0.1 * SR)
    z = np.array([np.mean(y[i:i + blk] ** 2) for i in range(0, len(y) - blk, hop)])
    z = z[-0.691 + 10 * np.log10(z + 1e-20) > -70]
    if not len(z): return -99.0
    rel = -0.691 + 10 * np.log10(np.mean(z)) - 10
    z = z[-0.691 + 10 * np.log10(z) > rel]
    return float(-0.691 + 10 * np.log10(np.mean(z)))


def at_rate(path):
    """a 44.1 kHz DI WAV at SR, as the harnesses read one (16-bit mono): build/lvl_di_SR_NAME"""
    out = os.path.join(ROOT, "build", "lvl_di_%d_%s" % (SR, os.path.basename(path)))
    w = wave.open(out, "wb")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(np.clip(np.round(nam_level.di(path, SR) * 32768), -32768, 32767).astype("<i2").tobytes())
    w.close()
    return out


def build():
    subprocess.run(["cc", "-O2", "-I" + os.path.join(ROOT, "firmware", "apps", "gamut", "engine"), os.path.join(ROOT, "firmware", "apps", "gamut", "tests", "engine", "chain.c"),
                    os.path.join(ROOT, "firmware", "apps", "gamut", "engine", "px_dsp.c"), os.path.join(ROOT, "firmware", "px_math.c"), "-lm", "-o", EXE],
                   check=True)


def loud(dis, blocks):
    """mean loudness over the DIs of a chain: blocks = [(block, type, [5 knobs]), ...]"""
    args = []
    for b, t, k in blocks: args += [str(b), str(t)] + [str(v) for v in k]
    out = os.path.join(ROOT, "build", "lvl.f32")
    ls = []
    for d in dis:
        subprocess.run([EXE, d, out] + args, check=True)
        ls.append(lufs(np.fromfile(out, np.float32).astype(np.float64)))
    return float(np.mean(ls))


def write(t):
    f = lambda v: "{" + ", ".join("%.2ff" % x for x in v) + "}"
    s = open(TRIM).read()
    for k in NT:
        s = re.sub(r"(%s_DB\[PX_%s_COUNT\] = )\{[^}]*\};" % (k, k), lambda m: m.group(1) + f(t[k]) + ";", s)
    open(TRIM, "w").write(s)


def main():
    dis = [at_rate(d) for d in sys.argv[1:]]
    if not dis: sys.exit(__doc__ or "usage: calib_levels.py DI.wav [...]")
    t = {k: [0.0] * n for k, n in NT.items()}
    write(t); build()
    noon = [50] * 5
    amp = (B["AMP"], 0, [M0, 50, 50, 50, 50])
    ref = loud(dis, [amp])
    print("the first NAM model at noon: %.2f LUFS" % ref)
    # every block's types, twice (blocks in front of the amp see its slight curve)
    for it in range(2):
        for k in NT:
            for ty in range(NT[k]):
                l = loud(dis, [amp, (B[k], ty, noon)])
                t[k][ty] = round(float(np.clip(t[k][ty] + ref - l, -15, 15)), 2)
            print(it, k, t[k], flush=True)
        write(t); build()
    # check
    worst = 0.0
    for k in NT:
        for ty in range(NT[k]):
            worst = max(worst, abs(loud(dis, [amp, (B[k], ty, noon)]) - ref))
    print("largest remaining difference: %.2f dB" % worst)


if __name__ == "__main__":
    main()
