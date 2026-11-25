/* SPDX-License-Identifier: GPL-3.0-only
 * OpenPocket — the pedal's screen on the PC: firmware/apps/gamut/ui.h + ui_fonts.h + ui_text.h drawn into a 240x240 RGB565
 * frame buffer, exactly as the pedal streams it (window + pixels). Writes PPM screenshots of a script of actions.
 *   cc -O1 -Ifirmware/apps/gamut/engine -Ifirmware -o build/uisim firmware/apps/gamut/tests/uisim.c firmware/apps/gamut/engine/px_dsp.c firmware/px_math.c -lm
 *   build/uisim OUTDIR        -> OUTDIR/NN_name.ppm ; also checks that every pixel is drawn on each full page
 * The frame buffer starts (and is re-poisoned before each full page) in magenta: any pixel left magenta after a
 * full redraw is a gap in the page's layout. */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "px_dsp.h"
#include "../px_midi.h"

#include "../../../../tests/simlcd.h"
#define POISON 0xF81F

static void fm1_wdt_feed(void) { }
static int waits, wait_shot;            /* the screen as it is at the wait_shot'th wait: what a page shows while the pedal waits */
static uint16_t wait_fb[240 * 240];
static void fm1_delay_ms(int ms) { (void)ms; if (++waits == wait_shot) memcpy(wait_fb, fb, sizeof wait_fb); }

static px_preset_t PRESET;
static uint32_t cur_preset = 0;
static uint32_t master_vol = 80;
static px_preset_t saved[52];
static int saved_ok[52];
static void st_get(uint32_t k, px_preset_t *p) { if (saved_ok[k]) *p = saved[k]; else px_preset_factory(p, (int)k); }
static int st_save(uint32_t k, const px_preset_t *p) { saved[k] = *p; saved_ok[k] = 1; return 0; }
static int st_reset(uint32_t k) { saved_ok[k] = 0; return 0; }
static int st_saved(uint32_t k) { return saved_ok[k]; }
static void load_preset(uint32_t i) { st_get(i, &PRESET); }
static int a_level_db(int ch) { return ch ? -84 : -62; }
static uint8_t a_pf[PX_NBLK + 1] = {0, 0, 0, 0, 0, 0, 3, 0, 0, 5, 7, 0, 64};   /* v38: CPU per block (the tuner's footer) */
static uint32_t a_wcut = 2;                            /* v39: wet blocks cut short */
static volatile uint8_t a_tmute;
static int bat_mv = 3920, bat_usb_mv = 0;
static int32_t bat_raw[5] = {612, 1, 0, 3, 91};   /* bat_read's raw values (the tuner page shows them) */
static int bat_pct = -1;                /* (-1: the gauge from bat_mv) */

static void b_num(char *d, uint32_t v) { char t[12]; int n = 0; while (*d) d++; do { t[n++] = (char)('0' + v % 10u); v /= 10u; } while (v); while (n) *d++ = t[--n]; *d = 0; }
static void b_str(char *d, const char *s) { while (*d) d++; while (*s) *d++ = *s++; *d = 0; }
static int midi_saved;
static void midi_persist(void) { midi_saved++; }
/* user slots for the list settings (F7): NAM slot 3 and IR slots 2 and 5 hold something, the others are empty */
int px_nam_user(int slot, char *name12, float *level_db, float *w) { (void)w; if (slot != 2) return 0; strcpy(name12, "MY AMP"); if (level_db) *level_db = 0; return 1; }
int px_ir_user(int slot, char *name12, float *h) { (void)h; if (slot != 1 && slot != 4) return 0; strcpy(name12, slot == 1 ? "V30 4X12" : "GREENBACK"); return 44100; }
#include "ui_text.h"
/* every text a page draws must fit its box and have its glyphs: ft_box cuts what does not fit and draws a space for a
 * character its font lacks, both without a word */
static int cut;
static uint32_t fit_box(uint32_t x, uint32_t y, uint32_t w, const char *s, const op_font *f, uint16_t fg, uint16_t bg, int align)
{
    if (x + w > 240u) w = 240u - x;
    if (ft_width(f, s) > w) { printf("text cut: \"%s\" is %u px wide, its box %u\n", s, ft_width(f, s), w); cut++; }
    for (const char *c = s; *c; c++) if (!strchr(f->chars, *c)) { printf("no glyph: '%c' of \"%s\" is not in its font\n", *c, s); cut++; }
    return ft_box(x, y, w, s, f, fg, bg, align);
}
#define ft_box fit_box
/* the base firmware's screens of a start and of a crash (base/diag.h, base/boot_screens.h), drawn through Gamut's names
 * for them (ui_hooks.h) as openpocket.c includes them; the chip's crash record and the 8 x 8 text are the PC's here */
#define OP_NAME "Gamut"
#define OP_VERSION "1.0b1"
#define OP_RAM_CODE px_block_label
#define OP_NOINIT
#define FM1_CRASH_MAGIC 0x43525348u
typedef struct { uint32_t magic, count, vec, pc, rets, emu, dbg, sp, psr, icfg, uptime_ms; } fm1_crash_t;
static fm1_crash_t fm1_crash;
#include "font8x8.h"
static void lcd_text(uint32_t x, uint32_t y, const char *s, uint16_t fg, uint16_t bg, uint32_t k)
{
    for (; *s; s++, x += 8u * k)
        for (uint32_t r = 0; r < 8u; r++) for (uint32_t c = 0; c < 8u; c++)
            lcd_rect(x + c * k, y + r * k, k, k, (FONT8X8[(*s < 0x20 || *s > 0x7E ? ' ' : *s) - 0x20][r] & (0x80u >> c)) ? fg : bg);
}
static int reboots;
static void fm1_reboot(void) { reboots++; }
#include "../ui_hooks.h"
#include "base/diag.h"
#include "../ui.h"
#include "../ui_boot.h"
#include "../ui_colors.h"               /* (the web editor's block colours: the screen must not show them) */

static int reds, gaps;                  /* pages that showed red, pages with pixels never drawn */
static void shot(const char *dir, const char *name)
{
    static int n;
    char p[512];
    snprintf(p, sizeof p, "%s/%02d_%s.ppm", dir, ++n, name);
    FILE *f = fopen(p, "wb");
    fprintf(f, "P6\n240 240\n255\n");
    for (int i = 0; i < 240 * 240; i++) {
        uint16_t c = fb[i];
        unsigned char rgb[3] = {(unsigned char)(((c >> 11) & 31) * 255 / 31), (unsigned char)(((c >> 5) & 63) * 255 / 63), (unsigned char)((c & 31) * 255 / 31)};
        fwrite(rgb, 1, 3, f);
    }
    fclose(f);
    int holes = 0, red = 0;
    for (int i = 0; i < 240 * 240; i++) {               /* (red: more red than amber or housing have for their green) */
        holes += fb[i] == POISON;
        red += fb[i] != POISON && (fb[i] >> 11) > 16 && ((fb[i] >> 5) & 63) < 24;
    }
    printf("%-28s %6lu px sent%s", name, px_sent, holes || red ? "" : "\n");
    if (holes) { printf("   %d pixels never drawn (magenta)\n", holes); gaps++; }
    else if (red) { printf("   %d red pixels: a fault is drawn in amber, never in red\n", red); reds++; }
    px_sent = 0;
}
static void poison(void) { for (int i = 0; i < 240 * 240; i++) fb[i] = POISON; }
static void status(void) { ui_status("dsp 42%", 0); }
static void full(void) { poison(); uc.screen = -1; ui_invalidate(); ui_render(); status(); }


/* ---- small letters: the engine's capitals are drawn small (UI_LC), a stored name as it is; the fonts fit the boxes ---- */
static int same_px(uint32_t x0, uint32_t y0, uint32_t x1, uint32_t y1, uint32_t w, uint32_t h)
{
    for (uint32_t j = 0; j < h; j++) for (uint32_t i = 0; i < w; i++) if (fb[(y0 + j) * 240u + x0 + i] != fb[(y1 + j) * 240u + x1 + i]) return 0;
    return 1;
}
static int small_letters(const char *d)
{
    char b[16];
    static const char *const V[][2] = {{"440 MS", "440 ms"}, {"-1.5 DB", "-1.5 dB"}, {"+5TH", "+5th"}, {"-m3", "-m3"}, {"FAST", "fast"}, {"ALL", "all"},
                                       {"C#", "C#"}, {"A", "A"}, {"P3", "p3"}, {"1+2", "1+2"}, {"55", "55"}};
    for (unsigned i = 0; i < sizeof V / sizeof V[0]; i++) {
        strcpy(b, V[i][0]); ui_value_text(b);
        if (strcmp(b, V[i][1])) { printf("small: the value \"%s\" reads \"%s\", not \"%s\"\n", V[i][0], b, V[i][1]); return 1; }
    }
    ui_box(0, 0, 120, "NOISE GATE", &GF_TX, C_HOUSING, C_GROUND, UI_LC); ft_box(0, 30, 120, "noise gate", &GF_TX, C_HOUSING, C_GROUND, 0);
    ui_box(0, 60, 120, "Twin 65", &GF_TX, C_HOUSING, C_GROUND, 0); ft_box(0, 90, 120, "twin 65", &GF_TX, C_HOUSING, C_GROUND, 0);
    if (!same_px(0, 0, 0, 30, 120, 22) || same_px(0, 60, 0, 90, 120, 22)) { printf("small: UI_LC draws capitals as small letters, and only UI_LC does\n"); return 1; }
    for (int k = 0; k < px_preset_count(); k++) {      /* the factory names are small letters, as data, and fit PLAY and the list */
        px_preset_t q; px_preset_factory(&q, k);
        for (const char *c = q.name; *c; c++) if (*c >= 'A' && *c <= 'Z') { printf("small: factory preset %d is \"%s\"\n", k + 1, q.name); return 1; }
        if (ft_width(&GF_NM, q.name) > 240u || ft_width(&GF_TX, q.name) > 174u) { printf("small: \"%s\" does not fit\n", q.name); return 1; }
    }
    { px_preset_t q; px_preset_factory(&q, 5); strcpy(q.name, "AMBIENT SWELL");   /* (a name saved in capitals before this version) */
      if (ft_width(&GF_NM, q.name) > 240u || ft_width(&GF_TX, q.name) > 174u) { printf("small: a stored name in capitals does not fit\n"); return 1; } }
    for (int blk = 0; blk < PX_NBLK; blk++) {           /* every label, name, model, setting and value the engine has fits its box */
        strcpy(b, px_block_label(blk)); ui_lower(b);
        if (ft_width(&GF_LB, b) > T_W - 4u) { printf("small: the label \"%s\" does not fit its key\n", b); return 1; }
        for (const char *c = b; *c; c++) if (!strchr(GF_HE.chars, *c)) { printf("small: the label \"%s\" has a letter the 40 px face lacks\n", b); return 1; }
        if (ft_width(&GF_HE, b) + 10u > P_LBL_W) { printf("small: the label \"%s\" does not fit beside the number, on its chip\n", b); return 1; }
        { char n[20]; strcpy(n, ui_block_name(blk)); ui_lower(n); if (ft_width(&GF_TX, n) > 136u) { printf("small: the name \"%s\" does not fit the band\n", n); return 1; } }
        for (int t = 0; t < px_ntypes(blk); t++) {
            if (ft_width(&GF_TX, px_type_name(blk, t)) > 184u) { printf("small: the model \"%s\" does not fit\n", px_type_name(blk, t)); return 1; }
            for (int k = 0; k < px_nparams(blk, t); k++) {
                char n[24]; strcpy(n, px_param_name(blk, t, k)); ui_lower(n);
                if (ui_list_n(blk, t, k)) { strcat(n, " 16/16"); if (ft_width(&GF_LB, n) > E_LIST_X - BAR_X) { printf("small: \"%s\" does not fit before its name\n", n); return 1; } continue; }
                if (ft_width(&GF_LB, n) > E_VAL_X - BAR_X) { printf("small: the setting \"%s\" does not fit\n", n); return 1; }
                for (int v = 0; v <= 100; v++) {
                    if (!px_param_text(blk, t, k, v, b)) continue;
                    if (blk == PX_B_CAB && t == PX_CAB_IR) ui_hz_text(b, k == 2 && v == 0); else ui_value_text(b);
                    for (const char *c = b; *c; c++) if (!strchr(GF_MD.chars, *c)) { printf("small: the value \"%s\" has a character the figures' font lacks\n", b); return 1; }
                    if (ft_width(&GF_MD, b) + 8u > 230u - E_VAL_X) { printf("small: the value \"%s\" does not fit its chip\n", b); return 1; }
                }
            }
        }
    }
    (void)d;
    return 0;
}
/* ---- the design review's quick wins (F1, F2, F3, F4): text that fits, and the state each screen shows ---- */
static int count_col(uint32_t x, uint32_t y, uint32_t w, uint32_t h, uint16_t col)
{
    int n = 0;
    for (uint32_t j = y; j < y + h; j++) for (uint32_t i = x; i < x + w; i++) n += fb[j * 240u + i] == col;
    return n;
}
static void play_again(void) { poison(); uc.screen = -1; ui_invalidate(); ui_render(); }
static int px_at(uint32_t x, uint32_t y, uint16_t c) { return fb[y * 240u + x] == c; }
/* ---- the palette's meanings (ui_palette.h): a block is on or off by light, not by a colour of its own; green is the lamp ---- */
static int ink_rows(uint32_t x, uint32_t y, uint32_t w, uint32_t h, uint16_t col)   /* the rows from the first to the last that show col */
{
    int top = -1, bot = -1;
    for (uint32_t j = 0; j < h; j++) if (count_col(x, y + j, w, 1, col)) { if (top < 0) top = (int)j; bot = (int)j; }
    return top < 0 ? 0 : bot - top + 1;
}
static int lamp_meanings(const char *d)
{
    load_preset(9); cur_preset = 9; ui_blk = PX_B_AMP; ui_home(); play_again(); ui_status("dsp 42%", UI_ST_NORM);
    for (int i = 0; i < PX_NBLK; i++) {                 /* (2 px into a key from its top, above its label) */
        int b = PRESET.order[i], on = PRESET.on[b] != 0;
        uint32_t x = tile_x(i) + T_W / 2u, y = tile_y(i);
        if (!px_at(tile_x(i) + 1u, y + (on ? T_ON : T_OFF) + 2u, on ? C_HOUSING : C_KEY)) { printf("line: block %d's key must be pale when on and dark when off\n", b); return 1; }
        if (!px_at(tile_x(i) + 1u, y + T_LINE, on ? C_HOUSING : C_LABEL) || !px_at(tile_x(i) - 2u, y + T_LINE, C_LABEL) || !px_at(tile_x(i) - 2u, y + T_LINE + 1u, C_LABEL))
            { printf("line: a key that is on sits on the line, one that is off below it, and the line runs on between the keys\n"); return 1; }
        if (!px_at(x, y + T_LANE + 1u, b == (int)ui_blk ? C_HOUSING : C_GROUND) || !px_at(x, y + T_LANE - 1u, C_GROUND)) { printf("line: the bar in the lane is under the selected block only\n"); return 1; }
    }
    if (count_col(0, T_Y0 + T_LINE, 240, 1, C_GROUND)) { printf("line: the line runs from edge to edge\n"); return 1; }
    for (int b = 0; b < PX_NBLK; b++)
        if (BLK_COL[b] != C_HOUSING && count_col(0, 0, 240, 240, BLK_COL[b])) { printf("lamp: PLAY shows block %d's colour\n", b); return 1; }
    int mark = count_col(0, 0, 25, S_H, C_LAMP);
    if (mark < 9 || count_col(0, 0, 240, 240, C_LAMP) != mark || count_col(0, 0, 240, 240, GRN)) { printf("lamp: PLAY's only green is the mark's lamp\n"); return 1; }
    master_vol = 0; ui_render();
    if (count_col(0, 0, 240, 240, C_LAMP) || count_col(0, 0, 25, S_H, C_LAMP_OFF) != mark) { printf("lamp: no sound passes at volume 0: the mark's lamp is unlit\n"); return 1; }
    master_vol = 80; ui_render();
    /* beside the number: the selected block's label, 40 px capitals' height, pale while its block is on, grey while off */
    if (!PRESET.on[PX_B_AMP] || !count_col(P_LBL_X, P_NUM_Y, P_LBL_W, 57, C_HOUSING)) { printf("label: an on block's label is pale\n"); return 1; }
    if (ink_rows(P_LBL_X, P_NUM_Y, P_LBL_W, 57, C_HOUSING) < 40 || ink_rows(6, P_NUM_Y, 98, 58, C_HOUSING) < 57) { printf("label: the label is 40 px tall at least and the number 58\n"); return 1; }
    PRESET.on[PX_B_AMP] = 0; ui_render(); shot(d, "play_selected_block_off");
    if (count_col(P_LBL_X, P_NUM_Y, P_LBL_W, 57, C_HOUSING) || !count_col(P_LBL_X, P_NUM_Y, P_LBL_W, 57, C_LABEL)) { printf("label: an off block's label is grey\n"); return 1; }
    for (uint32_t b = 0; b < PX_NBLK; b++) { ui_blk = b; ui_render(); }   /* (every label is drawn: fit_box counts one that is cut or lacks a glyph) */
    ui_blk = PX_B_AMP; ui_render();
    ui_push(); poison(); ui_render(); ui_status("dsp 42%", UI_ST_NORM);
    int lit = count_col(178, 6, 52, 19, C_LAMP_OFF);
    if (!px_at(180, 15, C_KEY) || lit < 40) { printf("lamp: block page: an off block has a dark key and an unlit lamp\n"); return 1; }
    for (int b = 0; b < PX_NBLK; b++)
        if (BLK_COL[b] != C_HOUSING && count_col(0, 0, 240, 240, BLK_COL[b])) { printf("lamp: the block page shows block %d's colour\n", b); return 1; }
    ui_knob(-1, 0); ui_push(); ui_render(); shot(d, "edit_on_key_selected");   /* (back from MODEL: ON; PUSH switches it) */
    if (!PRESET.on[PX_B_AMP] || !px_at(180, 15, C_HOUSING) || count_col(178, 6, 52, 19, C_LAMP_KEY) != lit || count_col(0, 0, 240, 240, C_LAMP)) { printf("lamp: block page: an on block has a pale key and the lamp lit in the key's green\n"); return 1; }
    if (!px_at(204, 4, C_HOUSING) || !px_at(204, 5, C_PLATE)) { printf("lamp: block page: the ring round the selected ON key is a pixel of plate away from it\n"); return 1; }
    ui_knob(1, 0); ui_knob(1, 0); ui_push(); ui_render(); shot(d, "edit_value_inverted");   /* (MODEL, the first setting, edit it) */
    if (ui_mode != M_EDIT || ui_item != 2u || !count_col(E_LIST_X, E_P0 + 1u, 230u - E_LIST_X, 22, C_GRAPHITE)) { printf("lamp: a value being changed is inverted: graphite on housing\n"); return 1; }
    ui_push(); ui_render();
    if (count_col(E_LIST_X, E_P0 + 1u, 230u - E_LIST_X, 22, C_GRAPHITE)) { printf("lamp: the value is as it was once the change is done\n"); return 1; }
    ui_home(); load_preset(9); play_again(); ui_status("dsp 42%", UI_ST_NORM);
    /* a block picked up: its key above the line and its label's chip, both amber; the bar under it amber too */
    { int i = ui_pos_of(PX_B_AMP);
      ui_move_start(); ui_render(); shot(d, "play_block_picked_up");
      if (!px_at(tile_x(i) + T_W / 2u, tile_y(i) + 2u, C_AMBER) || !px_at(tile_x(i) + T_W / 2u, tile_y(i) + T_LANE + 1u, C_AMBER) || !px_at(P_LBL_X + 8u, P_NUM_Y + 2u, C_AMBER)
          || !count_col(P_LBL_X, P_NUM_Y, P_LBL_W, 57, C_GRAPHITE)) { printf("line: a block picked up rises above the line in amber, and its label stands on an amber chip\n"); return 1; }
      ui_move_cancel(); ui_render();
      if (count_col(0, S_H, 240, F_Y - S_H, C_AMBER)) { printf("line: put back, nothing stays amber\n"); return 1; } }
    /* the battery: the charge turns amber at 30 %, the figure too at 15 %; neither is green or red */
    { int m = bat_mv;
      bat_pct = 31; ui_render(); if (count_col(BAT_X, 0, 59, S_H, C_AMBER)) { printf("lamp: a battery at 31 %% is not amber\n"); return 1; }
      bat_pct = 30; ui_render(); if (!count_col(BAT_X + 2u, 8, 16, 6, C_AMBER) || count_col(BAT_X + 25u, 0, 34, S_H, C_AMBER)) { printf("lamp: at 30 %% the charge is amber, the figure not yet\n"); return 1; }
      bat_pct = 15; ui_render(); shot(d, "play_battery_low"); if (!count_col(BAT_X + 25u, 0, 34, S_H, C_AMBER)) { printf("lamp: at 15 %% the figure is amber too\n"); return 1; }
      bat_pct = 100; ui_render(); bat_pct = -1; bat_mv = m; ui_render(); }
    return 0;
}
static int quick_wins(const char *d)
{
    char c[16];
    /* F1: every load text the main loop can build fits the box it is drawn in (it used to cut "BYP 2C 150%" to "BYP 2C 15"): its
     * word in the labels' face, 2 px, its figure in the figures' face. The peak of an overload is in PLAY's footer instead. */
    for (uint32_t l = 0; l <= 999u; l++)
        for (int m = 0; m < 4; m++) {
            int safe = m & 1, late = (m >> 1) & 1, sp = 0;
            ui_load_text(c, l, safe, 0, late);
            while (c[sp] != ' ') sp++;
            c[sp] = 0;
            if (ft_width(&GF_LB, c) + 2u + ft_width(&GF_MS, c + sp + 1) > ST_W) { printf("F1: \"%s %s\" does not fit the box of %u px\n", c, c + sp + 1, ST_W); return 1; }
        }
    if (ft_width(&GF_LB, "loading") > ST_W) { printf("F1: LOADING does not fit the load figure's box\n"); return 1; }
    ui_load_text(c, 150, 0, 1, 0);
    if (strcmp(c, "peak 150%")) { printf("F1: a peak of 150%% reads \"%s\"\n", c); return 1; }
    ui_load_text(c, 88, 0, 0, 1);
    if (strcmp(c, "dsp 88%!")) { printf("F11: a late block reads \"%s\"\n", c); return 1; }
    /* F1: overload is an amber band with its sign and an instruction, on PLAY (in the plate's place, taller) and on a block page (footer) */
    load_preset(9); cur_preset = 9; ui_blk = PX_B_AMP; ui_home(); play_again(); ui_status("dsp 42%", UI_ST_NORM);
    if (count_col(0, 0, 240, 3, C_AMBER) || uc.dy) { printf("F1: PLAY shows the band without an overload\n"); return 1; }
    poison(); ui_status("peak 150%", UI_ST_BYPASS); ui_render(); shot(d, "play_overload_banner");
    if (count_col(0, 0, 240, S_BAN, C_AMBER) < 240 * 20 || !px_at(14, 9, C_GRAPHITE) || count_col(28, 4, 204, 22, C_GRAPHITE) == 0) { printf("F1: PLAY overload: no amber band of 30 px with the sign and graphite words\n"); return 1; }
    if (count_col(0, F_TY, 240, 16, C_HOUSING) == 0 || count_col(0, F_TY, 240, 16, C_AMBER) == 0) { printf("F1: PLAY overload: the footer says what to do, and the peak in amber\n"); return 1; }
    if (count_col(0, S_BAN, 240, 1, C_GROUND) != 240 || count_col(0, F_Y - 1u, 240, 1, C_GROUND) != 240 || tile_y(11) + T_ROW >= F_Y) { printf("F1: PLAY overload: the page stands clear below the band and above the footer\n"); return 1; }
    ui_status("peak 999%", UI_ST_BYPASS); ui_render();   /* (the widest peak: fit_box counts a footer that is cut) */
    ui_push(); ui_render(); shot(d, "edit_overload_banner");
    if (count_col(0, F_Y, 240, 18, C_AMBER) < 240 * 3 || count_col(28, F_TY, 212, 16, C_GRAPHITE) == 0 || !px_at(14, F_TY + 3u, C_GRAPHITE)) { printf("F1: block page overload: the footer is not amber with the sign and graphite words\n"); return 1; }
    ui_status("dsp 42%", UI_ST_NORM); ui_render();
    if (count_col(0, F_Y, 240, 18, C_AMBER)) { printf("F1: the footer stays amber after the overload ends\n"); return 1; }
    ui_home(); play_again(); ui_status("dsp 42%", UI_ST_NORM);
    if (count_col(0, 0, 240, S_BAN, C_AMBER) || uc.dy) { printf("F1: the band stays after the overload ends\n"); return 1; }
    /* F2: LOADING shows amber on the MODEL row being edited (the name greys), and amber in the corner on PLAY */
    {
        play_again(); ui_status("dsp 61%", UI_ST_NORM);
        if (count_col(ST_X, 0, ST_W, S_H, C_AMBER) || !count_col(ST_X, 0, ST_W, S_H, C_HOUSING) || !count_col(ST_X, 0, ST_W, S_H, C_LABEL)) { printf("F2: PLAY: the load reads its word in grey and its figure in housing\n"); return 1; }
        ui_status("dsp 61%", UI_ST_LOADING); ui_render(); shot(d, "play_loading");
        if (!count_col(ST_X, S_TY, ST_W, 16, C_AMBER) || count_col(ST_X, 0, ST_W, S_H, C_HOUSING)) { printf("F2: PLAY: the corner must read LOADING in amber\n"); return 1; }
        ui_status("dsp 61%", UI_ST_NORM); ui_render();
        if (count_col(ST_X, 0, ST_W, S_H, C_AMBER)) { printf("F2: PLAY: the load figure must come back when the model plays\n"); return 1; }
        ui_push(); poison(); ui_render(); ui_status("dsp 61%", UI_ST_NORM);
        int row = count_col(BAR_X, E_P0 + 6u, E_LIST_X - BAR_X, 16, C_AMBER);
        ui_status("dsp 61%", UI_ST_LOADING); ui_render(); shot(d, "edit_model_loading");
        if (count_col(BAR_X, E_P0 + 6u, E_LIST_X - BAR_X, 16, C_AMBER) <= row || count_col(E_LIST_X, E_P0 + 1u, 230u - E_LIST_X, 22, C_HOUSING)) { printf("F2: block page: the MODEL row must read LOADING in amber, the name in grey\n"); return 1; }
        if (count_col(ST_X, F_TY, ST_W, 16, C_AMBER) || !count_col(ST_X, F_TY, ST_W, 16, C_HOUSING)) { printf("F2: block page: the corner keeps the load figure\n"); return 1; }
        ui_status("dsp 61%", UI_ST_NORM); ui_render();
        if (count_col(BAR_X, E_P0 + 6u, E_LIST_X - BAR_X, 16, C_AMBER) != row) { printf("F2: block page: the MODEL row must come back\n"); return 1; }
        /* a footer names each control in housing and what it does in label grey, clear of the load figure */
        if (!count_col(8, F_TY, ST_X - 10u, 16, C_HOUSING) || !count_col(8, F_TY, ST_X - 10u, 16, C_LABEL) || count_col(ST_X - 12u, F_TY, 12, 16, C_PLATE) != 12 * 16) { printf("footer: a block page's hints are a pale control and a grey action each, and end before the load figure\n"); return 1; }
        ui_home(); play_again(); ui_status("dsp 42%", UI_ST_NORM);
    }
    /* F3: a footswitch on a block page goes back to PLAY (on the block it was on); the band carries the preset number */
    ui_blk = PX_B_AMP; ui_mode = M_EDIT; ui_item = 2;
    ui_preset_step(1);
    if (ui_mode != M_CHAIN || ui_item != 0 || ui_blk != PX_B_AMP || cur_preset != 10) { printf("F3: a footswitch on a block page must return to PLAY\n"); return 1; }
    ui_preset_step(-1);
    if (cur_preset != 9) { printf("F3: the footswitch must still change the preset\n"); return 1; }
    ui_enter_block(PX_B_AMP); poison(); uc.screen = -1; ui_invalidate(); ui_render();
    int band = count_col(8, 6, 24, 19, C_KEY);
    cur_preset = 11; load_preset(11); ui_render(); shot(d, "edit_band_after_midi_change");   /* (a Program Change keeps the page) */
    if (!band || count_col(8, 6, 24, 19, C_KEY) == band) { printf("F3: the band must show the new preset number after a MIDI change\n"); return 1; }
    ui_home(); cur_preset = 9; load_preset(9);
    /* F4: while EDITED shows (in amber, in the top plate), the footer names SAVE */
    play_again(); ui_status("dsp 42%", UI_ST_NORM);
    if (count_col(0, F_TY, 240, 16, C_AMBER) || count_col(0, 0, 240, S_H, C_AMBER)) { printf("F4: SAVE is named without an edit\n"); return 1; }
    PRESET.p[PX_B_AMP][1] ^= 7u; ui_render(); shot(d, "play_edited_save_hint");
    if (!count_col(0, F_TY, 240, 16, C_AMBER) || !count_col(BAT_X + 59u, 0, ST_X - BAT_X - 59u, S_H, C_AMBER)) { printf("F4: the plate must say EDITED and the footer name SAVE, both in amber\n"); return 1; }
    load_preset(9); ui_render();
    if (count_col(0, F_TY, 240, 16, C_AMBER) || count_col(0, 0, 240, S_H, C_AMBER)) { printf("F4: EDITED or the SAVE hint stays after the edit is gone\n"); return 1; }
    return lamp_meanings(d) || small_letters(d);
}

/* ---- the full overhaul (v42): the design review's F4 to F17, through ui.h's own controls (ui_buttons, ui_turn, ui_action) ---- */
static uint32_t T = 100000u;                            /* the simulated clock (ms); ui_buttons runs every 5 ms as the main loop */
static void hold(uint32_t mask, uint32_t ms) { for (uint32_t t = 0; t < ms; t += 5u) { ui_buttons(T, mask); T += 5u; } }
static void tap(int b) { hold(1u << b, 40); hold(0, 5); }
#define CHECK(c, m) do { if (!(c)) { printf("%s\n", m); return 1; } } while (0)
/* the diagnostics as pictures (v42): each figure beside its graphic, colours by state, two pages turned by the knob */
static int diagnostics(const char *d)
{
    char b[48];
    ui_dg.load = 61; ui_dg.peak = 70; ui_dg.cores = 2; ui_dg.split = 1; ui_dg.guard = 93; ui_dg.cl[0] = 52; ui_dg.cl[1] = 56;
    ui_dg.late = 0; ui_dg.bypass = 0;
    diag_draw(); shot(d, "diagnostics");
    CHECK(dg_page == 0 && count_col(10, 60, 100, 6, C_HOUSING) && !count_col(10, 60, 100, 6, C_AMBER), "diag: a load of 61 % is a housing bar");
    CHECK(px_at(10 + dg_w(93, 100, 220) - 1, 58, C_AMBER) && px_at(10 + dg_w(93, 100, 220) - 1, 67, C_AMBER), "diag: the guard's tick at 93 %");
    CHECK(count_col(88, 93, 144, 6, C_HOUSING) && count_col(88, 109, 144, 6, C_HOUSING), "diag: a bar for each core");
    {
        uint8_t top[DG_BLK];
        int n = dg_top(top, DG_BLK);
        CHECK(n == 4 && top[0] == PX_NBLK && top[1] == PX_B_REVERB && top[2] == PX_B_DELAY && top[3] == PX_B_CAB, "diag: CPU per block, costliest first");
        CHECK(count_col(52, 163, 148, 5, C_HOUSING) && !count_col(52, 179, 148, 5, C_HOUSING), "diag: the heaviest block highlighted, the others not");
    }
    CHECK(count_col(2, 122, 76, 18, C_HOUSING) && !count_col(2, 122, 76, 18, C_AMBER), "diag: no late block: its chip in housing");
    ui_dg.load = 86; diag_draw();
    CHECK(count_col(10, 60, 100, 6, C_AMBER) && !count_col(10, 60, 100, 6, C_HOUSING), "diag: above 80 % the load turns amber");
    ui_dg.load = 61; ui_dg.late = 1; bat_raw[2] = 3; diag_draw(); shot(d, "diagnostics_late");
    CHECK(count_col(10, 60, 100, 6, C_AMBER) && count_col(2, 122, 76, 18, C_AMBER) && !count_col(2, 122, 76, 18, C_HOUSING), "diag: a late block: the load and its chip in amber");
    ui_dg.late = 0; bat_raw[2] = 0; ui_dg.load = 61; ui_dg.split = 0; diag_draw();
    CHECK(!count_col(88, 93, 144, 6, C_HOUSING), "diag: no layer split: no core bars (CPU0 --)");
    ui_dg.split = 1;
    /* every figure fits its box at its widest */
    dg_pct(b, "dsp ", 999); CHECK(ft_width(&GF_TX, b) <= 120u, "diag: dsp 999% fits");
    dg_pct(b, "peak ", 999); CHECK(ft_width(&GF_LB, b) <= 104u, "diag: peak 999% fits");
    CHECK(ft_width(&GF_LB, "cpu1 100%") <= 78u && ft_width(&GF_LB, "late 9999") <= 70u && ft_width(&GF_LB, "clip 9999") <= 70u
          && ft_width(&GF_LB, "bypass off") <= 76u && ft_width(&GF_LB, "pk 999%") <= 64u && ft_width(&GF_LB, "cores 2C") <= 80u
          && ft_width(&GF_LB, "guard 93%") <= 80u, "diag: the chips and core figures fit");
    CHECK(ft_width(&GF_LB, "soft clip: 99999 blocks") <= 204u && ft_width(&GF_LB, "raw  C9 4095  ch 1") <= DG_W
          && ft_width(&GF_LB, "R -199 dB") <= 74u && ft_width(&GF_LB, "cut 9999") <= 84u, "diag: page 2's figures fit");
    /* the knob turns the page; both pages are drawn whole */
    poison(); ui_turn(1, 0); CHECK(dg_page == 1, "diag: the knob turns to page 2");
    diag_draw(); shot(d, "diagnostics_2");
    CHECK(count_col(82, 58, 150, 8, C_HOUSING) && count_col(82, 58, 150, 8, DG_CLIP_ZONE) && DG_CLIP_ZONE != C_RIM, "diag: an input meter, in housing, with its clip zone");
    CHECK(!px_at(DG_X, 112, C_AMBER), "diag: no recent soft clip: the marker is dark");
    bat_raw[3]++; diag_draw(); CHECK(px_at(DG_X + 2, 114, C_AMBER), "diag: a new soft clip lights the marker");
    for (int i = 0; i < 25; i++) diag_draw();
    CHECK(!px_at(DG_X + 2, 114, C_AMBER), "diag: the marker goes dark again");
    CHECK(count_col(DG_X + 3, 159, 40, 16, C_HOUSING), "diag: the battery's cell is filled");
    poison(); ui_turn(-1, 0); diag_draw(); shot(d, "diagnostics_1_again");
    CHECK(dg_page == 0, "diag: and back to page 1");
    return 0;
}
static int overhaul(const char *d)
{
    char c[16];
    load_preset(9); cur_preset = 9; ui_blk = PX_B_AMP; ui_mode = M_CHAIN; ui_item = 0; full();
    /* F6: a click of PUSH on PLAY opens the block at its release, no wait; a 2nd one within 350 ms makes it MOVE */
    hold(1u << UB_PUSH, 60); CHECK(ui_mode == M_CHAIN, "F6: PUSH acts at its release");
    hold(0, 5); CHECK(ui_mode == M_BLOCK && ui_blk == PX_B_AMP, "F6: one click opens the block at once");
    hold(1u << UB_PUSH, 60); hold(0, 5); CHECK(ui_mode == M_MOVE && ui_blk == PX_B_AMP, "F6: a 2nd click within 350 ms: MOVE");
    tap(UB_HOME); CHECK(ui_mode == M_CHAIN, "MOVE: HOME puts the block back");
    tap(UB_PUSH); hold(0, 400); tap(UB_PUSH); CHECK(ui_mode == M_EDIT, "F6: a 2nd click after 350 ms edits the model, as on any block page");
    tap(UB_HOME);
    tap(UB_PUSH); ui_turn(1, 0); ui_turn(-1, 0); tap(UB_PUSH); CHECK(ui_mode == M_EDIT, "F6: the knob between the clicks: no MOVE");
    tap(UB_HOME);
    hold(1u << UB_PUSH, 850); CHECK(ui_mode == M_SAVE, "hold PUSH: SAVE");
    hold(0, 5); CHECK(ui_mode == M_SAVE, "the release of that hold stays on SAVE");
    tap(UB_HOME); CHECK(ui_mode == M_CHAIN, "HOME leaves SAVE");
    hold(1u << UB_FX, 850); hold(0, 5); CHECK(ui_mode == M_MIDI, "hold FX: MIDI");
    tap(UB_HOME); CHECK(ui_mode == M_CHAIN, "HOME leaves MIDI");
    /* F5: both footswitches: the first acts at once, the other within 150 ms takes that step back and opens the tuner */
    hold(1u << UB_FSUP, 60); CHECK(cur_preset == 10, "F5: the first footswitch acts at its press");
    poison();
    hold(1u << UB_FSUP | 1u << UB_FSDN, 60);
    CHECK(ui_mode == M_TUNER && cur_preset == 9 && a_tmute, "F5: both footswitches: the step back, the tuner, muted");
    tuner_draw(108.0f); shot(d, "tuner_flat");
    CHECK(count_col(4, TN_NOTE_Y + 30u, 36, 22, C_HOUSING) && !count_col(200, TN_NOTE_Y + 30u, 36, 22, C_HOUSING), "F12: flat: an arrow on the left, toward in tune");
    CHECK(count_col(0, 30, 240, 4, C_GROUND) == 240 * 4 && count_col(0, TN_Y + 41u, 240, F_Y - TN_Y - 41u, C_GROUND) == 240 * (int)(F_Y - TN_Y - 41u), "F12: no diagnostics on the tuner page");
    CHECK(ink_rows(40, TN_NOTE_Y, 160, 83, C_HOUSING) >= 80 && !count_col(0, 30, 240, F_Y - 30u, C_LAMP), "tuner: out of tune: the note in housing, 81 px tall, nothing lit");
    CHECK(count_col(110, TN_Y + 18u, 20, 6, C_LAMP_OFF) && px_at(120 - 64, TN_Y, C_HOUSING) && px_at(120 - 64, TN_Y + 17u, C_HOUSING), "tuner: 32 cents flat: the needle 64 px left of the middle, the window unlit");
    tuner_draw(112.5f); CHECK(!count_col(4, TN_NOTE_Y + 30u, 36, 22, C_HOUSING) && count_col(200, TN_NOTE_Y + 30u, 36, 22, C_HOUSING), "F12: sharp: the arrow on the right");
    tuner_draw(108.7366f);                               /* (20 cents flat: the needle on a tick) */
    CHECK(px_at(80, TN_Y, C_HOUSING) && !px_at(120 - 64, TN_Y, C_HOUSING), "tuner: the needle follows the note");
    tuner_draw(110.0f); CHECK(!count_col(4, TN_NOTE_Y + 30u, 36, 22, C_HOUSING) && !count_col(200, TN_NOTE_Y + 30u, 36, 22, C_HOUSING), "F12: in tune: no arrow");
    CHECK(count_col(40, TN_NOTE_Y, 160, 83, C_LAMP) && !count_col(40, TN_NOTE_Y, 160, 83, C_HOUSING) && count_col(110, TN_Y + 18u, 20, 6, C_LAMP) && px_at(120, TN_Y, C_HOUSING), "tuner: in tune: the note and the window are the lamp's green, the needle in the middle");
    CHECK(px_at(80, TN_Y, C_GROUND) && px_at(80, TN_Y + 10u, C_RIM) && px_at(79, TN_Y + 10u, C_GROUND) && px_at(80, TN_Y + 14u, C_RIM) && px_at(20, TN_Y + 6u, C_LABEL) && px_at(220, TN_Y + 6u, C_LABEL),
          "tuner: the scale is whole again where the needle was: a tick every 10 cents, the end ones tall");
    hold(0, 300);
    hold(1u << UB_FSDN, 40); hold(1u << UB_FSDN | 1u << UB_FSUP, 40); hold(0, 300);
    CHECK(ui_mode == M_CHAIN && cur_preset == 9 && !a_tmute, "F5: both footswitches leave the tuner, the preset as it was");
    tap(UB_FSUP); hold(0, 200); tap(UB_FSDN); hold(0, 200);
    CHECK(ui_mode == M_CHAIN && cur_preset == 9, "F5: footswitches 200 ms apart are two presses");
    tap(UB_FSUP); tap(UB_FSDN); hold(0, 200);
    CHECK(ui_mode == M_CHAIN && cur_preset == 9, "F5: one footswitch released before the other goes down: two presses");
    /* F12: hold HOME: the tuner; held on: the diagnostics (the photo the release notes ask for), with the sound on */
    hold(1u << UB_HOME, 750); CHECK(ui_mode == M_TUNER, "hold HOME 0.7 s: the tuner");
    poison();
    hold(1u << UB_HOME, 700); CHECK(ui_mode == M_DIAG && !a_tmute, "F12: HOME held on: the diagnostics, the sound on");
    hold(0, 5); CHECK(ui_mode == M_DIAG, "the release leaves the diagnostics open");
    if (diagnostics(d)) return 1;
    tap(UB_FX); CHECK(ui_mode == M_CHAIN, "any control leaves the diagnostics");
    full();
    /* F11: the load figure in plain words, amber when high or when a block ran late (which adds "!") */
    CHECK(ui_load_kind(85, 0, 0, 0, 0) == UI_ST_HIGH && ui_load_kind(80, 0, 0, 0, 0) == UI_ST_NORM && ui_load_kind(85, 1, 0, 0, 0) == UI_ST_NORM
          && ui_load_kind(85, 0, 0, 1, 0) == UI_ST_LATE && ui_load_kind(85, 0, 1, 1, 0) == UI_ST_BYPASS && ui_load_kind(5, 0, 1, 1, 1) == UI_ST_LOADING,
          "F11: the load's kind");
    ui_load_text(c, 42, 0, 0, 0); CHECK(!strcmp(c, "dsp 42%"), "F11: the load reads dsp 42%");
    ui_status("dsp 85%", UI_ST_HIGH); ui_render(); shot(d, "play_dsp_high");
    CHECK(count_col(ST_X, S_TY, ST_W, 16, C_AMBER), "F11: a high load in amber");
    ui_status("dsp 91%!", UI_ST_LATE); ui_render(); CHECK(count_col(ST_X, S_TY, ST_W, 16, C_AMBER), "F11: a late block in amber");
    ui_status("dsp 42%", UI_ST_NORM); ui_render(); CHECK(!count_col(ST_X, S_TY, ST_W, 16, C_AMBER), "F11: a normal load is not amber");
    /* F8: HOME on PLAY: the preset list; the knob browses without loading, PUSH loads, HOME goes back */
    poison(); tap(UB_HOME); CHECK(ui_mode == M_LIST, "F8: HOME on PLAY: the preset list"); ui_render(); shot(d, "preset_list");
    CHECK(count_col(12, LS_Y0 + 2u * LS_ROW, 8, LS_ROW, C_LAMP) && count_col(0, 0, 240, 240, C_LAMP) == count_col(12, LS_Y0 + 2u * LS_ROW, 8, LS_ROW, C_LAMP), "F8: the playing preset, and it alone, has the lamp");
    for (int i = 0; i < 3; i++) ui_turn(1, 0);
    ui_render(); shot(d, "preset_list_browsed");
    CHECK(!count_col(0, 0, 240, 240, C_LAMP), "F8: browsed away from the playing preset: no lamp in sight");
    for (int k = 0; k < px_preset_count(); k++) { px_preset_t q; px_preset_factory(&q, k); CHECK(ft_width(&GF_TX, q.name) <= 174u, "F8: a factory name does not fit its row of the list"); }
    CHECK(cur_preset == 9 && ls_at == 12, "F8: the knob browses without loading");
    tap(UB_PUSH); CHECK(cur_preset == 12 && ui_mode == M_CHAIN, "F8: PUSH loads the preset shown and returns to PLAY");
    tap(UB_HOME); ui_turn(-1, 0); tap(UB_HOME); CHECK(ui_mode == M_CHAIN && cur_preset == 12, "F8: HOME leaves the list without loading");
    tap(UB_HOME); tap(UB_FSUP); CHECK(ui_mode == M_CHAIN && cur_preset == 13, "F8: a footswitch on the list steps and shows PLAY");
    tap(UB_HOME); tap(UB_AMP); CHECK(ui_mode == M_BLOCK && ui_blk == PX_B_AMP && PRESET.on[PX_B_AMP], "F8: a block button on the list opens it, without switching it");
    ui_home(); full();
    /* F4: one unsaved edit survives a preset change and comes back with its slot */
    load_preset(9); cur_preset = 9; full();
    PRESET.p[PX_B_AMP][1] ^= 7u;
    uint8_t ed = PRESET.p[PX_B_AMP][1];
    ui_preset_step(1); CHECK(cur_preset == 10 && !ui_dirty(), "F4: the next preset plays as saved");
    ui_preset_step(-1); ui_render(); shot(d, "play_edit_kept");
    CHECK(ui_dirty() && PRESET.p[PX_B_AMP][1] == ed, "F4: back on the edited preset: the edit is back, EDITED");
    ui_preset_step(1); ui_preset_step(1); ui_preset_step(-1); ui_preset_step(-1);
    CHECK(ui_dirty() && PRESET.p[PX_B_AMP][1] == ed, "F4: the edit waits while other presets play");
    ui_preset_step(1); PRESET.p[PX_B_AMP][2] ^= 3u; ui_preset_step(-1);
    CHECK(!ui_dirty(), "F4: an edit elsewhere takes the place of the first");
    ui_preset_step(1); CHECK(ui_dirty(), "F4: that edit is kept in turn");
    load_preset(10); PRESET.p[PX_B_AMP][1] ^= 5u; { px_preset_t q = PRESET; ui_preset_step(1); st_save(10, &q); st_gen++; } ui_preset_step(-1);
    CHECK(!ui_dirty() && st_saved(10), "F4: a slot saved over meanwhile: the kept edit is dropped");
    st_reset(10); st_gen++; load_preset(9); cur_preset = 9;
    /* F7: a list setting steps one filled item a detent, fast or not, skips empty slots, stops at the last; it shows its place */
    PRESET.type[PX_B_AMP] = PX_AMP_NAM; PRESET.on[PX_B_AMP] = 1; PRESET.p[PX_B_AMP][0] = (uint8_t)px_nam_knob(0);
    ui_blk = PX_B_AMP; ui_mode = M_EDIT; ui_item = 2; full();
    for (int i = 1; i < PX_NAM_NFACT; i++) { ui_turn(1, i & 1); CHECK(px_nam_model(PRESET.p[PX_B_AMP][0]) == i, "F7: one model a detent, fast or not"); }
    ui_turn(1, 0); CHECK(px_nam_model(PRESET.p[PX_B_AMP][0]) == PX_NAM_NFACT + 2, "F7: the empty user slots are skipped");
    ui_turn(1, 0); CHECK(px_nam_model(PRESET.p[PX_B_AMP][0]) == PX_NAM_NFACT + 2, "F7: it stops at the last filled one");
    ui_render(); shot(d, "edit_nam_model_list");
    { int n, at = ui_list_place(PX_B_AMP, PX_NAM_N, PX_NAM_NFACT + 2, &n); CHECK(n == 13 && at == 13, "F7: its place: 13 of 13"); }
    for (int i = 0; i < 40; i++) ui_turn(-1, 1);
    CHECK(px_nam_model(PRESET.p[PX_B_AMP][0]) == 0, "F7: back to the first model, and no further");
    PRESET.type[PX_B_CAB] = PX_CAB_IR; PRESET.on[PX_B_CAB] = 1; PRESET.p[PX_B_CAB][0] = (uint8_t)px_ir_knob(1); PRESET.p[PX_B_CAB][1] = 30; PRESET.p[PX_B_CAB][2] = 0;
    ui_blk = PX_B_CAB; ui_mode = M_EDIT; ui_item = 2; full(); shot(d, "edit_user_ir_list");
    ui_turn(1, 0); CHECK(px_ir_slot(PRESET.p[PX_B_CAB][0]) == 4, "F7: USER IR: the next filled slot");
    ui_turn(1, 0); CHECK(px_ir_slot(PRESET.p[PX_B_CAB][0]) == 4, "F7: USER IR: stops at the last filled slot");
    {   /* F17: the cut frequencies with their unit */
        char b[16];
        strcpy(b, "89"); ui_hz_text(b, 0); CHECK(!strcmp(b, "89 Hz"), "F17: Hz");
        strcpy(b, "6325"); ui_hz_text(b, 0); CHECK(!strcmp(b, "6.3 kHz"), "F17: kHz");
        strcpy(b, "20000"); ui_hz_text(b, 1); CHECK(!strcmp(b, "off"), "F17: HIGH CUT at 0 is off");
        for (int v = 0; v <= 100; v++)
            for (int k = 1; k <= 2; k++) {
                px_param_text(PX_B_CAB, PX_CAB_IR, k, v, b); ui_hz_text(b, k == 2 && v == 0);
                CHECK(ft_width(&GF_MD, b) + 8u <= 230u - E_VAL_X, "F17: a cut frequency does not fit its box");
            }
    }
    /* F14: a block's model is on its page, a PUSH away, not on PLAY: PLAY stays as it is when a NAM amp's model changes */
    ui_home(); ui_blk = PX_B_AMP; full();
    { static uint16_t was[240 * 240];
      memcpy(was, fb, sizeof was);
      PRESET.p[PX_B_AMP][0] = (uint8_t)px_nam_knob(5); ui_render();
      CHECK(ui_dirty() && !memcmp(was, fb, sizeof was), "F14: PLAY does not name a block's model");
      ui_push(); full(); shot(d, "edit_model_on_its_page");
      int m0 = count_col(E_LIST_X, E_P0 + 1u, 230u - E_LIST_X, 22, C_HOUSING);
      PRESET.p[PX_B_AMP][0] = (uint8_t)px_nam_knob(0); ui_render();
      CHECK(m0 && count_col(E_LIST_X, E_P0 + 1u, 230u - E_LIST_X, 22, C_HOUSING) != m0, "F14: the block page names the NAM model, and follows it");
      PRESET.p[PX_B_AMP][0] = (uint8_t)px_nam_knob(5); }
    /* F9: the block page's selection goes in the order drawn: ON at the top, MODEL, the settings */
    ui_blk = PX_B_AMP; ui_mode = M_BLOCK; ui_item = 0;
    ui_turn(-1, 0); CHECK(ui_item == 1u, "F9: back from MODEL: ON");
    ui_turn(1, 0); CHECK(ui_item == 0u, "F9: on from ON: MODEL");
    ui_turn(1, 0); CHECK(ui_item == 2u, "F9: on from MODEL: the first setting");
    ui_item = 1; ui_turn(-1, 0); CHECK((int)ui_item == ui_nitems() - 1, "F9: back from ON: the last setting");
    ui_turn(1, 0); CHECK(ui_item == 1u, "F9: on from the last setting: ON");
    /* F10: FX steps through its blocks in the preset's chain order, as the tiles read */
    load_preset(9); cur_preset = 9; ui_home();
    for (int i = 0, last = -1; i < 7; i++) {
        tap(UB_FX);
        int pos = ui_pos_of(ui_blk);
        CHECK(ui_mode == M_BLOCK && ui_is_fx(ui_blk) && pos > last, "F10: FX goes on along the chain");
        last = pos;
    }
    tap(UB_FX); CHECK(ui_blk == PRESET.order[0] || ui_pos_of(ui_blk) < 3, "F10: after the last, FX starts again from the first");
    /* F17: SYN's page is SYNTH; a block of one model shows no arrows */
    CHECK(!strcmp(ui_block_name(PX_B_SYN), "SYNTH"), "F17: SYN's page is SYNTH");
    ui_blk = PX_B_GATE; ui_mode = M_BLOCK; ui_item = 0; full(); shot(d, "edit_gate_no_arrows");
    CHECK(px_ntypes(PX_B_GATE) == 1 && !count_col(8, E_TYPE_Y, 20, 23, C_LABEL), "F17: NOISE GATE: no arrows");
    /* F15, F16: SAVE says a copy keeps its name; RESTORE FACTORY says RESTORE and does nothing on a factory sound */
    ui_home(); load_preset(9); cur_preset = 9; full();
    poison(); save_open(); save_knob(1); save_draw(); shot(d, "save_copy_keeps_name");
    CHECK(count_col(0, 190, 240, 16, C_LABEL), "F15: SAVE to another slot says the name stays");
    CHECK(ink_rows(0, 76, 240, 58, C_HOUSING) >= 57, "SAVE: the slot's number is as tall as PLAY's");
    while (sv_dest != SV_FACTORY) save_knob(-1);
    save_draw(); shot(d, "save_restore_nothing");
    CHECK(sv_dest == SV_FACTORY && !st_saved(9), "F16: RESTORE FACTORY");
    tap(UB_PUSH); CHECK(ui_mode == M_SAVE && !st_saved(9), "F16: PUSH does nothing when there is nothing to restore");
    tap(UB_HOME); CHECK(ui_mode == M_CHAIN, "HOME leaves SAVE");
    full();
    return 0;
}

/* the update's screen (px_usb.h draws it through OP_OTA_SCREEN): a dot for each step, the running one the lamp; a failure in amber */
static int update_screen(const char *d)
{
    poison(); ui_update_show(2, 0); shot(d, "update_step_2");
    int dot = count_col(98, 118, 8, 8, C_LAMP);
    CHECK(!count_col(0, 0, 240, 240, POISON), "update: the whole screen is drawn");
    CHECK(dot >= 40 && count_col(0, 110, 240, 24, C_LAMP) == dot, "update: the step that runs, and it alone, is the lamp");
    CHECK(px_at(84, 122, C_HOUSING) && px_at(120, 122, C_RIM) && px_at(138, 122, C_RIM) && px_at(156, 122, C_RIM), "update: a step done is pale, the ones to come dark");
    CHECK(count_col(104, 30, 40, 50, C_LAMP) && count_col(0, 170, 240, 16, C_AMBER), "update: the mark's lamp is lit, and DO NOT UNPLUG is amber");
    poison(); ui_update_show(5, 0); shot(d, "update_restart");
    CHECK(px_at(156, 122, C_LAMP) && px_at(138, 122, C_HOUSING) && px_at(84, 122, C_HOUSING), "update: the last step");
    poison(); ui_update_show(9, -12); shot(d, "update_failed");
    CHECK(!count_col(0, 0, 240, 240, POISON) && !count_col(0, 0, 240, 240, C_LAMP), "update: failed: nothing is lit");
    CHECK(count_col(6, 116, 228, 62, C_AMBER) > 228 * 40 && count_col(32, 124, 198, 16, C_GRAPHITE) && px_at(20, 127, C_GRAPHITE), "update: failed: an amber box, the sign, the code in graphite");
    return 0;
}

/* the screens of a start, of a crash and of the rescue mode: the base firmware's own statements and fault handler run
 * here, and draw Gamut's screens through its names (ui_hooks.h) */
static int start_run(void)
{
#include "base/boot_screens.h"
    return safe;
}
static void show_wait(void) { memcpy(fb, wait_fb, sizeof wait_fb); }
static int start_screens(const char *d)
{
    op_diag.magic = OPD_MAGIC; op_diag.stage = ST_OK; op_diag.crash_seen = 0; op_diag.safe = 0;
    op_pwr.vdc0 = 49; op_pwr.sys0 = 33; op_pwr.rst = 1; op_pwr.pinr = 0;
    poison(); CHECK(start_run() == 0, "start: a start after a good one is not in safe mode"); shot(d, "boot");
    CHECK(!count_col(0, 0, 240, 240, POISON) && !count_col(0, 0, 240, 240, C_AMBER), "start: the whole screen is drawn, and nothing warns");
    CHECK(count_col(100, 40, 60, 60, C_LAMP) && count_col(100, 52, 42, 42, C_GRILLE), "start: the mark, its lamp lit");
    CHECK(count_col(0, 166, 240, 16, C_HOUSING) && count_col(0, 200, 240, 13, C_LABEL) && count_col(0, 216, 240, 13, C_LABEL), "start: STARTING, then the supplies and the reset's cause, small");
    ft_box(0, 0, 240, "gamut", &GF_NM, C_HOUSING, C_GROUND, 1);
    CHECK(same_px(0, 110, 0, 0, 240, 33), "start: the name is the word gamut, in small letters");
    op_pwr.rst = 3; poison(); start_run();              /* (two causes at once: the line still fits, in the narrower face) */
    /* a start that did not finish: the report for 12 s (the 7th wait is its first), then safe mode */
    op_diag.stage = ST_RUN; op_diag.blocks = 4294967295u; op_diag.load = 999; op_diag.peak = 999; op_diag.nans = 99999; op_diag.c1 = 99999; op_diag.loops = 4294967295u;
    op_pwr.rst = 4; waits = 0; wait_shot = 7;
    poison(); CHECK(start_run() == 1 && op_diag.safe == 1, "start: after a start that did not finish: safe mode"); shot(d, "boot_safe_mode");
    CHECK(!count_col(0, 0, 240, 240, POISON) && count_col(0, 146, 240, 13, C_AMBER) && !count_col(0, 160, 240, 80, C_LABEL), "start: safe mode is said in amber, without the start's figures");
    show_wait(); shot(d, "boot_start_failed");
    CHECK(!count_col(0, 0, 240, 240, POISON) && count_col(0, 0, 240, 30, C_AMBER) > 240 * 20 && px_at(16, 9, C_GRAPHITE) && count_col(30, 4, 204, 22, C_GRAPHITE),
          "start: the report: an amber band, the sign, LAST START FAILED in graphite");
    CHECK(count_col(10, BF_Y0, 94, 2 * BF_DY, C_LABEL) && count_col(104, BF_Y0, 132, 2 * BF_DY, C_HOUSING) && !count_col(0, BF_Y0 + 6 * BF_DY, 240, F_Y - BF_Y0 - 6 * BF_DY, C_HOUSING), "start: not a crash: where it stopped, the reset's cause and four lines of figures");
    CHECK(count_col(0, F_TY, 240, 16, C_AMBER) && !count_col(0, 30, 240, F_Y - 30u, C_AMBER), "start: the footer asks for a photo, in amber");
    CHECK(start_run() == 0 && op_diag.safe == 0, "start: the start after safe mode tries again");
    /* a crash: the handler's screen, then at the next start the report with the crash's figures */
    fm1_crash.magic = FM1_CRASH_MAGIC; fm1_crash.count = 1; fm1_crash.vec = 259; fm1_crash.pc = 0x0200A3F4u; fm1_crash.rets = 0x02008C10u;
    fm1_crash.dbg = 0xDEADBEEFu; fm1_crash.emu = 0x12345678u; fm1_crash.uptime_ms = 4294967295u;
    poison(); fm1_fault(&fm1_crash); shot(d, "crash");
    CHECK(reboots == 1 && !count_col(0, 0, 240, 240, POISON), "crash: the screen, then the restart");
    CHECK(count_col(0, 0, 240, 240, C_AMBER) > 240 * 200 && count_col(0, 0, 240, 240, C_AMBER) + count_col(0, 0, 240, 240, C_GRAPHITE) == 240 * 240 && px_at(14, 11, C_GRAPHITE),
          "crash: graphite on amber and nothing else, with the sign");
    CHECK(count_col(64, 40, 64, 8, C_GRAPHITE) && count_col(8, 136, 176, 8, C_GRAPHITE) && count_col(8, 152, 144, 8, C_GRAPHITE), "crash: the figures, and what to do");
    op_diag.stage = ST_OK; op_diag.blocks = 2210; op_diag.load = 71; op_diag.peak = 96; op_diag.nans = 0; op_diag.c1 = 1; op_diag.loops = 18842;
    waits = 0; wait_shot = 7;
    poison(); CHECK(start_run() == 1, "start: after a crash: safe mode"); show_wait(); shot(d, "boot_start_failed_crash");
    CHECK(!count_col(0, 0, 240, 240, POISON) && count_col(104, BF_Y0 + 9 * BF_DY, 132, 13, C_HOUSING) && BF_Y0 + 9 * BF_DY + 13 <= F_Y, "start: a crash: ten lines, its pc, return address, uptime and DBG among them");
    wait_shot = 0;
    poison(); ui_uboot_show(); shot(d, "uboot");
    CHECK(!count_col(0, 0, 240, 240, POISON) && !count_col(0, 0, 240, 240, C_LAMP) && count_col(104, 50, 40, 50, C_LAMP_OFF), "rescue mode: the whole screen, the mark's lamp unlit");
    return 0;
}

int main(int argc, char **argv)
{
    const char *d = argc > 1 ? argv[1] : ".";
    load_preset(9);
    cur_preset = 9;
    ui_blk = PX_B_AMP;
    full(); shot(d, "play");
    ui_knob(1, 0); ui_render(); shot(d, "play_knob_next_block");
    ui_knob(-1, 0); ui_push(); poison(); ui_render(); status(); shot(d, "edit_amp_model");
    ui_knob(1, 0); ui_knob(1, 0); ui_render(); shot(d, "edit_amp_gain_selected");
    ui_push(); for (int i = 0; i < 8; i++) ui_knob(1, 0); ui_render(); shot(d, "edit_amp_gain_editing");
    ui_push(); ui_home(); poison(); ui_render(); status(); shot(d, "play_edited");
    ui_enter_block(PX_B_DELAY); poison(); ui_render(); status(); shot(d, "edit_delay");
    ui_knob(1, 0); ui_render(); shot(d, "edit_delay_onoff_selected");
    ui_enter_block(PX_B_DELAY); ui_render(); shot(d, "edit_delay_off");
    ui_home(); ui_blk = PX_B_GATE; ui_mode = M_BLOCK; full(); shot(d, "edit_gate_preset_level");
    ui_home(); cur_preset = 13; load_preset(13); ui_blk = PX_B_REVERB; poison(); ui_render(); status(); shot(d, "play_smooth_lead");
    ui_move_start(); ui_knob(-1, 0); ui_render(); shot(d, "play_move");
    ui_move_cancel(); cur_preset = 23; load_preset(23); master_vol = 100; bat_mv = 3640; full(); ui_status("peak 97%", UI_ST_BYPASS); ui_render(); shot(d, "play_acoustic_bypass_vol100_bat12");
    bat_usb_mv = 5000; ui_render(); shot(d, "play_usb");
    bat_usb_mv = 0; bat_mv = 3920; master_vol = 80;
    save_open(); save_draw(); shot(d, "save");
    save_knob(1); save_draw(); shot(d, "save_other_slot");
    save_close(); ui_render(); status();
    tuner_open(); tuner_draw(110.5f); shot(d, "tuner_a_flat");
    {   /* v37: no battery reading: the icon shows an empty cell and "--" (it was hidden) */
        int m = bat_mv; bat_mv = 0; tuner_close(); poison(); ui_render(); status(); shot(d, "play_battery_unknown"); bat_mv = m;
        tuner_open(); tuner_draw(110.5f);
    }
    tuner_draw(110.0f); shot(d, "tuner_a_ok");
    tuner_close(); poison(); ui_render(); status(); shot(d, "play_after_tuner");
    px_midi_cfg_unpack(&mid_cfg, 0);
    midi_open(); midi_draw(); shot(d, "midi_defaults");
    midi_knob(1); midi_knob(1); midi_draw(); shot(d, "midi_channel_2");
    midi_push(); midi_knob(1); mid_usb_up = 1; mid_last[0] = PXM_CC; mid_last[1] = 25; mid_last[2] = 127; midi_draw(); shot(d, "midi_send_off_host_cc");
    midi_push(); midi_knob(1); mid_last[0] = PXM_PC; mid_last[1] = 11; midi_draw(); shot(d, "midi_clock_on_pc");
    mid_c1_off = 2; midi_draw(); shot(d, "midi_core2_off_late"); mid_c1_off = 0; midi_draw();   /* v41: the 2nd core retired */
    /* v42: the fourth row, USB AUDIO: the setting follows the row only when the page is left */
    midi_push(); midi_knob(1); midi_draw(); shot(d, "midi_usb_audio_on");
    if (px_ua_on) { printf("midi: USB AUDIO must not change while the page is open\n"); return 1; }
    /* the fifth row, USB PORT: it acts at once (the usb line says what the host finds) and is never saved */
    midi_push(); midi_knob(1);
    if (!px_usb_foot) { printf("midi: USB PORT must act at once\n"); return 1; }
    {
        static const char *const ST[] = {"midi_port_starting", "midi_port_waiting", "midi_port_no_midi", "midi_port_low_speed",
                                         "midi_port_connected", "midi_port_lost"};
        for (uint8_t st = PXU_OFF; st <= PXU_LOST; st++) { px_uh.st = st; midi_draw(); shot(d, ST[st]); }
    }
    midi_knob(1); px_uh.st = PXU_OFF; midi_draw();
    if (px_usb_foot) { printf("midi: USB PORT back to COMPUTER\n"); return 1; }
    midi_knob(1);                                  /* leave it on FOOTSWITCH: leaving the page must not save it */
    midi_push(); poison(); uc.screen = -1; ui_invalidate(); ui_render(); status();
    if (!px_usb_foot) { printf("midi: leaving the page must keep USB PORT as it was set\n"); return 1; }
    px_usb_foot = 0;
    if (midi_saved != 1 || ui_mode != M_CHAIN) { printf("midi: leaving the page after a change must save once and return to the chain\n"); return 1; }
    if (!px_ua_on) { printf("midi: leaving the page must set USB AUDIO as the row showed\n"); return 1; }
    midi_open(); midi_close();
    if (midi_saved != 1) { printf("midi: leaving without a change must not save\n"); return 1; }
    midi_open(); midi_push(); midi_push(); midi_push(); midi_push(); midi_knob(1); midi_close(); px_usb_foot = 0;
    if (midi_saved != 1) { printf("midi: USB PORT alone must not save\n"); return 1; }
    midi_open(); midi_push(); midi_push(); midi_push(); midi_knob(-1); midi_close();
    if (midi_saved != 2 || px_ua_on) { printf("midi: USB AUDIO off again must save once more\n"); return 1; }
    mid_cfg.chan = 16; midi_open(); midi_knob(1); midi_draw(); shot(d, "midi_channel_wraps_to_omni");
    if (mid_cfg.chan != 0) { printf("midi: channel 16 + 1 must wrap to omni\n"); return 1; }
    midi_knob(-1); if (mid_cfg.chan != 16) { printf("midi: omni - 1 must wrap to 16\n"); return 1; }
    if (quick_wins(d) || overhaul(d) || update_screen(d) || start_screens(d)) return 1;
    if (reds) { printf("%d pages show red\n", reds); return 1; }
    if (gaps) { printf("%d pages have pixels never drawn\n", gaps); return 1; }
    if (cut) { printf("%d texts cut or without a glyph\n", cut); return 1; }
    return 0;
}
