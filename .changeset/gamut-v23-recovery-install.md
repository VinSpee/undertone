---
"tools": minor
"base": minor
---

A BlackBox on M-VAVE's official V22 or V23 can now get Gamut without going back to V21: `tools/pd40_install.py` writes Gamut's app area through that boot loader's own recovery mode, which never touches the boot loader, and puts M-VAVE's V23 app back the same way. It is not yet tried on a real pedal, so the installer page still refuses such a pedal; the build now also writes each BlackBox package's app area as a file of its own (`BlackBox_950-v23.bin`) for it. The steps are in the rescue guide, under "Gamut on a BlackBox with V22 or V23".
