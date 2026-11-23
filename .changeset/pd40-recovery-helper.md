---
"tools": minor
---

A BlackBox on M-VAVE's V22 or V23 can now be reached when it shows RECOVERY: a new read-only helper in the rescue kit, `tools/pd40_recovery.py`, reads what the pedal's recovery mode reports and, on request, sends it to the USB boot state where the rescue tool takes over. It never writes to the pedal.
