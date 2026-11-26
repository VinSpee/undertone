/* SPDX-License-Identifier: GPL-3.0-only
 * OpenPocket X — UI v4 (v36): a PLAY screen and an EDIT screen, like the big multi-effects (Helix / HX Stomp,
 * Boss GT / GX): the preset readable from a distance, the chain as keys (pale when on, dark when off), big clear settings.
 * The colours and what each means are in ui_palette.h. No flicker: nothing is cleared, every element is a fixed box
 * redrawn in one pixel stream, and only when it changed.
 *
 *  PLAY                                   EDIT (a block)
 *  +------------------------------+       +------------------------------+
 *  |::vol 80 [=]78% edited dsp 42%|       |#amp ######################on#|  band: the block, its ON / OFF key
 *  | 07    amp                    |       | <        TM26 BLU         >  |  model
 *  |        brit crunch           |       | gain                     55  |
 *  |[gt][cmp]----------------[drv]|       | ==========-----------------  |  up to 5 settings, bar + value
 *  |         [pit][sfx][syn]      |       | bass                     50  |
 *  |[amp][cab]---------------[rev]|       | ...                          |
 *  | ====     [eq][mod][dly]      |       |                              |
 *  |knob block push edit home list|       |knob select  push edit dsp 42%|
 *  +------------------------------+       +------------------------------+
 *
 * PLAY: the preset number in 58 px figures and, beside it, the selected block's label in 40 px letters: the two texts read
 * from five feet. The name is below them. The chain is two rows of six slots along a line: a block that is on is a pale
 * key on the line, a block that is off a dark key below it, so on and off are told by light and by height. A bar in the
 * lane under a row marks the selected block; a block picked up rises above the line in amber. A block's model is on its
 * page, a PUSH away. A footer names each control in pale and what it does in grey.
 *
 * Text (v43's screen): B612 for words and B612 Mono for figures (ui_fonts.h, Gamut's own). Labels and hints are in small
 * letters; a preset's, a model's and an IR's name is drawn as it is stored. The engine words its labels in capitals
 * (px_dsp.c, which the web editor reads too): the screen draws them small with UI_LC, at the moment it draws them.
 *
 * Controls (ui_buttons, ui_turn and ui_action below: the main loop and the simulator both use them):
 * KNOB = select / adjust; PUSH = open / edit / confirm; HOME = back to PLAY, on PLAY the preset list (v42), hold 0.7 s =
 * tuner, held on = diagnostics; FOOTSWITCHES = next / previous preset, both together = tuner (v42);
 * AMP CAB DLY REV MOD = that block's page (press again = on/off); FX = the next of DRV, SFX, SYN, PIT, CMP, GT, EQ in the
 * preset's chain order (v42). Hold PUSH = SAVE (into one of the 52 slots, in flash). Hold FX = MIDI.
 * Double-click PUSH on PLAY = MOVE the selected block: KNOB moves it along the chain, PUSH drops it, HOME puts it back.
 * The preset LEVEL (v36) is the GT page's 3rd setting ("PRESET LVL").
 */
#pragma once

enum { M_CHAIN, M_BLOCK, M_EDIT, M_TUNER, M_SAVE, M_MOVE, M_MIDI, M_LIST, M_DIAG };
static uint32_t st_gen;                 /* bumped on each save: the "EDITED" reference reloads */
static void st_get(uint32_t k, px_preset_t *p);
static int st_save(uint32_t k, const px_preset_t *p);
static int st_reset(uint32_t k);
static int st_saved(uint32_t k);
static void save_draw(void);
static void midi_draw(void);
static void list_draw(void);
static uint32_t ui_mode = M_CHAIN, ui_blk = PX_B_AMP, ui_item = 0;
#define UI_PAGE (ui_mode == M_BLOCK || ui_mode == M_EDIT)   /* the block page has the focus */

#include "ui_palette.h"                /* the screen's colours and what each means */
#include "ui_fonts.h"                  /* its fonts: GF_LB labels, GF_TX text, GF_NM the preset name, GF_MS and GF_MD figures,
                                        * GF_XL the preset number, GF_HE the selected block's label, GF_LG the tuner's note */

/* geometry (cell heights: GF_LB 16, GF_TX 22, GF_NM 33, GF_MS 13, GF_MD 21, GF_XL 58, GF_HE 57, GF_LG 83; from a cell's
 * top the capitals stand on row 12 of GF_LB, 17 of GF_TX, 10 of GF_MS and 16 of GF_MD) */
#define S_H      22u                   /* PLAY: the top plate */
#define S_BAN    30u                   /* PLAY: the overload band that takes its place; the page below it moves down by */
#define P_BAN_DY 7u                    /* this (uc.dy), and still ends above the footer */
#define P_NUM_Y  24u                   /* PLAY: preset number */
#define P_LBL_X  114u                  /* PLAY: the selected block's label, beside the number (the widest, "mod" on its chip: 119 px) */
#define P_LBL_W  120u
#define P_NAME_Y 85u                   /* PLAY: preset name */
#define T_Y0     118u                  /* PLAY: the chain's 1st row of slots */
#define T_ROW    48u                   /* a slot's rows, from its top: a key picked up (22), T_ON a key that is on (22), the */
#define T_ON     8u                    /* line at T_LINE (2), T_OFF a key that is off (18), T_LANE the cursor's lane (4) */
#define T_LINE   18u
#define T_OFF    24u
#define T_LANE   44u
#define T_COLS   6
#define T_PITCH  39u
#define T_W      35u
#define F_Y      222u                  /* footer (both screens) */
#define F_TY     (F_Y + 1u)            /* its text: GF_LB's 16 rows of the footer's 18 */
#define S_TY     3u                    /* the top plate's text; its figures stand 2 px lower, on the same line */
#define E_BAND   30u                   /* EDIT: block band */
#define E_TYPE_Y 36u                   /* EDIT: model row */
#define E_P0     70u                   /* EDIT: 1st setting */
#define E_ROW    30u
#define BAR_X    10u
#define BAR_W    220u
#define ST_X     172u                  /* the load figure's box: top right of PLAY, bottom right of a block page */
#define ST_W     64u                   /* (wide enough for the widest, "dsp 100%!": uisim.c checks every one) */

static void num3(char *b, uint32_t v)  /* number without leading zeros */
{
    int i = 0;
    if (v >= 100u) b[i++] = (char)('0' + v / 100u);
    if (v >= 10u) b[i++] = (char)('0' + (v / 10u) % 10u);
    b[i++] = (char)('0' + v % 10u); b[i] = 0;
}
/* the lamp: an 8 px dot, green when lit (the darker green on a housing key), dark when not */
static void ui_lamp(uint32_t x, uint32_t y, int on, uint16_t bg)
{
    ui_rbox(x, y, 8, 8, 4, !on ? C_LAMP_OFF : bg == C_HOUSING ? C_LAMP_KEY : C_LAMP, bg);
}
/* the mark: sixteen holes, the top right one the lamp (lit: sound passes) */
static void ui_grille(uint32_t x, uint32_t y, uint32_t hole, uint32_t pitch, uint32_t lamp, int lit, uint16_t col, uint16_t bg)
{
    for (uint32_t r = 0; r < 4u; r++)
        for (uint32_t c = 0; c < 4u; c++)
            if (r || c != 3u) ui_rbox(x + c * pitch, y + r * pitch, hole, hole, hole / 2u, col, bg);
    uint32_t o = (lamp - hole) / 2u;
    ui_rbox(x + 3u * pitch - o, y - o, lamp, lamp, lamp / 2u, lit ? C_LAMP : C_LAMP_OFF, bg);
}
/* the warning sign, 13 x 11: beside a warning's words, so that amber is not its only mark */
static void ui_warn(uint32_t x, uint32_t y, uint16_t fg, uint16_t bg)
{
    static const uint16_t ROW[11] = {0x0040, 0x00E0, 0x00A0, 0x0110, 0x0150, 0x0248, 0x0248, 0x0404, 0x0444, 0x0802, 0x1FFF};
    lcd_win(x, y, 13, 11);
    for (int j = 0; j < 11; j++) for (int i = 12; i >= 0; i--) lcd_px((ROW[j] >> i) & 1u ? fg : bg);
    lcd_end();
}
/* the engine's words are capitals: UI_LC with a text box's alignment draws them in small letters, as they are drawn */
#define UI_LC 4
static void ui_lower(char *s) { for (; *s; s++) if (*s >= 'A' && *s <= 'Z') *s = (char)(*s + 32); }
static uint32_t ui_box(uint32_t x, uint32_t y, uint32_t w, const char *s, const op_font *f, uint16_t fg, uint16_t bg, int align)
{
    char t[41];
    if (align & UI_LC) {
        int i = 0;
        for (; s[i] && i < 40; i++) t[i] = s[i];       /* (ft_box draws 40 characters at most) */
        t[i] = 0; ui_lower(t); s = t;
    }
    return ft_box(x, y, w, s, f, fg, bg, align & 3);
}
/* a setting's value as the engine words it ("440 MS", "+5TH", "-1.5 DB", "FAST"), in small letters with dB as a unit; a
 * note's name (SITAR's key: "C#") keeps its capital */
static void ui_value_text(char *b)
{
    int n = 0, note = b[0] >= 'A' && b[0] <= 'G' && (!b[1] || (b[1] == '#' && !b[2]));
    while (b[n]) n++;
    if (note) return;
    ui_lower(b);
    if (n > 2 && b[n - 2] == 'd' && b[n - 1] == 'b' && b[n - 3] == ' ') b[n - 1] = 'B';
}
static void ui_band(const char *title)                 /* a page's top band: its title on the plate */
{
    lcd_rect(0, 0, 240, 4, C_PLATE); lcd_rect(0, 4, 8, 22, C_PLATE);
    ft_box(8, 4, 232, title, &GF_TX, C_HOUSING, C_PLATE, 0);
    lcd_rect(0, 26, 240, 4, C_PLATE);
}
static void ui_lamp_line(uint32_t y, const char *s, const op_font *f, int on, uint16_t fg)   /* a centred line, the lamp before it */
{
    ft_box(0, y, 240, s, f, fg, C_GROUND, 1);
    ui_lamp((240u - ft_width(f, s)) / 2u - 14u, y + (f->h - 8u) / 2u, on, C_GROUND);
}
/* a value at the right of its row, in f (dim: greyed). While the knob changes it (ed), it is inverted: graphite on a housing chip */
static void ui_value(uint32_t x, uint32_t y, uint32_t w, const char *s, const op_font *f, int dim, uint16_t bg, int ed)
{
    if (!ed) { ft_box(x, y, w, s, f, dim ? C_LABEL : C_HOUSING, bg, 2); return; }
    uint32_t tw = ft_width(f, s);
    if (tw + 8u > w) tw = w - 8u;
    ft_box(x, y, w - tw - 8u, "", f, C_HOUSING, bg, 0);
    ui_rbox(x + w - tw - 8u, y, tw + 8u, f->h, 4, C_HOUSING, bg);
    ft_box(x + w - tw - 4u, y, tw, s, f, dim ? C_LABEL : C_GRAPHITE, C_HOUSING, 0);
}
/* a footer's hints, in its first w px (centred, or from 8 px in): "knob=block|push=edit|home=list" names each control in
 * housing and what it does in label grey, 4 px apart, the pairs 10 px apart. A part after '!' is amber, after '~' grey. */
static void ui_footer(const char *s, uint32_t w, int centre)
{
    uint32_t x = 8u, tw = 0;
    for (int pass = 0; pass < 2; pass++) {
        int act = 0;                                   /* the part follows a '=': what the control does */
        if (pass) { if (centre) x = tw < w ? (w - tw) / 2u : 0u; lcd_rect(0, F_TY, x, 16, C_PLATE); }
        for (const char *p = s; *p; ) {
            char t[28];
            uint16_t col = act ? C_LABEL : C_HOUSING;
            uint32_t n = 0;
            if (*p == '!') { col = C_AMBER; p++; } else if (*p == '~') { col = C_LABEL; p++; }
            while (*p && *p != '=' && *p != '|') { if (n < 27u) t[n++] = *p; p++; }
            t[n] = 0;
            uint32_t gap = *p == '=' ? 4u : *p == '|' ? 10u : 0u, k = ft_width(&GF_LB, t);
            if (!pass) tw += k + gap;
            else if (x < w) {                          /* (a part too long for what is left is cut there, as ft_box cuts) */
                if (x + k > w) { k = w - x; gap = 0; }
                ft_box(x, F_TY, k, t, &GF_LB, col, C_PLATE, 0); lcd_rect(x + k, F_TY, gap, 16, C_PLATE); x += k + gap;
            }
            act = *p == '=';
            if (*p) p++;
        }
    }
    if (x < w) lcd_rect(x, F_TY, w - x, 16, C_PLATE);
}

/* what the load figure stands for: the overload banner (BYPASS), LOADING a NAM model (amber on the MODEL row, and in the
 * corner of PLAY), a late block or little headroom left (the figure in amber; a late block adds "!") */
enum { UI_ST_NORM, UI_ST_LATE, UI_ST_BYPASS, UI_ST_LOADING, UI_ST_HIGH };
#define UI_LOAD_HIGH 80u               /* above this load the figure turns amber */

/* ---- cache of what is on screen ---- */
static struct {
    int full, screen;                  /* screen: 0 PLAY, 1 EDIT, -1 another page was drawn over it */
    uint32_t dy;                       /* PLAY: how far the page stands below its place (the overload band is taller than the plate) */
    uint32_t preset, vol; char name[14];
    int dirty;
    uint8_t tile_on[PX_NBLK], tile_sel[PX_NBLK], tile_blk[PX_NBLK], tile_mv[PX_NBLK];
    int info_b, info_on, info_mv;
    int blk, type, np, item, mode, on;
    uint8_t val[PX_NPAR];
    int hint, row_ld; uint32_t bnum;
    char status[12]; int status_kind;
} uc;
static void ui_invalidate(void) { uc.full = 1; }
static int ui_np(void) { return px_nparams((int)ui_blk, PRESET.type[ui_blk]); }
static int ui_nitems(void) { return 2 + ui_np(); }     /* 0 = type, 1 = on/off, 2.. = parameters */
static const char *ui_block_name(int b) { return b == PX_B_SYN ? "SYNTH" : px_block_name(b); }   /* (the documents' name) */

/* v42: a setting that picks from a list (NAM MODEL, USER IR) steps one item a detent, skips the empty slots and shows its
 * place in the list. The stored value stays 0..100 (px_nam_knob, px_ir_knob): presets do not change. */
static int ui_list_n(int b, int t, int k)              /* the list's length, 0: not a list */
{
    if (k != 0) return 0;
    return b == PX_B_AMP && t == PX_AMP_NAM ? PX_NAM_N : b == PX_B_CAB && t == PX_CAB_IR ? PX_IR_N : 0;
}
static int ui_list_of(int b, int v) { return b == PX_B_AMP ? px_nam_model(v) : px_ir_slot(v); }
static int ui_list_val(int b, int i) { return b == PX_B_AMP ? px_nam_knob(i) : px_ir_knob(i); }
static int ui_list_name(int b, int i, char *nm12) { return b == PX_B_AMP ? px_nam_name(i, nm12) : px_ir_name(i, nm12); }
static int ui_list_place(int b, int n, int cur, int *count)   /* cur's place among the filled items (1..), 0: an empty one */
{
    char nm[12];
    int at = 0;
    *count = 0;
    for (int i = 0; i < n; i++) if (ui_list_name(b, i, nm)) { ++*count; if (i == cur) at = *count; }
    return at;
}
static void ui_order_fix(void) { if (!px_order_valid(PRESET.order)) px_order_default(PRESET.order); }
static int ui_pos_of(uint32_t b) { for (int i = 0; i < PX_NBLK; i++) if (PRESET.order[i] == b) return i; return 0; }

static int bat_percent(int mv)         /* a Li-ion cell at rest: 4.15 V full, 3.30 V empty */
{
    static const int16_t V[12] = {3300, 3500, 3630, 3690, 3720, 3750, 3790, 3840, 3900, 3970, 4050, 4150};
    static const int8_t P[12] = {0, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100};
    if (mv <= V[0]) return 0;
    for (int i = 1; i < 12; i++) if (mv < V[i]) return P[i - 1] + (P[i] - P[i - 1]) * (mv - V[i - 1]) / (V[i] - V[i - 1]);
    return 100;
}
/* battery, in the top plate of PLAY: a cell icon + "78%" (the charge amber from 30 % down, the figure from 15 %), "usb" when the 5 V supply is there, an empty cell and
 * "--" while there is no reading (v37: shown, not hidden: the raw readings are on the tuner page, bat_raw) */
#define BAT_X 73u                      /* the cell 20 x 10 and its tip, then the figure from BAT_X + 25: 59 px in all */
static void draw_battery(int force)
{
    static int last = -100;
    int usb = bat_usb_mv > 4300, pct = bat_pct >= 0 ? bat_pct : bat_mv ? bat_percent(bat_mv) : -1, key = usb ? 1000 + (pct < 0 ? 0 : pct) : pct;
    if (!force && key == last) return;
    last = key;
    const uint32_t x = BAT_X, y = 6u;
    uint16_t c = !usb && pct <= 30 ? C_AMBER : C_HOUSING;
    lcd_rect(x, 0, 25, y, C_PLATE); lcd_rect(x, y + 10u, 25, S_H - y - 10u, C_PLATE);
    lcd_rect(x, y, 20, 1, C_LABEL); lcd_rect(x, y + 9u, 20, 1, C_LABEL);
    lcd_rect(x, y + 1u, 1, 8, C_LABEL); lcd_rect(x + 19u, y + 1u, 1, 8, C_LABEL);
    lcd_rect(x + 20u, y + 3u, 2, 4, C_LABEL); lcd_rect(x + 20u, y, 2, 3, C_PLATE); lcd_rect(x + 20u, y + 7u, 2, 3, C_PLATE);
    lcd_rect(x + 22u, y, 3, 10, C_PLATE);
    uint32_t f = pct < 0 ? (usb ? 16u : 0u) : (uint32_t)pct * 16u / 100u;
    if (f) lcd_rect(x + 2u, y + 2u, f, 6, c);
    if (f < 16u) lcd_rect(x + 2u + f, y + 2u, 16u - f, 6, C_PLATE);
    lcd_rect(x + 1u, y + 1u, 1, 8, C_PLATE); lcd_rect(x + 18u, y + 1u, 1, 8, C_PLATE);
    lcd_rect(x + 2u, y + 1u, 16, 1, C_PLATE); lcd_rect(x + 2u, y + 8u, 16, 1, C_PLATE);
    char b[8] = "usb";
    if (!usb && pct < 0) { b[0] = '-'; b[1] = '-'; b[2] = 0; }
    else if (!usb) { num3(b, (uint32_t)pct); int i = 0; while (b[i]) i++; b[i] = '%'; b[i + 1] = 0; }
    const op_font *ft = usb ? &GF_LB : &GF_MS;
    uint32_t ty = usb ? S_TY : S_TY + 2u;              /* (the figures' cell is the shorter one: both stand on one line) */
    lcd_rect(x + 25u, 0, 34, ty, C_PLATE);
    ft_box(x + 25u, ty, 34, b, ft, usb ? C_HOUSING : pct < 0 ? C_LABEL : pct <= 15 ? C_AMBER : C_HOUSING, C_PLATE, 0);
    lcd_rect(x + 25u, ty + ft->h, 34, S_H - ty - ft->h, C_PLATE);
}

/* ---- status bar / footer, shared ---- */
static px_preset_t ui_ref;             /* what the current slot holds */
static int ui_dirty(void)              /* the preset differs from what its slot holds (hold PUSH to save) */
{
    static uint32_t ref_slot = ~0u, ref_gen = ~0u;
    if (ref_slot != cur_preset || ref_gen != st_gen) { st_get(cur_preset, &ui_ref); ref_slot = cur_preset; ref_gen = st_gen; }
    return memcmp(&ui_ref, &PRESET, sizeof ui_ref) != 0;
}
static void draw_status(int force)    /* PLAY's top plate: the mark, the volume, the battery, "edited"; the load figure is ui_status's */
{
    if (uc.screen != 0) return;        /* (EDIT: its band takes the top) */
    if (uc.status_kind == UI_ST_BYPASS) {                /* overload: an amber band in the plate's place, the sign and the word */
        if (force) {
            ui_warn(8, 9, C_GRAPHITE, C_AMBER);
            ft_box(28, 4, 96, "overload", &GF_TX, C_GRAPHITE, C_AMBER, 0);
            ft_box(124, 8, 108, "sound bypassed", &GF_LB, C_GRAPHITE, C_AMBER, 2);
        }
        return;
    }
    if (force || uc.vol != master_vol) {
        char b[4]; num3(b, master_vol);
        if (force) ft_box(24, S_TY, 20, "vol", &GF_LB, C_LABEL, C_PLATE, 0);
        ft_box(48, S_TY + 2u, 24, b, &GF_MS, C_HOUSING, C_PLATE, 0);
        ui_grille(6, 4, 3, 4, 5, master_vol != 0u, C_RIM, C_PLATE);   /* (its lamp: sound passes) */
        uc.vol = master_vol;
    }
    draw_battery(force);
    int d = ui_dirty();                                /* EDITED: the sound differs from its saved slot */
    if (force || d != uc.dirty) { ft_box(BAT_X + 59u, S_TY, ST_X - BAT_X - 59u, d ? "edited" : "", &GF_LB, C_AMBER, C_PLATE, 0); uc.dirty = d; }
}
/* the DSP load, from the main loop: "dsp 42%", "dsp 88%!" (a block ran late), "safe 42%", "peak 150%" (bypassed). v42: which
 * cores ran is on the diagnostics page (ui_dg). Every text fits ST_W (firmware/apps/gamut/tests/uisim.c checks them all; the
 * peak is shown in PLAY's footer, with what to do). */
static struct {                        /* the main loop's last DSP figures, for the diagnostics page */
    uint32_t load, peak, cl[2];        /* the load (the peak while bypassed), the peak since the preset, each core's (layer split) */
    uint8_t cores, split, guard, late, bypass;   /* cores: 0 C0, 1 C1, 2 both ("2C"); guard: the safety bypass's limit, % */
} ui_dg = {.guard = 85};
static void ui_load_text(char *c, uint32_t l, int safe, int bypass, int late)
{
    if (l > 999u) l = 999u;
    c[0] = 0;
    b_str(c, safe ? "safe " : bypass ? "peak " : "dsp ");
    b_num(c, l); b_str(c, "%");
    if (!safe && !bypass && late) b_str(c, "!");
}
static int ui_load_kind(uint32_t l, int safe, int bypass, int late, int loading)
{
    return loading ? UI_ST_LOADING : bypass ? UI_ST_BYPASS : late ? UI_ST_LATE : !safe && l > UI_LOAD_HIGH ? UI_ST_HIGH : UI_ST_NORM;
}
/* the load figure in its box: its word in label grey, its figure in the figures' face, amber when it warns ("dsp" "88%!");
 * a text that is not a word and a figure is drawn as it is (LOADING; the Bluetooth test image scrolls its states here) */
static void ui_load_box(uint32_t y, const char *s, int kind)
{
    int n = 0, sp = -1;
    int warn = kind == UI_ST_LATE || kind == UI_ST_HIGH || kind == UI_ST_LOADING;
    while (s[n]) { if (s[n] == ' ') sp = n; n++; }
#if OP_BLE_TEST
    int fig = 0;
#else
    int fig = sp > 0 && sp < 11 && s[sp + 1];
#endif
    for (int i = sp + 1; fig && s[i]; i++) if (!((s[i] >= '0' && s[i] <= '9') || s[i] == '%' || s[i] == '!')) fig = 0;
    if (!fig) { ft_box(ST_X, y, ST_W, s, &GF_LB, warn ? C_AMBER : C_LABEL, C_PLATE, 2); return; }
    char w[12];
    for (n = 0; n < sp; n++) w[n] = s[n];
    w[n] = 0;
    uint32_t fw = ft_width(&GF_MS, s + sp + 1), fx = ST_X + ST_W - fw;
    if (fw + 2u > ST_W) { fw = ST_W - 2u; fx = ST_X + 2u; }
    ft_box(ST_X, y, fx - 2u - ST_X, w, &GF_LB, C_LABEL, C_PLATE, 2);
    lcd_rect(fx - 2u, y, fw + 2u, 2, C_PLATE); lcd_rect(fx - 2u, y + 2u, 2, 13, C_PLATE);
    ft_box(fx, y + 2u, fw, s + sp + 1, &GF_MS, warn ? C_AMBER : C_HOUSING, C_PLATE, 0);
    lcd_rect(fx - 2u, y + 15u, fw + 2u, 1, C_PLATE);
}
static void ui_status(const char *s, int kind)
{
    if (ui_mode == M_TUNER || ui_mode == M_SAVE || ui_mode == M_MIDI || ui_mode == M_LIST || ui_mode == M_DIAG) return;
    int same = uc.status_kind == kind;
    for (int i = 0; i < 12; i++) { if (uc.status[i] != s[i]) same = 0; if (!s[i]) break; }
    if (same && !uc.full) return;
    int was = uc.status_kind;
    for (int i = 0; i < 12; i++) { uc.status[i] = s[i]; if (!s[i]) break; }
    uc.status[11] = 0;
    uc.status_kind = kind;
    if ((was == UI_ST_BYPASS) != (kind == UI_ST_BYPASS)) { uc.full = 1; return; }   /* the band comes or goes: redraw the page */
    if (kind == UI_ST_BYPASS) { uc.hint = -1; return; }                              /* (on PLAY the footer shows the peak; a block page's amber footer has the instruction alone) */
    int ld = kind == UI_ST_LOADING && uc.screen == 0;     /* on a block page the MODEL row says it instead */
    ui_load_box(uc.screen ? F_TY : S_TY, ld ? "loading" : uc.status, !ld && kind == UI_ST_LOADING ? UI_ST_NORM : kind);
}
static void draw_hint(int force)
{
    int h = (int)ui_mode, alert = uc.status_kind == UI_ST_BYPASS;
    int save = !alert && h == M_CHAIN && uc.dirty;       /* EDITED shows on PLAY: the footer names SAVE */
    int key = h | alert << 4 | save << 5;
    if (!force && uc.hint == key) return;
    uc.hint = key;
    if (alert && uc.screen) {                            /* overload on a block page: its whole footer turns amber, the sign and what to do */
        lcd_rect(0, F_Y, 240, 1, C_AMBER); lcd_rect(0, F_TY + 16u, 240, 1, C_AMBER);
        lcd_rect(0, F_TY, 8, 16, C_AMBER); lcd_rect(8, F_TY, 13, 3, C_AMBER);
        ui_warn(8, F_TY + 3u, C_GRAPHITE, C_AMBER);
        lcd_rect(8, F_TY + 14u, 13, 2, C_AMBER); lcd_rect(21, F_TY, 7, 16, C_AMBER);
        ft_box(28, F_TY, 212, "overload: turn a block off", &GF_LB, C_GRAPHITE, C_AMBER, 0);
        return;
    }
    if (alert) {                                         /* on PLAY: what to do, and the peak ("peak 142%") with its figure in amber */
        char t[40]; int sp = 0;
        t[0] = 0; b_str(t, "turn a block off");
        while (uc.status[sp] && uc.status[sp] != ' ') sp++;
        if (uc.status[sp]) { char w[12]; for (int i = 0; i < sp; i++) w[i] = uc.status[i]; w[sp] = 0; b_str(t, "="); b_str(t, w); b_str(t, "|!"); b_str(t, uc.status + sp + 1); }
        ui_footer(t, 240, 1);
        return;
    }
    ui_footer(save ? "push=edit|hold push=!save"
              : h == M_MOVE ? "knob=move|push=drop|home=undo"
              : h == M_EDIT ? "knob=value|push=done"
              : h == M_BLOCK ? "knob=select|push=edit"
              : "knob=block|push=edit|home=list", uc.screen ? ST_X - 2u : 240u, !uc.screen);
}

/* ===================================================== PLAY ======== */
/* beside the number, the selected block's label, 40 px tall: pale while the block is on, grey while it is off, graphite
 * on an amber chip while it is moved */
static void draw_label(int force)
{
    int b = (int)ui_blk, on = PRESET.on[b] != 0, mv = ui_mode == M_MOVE;
    if (!force && uc.info_b == b && uc.info_on == on && uc.info_mv == mv) return;
    char t[8];
    uint32_t n = 0, y = P_NUM_Y + uc.dy;
    for (const char *s = px_block_label(b); *s && n < 7u; s++) t[n++] = *s;
    t[n] = 0; ui_lower(t);
    uint32_t tw = ft_width(&GF_HE, t);
    if (mv && tw + 10u <= P_LBL_W) {
        ui_rbox(P_LBL_X, y, tw + 10u, 57, 6, C_AMBER, C_GROUND);
        ft_box(P_LBL_X + 5u, y, tw, t, &GF_HE, C_GRAPHITE, C_AMBER, 0);
        lcd_rect(P_LBL_X + tw + 10u, y, P_LBL_W - tw - 10u, 57, C_GROUND);
    } else ft_box(P_LBL_X, y, P_LBL_W, t, &GF_HE, on ? C_HOUSING : C_LABEL, C_GROUND, 0);
    uc.info_b = b; uc.info_on = on; uc.info_mv = mv;
}
static void draw_play_top(int force)
{
    if (force || uc.preset != cur_preset) {
        char b[4]; uint32_t n = cur_preset + 1u;
        b[0] = (char)('0' + n / 10u); b[1] = (char)('0' + n % 10u); b[2] = 0;
        ft_box(6, P_NUM_Y + uc.dy, 98, b, &GF_XL, C_HOUSING, C_GROUND, 0);
        uc.preset = cur_preset;
    }
    draw_label(force);
    int nchg = force;
    for (int i = 0; i < 14; i++) if (uc.name[i] != PRESET.name[i]) nchg = 1;
    if (nchg) {
        ft_box(0, P_NAME_Y + uc.dy, 240, PRESET.name, &GF_NM, C_HOUSING, C_GROUND, 1);
        for (int i = 0; i < 14; i++) uc.name[i] = PRESET.name[i];
    }
}
/* ---- the chain: slot i shows block PRESET.order[i], two rows of six along a line ---- */
static uint32_t tile_x(int i) { return 4u + (uint32_t)(i % T_COLS) * T_PITCH; }                 /* its key's left */
static uint32_t tile_y(int i) { return T_Y0 + uc.dy + (uint32_t)(i / T_COLS) * T_ROW; }         /* its slot's top */
static void tile_line(uint32_t x, uint32_t y, uint32_t w, uint32_t h)   /* a slot's first h rows, w px of them: ground, and the line where it runs */
{
    if (h <= T_LINE) { lcd_rect(x, y, w, h, C_GROUND); return; }
    lcd_rect(x, y, w, T_LINE, C_GROUND); lcd_rect(x, y + T_LINE, w, 2, C_LABEL);
    lcd_rect(x, y + T_LINE + 2u, w, h - T_LINE - 2u, C_GROUND);
}
static void draw_lane(int i)           /* the lane under a slot: the bar under the selected block (the knob's turn redraws no more) */
{
    int sel = PRESET.order[i] == ui_blk;
    lcd_rect(tile_x(i), tile_y(i) + T_LANE, T_W, T_ROW - T_LANE, !sel ? C_GROUND : ui_mode == M_MOVE ? C_AMBER : C_HOUSING);
    uc.tile_sel[i] = (uint8_t)sel;
}
/* a slot: its key on the line and pale while its block is on, below the line and dark while off, above it and amber while
 * it is moved; the line where the key does not hide it; the bar in the lane under the selected block */
static void draw_tile(int i)
{
    int b = PRESET.order[i];
    uint32_t x = tile_x(i), y = tile_y(i);
    int on = PRESET.on[b] != 0, sel = (b == (int)ui_blk), mv = sel && ui_mode == M_MOVE;
    uint32_t ky = mv ? 0u : on ? T_ON : T_OFF, kh = on || mv ? 22u : 18u;
    uint16_t bg = mv ? C_AMBER : on ? C_HOUSING : C_KEY, fg = on || mv ? C_GRAPHITE : C_LABEL;
    tile_line(x - 4u, y, 4, T_ROW);                    /* beside the key the line runs on, to the screen's edge after the last */
    if (i % T_COLS == T_COLS - 1) tile_line(x + T_W, y, 240u - x - T_W, T_ROW);
    tile_line(x, y, T_W, ky);                          /* (above a key that is off, the line runs past) */
    ui_rbox(x, y + ky, T_W, kh, 4, bg, C_GROUND);
    ui_box(x + 2u, y + ky + (kh - 16u) / 2u, T_W - 4u, px_block_label(b), &GF_LB, fg, bg, 1 | UI_LC);
    lcd_rect(x, y + ky + kh, T_W, T_LANE - ky - kh, C_GROUND);
    uc.tile_on[i] = (uint8_t)on; uc.tile_blk[i] = (uint8_t)b; uc.tile_mv[i] = (uint8_t)mv;
    draw_lane(i);
}
static void draw_tiles(int force)
{
    ui_order_fix();
    for (int i = 0; i < PX_NBLK; i++) {
        int b = PRESET.order[i], on = PRESET.on[b] != 0, sel = (b == (int)ui_blk), mv = sel && ui_mode == M_MOVE;
        if (force || uc.tile_blk[i] != b || uc.tile_on[i] != on || uc.tile_mv[i] != mv) draw_tile(i);
        else if (uc.tile_sel[i] != sel) draw_lane(i);
    }
}

/* ===================================================== EDIT ======== */
static void draw_band(int force)       /* the preset number, the block's name, the ON / OFF key with its lamp (item 1) */
{
    int on = PRESET.on[ui_blk] != 0, sel = (UI_PAGE && ui_item == 1u);
    if (!(force || uc.blk != (int)ui_blk || uc.bnum != cur_preset || uc.on != on || (uc.item == 1) != sel)) return;
    if (force || uc.blk != (int)ui_blk || uc.bnum != cur_preset) {   /* (the preset number: a change over MIDI does not leave the page) */
        char n[4]; num3(n, cur_preset + 1u);
        lcd_rect(0, 0, 240, 4, C_PLATE); lcd_rect(0, 27, 240, E_BAND - 27u, C_PLATE); lcd_rect(0, 4, 8, 23, C_PLATE);
        lcd_rect(8, 4, 24, 23, C_PLATE); ui_rbox(8, 6, 24, 19, 5, C_KEY, C_PLATE);
        ft_box(10, 11, 20, n, &GF_MS, C_HOUSING, C_KEY, 1);
        lcd_rect(32, 4, 4, 23, C_PLATE);
        ui_box(36, 4, 136, ui_block_name((int)ui_blk), &GF_TX, C_HOUSING, C_PLATE, UI_LC);
        lcd_rect(36, 26, 136, 1, C_PLATE);
        lcd_rect(172, 4, 4, 23, C_PLATE); lcd_rect(232, 4, 8, 23, C_PLATE);
        uc.bnum = cur_preset;
    }
    uint16_t ring = sel ? C_HOUSING : C_PLATE, key = on ? C_HOUSING : C_KEY;
    ui_rbox(176, 4, 56, 23, 6, ring, C_PLATE);                 /* the selection ring, 1 px of plate, the key (as a tile on PLAY) */
    ui_rbox(177, 5, 54, 21, 5, C_PLATE, ring);
    ui_rbox(178, 6, 52, 19, 5, key, C_PLATE);
    ui_lamp(184, 12, on, key);
    ft_box(194, 9, 32, on ? "on" : "off", &GF_LB, on ? C_GRAPHITE : C_LABEL, key, 1);
}
static void draw_type(void)
{
    int sel = (UI_PAGE && ui_item == 0u), ed = sel && ui_mode == M_EDIT, many = px_ntypes((int)ui_blk) > 1;
    uint16_t bg = ed ? C_HOUSING : sel ? C_KEY : C_GROUND, fg = ed ? C_GRAPHITE : C_HOUSING, ar = ed ? C_GRAPHITE : C_LABEL;   /* (while it is changed: inverted) */
    ui_rbox(4, E_TYPE_Y - 2u, 232, 28, 5, bg, C_GROUND);
    ft_box(8, E_TYPE_Y + 1u, 20, sel && many ? "<" : "", &GF_TX, ar, bg, 1);   /* (v42: no arrows on a block of one model) */
    ft_box(28, E_TYPE_Y + 1u, 184, px_type_name((int)ui_blk, PRESET.type[ui_blk]), &GF_TX, fg, bg, 1);
    ft_box(212, E_TYPE_Y + 1u, 20, sel && many ? ">" : "", &GF_TX, ar, bg, 1);
}
static int ui_loading_row(int k)       /* the NAM amp's MODEL row while its model loads */
{
    return uc.status_kind == UI_ST_LOADING && ui_blk == PX_B_AMP && PRESET.type[PX_B_AMP] == PX_AMP_NAM && k == 0;
}
static void ui_hz_text(char *b, int off)   /* v42: USER IR's cut frequencies with their unit: "89 Hz", "6.3 kHz", "off" */
{
    uint32_t hz = 0;
    for (int i = 0; b[i]; i++) hz = hz * 10u + (uint32_t)(b[i] - '0');
    b[0] = 0;
    if (off) { b_str(b, "off"); return; }
    if (hz < 1000u) { b_num(b, hz); b_str(b, " Hz"); return; }
    hz = (hz + 50u) / 100u;
    b_num(b, hz / 10u); b_str(b, "."); b_num(b, hz % 10u); b_str(b, " kHz");
}
#define E_LIST_X 96u                   /* a list setting: its place at the left, the item's name from here */
#define E_VAL_X  124u                  /* any other setting: its name up to here, its value from here ("-15.0 dB" in its chip: 104 px) */
static void draw_bar(int k)            /* value + bar: the only thing that moves while adjusting */
{
    uint32_t y = E_P0 + (uint32_t)k * E_ROW;
    int sel = (UI_PAGE && (int)ui_item == k + 2), ed = sel && ui_mode == M_EDIT, t = PRESET.type[ui_blk];
    int ln = ui_list_n((int)ui_blk, t, k), ld = ui_loading_row(k);
    uint16_t bg = sel ? C_KEY : C_GROUND, fc = sel ? C_HOUSING : C_LABEL;
    uint32_t v = PRESET.p[ui_blk][k]; if (v > 100u) v = 100u;
    char b[16];
    uc.val[k] = (uint8_t)v;
    if (ln) {                          /* "model 6/14", the name, one segment per filled item */
        int cur = ui_list_of((int)ui_blk, (int)v), n, at = ui_list_place((int)ui_blk, ln, cur, &n);
        char nm[12];
        b[0] = 0; b_str(b, px_param_name((int)ui_blk, t, k)); b_str(b, " ");
        if (at) b_num(b, (uint32_t)at); else b_str(b, "-");
        b_str(b, "/"); b_num(b, (uint32_t)n);
        ui_box(BAR_X, y + 6u, E_LIST_X - BAR_X, ld ? "loading" : b, &GF_LB, ld ? C_AMBER : sel ? C_HOUSING : C_LABEL, bg, UI_LC);
        ui_list_name((int)ui_blk, cur, nm);
        ui_value(E_LIST_X, y + 1u, 230u - E_LIST_X, nm, &GF_TX, ld, bg, ed);   /* (the new name stays grey until it plays) */
        uint32_t sw = n ? BAR_W / (uint32_t)n : BAR_W;
        for (int i = 0; i < n; i++) {
            lcd_rect(BAR_X + (uint32_t)i * sw, y + 24u, sw - 1u, 4, i + 1 == at ? fc : C_RIM);
            lcd_rect(BAR_X + (uint32_t)i * sw + sw - 1u, y + 24u, 1, 4, bg);
        }
        if (sw * (uint32_t)n < BAR_W) lcd_rect(BAR_X + sw * (uint32_t)n, y + 24u, BAR_W - sw * (uint32_t)n, 4, n ? bg : C_RIM);
        return;
    }
    if (!px_param_text((int)ui_blk, t, k, (int)v, b)) num3(b, v);   /* "+5TH", "440 MS"... */
    else if (ui_blk == PX_B_CAB && t == PX_CAB_IR && k >= 1) ui_hz_text(b, k == 2 && v == 0u);
    else ui_value_text(b);
    ui_value(E_VAL_X, y + 2u, 230u - E_VAL_X, b, &GF_MD, 0, bg, ed);
    uint32_t w = v * BAR_W / 100u;
    if (w) lcd_rect(BAR_X, y + 24u, w, 4, fc);
    if (w < BAR_W) lcd_rect(BAR_X + w, y + 24u, BAR_W - w, 4, C_RIM);
}
static void draw_row(int k)            /* one full setting row */
{
    uint32_t y = E_P0 + (uint32_t)k * E_ROW;
    if (k >= ui_np()) { lcd_rect(0, y, 240, E_ROW, C_GROUND); return; }
    int sel = (UI_PAGE && (int)ui_item == k + 2);
    uint16_t bg = sel ? C_KEY : C_GROUND;
    ui_rbox(4, y, 232, E_ROW - 1u, 5, bg, C_GROUND);
    lcd_rect(0, y + E_ROW - 1u, 240, 1, C_GROUND);
    if (sel) lcd_rect(4, y + 6u, 3, 14, C_HOUSING);              /* the selection's marker */
    int ld = ui_loading_row(k);
    if (!ui_list_n((int)ui_blk, PRESET.type[ui_blk], k))         /* (a list setting draws its label with its place) */
        ui_box(BAR_X, y + 6u, E_VAL_X - BAR_X, ld ? "loading" : px_param_name((int)ui_blk, PRESET.type[ui_blk], k), &GF_LB, ld ? C_AMBER : sel ? C_HOUSING : C_LABEL, bg, UI_LC);
    if (k == 0) uc.row_ld = ld;
    draw_bar(k);
}
static void draw_item(int it)
{
    if (it == 0) draw_type();
    else if (it == 1) draw_band(1);
    else draw_row(it - 2);
}
static void draw_edit(int force)
{
    int type = PRESET.type[ui_blk], np = ui_np(), on = PRESET.on[ui_blk] != 0;
    if (force || uc.blk != (int)ui_blk || uc.type != type) {
        draw_band(1); draw_type();
        lcd_rect(0, E_TYPE_Y + 26u, 240, E_P0 - E_TYPE_Y - 26u, C_GROUND);
        for (int k = 0; k < PX_NPAR; k++) draw_row(k);
        lcd_rect(0, E_P0 + PX_NPAR * E_ROW, 240, F_Y - (E_P0 + PX_NPAR * E_ROW), C_GROUND);
        uc.blk = (int)ui_blk; uc.type = type; uc.np = np; uc.item = (int)ui_item; uc.mode = (int)ui_mode; uc.on = on;
        return;
    }
    if (uc.item != (int)ui_item || uc.mode != (int)ui_mode) {   /* highlight moved: 2 items only */
        int old = uc.item;
        uc.item = (int)ui_item; uc.mode = (int)ui_mode;
        if (old != (int)ui_item) draw_item(old);
        draw_item((int)ui_item);
    }
    if (uc.on != on || uc.bnum != cur_preset) { draw_band(1); uc.on = on; }
    if (np > 0 && ui_loading_row(0) != uc.row_ld) draw_row(0);
    for (int k = 0; k < np; k++) if (uc.val[k] != PRESET.p[ui_blk][k]) draw_bar(k);
}

/* ---- render: sends only what changed to the screen ---- */
static void ui_render(void)
{
    if (ui_mode == M_TUNER || ui_mode == M_DIAG) return;   /* (the main loop draws them every 100 ms: tuner_draw, diag_draw) */
    if (ui_mode == M_SAVE) { save_draw(); return; }
    if (ui_mode == M_MIDI) { midi_draw(); return; }
    if (ui_mode == M_LIST) { list_draw(); return; }
    int scr = UI_PAGE ? 1 : 0;
    if (scr != uc.screen) { uc.screen = scr; uc.full = 1; }
    int f = uc.full;
    if (f) {                                                     /* page change: background drawn once */
        if (scr == 0) {
            int ban = uc.status_kind == UI_ST_BYPASS;
            uint32_t top = ban ? S_BAN : S_H, y;
            uc.dy = ban ? P_BAN_DY : 0u;
            y = P_NUM_Y + uc.dy;
            lcd_rect(0, 0, 240, top, ban ? C_AMBER : C_PLATE);
            lcd_rect(0, top, 240, y - top, C_GROUND);
            lcd_rect(0, y, 6, 58, C_GROUND); lcd_rect(104, y, P_LBL_X - 104u, 58, C_GROUND);
            lcd_rect(P_LBL_X, y + 57u, P_LBL_W, 1, C_GROUND); lcd_rect(P_LBL_X + P_LBL_W, y, 240u - P_LBL_X - P_LBL_W, 58, C_GROUND);
            lcd_rect(0, y + 58u, 240, P_NAME_Y - P_NUM_Y - 58u, C_GROUND);
            lcd_rect(0, T_Y0 + uc.dy + 2u * T_ROW, 240, F_Y - (T_Y0 + uc.dy + 2u * T_ROW), C_GROUND);
        } else {
            lcd_rect(0, E_BAND, 240, 4, C_GROUND);
            lcd_rect(0, E_BAND + 4u, 4, F_Y - E_BAND - 4u, C_GROUND); lcd_rect(236, E_BAND + 4u, 4, F_Y - E_BAND - 4u, C_GROUND);
        }
        lcd_rect(0, F_Y, 240, 1, C_PLATE); lcd_rect(0, F_TY + 16u, 240, 240u - F_TY - 16u, C_PLATE);
        if (scr) { lcd_rect(ST_X - 2u, F_TY, 2, 16, C_PLATE); lcd_rect(ST_X + ST_W, F_TY, 240u - ST_X - ST_W, 16, C_PLATE); }
        uc.full = 0;
    }
    if (scr == 0) {
        draw_status(f);
        draw_play_top(f);
        draw_tiles(f);
    } else draw_edit(f);
    draw_hint(f);
    if (f) { char s[12]; for (int i = 0; i < 12; i++) s[i] = uc.status[i]; uc.full = 1; ui_status(s, uc.status_kind); uc.full = 0; }
}

/* ---- actions ---- */
static void ui_enter_block(uint32_t b)
{
    if (ui_blk == b && UI_PAGE) PRESET.on[b] ^= 1u;   /* 2nd press on the same button: on/off */
    ui_blk = b; ui_mode = M_BLOCK; ui_item = 0;
}
static uint8_t mv_orig[PX_NBLK];            /* the order before the move (HOME puts it back) */
static void ui_move_start(void)
{
    ui_order_fix();
    for (int i = 0; i < PX_NBLK; i++) mv_orig[i] = PRESET.order[i];
    ui_mode = M_MOVE;
}
static void ui_move_drop(void) { ui_mode = M_CHAIN; }
static void ui_move_cancel(void) { for (int i = 0; i < PX_NBLK; i++) PRESET.order[i] = mv_orig[i]; ui_mode = M_CHAIN; }
static void ui_knob(int dd, int fast)
{
    if (ui_mode == M_CHAIN) {                          /* along the chain, in the preset's order */
        ui_order_fix();
        ui_blk = PRESET.order[(ui_pos_of(ui_blk) + PX_NBLK + dd) % PX_NBLK];
    } else if (ui_mode == M_MOVE) {                    /* the grabbed block swaps with its neighbour */
        int i = ui_pos_of(ui_blk), j = i + (dd > 0 ? 1 : -1);
        if (j >= 0 && j < PX_NBLK) { uint8_t t = PRESET.order[i]; PRESET.order[i] = PRESET.order[j]; PRESET.order[j] = t; }
    } else if (ui_mode == M_BLOCK) {                   /* v42: in the order drawn: ON (item 1) at the top, MODEL, the settings */
        int n = ui_nitems(), p = ui_item < 2u ? 1 - (int)ui_item : (int)ui_item;
        p = (p + n + dd) % n;
        ui_item = (uint32_t)(p < 2 ? 1 - p : p);
    } else if (ui_mode == M_EDIT) {
        if (ui_item == 0u) {
            int nt = px_ntypes((int)ui_blk);
            PRESET.type[ui_blk] = (uint8_t)((PRESET.type[ui_blk] + nt + dd) % nt);
        } else if (ui_item >= 2u) {
            int k = (int)ui_item - 2, t = PRESET.type[ui_blk], ln = ui_list_n((int)ui_blk, t, k);
            if (ln) {                                  /* one filled item a detent, at any speed; it stops at the ends */
                char nm[12];
                for (int i = ui_list_of((int)ui_blk, PRESET.p[ui_blk][k]) + dd; i >= 0 && i < ln; i += dd)
                    if (ui_list_name((int)ui_blk, i, nm)) { PRESET.p[ui_blk][k] = (uint8_t)ui_list_val((int)ui_blk, i); break; }
                return;
            }
            int v = PRESET.p[ui_blk][k] + dd * (fast ? 5 : 1);
            if (v < 0) v = 0;
            if (v > 100) v = 100;
            PRESET.p[ui_blk][k] = (uint8_t)v;
        }
    }
}
static void ui_push(void)
{
    if (ui_mode == M_MOVE) { ui_move_drop(); return; }
    if (ui_mode == M_CHAIN) { ui_mode = M_BLOCK; ui_item = 0; }
    else if (ui_mode == M_BLOCK) {
        if (ui_item == 1u) PRESET.on[ui_blk] ^= 1u;
        else ui_mode = M_EDIT;
    } else ui_mode = M_BLOCK;
}
static void ui_home(void) { if (ui_mode == M_MOVE) ui_move_cancel(); ui_mode = M_CHAIN; ui_item = 0; }

/* ===================================================== save page ======== */
/* hold PUSH: SAVE. KNOB picks the slot (01..52, then "FACTORY": this slot back to its factory preset), PUSH saves,
 * HOME cancels. Saving to another slot copies the sound there and moves to it. */
#define SV_FACTORY 52u
static uint32_t sv_dest, sv_shown = ~0u;
static void save_open(void)
{
    ui_mode = M_SAVE; sv_dest = cur_preset; sv_shown = ~0u;
    lcd_rect(0, 0, 240, 240, C_GROUND);
    ui_band("save preset");
    ft_box(0, 40, 240, PRESET.name, &GF_TX, C_HOUSING, C_GROUND, 1);
    lcd_rect(20, 70, 200, 1, C_RIM);
    lcd_rect(0, F_Y, 240, 240u - F_Y, C_PLATE);
}
static void save_draw(void)
{
    if (sv_shown == sv_dest) return;
    sv_shown = sv_dest;
    char b[20];
    int restore = sv_dest == SV_FACTORY, can = !restore || st_saved(cur_preset);   /* (v42: nothing to restore: PUSH does nothing) */
    ui_footer(!can ? "knob=slot|home=back" : restore ? "push=restore|home=back" : "knob=slot|push=save|home=back", 240, 1);
    /* v42: the pedal cannot rename: a copy keeps the name (the web editor renames) */
    ft_box(0, 190, 240, restore || sv_dest == cur_preset ? "" : "name stays: rename in the editor", &GF_LB, C_LABEL, C_GROUND, 1);
    if (restore) {
        ft_box(0, 76, 240, "", &GF_XL, C_HOUSING, C_GROUND, 1);
        ft_box(0, 138, 240, "restore factory", &GF_TX, C_HOUSING, C_GROUND, 1);
        b[0] = 's'; b[1] = 'l'; b[2] = 'o'; b[3] = 't'; b[4] = ' ';
        b[5] = (char)('0' + (cur_preset + 1u) / 10u); b[6] = (char)('0' + (cur_preset + 1u) % 10u); b[7] = 0;
        ft_box(0, 164, 240, can ? b : "already the factory sound", &GF_LB, C_LABEL, C_GROUND, 1);
        return;
    }
    px_preset_t d;
    st_get(sv_dest, &d);
    b[0] = (char)('0' + (sv_dest + 1u) / 10u); b[1] = (char)('0' + (sv_dest + 1u) % 10u); b[2] = 0;
    ft_box(0, 76, 240, b, &GF_XL, C_HOUSING, C_GROUND, 1);
    ft_box(0, 138, 240, sv_dest == cur_preset ? "this slot" : "replaces", &GF_TX, sv_dest == cur_preset ? C_HOUSING : C_LABEL, C_GROUND, 1);
    ft_box(0, 164, 240, sv_dest == cur_preset ? "" : d.name, &GF_LB, C_HOUSING, C_GROUND, 1);
}
static void save_close(void)
{
    ui_mode = M_CHAIN; ui_item = 0;
    lcd_rect(0, 0, 240, 240, C_GROUND);
    uc.screen = -1;
    ui_invalidate();
}
static void save_knob(int dd)
{
    sv_dest = (sv_dest + SV_FACTORY + 1u + (uint32_t)(dd > 0 ? 1 : SV_FACTORY)) % (SV_FACTORY + 1u);
}
static void save_confirm(void)
{
    int rc;
    if (sv_dest == SV_FACTORY && !st_saved(cur_preset)) return;
    ft_box(0, 190, 240, "saving...", &GF_TX, C_AMBER, C_GROUND, 1);
    if (sv_dest == SV_FACTORY) { rc = st_reset(cur_preset); }
    else { rc = st_save(sv_dest, &PRESET); if (!rc) cur_preset = sv_dest; }
    st_gen++;
    if (!rc) load_preset(cur_preset);
    {
        char b[16] = "error -";
        if (rc) { b[7] = (char)('0' + (uint32_t)(-rc) % 10u); b[8] = 0; }
        if (rc) ft_box(0, 190, 240, b, &GF_TX, C_AMBER, C_GROUND, 1);
        else ui_lamp_line(190, "saved", &GF_TX, 1, C_HOUSING);
    }
    for (int i = 0; i < 7; i++) { fm1_wdt_feed(); fm1_delay_ms(100); }
    save_close();
}
/* ===================================================== MIDI page ======== */
/* hold FX: the MIDI settings (docs/MIDI.md). KNOB changes the selected row, PUSH moves to the next row and, after the
 * last one, leaves; HOME leaves. The settings are saved (a flash write, as SAVE) only if something changed.
 * v42: a fourth row, USB AUDIO (docs/USB-AUDIO.md): the row shows mi_ua, and the setting (px_ua_on) follows only on
 * leaving, because a change takes the pedal off USB for a second.
 * A fifth row, USB PORT (docs/MIDI.md, "A footswitch by cable"): COMPUTER or FOOTSWITCH, the port the USB MIDI host of a
 * footswitch by cable. It acts at once, so the usb line under the rows says what the host finds, and it is never saved. */
enum { MI_CHAN, MI_SEND, MI_CLOCK,
#if OP_UAUDIO
       MI_UAUDIO,
#endif
#if OP_USB_HOST
       MI_PORT,
#endif
       MI_ROWS };
static uint32_t mi_row, mi_shown_hash = ~0u;
static uint8_t mi_orig, mi_ua;
static void midi_persist(void);                 /* openpocket.c: writes the settings to the store */
static void midi_open(void)
{
    ui_mode = M_MIDI; mi_row = 0; mi_shown_hash = ~0u; mi_orig = px_midi_cfg_pack(&mid_cfg); mi_ua = px_ua_on;
    lcd_rect(0, 0, 240, 240, C_GROUND);
    ui_band("midi");
    lcd_rect(0, F_Y, 240, 240u - F_Y, C_PLATE);
    ui_footer("knob=set|push=next|home=done", 240, 1);
}
static void midi_draw(void)
{
    uint32_t h = mi_row | (uint32_t)px_midi_cfg_pack(&mid_cfg) << 4 | (uint32_t)mid_usb_up << 12 |
                 (uint32_t)mid_last[0] << 13 | (uint32_t)mid_last[1] << 16 | (uint32_t)mid_last[2] << 23 | (uint32_t)mi_ua << 31;
    h ^= (uint32_t)mid_c1_off * 0x27D4EB2Fu;
#if OP_USB_HOST
    h ^= (uint32_t)(px_usb_foot | px_uh.st << 1) * 0x9E3779B1u;
#endif
    if (h == mi_shown_hash) return;
    mi_shown_hash = h;
    static const char *const NAME[MI_ROWS] = {"channel", "send", "clock > delay",
#if OP_UAUDIO
                                              "usb audio",
#endif
#if OP_USB_HOST
                                              "usb port",
#endif
    };
    char v[MI_ROWS][12];
    if (mid_cfg.chan) { v[0][0] = (char)(mid_cfg.chan >= 10 ? '0' + mid_cfg.chan / 10 : ' '); v[0][1] = (char)('0' + mid_cfg.chan % 10); v[0][2] = 0; }
    else { v[0][0] = 'o'; v[0][1] = 'm'; v[0][2] = 'n'; v[0][3] = 'i'; v[0][4] = 0; }
    v[1][0] = v[2][0] = 0;
    b_str(v[1], mid_cfg.send ? "on" : "off");
    b_str(v[2], mid_cfg.clock ? "on" : "off");
#if OP_UAUDIO
    v[MI_UAUDIO][0] = 0;
    b_str(v[MI_UAUDIO], mi_ua ? "on" : "off");
#endif
#if OP_USB_HOST
    v[MI_PORT][0] = 0;
    b_str(v[MI_PORT], px_usb_foot ? "footswitch" : "computer");
#endif
    for (uint32_t r = 0; r < MI_ROWS; r++) {       /* (five rows of 26 px; v42 four of 30, three of 36 before) */
        uint32_t y = 36u + r * 26u;
        uint16_t bg = r == mi_row ? C_KEY : C_GROUND;
        lcd_rect(0, y, 240, 24, bg);
        if (r == mi_row) lcd_rect(2, y + 5u, 3, 14, C_HOUSING);
        ft_box(8, y + 4u, 92, NAME[r], &GF_LB, r == mi_row ? C_HOUSING : C_LABEL, bg, 0);
        ft_box(100, y + 2u, 132, v[r], &GF_MD, C_HOUSING, bg, 2);
    }
    const char *usb = mid_usb_up ? "usb: host connected" : "usb: no host";
    int lit = mid_usb_up;
#if OP_USB_HOST
    if (px_usb_foot) {                             /* what the host finds (px_usbhost.h) */
        static const char *const FOOT[] = {"usb: starting", "usb: no footswitch", "usb: not a midi device",
                                           "usb: low speed device", "usb: footswitch connected", "usb: footswitch lost"};
        usb = FOOT[px_uh.st <= PXU_LOST ? px_uh.st : 0];
        lit = px_uh.st == PXU_OK;
    }
#endif
    ui_lamp_line(170, usb, &GF_LB, lit, lit ? C_HOUSING : C_LABEL);
    char l[24]; l[0] = 0;
    if (mid_last[0] == PXM_PC) { b_str(l, "last: PC "); b_num(l, mid_last[1] + 1u); }
    else if (mid_last[0] == PXM_CC) { b_str(l, "last: CC "); b_num(l, mid_last[1]); b_str(l, " = "); b_num(l, mid_last[2]); }
    else b_str(l, "last: none");
    ft_box(0, 188, 240, l, &GF_LB, C_HOUSING, C_GROUND, 1);
    /* v41: the second core retired (one core left until a power cycle: presets that need both go to BYP), and why */
    char c[32]; c[0] = 0;
    if (mid_c1_off) {
        static const char *const WHY[] = {"", "misread", "late", "until power-off", "fault", "silent"};
        b_str(c, "core 2 off: "); b_str(c, mid_c1_off <= 5u ? WHY[mid_c1_off] : "?");
    }
    ft_box(0, 205, 240, c, &GF_LB, C_AMBER, C_GROUND, 1);
}
static void midi_close(void)
{
    ui_mode = M_CHAIN; ui_item = 0;
    if (px_midi_cfg_pack(&mid_cfg) != mi_orig || mi_ua != px_ua_on) { px_ua_on = mi_ua; midi_persist(); }
    lcd_rect(0, 0, 240, 240, C_GROUND);
    uc.screen = -1;
    ui_invalidate();
}
static void midi_knob(int dd)
{
    if (mi_row == MI_CHAN) mid_cfg.chan = (uint8_t)((mid_cfg.chan + 17u + (uint32_t)(dd > 0 ? 1 : 16)) % 17u);
    else if (mi_row == MI_SEND) mid_cfg.send ^= 1u;
    else if (mi_row == MI_CLOCK) mid_cfg.clock ^= 1u;
#if OP_UAUDIO
    else if (mi_row == MI_UAUDIO) mi_ua ^= 1u;
#endif
#if OP_USB_HOST
    else if (mi_row == MI_PORT) px_usb_foot ^= 1u;   /* (px_uh_service, openpocket.c, makes the change on the next pass) */
#endif
}
static void midi_push(void) { if (++mi_row >= MI_ROWS) midi_close(); }

/* v42: one unsaved edit survives a preset change by foot or from the list: stepping away keeps it, coming back to its slot
 * gives it back (still EDITED). An edit elsewhere takes its place; it is dropped if its slot was saved over meanwhile. */
static px_preset_t ui_kept;
static uint32_t ui_kept_slot = ~0u, ui_kept_sum;     /* (the sum of what the slot held when the edit was kept) */
static uint32_t ui_sum(const px_preset_t *p)
{
    const uint8_t *b = (const uint8_t *)p;
    uint32_t h = 2166136261u;
    for (uint32_t i = 0; i < sizeof *p; i++) h = (h ^ b[i]) * 16777619u;
    return h;
}
static void ui_goto(uint32_t n)
{
    if (ui_dirty()) { ui_kept = PRESET; ui_kept_slot = cur_preset; ui_kept_sum = ui_sum(&ui_ref); }
    cur_preset = n;
    load_preset(n);
    if (ui_kept_slot == n) {
        if (ui_sum(&PRESET) == ui_kept_sum) PRESET = ui_kept;
        ui_kept_slot = ~0u;
    }
}
static int ui_stepped;                 /* the last footswitch's step (+1, -1; 0: none): both footswitches take it back */
static void ui_preset_step(int dd)
{
    int n = px_preset_count();
    ui_goto((uint32_t)(((int)cur_preset + n + dd) % n));
    ui_stepped = dd;
    if (UI_PAGE || ui_mode == M_LIST) { ui_mode = M_CHAIN; ui_item = 0; }   /* a footswitch on a block page goes back to PLAY, where the preset shows */
}
/* the FX button's blocks (the FX light follows them: px_lights.h) */
static const uint8_t UI_FXB[7] = {PX_B_DRIVE, PX_B_SFX, PX_B_SYN, PX_B_PITCH, PX_B_COMP, PX_B_GATE, PX_B_EQ};
static int ui_is_fx(uint32_t b) { for (int i = 0; i < 7; i++) if (UI_FXB[i] == b) return 1; return 0; }
static void ui_fx_cycle(void)          /* FX: the next of its blocks along the preset's chain, as the tiles read (v42), else the first */
{
    ui_order_fix();
    int from = ui_is_fx(ui_blk) ? ui_pos_of(ui_blk) + 1 : 0;
    for (int i = 0; i < PX_NBLK; i++) {
        uint32_t b = PRESET.order[(from + i) % PX_NBLK];
        if (ui_is_fx(b)) { ui_blk = b; break; }
    }
    ui_mode = M_BLOCK; ui_item = 0;
}

/* ===================================================== preset list ======== */
/* v42: HOME on PLAY: the knob browses the presets by name without loading them, PUSH loads the one in the middle, HOME goes
 * back. The playing preset has the lamp. */
#define LS_Y0  38u
#define LS_ROW 36u
static uint32_t ls_at, ls_shown = ~0u;
static void list_open(void)
{
    ui_mode = M_LIST; ls_at = cur_preset; ls_shown = ~0u;
    lcd_rect(0, 0, 240, 240, C_GROUND);
    ui_band("presets");
    lcd_rect(0, F_Y, 240, 240u - F_Y, C_PLATE);
    ui_footer("knob=preset|push=load|home=back", 240, 1);
    uc.screen = -1;
}
static void list_draw(void)
{
    uint32_t key = ls_at | cur_preset << 8 | st_gen << 16;
    if (key == ls_shown) return;
    ls_shown = key;
    int n = px_preset_count();
    for (uint32_t r = 0; r < 5u; r++) {
        uint32_t k = (uint32_t)(((int)ls_at + n + (int)r - 2) % n), y = LS_Y0 + r * LS_ROW;
        int sel = r == 2u;
        uint16_t bg = sel ? C_KEY : C_GROUND;
        px_preset_t q;
        char b[4];
        st_get(k, &q);
        b[0] = (char)('0' + (k + 1u) / 10u); b[1] = (char)('0' + (k + 1u) % 10u); b[2] = 0;
        ui_rbox(4, y, 232, LS_ROW - 2u, 5, bg, C_GROUND);
        if (sel) lcd_rect(4, y + 10u, 3, 14, C_HOUSING);
        if (k == cur_preset) ui_lamp(12, y + 12u, 1, bg);
        ft_box(24, y + 6u, 34, b, &GF_MD, sel ? C_HOUSING : C_LABEL, bg, 0);
        ft_box(58, y + 5u, 174, q.name, &GF_TX, sel ? C_HOUSING : C_LABEL, bg, 0);
    }
}
static void list_knob(int dd) { int n = px_preset_count(); ls_at = (uint32_t)(((int)ls_at + n + dd) % n); }
static void list_close(void) { ui_mode = M_CHAIN; ui_item = 0; uc.screen = -1; ui_invalidate(); }
static void list_load(void) { if (ls_at != cur_preset) ui_goto(ls_at); list_close(); }

/* ===================================================== tuner ======== */
/* v42: the tuner only; the readings for a photo are on the diagnostics page, HOME held on past the tuner. The note is 81 px
 * tall, read from five feet. Under it a scale of 50 cents each way, a tick every 10: the needle shows where the note is,
 * and the window under the middle is the lamp, lit while the note is within 5 cents (the note turns the lamp's green too). */
static const char *NOTE_N[12] = {"C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"};
static int tn_last_note = -2, tn_last_x = -1, tn_last_c = 1000, tn_last_dir = 2, tn_last_ok = -1;
#define TN_NOTE_Y 34u
#define TN_Y 158u                      /* the scale: its ticks stand on the line at TN_Y + 14, the needle is 20 px from TN_Y - 2 */
static void tn_scale(uint32_t x0, uint32_t x1)   /* the scale's columns x0 to x1 - 1, without the needle */
{
    lcd_rect(x0, TN_Y - 2u, x1 - x0, 16, C_GROUND);
    lcd_rect(x0, TN_Y + 14u, x1 - x0, 1, C_RIM);
    lcd_rect(x0, TN_Y + 15u, x1 - x0, 3, C_GROUND);
    for (uint32_t x = 20u; x <= 220u; x += 20u) {
        int tall = x == 20u || x == 120u || x == 220u;
        if (x >= x0 && x < x1) lcd_rect(x, TN_Y + (tall ? 4u : 8u), 1, tall ? 10u : 6u, tall ? C_LABEL : C_RIM);
    }
}
static void tuner_open(void)
{
    ui_mode = M_TUNER;
    a_tmute = 1;                                              /* v36: silent while tuning */
    lcd_rect(0, 0, 240, 240, C_GROUND);
    lcd_rect(0, 0, 240, 30, C_PLATE);
    ft_box(8, 4, 120, "tuner", &GF_TX, C_HOUSING, C_PLATE, 0);
    ft_box(128, 9, 108, "A4 = 440 Hz", &GF_LB, C_LABEL, C_PLATE, 2);
    tn_scale(20, 221);
    ft_box(0, TN_Y + 28u, 40, "-50", &GF_MS, C_LABEL, C_GROUND, 1);
    ft_box(100, TN_Y + 28u, 40, "0", &GF_MS, C_LABEL, C_GROUND, 1);
    ft_box(200, TN_Y + 28u, 40, "+50", &GF_MS, C_LABEL, C_GROUND, 1);
    lcd_rect(0, F_Y, 240, 240u - F_Y, C_PLATE);
    ui_footer("any switch=exit|hold home=diag", 240, 1);
    tn_last_note = -2; tn_last_x = -1; tn_last_c = 1000; tn_last_dir = 2; tn_last_ok = -1;
}
static void tuner_close(void) { a_tmute = 0; ui_mode = M_CHAIN; lcd_rect(0, 0, 240, 240, C_GROUND); uc.screen = -1; ui_invalidate(); }
static void tuner_draw(float hz)       /* hz <= 0: no note */
{
    int note = -1, c = 0; float cents = 0.0f;
    if (hz > 20.0f) {
        float st = 12.0f * logf(hz / 440.0f) * 1.44269504f;   /* semitones from A4 = 440 Hz */
        int r = (int)(st + (st >= 0 ? 0.5f : -0.5f));
        cents = (st - (float)r) * 100.0f;
        note = ((r % 12) + 12 + 9) % 12;                      /* A = 9 */
        c = (int)(cents + (cents >= 0 ? 0.5f : -0.5f));
    }
    int ok = (note >= 0 && c > -5 && c < 5);
    if (note != tn_last_note || ok != tn_last_ok) {
        ft_box(40, TN_NOTE_Y, 160, note < 0 ? "-" : NOTE_N[note], &GF_LG, note < 0 ? C_LABEL : (ok ? C_LAMP : C_HOUSING), C_GROUND, 1);
        tn_last_note = note;
    }
    int dir = note < 0 || ok ? 0 : c < 0 ? -1 : 1;           /* which way to turn: an arrow toward in tune, on the side the note is */
    if (dir != tn_last_dir) {
        ft_box(4, TN_NOTE_Y + 30u, 36, dir < 0 ? ">>" : "", &GF_TX, C_HOUSING, C_GROUND, 1);
        ft_box(200, TN_NOTE_Y + 30u, 36, dir > 0 ? "<<" : "", &GF_TX, C_HOUSING, C_GROUND, 1);
        tn_last_dir = dir;
    }
    if (c != tn_last_c || note < 0 || ok != tn_last_ok) {
        char b[8] = "";
        if (note >= 0) { int a = c < 0 ? -c : c; b[0] = (char)(c < 0 ? '-' : '+'); num3(b + 1, (uint32_t)a); }
        int i = 0; while (b[i]) i++;
        if (note >= 0) { b[i++] = ' '; b[i++] = 'c'; b[i++] = 't'; b[i] = 0; }
        ft_box(60, TN_NOTE_Y + 88u, 120, b, &GF_MD, ok ? C_LAMP : C_HOUSING, C_GROUND, 1);
        tn_last_c = note < 0 ? 1000 : c;
    }
    if (ok != tn_last_ok) { ui_rbox(110, TN_Y + 18u, 20, 6, 3, ok ? C_LAMP : C_LAMP_OFF, C_GROUND); tn_last_ok = ok; }
    int x = -1;
    if (note >= 0) x = 120 + (c < -48 ? -48 : c > 48 ? 48 : c) * 2;
    if (x != tn_last_x) {                                     /* the needle: the scale again where it was, then the needle where it is */
        if (tn_last_x >= 0) tn_scale((uint32_t)tn_last_x - 1u, (uint32_t)tn_last_x + 2u);
        if (x >= 0) lcd_rect((uint32_t)x - 1u, TN_Y - 2u, 3, 20, C_HOUSING);
        tn_last_x = x;
    }
}

/* ===================================================== diagnostics ======== */
/* v42 (on the tuner page before): what a bug report needs a photo of, as pictures with every figure written beside them.
 * HOME held on past the tuner; the knob turns the page (1: the DSP, 2: input and power); any control leaves. The sound
 * plays. Colours: housing; amber above UI_LOAD_HIGH, when a block ran late and while the effects are bypassed. */
#define DG_X   8u
#define DG_W   228u
#define DG_BLK 4                       /* the blocks shown in "CPU PER BLOCK": the costliest, the first one highlighted */
static uint32_t dg_page, dg_hash[4], dg_clip_seen, dg_clip_hold;
static uint16_t dg_col(uint32_t pct, int bad) { return bad || pct > UI_LOAD_HIGH ? C_AMBER : C_HOUSING; }
static uint32_t dg_w(uint32_t v, uint32_t full, uint32_t w) { return v >= full ? w : v * w / full; }
/* a bar of w px for v of full, and an amber tick at tick (0: none) with 2 px above and below it */
static void dg_bar(uint32_t x, uint32_t y, uint32_t w, uint32_t h, uint32_t v, uint32_t full, uint16_t col, uint32_t tick)
{
    uint32_t f = dg_w(v, full, w);
    lcd_rect(x, y - 2u, w, 2, C_GROUND); lcd_rect(x, y + h, w, 2, C_GROUND);
    if (f) lcd_rect(x, y, f, h, col);
    if (f < w) lcd_rect(x + f, y, w - f, h, C_RIM);
    if (tick) { uint32_t t = dg_w(tick, full, w); lcd_rect(x + (t ? t - 1u : 0u), y - 2u, 2, h + 4u, C_AMBER); }
}
static void dg_chip(uint32_t x, uint32_t y, uint32_t w, const char *s, uint16_t col)   /* a counter: its text on a dark chip */
{
    ui_rbox(x, y, w, 18, 4, C_KEY, C_GROUND);
    ft_box(x + 3u, y + 1u, w - 6u, s, &GF_LB, col, C_KEY, 1);
}
static int dg_top(uint8_t *idx, int n)  /* the costliest blocks (a_pf; PX_NBLK = the NAM network), most first: how many */
{
    uint8_t used[PX_NBLK + 1] = {0};
    int c = 0;
    for (; c < n; c++) {
        int best = -1;
        for (int k = 0; k <= PX_NBLK; k++) if (!used[k] && a_pf[k] && (best < 0 || a_pf[k] > a_pf[best])) best = k;
        if (best < 0) break;
        used[best] = 1; idx[c] = (uint8_t)best;
    }
    return c;
}
static void dg_pct(char *b, const char *label, uint32_t v) { b[0] = 0; b_str(b, label); b_num(b, v > 999u ? 999u : v); b_str(b, "%"); }
static int dg_changed(int k, uint32_t h) { if (h == dg_hash[k]) return 0; dg_hash[k] = h; return 1; }
static uint32_t dg_mix(uint32_t h, uint32_t v) { return (h ^ v) * 16777619u; }
static void diag_dsp(void)             /* page 1: the load against the guard, each core, the counters, the CPU per block */
{
    static const char *const CORES[3] = {"C0", "C1", "2C"};
    uint32_t late = (uint32_t)bat_raw[2], clip = (uint32_t)bat_raw[3], pk = (uint32_t)bat_raw[4];
    int bad = ui_dg.late || ui_dg.bypass;
    uint16_t c = dg_col(ui_dg.load, bad);
    char b[32];
    uint32_t h = 2166136261u;
    h = dg_mix(h, ui_dg.load); h = dg_mix(h, ui_dg.peak); h = dg_mix(h, ui_dg.cores); h = dg_mix(h, ui_dg.guard); h = dg_mix(h, (uint32_t)bad);
    if (dg_changed(0, h)) {
        dg_pct(b, "dsp ", ui_dg.load);
        ft_box(DG_X, 34, 120, b, &GF_TX, c, C_GROUND, 0);
        dg_pct(b, "peak ", ui_dg.peak);
        ft_box(128, 39, 104, b, &GF_LB, C_HOUSING, C_GROUND, 2);
        dg_bar(10, 60, 220, 6, ui_dg.load, 100, c, ui_dg.guard);
        b[0] = 0; b_str(b, "cores "); b_str(b, CORES[ui_dg.cores < 3u ? ui_dg.cores : 0u]);
        ft_box(DG_X, 70, 80, b, &GF_LB, C_HOUSING, C_GROUND, 0);
        dg_pct(b, "guard ", ui_dg.guard);
        ft_box(152, 70, 80, b, &GF_LB, C_LABEL, C_GROUND, 2);
    }
    h = 2166136261u;
    for (int k = 0; k < 2; k++) h = dg_mix(h, ui_dg.cl[k]);
    h = dg_mix(h, ui_dg.split); h = dg_mix(h, ui_dg.guard);
    if (dg_changed(1, h)) {
        for (uint32_t k = 0; k < 2u; k++) {                  /* each core (with the layer split; else "--") */
            uint32_t y = 88u + k * 16u;
            b[0] = 0; b_str(b, k ? "cpu1 " : "cpu0 ");
            if (ui_dg.split) { b_num(b, ui_dg.cl[k]); b_str(b, "%"); } else b_str(b, "--");
            ft_box(DG_X, y, 78, b, &GF_LB, ui_dg.split ? C_HOUSING : C_LABEL, C_GROUND, 0);
            dg_bar(88, y + 5u, 144, 6, ui_dg.split ? ui_dg.cl[k] : 0u, 100, dg_col(ui_dg.cl[k], 0), ui_dg.guard);
        }
    }
    h = dg_mix(dg_mix(dg_mix(dg_mix(2166136261u, late), clip), pk), ui_dg.bypass);
    if (dg_changed(2, h)) {                                /* the counters since boot, amber once not zero */
        dg_pct(b, "pk ", pk);                              /* (the highest block load since boot) */
        ft_box(88, 70, 64, b, &GF_LB, dg_col(pk, pk >= 100u), C_GROUND, 1);
        b[0] = 0; b_str(b, "late "); b_num(b, late > 9999u ? 9999u : late); dg_chip(2, 122, 76, b, late ? C_AMBER : C_HOUSING);
        b[0] = 0; b_str(b, "clip "); b_num(b, clip > 9999u ? 9999u : clip); dg_chip(79, 122, 76, b, clip ? C_AMBER : C_HOUSING);
        dg_chip(156, 122, 82, ui_dg.bypass ? "bypass on" : "bypass off", ui_dg.bypass ? C_AMBER : C_HOUSING);
    }
    uint8_t top[DG_BLK];
    int n = dg_top(top, DG_BLK);
    h = dg_mix(2166136261u, a_wcut);
    for (int i = 0; i < n; i++) h = dg_mix(dg_mix(h, top[i]), a_pf[top[i]]);
    if (dg_changed(3, dg_mix(h, (uint32_t)n))) {
        ft_box(DG_X, 141, 140, "cpu per block %", &GF_LB, C_LABEL, C_GROUND, 0);
        b[0] = 0;
        if (a_wcut) { b_str(b, "cut "); b_num(b, a_wcut > 9999u ? 9999u : a_wcut); }   /* v39: wet blocks cut short */
        ft_box(148, 141, 84, b, &GF_LB, C_AMBER, C_GROUND, 2);
        for (int i = 0; i < DG_BLK; i++) {                   /* sorted, the heaviest in housing, the others in label grey */
            uint32_t y = 158u + (uint32_t)i * 16u;
            if (i >= n) { lcd_rect(0, y, 240, 16, C_GROUND); continue; }
            const char *l = top[i] == PX_NBLK ? "nam" : px_block_label(top[i]);
            ui_box(DG_X, y, 42, l, &GF_LB, i ? C_LABEL : C_HOUSING, C_GROUND, UI_LC);
            dg_bar(52, y + 5u, 148, 5, a_pf[top[i]], 100, i ? C_LABEL : C_HOUSING, 0);
            b[0] = 0; b_num(b, a_pf[top[i]]);
            ft_box(202, y, 34, b, &GF_LB, i ? C_LABEL : C_HOUSING, C_GROUND, 2);
        }
    }
}
#define DG_DB_MIN 90                    /* the input meters: -90 dB to full scale; the last 3 dB are the clip zone */
#define DG_CLIP_ZONE ft_mix(C_AMBER, C_GROUND, 7)   /* (amber at half: it stands out from the empty part of the meter) */
static int r_str(char *b, int32_t v) { if (v < 0) { b[0] = '-'; b[1] = '-'; return 2; } char t[8]; t[0] = 0; b_num(t, (uint32_t)v); int i = 0; while (t[i]) { b[i] = t[i]; i++; } return i; }
static void diag_power(void)           /* page 2: the input levels, the output's soft clip, the battery, the raw readings */
{
    char b[40];
    int lv[2] = {a_level_db(0), a_level_db(1)};
    uint32_t clip = (uint32_t)bat_raw[3];
    if (clip != dg_clip_seen) { dg_clip_seen = clip; dg_clip_hold = 20u; }   /* lit for 20 draws (2 s) after a clip */
    else if (dg_clip_hold) dg_clip_hold--;
    uint32_t h = dg_mix(dg_mix(2166136261u, (uint32_t)lv[0]), (uint32_t)lv[1]);
    if (dg_changed(0, h)) {
        for (int ch = 0; ch < 2; ch++) {                     /* "L -62 dB" and a meter: amber above -6, as its clip zone is */
            uint32_t y = 54u + (uint32_t)ch * 18u;
            int v = lv[ch] < -DG_DB_MIN ? -DG_DB_MIN : lv[ch] > 0 ? 0 : lv[ch];
            b[0] = 0; b_str(b, ch ? "R " : "L ");
            if (lv[ch] <= -199) b_str(b, "---"); else { if (lv[ch] < 0) b_str(b, "-"); b_num(b, (uint32_t)(lv[ch] < 0 ? -lv[ch] : lv[ch])); }
            b_str(b, " dB");
            ft_box(DG_X, y, 74, b, &GF_LB, C_HOUSING, C_GROUND, 0);
            uint32_t w = 150u, zone = w * 3u / DG_DB_MIN, f = dg_w((uint32_t)(v + DG_DB_MIN), DG_DB_MIN, w);
            lcd_rect(82, y + 2u, w, 2, C_GROUND); lcd_rect(82, y + 12u, w, 2, C_GROUND);
            if (f) lcd_rect(82, y + 4u, f, 8, v > -6 ? C_AMBER : C_HOUSING);
            if (f < w - zone) lcd_rect(82 + f, y + 4u, w - zone - f, 8, C_RIM);
            if (f < w) { uint32_t s = f > w - zone ? f : w - zone; lcd_rect(82 + s, y + 4u, w - s, 8, DG_CLIP_ZONE); }   /* the clip zone */
        }
    }
    h = dg_mix(dg_mix(2166136261u, clip), dg_clip_hold ? 1u : 0u);
    if (dg_changed(1, h)) {                                  /* the output: a marker lit while it reaches the soft clipper */
        lcd_rect(DG_X, 112, 14, 14, dg_clip_hold ? C_AMBER : C_RIM);
        b[0] = 0; b_str(b, "soft clip: "); b_num(b, clip); b_str(b, " blocks");
        ft_box(28, 111, 204, b, &GF_LB, dg_clip_hold ? C_AMBER : C_HOUSING, C_GROUND, 0);
    }
    int usb = bat_usb_mv > 4300, pct = bat_pct >= 0 ? bat_pct : bat_mv ? bat_percent(bat_mv) : -1;
    h = dg_mix(dg_mix(dg_mix(2166136261u, (uint32_t)bat_mv), (uint32_t)usb), (uint32_t)pct);
    if (dg_changed(2, h)) {                                  /* the battery: a cell, its volts, its percent (or USB) */
        uint16_t c = !usb && pct <= 30 ? C_AMBER : C_HOUSING;
        uint32_t f = pct < 0 ? 0u : (uint32_t)pct * 40u / 100u;
        lcd_rect(DG_X, 156, 46, 22, C_HOUSING); lcd_rect(DG_X + 2u, 158, 42, 18, C_GROUND); lcd_rect(DG_X + 46u, 162, 3, 10, C_HOUSING);
        if (f) lcd_rect(DG_X + 3u, 159, f, 16, c);
        if (f < 40u) lcd_rect(DG_X + 3u + f, 159, 40u - f, 16, C_GROUND);
        b[0] = 0;
        if (bat_mv) { b_num(b, (uint32_t)bat_mv / 1000u); b_str(b, "."); b_num(b, (uint32_t)bat_mv / 100u % 10u); b_num(b, (uint32_t)bat_mv / 10u % 10u); b_str(b, " V"); }
        else b_str(b, "-- V");
        ft_box(62, 156, 96, b, &GF_MD, C_HOUSING, C_GROUND, 0);
        b[0] = 0;
        if (usb) b_str(b, "usb"); else if (pct >= 0) { b_num(b, (uint32_t)pct); b_str(b, "%"); } else b_str(b, "--");
        ft_box(158, 160, 74, b, &GF_LB, c, C_GROUND, 2);
    }
    h = dg_mix(dg_mix(2166136261u, (uint32_t)bat_raw[0]), (uint32_t)bat_raw[1]);
    if (dg_changed(3, h)) {                                  /* the battery's raw reading (PC9) and the status bit beside it */
        int i = 0; b[0] = 0; b_str(b, "raw  C9 "); while (b[i]) i++;
        i += r_str(b + i, bat_raw[0]); b[i] = 0; b_str(b, "  ch "); while (b[i]) i++; i += r_str(b + i, bat_raw[1]); b[i] = 0;
        ft_box(DG_X, 190, DG_W, b, &GF_LB, C_LABEL, C_GROUND, 0);
    }
}
static void diag_frame(void)           /* the page's fixed parts */
{
    lcd_rect(0, 0, 240, 240, C_GROUND);
    lcd_rect(0, 0, 240, 30, C_PLATE);
    ft_box(8, 4, 150, "diagnostics", &GF_TX, C_HOUSING, C_PLATE, 0);
    {
        char b[16]; b[0] = 0;
        b_str(b, dg_page ? "2/2" : "1/2");
#ifdef OP_VERSION
        b_str(b, "  " OP_VERSION);
#endif
        ft_box(158, 9, 78, b, &GF_LB, C_LABEL, C_PLATE, 2);
    }
    if (dg_page) {
        ft_box(DG_X, 36, DG_W, "input (dB below full scale)", &GF_LB, C_LABEL, C_GROUND, 0);
        ft_box(DG_X, 94, DG_W, "output", &GF_LB, C_LABEL, C_GROUND, 0);
        ft_box(DG_X, 138, DG_W, "battery", &GF_LB, C_LABEL, C_GROUND, 0);
    }
    lcd_rect(0, F_Y, 240, 240u - F_Y, C_PLATE);
    ui_footer(dg_page ? "knob=page 1|~photograph both" : "knob=page 2|~photograph both", 240, 1);
    for (int k = 0; k < 4; k++) dg_hash[k] = ~0u;
}
static void diag_open(void)
{
    ui_mode = M_DIAG;
    a_tmute = 0;                                              /* (the sound plays: the figures are of it) */
    dg_page = 0;
    dg_clip_seen = (uint32_t)bat_raw[3]; dg_clip_hold = 0;   /* (the marker lights for a clip from now on) */
    diag_frame();
}
static void diag_turn(void) { dg_page ^= 1u; diag_frame(); }
static void diag_close(void) { ui_mode = M_CHAIN; ui_item = 0; lcd_rect(0, 0, 240, 240, C_GROUND); uc.screen = -1; ui_invalidate(); }
static void diag_draw(void) { if (dg_page) diag_power(); else diag_dsp(); }

/* ===================================================== update ======== */
/* the update over USB (px_usb.h's ota_show draws it through OP_OTA_SCREEN): the mark, a dot for each of the five steps
 * (those done pale, the one running the lamp), the step's name; a failure in amber, with its sign, its code and what to do */
static void ui_update_show(uint32_t step, int32_t code)
{
    static const char *const STEP[] = {"", "package", "check", "loader", "confirm", "restart"};
    int fail = step >= 9u;
    lcd_rect(0, 0, 240, 240, C_GROUND);
    ui_grille(104, 40, 4, 9, 7, !fail, C_GRILLE, C_GROUND);
    ft_box(0, 84, 240, "update", &GF_TX, C_HOUSING, C_GROUND, 1);
    if (!fail) {
        for (uint32_t i = 1; i <= 5u; i++) ui_rbox(62u + i * 18u, 118, 8, 8, 4, i < step ? C_HOUSING : i == step ? C_LAMP : C_RIM, C_GROUND);
        ft_box(0, 134, 240, STEP[step < 6u ? step : 0], &GF_LB, C_HOUSING, C_GROUND, 1);
        ft_box(0, 170, 240, "do not unplug", &GF_LB, C_AMBER, C_GROUND, 1);
        return;
    }
    char b[28]; uint32_t v = (uint32_t)(code < 0 ? -code : code);
    b[0] = 0; b_str(b, "update failed (code "); b_num(b, v % 100u); b_str(b, ")");
    ui_rbox(6, 116, 228, 62, 6, C_AMBER, C_GROUND);
    ui_warn(14, 127, C_GRAPHITE, C_AMBER);
    ft_box(32, 124, 198, b, &GF_LB, C_GRAPHITE, C_AMBER, 0);
    ft_box(32, 146, 198, "try again from the installer", &GF_LB, C_GRAPHITE, C_AMBER, 0);
}

/* ===================================================== controls ======== */
/* What each control does on each page, in one place: the main loop (openpocket.c) and the simulator (tests/edsim.c) give
 * ui_buttons the debounced buttons and ui_turn the knob; the simulator's named gestures call ui_action. */
enum { UB_FSUP, UB_FSDN, UB_PUSH, UB_HOME, UB_FX, UB_MOD, UB_AMP, UB_CAB, UB_DLY, UB_REV, UB_N };   /* a button: bit 1 << UB_x */
enum { UA_SAVE = UB_N, UA_MOVE, UA_TUNER, UA_MIDI, UA_FEET };   /* the gestures (a button's plain press is its UB_x) */
#define UI_HOLD_PUSH 800u              /* hold PUSH: SAVE */
#define UI_HOLD_HOME 700u              /* hold HOME: the tuner; held on as long again: the diagnostics */
#define UI_HOLD_FX   800u              /* hold FX: MIDI */
#define UI_CLICK2    350u              /* PUSH again within this, after a click opened a block from PLAY: MOVE that block */
#define UI_FEET      150u              /* the other footswitch within this: both, the tuner */
static struct {
    uint32_t held, t[UB_N], clk_t, fs_t;
    uint8_t fired[UB_N], clk, clk_blk;
    int8_t fs, fs_dir;                 /* the last footswitch pressed (-1: none) and the step it made */
} ug = {.fs = -1};
static void ui_action(int a)
{
    static const uint8_t BLK_OF[5] = {PX_B_MOD, PX_B_AMP, PX_B_CAB, PX_B_DELAY, PX_B_REVERB};
    switch (ui_mode) {
    case M_SAVE: if (a == UB_PUSH) save_confirm(); else if (a == UB_HOME) save_close(); return;
    case M_MIDI: if (a == UB_PUSH) midi_push(); else if (a == UB_HOME) midi_close(); return;
    case M_TUNER: if (a == UA_TUNER) diag_open(); else tuner_close(); return;   /* any control leaves; HOME held on: diagnostics */
    case M_DIAG: if (a != UA_TUNER) diag_close(); return;
    case M_MOVE: if (a == UB_PUSH) ui_move_drop(); else if (a == UB_HOME) ui_move_cancel(); return;
    }
    switch (a) {
    case UB_FSUP: ui_preset_step(+1); break;
    case UB_FSDN: ui_preset_step(-1); break;
    case UB_PUSH: if (ui_mode == M_LIST) list_load(); else ui_push(); break;
    case UB_HOME: if (ui_mode == M_CHAIN) list_open(); else if (ui_mode == M_LIST) list_close(); else ui_home(); break;
    case UB_FX: ui_fx_cycle(); break;
    case UA_SAVE: save_open(); break;
    case UA_MOVE: if (ui_mode == M_CHAIN) ui_move_start(); break;
    case UA_TUNER: case UA_FEET: tuner_open(); break;
    case UA_MIDI: midi_open(); break;
    default: ui_enter_block(BLK_OF[a - UB_MOD]);
    }
}
static void ui_turn(int dd, int fast)  /* the PARA knob, one detent (fast: turned quickly) */
{
    ug.clk = 0;
    if (ui_mode == M_SAVE) save_knob(dd);
    else if (ui_mode == M_MIDI) midi_knob(dd);
    else if (ui_mode == M_LIST) list_knob(dd);
    else if (ui_mode == M_DIAG) diag_turn();
    else if (ui_mode != M_TUNER) ui_knob(dd, fast);
}
static void ui_press(int b, uint32_t now)   /* a button's plain press: at its press, PUSH HOME FX at a short release */
{
    if (b == UB_FSUP || b == UB_FSDN) {        /* v42: both footswitches = the tuner. The first acts at once, as always; the
                                                * other one soon after, while the first is still down, takes its step back
                                                * and opens the tuner */
        ug.clk = 0;
        if (ug.fs >= 0 && ug.fs != b && (ug.held >> ug.fs & 1u) && now - ug.fs_t < UI_FEET) {
            int d = ug.fs_dir;
            ug.fs = -1;
            if (d) { ui_preset_step(-d); ui_action(UA_FEET); }
            return;
        }
        ug.fs = (int8_t)b; ug.fs_t = now; ui_stepped = 0;
        ui_action(b);
        ug.fs_dir = (int8_t)ui_stepped;
        return;
    }
    if (b == UB_PUSH) {                        /* v42: a click on PLAY opens the block at once; a 2nd one soon after: MOVE it */
        if (ug.clk && ui_mode == M_BLOCK && ui_item == 0u && ui_blk == ug.clk_blk) {
            ug.clk = 0;
            ui_mode = M_CHAIN;
            ui_action(UA_MOVE);
            return;
        }
        int chain = ui_mode == M_CHAIN;
        ui_action(UB_PUSH);
        ug.clk = (uint8_t)(chain && ui_mode == M_BLOCK); ug.clk_t = now; ug.clk_blk = (uint8_t)ui_blk;
        return;
    }
    ug.clk = 0;
    ui_action(b);
}
static void ui_buttons(uint32_t now, uint32_t held)   /* every pass: which buttons are down (debounced), bit 1 << UB_x */
{
    uint32_t dn = held & ~ug.held, up = ug.held & ~held;
    ug.held = held;
    if (ug.clk && now - ug.clk_t >= UI_CLICK2) ug.clk = 0;
    for (int b = 0; b < UB_N; b++) {
        int timed = b == UB_PUSH || b == UB_HOME || b == UB_FX;   /* (these have a hold: they act at the release) */
        uint32_t hold = b == UB_PUSH ? UI_HOLD_PUSH : b == UB_HOME ? UI_HOLD_HOME : UI_HOLD_FX;
        if (dn >> b & 1u) { ug.t[b] = now; ug.fired[b] = 0; if (!timed) ui_press(b, now); }
        else if (timed && (held >> b & 1u) && (b == UB_HOME || !ug.fired[b]) && now - ug.t[b] >= hold) {
            ug.fired[b] = 1; ug.t[b] = now; ug.clk = 0;              /* (HOME: each further hold as long goes one page on) */
            ui_action(b == UB_PUSH ? UA_SAVE : b == UB_HOME ? UA_TUNER : UA_MIDI);
        }
        if ((up >> b & 1u) && timed && !ug.fired[b]) ui_press(b, now);
    }
}
