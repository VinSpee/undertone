/* SPDX-License-Identifier: GPL-3.0-only
 * OpenPocket — the USB-C port as the USB MIDI host of a footswitch by cable (an M-VAVE Chocolate), and what the pedal shows
 * of it (docs/MIDI.md, "A footswitch by cable"). No register access: px_usb.h feeds it, the app draws it,
 * tests/test_usb_host.c includes it alone. After ettorebox (Roberto Antonacci), commit 10e2c7c.
 *
 * felucca-bsp's host (chip/usb_host.c, FELUCCA_USB_HOST) tells the application what it sees one message at a time
 * (usb_host_message, UH_MSG_*): the host is on, off, a USB MIDI interface was started, none was found, a low-speed device, the
 * device was lost. pxu_msg turns them into the state the screen shows; pxu_line takes a NO MIDI or LOW SPEED device that was
 * unplugged back to "nothing attached" (the host says nothing then).
 *
 * pxu_ms_add is the host's clock: chip/usb_host.c times its waits and its timeouts with UH_MS. The main loop's ms_now() is
 * TIMER4 / 24000, which starts again from 0 every 178.9 s: a host given that time would stop looking for a device until the
 * clock caught up, and time a transfer out early. px_usb.h adds the TIMER4 ticks of each USB poll to a count of its own.
 */
#pragma once
#include <stdint.h>

enum { PXU_OFF, PXU_WAIT, PXU_NOMIDI, PXU_LOW, PXU_OK, PXU_LOST };   /* what the host sees */
enum { PXU_MSG_ON = 1, PXU_MSG_OFF, PXU_MSG_MIDI, PXU_MSG_NOMIDI, PXU_MSG_LOW, PXU_MSG_LOST };   /* chip/usb_host.c's UH_MSG_*:
                                                                     * the same numbers (px_usb.h checks them) */
#define PXU_IDLE_MS 200u       /* a NO MIDI or LOW SPEED device unplugged this long: nothing attached again */

typedef struct {
    uint8_t st;                /* PXU_*: the screen's state */
    uint8_t idle;              /* the line has been idle since idle_ms (NO MIDI / LOW SPEED only) */
    uint32_t idle_ms;
} pxu_t;

/* one message from usb_host_message (0: none) */
static void pxu_msg(pxu_t *u, uint32_t msg)
{
    switch (msg) {
    case PXU_MSG_ON: u->st = PXU_WAIT; break;
    case PXU_MSG_OFF: u->st = PXU_OFF; break;
    case PXU_MSG_MIDI: u->st = PXU_OK; break;
    case PXU_MSG_NOMIDI: u->st = PXU_NOMIDI; break;
    case PXU_MSG_LOW: u->st = PXU_LOW; break;
    case PXU_MSG_LOST: u->st = PXU_LOST; break;
    default: return;
    }
    u->idle = 0;
}

/* every main-loop pass while the port is a host: line, a device holds D+ or D- up (chip/fm1_usb.h fm1_usb_line). The host
 * waits for an unusable device to be unplugged before it looks again, without a message: the screen follows the line */
static void pxu_line(pxu_t *u, uint32_t line, uint32_t now)
{
    if ((u->st != PXU_NOMIDI && u->st != PXU_LOW) || line) { u->idle = 0; return; }
    if (!u->idle) { u->idle = 1; u->idle_ms = now; return; }
    if (now - u->idle_ms >= PXU_IDLE_MS) { u->st = PXU_WAIT; u->idle = 0; }
}

/* the host's clock: the whole milliseconds in the TIMER4 ticks since the last call (unsigned: TIMER4's wrap is harmless while
 * the calls come less than 178 s apart), the rest kept for the next */
typedef struct { uint32_t t4, acc; } pxu_ms_t;
static uint32_t pxu_ms_add(pxu_ms_t *c, uint32_t t4, uint32_t ticks_per_ms)
{
    uint32_t n;
    c->acc += t4 - c->t4;
    c->t4 = t4;
    n = c->acc / ticks_per_ms;
    c->acc -= n * ticks_per_ms;
    return n;
}
