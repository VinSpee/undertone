#!/usr/bin/env python3
"""tools/jlfold.py: the Bluetooth test image's constants read from ble_cfg.c and ble_stubs.c, and the fold of a member's IR."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import jlfold


def ok(cond, name):
    print(f"{name:<72} {'ok' if cond else 'FAIL'}")
    if not cond:
        sys.exit(1)


ble = ROOT / "firmware/apps/gamut/ble"
with tempfile.NamedTemporaryFile("w", suffix=".c") as f:
    f.write((ble / "ble_cfg.c").read_text() + (ble / "ble_stubs.c").read_text())
    f.flush()
    vals = jlfold.cfg_values(f.name)
ok(vals.get("config_btctler_le_roles") == ("i32", 6), "ble_cfg.c: config_btctler_le_roles is LE_ADV | LE_SLAVE")
ok(vals.get("rx_fre_offset_adjust_enable") == ("i8", 1), "ble_cfg.c: a uint8_t constant read at its width")
ok(vals.get("log_tag_const_e_LL") == ("i8", 0), "ble_stubs.c: the log tags are off")
ok(vals.get("config_asser") == ("i32", 0), "audio_probe.h: config_asser is 0")
ok("config_btctler_le_features" not in vals, "a 64-bit constant is left to the linker")

# the forms the library's members take as text IR (-disable-llvm-passes)
ir = """@config_btctler_le_roles = external local_unnamed_addr constant i32, align 4
@log_tag_const_e_LL = external local_unnamed_addr constant i8, align 1
@rx_fre_offset_adjust_enable = external local_unnamed_addr constant i32, align 4
@other_const = external local_unnamed_addr constant i32, align 4
declare void @printf_buf(i8*, i32) local_unnamed_addr #1
declare i32 @printf(i8* nocapture readonly, ...) local_unnamed_addr #3
declare i32 @puts(i8* nocapture readonly) #4
declare i32 @strlen(i8*) local_unnamed_addr #1
"""
text, folded, skipped, emptied = jlfold.fold(ir, vals)
ok("@config_btctler_le_roles = internal constant i32 6" in text, "a setting becomes an internal constant with its value")
ok("@log_tag_const_e_LL = internal constant i8 0" in text, "a log tag becomes an internal 0")
ok("@rx_fre_offset_adjust_enable = external" in text and skipped == ["rx_fre_offset_adjust_enable (i32, defined i8)"],
   "a constant read at another width is left to the linker")
ok("@other_const = external" in text, "a constant no file defines is left alone")
ok("define internal void @printf_buf(i8*, i32) {\n  ret void\n}" in text, "an empty print helper becomes internal (void)")
ok("define internal i32 @printf(i8* nocapture readonly, ...) {\n  ret i32 0\n}" in text, "an empty print helper becomes internal (i32)")
ok("define internal i32 @puts(i8* nocapture readonly) {\n  ret i32 0\n}" in text, "one with no attributes before its number too")
ok("declare i32 @strlen" in text, "other functions are left alone")
ok(emptied == 3 and folded == 2, "two constants folded, three print helpers emptied")
print("jlfold: ok")
