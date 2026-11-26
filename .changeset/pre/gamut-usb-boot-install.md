---
"tools": major
---

Gamut can now be installed on a BlackBox that runs M-VAVE's official V22 or V23, with no downgrade, and M-VAVE's firmware can be put back the same way. One command on a Mac, `sudo python3 tools/uboot_install.py` (`make usb-install`), takes the pedal from its RECOVERY screen to the chip's USB boot state and writes only the app area, never the boot loader; it is a dry run until `--write` is added, and it saves a backup of the whole flash first. The route has worked on one real pedal; the single command has so far run against simulated pedals only. The earlier route, `tools/pd40_install.py --write`, could not finish on a real pedal and is now refused. The same command also accepts a pedal with the older layout (V16, V17, V20) and refuses every other one; on those pedals the installer page remains the usual way. The steps are in the rescue guide, under "Gamut on a BlackBox with V22 or V23". The rescue kit is now number 6, with its texts brought up to date.
