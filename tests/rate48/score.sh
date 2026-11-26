#!/bin/sh
# OpenPocket: how far Gamut is from sounding at 48 kHz as it does at 44.1 kHz (the 48 kHz port, docs/RATE48-TEST.md).
#   sh tests/rate48/score.sh            prints each failure, then "failures: N" (the target is 0)
# Its checks, each failure counting 1, on the PC (no pedal, no toolchain; writes to build/rate48):
#  - blocks: every block type but AMP and CAB alone, all its settings at 0, 50 and 100, through docs/nam_di.wav, at
#    44.1 kHz with the engine built as today and at 48 kHz with the engine built for 48 kHz (-DPX_FS=48000): no NaN,
#    the level and every third-octave band from 99 Hz to 10 kHz within 0.5 dB (tests/rate48/compare.py, which lists
#    the cases allowed to differ, by how much and why)
#  - delay: DIGITAL at TIME 100 echoes at 48 kHz within one sample of where it does at 44.1 kHz (2000 ms)
#  - plate: the PLATE reverb at 48 kHz keeps at least its size at 44.1 kHz (where its memory holds 0.96 of Dattorro's)
#  - tuner: tests/test_tuner.c at 48 kHz (every note within 2 cents, as at 44.1 kHz)
#  - USB audio: tests/test_usb_audio.c at 48 kHz (the streams at 48 kHz, 10 minutes with the clocks 300 ppm apart)
#  - base audio: tests/test_base_audio.c at 48 kHz (the block's budget follows A_SR)
#  - amps, only with NAM_CAPTURES=<a folder holding the capture files of tools/nam_factory.txt>, which the repository
#    does not hold: each factory amp is its capture's A2-Lite part and the pedal's fixed point plays it at 48 kHz
#    (tests/rate48/amps.py)
# Not here, as it needs a file the repository does not hold: the factory cabinet IR against its 48 kHz WAV.
# Guard, not scored: until the switch to 48 kHz, the 44.1 kHz engine stays bit for bit the one of the commit the
# port started from (firmware/apps/gamut/tests/equiv.sh REF).
cd "$(dirname "$0")/../.."
CC="${CC:-cc}"
B=build/rate48
mkdir -p "$B"
for f in tuner usb base; do : > "$B/$f.log"; done
fails=0
fail() { echo "FAIL $*"; fails=$((fails + 1)); }
why() { tail -1 "$B/$1.log"; grep -m1 error "$B/$1.err"; }   # a test's last line, or why it did not build
EF="-O2 -w -fno-builtin -ffp-contract=off -Ifirmware/apps/gamut/engine"
$CC $EF -o $B/render44 tests/rate48/render.c firmware/px_math.c -lm || exit 1
$CC $EF -DPX_FS=48000 -o $B/render48 tests/rate48/render.c firmware/px_math.c -lm || exit 1
$B/render44 bands 44100 docs/nam_di.wav > $B/bands44.txt & p44=$!
$B/render48 bands 48000 docs/nam_di.wav > $B/bands48.txt || exit 1
wait $p44 || exit 1
python3 tests/rate48/compare.py $B/bands44.txt $B/bands48.txt > $B/blocks.txt || exit 1
grep -v '^blocks:' $B/blocks.txt
n=$(sed -n 's/^blocks: \([0-9]*\) failures.*/\1/p' $B/blocks.txt)
fails=$((fails + n))
d44=$($B/render44 delay 44100) d48=$($B/render48 delay 48000)
awk -v a="$d44" -v b="$d48" 'BEGIN { d = a - b; exit !(d <= 1000 / 48000 && d >= -1000 / 48000) }' ||
  fail "delay: TIME 100 echoes at $d48 ms at 48 kHz, $d44 ms at 44.1 kHz"
p44=$($B/render44 plate 44100) p48=$($B/render48 plate 48000)
awk -v a="$p44" -v b="$p48" 'BEGIN { exit !(b >= a) }' || fail "plate: $p48 of Dattorro's size at 48 kHz, $p44 at 44.1 kHz"
{ $CC -O1 -Wall -Ifirmware -DA_SR=48000u tests/test_tuner.c -lm -o $B/test_tuner && $B/test_tuner > $B/tuner.log; } 2> $B/tuner.err ||
  fail "tuner: $(why tuner)"
UAF="-O1 -Wall -Wno-unused-function -Wno-int-to-pointer-cast -Ifirmware/apps/gamut/engine -Ifirmware -Ifirmware/bsp/chip"
{ $CC $UAF -DA_SR=48000u tests/test_usb_audio.c -lm -o $B/test_usb_audio && $B/test_usb_audio > $B/usb.log; } 2> $B/usb.err ||
  fail "USB audio: $(why usb)"
BAF="-O1 -Wall -Wno-unused-function -Wno-unused-variable -Wno-int-to-pointer-cast -Ifirmware"
{ $CC $BAF -DA_SR=48000u tests/test_base_audio.c firmware/px_math.c -lm -o $B/test_base_audio && $B/test_base_audio > $B/base.log; } 2> $B/base.err ||
  fail "base audio: $(why base)"
if [ -n "$NAM_CAPTURES" ]; then
  { $CC -O2 -DPXN_EMUVEC -Ifirmware/apps/gamut/engine firmware/apps/gamut/tests/engine/nam_test.c firmware/apps/gamut/engine/px_nam.c -o $B/nam_test &&
    python3 tests/rate48/amps.py "$NAM_CAPTURES" $B/nam_test > $B/amps.log; } 2> $B/amps.err
  grep FAIL $B/amps.log
  n=$(sed -n 's/^amps: \([0-9]*\) failures/\1/p' $B/amps.log)
  fails=$((fails + ${n:-1}))
fi
echo "failures: $fails"
