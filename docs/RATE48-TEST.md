# Gamut at 48 kHz: the clock and the checks on a pedal

Gamut's release runs at 48 kHz, the rate its factory amps were captured at. It moves the I2S to 48 kHz only when its
guard allows it, and otherwise runs at 44.1 kHz and says why. The 48 kHz clock's real rate has not been read on a pedal
yet, so USB audio's clock figure (`UAC_I2S_HZ100` in `firmware/px_uaconf.h`) is the nominal 48,000 Hz until it is.

One test build is left: **rate-diag** (`OP_RATE_DIAG`), Gamut at 44.1 kHz as before the switch. The driver sets the
clock exactly as it did in the 44.1 kHz release; the build reads the clock registers, writes none of them itself, and
measures the real sample rate. The installer offers it only through `?channel=rate-diag`. The rate48 test build that
came before the switch is the release now.

The code is `firmware/base/rate.h`. `tests/test_rate.c` runs it on a PC against a model of the I2S driver's register
writes.

## What the release does at the start

The JieLi driver's 48 kHz case (`sdk/iis.bc`, `iis_set_sample_rate` for ALNK0) differs from its 44.1 kHz case in two
writes:

- It ORs bit 25 into `0x119A4`, PLL0's second control register. That PLL probably also clocks USB.
- It sets bit 8 of `0x10014`. The 44.1 kHz case clears that bit.

Both cases write the same divider byte and clear bit 9 of `0x10014`. Gamut therefore calls the driver's 44.1 kHz case
and then sets bit 8 itself. It never writes PLL0. Its guard allows 48 kHz only when both are true:

- Bit 25 of `0x119A4` is already set at the start, so the 48 kHz family's source is already on.
- The start is not a safe-mode start. A start after a failed one always runs at 44.1 kHz.

The rate is picked before USB starts. At 48 kHz the engine, the tuner, the block budget, the load figures and USB
audio run at 48 kHz. At 44.1 kHz the engine, the tuner and the load figures follow the clock (the engine's memory is
still 48 kHz's, so its pitch effects and synths sound slightly different), and USB audio is not offered: its streams
are 48 kHz's, so the pedal is a MIDI device alone. Cabinet IRs play at the pedal's rate: the factory IR from its table
for that rate, and an IR made at the other rate resampled when a preset loads it.

Both Gamut and rate-diag answer the editor protocol's `DIAG` with one line, which `node tools/op.mjs log` reads and
explains. It shows the rate asked for and the rate in use, the guard, and the rate measured over the last 10 s from the
guitar's blocks against the 24 MHz timer. It also shows the clock registers now and as they were before the rate was
set:

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
node tools/op.mjs package
node tools/op.mjs package-test rate-diag
```

The first command builds the release, the second the 44.1 kHz report build. Each prints the SHA-256 of what it built,
the BlackBox app area `BlackBox_950-v23.bin` (`BlackBox_942-v23.bin` for rate-diag) included; the release's must be
the sums of `firmware/apps/gamut/release.sha256`.

### The release: the clock

```
node tools/op.mjs flash --dry-run
node tools/op.mjs flash --confirm-flash
node tools/op.mjs log --wait 30
node tools/op.mjs log --wait 30 --json > rc-clock.json
```

The dry run writes nothing. It must print `dry run ok: would update ... -> PocketX_950 (Gamut)`, or the same with
`BlackBox`. The boot screen's version line is `1.0b1`. The clock passes when all of the following are true:

- The `log` verdict is PASS: guard PASS, and a rate within 0.5 % of 48 kHz.
- The pedal did not start in safe mode.

The measured rate is the figure `UAC_I2S_HZ100` waits for: send `rc-clock.json`. If the verdict is FAIL with guard
BIT25, the 48 kHz family's source is off on this pedal: it runs at 44.1 kHz, and the rate-diag build below says the
same without the 48 kHz path.

### The release: the sound

Run these only after the clock has passed.

1. **The DSP load.** Every factory preset, and the worst-case chains (all 12 blocks on, every knob at 100) saved as
   presets of your own:

   ```
   node tools/op.mjs dsp --presets 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24 --json > rc-dsp.json
   node tools/op.mjs dsp --json > rc-dsp-saved.json
   ```

   It passes with no late block and no safety bypass on any of them. Each load is expected to be about 1.09 times what
   the 44.1 kHz release showed on the same preset (a projection, not a measurement). Keep the peaks.
2. **USB audio.** Turn USB audio on. The computer must list an **OpenPocket** device at 48 kHz. Record the pedal for a
   few minutes and check the recording for gaps and repeats; a build with `OP_UADEV 1` puts a steady tone at the input
   for that ([USB-AUDIO.md](USB-AUDIO.md)).
3. **Listening.** The factory presets, the tuner, and a guitar through effect-only presets (AMP and CAB off): no
   crackle, noise, aliasing or a dead output. The owner approves the sound.

If the release fails, the possible results are these:

- **Verdict FAIL with the rate.** The 48 kHz family runs at another rate. The measured rate is the finding.
- **No sound, but the pedal answers.** The 48 kHz clock does not run. USB works, so go back (below).
- **The pedal crashes once.** The next start is in safe mode, which runs at 44.1 kHz. `log` then says SAFE. Go back.
- **A restart loop.** Run `node tools/op.mjs flash --rescue --confirm-flash` (`docs/BUILDING.md`), then
  `docs/RESCUE.md` if needed.

### The report at 44.1 kHz

```
node tools/op.mjs flash --dry-run --manifest build/apps/gamut/rate-diag/manifest.json
node tools/op.mjs flash --confirm-flash --manifest build/apps/gamut/rate-diag/manifest.json
node tools/op.mjs log --wait 30 --json > rate-diag.json
```

The boot screen's version line names the build: `v42 RATE DIAG`. The sound is Gamut at 44.1 kHz. The verdict PASS
means the rate was measured within 0.5 % of 44.1 kHz; about 44,117.6 Hz is expected. The verdict also says whether bit
25 of `0x119A4` is set, which decides whether the release can run at 48 kHz.

### On a BlackBox with M-VAVE V22 or V23

This route writes the release's app area, or a test build's with `--image`, through the chip's USB boot state with `tools/uboot_install.py`,
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

The release:

```
sudo python3 tools/uboot_install.py 2>&1 | tee rc-dry.log
sudo python3 tools/uboot_install.py --write 2>&1 | tee rc-write.log
```

The report at 44.1 kHz:

```
sudo python3 tools/uboot_install.py --image build/apps/gamut/rate-diag/BlackBox_942-v23.bin 2>&1 | tee rate-diag-dry.log
sudo python3 tools/uboot_install.py --image build/apps/gamut/rate-diag/BlackBox_942-v23.bin --write 2>&1 | tee rate-diag-write.log
```

The first command of each pair is the dry run and writes nothing. It prints the file, its identity (`BlackBox_950`, or
`BlackBox_942` for rate-diag) and its SHA-256 (the same as the build's line for that file), the layout `M-VAVE's V22/V23 head`, the sectors that
differ, the backup's path and the way back. Check the SHA-256 and the layout. A `WARNING` or any `REFUSED` here means
the wrong file: stop and send the log. The second command asks for a typed `yes` before it looks for the pedal, then
writes and ends with `Done: N sectors written and verified`. Switch the pedal off and on, then run `log` and the
checks above, from `node tools/op.mjs log --wait 30`.

The way back, the same way, each with its dry run first (without `--write`):

```
sudo python3 tools/uboot_install.py --image OLD/build/apps/gamut/BlackBox_950-v23.bin --write   # Gamut at 44.1 kHz
sudo python3 tools/uboot_install.py --official BlackBox_023.fwsc --write      # M-VAVE's V23
```

`--restore` with the backup the first run saved puts back the whole app area as it was. If a write stops halfway, the
pedal may not start, but its boot loader is untouched: the key hold still works, and the same command resumes.

### The way back

The way back is Gamut at 44.1 kHz: the build of commit `6dfb8be`, whose release pin the changelog keeps (the entry for
the switch to 48 kHz). Build it from that commit in a checkout of its own, with `node tools/op.mjs package`, and check
its sums against that pin. On a Pocket X or a BlackBox on V21 or older:

```
node tools/op.mjs flash --dry-run --manifest OLD/build/apps/gamut/manifest.json
node tools/op.mjs flash --confirm-flash --manifest OLD/build/apps/gamut/manifest.json
```

`OLD` is that checkout. Its identity is the same, `PocketX_950`; the flasher checks only the pedal's model. The presets, NAM models and
IRs are kept through all of these flashes. After any crash, run `node tools/op.mjs dsp --presets 19 --seconds 2` and
check that `cores` is 2 before you trust a load figure.
