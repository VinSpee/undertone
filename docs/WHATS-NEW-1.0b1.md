# What's new in Gamut 1.0b1: 48 kHz, new factory amps, a factory cabinet IR, a safer update loader

The guitar firmware, formerly OpenPocket, is now called **Gamut**. This is its first beta, version 1.0b1. The sound and
the controls are those of the build after v42; the sections below say what changed since OpenPocket v42.

## 1. The sound at 48 kHz

- **Gamut runs at 48 kHz**, the rate most NAM captures are made at, so they play as they were captured. USB audio is
  48 kHz too. The pedal moves its clock to 48 kHz only when that clock's source is already running; otherwise, and in
  safe mode, it runs at 44.1 kHz without USB audio ([RATE48-TEST.md](RATE48-TEST.md)).
- Your cabinet IRs keep their sound: an IR made at 44.1 kHz is resampled when a preset loads it.

## 2. The amps and cabinets

- **The built-in amps and cabinets are removed.** The AMP block plays NAM models and the CAB block plays your own IRs.
  The drives stay.
- **The 12 factory amps are NAM captures from TONE3000**, shipped with their authors' permission: a Fender Super Reverb
  and a Vox AC30, four channels of a Bogner TM 26, two Soldano SLO-100, two Orange Dual Terror and two Orange Jim Root
  Terror ([NAM.md](NAM.md)). Eight of them hold their cabinet and play with the CAB block off. The factory presets are
  rebuilt round them.
- A preset you saved with a factory amp keeps its MODEL number, so it now plays the new model in that place. A preset
  saved with a built-in amp plays the factory model nearest its character. A preset saved with a built-in cabinet
  plays the IR in slot 1; DI turns the cabinet off.
- **Slot IR1 comes with a cabinet IR**, "BEST IR IN THE WORLD" by ML Sound Lab
  ([video](https://www.facebook.com/watch/?ref=embed_video&v=1053603041469100)). It is the only built-in cabinet IR.
  The factory presets play it until you load your own IR into IR1, and removing yours brings it back. The factory
  presets' levels are set for it. It is redistributed with the creator's permission, as stated by the project's owner;
  no other licence is given for it. [NOTICE.md](../NOTICE.md) has the details.

## 3. The preset store

The preset store is format 6. A preset saved by an earlier version is converted when it loads. The editor protocol is
version 6: INFO gives the pedal's sample rate.

## 4. The update loader and the packages

- **The update loader reads the pedal's own flash head before it erases anything** and refuses, writing nothing, a head
  it does not know, such as M-VAVE's BlackBox V22 and later. The installer page and `node tools/op.mjs flash` refuse a
  BlackBox on official firmware 022 or later outright, with no confirmation that lifts it.
- **Every firmware package fits both flash layouts:** its app area sits at 0x4000, as on older pedals, or at 0x6000, as
  on M-VAVE's BlackBox V22 and later, without reaching those pedals' stock settings. The loader writes only the
  package's app area and refuses a package that would run past the slot of the pedal's flash head.

## 5. Fixes

- Saving or deleting a NAM model or a cabinet IR from the editor no longer reads the pedal's memory while the second
  processor may be working, which could stop that processor until the pedal was switched off.
- The editor no longer misses a change made on the pedal when the pedal answers one of its requests within 40 ms of the
  change.

## 6. The new name

The boot screen shows Gamut, and the editor and the installer call it Gamut with the version 1.0b1. The firmware's
identity is 50 (`PocketX_950`, `BlackBox_950`), so a pedal running it can be told apart from one running v42.

The USB device name, the update loader's identity and the package names stay as they were, so this installer, the
editor and the original OpenPocket project's installer all still find the pedal. That installer names it OpenPocket v50.
