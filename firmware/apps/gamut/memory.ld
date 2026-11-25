/* SPDX-License-Identifier: MPL-2.0
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* OpenPocket's own memory regions (firmware/app.ld includes this file; docs/BASE-FIRMWARE.md): the 432 KiB of SRAM
 * from 0x01C08000 up to the stacks, split for the amp modeller. POOL: free SRAM (like CLIPPER), the DSP engine (v40:
 * was 0x54000). RAMTEXT: v40, the RAM code, audio path included (was 24 KB at 0x01C00000).
 * An engine built for 48 kHz (op_engine48 = 1: firmware/build.sh; px_dsp.h PX_FS) holds 26 KB more, for its delay's
 * 2 s, its reverb's ring and its pitch shifters' rings: the POOL takes 16 KB from the RAM's free end and 10 KB from the
 * RAM code window's. */
MEMORY
{
    RAM    (rwx) : ORIGIN = 0x01C08000, LENGTH = 96K - op_engine48 * 16K
    POOL   (rw)  : ORIGIN = 0x01C20000 - op_engine48 * 16K, LENGTH = 0x3E000 + op_engine48 * 26K
    RAMTEXT (rwx): ORIGIN = 0x01C5E000 + op_engine48 * 10K, LENGTH = 0x16000 - op_engine48 * 10K
}
