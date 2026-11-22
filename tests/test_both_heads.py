#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""One package serves both flash heads. Each package's app area, written where a pedal's head names it (0x4000 on the
old head, 0x6000 on M-VAVE's BlackBox V22 and later), leaves the head as it was, ends at or below the start of that
head's stock settings (the end of its own flash.bin), and passes every check of the area: its head entry under the chip
key, the CRC of each file, the entry address 0x02000120.
  python3 tests/test_both_heads.py [--built] [OFFICIAL.fwsc ...]
The heads are synthetic ones built to the two layouts (tests/fw_layouts.py), and the official packages' own heads when
their files are given (they are not in this repository). The packages: one built here whose app fills the whole slot,
and with --built every package the build made (docs/firmware, build/apps/*)."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import pocketx_fw as fw  # noqa: E402
import pxpkg  # noqa: E402
from fw_layouts import flash_image  # noqa: E402

FLASH_SIZE = 0x100000
fails = 0


def ok(cond, what):
    global fails
    print(f"{what:<110} {'ok' if cond else 'FAIL'}")
    fails += 0 if cond else 1


def flash_bin(path):
    _, L, _, u = fw.load(path)
    return next(L[e["off"]:e["off"] + e["len"]] for e in u["ents"] if e["name"] == "flash.bin")


def install(head_flash, area):
    """What the update loader leaves: the area at the address the pedal's head names, nothing else written.
    -> the flash, the area's start and its end"""
    flash = bytearray(head_flash.ljust(FLASH_SIZE, b"\xFF"))
    base = fw.app_base(bytes(flash))
    flash[base:base + len(area)] = area
    return bytes(flash), base, base + len(area)


def problems(head_flash, area):
    """Why this area does not fit this head: [] when it does"""
    flash, base, end = install(head_flash, area)
    out = []
    if end > len(head_flash):
        out.append(f"ends at {end:#x}, past the head's stock settings at {len(head_flash):#x}")
    if flash[:base] != head_flash[:base]:
        out.append("the head changed")
    dec = fw.flash_decrypt(flash[:end])
    ents = fw.flash_parse(dec)
    out += [k for k, v in fw.flash_checks(dec, ents).items() if not v]
    if ents[0]["addr"] != 0x02000120:
        out.append(f"entry {ents[0]['addr']:#x}")
    return out


heads = [("synthetic old head", flash_image(0x4000, length=0xA3000)),
         ("synthetic V22 head", flash_image(0x6000, length=0x9F000))]
heads += [(f"{Path(f).name} ({fw.load(f)[2]})", flash_bin(f)) for f in sys.argv[1:] if f != "--built"]
for name, head in heads:
    print(f"head {name}: app area at {fw.app_base(head):#x}, stock settings at {len(head):#x}")

with tempfile.TemporaryDirectory() as t:
    app = b"OP-PRODUCT:PocketX_900".ljust(32, b"\0")
    app = (app + bytes(range(256)) * (pxpkg.APP_SLOT // 256 + 1))[:pxpkg.APP_SLOT]
    pxpkg.build(app, b"OTA" * 100, Path(t), 99, None, ROOT / "firmware" / "sdk" / "packager")
    packages = sorted(Path(t).glob("*.fwsc"))
    if "--built" in sys.argv:
        built = sorted((ROOT / "docs" / "firmware").glob("*.fwsc")) + sorted((ROOT / "build" / "apps").glob("*/*.fwsc"))
        ok(len(built) >= 4, f"--built: {len(built)} packages the build made")
        packages += built

    for pkg in packages:
        fl = flash_bin(pkg)
        ok(fw.app_base(fl) == 0x4000 and len(fl) == 0x4000 + pxpkg.AREA_LEN,
           f"{pkg.name}: flash.bin is the area at 0x4000 and {pxpkg.AREA_LEN:#x} bytes of it")
        for name, head in heads:
            bad = problems(head, fl[0x4000:])
            ok(not bad, f"{pkg.name} on the {name}" + (f": {', '.join(bad)}" if bad else ""))

    # the check itself: the area of the earlier, larger slot runs into the V22 head's stock settings
    sdk = pxpkg.sdk_files(None, ROOT / "firmware" / "sdk" / "packager")
    old = pxpkg.app_area(app, sdk["cfg_tool.bin"], sdk["cfg/eq_cfg_hw.bin"], slot=0x9D740)
    bad = problems(heads[1][1], old.ljust((len(old) + 0xFFF) & ~0xFFF, b"\xFF"))
    ok(any("past the head's stock settings" in b for b in bad), "the earlier slot (0x9D740) on the synthetic V22 head: "
       "past its stock settings")

print("OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
