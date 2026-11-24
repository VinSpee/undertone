/* SPDX-License-Identifier: GPL-3.0-only */
/* Host stand-in for bsp/chip/fm1_time.h: TIMER4 is a variable the test advances (24 MHz, it wraps every 178.957 s) */
#pragma once
#include <stdint.h>
static uint32_t shim_t4;
#define FM1_T4_CNT shim_t4
#define FM1_TICKS_PER_US 24u
