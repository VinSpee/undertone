/* SPDX-License-Identifier: GPL-3.0-only
 * The base firmware (docs/BASE-FIRMWARE.md): the I2S clock's two test builds, which decide whether the sound can run at
 * 48 kHz (docs/RATE48-TEST.md). Gamut's test channels only (firmware/build.sh): no release has either.
 *   OP_RATE_DIAG 1  (channel rate-diag) 44.1 kHz as ever. It reads the clock's registers before the I2S's rate is set and
 *                   at each DIAG, times the guitar's blocks against TIMER4, and writes no clock register
 *   OP_RATE48 1     (channel rate48) the same report, at 48 kHz when the guard lets it: else 44.1 kHz, and says why
 * The JieLi driver's 48 kHz case (sdk/iis.bc iis_set_sample_rate, ALNK0) differs from its 44.1 kHz case in two writes:
 * it ORs bit 25 into PLL0's CON1 (0x119A4), the PLL that probably clocks USB too, and it sets bit 8 of 0x10014 where the
 * 44.1 kHz case clears it. Both cases write the same divider byte and clear bit 9. So 48 kHz here is the driver's
 * 44.1 kHz case, then bit 8 set: PLL0 is never written. The guard: bit 25 already set (the 48 kHz family's source is
 * on), and not a safe-mode start (one after a failed start is always 44.1 kHz). The DIAG line, read by
 * `node tools/op.mjs log` (tools/log.mjs parseRate):
 *   RATE ASK 48000 SR 48000 GUARD PASS W 3 F 480012 T 240000000 PLL0 <CON0> <CON1> PLL1 <CON0> <CON1> HSB <0x10008>
 *        MUX <0x1000C> SYS <0x10014> DIV <the ALNK0 divider byte> BEFORE <CON1> <SYS> <DIV>
 * ASK the rate this build asks for, SR the rate it runs at, GUARD NONE (the diagnostic build) PASS BIT25 SAFE; W the
 * timing windows finished, F the guitar's frames in the last one and T its TIMER4 ticks (24 MHz): the rate is
 * F x 24,000,000 / T. The registers in hex now, and BEFORE as found before the rate was set.
 * Included by base/audio.h (it provides a_sr, A_SR, fm1_ticks, iis_set_sample_rate); the app calls a_rate_pick before
 * its engine takes A_SR. tests/test_rate.c runs it on a PC (AR_RD, AR_RD8 and AR_WR stood in for).
 */
#pragma once

#define AR_PLL0_CON0  0x119A0u
#define AR_PLL0_CON1  0x119A4u                 /* bit 25: the 48 kHz family's source on */
#define AR_PLL1_CON0  0x119A8u
#define AR_PLL1_CON1  0x119ACu
#define AR_HSB        0x10008u
#define AR_MUX        0x1000Cu
#define AR_SYS        0x10014u                 /* bit 8: the I2S's clock from the 48 kHz family */
#define AR_ALNK0_DIV  0x12E0Cu                 /* the driver's divider byte (iis_reg field 6): [7:5] 4, [4:2] 0 at both rates */
#define AR_PLL0_48K   (1u << 25)
#define AR_SYS_48K    (1u << 8)
#ifndef AR_RD                                  /* (a PC test has its own) */
#define AR_RD(a)      (*(volatile uint32_t *)(uintptr_t)(a))
#define AR_RD8(a)     (*(volatile uint8_t *)(uintptr_t)(a))
#define AR_WR(a, v)   (*(volatile uint32_t *)(uintptr_t)(a) = (v))
#endif
#define AR_WINDOW     (10u * 1000000u * FM1_TICKS_PER_US)   /* a timing window: 10 s of TIMER4 */

enum { AR_GUARD_NONE, AR_GUARD_PASS, AR_GUARD_BIT25, AR_GUARD_SAFE };
static const char *const AR_GUARD_NAME[] = {"NONE", "PASS", "BIT25", "SAFE"};
static struct {
    uint8_t picked, on, guard;
    uint32_t pll0, sys, div;                   /* before the rate was set */
    uint32_t t0, f;                            /* the window running: its start (a block's tick), the frames since */
    volatile uint32_t w, wf, wt;               /* the windows finished, the last one's frames and ticks */
} a_rt;

/* the rate, before the app's engine takes it (and again at the I2S's start: once only) */
static void a_rate_pick(void)
{
    if (a_rt.picked) return;
    a_rt.picked = 1;
    a_rt.pll0 = AR_RD(AR_PLL0_CON1);
    a_rt.sys = AR_RD(AR_SYS);
    a_rt.div = AR_RD8(AR_ALNK0_DIV);
#if OP_RATE48
    a_rt.guard = op_diag.safe ? AR_GUARD_SAFE : !(a_rt.pll0 & AR_PLL0_48K) ? AR_GUARD_BIT25 : AR_GUARD_PASS;
    a_sr = a_rt.guard == AR_GUARD_PASS ? 48000u : 44100u;
#else
    a_rt.guard = AR_GUARD_NONE;
#endif
}

/* in place of iis_set_sample_rate (base/audio.h audio_io_start): never a write to PLL0 */
static void a_rate_set(void)
{
    a_rate_pick();
    iis_set_sample_rate(44100, 0);
#if OP_RATE48
    if (a_rt.guard == AR_GUARD_PASS) AR_WR(AR_SYS, AR_RD(AR_SYS) | AR_SYS_48K);   /* the 48 kHz family */
#endif
}

/* a guitar block of n frames came (a_enc, in the interrupt; inline: it runs from RAM) */
static inline __attribute__((always_inline)) void a_rate_block(uint32_t n)
{
    const uint32_t t = fm1_ticks();
    if (!a_rt.on) { a_rt.on = 1; a_rt.t0 = t; a_rt.f = 0; return; }   /* the first block starts the first window */
    a_rt.f += n;
    if (t - a_rt.t0 >= AR_WINDOW) { a_rt.wf = a_rt.f; a_rt.wt = t - a_rt.t0; a_rt.w++; a_rt.t0 = t; a_rt.f = 0; }
}

/* the DIAG line (out: 224 bytes) */
static void a_rate_text(char *out)
{
    char h[9];
    uint32_t w, f, t;
    do { w = a_rt.w; f = a_rt.wf; t = a_rt.wt; } while (w != a_rt.w);   /* (the interrupt may finish a window meanwhile) */
#define AR_HEX(v) do { hex8(h, v); b_str(out, " "); b_str(out, h); } while (0)
    out[0] = 0;
    b_str(out, "RATE ASK "); b_num(out, OP_RATE48 ? 48000u : 44100u);
    b_str(out, " SR "); b_num(out, A_SR);
    b_str(out, " GUARD "); b_str(out, AR_GUARD_NAME[a_rt.guard]);
    b_str(out, " W "); b_num(out, w);
    b_str(out, " F "); b_num(out, f);
    b_str(out, " T "); b_num(out, t);
    b_str(out, " PLL0"); AR_HEX(AR_RD(AR_PLL0_CON0)); AR_HEX(AR_RD(AR_PLL0_CON1));
    b_str(out, " PLL1"); AR_HEX(AR_RD(AR_PLL1_CON0)); AR_HEX(AR_RD(AR_PLL1_CON1));
    b_str(out, " HSB"); AR_HEX(AR_RD(AR_HSB));
    b_str(out, " MUX"); AR_HEX(AR_RD(AR_MUX));
    b_str(out, " SYS"); AR_HEX(AR_RD(AR_SYS));
    b_str(out, " DIV"); AR_HEX(AR_RD8(AR_ALNK0_DIV));
    b_str(out, " BEFORE"); AR_HEX(a_rt.pll0); AR_HEX(a_rt.sys); AR_HEX(a_rt.div);
#undef AR_HEX
}
