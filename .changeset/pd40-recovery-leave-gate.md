---
"tools": minor
---

The recovery helper for a BlackBox on M-VAVE's V22 or V23, `tools/pd40_recovery.py`, now watches the USB devices after every probe and logs when the pedal leaves its recovery mode, counted from the last command sent and from the first access, and whether it comes back as the USB boot state or as the normal pedal. A new flag, `--accept-control-reply`, given with `--leave --accept-inferred`, lets its single leave command go out when the pedal answered the hello only over the control endpoint, as a real V23 pedal did. It still never writes to the pedal.
