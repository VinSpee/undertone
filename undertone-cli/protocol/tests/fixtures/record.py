#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Records what the Python tools send to a simulated pedal, as the golden transcripts the Rust port must reproduce byte
for byte (protocol/tests/transcripts.rs). It runs tools/uboot_rescue.py and tools/uboot_install.py, unchanged, against
the simulated pedals of tests/uboot_sim.py and tests/recovery_sim.py on the bus of tests/test_uboot_install.py, with
inputs both sides build the same way (an xorshift64* noise and tests/fw_layouts.py's images). It writes every transfer
(each SCSI command with its data's length and CRC-32, each recovery-mode request, frame and read), every line the tools
log, and the flash the pedal ends with.

  python3 undertone-cli/protocol/tests/fixtures/record.py      rewrites transcripts.json beside this file
"""
import hashlib, json, sys, tempfile, zlib
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "tools")]
import uboot_sim
import recovery_sim
from fw_layouts import flash_image
import pd40_recovery as pr
import pocketx_fw as fw
import pxpkg
import uboot_install as ui
import uboot_rescue as ur

M64 = (1 << 64) - 1


def noise(seed, n):
    """protocol/src/sim.rs's `noise`."""
    x = (seed * 0x9E3779B97F4A7C15 & M64) | 1
    out = bytearray(n)
    for i in range(n):
        x ^= x >> 12
        x ^= (x << 25) & M64
        x ^= x >> 27
        out[i] = (x * 0x2545F4914F6CDD1D & M64) >> 56
    return bytes(out)


class Pedal(uboot_sim.SimPedal):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.transcript = []

    def execute(self, cdb, out, in_len, timeout=2000):
        if out is not None:
            self.transcript.append(f"scsi {cdb.hex()} out={len(out)}:{zlib.crc32(out):08x} in={in_len} t={timeout}")
        else:
            self.transcript.append(f"scsi {cdb.hex()} in={in_len} t={timeout}")
        return super().execute(cdb, out, in_len, timeout)


class Recovery(recovery_sim.SimRecovery):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.transcript, self.line = [], None

    def access(self, kind, *what):
        super().access(kind, *what)
        self.transcript.append(self.line)

    def control_in(self, request, n):
        self.line = f"ctl {request:#04x} {n}"
        return super().control_in(request, n)

    def bulk_out(self, data):
        self.line = f"out {len(data)} {zlib.crc32(bytes(data)):08x}"
        return super().bulk_out(data)

    def bulk_in(self, n, ms):
        self.line = f"in {n} {ms}"
        return super().bulk_in(n, ms)


class Bench:
    """tests/test_uboot_install.py's Bench, with the recording pedals (protocol/src/sim.rs ports it)."""
    POLL = 0.05

    def __init__(self, flash, starts):
        self.clock = uboot_sim.FakeClock()
        self.uboot = Pedal(flash, LOADER, self.clock)
        self.uboot.present = False
        self.starts, self.boot_window = list(starts), 3.0
        self.end = self.clock.t + 120.0
        self.mode, self.rec, self.recoveries = "off", None, []
        self.empty_since = self.clock.t

    def now(self):
        return self.clock.t

    def sleep(self, s):
        self.clock.t += s
        if self.clock.t > self.end:
            raise KeyboardInterrupt

    def appear(self, at):
        self.uboot.reenumerate()
        self.mode, self.appeared, self.claimed = "uboot", at, False

    def step(self):
        t = self.clock.t
        if self.mode == "recovery":
            self.rec.tick()
            if not self.rec.present:
                self.mode = "gap" if self.rec.next_device == pr.UBOOT else "off"
        if self.mode == "gap" and t >= self.rec.departed_at + self.rec.reset_s:
            self.appear(self.rec.departed_at + self.rec.reset_s)
        if self.mode == "uboot" and (not self.uboot.present or not self.claimed and t >= self.appeared + self.boot_window):
            self.uboot.present, self.mode = False, "off"
        if self.mode != "off":
            self.empty_since = None
        elif self.empty_since is None:
            self.empty_since = t
        if self.mode == "off" and self.starts and t >= self.empty_since + 1:
            self.empty_since = None
            if self.starts.pop(0) == "uboot":
                self.appear(t)
            else:
                self.rec = Recovery(boot_crc=zlib.crc32(bytes(self.uboot.flash[:0x6000])), in_zeros=True)
                self.rec.clock, self.rec.wait = self.now, self.sleep
                self.recoveries.append(self.rec)
                self.mode = "recovery"

    def present(self):
        self.step()
        return {"recovery": {pr.RECOVERY}, "uboot": {pr.UBOOT}}.get(self.mode, set())

    def open_recovery(self):
        self.step()
        return self.rec if self.mode == "recovery" else None

    def open_uboot(self):
        self.step()
        if self.mode != "uboot":
            return None
        self.claimed = True
        return self.uboot

    def transcript(self):
        return [line for r in self.recoveries for line in r.transcript] + self.uboot.transcript


LOADER = noise(1, ur.LOADER_SIZE)
BACKUPS = Path(tempfile.mkdtemp())


def logger(lines):
    def log(m):
        lines.append("backup saved: BACKUP" if m.startswith("backup saved: ") else m)
    return log


def outcome(run):
    try:
        n, _ = run()
        return {"code": 0, "sectors": n}
    except ur.GuardError as e:
        return {"code": 2, "error": str(e)}
    except ui.Stopped as e:
        return {"code": e.code, "error": str(e)}
    except ur.RescueError as e:
        return {"code": 1, "error": str(e)}


# ---------------------------------------------------------------- the rescue
IMAGE = noise(2, 0x10000)


def crashed_flash():
    flash = bytearray(noise(3, ur.FLASH_SIZE))
    flash[:0x4000] = IMAGE[:0x4000]
    for s in (5, 6):
        flash[s * 0x1000:(s + 1) * 0x1000] = IMAGE[s * 0x1000:(s + 1) * 0x1000]
    return bytes(flash)


def rescue(write, drop_at=None):
    pedal = Pedal(crashed_flash(), LOADER)
    pedal.drop_at = drop_at
    lines = []

    def open_device():
        if not pedal.present:
            pedal.reenumerate()
        return pedal
    result = outcome(lambda: ur.rescue(open_device, LOADER, ur.whole_image(IMAGE), write, BACKUPS, 10, logger(lines)))
    return {"transcript": pedal.transcript, "log": lines, "result": result,
            "flash": hashlib.sha256(bytes(pedal.flash)).hexdigest()}


# ---------------------------------------------------------------- the install, on each layout
def layouts_and_images():
    old, new = flash_image(0x4000, noise(20, 0x8000)), flash_image(0x6000, noise(23, 0x8000))
    layouts = (replace(ui.LAYOUTS[0], boot_crc=zlib.crc32(old[:0x4000])),
               replace(ui.LAYOUTS[1], boot_crc=zlib.crc32(new[:0x6000])))
    return layouts, {"old": old, "new": new}


LAYOUTS, IMAGES = layouts_and_images()
SOURCES = {"old": flash_image(0x4000, noise(21, 0x8000)), "new": flash_image(0x6000, noise(24, 0x8000))}


def install(which, write):
    flash = IMAGES[which] + noise(99, ur.FLASH_SIZE - len(IMAGES[which]))
    bench = Bench(flash, ("uboot",) if which == "old" else ("recovery",))
    lines = []
    log = logger(lines)
    with mock.patch.object(ui, "LAYOUTS", LAYOUTS), \
            mock.patch.dict(pr.HEADS, {LAYOUTS[1].boot_crc: "the synthetic V23 head of this test"}):
        source = ui.flash_source(SOURCES[which], "the test image", "the test image: its")
        seen = []

        def open_device():
            msc = ui.boot_state(bench, log, log)
            log("pedal found in the chip's USB boot state")
            return msc
        result = outcome(lambda: ur.rescue(open_device, LOADER, ui.plan_for(source, log, seen), write, BACKUPS, 10,
                                           log))
    return {"transcript": bench.transcript(), "log": lines, "result": result,
            "flash": hashlib.sha256(bytes(bench.uboot.flash)).hexdigest(), "source_what": source.what}


# ---------------------------------------------------------------- packages and their checks
def packages():
    """Each package's identity and checks, and what the rescue and the install make of it."""
    flash = flash_image(0x6000, noise(23, 0x8000))
    damaged = bytearray(flash)
    damaged[0x6000 + 0x200] ^= 1                  # inside app.bin: its data CRC fails, the UFW entry's does not
    cases = {"official": (flash, "BlackBox_023"), "ours": (flash, "BlackBox_950"), "pocketx": (flash, "PocketX_016"),
             "damaged": (bytes(damaged), "BlackBox_023")}
    out = {}
    for name, (f, tag) in cases.items():
        raw = pxpkg.ufw(f, b"OTA" * 100, tag)
        if name == "official":
            out["broken-header"] = record_package(bytes([raw[0] ^ 1]) + raw[1:])
        out[name] = record_package(raw)
    return out


def record_package(raw):
    path = BACKUPS / "BlackBox_023.fwsc"
    path.write_bytes(raw)
    _, L, tag, u = fw.load(path)
    entry = {"tag": tag, "checks": [[k, v] for k, v in fw.package_checks(L, u).items()]}
    try:
        entry["rescue"] = {"ok": hashlib.sha256(ur.load_image(path)).hexdigest()}
    except ur.RescueError as e:
        entry["rescue"] = {"error": str(e).replace(str(path), path.name)}
    with mock.patch.object(ui, "LAYOUTS", LAYOUTS):
        try:
            source = ui.official_area(path)
            entry["install"] = {"what": source.what, "area": hashlib.sha256(source.area).hexdigest()}
        except ur.GuardError as e:
            entry["install"] = {"refused": str(e)}
    return entry


def main():
    fixtures = {
        "rescue-read-only": rescue(False),
        "rescue-write": rescue(True),
        "rescue-resume": rescue(True, drop_at=150),
        "install-old-dry-run": install("old", False),
        "install-old-write": install("old", True),
        "install-new-dry-run": install("new", False),
        "install-new-write": install("new", True),
    }
    out = Path(__file__).with_name("transcripts.json")
    out.write_text(json.dumps(fixtures, indent=1) + "\n")
    Path(__file__).with_name("packages.json").write_text(json.dumps(packages(), indent=1) + "\n")
    print(f"wrote {out}: " + ", ".join(f"{k} {len(v['transcript'])} transfers" for k, v in fixtures.items()))


if __name__ == "__main__":
    main()
