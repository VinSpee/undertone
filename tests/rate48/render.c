/* SPDX-License-Identifier: GPL-3.0-only
 * OpenPocket — the engine at one rate, for tests/rate48/score.sh (the 48 kHz port, docs/RATE48-TEST.md): built once for
 * 44.1 kHz (-DPX_FS=44100, px_dsp.h) and once for 48 kHz, the release's, each run at its own rate.
 *   render bands RATE DI.wav   every block type but AMP and CAB alone, all five settings at 0, 50 and 100, through the
 *                              DI (a 16-bit mono WAV at 44.1 kHz, cut at 20 kHz and resampled to RATE): its level and
 *                              its third-octave bands from 99 Hz to 10 kHz, in dB, one line a case
 *   render delay RATE          the first echo of an impulse through DIGITAL at TIME 100 (2000 ms), in ms
 *   render plate RATE          the PLATE reverb's size: its shortest line against Dattorro's (1 = his lengths)
 * The engine is built as the pedal builds it (-fno-builtin -ffp-contract=off, firmware/px_math.c as the libm).
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "px_dsp.c"

static px_engine e;

/* ---- the DI, at the render's rate: a windowed-sinc resampler (128 taps, cut at 20 kHz, Kaiser beta 9), the same filter
 * at 44.1 kHz (what lies above 20 kHz would reach the bands through a block's distortion at one rate only) ---- */
static float *read_di(const char *fn, int *n)
{
    FILE *f = fopen(fn, "rb");
    if (!f) { perror(fn); exit(2); }
    fseek(f, 0, SEEK_END);
    long sz = ftell(f) - 44;
    fseek(f, 44, SEEK_SET);
    *n = (int)(sz / 2);
    short *s = malloc((size_t)sz);
    if (fread(s, 2, (size_t)*n, f) != (size_t)*n) { fprintf(stderr, "%s: short read\n", fn); exit(2); }
    fclose(f);
    float *x = malloc(sizeof(float) * (size_t)*n);
    for (int i = 0; i < *n; i++) x[i] = s[i] / 32768.0f;
    free(s);
    return x;
}
static double bessel0(double x)
{
    double s = 1.0, t = 1.0;
    for (int k = 1; k < 40; k++) { t *= (x / (2.0 * k)) * (x / (2.0 * k)); s += t; }
    return s;
}
static float *resample(const float *x, int n, double from, double to, int *m)
{
    enum { H = 64, R = 256 };                          /* taps each side; the kernel's table: R points a sample */
    static double K[H * R + 2];
    const double fc = 20000.0 / from, beta = 9.0;
    for (int i = 0; i <= H * R + 1; i++) {
        const double u = (double)i / R, r = u / H;
        const double sinc = u == 0.0 ? 2.0 * fc : sin(2.0 * M_PI * fc * u) / (M_PI * u);
        K[i] = r >= 1.0 ? 0.0 : sinc * bessel0(beta * sqrt(1.0 - r * r)) / bessel0(beta);
    }
    *m = (int)floor(n * to / from);
    float *y = malloc(sizeof(float) * (size_t)*m);
    for (int j = 0; j < *m; j++) {
        const double t = j * from / to;
        const int k0 = (int)floor(t);
        double acc = 0.0;
        for (int k = k0 - H + 1; k <= k0 + H; k++) {
            if (k < 0 || k >= n) continue;
            const double a = fabs(t - k) * R;
            const int i = (int)a;
            acc += x[k] * (K[i] + (K[i + 1] - K[i]) * (a - i));
        }
        y[j] = (float)acc;
    }
    return y;
}

/* ---- third-octave bands of a whole render (one FFT, 0.1 s cosine tapers at both ends) ---- */
#define NB 21
static void fft(double *re, double *im, int n)
{
    for (int i = 1, j = 0; i < n; i++) {
        int b = n >> 1;
        for (; j & b; b >>= 1) j ^= b;
        j ^= b;
        if (i < j) { double t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
    }
    for (int len = 2; len <= n; len <<= 1) {
        const double a = -2.0 * M_PI / len;
        for (int i = 0; i < n; i += len)
            for (int k = 0; k < len / 2; k++) {
                const double c = cos(a * k), s = sin(a * k);
                double *ur = &re[i + k], *ui = &im[i + k], *vr = &re[i + k + len / 2], *vi = &im[i + k + len / 2];
                const double tr = *vr * c - *vi * s, ti = *vr * s + *vi * c;
                *vr = *ur - tr; *vi = *ui - ti; *ur += tr; *ui += ti;
            }
    }
}
static void bands(const float *y, int n, double sr, double *level, double *b)
{
    int N = 1;
    while (N < n) N <<= 1;
    static double *re, *im;
    static int cap;
    if (cap < N) { re = realloc(re, sizeof(double) * (size_t)N); im = realloc(im, sizeof(double) * (size_t)N); cap = N; }
    const int tap = (int)(0.1 * sr);
    double w2 = 0.0, ms = 0.0;
    for (int i = 0; i < N; i++) {
        double w = 0.0;
        if (i < n) w = i < tap ? 0.5 - 0.5 * cos(M_PI * i / tap) : i >= n - tap ? 0.5 - 0.5 * cos(M_PI * (n - 1 - i) / tap) : 1.0;
        re[i] = i < n ? w * y[i] : 0.0; im[i] = 0.0;
        w2 += w * w; ms += re[i] * re[i];
    }
    *level = 10.0 * log10(ms / w2 + 1e-30);
    fft(re, im, N);
    for (int j = 0; j < NB; j++) {
        const double c = 1000.0 * pow(2.0, (j - 10) / 3.0), lo = c / pow(2.0, 1.0 / 6.0), hi = c * pow(2.0, 1.0 / 6.0);
        double p = 0.0;
        for (int k = (int)ceil(lo * N / sr); k * sr / N < hi; k++) p += re[k] * re[k] + im[k] * im[k];
        b[j] = 10.0 * log10(2.0 * p / ((double)N * w2) + 1e-30);
    }
}

static void run(const px_preset_t *q, double sr, const float *x, float *y, int n)
{
    px_engine_init(&e, (float)sr);
    px_engine_set(&e, q);
    for (int i = 0; i < n; i += PX_MAX_BLOCK) px_engine_process(&e, x + i, y + i, n - i < PX_MAX_BLOCK ? n - i : PX_MAX_BLOCK);
}
static void alone(px_preset_t *q, int blk, int type, int v)
{
    px_preset_factory(q, 0);
    for (int j = 0; j < PX_NBLK; j++) q->on[j] = j == blk;
    q->p[PX_B_GATE][PX_PATCH_LEVEL] = 50;          /* 0 dB, whatever the factory preset's: the output limiter stays out of it */
    q->type[blk] = (uint8_t)type;
    for (int k = 0; k < PX_NPAR; k++) q->p[blk][k] = (uint8_t)v;
}

int main(int argc, char **argv)
{
    if (argc < 3) { fprintf(stderr, "usage: render bands|delay|plate RATE [DI.wav]\n"); return 2; }
    const double sr = atof(argv[2]);
    px_preset_t q;
    if (!strcmp(argv[1], "bands") && argc > 3) {
        int n44, n;
        float *di = read_di(argv[3], &n44), *x = resample(di, n44, 44100.0, sr, &n), *y = malloc(sizeof(float) * (size_t)n);
        static const int V[3] = {0, 50, 100};
        for (int b = 0; b < PX_NBLK; b++) for (int t = 0; t < px_ntypes(b); t++) for (int s = 0; s < 3; s++) {
            if (b == PX_B_AMP || b == PX_B_CAB) continue;
            alone(&q, b, t, V[s]);
            run(&q, sr, x, y, n);
            int nan = 0;
            for (int i = 0; i < n; i++) nan += y[i] != y[i];
            double lv, bd[NB];
            bands(y, n, sr, &lv, bd);
            printf("%s|%s|%d|%d|%.3f", px_block_label(b), px_type_name(b, t), V[s], nan, lv);
            for (int j = 0; j < NB; j++) printf("|%.3f", bd[j]);
            printf("\n");
        }
        return 0;
    }
    if (!strcmp(argv[1], "delay")) {
        const int n = (int)(2.2 * sr);
        float *x = calloc((size_t)n, sizeof(float)), *y = malloc(sizeof(float) * (size_t)n);
        x[0] = 1.0f;
        alone(&q, PX_B_DELAY, PX_DLY_DIGITAL, 0);
        q.p[PX_B_DELAY][0] = 100; q.p[PX_B_DELAY][2] = 100; q.p[PX_B_DELAY][3] = 100;
        run(&q, sr, x, y, n);
        int at = (int)(0.05 * sr);
        for (int i = at; i < n; i++) if (fabsf(y[i]) > fabsf(y[at])) at = i;
        printf("%.3f\n", at * 1000.0 / sr);
        return 0;
    }
    if (!strcmp(argv[1], "plate")) {
        alone(&q, PX_B_REVERB, PX_REV_PLATE, 50);
        px_engine_init(&e, (float)sr);
        px_engine_set(&e, &q);
        const double k = e.rv.rv_sr / 29761.0;           /* Dattorro's lengths, at the tank's rate */
        double lo = 1e9;
        for (int i = 0; i < 8; i++) { const double f = e.rv.rv_d[5 + i] / (PL_LEN[i] * k); if (f < lo) lo = f; }
        printf("%.4f\n", lo);
        return 0;
    }
    fprintf(stderr, "render: unknown command %s\n", argv[1]);
    return 2;
}
