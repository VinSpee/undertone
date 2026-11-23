#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""uboot_install.py - install Gamut on a BlackBox, or put M-VAVE's firmware or a saved backup back, through the chip's
USB boot state. One command for both flash layouts; it never writes a boot loader.

The chip's ROM has a USB boot state (USB 4C4A:8057) in which tools/uboot_rescue.py reads and writes the flash. This
tool uses the same code, with a plan of its own: it reads the pedal's flash, names its layout by the CRC-32 of its boot
area, composes the image from the pedal's own boot area and the app area it was given, and writes only the sectors of
that app area that differ. docs/RESCUE.md, "Gamut on a BlackBox with V22 or V23", has the steps.

  sudo tools/uboot_install.py                              dry run with Gamut: everything below but the write
  sudo tools/uboot_install.py --write                      install Gamut
  sudo tools/uboot_install.py --official FILE.fwsc [--write]     put M-VAVE's app area back from its official package
  sudo tools/uboot_install.py --restore DUMP.bin [--write]       put back the app area of a backup of this pedal
  options: --gamut FILE (default: the file the release pin names, build/apps/gamut/BlackBox_950-v23.bin)
           --loader FILE  --backup-dir DIR (default ~/OpenPocket-rescue)  --attempts N (default 10)

The two layouts, and the only ones accepted:
  the old head (M-VAVE V16, V17 and V20)   boot area [0, 0x4000), CRC-32 0x5A2121FF; app area in [0x4000, 0xA5000)
  M-VAVE's V22/V23 head                    boot area [0, 0x6000), CRC-32 0xB19D96A1; app area in [0x6000, 0x9F000)
Gamut's app area is the same bytes on both; it goes where the pedal's layout puts it. An official package and a backup
carry their own boot area, which must be the pedal's, byte for byte: the V20 file on a V22/V23 pedal would overwrite
the end of its boot loader, and the pedal would no longer switch on.

Start it first; it waits and sends nothing until the pedal shows up in one of two ways:
  - in the chip's USB boot state: a pedal on the old head that restarts in a loop, or one that Gamut's or the official
    V21's soft key sent there (the installer page's buttons). The tool starts at once.
  - in M-VAVE's recovery mode (USB 3654:7940; V22 and V23 only: power off, hold HOME, the right footswitch and the
    knob's PUSH, power on, hold until the screen shows RECOVERY). The tool sends one hello and the single leave command
    (tools/pd40_recovery.py's, with its checks), and takes the USB boot state the moment the pedal comes back in it. The
    recovery mode ends about 4 s after power-on, and the USB boot state lasts only seconds while nothing talks to it:
    that is why the tool must be waiting before the pedal is switched on.

Steps of a run (a rerun, or the next try of the same run, resumes: only the sectors that still differ are written):
  1 the checks of the app area, before anything is opened
  2 wait as above; from the recovery mode, the hello (the boot area's CRC-32 must be a known one) and the leave
  3 the loader into RAM, the chip key (0x980F) and the flash id (EB 60 14 or 85 60 14, a 1 MiB flash)
  4 back up the whole flash to a file, before anything is written
  5 name the layout by the boot area's CRC-32; refuse an unknown head, and an app area for another layout
  6 compose the image: the pedal's own boot area, then the app area; compare
  7 --write only: for each 4 KiB sector of the app area that differs: erase, write, read back, compare
  8 run-app: the pedal restarts into its firmware
Guards that cannot be switched off: no write below the app area's start or from the layout's limit up, so never a boot
loader, the radio records, the user area or key_mac, nor the stock settings of V20, V22 and V23 (those of V16 start at
0xA3000, inside the old head's range: a V20 package or a backup puts its own bytes there); Gamut's area must be the
release pin's, an official package must pass every CRC and be a BlackBox one; a backup must be a whole 1 MiB dump whose
app area the boot loader would start; and uboot_rescue's own: the loader's command whitelist, the chip key, the flash
size.

One-time install (macOS): `brew install libusb`. macOS keeps its mass-storage driver on the USB boot state, so the tool
needs sudo. Linux has not been tried; Windows is not supported (RESCUE.bat restores the official firmware there).
Exit codes: 0 done, 1 setup problem or a failed transfer, 2 refused by a check (nothing more is sent), 3 the pedal left
after the leave but the USB boot state did not appear, 5 the pedal stayed in the recovery mode after the leave,
130 stopped by Ctrl-C.
"""
import argparse, hashlib, re, struct, sys, time, zlib
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pocketx_fw as fw
import pd40_install as pi
import pd40_recovery as pr
import uboot_rescue as ur
from uboot_rescue import GuardError, RescueError, ScsiError, Window

GAMUT_PIN = ur.ROOT / "firmware" / "apps" / "gamut" / "release.sha256"
FLASH_IDS = frozenset({0xEB6014, 0x856014})    # seen on a real pedal; the other one the V22/V23 boot loader accepts
LEAVE_WAIT = 10.0                              # s for the USB boot state after the leave; it took about 0.8 s


@dataclass(frozen=True)
class Layout:
    name: str                                  # in words
    base: int                                  # the app area starts here; [0, base) is the boot area, never written
    limit: int                                 # nothing from here up is written: its newest firmware's stock settings
    boot_crc: int                              # CRC-32 of the boot area
    levels: str                                # the supply levels Gamut finds, as its boot screen shows them


LAYOUTS = (Layout("the old head (M-VAVE V16, V17 and V20)", 0x4000, 0xA5000, 0x5A2121FF, "3 11"),
           Layout("M-VAVE's V22/V23 head", 0x6000, 0x9F000, pi.KNOWN_HEAD, "7 15"))


@dataclass(frozen=True)
class Source:
    """The app area to write. boot: the boot area the pedal must hold, byte for byte, when the area belongs to one
    (an official package's, a backup's); None for Gamut's area, which is the same on every known layout."""
    what: str
    area: bytes
    boot: bytes = None


class Stopped(RescueError):
    """The leave did not bring the USB boot state. code is the exit code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def layout_of(flash, whose):
    """The layout of a flash image that starts at 0, by its boot area's CRC-32. GuardError for any other head."""
    for layout in LAYOUTS:
        if zlib.crc32(flash[:layout.base]) == layout.boot_crc:
            return layout
    seen = ", ".join(f"[0, {l.base:#x}) {zlib.crc32(flash[:l.base]):#010x}" for l in LAYOUTS)
    known = "; ".join(f"{l.name}, {l.boot_crc:#010x}" for l in LAYOUTS)
    raise GuardError(f"{whose} boot area is not one this tool knows (CRC-32 of {seen}; known: {known}). An app area "
                     "written to the wrong place overwrites a boot loader, so nothing is written to another head")


def read(path):
    try:
        return Path(path).read_bytes()
    except OSError as e:
        raise RescueError(f"cannot read {path}: {e.strerror}")


def gamut_pin():
    """(the file, its SHA-256) of Gamut's app area in the release pin."""
    for line in GAMUT_PIN.read_text().splitlines():
        digest, _, name = line.partition("  ")
        if name.endswith("-v23.bin"):
            return ur.ROOT / name, digest
    raise RescueError(f"{GAMUT_PIN} names no app area (*-v23.bin)")


def gamut_area(path=None):
    """Gamut's app area: the bytes of the release pin, and no other build."""
    pinned, digest = gamut_pin()
    path = Path(path) if path else pinned
    if not path.exists():
        raise RescueError(f"{path} not found: build Gamut first (node tools/op.mjs package), or pass --gamut FILE")
    area = read(path)
    if hashlib.sha256(area).hexdigest() != digest:
        raise GuardError(f"{path.name} is not the Gamut app area of the release pin (SHA-256 {digest}, in "
                         f"{GAMUT_PIN}): only the pinned release is installed this way")
    room = min(l.limit - l.base for l in LAYOUTS)
    identity = pi.check_area(area, 0, room)
    return Source(f"Gamut's app area {path.name}, identity {identity}", area)


def flash_source(image, what, whose):
    """The app area of a flash image that carries its own boot area: an official flash.bin, or a backup."""
    layout = layout_of(image, whose)
    area = image[layout.base:layout.limit]
    try:
        pi.check_area(area, layout.base, layout.limit)
    except GuardError as e:
        raise GuardError(f"{whose} app area at {layout.base:#x} is not one the boot loader would start: {e}")
    return Source(f"{what}, for {layout.name}", area, image[:layout.base])


def official_area(path):
    """M-VAVE's app area from its official BlackBox package, every CRC of the package checked first."""
    name = Path(path).name
    try:
        _, L, tag, u = fw.load(path)
        bad = [k for k, v in fw.package_checks(L, u).items() if not v]
    except OSError as e:
        raise RescueError(f"cannot read {path}: {e.strerror}")
    except (ValueError, IndexError, struct.error, UnicodeDecodeError) as e:
        raise GuardError(f"{name}: not a readable package ({e})")
    if bad:
        raise GuardError(f"{name}: the package is damaged ({', '.join(bad)})")
    m = re.fullmatch(r"BlackBox_(\d+)", tag)
    if not m or int(m[1]) >= 900:
        raise GuardError(f"{name} (identity {tag!r}) is not one of M-VAVE's official BlackBox packages")
    flash = next(L[e["off"]:e["off"] + e["len"]] for e in u["ents"] if e["name"] == "flash.bin")
    return flash_source(flash, f"M-VAVE's app area from {name} ({tag})", f"{name}: its")


def backup_area(path):
    """The app area of a whole-flash backup (blackbox-<time>.dump.bin) that this tool or uboot_rescue.py saved."""
    name = Path(path).name
    dump = read(path)
    if len(dump) != ur.FLASH_SIZE:
        raise GuardError(f"{name} is {len(dump)} bytes, not a backup of the whole 1 MiB flash")
    return flash_source(dump, f"the app area of the backup {name}", f"{name}: its")


def plan_for(source, log, seen):
    """uboot_rescue's plan for this source: once the pedal's flash is read, the image it should hold and the only window
    that may be written, or GuardError. seen collects the pedal's layout for the last message."""
    def plan(chip, flash):
        if chip.flash_id not in FLASH_IDS:
            raise GuardError(f"flash id {chip.flash_id:#08x} is not one this tool knows ("
                             + ", ".join(f"{i:#08x}" for i in sorted(FLASH_IDS)) + "): nothing was written")
        layout = layout_of(flash, "the pedal's")
        log(f"boot area [0, {layout.base:#x}) CRC-32 {layout.boot_crc:#010x}: {layout.name}; its app area is in "
            f"[{layout.base:#x}, {layout.limit:#x})")
        seen.append(layout)
        if source.boot is not None and source.boot != flash[:layout.base]:
            raise GuardError(f"{source.what}: its boot area is not this pedal's, which has {layout.name}. Written "
                             "here it would not start, or would overwrite the end of the boot loader; nothing was "
                             "written")
        end = layout.base + len(source.area)
        if end > layout.limit:
            raise GuardError(f"{source.what} would end at {end:#x}, past {layout.limit:#x}; nothing was written")
        log(f"image: the pedal's own boot area, then {source.what} in [{layout.base:#x}, {end:#x})")
        return flash[:layout.base] + source.area, Window(layout.base, end)
    return plan


WAITING = """\
waiting for the pedal; nothing is sent until it appears. Either:
  - a BlackBox on M-VAVE's V22 or V23 head: switch it off, hold HOME, the right footswitch and the knob's PUSH, switch
    it on and keep holding until the screen shows RECOVERY (USB 3654:7940). The tool then sends the leave by itself
  - a pedal already in the chip's USB boot state (USB 4C4A:8057): it is taken as it is
Plug it straight into this computer, with no hub."""


def leave(bus, say):
    """From M-VAVE's recovery mode to the chip's USB boot state: the hello, the single leave, then the USB boot device
    taken the moment it appears. Returns it claimed, or None when the recovery mode ended before the leave was sent.
    say prints a line as tools/pd40_recovery.py does, with its time in milliseconds since the device was found."""
    dev = bus.open_recovery()
    if dev is None:
        return None
    found = bus.now()
    stamped = lambda m: say(f"[{(bus.now() - found) * 1000:6.0f} ms] {m}")
    session = pr.Recovery(dev, stamped, bus.now)
    try:
        stamped(f"found {pr.VID:04X}:{pr.PID:04X} {dev.manufacturer!r} {dev.product!r}: M-VAVE's recovery mode")
        try:
            hello, bulk = session.probe()
            pr.describe(hello, bulk, stamped)
            if not any((l.boot_crc, l.base, l.limit) == (hello.boot_crc, hello.base, hello.limit) for l in LAYOUTS):
                raise GuardError(f"the pedal's boot area CRC-32 {hello.boot_crc:#010x} is not a head this tool knows: "
                                 "the leave is not sent, and the pedal restarts by itself")
            if bulk is not None:
                stamped("the hello reply came over the control endpoint only, as on the one real pedal tried, which "
                        "acted on the leave all the same")
            session.leave(hello)
        except ScsiError as e:
            if not pr.left_bus(bus, e):
                raise
            if session.sent is None or session.sent[0] != pr.LEAVE:
                stamped(f"the pedal left the bus ({e}), {session.since(bus.now())}: the recovery mode ended before the "
                        "leave was sent. It ends about 4 s after power-on. Enter it again; this tool is still waiting")
                return None
    finally:
        dev.close()
    sent = session.sent[2]
    stamped("leave sent: waiting for the chip's USB boot state (USB 4C4A:8057)")
    while bus.now() - sent < LEAVE_WAIT:
        msc = bus.open_uboot()
        if msc:
            stamped(f"the chip's USB boot state appeared {(bus.now() - sent) * 1000:.0f} ms after the leave")
            return msc
        bus.sleep(bus.POLL)
    if pr.RECOVERY in bus.present():
        raise Stopped(5, f"the pedal stayed in the recovery mode for {LEAVE_WAIT:g} s after the leave: it did not act on "
                         "it. Nothing was written; send this output back")
    raise Stopped(3, f"the chip's USB boot state did not appear within {LEAVE_WAIT:g} s of the leave. Nothing was "
                     "written. If RECOVERY had been on the screen for some seconds, the pedal's own reset came first: "
                     "run this again and enter the recovery mode only once it is waiting. If the pedal restarts into "
                     "its firmware every time, send this output back")


def boot_state(bus, log, say):
    """The pedal in the chip's USB boot state, claimed. Waits for it, or for M-VAVE's recovery mode, and sends nothing
    until one of them is on the bus. log prints with uboot_rescue's time stamp, say with the recovery session's."""
    told = False
    while True:
        msc = bus.open_uboot()
        if msc is None and pr.RECOVERY in bus.present():
            msc, told = leave(bus, say), False
        if msc:
            return msc
        if not told:
            log(WAITING)
            told = True
        bus.sleep(bus.POLL)


class LibusbBus(pr.LibusbBus):
    POLL = ur.Libusb.POLL

    def open_uboot(self):
        """The pedal in the chip's USB boot state, claimed as tools/uboot_rescue.py claims it, or None."""
        return self.usb.open_pedal()


def transport():
    if ur.WINDOWS:
        raise RescueError("this tool does not run on Windows: M-VAVE's recovery mode has not been tried there. "
                          "RESCUE.bat restores the official firmware (docs/RESCUE.md)")
    if sys.platform == "darwin" and not ur.as_root():
        raise RescueError(ur.SUDO_HINT)
    return LibusbBus()


FIRST_RUN = """\
First-run check (docs/RESCUE.md): power-cycle the pedal. The boot screen's line PWR shows the supply levels the boot
loader left; on this pedal it should read `PWR {levels} (BOOT LEVELS)`. Then, with the pedal on USB:
    node tools/op.mjs dsp 2>&1 | tee gamut-dsp.log
It plays every saved preset for 6 s and reads the load, the peak, the late blocks and the bypass; exit 0 means no
preset was late or bypassed. Play through each preset and listen for crackles."""


def main(argv=None):
    ap = argparse.ArgumentParser(description="Install Gamut on a BlackBox, or put M-VAVE's firmware or a backup back, "
                                             "through the chip's USB boot state. Dry run unless --write is given.")
    ap.add_argument("--write", action="store_true", help="really write the app area (default: a dry run that reads, "
                                                         "backs up, composes and compares)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--gamut", metavar="FILE", help="Gamut's app area (default: the file the release pin names)")
    src.add_argument("--official", metavar="FILE.fwsc", help="M-VAVE's official BlackBox package: its app area, the way back")
    src.add_argument("--restore", metavar="DUMP.bin", help="a whole-flash backup of this pedal: its app area")
    ap.add_argument("--loader", help="wl82loader.bin (default: download once into build/cache/)")
    ap.add_argument("--backup-dir", default=str(ur.DEFAULT_BACKUPS), help="where the flash backup goes (default ~/OpenPocket-rescue)")
    ap.add_argument("--attempts", type=int, default=10, help="tries at the USB boot state before giving up (default 10)")
    a = ap.parse_args(argv)

    t0 = [time.monotonic()]
    log = lambda m: print(f"[{time.monotonic() - t0[0]:6.1f}s] {m}", flush=True)
    seen = []
    try:
        source = (official_area(a.official) if a.official else backup_area(a.restore) if a.restore
                  else gamut_area(a.gamut))
        loader = ur.get_loader(a.loader)
        log(f"{source.what}: {len(source.area):#x} bytes, CRC-32 {zlib.crc32(source.area):#010x}, every check passed; "
            + ("WRITE mode" if a.write else "dry run: nothing will be written"))
        bus = transport()

        def open_device():
            msc = boot_state(bus, log, lambda m: print(m, flush=True))
            t0[0] = time.monotonic()
            log("pedal found in the chip's USB boot state")
            return msc

        n, saved = ur.rescue(open_device, loader, plan_for(source, log, seen), a.write,
                             Path(a.backup_dir).expanduser(), a.attempts, log)
    except GuardError as e:
        print(f"\nREFUSED: {e}", file=sys.stderr)
        return 2
    except Stopped as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return e.code
    except RescueError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    except ScsiError as e:
        print(f"\nERROR: the pedal stopped answering in its recovery mode ({e}); nothing was written", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nstopped; rerunning resumes where it stopped", file=sys.stderr)
        return 130
    if not a.write:
        print(f"\nDry run finished, nothing was written. {n} sectors differ from {source.what}. The pedal restarts into "
              f"its firmware. Backup: {saved[0]}\nTo write: the same command with --write.")
        return 0
    print(f"\nDone: {n} sectors written and verified, on {seen[-1].name}. Backup: {saved[0]}")
    if source.boot is None:
        print(FIRST_RUN.format(levels=seen[-1].levels))
    else:
        print("Power-cycle the pedal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
