---
"tools": minor
---

The install for a BlackBox on M-VAVE's V22 or V23, `tools/pd40_install.py`, now works on a pedal that answers over its control endpoint only, as the one real V23 pedal tried does: with the new flag `--accept-control-reply` it reads each reply from the pedal's reply buffer when the bulk IN endpoint sends zeros in its place, checks it the same way, and refuses such a pedal without the flag. It also logs which route the replies took, how long each phase took, and, if the recovery mode ends during the session, after which frame.
