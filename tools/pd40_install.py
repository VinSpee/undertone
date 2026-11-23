#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""pd40_install.py - write an app area to a BlackBox with M-VAVE's V22 or V23 boot loader, through its recovery mode.

On such a pedal the app area starts at 0x6000, and the boot loader starts it after four CRC16 checks only: the flash
header, the head's entries up to app_dir_head, and the first 32 bytes at 0x6000 under the chip key 0x980F. Its recovery
mode (the screen shows RECOVERY, USB 3654:7940 "PD40 BOOT Recovery"; hold HOME, the right footswitch and the knob's PUSH
at power-on) takes an image for [0x6000, 0x9F000) and never writes the head [0, 0x6000) nor anything from 0x9F000 up.
This tool installs Gamut that way, and puts M-VAVE's own app area back from the official V22 or V23 package, which is
the way back. docs/RESCUE.md, "Gamut on a BlackBox with V22 or V23", has the steps.

  tools/pd40_install.py IMAGE              dry run (the default): checks IMAGE and prints every frame the install would
                                           send, in order. Opens no USB device
  tools/pd40_install.py IMAGE --verify     the recovery mode's own first pass: the pedal checks the manifest, every block
                                           and the whole image against its own head, and writes nothing
  tools/pd40_install.py IMAGE --write      the install: the first pass, then the erase, the second pass that writes,
                                           the commit (block 0, the area head, last) and the start of the new app

IMAGE is one of:
  build/apps/gamut/BlackBox_950-v23.bin    Gamut's app area (node tools/op.mjs package)
  build/apps/gamut/BlackBox_950.fwsc       the same area, read from Gamut's BlackBox package
  BlackBox_023.fwsc or BlackBox_022.fwsc   M-VAVE's official package: its app area [0x6000, 0x9F000), the way back. Its
                                           head must be the pedal's: the hello names the CRC-32 of the pedal's [0, 0x6000)

The protocol, read in the V23 boot loader's code (frames of 4608 bytes from "SBU2", 64-byte replies from "SBR2", CRC-32
as zlib's): 1 hello; 2 the manifest ("SKR2", the protocol's constants, the write range, the image's length and CRC-32,
the CRC-32 of the pedal's [0, 0x6000), the entry 0x02000120, the block count, a CRC-32 over these and the table, then one
CRC-32 per 4 KiB block); 3 a block, in order: in state 1 only checked, in state 3 erased, programmed and read back,
block 0 kept in RAM; 4 with argument 2 the erase of the sector at 0x6000 (from here the pedal starts no app until the
commit), with argument 4 the commit, which checks the whole image, writes block 0 and checks again; 5 the start of the
new app. Every frame and reply is printed with its time in milliseconds from the moment the device was found, as
tools/pd40_recovery.py prints them.

Before anything is erased the tool requires: a hello answered over the bulk IN endpoint in state 0, a pedal head this
tool knows (the official V22/V23 head), and the pedal's own first pass completed (state 2). It refuses an image that is
not a whole number of 4 KiB blocks, longer than the write range, whose area head fails its CRC under the chip key, whose
entry is not 0x02000120, whose files fail their CRCs, a Pocket X image, and an official package for another head.

One-time install (macOS): `brew install libusb`; no sudo. Exit codes: 0 done (the dry run printed, the pedal's check
passed, or the new app appeared), 1 setup problem, no recovery device or a failed transfer, 2 refused or a bad answer,
3 the install finished but the new app did not appear, 4 the pedal left the recovery mode on its own, 130 Ctrl-C.
"""
import argparse, ctypes, re, struct, sys, zlib
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pocketx_fw as fw
import pd40_recovery as pr
from pd40_recovery import BadAnswer, GuardError, RescueError, ScsiError
import uboot_rescue as ur

BLOCK, FLASH_SIZE, ENTRY = 4096, 0x100000, 0x02000120
CONSTANTS, VERSION = 0x07910040, 0x00020000
BASE, LIMIT = pr.PROTOCOL[2], pr.PROTOCOL[3]   # the write range [0x6000, 0x9F000) every reply carries
MAX_BLOCKS = (LIMIT - BASE) // BLOCK           # 153
HELLO, MANIFEST, BLOCK_CMD, COMMIT, START_APP = pr.HELLO, pr.MANIFEST, pr.BLOCK, pr.COMMIT, pr.START_APP
ERASE_ARG, COMMIT_ARG = 2, 4                   # command 4's two arguments
NAMES = {HELLO: "hello", MANIFEST: "manifest", BLOCK_CMD: "block", COMMIT: "erase or commit", START_APP: "start the app"}
GAMUT = (0x1209, 0x0001)                       # the USB device of Gamut and of every firmware of this project
WATCHED = {**pr.WATCHED, GAMUT: "Gamut (or another firmware of this project)"}
KNOWN_HEAD = next(iter(pr.HEADS))              # 0xB19D96A1, the official V22 and V23 head
READ_MS = 1000                                 # a reply that only checks
WRITE_MS = 5000                                # a block in the second pass, the erase: a sector erased and programmed
COMMIT_MS = 15000                              # the whole image read twice and block 0 written


@dataclass(frozen=True)
class Image:
    area: bytes                                # the bytes for [0x6000, 0x6000 + len)
    what: str                                  # in words, for the log
    head_crc: int                              # the CRC-32 of the [0, 0x6000) it needs on the pedal; None: any known head
    expect: tuple                              # the USB device the new app is

    @property
    def blocks(self):
        return len(self.area) // BLOCK


def check_area(area):
    """The checks of an app area on its own (offsets from its start), as the boot loader and pocketx_fw read it.
    Returns the identity in its OP-PRODUCT field, or None. Raises GuardError with the first failure."""
    if not area or len(area) % BLOCK:
        raise GuardError(f"the image is {len(area)} bytes, not a whole number of 4 KiB blocks")
    if len(area) > LIMIT - BASE:
        raise GuardError(f"the image is {len(area):#x} bytes, longer than the write range [{BASE:#x}, {LIMIT:#x})")
    dec = fw.sfc(area, 0)
    head = fw.jlfs_entry(dec, 0)
    if not head["hdr_ok"] or head["name"] != "app_area_head":
        raise GuardError("its first 32 bytes are not an app area head under the chip key 0x980F: the boot loader "
                         "would not start it")
    if head["addr"] != ENTRY:
        raise GuardError(f"its entry is {head['addr']:#x}, not {ENTRY:#x}")
    if head["len"] > len(area) or fw.crc16(dec[0x20:head["len"]]) != head["dcrc"]:
        raise GuardError("its area head's data CRC fails")
    ents, o = [head], 0x20
    while o < 0x120:
        e = fw.jlfs_entry(dec, o)
        if not e["name"] or not e["name"].isprintable():
            break
        ents.append(e)
        o += 32
    for e in fw.area_files(ents):
        if not e["hdr_ok"] or e["addr"] + e["len"] > len(area) or fw.crc16(dec[e["addr"]:e["addr"] + e["len"]]) != e["dcrc"]:
            raise GuardError(f"its file {e['name']} fails its CRC")
    m = re.search(rb"OP-PRODUCT:([A-Za-z]+_\d+)", dec)
    return m[1].decode() if m else None


def load_image(path):
    """IMAGE as an Image, every check passed; GuardError otherwise."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as e:
        raise RescueError(f"{path}: {e.strerror}")
    if path.suffix.lower() != ".fwsc":
        identity = check_area(data)
        if not identity or not identity.startswith("BlackBox_"):
            raise GuardError(f"{path.name} holds {'the identity ' + identity if identity else 'no OpenPocket identity'}: "
                             "an image file must be a BlackBox app area this project built (*-v23.bin). For M-VAVE's "
                             "firmware give its .fwsc package, so that its head can be compared with the pedal's")
        return Image(data, f"the app area {path.name}, identity {identity}", None, GAMUT)
    try:
        _, L, tag, u = fw.load(path)
        bad = [k for k, v in fw.package_checks(L, u).items() if not v]
    except (ValueError, IndexError, struct.error, UnicodeDecodeError) as e:
        raise GuardError(f"{path.name}: not a readable package ({e})")
    if bad:
        raise GuardError(f"{path.name}: the package is damaged ({', '.join(bad)})")
    m = re.fullmatch(r"(PocketX|BlackBox)_(\d+)", tag)
    if not m:
        raise GuardError(f"{path.name}: not a Pocket X or BlackBox package (identity {tag!r})")
    if m[1] != "BlackBox":
        raise GuardError(f"{path.name} is a Pocket X package: the recovery mode is the BlackBox V22/V23 boot loader's")
    flash = next(L[e["off"]:e["off"] + e["len"]] for e in u["ents"] if e["name"] == "flash.bin")
    base = fw.app_base(flash)
    if int(m[2]) >= 900:                       # this project's: its area, whatever head the package carries
        area = flash[base:]
        identity = check_area(area)
        if identity != tag:
            raise GuardError(f"{path.name}: its app says it is {identity}, the package says {tag}")
        return Image(area, f"the app area of {path.name}, identity {tag}", None, GAMUT)
    if base != BASE:
        raise GuardError(f"{path.name} ({tag}) puts its app area at {base:#x}: it is a package for the old head, and "
                         "only M-VAVE's V22 and V23 packages, made for this boot loader, can be put back through the "
                         "recovery mode")
    area = flash[BASE:]
    check_area(area)
    return Image(area, f"M-VAVE's app area from {path.name} ({tag})", zlib.crc32(flash[:BASE]), pr.APP)


def manifest(image, boot_crc, word=0):
    """Command 2's payload: 64 bytes of header (its CRC-32 over bytes 0..59 and the table), then the table."""
    table = b"".join(struct.pack("<I", zlib.crc32(image.area[i:i + BLOCK])) for i in range(0, len(image.area), BLOCK))
    head = struct.pack("<4s14I", b"SKR2", VERSION, CONSTANTS, FLASH_SIZE, BASE, LIMIT, len(image.area),
                       zlib.crc32(image.area), boot_crc, ENTRY, image.blocks, word, 0, 0, 0)
    return head + struct.pack("<I", zlib.crc32(head + table)) + table


def frame(command, tag, arg=0, payload=b""):
    """A 4608-byte frame: "SBU2", command, tag, argument, the payload's length and CRC-32, the payload."""
    if command not in NAMES or len(payload) > BLOCK:
        raise GuardError(f"command {command} with {len(payload)} bytes is not a frame of the install")
    head = struct.pack("<4sIIIII", b"SBU2", command, tag, arg, len(payload), zlib.crc32(payload))
    return (head + payload).ljust(pr.FRAME, b"\0")


def plan(image, boot_crc, write):
    """The frames of a session after the hello, in order: (command, argument, payload, the state after it, what)."""
    p = [(MANIFEST, 0, manifest(image, boot_crc), 1, "the manifest")]
    blocks = [(BLOCK_CMD, o, image.area[o:o + BLOCK], None, f"block {o // BLOCK}") for o in range(0, len(image.area), BLOCK)]
    p += blocks                                # the first pass: checked, not written
    if write:
        p += [(COMMIT, ERASE_ARG, b"", 3, "the erase of the sector at 0x6000")]
        p += blocks                            # the second pass: written, block 0 kept in RAM
        p += [(COMMIT, COMMIT_ARG, b"", 5, "the commit"), (START_APP, 0, b"", None, "the start of the new app")]
    return p


class Session(pr.Recovery):
    """The recovery protocol with the write commands. The hello is pd40_recovery's probe."""

    def __init__(self, dev, log, now):
        super().__init__(dev, log, now)
        self.erased = False

    def send(self, command, arg=0, payload=b"", quiet=False):
        self.tag += 1
        data = frame(command, self.tag, arg, payload)
        if not quiet:
            self.log(f"frame header: {data[:24].hex()} ({NAMES[command]}, tag {self.tag}, argument {arg:#x}, "
                     f"length {len(payload)})")
        self.access()
        self.dev.bulk_out(data)
        self.sent = (command, self.tag, self.now())

    def answer(self, command, ms):
        """The reply over bulk IN, checked: the protocol's, for this frame, status 0."""
        self.access()
        try:
            raw = bytes(self.dev.bulk_in(pr.REPLY, ms))
        except pr.Timeout:
            raise BadAnswer(f"no reply to the {NAMES[command]} over the bulk IN endpoint within {ms} ms")
        r = pr.parse_reply(raw, command, self.tag)
        if r.status:
            raise BadAnswer(f"the {NAMES[command]} (tag {self.tag}) was answered with status {r.status} "
                            f"({pr.STATUS.get(r.status, 'unknown')}), state {r.state}, next offset {r.next_offset:#x}, "
                            f"last flash error {r.words[1]:#x}")
        return r

    def step(self, command, arg, payload, state, what, ms, quiet=False):
        self.send(command, arg, payload, quiet)
        if command == COMMIT and arg == ERASE_ARG:
            self.erased = True                 # from here the pedal starts no app until the commit
        r = self.answer(command, ms)
        if command == BLOCK_CMD:
            want = arg + BLOCK
            if r.next_offset != want:
                raise BadAnswer(f"after {what} the pedal expects offset {r.next_offset:#x}, not {want:#x}")
        if state is not None and r.state != state:
            raise BadAnswer(f"after {what} the pedal is in state {r.state}, not {state}")
        if not quiet:
            self.log(f"{what}: accepted, state {r.state}, next offset {r.next_offset:#x}, image length "
                     f"{r.image_length:#x}")
        return r


def dry_run(image, log):
    """Every frame the install would send, with a hello first; nothing is opened."""
    boot = image.head_crc if image.head_crc is not None else KNOWN_HEAD
    log(f"dry run: nothing is opened or sent. The manifest names the boot area CRC-32 {boot:#010x} "
        f"({'the package head' if image.head_crc is not None else pr.HEADS[KNOWN_HEAD]}); the install uses the one the "
        "pedal's hello reports, and refuses any other")
    tag = 1
    log(f"frame 1 header: {frame(HELLO, tag)[:24].hex()} (hello)")
    for command, arg, payload, _, what in plan(image, boot, write=True):
        tag += 1
        head = frame(command, tag, arg, payload)[:24].hex()
        if command == BLOCK_CMD:
            log(f"frame {tag} header: {head} ({what}: image bytes [{arg:#x}, {arg + BLOCK:#x}) to flash "
                f"{BASE + arg:#x}, CRC-32 {zlib.crc32(payload):#010x})")
        else:
            log(f"frame {tag} header: {head} ({what})")
        if command == MANIFEST:
            for i in range(0, len(payload), 32):
                log(f"  manifest {i:3d}: {payload[i:i + 32].hex()}")
    log(f"dry run finished: {tag} frames; --verify sends the first {image.blocks + 2} (nothing written), --write all")
    return 0


AFTER_START = {GAMUT: "Gamut started: the install worked", pr.APP: "M-VAVE's app started: the official app area is back",
               pr.RECOVERY: "the recovery mode came back: the boot loader did not start the new app",
               pr.UBOOT: "the chip's USB boot state appeared: the boot loader did not start the new app"}

FIRST_RUN = """\
First-run check (docs/RESCUE.md): the boot screen's line PWR shows the supply levels the boot loader left (7 15 on
this head; 3 11 on the old head, at which Gamut was tuned). Then, with the pedal on USB:
    node tools/op.mjs dsp 2>&1 | tee gamut-v23-dsp.log
It plays every saved preset for 6 s and reads the load, the peak, the late blocks and the bypass; exit 0 means no
preset was late or bypassed. Play through each preset and listen for crackles. Send the log back either way."""

ERASED = """\
The app area is erased or half written: the pedal starts no firmware until an install finishes. Nothing below 0x6000
or from 0x9F000 up was touched. Switch the pedal off, hold HOME, the right footswitch and the knob's PUSH, switch it on
until the screen shows RECOVERY, and run this again with --write: this image, or M-VAVE's BlackBox_023.fwsc to put the
official firmware back."""


def run(bus, image, mode, watch, log):
    """mode: "verify" or "write". Returns the exit code."""
    dev = bus.open_recovery()
    if dev is None:
        log(f"no recovery device ({pr.VID:04X}:{pr.PID:04X}) found. Power the pedal off, hold HOME, the right footswitch "
            "and the knob's PUSH, power it on and keep holding until the screen shows RECOVERY, then run this again")
        return 1
    found = bus.now()
    stamped = lambda m: log(f"[{(bus.now() - found) * 1000:6.0f} ms] {m}")
    session = Session(dev, stamped, bus.now)
    started = None
    try:
        stamped(f"found {pr.VID:04X}:{pr.PID:04X} {dev.manufacturer!r} {dev.product!r}, device version {dev.bcd_device:#06x}")
        try:
            hello, bulk = session.probe()
            pr.describe(hello, bulk, log)
            if bulk is not None:
                raise GuardError("the hello reply did not come over the bulk IN endpoint, and the pedal takes the next "
                                 "frame only after its reply has been read there")
            if hello.state != 0:
                raise GuardError(f"the recovery mode is in state {hello.state}: another tool started an update. Power-"
                                 "cycle the pedal into the recovery mode again first")
            if hello.boot_crc not in pr.HEADS:
                raise GuardError(f"the pedal's boot area CRC-32 {hello.boot_crc:#010x} is not a head this tool knows")
            if image.head_crc is not None and image.head_crc != hello.boot_crc:
                raise GuardError(f"the package's head (CRC-32 {image.head_crc:#010x}) is not the pedal's "
                                 f"({hello.boot_crc:#010x})")
            steps = plan(image, hello.boot_crc, mode == "write")
            stamped(f"{image.what}: {len(image.area):#x} bytes, {image.blocks} blocks, CRC-32 "
                    f"{zlib.crc32(image.area):#010x}; {'the install' if mode == 'write' else 'the check only'}: "
                    f"{len(steps)} frames")
            for i, (command, arg, payload, state, what) in enumerate(steps):
                if command == START_APP and mode == "write":
                    started = True
                k = arg // BLOCK                                  # blocks: the first, every 32nd and the last shown
                quiet = command == BLOCK_CMD and 0 < k < image.blocks - 1 and k % 32
                ms = (COMMIT_MS if (command, arg) == (COMMIT, COMMIT_ARG) else
                      WRITE_MS if session.erased or command == COMMIT else READ_MS)
                r = session.step(command, arg, payload, state, what, ms, quiet)
                if command == BLOCK_CMD and r.state in (2, 4):
                    stamped(f"{'first' if r.state == 2 else 'second'} pass done: {image.blocks} blocks and the whole "
                            f"image's CRC-32 accepted, state {r.state}"
                            + (": nothing was written" if r.state == 2 else ""))
        except pr.ScsiError as e:
            if not pr.left_bus(bus, e):
                raise
            if not started:
                stamped(f"the pedal left the bus ({e}): the recovery mode ended on its own; nothing more is sent")
                if session.erased:
                    log(ERASED)
                return 4
            stamped("start the app: sent; its reply did not arrive")   # it acts once its reply is read: it was
    except (GuardError, ScsiError):
        if session.erased:
            log(ERASED)
        raise
    finally:
        dev.close()
    if not started:
        log("the pedal checked the manifest, every block and the whole image against its own head: nothing was "
            "written. It stays in the recovery mode; switch it off and on to leave")
        return 0
    stamped("the pedal resets into the new app")
    seen = watch_bus(bus, watch, stamped, until=image.expect)
    if image.expect in seen:
        log(AFTER_START[image.expect])
        if image.expect == GAMUT:
            log(FIRST_RUN)
        return 0
    came = AFTER_START.get(seen[0], "") if seen else f"nothing appeared within {watch:g} s"
    log(f"the new app did not appear ({came}). The install itself finished: power-cycle the pedal once. If it still "
        "shows no firmware, enter the recovery mode and put the official app area back (docs/RESCUE.md)")
    return 3


def watch_bus(bus, seconds, log, until):
    """pd40_recovery.watch_bus with Gamut's device among the watched ones. Opens nothing and sends nothing."""
    log(f"watching the bus for {seconds:g} s (listing only: nothing is opened or sent)")
    end, on, seen = bus.now() + seconds, {pr.RECOVERY}, []
    while True:
        now = bus.present()
        for d in sorted(now - on):
            log(f"{d[0]:04X}:{d[1]:04X} appeared: {WATCHED[d]}")
            seen.append(d)
        for d in sorted(on - now):
            log(f"{d[0]:04X}:{d[1]:04X} left the bus: {WATCHED[d]}")
        on = now
        if until in on or bus.now() >= end:
            return seen
        bus.sleep(bus.POLL)


class LibusbBus(pr.LibusbBus):
    def present(self):
        """The WATCHED devices on the bus now, Gamut's among them. Reads device descriptors only; opens nothing."""
        devs = ctypes.POINTER(ctypes.c_void_p)()
        n = self.lib.libusb_get_device_list(self.usb.ctx, ctypes.byref(devs))
        try:
            found = set()
            for i in range(max(n, 0)):
                desc = ur.DevDesc()
                if self.lib.libusb_get_device_descriptor(devs[i], ctypes.byref(desc)) == 0:
                    found.add((desc.idVendor, desc.idProduct))
            return found & set(WATCHED)
        finally:
            self.lib.libusb_free_device_list(devs, 1)


def transport():
    return LibusbBus()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Install an app area on a BlackBox with the V22/V23 boot loader through its "
                                             "recovery mode (USB 3654:7940). The default is a dry run that opens nothing.")
    ap.add_argument("image", type=Path, help="a *-v23.bin app area, a BlackBox package of this project, or M-VAVE's "
                                             "BlackBox_022/023.fwsc")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true", help="the pedal checks the image in its first pass; nothing is written")
    mode.add_argument("--write", action="store_true", help="write the image to [0x6000, 0x9F000) and start it")
    ap.add_argument("--watch", type=float, default=60, help="seconds to wait for the new app after the start (default 60)")
    a = ap.parse_args(argv)
    log = lambda m: print(m, flush=True)
    try:
        image = load_image(a.image)
        log(f"image: {image.what}: {len(image.area):#x} bytes for [{BASE:#x}, {BASE + len(image.area):#x}), "
            f"{image.blocks} blocks, CRC-32 {zlib.crc32(image.area):#010x}, every check passed")
        if not (a.verify or a.write):
            return dry_run(image, log)
        return run(transport(), image, "write" if a.write else "verify", a.watch, log)
    except GuardError as e:
        print(f"\nREFUSED: {e}; nothing more was sent", file=sys.stderr)
        return 2
    except RescueError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    except ScsiError as e:
        print(f"\nERROR: the recovery device stopped answering ({e}); nothing more was sent", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
