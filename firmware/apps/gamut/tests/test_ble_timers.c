/* SPDX-License-Identifier: GPL-3.0-only */
/* The Bluetooth test image's timers (firmware/apps/gamut/ble/ble_os.c) on a PC, with TIMER4 and the interrupt enable as
 * variables (tests/ble_shim): the scheduler's clock counts on across TIMER4's wrap, so a periodic timer, a one-shot and a
 * task's sleep that straddle it fire on time; adding, deleting and restarting a timer leaves the interrupts as it found them
 * (on or off); the usr timeouts run from the 10 kHz tick every millisecond, never before their delay, with the interrupts as
 * the tick found them, and wait for a millisecond while the baseband's lock is taken; a usr id deletes in its own table
 * through any delete; full tables refuse.
 *   cc -O1 -Wall -Wno-unused-function -Ifirmware/apps/gamut/tests/ble_shim -Ifirmware/apps/gamut/ble -o build/ble_timers firmware/apps/gamut/tests/test_ble_timers.c && build/ble_timers */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* ble_os.c's heap and the C library names ble_os.h declares for the pedal, renamed off the PC's (whose headers are already
 * in, so their declarations stay as they are) */
#undef memset
#undef memcpy
#undef memmove
#undef strcpy
#undef strncpy
#define memset ble_t_memset
#define memcpy ble_t_memcpy
#define memmove ble_t_memmove
#define memcmp ble_t_memcmp
#define strlen ble_t_strlen
#define strcmp ble_t_strcmp
#define strcpy ble_t_strcpy
#define strncpy ble_t_strncpy
#define malloc ble_t_malloc
#define free ble_t_free
#ifdef __APPLE__
#define section(x) used                         /* (Mach-O takes no ELF section names; Linux, the CI, keeps them) */
#endif
#include "../ble/ble_os.c"
#undef section
void *ble_t_memset(void *d, int c, unsigned n) { uint8_t *p = d; while (n--) *p++ = (uint8_t)c; return d; }
void *ble_t_memcpy(void *d, const void *s, unsigned n) { uint8_t *p = d; const uint8_t *q = s; while (n--) *p++ = *q++; return d; }
int ble_t_strcmp(const char *a, const char *b) { while (*a && *a == *b) { a++; b++; } return (uint8_t)*a - (uint8_t)*b; }
char *ble_t_strncpy(char *d, const char *s, size_t n) { size_t i = 0; for (; i < n && s[i]; i++) d[i] = s[i]; for (; i < n; i++) d[i] = 0; return d; }
void ble_ctx_swap(uint32_t **save, uint32_t *load) { (void)load; if (save == &sched_sp && cur) cur->state = T_WAIT_Q; }
void ble_ctx_enter(uint32_t **save, uint32_t *top, void (*fn)(void)) { (void)save; (void)top; (void)fn; if (cur) cur->state = T_WAIT_Q; }
void ble_isr_ev(void) { }
void ble_isr_rx(void) { }
uint8_t *bb_hdl;                                /* RF_ble.c's baseband handle: its lock byte at BB_LOCK_AT */
static uint8_t fake_bb[40];

static int fails;
static void ok(int c, const char *what) { printf("%-100s %s\n", what, c ? "ok" : "FAIL"); if (!c) fails++; }
#define T4_PER_MS 24000u
static void at_ms(uint32_t ms) { shim_t4 += ms * T4_PER_MS; }   /* time passes (TIMER4 wraps by itself, as uint32_t) */
static void tick_ms(uint32_t ms)                /* time passes with the 10 kHz tick running: 10 ticks a millisecond */
{
    uint32_t i, k;
    for (i = 0; i < ms; i++) { shim_t4 += T4_PER_MS; for (k = 0; k < 10u; k++) ble_usr_tick(); }
}
static int fired, usr_fired, lib_runs, lib_ie_at_entry;
static void cb(void *p) { (void)p; fired++; }
static void cb_usr(void *p) { (void)p; usr_fired++; }
static void cb_lib(void *p) { (void)p; lib_runs++; lib_ie_at_entry = (int)shim_ie; local_irq_disable(); local_irq_enable(); }

int main(void)
{
    uint16_t id, u;
    uint32_t i;
    ble_os_init();
    ble_ms();

    /* ---- the clock across TIMER4's wrap ---- */
    shim_t4 = 0xFFFFFFFFu - 150u * T4_PER_MS;   /* 150 ms before the wrap */
    ble_ms();
    fired = 0;
    id = sys_timer_add(0, cb, 100u);
    u = sys_timeout_add(0, cb, 250u);
    for (i = 0; i < 10u; i++) { at_ms(50u); ble_poll(); }   /* 500 ms, across the wrap */
    ok(fired == 5 + 1, "a periodic 100 ms timer and a 250 ms one-shot both straddle TIMER4's wrap and fire on time (5 + 1)");
    sys_timer_del(id);
    ok(timers[u - 1].used == 0, "the one-shot is free after it fired");

    /* ---- the interrupts as they were ---- */
    shim_ie = 1u; id = sys_timeout_add(0, cb, 10u);
    ok(shim_ie == 1u && id != 0, "a timer added with the interrupts on leaves them on");
    shim_ie = 0u; sys_timer_re_run(id); sys_timer_modify(id, 20u); sys_timeout_del(id);
    ok(shim_ie == 0u, "added, restarted, changed and deleted with them off (an interrupt), they stay off: never a bare enable");
    shim_ie = 0u; u = usr_timeout_add(0, cb_usr, 5u, 0); usr_timeout_del(u);
    ok(shim_ie == 0u && u > USR_ID0, "a usr timeout added and deleted with them off leaves them off");
    shim_ie = 1u;

    /* ---- the usr timeouts on the tick ---- */
    usr_fired = 0;
    u = usr_timeout_add(0, cb_usr, 6u, 0);
    ble_poll();
    ok(usr_fired == 0, "ble_poll does not run the usr timeouts");
    tick_ms(6u);
    ok(usr_fired == 0, "not before their delay (6 ms after, the next millisecond's tick)");
    tick_ms(1u);
    ok(usr_fired == 1, "the tick runs it once it is due");
    tick_ms(20u);
    ok(usr_fired == 1, "...and once only");
    shim_ie = 0u; usr_timeout_add(0, cb_lib, 1u, 0); tick_ms(3u);
    ok(lib_runs == 1 && lib_ie_at_entry == 0 && shim_ie == 0u, "a callback runs with the interrupts as the tick found them, and its own pair does not leave them on");
    shim_ie = 1u; usr_timeout_add(0, cb_lib, 1u, 0); tick_ms(3u);
    ok(lib_runs == 2 && lib_ie_at_entry == 1 && shim_ie == 1u, "...with them on, on");

    bb_hdl = fake_bb; fake_bb[BB_LOCK_AT] = 1u;
    usr_fired = 0; usr_timeout_add(0, cb_usr, 1u, 0); tick_ms(5u);
    ok(usr_fired == 0, "while the baseband's lock is taken, a due usr timeout waits");
    fake_bb[BB_LOCK_AT] = 0u; tick_ms(1u);
    ok(usr_fired == 1, "and runs at the next millisecond once it is free");
    bb_hdl = 0;

    usr_fired = 0;
    u = usr_timeout_add(0, cb_usr, 2u, 0); sys_timeout_del(u);
    id = usr_timeout_add(0, cb_usr, 2u, 0); usr_timeout_del(id);
    tick_ms(10u);
    ok(usr_fired == 0 && usr_used == 0u, "a usr id given to sys_timeout_del or usr_timeout_del is deleted from its own table");
    fired = 0; id = sys_timeout_add(0, cb, 1u); usr_timeout_del(id); at_ms(5u); ble_poll();
    ok(fired == 0, "and a timer's id given to usr_timeout_del deletes the timer");

    for (i = 0; i < MAXUSR; i++) usr_timeout_add(0, cb_usr, 100u, 0);
    ok(usr_timeout_add(0, cb_usr, 1u, 0) == 0, "a full usr table refuses");
    for (i = 0; i < MAXUSR; i++) usr_timeout_del((uint16_t)(USR_ID0 + i + 1u));
    for (i = 0; i < MAXTIMER; i++) sys_timeout_add(0, cb, 100u);
    ok(sys_timeout_add(0, cb, 1u) == 0, "a full timer table refuses");

    puts(fails ? "ble timers: FAILED" : "ble timers: ok");
    return fails != 0;
}
