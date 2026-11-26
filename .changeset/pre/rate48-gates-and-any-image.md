---
"tools": minor
---

`tools/uboot_install.py --image FILE` installs any app image on a BlackBox through the chip's USB boot state, the same way as Gamut, on a pedal with M-VAVE's V22 or V23 or with the older layout. It refuses a file that is not whole 4 KiB sectors, does not fit the pedal's app area or carries a boot area; it warns when the boot loader would not start the image, prints the file's SHA-256, asks for a typed `yes` before `--write`, and prints the way back. The dry run now also lists the sectors a write would change. Two test builds, `rate-diag` and `rate48`, decide whether Gamut can run at 48 kHz; the installer offers them only through `?channel=rate-diag` and `?channel=rate48`, and the steps are in `docs/RATE48-TEST.md`. The rescue kit is now number 9.
