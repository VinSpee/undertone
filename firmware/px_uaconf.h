/* SPDX-License-Identifier: GPL-3.0-only
 * OpenPocket — USB audio: what the pedal asks of felucca-bsp's USB device (bsp/chip/usb.c), set before it is included
 * (px_usb.h; tests/test_usb_audio.c, which runs the same device on a PC). docs/USB-AUDIO.md.
 */
#pragma once

#define FELUCCA_UAC 1                           /* the pedal's sound to the computer (EP4 IN, asynchronous) */
#define FELUCCA_UAC_48K 0                       /* 44.1 kHz only, as the stock firmware: no resampler in the interrupt */
#define FELUCCA_UAC_OUT 1                       /* the computer's playback to the pedal's output (EP4 OUT, adaptive) */
#define FELUCCA_UAC_MIDI_LAST 1                 /* audio control, the streams, then MIDI: the order macOS 13-15 need (usb.c) */
#define UAC_RATE A_SR                           /* the streams' rate, the only one offered: the I2S's (base/audio.h) */
/* UAC_I2S_HZ100: the I2S clock's real rate at it (Hz x 100), which usb.c's packet pattern (UA_N1, UA_FRAC) and playback
 * step (UO_STEP) follow. UA_UP: frames the record ring's band sits higher than the 44.1 kHz times give (below) */
#if UAC_RATE == 44100u
#define UAC_I2S_HZ100 4411765u                  /* the 44.1 kHz family's 6 MHz / 136 = 44,117.647 Hz (docs/USB-AUDIO.md) */
#define UA_UP 0u
#elif UAC_RATE == 48000u
/* NOMINAL, NOT MEASURED: the 48 kHz family's real rate is not known yet. The rate48 build ran on a pedal, but its clock
 * report (DIAG) was not read. Measure it with that build (docs/RATE48-TEST.md: `node tools/op.mjs log`) and set it here */
#define UAC_I2S_HZ100 4800000u
/* at a whole 48 frames a ms, 3 blocks are 8 packets: the blocks' phase against the packets barely moves, so the fill read
 * at a block's start can drop by a whole packet at once (tests/test_usb_audio.c: 25 frames at 300 ppm slow, with the
 * band of the 44.1 kHz times); 8 frames more keep 0.6 ms in hand */
#define UA_UP 8u
#else
#error "USB audio at another rate needs that clock measured"
#endif
#define UA_T(f) (((f) * UAC_RATE + 22050u) / 44100u)   /* f frames at 44.1 kHz: the same time at the streams' rate */
#define FELUCCA_UAC_SWITCH 1                    /* only while the setting is on (usb_uac_on) */
#define HALF_FRAMES A_FR                        /* the frames a block feeds the record ring */
#define UO_N 1024u                              /* the playback ring: 4 KB (the target, a block and a packet either way) */
/* v42: the rings' fills, for the pedal's blocks (px_uaudio.h). A block is written and read where its sound is ready
 * (a_send, px_audio.h): 0.3 to 2.5 ms after the interrupt's start, by the preset, but steady within a preset (measured
 * over the 52 presets with a guitar playing: within 0.06 ms, 0.2 ms on ORGAN) since v42 keeps the callbacks' order
 * (px_aorder.h). felucca-bsp's own figures (a band of 80 to 128, primed at 104, and a target of 256) allow for a render
 * that starts up to 0.7 ms late and held 1.6 ms more than the pedal needs. Measured with these: the record ring's fill at
 * a block's write 38 to 121 frames, the playback ring's at a block's read 167 to 251 (it needs 130).
 * The margin left, with the two clocks up to 300 ppm apart either way (tests/test_usb_audio.c): 0.6 ms (26 frames)
 * and more. The record ring takes a block that comes that much later than the one before (an effect switched on), the
 * playback ring one that comes that much sooner (switched off); beyond it a few frames are held or the ring is primed
 * again, as at a preset change. These figures are 44.1 kHz frames; at 48 kHz the same times (UA_T) keep the margins. */
#if !OP_UADEV                                   /* (the measurement option sets them at run time, px_usb.h) */
#define UA_LO (UA_T(52u) + UA_UP)               /* the band of the record ring's fill at a block's write: below, a packet one frame shorter */
#define UA_HI (UA_T(108u) + UA_UP)              /*   above, one frame longer (one correction a block at most) */
#define UA_PRIME (UA_T(80u) + UA_UP)            /* silence ahead of the first block: the band's middle */
#define UO_TGT UA_T(208u)                       /* the playback ring's fill a block's read aims at */
#endif
