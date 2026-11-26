# The 48 kHz gates: two test builds

Two test builds of Gamut decide whether its sound can run at 48 kHz on a pedal. Neither is a release, and the installer
offers them only through `?channel=rate-diag` and `?channel=rate48`. Nothing here was tried on a pedal yet.

- **rate-diag** (`OP_RATE_DIAG`) runs at 44.1 kHz, as the release does: the driver sets the clock exactly as in the
  release. It reads the clock registers, writes none of them itself, and measures the real sample rate.
- **rate48** (`OP_RATE48`) runs the I2S at 48 kHz only when its guard allows it. Otherwise it runs at 44.1 kHz and says
  why.

The code is `firmware/base/rate.h`. `tests/test_rate.c` runs it on a PC against a model of the I2S driver's register
writes.

## What the builds do

The JieLi driver's 48 kHz case (`sdk/iis.bc`, `iis_set_sample_rate` for ALNK0) differs from its 44.1 kHz case in two
writes:

- It ORs bit 25 into `0x119A4`, PLL0's second control register. That PLL probably also clocks USB.
- It sets bit 8 of `0x10014`. The 44.1 kHz case clears that bit.

Both cases write the same divider byte and clear bit 9 of `0x10014`. The rate48 build therefore calls the driver's
44.1 kHz case and then sets bit 8 itself. It never writes PLL0. Its guard allows 48 kHz only when both are true:

- Bit 25 of `0x119A4` is already set at the start, so the 48 kHz family's source is already on.
- The start is not a safe-mode start. A start after a failed one always runs at 44.1 kHz.

At 48 kHz the rate48 build also gives the engine, the tuner, the block budget and the load figures the 48 kHz rate. Its
engine is built for 48 kHz (`PX_FS` in `firmware/apps/gamut/engine/px_dsp.h`): its memory holds the 2 s delay, and its
effects sound as they do at 44.1 kHz (`sh tests/rate48/score.sh` compares them). Its cabinet IRs play at 48 kHz: the
factory IR from its 48 kHz table, and an IR of the user's made at 44.1 kHz resampled when a preset loads it. It has no
USB audio, because USB audio's rate is fixed when the firmware is built and this build picks its rate at the start; USB
MIDI, the editor and the installer work as usual. Known differences at 48 kHz, which are expected and not part of this
test:

- The NAM amps sound brighter.
- The bitcrusher's SR DIV divides 48 kHz, so its reduced rate is 9 % higher.

When the build stays at 44.1 kHz, its pitch effects and synths sound slightly different from the release's, because
their windows are set for 48 kHz.

Both builds answer the editor protocol's `DIAG` with one line, which `node tools/op.mjs log` reads and explains. It
shows the rate asked for and the rate in use, the guard, and the rate measured over the last 10 s from the guitar's
blocks against the 24 MHz timer. It also shows the clock registers now and as they were before the rate was set:

- PLL0: `0x119A0` and `0x119A4`
- PLL1: `0x119A8` and `0x119AC`
- `0x10008`, `0x1000C` and `0x10014`
- ALNK0's divider byte, `0x12E0C`

## Steps on the pedal

Flash only one pedal, and only with the owner's go-ahead. On a Pocket X, or a BlackBox on M-VAVE V21 or older, use the
flasher, as below. On a BlackBox that ever ran M-VAVE V22 or V23 the flasher refuses, because its write would overwrite
the end of that boot loader: use [the USB boot state](#on-a-blackbox-with-m-vave-v22-or-v23) instead. Close the
browser installer and any other MIDI program first.

### Once

```
npm ci --prefix tools
node tools/op.mjs package-test rate-diag
node tools/op.mjs package-test rate48
node tools/op.mjs package
```

The last command builds the release again, for the way back. Each command prints the SHA-256 of what it built, the
BlackBox app area `BlackBox_942-v23.bin` included.

### Gate A: the clock report at 44.1 kHz

```
node tools/op.mjs flash --dry-run --manifest build/apps/gamut/rate-diag/manifest.json
```

The dry run writes nothing. It must print `dry run ok: would update PocketX_950 (...) -> PocketX_942 (Gamut)`,
or the same with `BlackBox`. Then:

```
node tools/op.mjs flash --confirm-flash --manifest build/apps/gamut/rate-diag/manifest.json
node tools/op.mjs log --wait 30
node tools/op.mjs log --wait 30 --json > rate-diag.json
```

The boot screen's version line names the build: `v42 RATE DIAG`. Play a little: the sound must be the release's.

The `log` verdict PASS means the rate was measured within 0.5 % of 44.1 kHz; about 44,117.6 Hz is expected. The verdict
also says whether bit 25 of `0x119A4` is set. If it is clear, the rate48 build stays at 44.1 kHz, so Gate B cannot pass:
stop and send `rate-diag.json`.

### Gate B: the guarded 48 kHz build

Run Gate B only after Gate A has passed.

```
node tools/op.mjs flash --dry-run --manifest build/apps/gamut/rate48/manifest.json
node tools/op.mjs flash --confirm-flash --manifest build/apps/gamut/rate48/manifest.json
node tools/op.mjs log --wait 30
node tools/op.mjs log --wait 30 --json > rate48.json
```

The boot screen's version line names the build: `v42 RATE48`. The gate passes when all of the following are true:

- The `log` verdict is PASS: guard PASS, and a rate within 0.5 % of 48 kHz.
- The pedal did not start in safe mode.
- Effect-only presets sound clean, without crackle, noise or a dead output. Try a drive, a modulation, a delay and a
  reverb with the AMP and CAB blocks off.
- The status corner's DSP load is about 1.09 times the release's on the same preset, for example 61 % where the
  release shows 56 %.

Send `rate48.json` and what you heard.

If Gate B fails, the possible results are these:

- **Verdict FAIL with the rate.** The 48 kHz family runs at another rate. The measured rate is the finding.
- **No sound, but the pedal answers.** The 48 kHz clock does not run. USB works, so go back to the release.
- **The pedal crashes once.** The next start is in safe mode, which runs at 44.1 kHz. `log` then says SAFE. Go back to
  the release.
- **A restart loop.** Run `node tools/op.mjs flash --rescue --confirm-flash` (`docs/BUILDING.md`), then
  `docs/RESCUE.md` if needed.

### On a BlackBox with M-VAVE V22 or V23

This route writes the same builds' app areas through the chip's USB boot state with `tools/uboot_install.py --image`,
as [`docs/RESCUE.md`](RESCUE.md#gamut-on-a-blackbox-with-v22-or-v23) installs Gamut. Read that section's "Before the
first run" once: a Mac with `brew install libusb`, `sudo`, the pedal straight on the Mac with no hub, and M-VAVE's
`BlackBox_023.fwsc` at hand for the way back. The tool names the pedal's layout by its boot area's CRC-32, backs up the
whole flash first, never writes below `0x6000` or from `0x9F000` up, and writes, reads back and compares only the
sectors that differ; a rerun resumes. `--image` takes any app image: it refuses only a file that is not whole 4 KiB
sectors, is longer than the pedal's app area, or begins with a boot area. It prints the file's SHA-256 for the record
and does not compare it with a list. It warns, loudly, when the boot loader would not start the image; the boot area is
never written, so the way back below works even then.

In every run, **start the command first, wait for `waiting for the pedal`, then do the key hold**: pedal off, hold
HOME, the right footswitch and the knob's PUSH, switch on, keep holding until the screen shows `RECOVERY`.

Gate A:

```
sudo python3 tools/uboot_install.py --image build/apps/gamut/rate-diag/BlackBox_942-v23.bin 2>&1 | tee rate-diag-dry.log
sudo python3 tools/uboot_install.py --image build/apps/gamut/rate-diag/BlackBox_942-v23.bin --write 2>&1 | tee rate-diag-write.log
```

The first command is the dry run and writes nothing. It prints the file, its identity `BlackBox_942` and its SHA-256
(the same as the `package-test rate-diag` line for that file), the layout `M-VAVE's V22/V23 head`, the sectors that
differ, the backup's path and the way back. Check the SHA-256 and the layout. A `WARNING` or any `REFUSED` here means
the wrong file: stop and send the log. The second command asks for a typed `yes` before it looks for the pedal, then
writes and ends with `Done: N sectors written and verified`. Switch the pedal off and on, then run `log` as in Gate A above, from `node tools/op.mjs log --wait 30`.

Gate B, only after Gate A has passed: the same two commands with `rate48` in place of `rate-diag`, then `log` and the
checks of Gate B above.

The way back, the same way, each with its dry run first (without `--write`):

```
sudo python3 tools/uboot_install.py --write                                   # the release, Gamut 1.0b1
sudo python3 tools/uboot_install.py --official BlackBox_023.fwsc --write      # M-VAVE's V23
```

`--restore` with the backup the first run saved puts back the whole app area as it was. If a write stops halfway, the
pedal may not start, but its boot loader is untouched: the key hold still works, and the same command resumes.

### The way back

On a Pocket X or a BlackBox on V21 or older:

```
node tools/op.mjs flash --dry-run
node tools/op.mjs flash --confirm-flash
```

These commands put back the release from `build/apps/gamut/` (Gamut 1.0b1, `PocketX_950`). The presets, NAM models and
IRs are kept through all of these flashes. After any crash, run `node tools/op.mjs dsp --presets 19 --seconds 2` and
check that `cores` is 2 before you trust a load figure.
