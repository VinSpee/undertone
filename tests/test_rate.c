/* SPDX-License-Identifier: GPL-3.0-only
 * OpenPocket — host test of the I2S clock's two test builds (firmware/base/rate.h, docs/RATE48-TEST.md), through
 * firmware/base/audio.h as Gamut includes it. The clock's registers are a table here, and the I2S driver's rate entry
 * point does to it what sdk/iis.bc's iis_set_sample_rate does to ALNK0 (read in its disassembly): 44.1 kHz clears bits 8
 * and 9 of 0x10014; 48 kHz ORs bit 25 into 0x119A4 and sets bit 8; both write the same divider byte.
 * Built twice (tests/run_tests.sh): -DOP_RATE_DIAG=1, the report at 44.1 kHz, which must write no clock register; and
 * -DOP_RATE48=1, whose 48 kHz must be the driver's own 48 kHz registers without a write to PLL0, and 44.1 kHz when bit 25
 * is clear or the start is a safe-mode one. Both time the guitar's blocks across TIMER4's wrap and print the DIAG line
 * that tools/log.mjs reads (to build/rate_diag.txt or build/rate48.txt, or the file the first argument names), which
 * tests/test_log.mjs parses.
 *   cc -O1 -Wall -Wno-unused-function -Wno-unused-variable -Wno-int-to-pointer-cast -Ifirmware -DOP_RATE48=1 tests/test_rate.c \
 *      -o build/test_rate48 && build/test_rate48
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* ---- the chip, stood in for ---- */
#define FM1_TICKS_PER_US 24u
static uint32_t now;
static uint32_t fm1_ticks(void) { return now; }
static void fm1_delay_ms(uint32_t ms) { (void)ms; }
static void fm1_irq_attach(int irq, void (*isr)(void), int prio) { (void)irq; (void)isr; (void)prio; }
static void fm1_irq_enable_all(void) { }
#define FM1_IRQ_ALNK0 0
static void fm1_irq_mask(int irq) { (void)irq; }
static void fm1_irq_unmask(int irq) { (void)irq; }
static void fm1_wdt_feed(void) { }
void isr_alnk0(void) { }
enum { ST_I2S };
static void op_stage(uint32_t s, const char *txt) { (void)s; (void)txt; }
static struct { uint32_t safe; } op_diag;                  /* (base/diag.h) */
static void hex8(char *b, uint32_t v) { static const char H[] = "0123456789ABCDEF"; for (int i = 0; i < 8; i++) b[i] = H[(v >> (28 - 4 * i)) & 15u]; b[8] = 0; }
static void b_num(char *d, uint32_t v) { char t[12]; int n = 0; while (*d) d++; do { t[n++] = (char)('0' + v % 10u); v /= 10u; } while (v); while (n) *d++ = t[--n]; *d = 0; }
static void b_str(char *d, const char *s) { while (*d) d++; while (*s) *d++ = *s++; *d = 0; }

/* the clock's registers: a table; t_wr counts rate.h's own writes (the driver's are its model's, below) */
enum { R_PLL0_0, R_PLL0_1, R_PLL1_0, R_PLL1_1, R_HSB, R_MUX, R_SYS, R_DIV, R_N };
static const uint32_t R_ADDR[R_N] = {0x119A0u, 0x119A4u, 0x119A8u, 0x119ACu, 0x10008u, 0x1000Cu, 0x10014u, 0x12E0Cu};
static uint32_t reg[R_N], t_wr[R_N], t_bad;
static int r_at(uint32_t a) { for (int i = 0; i < R_N; i++) if (R_ADDR[i] == a) return i; t_bad++; return 0; }
static uint32_t r_rd(uint32_t a) { return reg[r_at(a)]; }
static void r_wr(uint32_t a, uint32_t v) { const int i = r_at(a); reg[i] = v; t_wr[i]++; }
#define AR_RD(a) r_rd(a)
#define AR_RD8(a) (r_rd(a) & 0xFFu)
#define AR_WR(a, v) r_wr(a, v)

#define printf jl_printf
#define malloc jl_malloc
#define free jl_free
#include "base/audio.h"
#undef printf
static uint32_t t_rates[4], t_nrates;                     /* the rates asked of the driver */
static void drv_rate(uint32_t *r, int sr)                  /* sdk/iis.bc iis_set_sample_rate, ALNK0 (index 0) */
{
    if (sr == 48000) { r[R_PLL0_1] |= 1u << 25; r[R_SYS] |= 1u << 8; }
    else r[R_SYS] &= ~(1u << 8);
    r[R_DIV] &= 0xFFu & ~0x1Cu; r[R_DIV] = (r[R_DIV] & 0x1Fu) | 0x80u;
    r[R_SYS] &= ~(1u << 9);
}
int  iis_open(struct iis_platform_data *pd, uint8_t index) { (void)pd; (void)index; return 0; }
int  iis_set_sample_rate(int sample_rate, uint8_t index) { (void)index; if (t_nrates < 4u) t_rates[t_nrates++] = (uint32_t)sample_rate; drv_rate(reg, sample_rate); return 0; }
void iis_channel_on(uint8_t channel, uint8_t index) { (void)channel; (void)index; }
void iis_set_enc_data_handler(void *priv, void (*cb)(void *, uint8_t *, int, uint8_t), uint8_t index) { (void)priv; (void)cb; (void)index; }
void iis_set_dec_data_handler(void *priv, void (*cb)(void *, uint8_t *, int, uint8_t), uint8_t index) { (void)priv; (void)cb; (void)index; }
void iis_irq_handler(uint8_t index) { (void)index; }
static void a_block(const uint8_t *data, int len) { (void)data; (void)len; }
static void a_send(int32_t *d, uint32_t n) { (void)d; (void)n; }
static void a_collect(void) { }

static int fails;
#define CHECK(c, what) do { if (!(c)) { fprintf(stdout, "FAIL %s\n", what); fails++; } } while (0)
static FILE *lines;

/* a start: the registers as M-VAVE's boot loader leaves an FM-1 (fm1_clock.h), with bit 25 as given; bits 8 and 9 of
 * 0x10014 set, so that what clears them shows */
static void boot(int bit25, int safe)
{
    memset(&a_rt, 0, sizeof a_rt);
#if OP_RATE48
    a_sr = 44100u;
#endif
    const uint32_t r0[R_N] = {0x45400203u, bit25 ? 0x3F503026u : 0x3D503026u, 0x0940022Bu, 0x0750310Cu, 0x00010200u, 0x1C1u, 0x306u, 0x00u};
    memcpy(reg, r0, sizeof reg);
    memset(t_wr, 0, sizeof t_wr);
    t_nrates = 0;
    op_diag.safe = (uint32_t)safe;
    a_rate_pick();                                         /* (Gamut's audio_start, before the engine takes A_SR) */
    a_rate_set();                                          /* (base/audio.h audio_io_start) */
}

/* `secs` seconds of guitar blocks at `hz`, through the I2S's input callback, TIMER4 starting near its wrap */
static void play(double hz, double secs)
{
    static uint8_t blk[A_FR * 8u];
    double t = 4294967296.0 - 3.0 * 24e6;                  /* 3 s before the wrap */
    for (double s = 0; s < secs * hz; s += A_FR, t += A_FR * 24e6 / hz) {
        now = (uint32_t)(uint64_t)t;
        a_enc(0, blk, (int)sizeof blk, 1);
        a_dec(0, blk, (int)sizeof blk, 0);
    }
}

/* the DIAG line's rate and fields, read back as tools/log.mjs reads them */
static double line_hz(const char *l, unsigned *w)
{
    unsigned f = 0, t = 0;
    const char *p = strstr(l, " W ");
    if (!p || sscanf(p, " W %u F %u T %u", w, &f, &t) != 3 || !t) return 0.0;
    return (double)f * 24e6 / (double)t;
}

static void report(const char *what, double hz)
{
    char l[224];
    unsigned w = 0;
    a_rate_text(l);
    CHECK(strlen(l) < sizeof l - 1u, "the DIAG line fits ED_DIAG_LEN");
    const double got = line_hz(l, &w);
    char m[160];
    snprintf(m, sizeof m, "%s: the rate measured, %.3f Hz, is the blocks' %.3f Hz within 0.01 Hz", what, got, hz);
    CHECK(w >= 2u && got > hz - 0.01 && got < hz + 0.01, m);
    if (lines) fprintf(lines, "%s\n", l);
    fprintf(stdout, "%s\n  %s\n", what, l);
}

int main(int argc, char **argv)
{
    uint32_t after48[R_N], r[R_N];
    lines = fopen(argc > 1 ? argv[1] : OP_RATE48 ? "build/rate48.txt" : "build/rate_diag.txt", "w");
    {   /* what the driver's own 48 kHz case leaves, from the same start */
        const uint32_t r0[R_N] = {0x45400203u, 0x3F503026u, 0x0940022Bu, 0x0750310Cu, 0x00010200u, 0x1C1u, 0x306u, 0x00u};
        memcpy(after48, r0, sizeof r0);
        drv_rate(after48, 48000);
    }
#if !OP_RATE48
    boot(1, 0);
    CHECK(A_SR == 44100u && A_BUDGET == 69648u, "diagnostic build: 44.1 kHz, the budget as the release's");
    CHECK(t_nrates == 1u && t_rates[0] == 44100u, "diagnostic build: the driver is asked for 44.1 kHz, once");
    for (int i = 0; i < R_N; i++) CHECK(!t_wr[i], "diagnostic build: no clock register written");
    CHECK(reg[R_PLL0_1] == 0x3F503026u && !(reg[R_SYS] & (1u << 8)), "diagnostic build: PLL0 as found, the 44.1 kHz family");
    CHECK(a_rt.pll0 == 0x3F503026u && a_rt.sys == 0x306u && a_rt.div == 0u, "diagnostic build: the registers as found before the rate");
    play(6000000.0 / 136.0, 25.0);                        /* the 44.1 kHz family's clock: 6 MHz / 136 */
    report("diagnostic build, 44.1 kHz family", 6000000.0 / 136.0);
    {
        char l[224];
        a_rate_text(l);
        CHECK(!strncmp(l, "RATE ASK 44100 SR 44100 GUARD NONE W 2 F 441216 T 240021504 PLL0 45400203 3F503026 PLL1 0940022B "
                          "0750310C HSB 00010200 MUX 000001C1 SYS 00000006 DIV 00000080 BEFORE 3F503026 00000306 00000000", 224),
              "diagnostic build: the DIAG line, field by field (tools/log.mjs parseRate)");
    }
    boot(0, 0);
    CHECK(t_nrates == 1u && t_rates[0] == 44100u && !t_wr[R_PLL0_1] && !t_wr[R_SYS], "diagnostic build, bit 25 clear: the same, nothing written");
#else
    boot(1, 0);
    CHECK(a_rt.guard == AR_GUARD_PASS && A_SR == 48000u, "48 kHz build, bit 25 set: 48 kHz");
    CHECK(A_BUDGET == 128000000u / 48000u * 24u, "48 kHz build: the block's budget at 48 kHz");
    CHECK(t_nrates == 1u && t_rates[0] == 44100u, "48 kHz build: the driver is asked for its 44.1 kHz case only");
    CHECK(!t_wr[R_PLL0_0] && !t_wr[R_PLL0_1] && !t_wr[R_PLL1_0] && !t_wr[R_PLL1_1], "48 kHz build: no PLL register written");
    CHECK(t_wr[R_SYS] == 1u && !t_wr[R_DIV] && !t_wr[R_HSB] && !t_wr[R_MUX], "48 kHz build: one write of its own, to 0x10014");
    CHECK(!memcmp(reg, after48, sizeof reg), "48 kHz build: the registers the driver's own 48 kHz case leaves");
    play(48000.0, 25.0);
    report("48 kHz build, 48 kHz family", 48000.0);
    play(47000.0, 25.0);                                   /* (another clock: what the measurement is for) */
    report("48 kHz build, a clock at 47 kHz", 47000.0);

    boot(0, 0);
    CHECK(a_rt.guard == AR_GUARD_BIT25 && A_SR == 44100u && A_BUDGET == 69648u, "48 kHz build, bit 25 clear: 44.1 kHz");
    for (int i = 0; i < R_N; i++) CHECK(!t_wr[i], "48 kHz build, bit 25 clear: no clock register written");
    CHECK(t_nrates == 1u && t_rates[0] == 44100u && !(reg[R_SYS] & (1u << 8)), "48 kHz build, bit 25 clear: the driver's 44.1 kHz case");
    play(6000000.0 / 136.0, 25.0);
    report("48 kHz build, refused (bit 25 clear)", 6000000.0 / 136.0);

    boot(1, 1);
    CHECK(a_rt.guard == AR_GUARD_SAFE && A_SR == 44100u, "48 kHz build, a safe-mode start: 44.1 kHz");
    for (int i = 0; i < R_N; i++) CHECK(!t_wr[i], "48 kHz build, a safe-mode start: no clock register written");
    memcpy(r, reg, sizeof r);
    a_rate_pick(); a_rate_set();                           /* (picked once: a second call changes nothing) */
    CHECK(A_SR == 44100u && !memcmp(r, reg, sizeof r) && t_nrates == 2u, "48 kHz build: the rate is picked once");
    play(6000000.0 / 136.0, 25.0);
    report("48 kHz build, refused (safe mode)", 6000000.0 / 136.0);
#endif
    CHECK(!t_bad, "no register outside the clock's read or written");
    if (lines) fclose(lines);
    fprintf(stdout, "%s: %s\n", OP_RATE48 ? "48 kHz build" : "diagnostic build", fails ? "FAILED" : "ok");
    return fails ? 1 : 0;
}
