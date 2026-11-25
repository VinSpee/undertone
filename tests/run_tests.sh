#!/bin/sh
# OpenPocket host tests (Linux / macOS, or in the container: tools/op.mjs test; no pedal, no JieLi toolchain needed):
#   tests/run_tests.sh [PocketX_016.fwsc]
#  (each firmware's own tests are in firmware/apps/<name>/tests/run.sh, which this script runs after the shared ones)
#  - the audio callbacks' order (v42, firmware/px_aorder.h): the I2S driver calls the output's callback before the
#    input's when its interrupt enters late; every output block must still be the sound of that interrupt's guitar block
#  - tuner (firmware/px_tuner.h): bass and guitar notes, sine and plucked, in tune and off it, read every 100 ms: the
#    note and its octave, within 2 cents from a five-string bass's low B (31 Hz) to the high E string
#  - base audio (firmware/base/audio.h, audio_plain.h): the audio stages every app shares, for a mono and for a stereo
#    app: the guitar through an app's sound to the output channels, MASTER, the mutes, the fades, the soft knee, the
#    load's bypass
#  - the I2S clock's test builds (firmware/base/rate.h): the 44.1 kHz report writes no clock register; the 48 kHz build
#    leaves the registers the driver's own 48 kHz case leaves without writing PLL0, and stays at 44.1 kHz when PLL0's bit
#    25 is clear or the start is a safe-mode one; both measure the rate of the guitar's blocks across TIMER4's wrap
#  - base controls (firmware/base/input.h): each button's pins and the keypad's voltages to its event, the debounce, a
#    hold and its release, two buttons together, the encoder's detents, the MASTER knob
#  - base store (firmware/base/store.h): save / reload, a power cut at every step of a save, nothing written outside its
#    ten sectors, no sector ending like an update record whatever the app saves
#  - USB audio (v42): the USB device code and the audio glue (bsp/chip/usb.c, firmware/px_uaudio.h) against a model of
#    the controller and a computer: with the setting off the descriptors are the earlier device's byte for byte; with
#    it on, the descriptors, the requests, 10 minutes of each stream with the clocks apart (no gap, no repeat)
#    and the MIDI input ring with an app's reader of it (firmware/base/midi.h): unread, it blocks the installer's SysEx
#  - USB footswitch by cable (the pedal its USB MIDI host): felucca-bsp's descriptor parser on the M-VAVE Chocolate's
#    layout, the packets passed, the screen's state (firmware/px_usbhost.h), the host's clock across TIMER4's wrap
#  - LED map + lights driver (led_probe.h, px_leds.h): PC7 enable after the first byte, the 595 timing, the table
#  - package reader: tools/pocketx_fw.py on packages built to the old (0x4000) and the V22 (0x6000) layout: info, unpack, pack
#  - packages: tools/pxpkg.py rebuilds the official PocketX_016 app area byte for byte (needs the official file)
#  - both flash heads: each package's app area placed at 0x4000 and at 0x6000 (BlackBox V22 and later) passes every
#    check of the area and ends below that head's stock settings (tests/test_both_heads.py; synthetic heads, and the
#    official file's head when given)
#  - catalog: tools/catalog.py, the list of firmwares the installer page offers (release.json), from the manifests and
#    packages a build made. With OP_BUILT=1 also the catalog the build wrote: every firmware of firmware/catalog.json
#  - installer: docs/pxota.js + docs/pxpkg.js against a simulated pedal running the real update code (ota.c, ldr_core.c)
#  - flasher: tools/flash.mjs (node tools/op.mjs flash) against the same simulated pedal: update, dry run, wrong model, damaged package, rescue of a pedal that restarts in a loop
#  - products: an alternative firmware (an app on the base firmware) on the same simulated pedal: what it says it is, the
#    flasher's --app guard, the install, the way back to OpenPocket (also by rescue), what the flash keeps through both.
#    With OP_BUILT=1 (node tools/op.mjs all) also with the packages the build made: each product's image byte for byte
#  - release files: .github/scripts/assets.mjs assembles a release from fixture packages; site/latest.py and site/release.sh
#    take it from a stand-in GitHub; .github/scripts/release.mjs --draft with a stand-in gh (tests/test_release_files.mjs)
#  - rescue: tools/uboot_rescue.py (protocol, guards, resume) against a simulated UBOOT pedal, tests/uboot_sim.py
#  - recovery helper: tools/pd40_recovery.py (probe, bus watch and departure times, leave and its control-endpoint gate,
#    refusal of every write, bad answers) against a simulated pedal in M-VAVE's V22/V23 recovery mode that sends zeros
#    after a sync and leaves at one failed access or on its own, tests/recovery_sim.py
#  - recovery-mode check: tools/pd40_install.py (dry run, the pedal's own check of Gamut's app area and of M-VAVE's,
#    which writes nothing; refusals, the pedal leaving; the replies over bulk IN and, with --accept-control-reply, over
#    the control endpoint when bulk IN sends zeros; --write refused with nothing sent) against the same simulated
#    recovery mode on a simulated V23 flash (tests/test_pd40_install.py)
#  - install through the USB boot state: tools/uboot_install.py (the dry run, Gamut's app area installed and M-VAVE's
#    or a backup's put back, on the old head at 0x4000 and on the V22/V23 head at 0x6000; another app area of this
#    project, such as a test build's, after a typed yes; the leave from the recovery mode; an unknown head, an app area
#    for the other layout, an image that is not one of this project's app areas, another chip or flash refused before
#    any erase; the resume) against one simulated pedal that is in the recovery mode, in the USB boot state, or off the
#    bus (tests/test_uboot_install.py)
#  - undertone: tools/undertone.py's rescue, install and check on the simulated pedals, each write only after a typed yes;
#    its guided screens (tools/undertone_screens.py) as a state machine, their keys and frames, and the guided rescue
#    driven by key presses (tests/test_undertone.py)
#  - rescue kit: rescue/build_kit.py gives the pinned bytes twice; an unzipped kit's own files restore a simulated pedal
#    on a V20, a V22 and a V23 flash head, and refuse the file of the other head (tests/test_rescue_kit.py)
#  - hosted simulator: tools/sim.mjs driven over HTTP (controls, held buttons, screen, flash file, SysEx, the Web MIDI shim)
#  - pedal skin: its input mapping (tools/sim/pedal-input.js)
#  - sound: the WebAssembly engine on known signals, against the native build; the bundled loops against their manifest
#  - Chocolate Plus files: tools/chocolate/fcp.py against a made-up export
#  - Bluetooth library fold: tools/jlfold.py reads ble_cfg.c and ble_stubs.c and folds a sample of the members' IR
#  - editor: docs/pxedit.js against the simulated pedal (tests/edsim.c), PING's figures, and the editor's own logic
#    (docs/pxmidi.js: the Control Change map against docs/MIDI.md, learned controls; docs/pxble.js and docs/pxchoc.js:
#    Bluetooth MIDI packets and a Chocolate's controls; docs/pxlib.js: the model library)
#  - pages: docs/install.html, docs/editor.html and the pedal skin in headless Chromium (needs Playwright: npm i playwright
#    && npx playwright install chromium)
set -e
cd "$(dirname "$0")/.."
mkdir -p build
CC="${CC:-cc}"
. tests/lib.sh
echo "== audio callbacks' order (the output block is its interrupt's, whichever callback the driver calls first)"
$CC -O1 -Wall -Ifirmware tests/test_aorder.c -o build/test_aorder && build/test_aorder | tail -1
echo "== tuner (bass and guitar notes through the pedal's capture and estimate)"
$CC -O1 -Wall -Ifirmware tests/test_tuner.c -lm -o build/test_tuner && build/test_tuner | tail -1
echo "== base audio (the stages every app shares, under the plain schedule: firmware/base/audio.h, audio_plain.h)"
BAF="-O1 -Wall -Wno-unused-function -Wno-unused-variable -Wno-int-to-pointer-cast -Ifirmware"
base_test test_base_audio $CC $BAF tests/test_base_audio.c firmware/px_math.c -lm
base_test test_base_audio2 $CC $BAF -DA_CH=2 tests/test_base_audio.c firmware/px_math.c -lm   # an app with a stereo sound
echo "== the I2S clock's test builds (firmware/base/rate.h: the report writes no clock register; 48 kHz never writes PLL0)"
base_test test_rate_diag $CC $BAF -DOP_RATE_DIAG=1 tests/test_rate.c
base_test test_rate48 $CC $BAF -DOP_RATE48=1 tests/test_rate.c
echo "== base controls (firmware/base/input.h over base/controls.h: the pins and the ADC to an app's events)"
base_test test_base_input $CC -O1 -Wall -Wno-unused-function -Wno-unused-variable -Itests/host -Ifirmware tests/test_base_input.c
echo "== base store (firmware/base/store.h: an app's own data in flash, kept by every update loader)"
base_test test_base_store $CC -O1 -Wall -Wno-unused-function -Ifirmware tests/test_base_store.c
echo "== USB audio (the device code and the audio glue against a model of the controller and a computer)"
UAF="-O1 -Wall -Wno-unused-function -Wno-int-to-pointer-cast -Ifirmware/apps/gamut/engine -Ifirmware -Ifirmware/bsp/chip"
$CC $UAF tests/test_usb_audio.c -lm -o build/test_usb_audio
$CC $UAF -DT_REF tests/test_usb_audio.c -lm -o build/test_usb_audio_ref      # the USB device as it was before v42
build/test_usb_audio desc > build/usb_desc_off.txt
build/test_usb_audio_ref > build/usb_desc_ref.txt
if cmp -s build/usb_desc_off.txt build/usb_desc_ref.txt; then echo "USB AUDIO off: the descriptors are the earlier device's, byte for byte"
else echo "USB AUDIO off: the descriptors differ from the earlier device's"; diff build/usb_desc_ref.txt build/usb_desc_off.txt; exit 1; fi
build/test_usb_audio > build/usb_audio.log || { cat build/usb_audio.log; exit 1; }
tail -1 build/usb_audio.log
echo "== USB footswitch by cable (the descriptor parser on the Chocolate's layout, the packets passed, the screen's state, the host's clock)"
base_test test_usb_host $CC -O1 -Wall -Wno-unused-function -Ifirmware tests/test_usb_host.c
echo "== LED map and the lights driver (LED_PROBE build, issue #8)"
mkdir -p build/lp && $CC -O1 -Wall -Wno-unused-function -Ifirmware -o build/lpsim tests/lpsim.c && build/lpsim build/lp
echo "== simulated pedal"
$CC -O1 -Wall -Wno-unused-function -o build/devsim tests/devsim.c
if [ -n "$1" ]; then echo "== packages"; python3 tests/test_pxpkg.py "$1"; fi
echo "== package reader (tools/pocketx_fw.py: the app area where the flash head names it, 0x4000 or 0x6000)"
python3 tests/test_pocketx_fw.py $1 | tail -1
echo "== packages of two products (tools/pxpkg.py: an app's product descriptor, its packages' names, the manifest)"
python3 tests/test_pxpkg_app.py > build/pxpkg_app.log || { cat build/pxpkg_app.log; exit 1; }; tail -1 build/pxpkg_app.log
echo "== one package on both flash heads (its app area at 0x4000 and at 0x6000, below each head's stock settings)"
python3 tests/test_both_heads.py ${OP_BUILT:+--built} $1 > build/both_heads.log || { cat build/both_heads.log; exit 1; }; tail -1 build/both_heads.log
echo "== catalog (tools/catalog.py: the firmwares a site offers, from what the build made)"
python3 tests/test_catalog.py ${OP_BUILT:+--built} > build/catalog.log || { cat build/catalog.log; exit 1; }; tail -1 build/catalog.log
echo "== installer"
node tests/test_installer.mjs "$1"
echo "== flasher (tools/flash.mjs)"
node tests/test_flash.mjs
echo "== two products from one base (an alternative firmware installed, told from OpenPocket, and OpenPocket put back)"
node tests/test_products.mjs ${OP_BUILT:+--built}
echo "== build entry point (tools/op.mjs)"
node tests/test_op.mjs
echo "== release pin (tests/release_pin.sh: the same sums pass, one changed byte's sum fails)"
for pin in firmware/apps/*/release.sha256; do
  n=$(basename "$(dirname "$pin")")
  sh tests/release_pin.sh "$n" "$pin" > /dev/null || { echo "release pin: $n refuses its own sums"; exit 1; }
  sed '1s/^./0/;1s/^00/01/' "$pin" > build/release_pin_wrong.sums
  if sh tests/release_pin.sh "$n" build/release_pin_wrong.sums > /dev/null 2>&1; then echo "release pin: $n accepts a changed image"; exit 1; fi
  if sh tests/release_pin.sh "$n" build/no-such.sums > /dev/null 2>&1; then echo "release pin: $n accepts a missing build"; exit 1; fi
done
if sh tests/release_pin.sh starter > /dev/null 2>&1; then echo "release pin: accepts a firmware with no pin"; exit 1; fi
echo "release pin: ok ($(ls firmware/apps/*/release.sha256 | wc -l | tr -d ' ') pinned firmwares)"
echo "== release files (.github/scripts/assets.mjs, release.mjs --draft: the assets, site.sha256 through the site's own steps)"
node tests/test_release_files.mjs > build/release_files.log || { cat build/release_files.log; exit 1; }; tail -1 build/release_files.log
echo "== rescue tool (tools/uboot_rescue.py on a simulated UBOOT pedal)"
python3 tests/test_uboot_rescue.py $1
echo "== recovery helper (tools/pd40_recovery.py on a simulated V22/V23 recovery mode)"
python3 tests/test_pd40_recovery.py
echo "== recovery-mode check (tools/pd40_install.py: the pedal's own check of an app area, on a simulated V23 pedal; no write)"
python3 tests/test_pd40_install.py ${OP_BUILT:+--built}
echo "== install through the USB boot state (tools/uboot_install.py: Gamut and the way back, on a simulated pedal of each flash layout)"
python3 tests/test_uboot_install.py ${OP_BUILT:+--built}
echo "== undertone (tools/undertone.py and its guided screens: rescue, install and check on simulated pedals, keys, frames)"
python3 tests/test_undertone.py
echo "== rescue kit (rescue/build_kit.py: the pinned bytes; the unzipped kit on a simulated V20, V22 and V23 pedal)"
python3 tests/test_rescue_kit.py
echo "== hosted simulator (tools/sim.mjs)"
node tests/test_sim.mjs
echo "== Chocolate Plus files (tools/chocolate/fcp.py)"
python3 tests/test_fcp.py
echo "== Bluetooth library fold (tools/jlfold.py)"
python3 tests/test_jlfold.py
echo "== pedal skin input"
node tests/test_pedal_input.mjs
echo "== simulated sound"
node tests/test_audio.mjs
echo "== editor"
$CC -O1 -Wall -Wno-unused-function -o build/edsim tests/edsim.c firmware/apps/gamut/engine/px_dsp.c firmware/px_math.c -lm
node tests/test_editor.mjs
node tests/test_ping.mjs
node tests/test_editor_logic.mjs
echo "== log channel (tools/op.mjs log)"
$CC -O1 -Wall -Wno-unused-function -DOP_BLE_TEST=1 -o build/edsim_diag tests/edsim.c firmware/apps/gamut/engine/px_dsp.c firmware/px_math.c -lm
node tests/test_log.mjs
# each firmware's own tests (firmware/apps/<name>/tests/run.sh), with this script's arguments
for t in firmware/apps/*/tests/run.sh; do echo "==== $(basename "$(dirname "$(dirname "$t")")")"; sh "$t" "$@"; done
if node -e "require('playwright')" 2>/dev/null; then echo "== page"; node tests/test_page.mjs build/page; echo "== editor page"; node tests/test_editor_page.mjs build/editor; echo "== pedal skin"; node tests/test_pedal_page.mjs build/pedal; echo "== pedal sound"; node tests/test_audio_page.mjs build/audio; else echo "(Playwright not installed: page tests skipped)"; fi
