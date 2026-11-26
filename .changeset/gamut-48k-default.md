---
"openpocket": minor
"base": minor
---

Gamut runs at 48 kHz, the rate its factory amps were captured at, so they play exactly as captured, and so do most NAM captures from TONE3000; USB audio is 48 kHz. The pedal moves its clock to 48 kHz only when that clock's source is already running, and never writes the PLL that clocks USB; otherwise, and in safe mode, it stays at 44.1 kHz without USB audio. `node tools/op.mjs log` shows which rate it chose and the rate it measured. The way back to Gamut at 44.1 kHz is the build of commit `6dfb8be`, whose release pin was:

```
5a345d85d88ae3df72e01cae7a6cecb1dafcec2512888a9676f64ff932f2ec54  build/apps/gamut/openpocket.bin
679db5e22628c1fcc0b23c122313b45f4e027c51caf02a0a8a5a98fa0fef57e9  build/apps/gamut/BlackBox_950.fwsc
4334830d3d04d4cff31ae740781a58823a1aeec64fe5611262abd5cfb440fad3  build/apps/gamut/PocketX_950.fwsc
33dfbc3f151ad0c3ade0d4e6f8e0a8af93b0ed4f50c557c54ada25fec08f6d94  build/apps/gamut/BlackBox_950-v23.bin
889d5d173a6e0878eb7b2acf5c039aebe6df3fb2223aea909ec4628035815097  build/apps/gamut/manifest.json
```
