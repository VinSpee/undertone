#!/bin/sh
# OpenPocket's own host tests (run by tests/run_tests.sh; alone: sh firmware/apps/gamut/tests/run.sh):
#  - engine: every block x model x extreme knob, signal / silence / overload, with the pedal's own libm (px_math.c):
#    no NaN; long runs (3 s pluck + 8 s silence): nothing runs away (only delays at FDBK 100 hold on, by design)
#  - the two-core pipeline (PRE / NAM / POST stages) gives the plain engine's output one block later
#  - NAM hand routines: their start-up check and dispatch with C stand-ins under the sanitizers; post5's assembly text
#    against the C post through a model of its instructions (firmware/apps/gamut/tests/test_post5.py)
#  - (not run here, it needs the git history: firmware/apps/gamut/tests/equiv.sh REF, this tree's engine against commit REF's, bit for bit)
#  - changes without clicks (v38): knob changes glide to exactly where a full set goes, blocks on / off fade, fewer clicks
#  - USER IR (v38): the partitioned FFT convolution against the direct FIR, slots, names
#  - wet lanes (v39): the delay through its lane as inline bit for bit, the reverb's tail lag frames later, the pipeline
#  - trails: after px_engine_switch the outgoing delay and reverb are their own tails, sample for sample, on every type;
#    they end; the stretches of the delay memory never overlap through changes at random (under the sanitizers)
#  - the engine built for 44.1 kHz (px_dsp.h PX_FS 44100, the rate-diag test build's): the sweep (no NaN) and the trails in
#    its memory
#  - NAM: firmware/apps/gamut/engine/px_nam.c against tools/nam_a2.py with every factory model, at GAIN noon and +12 dB
#    (needs numpy)
#  - factory preset levels: each within 0.5 LU of -23 LUFS on docs/nam_di.wav (tools/level_presets.py --check; needs scipy)
#  - MIDI: the musical-MIDI code (firmware/apps/gamut/px_midi.h) on a PC: decoder, CC map, messages sent, settings byte, clock
#  - preset store: save / reload / power cut at every step of a save (firmware/apps/gamut/px_store.h on a simulated flash)
#  - flash hold (firmware/apps/gamut/px_store.h, px_models.h, px_irs.h): every erase, program and SPI read of a save or an erase
#    of a preset, a NAM model or an IR falls inside the audio hold (formal/FINDINGS.md, F1)
#  - button lights (px_lights.h): each block lights its button, FX for its group, HOME blinks in the tuner
#  - the Bluetooth test image: its sources (third_party/jieli-ble), its status codes, the VM item log reader, and its
#    timers (ble/ble_os.c: across TIMER4's wrap, the interrupts as found, the usr timeouts on the 10 kHz tick)
set -e
cd "$(dirname "$0")/../../../.."
mkdir -p build
CC="${CC:-cc}"
. tests/lib.sh
echo "== engine"
$CC -O2 -Ifirmware/apps/gamut/engine firmware/apps/gamut/tests/engine/sweep2.c firmware/apps/gamut/engine/px_dsp.c firmware/px_math.c -lm -o build/sweep && build/sweep | tail -1
$CC -O2 -Ifirmware/apps/gamut/engine firmware/apps/gamut/tests/engine/long.c firmware/apps/gamut/engine/px_dsp.c firmware/px_math.c -lm -o build/long && build/long | tail -1
$CC -O2 -Ifirmware/apps/gamut/engine firmware/apps/gamut/tests/engine/pipe_test.c firmware/apps/gamut/engine/px_dsp.c firmware/px_math.c -lm -o build/pipe_test && build/pipe_test | tail -1
# v40.2: the network split between the cores by layers, against one core and through the pipeline
$CC -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all -DPXN_EMUVEC -Ifirmware/apps/gamut/engine firmware/apps/gamut/tests/engine/lp_test.c firmware/px_math.c -lm -o build/lp_test && build/lp_test | tail -1
# v40.5: CPU0's waits for a second core that never moves end after the limit (a stuck CPU1: LATE, not the watchdog)
$CC -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all -Ifirmware/apps/gamut/engine firmware/apps/gamut/tests/engine/lp_stuck.c firmware/px_math.c -lm -o build/lp_stuck && build/lp_stuck | tail -1
# v40.2: the NAM hand routines' start-up check, timing and dispatch, with C stand-ins under the sanitizers (a fault there
# would be a boot loop on the pedal)
$CC -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all -DPXN_HAND=1 -Ifirmware/apps/gamut/engine firmware/apps/gamut/tests/engine/hand_test.c firmware/px_math.c -lm -o build/hand_test && build/hand_test | tail -1
$CC -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all -DPXN_HAND=1 -DPXN_LEAN=1 -Ifirmware/apps/gamut/engine firmware/apps/gamut/tests/engine/hand_test.c firmware/px_math.c -lm -o build/hand_test_lean && build/hand_test_lean | tail -1   # (the Bluetooth image's)
# v40.5: post5's assembly text itself, run by a model of its instructions against the C post (firmware/apps/gamut/tests/test_post5.py), and
# the same with one offset changed, which must fail
python3 firmware/apps/gamut/tests/test_post5.py
if python3 firmware/apps/gamut/tests/test_post5.py "r6 = [sp+40]" "r6 = [sp+44]" > /dev/null 2>&1; then echo "test_post5 accepts a wrong routine"; exit 1; fi
$CC -O2 -Ifirmware/apps/gamut/engine -Ifirmware firmware/apps/gamut/tests/engine/change_test.c firmware/px_math.c -lm -o build/change_test && build/change_test | tail -1
$CC -O2 -Ifirmware/apps/gamut/engine -Ifirmware firmware/apps/gamut/tests/engine/ir_test.c firmware/px_math.c -lm -o build/ir_test && build/ir_test | tail -1
$CC -O2 -Ifirmware/apps/gamut/engine firmware/apps/gamut/tests/engine/wet_test.c firmware/apps/gamut/engine/px_dsp.c firmware/px_math.c -lm -o build/wet_test && build/wet_test | tail -1
$CC -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all -Ifirmware/apps/gamut/engine -Ifirmware firmware/apps/gamut/tests/engine/trail_test.c firmware/px_math.c -lm -o build/trail_test && build/trail_test | tail -1
# the engine built for 44.1 kHz (px_dsp.h PX_FS 44100: its memory and its counts of samples, the rate-diag test build's):
# the sweep at 44.1 kHz; the trails in its delay memory and its reverb ring, a power of two. (The tests above build the
# engine for 48 kHz, the release's: a reverb ring that is not a power of two)
base_test sweep44 $CC -O2 -DPX_FS=44100 -Ifirmware/apps/gamut/engine firmware/apps/gamut/tests/engine/sweep2.c firmware/apps/gamut/engine/px_dsp.c firmware/px_math.c -lm
base_test trail_test44 $CC -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all -DPX_FS=44100 -Ifirmware/apps/gamut/engine -Ifirmware firmware/apps/gamut/tests/engine/trail_test.c firmware/px_math.c -lm
echo "== NAM (fixed point against the float reference, every factory model)"
$CC -O2 -DPXN_EMUVEC -Ifirmware/apps/gamut/engine firmware/apps/gamut/tests/engine/nam_test.c firmware/apps/gamut/engine/px_nam.c -o build/nam_test
if python3 -c "import numpy" 2>/dev/null; then mkdir -p build/nam; python3 firmware/apps/gamut/tests/test_nam.py build/nam_test > build/nam/log.txt || { cat build/nam/log.txt; exit 1; }; tail -1 build/nam/log.txt; else echo "(numpy not installed: NAM comparison skipped)"; fi
echo "== factory preset levels (tools/level_presets.py --check)"
if python3 -c "import numpy, scipy" 2>/dev/null; then python3 tools/level_presets.py --check docs/nam_di.wav > build/levels.log || { cat build/levels.log; exit 1; }; tail -1 build/levels.log; else echo "(numpy or scipy not installed: preset levels skipped)"; fi
echo "== preset store"
$CC -O1 -Ifirmware/apps/gamut/engine firmware/apps/gamut/tests/test_store.c firmware/apps/gamut/engine/px_dsp.c firmware/px_math.c -lm -o build/test_store && build/test_store | tail -2
echo "== flash hold (every flash access of a save or an erase with the audio held and the second core collected)"
base_test test_flash_hold $CC -O1 -Wall -Wno-unused-function -Ifirmware/apps/gamut/engine firmware/apps/gamut/tests/test_flash_hold.c firmware/apps/gamut/engine/px_dsp.c firmware/px_math.c -lm
echo "== screen (every page fully drawn)"
mkdir -p build/ui && $CC -O1 -Wall -Wno-unused-function -Ifirmware/apps/gamut/engine -Ifirmware -o build/uisim firmware/apps/gamut/tests/uisim.c firmware/apps/gamut/engine/px_dsp.c firmware/px_math.c -lm
build/uisim build/ui > build/ui/log.txt
if grep -q "never drawn" build/ui/log.txt; then grep "never drawn" build/ui/log.txt; echo "screen: FAIL"; exit 1; else echo "screen: $(wc -l < build/ui/log.txt) pages ok (build/ui/*.ppm)"; fi
echo "== MIDI (firmware/apps/gamut/px_midi.h: decoder, Control Change map, what the pedal sends, settings, clock)"
for t in midisim midiio; do
  $CC -O1 -Wall -Wno-unused-function -Ifirmware/apps/gamut/engine -Ifirmware -o build/$t firmware/apps/gamut/tests/$t.c firmware/apps/gamut/engine/px_dsp.c firmware/px_math.c -lm
  build/$t > build/$t.log || { grep FAIL build/$t.log; exit 1; }
  tail -1 build/$t.log
done
echo "== button lights in the normal firmware (px_lights.h, issue #8)"
$CC -O1 -Wall -Wno-unused-function -Ifirmware/apps/gamut/engine -Ifirmware -o build/lightsim firmware/apps/gamut/tests/lightsim.c
build/lightsim > build/lightsim.log || { cat build/lightsim.log; exit 1; }; tail -1 build/lightsim.log
echo "== Bluetooth test image sources (third_party/jieli-ble)"
node firmware/apps/gamut/tests/test_ble_sources.mjs
echo "== Bluetooth test image status codes"
$CC -O1 -Wall -Wno-unused-function -o build/ble_status firmware/apps/gamut/tests/test_ble_status.c && build/ble_status
$CC -O1 -Wall -Wno-unused-function -o build/ble_vm firmware/apps/gamut/tests/test_ble_vm.c && build/ble_vm
echo "== Bluetooth test image timers (ble/ble_os.c)"
$CC -O1 -Wall -Wno-unused-function -Ifirmware/apps/gamut/tests/ble_shim -Ifirmware/apps/gamut/ble -o build/ble_timers firmware/apps/gamut/tests/test_ble_timers.c && build/ble_timers
