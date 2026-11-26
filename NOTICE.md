# Credits and licences

Undertone is GPL-3.0-only (`LICENSE`), except the parts below, which keep their own licences.

| Part | Origin | Licence |
| --- | --- | --- |
| `firmware/bsp/` (chip support: startup, interrupts, second core, flash, USB-MIDI device, M-UPGRADE update entry `ota.c`) | [felucca-bsp](https://github.com/hugelton/felucca-bsp), Leo Kuroshita / Hügelton Instruments and contributors. `chip/ota.c` changed for Undertone (identity read at run time). `chip/usb.c` changed for the USB audio of Gamut (v42, then called OpenPocket): the audio streams switched at run time (`FELUCCA_UAC_SWITCH`), the record stream's packet pacing of felucca-bsp `e79a1f8`, the playback mix in integers, fewer controller reads a poll. `chip/usb_host.c` changed for Gamut's USB footswitch by cable: its clock given by the application (`UH_MS`). | MPL-2.0 (`LICENSES/MPL-2.0.txt`) |
| `loader/` (update loader) | felucca-bsp `loader/`, changed for the Pocket X flash layout | MPL-2.0 |
| `docs/pxota.js`, `docs/pxpkg.js`, `tools/pxpkg.py`, `tools/mkloader.py`, `tools/lz4blk.py` | adapted from [Felucca](https://github.com/hugelton/Felucca)'s web installer and build tools (as used by CLIPPER and SLOOP) | GPL-3.0 |
| `firmware/sdk/` (I2S and DAC drivers as LLVM bitcode, SPL, cfg files) | JieLi AC79 SDK V1.2.0 (fw-AC79_AIoT_SDK) | Apache-2.0 (`LICENSES/Apache-2.0.txt`) |
| `firmware/px_cacheram.h` (data-cache ways as RAM, for the NAM network's vector-unit buffers) | [melodee](https://github.com/keremimo/melodee) `firmware/hal/fm1_cache.h`, Kerem Kilic (Ellic Studio), after the AC79 SDK's cache way setup | GPL-3.0 |
| `third_party/jieli-ble/` (JieLi's Bluetooth LE controller, 33 objects of `btctrler.a` and 3 of `cpu.a`, as published LLVM bitcode, used only by the Bluetooth test image `make ble`) | JieLi AC79 SDK V1.2.0 (fw-AC79_AIoT_SDK, commit `0617f4c`), `cpu/wl82/liba/`; see `third_party/jieli-ble/README.md` | Apache-2.0 (`third_party/jieli-ble/LICENSE-JieLi-Apache-2.0`, `LICENSES/Apache-2.0.txt`) |
| `tools/jlfold.py` (the Bluetooth test image's controller library folded at build time) | [ettorebox](https://github.com/steponme82/ettorebox) `tools/jlfold.py`, Roberto Antonacci, commit `375a253`; reduced to its `fold` command and the LE controller's names | GPL-3.0 |
| `firmware/apps/gamut/ble/ble_cfg.c` | values and names from the same SDK's `apps/common/config/log_config/lib_btctrler_config.c` | Apache-2.0 |
| `firmware/fonts.h` (bitmaps generated from Inter) | [Inter](https://rsms.me/inter/), Rasmus Andersson | SIL OFL 1.1 (`LICENSES/OFL-1.1-Inter.txt`) |
| `firmware/apps/gamut/ui_fonts.h` (bitmaps generated from B612 and B612 Mono by `tools/mkfont.py gamut`: a modified version of the fonts, which declare no reserved font name) | [B612](https://github.com/polarsys/b612), The B612 Project Authors | SIL OFL 1.1 (`LICENSES/OFL-1.1-B612.txt`) |
| `assets/loops/*.wav` (guitar loops for the simulator), and `docs/assets/audio/riff.m4a` (`riff.wav` as AAC, which the site's home page plays) | cut from [Guitar-TECHS](https://zenodo.org/records/14963133), credits in `assets/loops/ATTRIBUTION.md` | CC BY 4.0 |

The factory NAM models (`firmware/apps/gamut/engine/px_nam_factory.h`) are the A2-Lite networks of Neural Amp Modeler
A2 captures published on [TONE3000](https://www.tone3000.com/). Each author gave the project's owner written permission
to ship them inside this GPL-3.0 firmware; on TONE3000 they carry its T3K licence, which allows redistribution only
with that permission. `tools/nam_factory.txt` lists each capture file and its SHA-256.

| Models | Author on TONE3000 | Captures |
| --- | --- | --- |
| SUPER 65, AC30 TB | Amalgam Captures (amalgamaudio) | [Fender Super Reverb 1965 edge of breakup A2](https://www.tone3000.com/tones/fender-super-reverb-1965-edge-of-breakup-a2-88775); [1964 Vox AC30 Top Boost Super Twin edge of breakup A2](https://www.tone3000.com/tones/1964-vox-ac30-top-boost-super-twin-edge-of-breakup-a2-82521) |
| TM26 GRN, TM26 PLX, TM26 BLU, TM26 RED | torcuato | [Bogner TM 26 no cab](https://www.tone3000.com/tones/bogner-tm-26-no-cab-109210) |
| SLO 100, SLO RIFF | subterraneans | [Soldano SLO-100](https://www.tone3000.com/tones/soldano-slo-100-106781) |
| DT MIDS, DT SCOOP | chuggernautxanner | [Orange Dual Terror full rig, boosted and unboosted](https://www.tone3000.com/tones/orange-dual-terror-full-rig-boostedunboosted-81959) |
| JRT GN 5, JRT GN 7 | CavLabs (caveraolabs) | [CavLabs #4 Orange Jim Root Terror](https://www.tone3000.com/tones/cavlabs-4-orange-jim-root-terror-24650) |

The NAM A2 architecture is from Neural Amp Modeler (Steven Atkinson, MIT); `firmware/apps/gamut/engine/px_nam.c`,
`tools/nam_a2.py` and `tools/train_a2.py` are written for Gamut from the published architecture. The level reference
`docs/nam_di.wav` is DI guitar from [Alec-Wright/Automated-GuitarAmpModelling](https://github.com/Alec-Wright/Automated-GuitarAmpModelling)
(GPL v3).

The factory cabinet IR (`firmware/apps/gamut/engine/px_ir_factory.h`, slot IR1's IR while the user has loaded none there) is
["BEST IR IN THE WORLD"](https://www.facebook.com/watch/?ref=embed_video&v=1053603041469100), a free cabinet impulse response by ML Sound Lab. It is redistributed
with the creator's permission, as stated by the project's owner; no other licence is given for it, and the GPL of this
repository does not cover it. The firmware holds it converted (at 44.1 and at 48 kHz, its first 1024 samples, `tools/mk_ir_factory.mjs`);
the original WAV file is not in this repository or in the firmware.

Contributors: **Vince Speelman ([VinSpee](https://github.com/VinSpee))**: the simulator's WebAssembly engine and its sound, the
command-line flasher, MIDI, the Bluetooth test image (the radio's fix, a connectable BLE-MIDI peripheral, the Chocolate
Plus test, `op.mjs log`), and v41's two-core NAM work (the network split by layers, the `rdm` / `post4` / `post5` routines, 24 KB of RAM
freed, the faster preset switches with LOADING, PING's DSP health and `tools/dsp.mjs`, the pedal screen's quick wins;
pull request #22), and v42's web editor in four sections (#23), the pedal's reworked controls and diagnostics pages
(#24) and USB audio (#25).
**Ivan Shevchuk ([Testing7B](https://github.com/Testing7B))**: v42's check and restore of the BlackBox V21 factory
sounds (pull request #26).
**Roberto Antonacci ([steponme82](https://github.com/steponme82))**: the BlackBox button lights (#17), and from his fork
[ettorebox](https://github.com/steponme82/ettorebox): the build-time fold of the Bluetooth library (`tools/jlfold.py`, commit
`375a253`), the web editor's NAM import in browsers with no second window or script-opened file picker, such as MIDIWeb on
an iPhone (commit `f25a720`), the USB MIDI messages' arrival time and the pedal as the USB MIDI host of a footswitch by cable with its own clock
(commit `10e2c7c`), the footswitch numbers CC 116, 118
and 119 (commits `c324798`, `5675bcc`), the second core's fault record with its registers (commit `409771d`), and the
Bluetooth library's timers made safe in interrupts with its usr timeouts on the 10 kHz tick (commits `7819e5a`, `c09d828`).

Sound models: the names refer to the gear that inspired each voicing (circuit analyses published by ElectroSmash,
Electric Druid, R.G. Keen / GEOFEX, Rob Robinette, Duncan's Tone Stack Calculator; speaker data sheets; manufacturers'
manuals). All trademarks belong to their owners; Undertone is not affiliated with Donner, M-VAVE or any gear maker.

No part of the official Pocket X / BlackBox firmware is in this repository. The installer's way back to the official
firmware uses the file you download from the maker; it is checked in your browser and never uploaded.
