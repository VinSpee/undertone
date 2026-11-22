---
"base": patch
"tools": patch
---

The update loader now reads the pedal's own flash head before it erases anything and refuses, writing nothing, a head it does not know, such as M-VAVE's BlackBox V22 and later; the installer page and `node tools/op.mjs flash` refuse a BlackBox on official firmware 022 or later outright, with no confirmation that lifts it (the idea of upstream pull request isod89/openpocket#35).
