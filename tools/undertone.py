#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""undertone - one command for a BlackBox over its USB cable: rescue a pedal that will not start, put Gamut on a pedal,
or check what a pedal holds. It runs tools/uboot_rescue.py and tools/uboot_install.py as libraries: every check,
refusal and write is theirs, unchanged. The guide is docs/RESCUE.md.

  undertone                the guided screens: one question at a time (numbered questions when not in a terminal)
  undertone rescue         a read-only check that saves a backup, then, after you type yes, the restore with M-VAVE's
                           file in the firmware folder whose head matches the pedal (= tools/uboot_rescue.py)
  undertone install        Gamut, or --official FILE.fwsc, or --restore DUMP.bin: a dry run, then, after you type yes,
                           the write (= tools/uboot_install.py). Not on Windows
  undertone check          read-only: how the pedal was found, its flash layout, the firmware it had; saves a backup
  undertone version

Nothing is written before you type yes, and every run saves a backup of the whole flash first. On macOS and Linux the
pedal is reached as root (sudo): in a terminal undertone asks for your password itself. On Windows it runs in a
Command Prompt opened as administrator.
Exit codes: those of the tool: 0 done, 1 setup problem or a failed transfer, 2 refused by a check, 3 and 5 as
uboot_install.py; 4 the write was not confirmed (nothing was written); 130 stopped.
"""
import argparse, functools, os, sys, time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "rescue" / "kit" / "tools")]   # the kit's layout, then the repository's
import uboot_rescue as ur
import uboot_install as ui
import pd40_install as pi
import head_fingerprint as hf
from uboot_rescue import GuardError, RescueError, ScsiError

KIT = "{{VERSION}}"                            # rescue/build_kit.py writes the kit's number here
GUIDE = "https://github.com/VinSpee/undertone/blob/main/docs/RESCUE.md"
FIRMWARE = ur.ROOT / "firmware"                # the kit's folder for M-VAVE's files
OFFICIAL = ("BlackBox_023.fwsc", "BlackBox_022.fwsc", "BlackBox_020.fwsc")   # tried in this order
PATH_FILE = {"A": "BlackBox_020.fwsc", "B": "BlackBox_023.fwsc"}             # head_fingerprint's paths
ENDS_ON = {"BlackBox_020.fwsc": "V20", "BlackBox_022.fwsc": "V22", "BlackBox_023.fwsc": "V23"}
NOT_CONFIRMED = 4
SUDO = ("talking to the pedal over USB needs root on macOS and Linux: the system keeps the pedal's USB disk for "
        "itself. Run it again with sudo in front (sudo ./undertone ...); nothing was sent to the pedal")
ADMIN = ("Windows lets only an administrator send these commands to the pedal: press the Windows key, type cmd, "
         "right-click Command Prompt, choose Run as administrator, go to this folder and run undertone there; nothing "
         "was sent to the pedal")


@functools.cache
def version():
    if KIT.isdigit():
        return KIT
    try:
        return (ur.ROOT / "rescue" / "VERSION").read_text().strip()
    except OSError:
        return "?"


def permission_problem():
    """None when this process may reach the pedal, else what to do, in words."""
    if ur.WINDOWS:
        return None if ur.is_admin() else ADMIN
    return None if ur.as_root() else SUDO


def as_root(argv):
    """Start this program again under sudo with the same arguments (macOS, Linux). sudo asks for the password."""
    os.execvp("sudo", ["sudo", sys.executable, str(Path(__file__).resolve()), *argv])


# ---------------------------------------------------------------- one pass of a tool
@dataclass
class Options:
    loader: str = None
    backup_dir: str = str(ur.DEFAULT_BACKUPS)
    attempts: int = 10


@dataclass
class Job:
    kind: str                                  # "rescue", "install" or "check"
    write: bool = False
    images: dict = field(default_factory=dict)  # rescue: {file name: flash image}; empty: identify only
    source: object = None                      # install: a uboot_install.Source
    opts: Options = field(default_factory=Options)


@dataclass
class Outcome:
    code: int                                  # the tool's exit code
    text: str = ""                             # its closing line
    changed: int = 0                           # sectors that differ, or were written
    backup: Path = None
    flash: bytes = None                        # the whole flash as read
    file: str = None                           # rescue: the file whose head is the pedal's
    layout: object = None                      # install: the pedal's flash layout
    found_in: str = None                       # "recovery" when the pedal came from M-VAVE's recovery mode


class Cancelled(RescueError):
    """The wait for the pedal was stopped. Nothing was sent."""


class Watch:
    """A transport whose waits end when stop is set, so that the guided screens can go back while it waits."""

    def __init__(self, inner, stop):
        self.inner, self.stop = inner, stop

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def _check(self):
        if self.stop is not None and self.stop.is_set():
            raise Cancelled("stopped while waiting for the pedal; nothing was sent")

    def open_pedal(self):
        self._check()
        return self.inner.open_pedal()

    def open_uboot(self):
        self._check()
        return self.inner.open_uboot()

    def sleep(self, s):
        self._check()
        self.inner.sleep(s)


def matching(images, seen):
    """uboot_rescue's plan over several files: the first whose head [0, 0x4000) is the pedal's, else the first, which
    uboot_rescue then refuses as always. With no file the image is the pedal's own flash: nothing differs."""
    def plan(chip, flash):
        seen["flash"] = flash
        if not images:
            return ur.whole_image(flash[:ur.WRITE_LIMIT])(chip, flash)
        name = next((n for n, i in images.items() if flash[:ur.WRITE_FROM] == i[:ur.WRITE_FROM]), next(iter(images)))
        seen["file"] = name
        return ur.whole_image(images[name])(chip, flash)
    return plan


def rescue_transport():
    return ur.transport()


def install_transport():
    return ui.transport()


def run(job, log, say=None, stop=None):
    """One pass of a tool: wait for the pedal, back it up, compare, and with job.write write. Returns an Outcome; only
    KeyboardInterrupt goes through. log gets every line the tool prints, say the recovery mode's lines."""
    if job.write and (identifies(job) or (job.kind == "rescue" and len(job.images) != 1)):
        raise ValueError("only a rescue with one file or an install writes")
    say = say or log
    seen, layouts = {}, []

    def logged(m):
        if m.startswith("backup saved: "):
            seen["backup"] = Path(m[len("backup saved: "):])
        log(m)

    def said(m):
        if "M-VAVE's recovery mode" in m:
            seen["found_in"] = "recovery"
        say(m)

    try:
        loader = ur.get_loader(job.opts.loader)
        if job.kind == "install" or (job.kind == "check" and not ur.WINDOWS):
            bus = Watch(install_transport(), stop)
            open_device = lambda: ui.boot_state(bus, logged, said)
        else:
            usb = Watch(rescue_transport(), stop)
            open_device = lambda: ur.wait_for_pedal(usb, logged)

        def opened():
            msc = open_device()
            logged("pedal found")
            return msc

        if job.kind == "install":
            plan = ui.plan_for(job.source, logged, layouts)
        else:
            if identifies(job):
                logged("check: the pedal is compared with its own flash, so nothing differs and nothing is written")
            plan = matching(job.images if job.kind == "rescue" else {}, seen)
        n, saved = ur.rescue(opened, loader, plan, job.write, Path(job.opts.backup_dir).expanduser(),
                             job.opts.attempts, logged)
        code, text = 0, closing(job, n, saved[0], layouts)
    except GuardError as e:
        code, text, n = 2, f"REFUSED: {e}", 0
    except ui.Stopped as e:
        code, text, n = e.code, f"ERROR: {e}", 0
    except Cancelled as e:
        code, text, n = 130, f"stopped: {e}", 0
    except RescueError as e:
        code, text, n = 1, f"ERROR: {e}", 0
    except ScsiError as e:
        code, text, n = 1, f"ERROR: the pedal stopped answering ({e}); nothing was written", 0
    return Outcome(code, text, n, seen.get("backup"), seen.get("flash"), seen.get("file"),
                   layouts[-1] if layouts else None, seen.get("found_in"))


def identifies(job):
    """A run that only reads and names the pedal: a check, or a rescue with no file to compare."""
    return job.kind == "check" or (job.kind == "rescue" and not job.images)


def closing(job, n, backup, layouts):
    """The tool's own last line."""
    if identifies(job):
        return f"Check finished, nothing was written. Backup: {backup}"
    if job.kind == "rescue":
        return (f"Done: {n} sectors written and verified. Power-cycle the pedal. Backup: {backup}" if job.write else
                f"Read-only run finished, nothing was written. {n} sectors differ from the image. Backup: {backup}")
    if job.write:
        return f"Done: {n} sectors written and verified, on {layouts[-1].name}. Backup: {backup}"
    return (f"Dry run finished, nothing was written. {n} sectors differ from {job.source.what}. The pedal restarts "
            f"into its firmware. Backup: {backup}")


# ---------------------------------------------------------------- what to write, and what the pedal held
def official_images(package=None, image=None):
    """{file name: flash image} to try: the file given, else M-VAVE's files found in the firmware folder."""
    if package or image:
        return {Path(package or image).name: ur.load_image(package, image)}
    return {n: ur.load_image(FIRMWARE / n) for n in OFFICIAL if (FIRMWARE / n).exists()}


def gamut_source(path=None):
    if not ui.GAMUT_PIN.exists():
        raise RescueError("Gamut's file is not in this folder: the rescue kit holds only M-VAVE's way back. Install "
                          "Gamut from the Undertone repository after `node tools/op.mjs package`, or from the "
                          f"installer page when the pedal starts ({GUIDE}#gamut-on-a-blackbox-with-v22-or-v23)")
    return ui.gamut_area(path)


@dataclass
class Reading:
    """What a backup says about the pedal, in words."""
    family: str                                # the firmware generation its head belongs to
    path: str                                  # "A", "B" or "C", as in docs/RESCUE.md
    layout: str                                # the flash layout, or None
    app: str                                   # what its app area would start


def read_pedal(flash):
    _, family, action = hf.describe(flash)
    path = action[5] if action.startswith("Path ") else "C"
    try:
        layout = ui.layout_of(flash, "the pedal's")
    except GuardError:
        layout = None
    app = None
    if layout:
        try:
            identity = pi.check_area(flash[layout.base:layout.limit], layout.base, layout.limit)
            app = f"an Undertone app ({identity})" if identity else "M-VAVE's own firmware"
        except GuardError as e:
            app = f"nothing that starts ({e})"
    return Reading(family, path, layout.name if layout else None, app)


# ---------------------------------------------------------------- the commands
class Out:
    """Plain lines with a calm header; bold and the lamp only on a terminal that takes colour."""

    def __init__(self, stream=None):
        self.s = stream or sys.stdout
        self.rich = self.s.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"
        self.t0 = time.monotonic()

    def line(self, text=""):
        print(text, file=self.s, flush=True)

    def strong(self, text):
        self.line(f"\x1b[1m{text}\x1b[0m" if self.rich else text)

    def header(self, what):
        lamp = "\x1b[38;2;196;245;66m●\x1b[0m " if self.rich else ""
        self.line()
        self.strong(f"{lamp}undertone · {what}" if self.rich else f"undertone - {what}")
        self.line(f"rescue kit {version()}")
        self.line()

    def log(self, m):
        if m == "pedal found":
            self.t0 = time.monotonic()
        self.line(f"[{time.monotonic() - self.t0:6.1f}s] {m}")


def confirm(out, question, reader=input):
    """True only when the person types yes."""
    out.line()
    try:
        answer = reader(f"{question} Type yes to go on, anything else to stop: ")
    except EOFError:
        answer = ""
    return answer.strip().lower() == "yes"


def allowed(out, argv):
    problem = permission_problem()
    if problem is None:
        return True
    if not ur.WINDOWS and sys.stdin.isatty() and sys.stdout.isatty():
        out.line("This needs your computer password: the system keeps the pedal's USB disk for itself, and only an "
                 "administrator may take it. Nothing shows while you type.")
        as_root(argv)
    out.line(f"ERROR: {problem}")
    return False


def finished(out, o):
    if o.code:
        out.line()
        out.strong(o.text)
        if o.backup:
            out.line(f"Backup: {o.backup}")
    return o.code


def cmd_rescue(a, out, reader=input):
    out.header("rescue a pedal that will not start")
    try:
        images = official_images(a.package, a.image)
    except RescueError as e:
        return finished(out, Outcome(1, f"ERROR: {e}"))
    out.line("Step 1 of 2: a read-only check. It saves a backup of the whole pedal and writes nothing.")
    out.line("Unplug the pedal. When this says it is waiting, plug it straight into this computer, with no hub.")
    out.line()
    o = run(Job("rescue", images=images, opts=a.opts), out.log)
    if o.code:
        finished(out, o)
        if o.code == 2 and o.flash is not None:
            advise(out, o, images)
        return o.code
    out.line()
    out.line(o.text)
    if not images:
        return advise(out, o, images)
    file = o.file
    out.line()
    out.strong(f"The pedal matches {file}. The restore puts M-VAVE's official {ENDS_ON.get(file, file)} back.")
    if not confirm(out, "Step 2 writes the pedal's app area.", reader):
        out.line(f"Stopped. Nothing was written. Backup: {o.backup}")
        return NOT_CONFIRMED
    out.line()
    out.line("Step 2 of 2: the restore. Unplug the pedal and plug it in again when this says it is waiting. Do not "
             "touch the cable while it writes.")
    out.line()
    o = run(Job("rescue", True, {file: images[file]}, opts=a.opts), out.log)
    if o.code:
        return finished(out, o)
    out.line()
    out.strong(o.text)
    out.line("Next: unplug the cable, switch the pedal off, wait 5 seconds and switch it on.")
    if file != PATH_FILE["A"]:
        out.line("Do not install Gamut on this pedal from an installer page: it would go dark again. Use "
                 "`undertone install` (the guide's section \"Gamut on a BlackBox with V22 or V23\").")
    return 0


def advise(out, o, images):
    """After a refusal or a run with no file: which file the pedal needs, from its head."""
    r = read_pedal(o.flash)
    out.line()
    out.line(f"The pedal had {r.family}.")
    need = PATH_FILE.get(r.path)
    if need and need not in images and not (r.path == "B" and "BlackBox_022.fwsc" in images):
        out.strong(f"Next: put M-VAVE's {need} in the firmware folder ({FIRMWARE}) and run undertone rescue again. "
                   f"firmware/README.txt says where to get it.")
        return 1
    if r.path == "C":
        out.strong("Next: stop here. No official file fits this pedal; do not try others. Keep the backup and ask for "
                   f"help with the guide: {GUIDE}#if-it-does-not-work")
        return 2
    return 1


def install_source(a):
    if a.official:
        return ui.official_area(a.official)
    if a.restore:
        return ui.backup_area(a.restore)
    return gamut_source(a.gamut)


def cmd_install(a, out, reader=input):
    out.header("put Gamut on a pedal")
    try:
        source = install_source(a)
    except GuardError as e:
        return finished(out, Outcome(2, f"REFUSED: {e}"))
    except RescueError as e:
        return finished(out, Outcome(1, f"ERROR: {e}"))
    out.line(f"Step 1 of 2: a dry run with {source.what}. It saves a backup and writes nothing.")
    out.line(KEY_HOLD)
    out.line()
    o = run(Job("install", source=source, opts=a.opts), out.log, lambda m: out.line(m))
    if o.code:
        return finished(out, o)
    out.line()
    out.line(o.text)
    if not confirm(out, f"Step 2 writes {source.what} to the pedal's app area.", reader):
        out.line(f"Stopped. Nothing was written. Backup: {o.backup}")
        return NOT_CONFIRMED
    out.line()
    out.line("Step 2 of 2: the write. " + KEY_HOLD + " Do not touch the cable while it writes.")
    out.line()
    o = run(Job("install", True, source=source, opts=a.opts), out.log, lambda m: out.line(m))
    if o.code:
        return finished(out, o)
    out.line()
    out.strong(o.text)
    out.line(ui.FIRST_RUN.format(levels=o.layout.levels) if source.boot is None else "Next: power-cycle the pedal.")
    return 0


KEY_HOLD = ("When this says it is waiting: on a BlackBox with M-VAVE's V22 or V23 head, switch it off, hold HOME, the "
            "right footswitch and the knob's PUSH, switch it on and keep holding until the screen shows RECOVERY. A "
            "pedal already in the chip's USB boot state is taken as it is.")


def cmd_check(a, out, reader=input):
    out.header("check a pedal")
    out.line("A read-only check: it finds the pedal, saves a backup of the whole pedal and writes nothing.")
    out.line(KEY_HOLD if not ur.WINDOWS else "Plug the pedal straight into this computer, with no hub.")
    out.line()
    o = run(Job("check", opts=a.opts), out.log, lambda m: out.line(m))
    if o.code:
        return finished(out, o)
    r = read_pedal(o.flash)
    out.line()
    out.line(f"found in:  {'M-VAVE recovery mode, then the chip USB boot state' if o.found_in else 'the chip USB boot state'}")
    out.line(f"head:      {r.family}")
    out.line(f"layout:    {r.layout or 'not one undertone knows'}")
    out.line(f"app area:  {r.app or 'unknown'}")
    out.line(f"backup:    {o.backup}")
    out.line()
    out.strong({"A": "To restore it: undertone rescue, with BlackBox_020.fwsc in the firmware folder.",
                "B": "To restore it: undertone rescue, with BlackBox_023.fwsc in the firmware folder."}.get(
        r.path, "No official file of this kit fits this pedal. Keep the backup and ask for help with the guide."))
    return 0


def parser():
    ap = argparse.ArgumentParser(prog="undertone", description="Rescue, install or check a BlackBox over USB. Without "
                                 "a command: the guided screens.", epilog=f"The guide: {GUIDE}")
    ap.add_argument("--version", action="store_true", help="print the version and exit")
    ap.add_argument("--start", choices=("rescue", "install", "check"), help=argparse.SUPPRESS)  # after sudo
    sub = ap.add_subparsers(dest="command", metavar="COMMAND")

    def common(p):
        p.add_argument("--loader", help="wl82loader.bin (default: downloaded once and checked)")
        p.add_argument("--backup-dir", default=str(ur.DEFAULT_BACKUPS), help="where backups go (default ~/OpenPocket-rescue)")
        p.add_argument("--attempts", type=int, default=10, help="USB boot state windows to try (default 10)")

    p = sub.add_parser("rescue", help="restore M-VAVE's firmware on a pedal that will not start: a check, then the restore")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--package", help="M-VAVE's official .fwsc (default: the matching file in the firmware folder)")
    src.add_argument("--image", help="a raw flash image (flash.bin) instead of a package")
    common(p)
    p = sub.add_parser("install", help="put Gamut, M-VAVE's firmware or a backup on a pedal: a dry run, then the write")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--gamut", metavar="FILE", help="Gamut's app area (default: the file the release pin names)")
    src.add_argument("--official", metavar="FILE.fwsc", help="M-VAVE's official package: its app area, the way back")
    src.add_argument("--restore", metavar="DUMP.bin", help="a whole-flash backup of this pedal: its app area")
    common(p)
    common(sub.add_parser("check", help="read-only: how the pedal was found, what it had; saves a backup"))
    sub.add_parser("version", help="print the version")
    return ap


COMMANDS = {"rescue": cmd_rescue, "install": cmd_install, "check": cmd_check}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    a = parser().parse_args(argv)
    if a.version or a.command == "version":
        print(f"undertone, rescue kit {version()}")
        return 0
    if a.command is None:
        import undertone_screens
        return undertone_screens.main(argv, a.start or "menu")
    out = Out()
    if not allowed(out, argv):
        return 1
    a.opts = Options(a.loader, a.backup_dir, a.attempts)
    try:
        return COMMANDS[a.command](a, out)
    except KeyboardInterrupt:
        out.line("\nstopped; rerunning resumes where it stopped")
        return 130


if __name__ == "__main__":
    sys.exit(main())
