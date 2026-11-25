#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# OpenPocket — tests/rate48/score.sh's block check: each case of `render bands` at 44.1 kHz against the same case at
# 48 kHz. A case fails when either render has a NaN, when the levels differ by more than 0.5 dB, or when a third-octave
# band within 40 dB of the 44.1 kHz render's loudest differs by more than 0.5 dB once the level difference is taken out.
# A case of ALLOW has its own limit, and the reason it differs.
#   compare.py BANDS44 BANDS48         prints each failing or allowed case, then "blocks: N failures of M cases"
import sys

LIMIT, RANGE, SILENT = 0.5, 40.0, -90.0
# (block, type, setting, or None for every setting): (limit in dB, or None for none; why it differs at 48 kHz)
ALLOW = {}


def read(path):
    rows = {}
    for line in open(path):
        f = line.rstrip("\n").split("|")
        rows[tuple(f[:3])] = (int(f[3]), float(f[4]), [float(v) for v in f[5:]])
    return rows


def main(a, b):
    r44, r48 = read(a), read(b)
    fails, told = 0, {}                                # a reason given: the first case it was given for
    for case, (nan44, lv44, b44) in r44.items():
        nan48, lv48, b48 = r48[case]
        limit, reason = ALLOW.get(case) or ALLOW.get(case[:2] + (None,)) or (LIMIT, None)
        name = " ".join(case)
        if nan44 or nan48:
            why, bad = f"NaN ({nan44} at 44.1 kHz, {nan48} at 48 kHz)", True
        elif lv44 < SILENT and lv48 < SILENT:
            continue
        else:
            top = max(b44)
            dev = [(abs((y - x) - (lv48 - lv44)), i) for i, (x, y) in enumerate(zip(b44, b48)) if x >= top - RANGE]
            worst, at = max(dev) if dev else (0.0, 0)
            worst = max(worst, abs(lv48 - lv44))
            if worst <= LIMIT:
                continue
            why = f"level {lv48 - lv44:+.2f} dB, band {1000 * 2 ** ((at - 10) / 3):.0f} Hz {max(dev)[0] if dev else 0:.2f} dB"
            bad = limit is not None and worst > limit
        if reason and not bad:
            print(f"allowed {name}: {why} ({'as ' + told[reason] if reason in told else reason})")
            told.setdefault(reason, name)
            continue
        print(f"FAIL {name}: {why}" + (f" (more than its {limit} dB: {reason})" if reason else ""))
        fails += 1
    print(f"blocks: {fails} failures of {len(r44)} cases")


main(*sys.argv[1:3])
