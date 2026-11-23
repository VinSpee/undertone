/* SPDX-License-Identifier: GPL-3.0-only
 * OpenPocket — the blocks' colours (RGB565) in the web editor (px_editor.h CAT_BLOCK). The pedal's screen does not use
 * them: it shows a block that is on by light (ui_palette.h). */
#pragma once
static const uint16_t BLK_COL[PX_NBLK] = {
    0x5D9F, 0x5D9F,   /* GT, CMP: blue (dynamics) */
    0xC31F,           /* PIT: purple */
    0xFB1A,           /* SFX: pink */
    0xFE00,           /* DRV: yellow */
    0xFB20,           /* AMP: orange */
    0xCC4A,           /* CAB: beige */
    0x6FE8,           /* EQ: light green */
    0x7D5F,           /* MOD: lavender */
    0x47FF,           /* DLY: cyan */
    0x8FE0,           /* REV: green */
    0xF8B2,           /* SYN: raspberry */
};
