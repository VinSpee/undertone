/* SPDX-License-Identifier: GPL-3.0-only
 * OpenPocket — musical MIDI over USB: the glue between usb.c's rings and the pedal (docs/MIDI.md).
 *
 * usb.c (felucca-bsp, unchanged) puts the channel voice messages and the clock / transport bytes of the host into
 * midi_in_q (4-byte USB-MIDI event packets, with the millisecond they arrived) and sends what is put in midi_out_q.
 * SysEx never takes this road: it goes to the update code (ota.c) and the editor (px_editor.h) only. With the MIDI page's
 * USB PORT on FOOTSWITCH, felucca-bsp's host (chip/usb_host.c) puts a footswitch's channel messages in the same ring, so a
 * Chocolate by cable is read as a computer is; nothing is sent back to it then.
 * The including file provides px_midi.h, usb.c's rings, PRESET, cur_preset, load_preset, master_vol, ui_mode / ui_item /
 * ui_nitems and ui_preset_step (ui.h), st_midi, st_usb and st_commit (px_store.h), and ms_now.
 *
 * The ring must be emptied: usb.c leaves the host's USB packet unread (NAK) while the ring is nearly full, and the
 * editor's and installer's SysEx come in the same packets. Nothing drained it before this file.
 */
#pragma once

static px_midi_tx_t mid_tx;
static px_midi_clock_t mid_clk;
static px_midi_tap_t mid_tap;

static void midi_persist(void)                  /* the page's HOME: save the settings (the sound is not touched) */
{
    st_midi = px_midi_cfg_pack(&mid_cfg);
    st_usb = (uint8_t)((st_usb & ~1u) | (px_ua_on & 1u));   /* v42: USB AUDIO (px_usb.h then presents the device anew) */
    ft_box(0, 186, 240, "saving...", &GF_TX, C_AMBER, C_GROUND, 1);
    if (st_ok) (void)st_commit();
}

#if OP_BLE_TEST
/* what a Bluetooth write leaves here (px_midi_ble_write) goes through the same px_midi_in as USB. The writer is the Bluetooth
 * stack's task, which runs from the main loop (ble_poll), so nothing here races: a full ring only drops what does not fit. */
#include "px_ble_midi.h"
#define BLE_MQ 32u
static uint32_t ble_in_q[BLE_MQ], ble_in_w, ble_in_r;
static px_blem_t ble_parse;
static void px_midi_ble_write(const uint8_t *p, uint32_t n)
{
    uint32_t pkt[BLE_MQ], got = px_blem_parse(&ble_parse, p, n, pkt, BLE_MQ), i;
    for (i = 0; i < got && ble_in_w - ble_in_r < BLE_MQ; i++) ble_in_q[ble_in_w++ % BLE_MQ] = pkt[i];
}
#endif

/* a quarter note in ms, from MIDI clock or CC 116's taps: the delay's TIME, the nearest step */
static void mid_quarter(uint32_t q, int *touched)
{
    int v = px_dly_value_for_ms(PRESET.type[PX_B_DELAY], (float)q);
    if (PRESET.p[PX_B_DELAY][0] != v) { PRESET.p[PX_B_DELAY][0] = (uint8_t)v; *touched = 1; }
}

/* one received event packet, from either road; *touched: the sound changed */
static void px_midi_in(uint32_t pkt, uint32_t ms, int free_ui, int *touched)
{
    px_midi_msg_t m = px_midi_decode(&mid_cfg, pkt);
    if (m.type == PXM_IGNORE) return;
    if (m.type == PXM_CLOCK) {
        uint32_t q = mid_cfg.clock && free_ui ? px_midi_clock_tick(&mid_clk, ms) : 0u;
        if (q) mid_quarter(q, touched);
        return;
    }
    if (m.type == PXM_START || m.type == PXM_STOP) { px_midi_clock_reset(&mid_clk); return; }
    mid_last[0] = m.type; mid_last[1] = m.d1; mid_last[2] = m.d2;
    if (m.type == PXM_PC) {
        if (free_ui && m.d1 < px_preset_count()) {
            cur_preset = m.d1;
            load_preset(cur_preset);
            if (ui_mode == M_EDIT) ui_mode = M_BLOCK;
            if ((int)ui_item >= ui_nitems()) ui_item = 0;
            *touched = 1;
        }
    } else if (m.d1 == PXM_CC_TAP) {                  /* a tap of the delay's tempo */
        uint32_t q = m.d2 >= 64u && free_ui ? px_midi_tap(&mid_tap, ms) : 0u;
        if (q) mid_quarter(q, touched);
    } else if (m.d1 == PXM_CC_NEXT || m.d1 == PXM_CC_PREV) {   /* the next / the previous preset, as the footswitches */
        if (m.d2 >= 64u && free_ui) { ui_preset_step(m.d1 == PXM_CC_NEXT ? 1 : -1); *touched = 1; }
    } else {
        uint32_t mv = master_vol;
        int mset = 0;
        if (free_ui && px_midi_cc_apply(&PRESET, m.d1, m.d2, &mv, &mset)) *touched = 1;
        else if (mset) master_vol = mv;
    }
}

/* every main-loop pass */
static void px_midi_service(void)
{
    /* the sound may be changed from the host only while the pedal is on a normal page */
    int free_ui = ui_mode != M_SAVE && ui_mode != M_TUNER && ui_mode != M_MOVE && ui_mode != M_MIDI;
    int touched = 0;
#if OP_USB_HOST
    const int to_host = !px_usb_foot && usb_midi_out_ready();   /* USB PORT on FOOTSWITCH: the footswitch is not a computer */
#else
    const int to_host = usb_midi_out_ready();
#endif
    mid_usb_up = (uint8_t)to_host;
    while (mi_r != mi_w) {                      /* usb.c's timer interrupt is the only writer */
        uint32_t at = mi_r % MQ, pkt = midi_in_q[at], ms = midi_in_ms[at];
        RING_PUBLISH();
        mi_r++;
        px_midi_in(pkt, ms, free_ui, &touched);
    }
#if OP_BLE_TEST
    while (ble_in_r != ble_in_w) px_midi_in(ble_in_q[ble_in_r++ % BLE_MQ], ms_now(), free_ui, &touched);
#endif
    if (midi_in_overflow && mi_r == mi_w) midi_in_overflow = 0;   /* usb.c stopped queueing on overflow: start over */
    if (touched) px_midi_tx_sync(&mid_tx, &PRESET, cur_preset);   /* what the host sent is not sent back */
    if (!to_host) { px_midi_tx_sync(&mid_tx, &PRESET, cur_preset); return; }   /* (nothing is sent to a footswitch: one that
                                                * never takes its OUT endpoint's packets would be dropped as lost, uh_tx_poll) */
    while (midi_out_room()) {
        uint32_t pkt = px_midi_tx_next(&mid_tx, &mid_cfg, &PRESET, cur_preset);
        if (!pkt) break;
        midi_out_try(pkt);
    }
}
