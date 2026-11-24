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
import dataclasses, hashlib, io, json, re, sys, tempfile, threading, zlib
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
import undertone as u
import undertone_screens as screens

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

    def __init__(self, flash, starts, drops=()):
        self.clock = uboot_sim.FakeClock()
        self.uboot = Pedal(flash, LOADER, self.clock)
        self.uboot.present = False
        self.starts, self.boot_window, self.drops = list(starts), 3.0, list(drops)
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
        if self.drops:
            self.uboot.drop_at = len(self.uboot.seen) + self.drops.pop(0)
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

    open_pedal = open_uboot                     # uboot_rescue.wait_for_pedal's name for it

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


# ---------------------------------------------------------------- undertone's commands, as a person runs them
FIRMWARE = BACKUPS / "firmware"


def firmware():
    """The kit's firmware folder with a package for each layout (BlackBox_020 and BlackBox_023), and their images."""
    FIRMWARE.mkdir(exist_ok=True)
    images = {}
    for v, image in (("020", flash_image(0x4000, noise(10, 0x8000), 0xA5000)), ("023", IMAGES["new"])):
        (FIRMWARE / f"BlackBox_{v}.fwsc").write_bytes(pxpkg.ufw(image, b"OTA" * 100, f"BlackBox_{v}"))
        images[v] = image
    return images


def shown(text):
    """The window's text, without what differs from run to run: the times, the backup's and the folders' paths."""
    text = re.sub(r"\[\s*\d+\.\ds\]", "[time]", text)
    text = re.sub(r"\S*blackbox-\d{8}-\d{6}\.dump\.bin", "BACKUP", text)
    return text.replace(str(FIRMWARE), "FIRMWARE")


def command(name, flash, starts, answer, *argv):
    """undertone's command `name` with `argv`, on a pedal that holds `flash`, the person typing `answer`."""
    bench = Bench(flash, starts)
    a = u.parser().parse_args([name, *argv, "--backup-dir", str(BACKUPS)])
    a.opts = u.Options(None, str(BACKUPS), 10)
    out = io.StringIO()
    with mock.patch.object(u, "FIRMWARE", FIRMWARE), mock.patch.object(ur, "get_loader", lambda p=None: LOADER), \
            mock.patch.object(u, "rescue_transport", lambda: bench), mock.patch.object(u, "install_transport", lambda: bench), \
            mock.patch.object(ui, "LAYOUTS", LAYOUTS), mock.patch.object(ur.time, "sleep", bench.sleep):
        code = u.COMMANDS[name](a, u.Out(out), lambda prompt: answer)
    transfers = "\n".join(bench.transcript()).encode()
    return {"code": code, "shown": shown(out.getvalue()).splitlines(),
            "transcript": hashlib.sha256(transfers).hexdigest(),
            "flash": hashlib.sha256(bytes(bench.uboot.flash)).hexdigest()}


def commands():
    images = firmware()
    dark = bytearray(noise(20, ur.FLASH_SIZE))
    dark[:len(images["023"])] = images["023"]
    dark[0x4000:0xA3000] = noise(21, 0xA3000 - 0x4000)
    dark = bytes(dark)
    on_v23 = SOURCES["new"] + noise(99, ur.FLASH_SIZE - len(SOURCES["new"]))   # the V23 head, another app
    return {
        "rescue": command("rescue", dark, ("uboot", "uboot"), "yes"),
        "rescue-not-confirmed": command("rescue", dark, ("uboot",), "no"),
        "rescue-refused": command("rescue", noise(22, ur.FLASH_SIZE), ("uboot",), "yes"),
        "install-official": command("install", on_v23, ("recovery", "recovery"), "YES ",
                                    "--official", str(FIRMWARE / "BlackBox_023.fwsc")),
        "check": command("check", on_v23, ("recovery",), ""),
    }


# ---------------------------------------------------------------- the guided screens
def screen_dict(screen):
    d = dataclasses.asdict(screen)
    d["aside"] = ["BACKUP" if "blackbox-" in line else line for line in d["aside"]]
    return json.loads(json.dumps(d))


class RecordingView:
    """A view that answers each question with the next scripted choice and runs each tool at once, keeping every screen,
    the phases the tool's lines walk the progress through, and each outcome."""

    def __init__(self, keys):
        self.keys, self.seen = list(keys), []
        self.caps = screens.Caps(unicode=False, motion=False)

    def ask(self, screen):
        key = self.keys.pop(0)
        self.seen.append({"ask": screen_dict(screen), "key": key})
        return key

    def work(self, screen, job_fn, log, write=False, hint=()):
        progress, phases = screens.Progress(write), []

        def take(line):
            progress.feed(line)
            if not phases or phases[-1] != progress.phase:
                phases.append(progress.phase)
        o = job_fn(take, take, threading.Event())
        self.seen.append({"work": screen_dict(screen), "write": write, "hint": list(hint), "phases": phases,
                          "code": o.code, "text": shown(o.text)})
        return o


class NoLog:
    path = None

    def write(self, line):
        pass


def guided(name, flash, starts, keys, start="menu", drops=(), attempts=10, permission=None):
    bench = Bench(flash, starts, drops)
    view, opened = RecordingView(keys), []
    gamut = ui.Source("Gamut's app area of the test", IMAGES["new"][0x6000:0x9F000])
    with mock.patch.object(u, "FIRMWARE", FIRMWARE), mock.patch.object(ur, "get_loader", lambda p=None: LOADER), \
            mock.patch.object(u, "rescue_transport", lambda: bench), mock.patch.object(u, "install_transport", lambda: bench), \
            mock.patch.object(ui, "LAYOUTS", LAYOUTS), mock.patch.object(ur.time, "sleep", bench.sleep), \
            mock.patch.object(u, "permission_problem", lambda: permission), mock.patch.object(ur, "WINDOWS", False), \
            mock.patch.object(u, "gamut_source", lambda p=None: gamut), mock.patch.object(screens, "Log", lambda f: NoLog()):
        guide = screens.Guide(view, u.Options(None, str(BACKUPS), attempts), start, open_url=opened.append)
        result = guide.go()
    return {"screens": view.seen, "opened": opened, "code": result.code, "restart": result.restart,
            "lines": [shown(line) for line in result.lines],
            "backup": result.backup is not None, "flash": hashlib.sha256(bytes(bench.uboot.flash)).hexdigest()}


def guided_flows():
    images = firmware()
    dark = bytearray(noise(20, ur.FLASH_SIZE))
    dark[:len(images["023"])] = images["023"]
    dark[0x4000:0xA3000] = noise(21, 0xA3000 - 0x4000)
    dark = bytes(dark)
    on_v23 = SOURCES["new"] + noise(99, ur.FLASH_SIZE - len(SOURCES["new"]))
    return {
        "rescue": guided("rescue", dark, ("uboot", "uboot"), ["rescue", "go", "go", "yes", "done"]),
        "rescue-not-now": guided("rescue-not-now", dark, ("uboot",), ["rescue", "go", "later", "done"]),
        "rescue-cannot": guided("rescue-cannot", noise(22, ur.FLASH_SIZE), ("uboot",), ["rescue", "go", "guide", "done"]),
        "rescue-fails-then-no": guided("rescue-fails-then-no", dark, ("uboot", "uboot"),
                                       ["rescue", "go", "go", "yes", "again", "no", "done"], drops=(100000, 100),
                                       attempts=1),
        "install": guided("install", on_v23, ("recovery", "recovery"), ["install", "go", "go", "yes", "done"]),
        "check": guided("check", on_v23, ("recovery",), ["check", "go", "done"]),
        "password": guided("password", on_v23, (), ["check", "go", "go"], permission=u.SUDO),
        "back-and-quit": guided("back-and-quit", on_v23, (), ["install", "back", "check", "back", "quit"]),
    }


CONFIGS = [("truecolor", "dark", True, False, 80, 24, 0.0), ("256", "light", True, False, 100, 30, 0.0),
           ("16", None, False, False, 62, 24, 0.0), ("truecolor", "light", True, True, 80, 24, 0.7)]
STATUSES = [(("spin", "looking for your pedal…", 0.0), (), "wait"),
            (("spin", "looking for your pedal…", 0.0), ("Still looking. Plug straight into this computer, no hub.",
                                                       "A pedal that will not start shows up between restarts."), "wait"),
            (("ok", "found it", 0.0), (), "busy"),
            (("bar", "writing", 0.42), (screens.REFUSED,), "busy")]


def frames(flows):
    """Every screen of the flows, and each tool screen with each status, composed in each configuration: the rows of
    (text, style) runs and the escape codes the palette gives each row."""
    seen, out = set(), []
    for flow in flows.values():
        for step in flow["screens"]:
            fields = step.get("ask") or step["work"]
            variants = [fields] if "ask" in step else [
                dict(fields, status=list(st), warn=list(warn), choices=[], foot=foot) for st, warn, foot in STATUSES]
            for v in variants:
                key = json.dumps(v, sort_keys=True)
                if key in seen:
                    continue
                seen.add(key)
                screen = screens.Screen(**{k: (tuple(tuple(c) for c in x) if k == "choices" else
                                              tuple(x) if isinstance(x, list) else x) for k, x in v.items()})
                for depth, theme, unicode, motion, cols, rows, tick in CONFIGS:
                    caps = screens.Caps(depth, theme, unicode, motion)
                    frame = screens.compose(screen, caps, cols, rows, tick)
                    palette = screens.Palette(depth, theme)
                    out.append({"screen": v, "caps": [depth, theme, unicode, motion], "size": [cols, rows],
                                "tick": tick, "plain": screens.plain(frame).split("\n"),
                                "digest": frame_digest(frame, palette)})
    return out


def frame_digest(frame, palette):
    """SHA-256 of every run's text and style and every row's escape codes (undertone/src/tui/look.rs's `digest`)."""
    runs = "\n".join("".join(f"{t}\x1f{','.join(st)}\x1e" for t, st in r) for r in frame)
    ansi = "\n".join(screens.ansi_row(r, palette) for r in frame)
    return hashlib.sha256((runs + "\n\n" + ansi).encode()).hexdigest()


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
    Path(__file__).with_name("commands.json").write_text(json.dumps(commands(), indent=1) + "\n")
    flows = guided_flows()
    Path(__file__).with_name("guided.json").write_text(json.dumps(flows, indent=1) + "\n")
    Path(__file__).with_name("frames.json").write_text(json.dumps(frames(flows), indent=0) + "\n")
    print(f"wrote {out}: " + ", ".join(f"{k} {len(v['transcript'])} transfers" for k, v in fixtures.items()))


if __name__ == "__main__":
    main()
