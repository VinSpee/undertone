---
"openpocket": patch
"base": patch
"tools": patch
---

When the second processor faults and is switched off, the pedal now keeps its registers and stack pointer, and the Bluetooth test image's log (`node tools/op.mjs log`) shows them, so the cause can be found. The processor is still not started again.
