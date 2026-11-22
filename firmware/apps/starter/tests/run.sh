#!/bin/sh
# STARTER's own host tests (run by tests/run_tests.sh; alone: sh firmware/apps/starter/tests/run.sh):
#  - an app in the hosted simulator: firmware/apps/starter's own C files with tests/host as the chip, over the same HTTP
#    interface: its controls, its sound at the two outputs, MIDI, its store, safe mode, the boot guard
set -e
cd "$(dirname "$0")/../../../.."
mkdir -p build
CC="${CC:-cc}"
. tests/lib.sh
echo "== an app on the base firmware in the simulator (firmware/apps/starter, from its own C files: tools/sim.mjs --app)"
node firmware/apps/starter/tests/test_app_sim.mjs
