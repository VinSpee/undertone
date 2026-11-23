#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""pd40_install.py - have a BlackBox with M-VAVE's V22 or V23 boot loader check an app area in its recovery mode. It
writes nothing: the install itself is tools/uboot_install.py.

On such a pedal the app area starts at 0x6000, and the boot loader starts it after four CRC16 checks only: the flash
header, the head's entries up to app_dir_head, and the first 32 bytes at 0x6000 under the chip key 0x980F. Its recovery
mode (the screen shows RECOVERY, USB 3654:7940 "PD40 BOOT Recovery"; hold HOME, the right footswitch and the knob's PUSH
at power-on) can take an image for [0x6000, 0x9F000) in two passes: the first only checks it, the second writes it.

A write through the recovery mode cannot finish on this chip. On the one real pedal tried, the chip's long-press reset
(P33 PINR_CON), which M-VAVE's recovery code never turns off, restarted the pedal about 4.3 s after power-on, whatever
the computer did; the write needs about 14 s, the protocol starts again from the first block at every entry, and it has
no command that could turn the reset off. The attempt left the app area erased. So --write is refused, and the
install of Gamut and the way back to M-VAVE's firmware go through the chip's USB boot state: tools/uboot_install.py,
docs/RESCUE.md, "Gamut on a BlackBox with V22 or V23". The first pass, which took 1.9 s on that pedal, does fit:

  tools/pd40_install.py IMAGE              dry run (the default): checks IMAGE and prints every frame the check would
                                           send, in order. Opens no USB device
  tools/pd40_install.py IMAGE --verify     the recovery mode's own first pass: the pedal checks the manifest, every block
                                           and the whole image against its own head, and writes nothing
  ... --verify --accept-control-reply      the same, also when the pedal answers over the control endpoint only

IMAGE is one of:
  build/apps/gamut/BlackBox_950-v23.bin    Gamut's app area (node tools/op.mjs package)
  build/apps/gamut/BlackBox_950.fwsc       the same area, read from Gamut's BlackBox package
  BlackBox_023.fwsc or BlackBox_022.fwsc   M-VAVE's official package: its app area [0x6000, 0x9F000). Its head must be
                                           the pedal's: the hello names the CRC-32 of the pedal's [0, 0x6000)

The protocol, read in the V23 boot loader's code (frames of 4608 bytes from "SBU2", 64-byte replies from "SBR2", CRC-32
as zlib's): 1 hello; 2 the manifest ("SKR2", the protocol's constants, the write range, the image's length and CRC-32,
the CRC-32 of the pedal's [0, 0x6000), the entry 0x02000120, the block count, a CRC-32 over these and the table, then one
CRC-32 per 4 KiB block); 3 a block, in order, which in this pass is only checked. The commands that write (4 the erase
and the commit, 5 the start of the new app, and a block after the erase) are never sent: this tool cannot compose them.
Every frame and reply is printed with its time in milliseconds from the moment the device was found, as
tools/pd40_recovery.py prints them, with the time each phase took; when the pedal leaves the bus, the log says after
which frame and how long after it was sent.

The replies. The pedal takes the next frame once the bulk IN endpoint's packet for the last one has been read, and that
packet should be the reply. On the one real V23 pedal tried it was 64 zero bytes, while the reply buffer (vendor request
0x43) held the real reply. So the tool reads every reply over the bulk IN endpoint first and, when that endpoint sends
64 zero bytes in its place and --accept-control-reply is given, reads it from the reply buffer and checks it the same
way: "SBR2", the command and tag of this frame, the CRC-32, the protocol's constants and write range, status 0, then
the state and the next offset. Without the flag such a pedal is refused at the hello, or at the first reply that comes
as zeros, before anything more is sent. The frames go out back to back, because the mode ends seconds after power-on.

It refuses an image that is not a whole number of 4 KiB blocks, longer than the write range, whose area head fails its
CRC under the chip key, whose entry is not 0x02000120, whose files fail their CRCs, a Pocket X image, and an official
package for another head; and a pedal whose hello is not answered in state 0 or names a head this tool does not know.

One-time install (macOS): `brew install libusb`; no sudo. Exit codes: 0 done (the dry run printed, or the pedal's check
passed), 1 setup problem, no recovery device or a failed transfer, 2 refused or a bad answer, 4 the pedal left the
recovery mode before the check finished, 130 Ctrl-C.
"""
import argparse, re, struct, sys, zlib
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pocketx_fw as fw
import pd40_recovery as pr
from pd40_recovery import BadAnswer, GuardError, RescueError, ScsiError

BLOCK, FLASH_SIZE, ENTRY = 4096, 0x100000, 0x02000120
CONSTANTS, VERSION = 0x07910040, 0x00020000
BASE, LIMIT = pr.PROTOCOL[2], pr.PROTOCOL[3]   # the write range [0x6000, 0x9F000) every reply carries
HELLO, MANIFEST, BLOCK_CMD = pr.HELLO, pr.MANIFEST, pr.BLOCK
NAMES = {HELLO: "hello", MANIFEST: "manifest", BLOCK_CMD: "block"}   # the only commands this tool can send
KNOWN_HEAD = next(iter(pr.HEADS))              # 0xB19D96A1, the official V22 and V23 head
READ_MS = 1000                                 # a reply that only checks
ROUTES = {"bulk": "bulk IN endpoint", "control": f"control endpoint (request {pr.REPLY_BUFFER:#x})"}

NO_WRITE = """\
a write through the recovery mode cannot finish on this chip. Its long-press reset restarts the pedal about 4.3 s after
power-on in M-VAVE's recovery mode, the write needs about 14 s, and the computer cannot turn that reset off: the attempt
on a real pedal left the app area erased. Install through the chip's USB boot state instead:
    sudo python3 tools/uboot_install.py --write
(docs/RESCUE.md, "Gamut on a BlackBox with V22 or V23"; --official FILE.fwsc puts M-VAVE's firmware back).
Nothing was sent to the pedal"""


@dataclass(frozen=True)
class Image:
    area: bytes                                # the bytes for [0x6000, 0x6000 + len)
    what: str                                  # in words, for the log
    head_crc: int                              # the CRC-32 of the [0, 0x6000) it needs on the pedal; None: any known head

    @property
    def blocks(self):
        return len(self.area) // BLOCK


def check_area(area, base=BASE, limit=LIMIT):
    """The checks of an app area on its own (offsets from its start), as the boot loader and pocketx_fw read it, for a
    flash layout that keeps it in [base, limit). Returns the identity in its OP-PRODUCT field, or None. Raises
    GuardError with the first failure."""
    if not area or len(area) % BLOCK:
        raise GuardError(f"the image is {len(area)} bytes, not a whole number of 4 KiB blocks")
    if len(area) > limit - base:
        raise GuardError(f"the image is {len(area):#x} bytes, longer than the write range [{base:#x}, {limit:#x})")
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
        return Image(data, f"the app area {path.name}, identity {identity}", None)
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
        return Image(area, f"the app area of {path.name}, identity {tag}", None)
    if base != BASE:
        raise GuardError(f"{path.name} ({tag}) puts its app area at {base:#x}: it is a package for the old head, and "
                         "only M-VAVE's V22 and V23 packages are made for this boot loader")
    area = flash[BASE:]
    check_area(area)
    return Image(area, f"M-VAVE's app area from {path.name} ({tag})", zlib.crc32(flash[:BASE]))


def manifest(image, boot_crc, word=0):
    """Command 2's payload: 64 bytes of header (its CRC-32 over bytes 0..59 and the table), then the table."""
    table = b"".join(struct.pack("<I", zlib.crc32(image.area[i:i + BLOCK])) for i in range(0, len(image.area), BLOCK))
    head = struct.pack("<4s14I", b"SKR2", VERSION, CONSTANTS, FLASH_SIZE, BASE, LIMIT, len(image.area),
                       zlib.crc32(image.area), boot_crc, ENTRY, image.blocks, word, 0, 0, 0)
    return head + struct.pack("<I", zlib.crc32(head + table)) + table


def frame(command, tag, arg=0, payload=b""):
    """A 4608-byte frame: "SBU2", command, tag, argument, the payload's length and CRC-32, the payload."""
    if command not in NAMES or len(payload) > BLOCK:
        raise GuardError(f"command {command} with {len(payload)} bytes is not a frame of the check: this tool "
                         "sends the hello, the manifest and the blocks of the first pass only")
    head = struct.pack("<4sIIIII", b"SBU2", command, tag, arg, len(payload), zlib.crc32(payload))
    return (head + payload).ljust(pr.FRAME, b"\0")


def plan(image, boot_crc):
    """The frames of the check after the hello, in order: (command, argument, payload, the state after it, what, the
    phase it belongs to). The recovery mode is in state 2 after the last block: checked, nothing written."""
    last = len(image.area) - BLOCK
    return [(MANIFEST, 0, manifest(image, boot_crc), 1, "the manifest", "the manifest")] + [
        (BLOCK_CMD, o, image.area[o:o + BLOCK], 1 + (o == last), f"block {o // BLOCK}", "the first pass")
        for o in range(0, len(image.area), BLOCK)]


class Session(pr.Recovery):
    """The recovery protocol with the commands of the first pass. The hello is pd40_recovery's probe. control: a reply
    may be read from the reply buffer (request 0x43) when the bulk IN endpoint sends 64 zero bytes in its place."""

    def __init__(self, dev, log, now, control=False):
        super().__init__(dev, log, now)
        self.control = control
        self.last = None                       # what the last frame sent was, in words
        self.routes = {"bulk": 0, "control": 0}   # the replies read over each endpoint

    def send(self, command, arg=0, payload=b"", quiet=False):
        self.tag += 1
        data = frame(command, self.tag, arg, payload)
        if not quiet:
            self.log(f"frame header: {data[:24].hex()} ({NAMES[command]}, tag {self.tag}, argument {arg:#x}, "
                     f"length {len(payload)})")
        self.access()
        self.dev.bulk_out(data)
        self.sent = (command, self.tag, self.now())

    def reply_buffer(self):
        self.access()
        return bytes(self.dev.control_in(pr.REPLY_BUFFER, pr.REPLY))

    def answer(self, command, ms):
        """The reply to the last frame, checked: the protocol's, for this frame, status 0. Over the bulk IN endpoint,
        whose packet must be read for the pedal to go on; with control, from the reply buffer when that packet is 64
        zero bytes. Returns (the reply, "bulk" or "control")."""
        self.access()
        try:
            raw = bytes(self.dev.bulk_in(pr.REPLY, ms))
        except pr.Timeout:
            held = f"; the reply buffer (request {pr.REPLY_BUFFER:#x}) holds {pr.dump(self.reply_buffer())}" \
                if self.control else ""
            raise BadAnswer(f"no reply to the {NAMES[command]} (tag {self.tag}) over the bulk IN endpoint within "
                            f"{ms} ms{held}")
        route, why = "bulk", pr.what_came(raw, command, self.tag)
        if why is not None:
            if not self.control or raw != bytes(pr.REPLY):
                raise BadAnswer(f"the bulk IN endpoint sent {why} in place of the reply to the {NAMES[command]} (tag "
                                f"{self.tag})" + ("" if self.control else
                                                  "; --accept-control-reply would read it from the reply buffer"
                                                  if raw == bytes(pr.REPLY) else ""))
            route, raw = "control", self.reply_buffer()
            why = pr.what_came(raw, command, self.tag)
            if why is not None:
                raise BadAnswer(f"the bulk IN endpoint sent 64 zero bytes in place of the reply to the "
                                f"{NAMES[command]} (tag {self.tag}), and the reply buffer (request "
                                f"{pr.REPLY_BUFFER:#x}) holds {why}")
        self.routes[route] += 1
        r = pr.parse_reply(raw, command, self.tag)
        if r.status:
            raise BadAnswer(f"the {NAMES[command]} (tag {self.tag}) was answered with status {r.status} "
                            f"({pr.STATUS.get(r.status, 'unknown')}), state {r.state}, next offset {r.next_offset:#x}, "
                            f"last flash error {r.words[1]:#x}")
        return r, route

    def step(self, command, arg, payload, state, what, quiet=False):
        self.last = what
        self.send(command, arg, payload, quiet)
        r, route = self.answer(command, READ_MS)
        if command == BLOCK_CMD and r.next_offset != arg + BLOCK:
            raise BadAnswer(f"after {what} the pedal expects offset {r.next_offset:#x}, not {arg + BLOCK:#x}")
        if r.state != state:
            raise BadAnswer(f"after {what} the pedal is in state {r.state}, not {state}")
        if not quiet:
            self.log(f"{what}: accepted over the {ROUTES[route]}, state {r.state}, next offset {r.next_offset:#x}, "
                     f"image length {r.image_length:#x}")
        return r

    def replies(self):
        """How many replies came over each endpoint, in words."""
        return ", ".join(f"{n} over the {ROUTES[k]}" for k, n in self.routes.items() if n) or "none"


def dry_run(image, log):
    """Every frame the check would send, with a hello first; nothing is opened."""
    boot = image.head_crc if image.head_crc is not None else KNOWN_HEAD
    log(f"dry run: nothing is opened or sent. The manifest names the boot area CRC-32 {boot:#010x} "
        f"({'the package head' if image.head_crc is not None else pr.HEADS[KNOWN_HEAD]}); the check uses the one the "
        "pedal's hello reports, and refuses any other")
    tag = 1
    log(f"frame 1 header: {frame(HELLO, tag)[:24].hex()} (hello)")
    for command, arg, payload, _, what, _ in plan(image, boot):
        tag += 1
        head = frame(command, tag, arg, payload)[:24].hex()
        if command == BLOCK_CMD:
            log(f"frame {tag} header: {head} ({what}: image bytes [{arg:#x}, {arg + BLOCK:#x}) for flash "
                f"{BASE + arg:#x}, CRC-32 {zlib.crc32(payload):#010x})")
        else:
            log(f"frame {tag} header: {head} ({what})")
        if command == MANIFEST:
            for i in range(0, len(payload), 32):
                log(f"  manifest {i:3d}: {payload[i:i + 32].hex()}")
    log(f"dry run finished: {tag} frames, the ones --verify sends; none of them writes")
    return 0


def run(bus, image, log, control=False):
    """The pedal's own check of the image; control: --accept-control-reply. Returns the exit code."""
    dev = bus.open_recovery()
    if dev is None:
        log(f"no recovery device ({pr.VID:04X}:{pr.PID:04X}) found. Power the pedal off, hold HOME, the right footswitch "
            "and the knob's PUSH, power it on and keep holding until the screen shows RECOVERY, then run this again")
        return 1
    found = bus.now()
    stamped = lambda m: log(f"[{(bus.now() - found) * 1000:6.0f} ms] {m}")
    session = Session(dev, stamped, bus.now, control)
    phase = None                               # [name, when it started, frames sent in it]

    def timed():
        if phase:
            name, at, n = phase
            stamped(f"{name}: {n} frame{'s' if n > 1 else ''} in {(bus.now() - at) * 1000:.0f} ms")

    try:
        stamped(f"found {pr.VID:04X}:{pr.PID:04X} {dev.manufacturer!r} {dev.product!r}, device version {dev.bcd_device:#06x}")
        phase = ["the hello", bus.now(), 1]
        session.last = "the hello"
        hello, bulk = session.probe()
        pr.describe(hello, bulk, log)
        if bulk is not None and not control:
            raise GuardError(f"the hello reply came over the control endpoint only (the bulk IN endpoint sent "
                             f"{bulk}). To read every such reply from the reply buffer (request "
                             f"{pr.REPLY_BUFFER:#x}), checked the same way, run this again with "
                             "--accept-control-reply: the one real V23 pedal tried answered this way")
        session.routes["bulk" if bulk is None else "control"] += 1
        timed()
        phase = None
        if bulk is not None:
            stamped(f"replies: over the {ROUTES['control']}, because the bulk IN endpoint sent {bulk} in place of "
                    "the hello reply (--accept-control-reply); each frame's bulk IN packet is still read first, "
                    "and a reply that comes there is taken there")
        else:
            stamped(f"replies: over the {ROUTES['bulk']}" + (
                f"; over the {ROUTES['control']} whenever the bulk IN endpoint sends 64 zero bytes in place of "
                "one (--accept-control-reply)" if control else ""))
        if hello.state != 0:
            raise GuardError(f"the recovery mode is in state {hello.state}: another tool started an update. Power-"
                             "cycle the pedal into the recovery mode again first")
        if hello.boot_crc not in pr.HEADS:
            raise GuardError(f"the pedal's boot area CRC-32 {hello.boot_crc:#010x} is not a head this tool knows")
        if image.head_crc is not None and image.head_crc != hello.boot_crc:
            raise GuardError(f"the package's head (CRC-32 {image.head_crc:#010x}) is not the pedal's "
                             f"({hello.boot_crc:#010x})")
        steps = plan(image, hello.boot_crc)
        stamped(f"{image.what}: {len(image.area):#x} bytes, {image.blocks} blocks, CRC-32 "
                f"{zlib.crc32(image.area):#010x}; the check only: {len(steps)} frames")
        for command, arg, payload, state, what, part in steps:
            if phase is None or part != phase[0]:
                timed()
                phase = [part, bus.now(), 0]
            phase[2] += 1
            k = arg // BLOCK                                  # blocks: the first, every 32nd and the last shown
            session.step(command, arg, payload, state, what, command == BLOCK_CMD and 0 < k < image.blocks - 1 and k % 32)
        timed()
        stamped(f"first pass done: {image.blocks} blocks and the whole image's CRC-32 accepted, state 2: nothing was "
                f"written. Replies: {session.replies()}")
    except ScsiError as e:
        if not pr.left_bus(bus, e):
            raise
        stamped(f"the pedal left the bus ({e}) during {session.last} (tag {session.tag}), "
                f"{session.since(bus.now())}: the recovery mode ended before the check finished; nothing more is sent "
                f"and nothing was written. Replies read: {session.replies()}. The mode ends seconds after power-on: "
                "enter it again with this command ready and start it the moment the screen shows RECOVERY")
        return 4
    finally:
        dev.close()
    log("the pedal checked the manifest, every block and the whole image against its own head: nothing was "
        "written. It leaves the recovery mode by itself; switch it off and on to start its firmware")
    return 0


transport = pr.transport


def main(argv=None):
    ap = argparse.ArgumentParser(description="Have a BlackBox with the V22/V23 boot loader check an app area in its "
                                             "recovery mode (USB 3654:7940). Nothing is written; the default is a dry "
                                             "run that opens nothing. The install is tools/uboot_install.py.")
    ap.add_argument("image", type=Path, help="a *-v23.bin app area, a BlackBox package of this project, or M-VAVE's "
                                             "BlackBox_022/023.fwsc")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true", help="the pedal checks the image in its first pass; nothing is written")
    mode.add_argument("--write", action="store_true",
                      help="refused: a write through the recovery mode cannot finish on this chip. Use "
                           "tools/uboot_install.py")
    ap.add_argument("--accept-control-reply", action="store_true",
                    help="with --verify: read a reply from the reply buffer (control request 0x43) when the bulk IN "
                         "endpoint sends 64 zero bytes in its place, as on the one real V23 pedal tried; checked the "
                         "same way")
    a = ap.parse_args(argv)
    if a.accept_control_reply and not a.verify:
        ap.error("--accept-control-reply goes with --verify")
    log = lambda m: print(m, flush=True)
    try:
        if a.write:
            raise GuardError(NO_WRITE)
        image = load_image(a.image)
        log(f"image: {image.what}: {len(image.area):#x} bytes for [{BASE:#x}, {BASE + len(image.area):#x}), "
            f"{image.blocks} blocks, CRC-32 {zlib.crc32(image.area):#010x}, every check passed")
        if not a.verify:
            return dry_run(image, log)
        return run(transport(), image, log, a.accept_control_reply)
    except GuardError as e:
        print(f"\nREFUSED: {e}" + ("" if a.write else "; nothing more was sent"), file=sys.stderr)
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
