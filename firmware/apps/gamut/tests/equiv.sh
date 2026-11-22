#!/bin/sh
# OpenPocket: is this tree's engine bit-identical to commit REF's? (firmware/apps/gamut/tests/engine/equiv.c: 702 runs hashed)
#   firmware/apps/gamut/tests/equiv.sh REF        e.g. firmware/apps/gamut/tests/equiv.sh origin/openpocket-v40-ram-dsp
# Both engines are built as the pedal builds them: -fno-builtin (the pedal has no square-root instruction: px_math.c's
# sqrtf) and -ffp-contract=off (it does not fuse a multiply with an add), with firmware/px_math.c as the libm. A PC
# compiler left to itself does both, and its fused multiply-adds follow the shape of the code: two engines that are
# identical on the pedal can then differ on the PC in the last bit.
# Needs git and a C compiler; writes to build/equiv. Exit 0: identical.
set -e
cd "$(dirname "$0")/../../../.."
REF=${1:?usage: firmware/apps/gamut/tests/equiv.sh REF}
CC="${CC:-cc}"
B=build/equiv
rm -rf "$B/ref"
mkdir -p "$B/ref"
# REF's engine is where REF has it: engine/ before the primary firmware moved into its app folder
E=firmware/apps/gamut/engine; git cat-file -e "$REF:$E" 2>/dev/null || E=engine
git archive "$REF" "$E" firmware/px_math.c | tar -x -C "$B/ref"
$CC -O2 -w -fno-builtin -ffp-contract=off -I"$B/ref/$E" -o "$B/ref-run" firmware/apps/gamut/tests/engine/equiv.c "$B/ref/firmware/px_math.c" -lm
$CC -O2 -w -fno-builtin -ffp-contract=off -Ifirmware/apps/gamut/engine -o "$B/new-run" firmware/apps/gamut/tests/engine/equiv.c firmware/px_math.c -lm
"$B/ref-run" > "$B/ref.txt"
"$B/new-run" > "$B/new.txt"
if cmp -s "$B/ref.txt" "$B/new.txt"; then echo "equiv: identical to $REF, $(tail -1 "$B/new.txt")"; exit 0; fi
echo "equiv: DIFFERS from $REF"
diff "$B/ref.txt" "$B/new.txt" | head -8
exit 1
