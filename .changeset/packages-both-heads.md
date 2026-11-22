---
"base": patch
---

Every firmware package now fits both pedal flash layouts: its app area is small enough to sit at 0x4000, as on older pedals, or at 0x6000, as on M-VAVE's BlackBox V22 and later, without reaching those pedals' stock settings. The update loader writes only the package's app area and refuses a package that would run past the slot of the pedal's flash head. The installer still refuses BlackBox V22 and later.
