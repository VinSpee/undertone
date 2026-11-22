#!/bin/sh
# PALETTE's own host tests (run by tests/run_tests.sh; alone: sh firmware/apps/palette/tests/run.sh):
#  - PALETTE (firmware/apps/palette, docs/PALETTE.md): its engine's own code with the firmware's math library, under the
#    sanitizers (every effect at its knobs' ends, changes without a step, bypass, the tempo); each effect on the standard
#    signal (firmware/apps/palette/tests/palette_render.c); the app in the hosted simulator (controls, MIDI map, editor requests, store)
set -e
cd "$(dirname "$0")/../../../.."
mkdir -p build
CC="${CC:-cc}"
. tests/lib.sh
echo "== PALETTE's engine (firmware/apps/palette/engine.c: twenty effects in four modules, changes without a step)"
base_test test_palette $CC -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all -Wall -Ifirmware/apps/palette firmware/apps/palette/tests/test_palette.c firmware/apps/palette/engine.c firmware/px_math.c -lm
$CC -O2 -Wall -Ifirmware/apps/palette -o build/palette_render firmware/apps/palette/tests/palette_render.c firmware/apps/palette/engine.c firmware/px_math.c -lm
build/palette_render --runs 1 > build/palette_render.log || { cat build/palette_render.log; exit 1; }; echo "palette render: each effect on the standard signal is finite, under full scale and not silent (build/palette_render.log)"
echo "== PALETTE in the simulator (firmware/apps/palette, from its own C files)"
node firmware/apps/palette/tests/test_palette_sim.mjs
