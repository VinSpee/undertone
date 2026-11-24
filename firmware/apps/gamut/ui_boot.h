/* SPDX-License-Identifier: GPL-3.0-only
 * Gamut — the screens of a start, of a crash and of the USB rescue mode, in Gamut's design: the mark, small letters, and
 * a fault in amber with its sign, never in red. The base firmware draws them through ui_hooks.h's names: a start and the
 * report of one that failed (base/boot_screens.h), a crash (base/diag.h), the rescue mode (px_usb.h). After ui.h.
 */
#pragma once

/* a start: the mark with its lamp, the name in small letters, the version, then the supplies as found and why the chip
 * last reset, small, for a photo. safe: the start after one that failed, which keeps the effects off */
static void ui_boot_show(int safe)
{
    char l[80], h[9];
    lcd_rect(0, 0, 240, 240, C_GROUND);
    ui_grille(100, 52, 6, 12, 9, 1, C_GRILLE, C_GROUND);
    ui_box(0, 110, 240, OP_NAME, &GF_NM, C_HOUSING, C_GROUND, 1 | UI_LC);
    l[0] = 0; b_str(l, OP_VERSION);
    if (safe) b_str(l, " safe mode");
#if OP_BLE_TEST
    else b_str(l, " ble test");
#endif
    ui_box(0, 146, 240, l, &GF_MS, safe ? C_AMBER : C_LABEL, C_GROUND, 1 | UI_LC);
    if (safe) return;
    ft_box(0, 166, 240, "starting", &GF_LB, C_HOUSING, C_GROUND, 1);
    l[0] = 0; b_str(l, "pwr "); b_num(l, op_pwr.vdc0); b_str(l, " "); b_num(l, op_pwr.sys0); b_str(l, " (boot levels)");
    ft_box(0, 200, 240, l, &GF_MS, C_LABEL, C_GROUND, 1);
    l[0] = 0; b_str(l, "rst "); rst_names(l, op_pwr.rst); ui_lower(l); b_str(l, " pinr "); hex8(h, op_pwr.pinr); b_str(l, h + 6);
    ft_box(0, 216, 240, l, ft_width(&GF_MS, l) <= 240u ? &GF_MS : &GF_LB, C_LABEL, C_GROUND, 1);   /* (several causes at once: the narrower face) */
}
/* a line of the report: its label in grey, its value in housing, the values in one column unless one is too long for it */
#define BF_Y0 78u                      /* the report's 1st line of figures; ten lines at most, BF_DY apart, end above the footer */
#define BF_DY 14u
static void ui_fail_row(uint32_t i, const char *label, const char *v)
{
    uint32_t y = BF_Y0 + i * BF_DY, vx = ft_width(&GF_MS, v) <= 132u ? 104u : 18u + ft_width(&GF_MS, label);
    ft_box(10, y, vx - 10u, label, &GF_MS, C_LABEL, C_GROUND, 0);
    ft_box(vx, y, 236u - vx, v, &GF_MS, C_HOUSING, C_GROUND, 0);
}
/* the report of a start that did not finish (st: where it stopped) or that crashed: what happened and what to do first,
 * then the figures a bug report needs, shown for 12 s */
static void ui_boot_failed(uint32_t st, int crashed)
{
    char l[80], h[9];
    uint32_t i = 0;
    lcd_rect(0, 0, 240, 240, C_GROUND);
    lcd_rect(0, 0, 240, 30, C_AMBER);
    ui_warn(10, 9, C_GRAPHITE, C_AMBER);
    ft_box(30, 4, 204, "last start failed", &GF_TX, C_GRAPHITE, C_AMBER, 0);
    ft_box(10, 35, 224, "the effects are off for this start", &GF_LB, C_HOUSING, C_GROUND, 0);
    ft_box(10, 52, 224, "switch off and on to try again", &GF_LB, C_HOUSING, C_GROUND, 0);
    lcd_rect(10, 72, 220, 1, C_RIM);
    l[0] = 0; b_str(l, ST_NAME[st]); ui_lower(l); ui_fail_row(i++, "stopped at", l);
    if (!crashed) { l[0] = 0; rst_names(l, op_pwr.rst); ui_lower(l); ui_fail_row(i++, "reset by", l); }
    else {
        hex8(h, fm1_crash.pc); ui_fail_row(i++, "crash pc", h);
        l[0] = 0; hex8(h, fm1_crash.rets); b_str(l, h); b_str(l, "  "); b_num(l, fm1_crash.vec); ui_fail_row(i++, "rets  vec", l);
#ifdef OP_RAM_CODE
        hex8(h, (uint32_t)(uintptr_t)OP_RAM_CODE); ui_fail_row(i++, "dsp code", h);
#endif
        l[0] = 0; b_num(l, fm1_crash.uptime_ms); b_str(l, " ms"); ui_fail_row(i++, "uptime", l);
        hex8(h, fm1_crash.dbg); ui_fail_row(i++, "dbg", h);
    }
    l[0] = 0; b_num(l, op_diag.blocks); ui_fail_row(i++, "blocks", l);
    l[0] = 0; b_num(l, op_diag.load); b_str(l, "%  "); b_num(l, op_diag.peak); b_str(l, "%"); ui_fail_row(i++, "load  peak", l);
    l[0] = 0; b_num(l, op_diag.nans); b_str(l, "  "); b_num(l, op_diag.c1); ui_fail_row(i++, "nan  cpu1", l);
    l[0] = 0; b_num(l, op_diag.loops); ui_fail_row(i++, "loops", l);
    lcd_rect(0, F_Y, 240, 240u - F_Y, C_PLATE);
    ft_box(0, F_TY, 240, "photograph this for a bug report", &GF_LB, C_AMBER, C_PLATE, 1);
}
/* a crash, from the fault handler: the 8 x 8 face and plain rectangles only, graphite on amber, then the pedal restarts */
static void ui_fault_show(const fm1_crash_t *c)
{
    static const char *const NAME[5] = {"vec", "pc", "rets", "dbg", "emu"};
    const uint32_t v[5] = {c->vec, c->pc, c->rets, c->dbg, c->emu};
    char h[9];
    lcd_rect(0, 0, 240, 240, C_AMBER);
    ui_warn(8, 11, C_GRAPHITE, C_AMBER);
    lcd_text(28, 8, "crash", C_GRAPHITE, C_AMBER, 2);
    for (uint32_t i = 0; i < 5u; i++) {
        hex8(h, v[i]);
        lcd_text(8, 40u + i * 16u, NAME[i], C_GRAPHITE, C_AMBER, 1); lcd_text(64, 40u + i * 16u, h, C_GRAPHITE, C_AMBER, 1);
    }
    lcd_text(8, 136, "photograph this screen", C_GRAPHITE, C_AMBER, 1);
    lcd_text(8, 152, "the pedal restarts", C_GRAPHITE, C_AMBER, 1);
}
/* the chip's USB rescue mode (the installer's soft key): the mark, its lamp unlit, since no sound passes */
static void ui_uboot_show(void)
{
    lcd_rect(0, 0, 240, 240, C_GROUND);
    ui_grille(104, 60, 4, 9, 7, 0, C_GRILLE, C_GROUND);
    ft_box(0, 104, 240, "uboot", &GF_TX, C_HOUSING, C_GROUND, 1);
    ft_box(0, 132, 240, "rescue mode over usb", &GF_LB, C_LABEL, C_GROUND, 1);
}
