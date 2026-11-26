# base

## 1.0.0-beta.1

### Minor Changes

- [#96](https://github.com/VinSpee/undertone/pull/96) [`6dfb8be`](https://github.com/VinSpee/undertone/commit/6dfb8be690f9637f6b61b4cd3c8c6b6e51d36528) Thanks [@VinSpee](https://github.com/VinSpee)! - Gamut gets ready for 48 kHz. A cabinet IR is now loaded at the pedal's own sample rate, and the pedal plays an IR made at the other rate resampled, so your saved IRs keep their sound when Gamut moves to 48 kHz; the editor's note on a NAM capture's sample rate now compares it with the pedal's. At 44.1 kHz the sound is unchanged. A firmware that runs at 48 kHz offers USB audio at 48 kHz only, and the simulated pedal's sound runs at 48 kHz.

- [#62](https://github.com/VinSpee/undertone/pull/62) [`4cf1479`](https://github.com/VinSpee/undertone/commit/4cf147959482b3708935528e09f23e6d5fe55a3e) Thanks [@VinSpee](https://github.com/VinSpee)! - A BlackBox on M-VAVE's official V22 or V23 can now get Gamut without going back to V21: `tools/pd40_install.py` writes Gamut's app area through that boot loader's own recovery mode, which never touches the boot loader, and puts M-VAVE's V23 app back the same way. It is not yet tried on a real pedal, so the installer page still refuses such a pedal; the build now also writes each BlackBox package's app area as a file of its own (`BlackBox_950-v23.bin`) for it. The steps are in the rescue guide, under "Gamut on a BlackBox with V22 or V23".

### Patch Changes

- [#74](https://github.com/VinSpee/undertone/pull/74) [`4f9b968`](https://github.com/VinSpee/undertone/commit/4f9b968e24e2900127cbfcaf438e025cd67c1d26) Thanks [@VinSpee](https://github.com/VinSpee)! - When the second processor faults and is switched off, the pedal now keeps its registers and stack pointer, and the Bluetooth test image's log (`node tools/op.mjs log`) shows them, so the cause can be found. The processor is still not started again.

- [#53](https://github.com/VinSpee/undertone/pull/53) [`10b4f1c`](https://github.com/VinSpee/undertone/commit/10b4f1c8073e47748856256f5bff3e0ff33b7378) Thanks [@VinSpee](https://github.com/VinSpee)! - The update loader now reads the pedal's own flash head before it erases anything and refuses, writing nothing, a head it does not know, such as M-VAVE's BlackBox V22 and later; the installer page and `node tools/op.mjs flash` refuse a BlackBox on official firmware 022 or later outright, with no confirmation that lifts it (the idea of upstream pull request isod89/openpocket#35).

- [#55](https://github.com/VinSpee/undertone/pull/55) [`9ed4403`](https://github.com/VinSpee/undertone/commit/9ed4403b223958896bd855dc845b94778ac6fa8f) Thanks [@VinSpee](https://github.com/VinSpee)! - Every firmware package now fits both pedal flash layouts: its app area is small enough to sit at 0x4000, as on older pedals, or at 0x6000, as on M-VAVE's BlackBox V22 and later, without reaching those pedals' stock settings. The update loader writes only the package's app area and refuses a package that would run past the slot of the pedal's flash head. The installer still refuses BlackBox V22 and later.

- [#70](https://github.com/VinSpee/undertone/pull/70) [`6c70d1b`](https://github.com/VinSpee/undertone/commit/6c70d1b46e9f4bb3ca38121bbe00a4b1197c5499) Thanks [@VinSpee](https://github.com/VinSpee)! - MIDI clock sent over USB now sets the delay time (Gamut, with CLOCK > DELAY on) and PALETTE's tempo: the pedal now notes when each USB MIDI message arrives, which it never did before, so it could not time the clock.
