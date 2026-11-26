#!/bin/sh
# The engine as WebAssembly, for the simulated pedal's sound, built for 48 kHz (px_dsp.h PX_FS; tools/sim/px-engine.js
# ENGINE_RATE): tools/sim/px_engine.wasm and, next to it, the SHA-256 of the sources it was built from
# (tests/test_audio.mjs fails when they differ). In the container: tools/op.mjs wasm.
set -e
cd "$(dirname "$0")/../../../.."
SRC="firmware/apps/gamut/engine/px_wasm.c firmware/apps/gamut/engine/px_dsp.c firmware/px_math.c"
O=build/wasm; mkdir -p "$O"
for f in $SRC; do
  clang --target=wasm32 -O2 -fno-builtin -ffp-contract=off -nostdlibinc -DPX_FS=48000 -Ifirmware/apps/gamut/engine -Ifirmware/inc -Wall -Wno-unused-function -c "$f" -o "$O/$(basename "$f" .c).o"
done
wasm-ld --no-entry --strip-all -z stack-size=65536 "$O"/*.o -o tools/sim/px_engine.wasm
cat $SRC firmware/apps/gamut/engine/px_dsp.h firmware/apps/gamut/engine/px_trim.h firmware/apps/gamut/engine/px_nam.c firmware/apps/gamut/engine/px_nam.h firmware/apps/gamut/engine/px_nam_factory.h firmware/apps/gamut/engine/px_ir_factory.h | sha256sum | cut -d' ' -f1 > tools/sim/px_engine.wasm.sources
chmod 644 tools/sim/px_engine.wasm
ls -l tools/sim/px_engine.wasm
