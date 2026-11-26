#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# OpenPocket — the factory amps against their source captures at 48 kHz, the rate the captures were made at (the 48 kHz
# port, docs/RATE48-TEST.md). It needs the capture files, which the repository does not hold (tools/nam_factory.txt):
#   python3 tests/rate48/amps.py CAPTURES [build/nam_test]
# For each factory model, on docs/nam_di.wav resampled to 48 kHz, at the level the factory presets' DI reaches the
# network at GAIN noon (the clip as it is):
#  - its weights (px_nam_factory.h) play exactly its capture's A2-Lite part (ESR below 1e-9: fit_range's scale changes
#    nothing)
#  - for the record, not a failure: how far the A2-Lite part is from the capture's own A2-Full (ESR, and the largest
#    third-octave band difference from 80 Hz to 10 kHz with the level taken out)
# and on its first second at firmware/apps/gamut/tests/test_nam.py's hotter level: the pedal's fixed point
# (build/nam_test, firmware/apps/gamut/engine/px_nam.c) within 80 dB of float, at GAIN noon and +12 dB
# Prints a line a model, then "amps: N failures".
import json, os, re, subprocess, sys
import numpy as np
from scipy.signal import resample_poly, welch

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import mk_nam_factory, nam_a2, nam_level  # noqa: E402

SR = 48000


def esr(y, ref):
    return float(np.sum((y - ref) ** 2) / np.sum(ref ** 2))


def bands(y):
    f, p = welch(y, SR, nperseg=round(16384 * SR / 44100))
    cs = 1000 * 2 ** (np.arange(-10, 11) / 3)
    return np.array([10 * np.log10(p[(f >= c / 2 ** (1 / 6)) & (f < c * 2 ** (1 / 6))].sum() + 1e-30) for c in cs])


def main():
    top = sys.argv[1]
    exe = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "build", "nam_test")
    out = os.path.join(ROOT, "build", "rate48")
    os.makedirs(out, exist_ok=True)
    hdr = open(os.path.join(ROOT, "firmware", "apps", "gamut", "engine", "px_nam_factory.h")).read()
    body = hdr[hdr.index("PXN_FW[PX_NAM_NFACT][PXN_NW] = {"):]
    models = [np.array([float(v.rstrip("f")) for v in re.findall(r"[-+0-9.eE]+f", m)], np.float32)
              for m in re.findall(r"\{([^{}]*)\}", body)]
    x = resample_poly(nam_level.di(), 160, 147)
    xq = x[:SR] / 0.15 * 0.5
    fails = 0
    for (name, fn, sha, author, page), w in zip(mk_nam_factory.rows(), models):
        j = json.load(open(mk_nam_factory.find(top, fn)))
        lite = nam_a2.unpack(nam_a2.pick(j, "lite")[0]["weights"], 3)
        mf, cf = nam_a2.pick(j, "full")
        full = nam_a2.unpack(mf["weights"], cf)
        y = nam_a2.run(nam_a2.unpack(w.astype(np.float64), 3), x)
        yl, yf = nam_a2.run(lite, x), nam_a2.run(full, x)
        same = esr(y, yl)
        snr = []
        for g in (1.0, 10 ** (12 / 20)):
            xi = (xq * g).astype(np.float32)
            w.tofile(os.path.join(out, "w.f32")); xi.tofile(os.path.join(out, "in.f32"))
            subprocess.run([exe, os.path.join(out, "w.f32"), os.path.join(out, "in.f32"), os.path.join(out, "out.f32"), "64"], check=True)
            ref = nam_a2.run(nam_a2.unpack(w.astype(np.float64), 3), xi.astype(np.float64))
            yq = np.fromfile(os.path.join(out, "out.f32"), np.float32)
            snr.append(10 * np.log10(np.sum(ref ** 2) / max(np.sum((yq - ref) ** 2), 1e-30)))
        bl, bf = bands(yl), bands(yf)
        dev = (bl - bf) - (nam_level.lufs(yl, SR) - nam_level.lufs(yf, SR))
        worst = float(np.max(np.abs(dev[bf > bf.max() - 40])))
        ok = same < 1e-9 and min(snr) > 80
        fails += not ok
        print("%-8s the capture's A2-Lite: ESR %.1e; fixed point %.1f / %.1f dB (noon / +12 dB); against its A2-Full: "
              "ESR %.3f, worst band %.1f dB  %s" % (name, same, snr[0], snr[1], esr(yl, yf), worst, "ok" if ok else "FAIL"))
    print("amps: %d failures" % fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
