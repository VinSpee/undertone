---
"tools": minor
---

A BlackBox on M-VAVE's V22 or V23 can now be read when it shows RECOVERY: a new read-only helper in the rescue kit, `tools/pd40_recovery.py`, reads what the pedal's recovery mode reports, also over the control endpoint when the bulk endpoint sends zeros as on a real V23 pedal, and watches what the pedal starts when the recovery mode ends. Its command to leave for the USB boot state stays behind an explicit flag, because whether it gets there is not known. It never writes to the pedal.
