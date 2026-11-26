#!/bin/sh
# A firmware's release pin: its image and packages must be the bytes of its pinned release, whatever changed in the base
# firmware or in another firmware (docs/BASE-FIRMWARE.md, section 9). firmware/apps/NAME/release.sha256 holds their
# SHA-256; a firmware with no such file has no pin (STARTER, the template, is never released).
#   tests/release_pin.sh NAME [SUMS]   compare SUMS with NAME's pin. The default SUMS is what the build wrote:
#                                      build/apps/NAME/SHA256SUMS (`tools/op.mjs package` for Gamut, gamut;
#                                      `tools/op.mjs app NAME` for another firmware)
# The same sums mean that nothing in that firmware needs a check on a pedal. To pin a new release of it, such as a merge
# of upstream's next OpenPocket or a change made on purpose once its own tests pass, copy the build's SHA256SUMS over
# its release.sha256 in the same commit. Gamut's pin (gamut) is upstream's published OpenPocket v42 with the bass tuner
# fix, trails, the editor watch fix, the flash hold fix, the built-in amps and cabinets removed and slot IR1's factory IR,
# its update loader refusing a flash head it does not know, its packages fitting both flash heads, renamed Gamut: the
# boot screen's name, the version text 1.0b1 and the identity 50 (PocketX_950, BlackBox_950), with the BlackBox
# package's app area also as a file of its own for M-VAVE's V22/V23 recovery mode (BlackBox_950-v23.bin), and its
# screen in its own palette (firmware/apps/gamut/ui_palette.h) and fonts (ui_fonts.h), in small letters, the factory
# presets' names too, USB MIDI messages stamped with the time they came in (firmware/px_usb.h), which PALETTE's pin
# also takes, the footswitch numbers CC 116, 118 and 119 (firmware/apps/gamut/px_midi_io.h), the second core's fault
# record with its registers and SP (firmware/bsp/chip/fm1_cpu1.h), and its layout: the chain along a line, the selected
# block's label beside the 58 px preset number, the tuner's 81 px note over a scale, footers of a control and what it
# does, the update's step dots, and its own screens for a start, a failed start's report, a crash and the rescue mode
# (firmware/apps/gamut/ui_boot.h), the MIDI page's USB PORT row, the pedal the USB MIDI host of a footswitch by cable
# (firmware/px_usb.h, firmware/px_usbhost.h), and cabinet IR slots at 44.1 or 48 kHz (version 2), an IR made at the
# engine's other rate resampled when it is loaded, slot IR1's factory IR at both rates, and the editor protocol 6's
# sample rate in INFO (firmware/apps/gamut/px_irs.h, engine/px_dsp.c, px_editor.h), and its factory amps the A2-Lite
# parts of twelve NAM captures from TONE3000 with the factory presets rebuilt round them (engine/px_nam_factory.h,
# tools/nam_factory.txt, engine/px_dsp.c), and its sound at 48 kHz: the engine built for it, the I2S moved there through
# base/rate.h's guard without a write to PLL0, else 44.1 kHz without USB audio, USB audio at 48 kHz, and DIAG's clock
# line (firmware/apps/gamut/openpocket.c OP_RATE48, firmware/build.sh, firmware/px_uaconf.h). The pin before it, at
# 44.1 kHz, is in the changelog: the changeset gamut-48k-default.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="$1"
case "$NAME" in ""|*[!a-z0-9-]*) echo "usage: tests/release_pin.sh NAME [SUMS]   (NAME: a folder of firmware/apps)"; exit 2;; esac
PIN="$ROOT/firmware/apps/$NAME/release.sha256"
if [ ! -f "$PIN" ]; then echo "release pin: $NAME has no pin (firmware/apps/$NAME/release.sha256)"; exit 1; fi
if [ "$NAME" = gamut ]; then BUILD=package; else BUILD="app $NAME"; fi
SUMS="${2:-$ROOT/build/apps/$NAME/SHA256SUMS}"
if [ ! -f "$SUMS" ]; then echo "release pin: $SUMS not found (run: node tools/op.mjs $BUILD)"; exit 1; fi
if diff -u "$PIN" "$SUMS"; then
  echo "release pin: $NAME's image and packages are the release's, byte for byte ($(wc -l < "$SUMS" | tr -d ' ') files)"
else
  echo "release pin: FAILED. $NAME's image or packages changed (lines with + above are this build's)."
  echo "  A change to the base firmware or to another firmware must leave them the same: find what changed $NAME's code."
  echo "  A new release of $NAME is pinned on purpose: see the head of tests/release_pin.sh."
  exit 1
fi
