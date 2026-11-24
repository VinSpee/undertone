/* SPDX-License-Identifier: GPL-3.0-only
 * Gamut — the pedal screen's palette (RGB565) and what each colour is for. It is Gamut's own: PALETTE and STARTER keep the
 * base firmware's (base/board.h), and the web editor keeps the blocks' colours (ui_colors.h).
 * Light carries the state: a thing that is on is pale, a thing that is off is dark. Green is the lamp, and only that:
 * sound passes, a thing is on, the note is in tune. Amber is the only warning: something waits on the player (an unsaved
 * edit, a model loading) or went wrong (overload, a late block, a low battery, a fault). No red, and no colour per block. */
#pragma once
#define C_GROUND   0x10A3              /* the screen's ground */
#define C_PLATE    0x2966              /* the bands at the top and the foot of a page, which carry the controls */
#define C_KEY      0x2125              /* a key that is off, a selected row */
#define C_RIM      0x4208              /* rules, the empty part of a bar, the mark's holes in the plate */
#define C_GRILLE   0x5B0B              /* the mark's holes on the ground (a start, an update, the rescue mode) */
#define C_HOUSING  0xF7BD              /* text, a key that is on, the needle */
#define C_LABEL    0xAD54              /* labels and hints */
#define C_LAMP     0x5DEA              /* the lamp, lit */
#define C_LAMP_OFF 0x29C5              /* the lamp, unlit */
#define C_LAMP_KEY 0x3C47              /* the lamp lit on a housing key (the bright one reads at 2.2:1 there, this at 4.0:1) */
#define C_AMBER    0xF715              /* a note or a warning */
#define C_GRAPHITE 0x2966              /* text on housing and on amber (never on the plate: they are one RGB565 value) */
