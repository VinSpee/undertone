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

At 48 kHz the rate48 build also gives the engine, the block budget and the load figures the 48 kHz rate. It has no USB
audio, because USB audio's clock figures are for 44.1 kHz; USB MIDI, the editor and the installer work as usual. Known
differences at 48 kHz, which are expected and not part of this test:

- The tuner reads 1.47 semitones flat.
- The NAM amps and the factory cabinet sound brighter.
- The pitch effects and the synths sound slightly different.
- The longest delay is 1.85 s.

Both builds answer the editor protocol's `DIAG` with one line, which `node tools/op.mjs log` reads and explains. It
shows the rate asked for and the rate in use, the guard, and the rate measured over the last 10 s from the guitar's
blocks against the 24 MHz timer. It also shows the clock registers now and as they were before the rate was set:

- PLL0: `0x119A0` and `0x119A4`
- PLL1: `0x119A8` and `0x119AC`
- `0x10008`, `0x1000C` and `0x10014`
- ALNK0's divider byte, `0x12E0C`

## Steps on the pedal

Flash only one pedal, and only with the owner's go-ahead. Use a Pocket X, or a BlackBox on M-VAVE V21 or older: the
flasher refuses a BlackBox on V22 or later. Close the browser installer and any other MIDI program first.

### Once

```
npm ci --prefix tools
node tools/op.mjs package-test rate-diag
node tools/op.mjs package-test rate48
node tools/op.mjs package
```

The last command builds the release again, for the way back. Each command prints the SHA-256 of what it built.

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

### The way back

```
node tools/op.mjs flash --dry-run
node tools/op.mjs flash --confirm-flash
```

These commands put back the release from `build/apps/gamut/` (Gamut 1.0b1, `PocketX_950`). The presets, NAM models and
IRs are kept through all of these flashes. After any crash, run `node tools/op.mjs dsp --presets 19 --seconds 2` and
check that `cores` is 2 before you trust a load figure.
