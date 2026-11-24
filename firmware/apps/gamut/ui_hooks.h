/* SPDX-License-Identifier: GPL-3.0-only
 * Gamut — the screens the base firmware would draw, which Gamut draws itself in its own design (ui_boot.h, ui.h). The
 * base draws through these names when an app defines them (docs/BASE-FIRMWARE.md); PALETTE and STARTER define none and
 * keep the base's screens. Included before base/diag.h, whose crash screen is the first to need its name. */
#pragma once
static void ui_boot_show(int safe);                      /* a start: the mark, the name, the version (safe: after a start that failed) */
static void ui_boot_failed(uint32_t st, int crashed);    /* the report of a start that did not finish, or that crashed */
static void ui_fault_show(const fm1_crash_t *c);         /* a crash, from the fault handler */
static void ui_uboot_show(void);                         /* the chip's USB rescue mode */
static void ui_update_show(uint32_t step, int32_t code); /* an update's steps and its failure (ui.h) */
#define OP_BOOT_SCREEN  ui_boot_show                     /* base/boot_screens.h, with OP_BOOT_FAILED */
#define OP_BOOT_FAILED  ui_boot_failed
#define OP_FAULT_SCREEN ui_fault_show                    /* base/diag.h */
#define OP_UBOOT_SCREEN ui_uboot_show                    /* px_usb.h */
#define OP_OTA_SCREEN   ui_update_show                   /* px_usb.h */
