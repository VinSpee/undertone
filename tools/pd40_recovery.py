#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""pd40_recovery.py - a read-only helper for M-VAVE's recovery mode on a BlackBox with the V22 or V23 boot loader.

M-VAVE's V22/V23 boot loader carries a recovery mode of its own: the screen shows RECOVERY and the pedal is a WinUSB
device, USB 3654:7940 "PD40 BOOT Recovery". It starts when the three controls HOME, the right footswitch and the knob's
PUSH are held at power-on, when the stock V23 app receives the SysEx F0 22 24 35 7D F7, or when an app returns to the
boot loader. On such a pedal the chip's USB boot state (4C4A:8057), where tools/uboot_rescue.py works, is no longer
reached the old way. This tool reads what the recovery mode says about the pedal and, when asked, sends the one command
that leaves it for the USB boot state. The repository's tools/uboot_install.py sends the same hello and leave and then
installs or restores in one run; this helper is the way to look at a pedal without writing. docs/RESCUE.md, "A pedal
on M-VAVE's V22 or V23", has the steps.

  tools/pd40_recovery.py                              read-only probe: the request buffers, one hello, its reply
  tools/pd40_recovery.py --sync                       the same with the sync request 0x42 before the hello
  tools/pd40_recovery.py --leave --accept-inferred    the probe, then command 6, the leave to the USB boot state
  tools/pd40_recovery.py --leave --accept-inferred --accept-control-reply
                                                      the same, also when the hello reply came over the control endpoint

The probe reads the frame buffer (vendor request 0x44) and the reply buffer (0x43), sends one hello, reads both again,
then reads the reply on the bulk IN endpoint. The reply buffer gives the hello result even when the bulk IN endpoint
sends something else: on a real pedal on V23 it sent 64 zero bytes, then nothing. The recovery code as read has no
timer and ends at its first failed access to its USB controller, yet on a real pedal the mode ended about 4 s after
power-on whatever the computer did: the chip's long-press reset, which the recovery code never turns off, is the likely
cause (inferred). So after the probe, and after the leave, the helper releases the device and lists the USB
devices for a while, sending nothing: it logs when the pedal leaves the bus, how long after the last command it sent
and after its first access, and whether the pedal comes back as the chip's USB boot state, the recovery mode or the
normal pedal. Every phase and transfer is printed with its raw bytes and its time in milliseconds from the moment the
device was found.

It never writes to the pedal's flash. The protocol's write commands (2 manifest, 3 block, 4 erase and commit, 5 start
the new app) and every vendor request but 0x42, 0x43 and 0x44 are refused before anything is sent; frames carry no
payload. The protocol was read in the V23 boot loader's code (frames of 4608 bytes from "SBU2", 64-byte replies from
"SBR2", CRC-32 as zlib's). Command 6 resets the processor core, not the whole chip as OpenPocket's own soft key does.
On the one real pedal tried, a BlackBox on V23, the chip's ROM then entered its USB boot state: the pedal left the bus
about 275 ms after the leave and came back as 4C4A:8057 about 500 ms later. No other pedal has been tried, so --leave
stops with the explanation unless --accept-inferred is given too. The pedal acts on command 6 once its reply has been
read, so the leave is refused when the hello reply did not come over the bulk IN endpoint, unless
--accept-control-reply is given as well: that pedal answered the hello over the control endpoint only and acted on the
leave all the same.

One-time install (macOS): `brew install libusb`. The recovery device's interface is vendor-specific and no macOS driver
holds it, so the probe needs no sudo. tools/uboot_rescue.py, which takes over after --leave, needs sudo. Linux and
Windows have not been tried; on Windows set LIBUSB_PATH to libusb-1.0.dll.
Exit codes: 0 done (after a probe without the leave: the pedal stayed in the recovery mode for the whole watch), 1 setup
problem, no recovery device or a failed transfer, 2 refused or a bad answer (nothing more was sent), 3 the pedal left
after --leave but the USB boot state did not appear, 4 the pedal left the recovery mode on its own during the probe or
the watch after it, 5 the pedal stayed in the recovery mode after --leave, 130 stopped by Ctrl-C.
"""
import argparse, ctypes, struct, sys, time, zlib
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import uboot_rescue as ur
from uboot_rescue import DeviceGone, GuardError, RescueError, ScsiError

VID, PID = 0x3654, 0x7940
FRAME, REPLY = 4608, 64                        # a frame is always 4608 bytes; a reply 64
SYNC, REPLY_BUFFER, FRAME_BUFFER = 0x42, 0x43, 0x44
REQUESTS = {SYNC: 4, REPLY_BUFFER: REPLY, FRAME_BUFFER: 24}   # the only vendor IN requests (0xC1) sent, and their lengths
HELLO, MANIFEST, BLOCK, COMMIT, START_APP, LEAVE = 1, 2, 3, 4, 5, 6
ALLOWED = frozenset({HELLO, LEAVE})            # the only commands this tool can send; neither carries data
WRITES = {MANIFEST: "manifest", BLOCK: "block", COMMIT: "erase and commit", START_APP: "start the new app"}
PROTOCOL = (0x07910040, 0x00020000, 0x6000, 0x9F000)   # constants and the write range [base, limit) every reply carries
HEADS = {0xB19D96A1: "M-VAVE V22 or V23 (the boot area of both official packages)"}
STATUS = {0: "accepted", 1: "malformed", 2: "wrong state", 4: "out of range", 5: "boot CRC is not this pedal's",
          6: "CRC error", 7: "flash error", 8: "block out of order"}
LEAVE_STATES = (0, 6)                          # command 6 is accepted in these states only
FIRST_READ_MS, SECOND_READ_MS = 1000, 300      # the bulk IN reads of a reply
RECOVERY, UBOOT, APP = (VID, PID), (ur.VID, ur.PID), (VID, 0x7756)
WATCHED = {UBOOT: "the chip's USB boot state", RECOVERY: "the recovery mode",
           APP: "the normal pedal (the stock V23 app)"}
AFTER_DEPARTURE = {
    UBOOT: "the chip's ROM honoured usb_update_mode after the core reset",
    RECOVERY: "the boot loader ran again and saw the three controls again",
    APP: "the boot loader ran, did not see the three controls, and started the app"}


class BadAnswer(GuardError):
    """The device answered in a way the protocol does not allow. Nothing more is sent to it."""


class Timeout(ScsiError):
    """A transfer was not answered in time. On a bulk IN read the probe expects this and reads nothing more there."""


@dataclass(frozen=True)
class Reply:
    command: int
    tag: int
    status: int
    state: int
    next_offset: int
    image_length: int
    constants: tuple
    base: int
    limit: int
    boot_crc: int
    words: tuple                               # erase started, last flash error, the manifest's word at offset 68


def frame(command, tag):
    """The 4608-byte frame of a command without payload: "SBU2", command, tag, argument 0, length 0, CRC-32 0."""
    if command not in ALLOWED:
        raise GuardError(refusal(command))
    return struct.pack("<4sIIIII", b"SBU2", command, tag, 0, 0, 0).ljust(FRAME, b"\0")


def refusal(command):
    if command in WRITES:
        return f"command {command} ({WRITES[command]}) belongs to a write to the flash: this tool never sends it"
    return f"command {command} is not one this tool sends (only {HELLO} hello and {LEAVE} leave)"


def parse_reply(raw, command, tag):
    """The 64-byte reply, checked: "SBR2", the command and tag echoed, the CRC-32 of its first 60 bytes."""
    if len(raw) != REPLY:
        raise BadAnswer(f"the reply is {len(raw)} bytes, not {REPLY}")
    w = struct.unpack("<4s15I", raw)
    if w[0] != b"SBR2":
        raise BadAnswer(f"the reply starts with {w[0]!r}, not 'SBR2'")
    if w[15] != zlib.crc32(raw[:60]):
        raise BadAnswer(f"the reply's CRC-32 {w[15]:#010x} is not that of its contents ({zlib.crc32(raw[:60]):#010x})")
    if (w[1], w[2]) != (command, tag):
        raise BadAnswer(f"the reply is for command {w[1]} tag {w[2]}, not command {command} tag {tag}")
    r = Reply(w[1], w[2], w[3], w[4], w[5], w[6], (w[7], w[8]), w[9], w[10], w[11], w[12:15])
    if (*r.constants, r.base, r.limit) != PROTOCOL:
        raise BadAnswer("the reply's constants or write range are not the ones read in the V23 boot loader "
                        f"({r.constants[0]:#x} {r.constants[1]:#x} [{r.base:#x}, {r.limit:#x})): another recovery version")
    return r


def dump(raw):
    return f"{len(raw)} B " + (raw.hex() if any(raw) else "all zero")


def what_came(raw, command, tag):
    """Why raw is not the reply to command and tag, in words; None when it is."""
    if raw is None:
        return "nothing"
    if raw and not any(raw):
        return f"{len(raw)} zero bytes"
    try:
        parse_reply(raw, command, tag)
    except BadAnswer as e:
        return str(e)
    return None


class Recovery:
    """The recovery protocol over a transport: dev.control_in(request, n), dev.bulk_out(data), dev.bulk_in(n, ms).
    log prints a line with the time since the device was found; now is the clock that time is measured on."""

    def __init__(self, dev, log, now):
        self.dev, self.log, self.now, self.tag = dev, log, now, 0
        self.first = self.sent = None            # when the first transfer started; (command, tag, when) of the last
                                                 # frame sent

    def access(self):
        if self.first is None:
            self.first = self.now()

    def since(self, at):
        """How long before at the last command was sent and the first transfer started, in words."""
        first = f"{(at - self.first) * 1000:.0f} ms after the first access"
        if self.sent is None:
            return f"before any command was sent, {first}"
        command, tag, when = self.sent
        return f"{(at - when) * 1000:.0f} ms after the last command sent (command {command}, tag {tag}) and {first}"

    def request(self, request, what):
        self.access()
        got = bytes(self.dev.control_in(request, REQUESTS[request]))
        self.log(f"{what} ({request:#x}): {dump(got)}")
        return got

    def send(self, command):
        data = frame(command, self.tag + 1)
        self.tag += 1
        self.log(f"frame header: {data[:24].hex()} (command {command}, tag {self.tag}, length 0)")
        self.access()
        self.dev.bulk_out(data)
        self.sent = (command, self.tag, self.now())
        self.log(f"frame: command {command}, tag {self.tag}, {len(data)} bytes in one transfer")

    def read(self, ms, what):
        """One bulk IN read of exactly 64 bytes; None when nothing came within ms."""
        self.access()
        try:
            got = bytes(self.dev.bulk_in(REPLY, ms))
        except Timeout:
            self.log(f"{what}: nothing within {ms} ms")
            return None
        self.log(f"{what}: {dump(got)}")
        return got

    def sync(self):
        got = self.request(SYNC, "sync")
        if got != b"SBU2":
            raise BadAnswer(f"the sync request answered {got!r}, not 'SBU2'")

    def probe(self, sync=False):
        """The buffers, one hello, the buffers again, then its reply over bulk IN. Never a sync between the frame and
        the reads of its reply: the sync drops a waiting reply. Returns (the hello reply, None when it came over bulk IN
        or else what the bulk IN endpoint sent in its place)."""
        before = self.request(FRAME_BUFFER, "frame buffer") + self.request(REPLY_BUFFER, "reply buffer")
        if any(before):
            self.log("the buffers are not empty: another tool spoke to the pedal since it entered the recovery mode")
        if sync:
            self.sync()
        self.send(HELLO)
        head = self.request(FRAME_BUFFER, "frame buffer")
        kept = self.request(REPLY_BUFFER, "reply buffer")
        raw, bulk = self.await_reply(HELLO)
        if raw is not None:
            return self.check(parse_reply(raw, HELLO, self.tag)), None
        why = what_came(kept, HELLO, self.tag)
        if why is not None:
            got = ("" if any(kept) else ": the frame arrived only in part" if head == frame(HELLO, self.tag)[:24]
                   else ": the frame did not reach the frame buffer")
            raise BadAnswer(f"no reply to the hello: the bulk IN endpoint sent {bulk}, and the reply buffer holds {why}"
                            + got)
        return self.check(parse_reply(kept, HELLO, self.tag)), bulk

    def await_reply(self, command):
        """Up to two bulk IN reads for the reply to command, the second only after something else came. Returns (the raw
        reply, None), or (None, what the bulk IN endpoint sent in its place, in words)."""
        came = []
        for ms, what in ((FIRST_READ_MS, "bulk IN read 1"), (SECOND_READ_MS, "bulk IN read 2")):
            raw = self.read(ms, what)
            why = what_came(raw, command, self.tag)
            if why is None:
                return raw, None
            came.append(why)
            if raw is None:
                break                            # a second read after a timeout could only disturb the device
        return None, ", then ".join(came)

    def check(self, r):
        if r.status:
            raise BadAnswer(f"hello was answered with status {r.status} ({STATUS.get(r.status, 'unknown')})")
        return r

    def leave(self, hello):
        """Command 6. The pedal acts on it once its reply has been read; a lost reply is not an error."""
        if hello.state not in LEAVE_STATES:
            raise GuardError(f"the recovery mode is in state {hello.state}: another tool started an update, and "
                             "command 6 is refused there. Power-cycle the pedal into the recovery mode again first")
        self.send(LEAVE)
        raw, bulk = self.await_reply(LEAVE)
        if raw is None:
            self.log(f"leave: the bulk IN endpoint sent {bulk} in place of its reply")
            return None
        r = parse_reply(raw, LEAVE, self.tag)
        if r.status:
            raise BadAnswer(f"leave was answered with status {r.status} ({STATUS.get(r.status, 'unknown')})")
        return r


def describe(r, bulk, log):
    head = HEADS.get(r.boot_crc, "not a head this tool knows: the pedal's head is not an official V22/V23 head")
    log(f"hello: status {r.status} ({STATUS[0]}), state {r.state}"
        + (" (no update started)" if r.state == 0 else " (an update was started by another tool)"))
    log("  read over the bulk IN endpoint" if bulk is None else
        f"  read over the control endpoint (request {REPLY_BUFFER:#x}) because the bulk IN endpoint sent {bulk}")
    log(f"  boot area [0, {r.base:#x}) CRC-32 {r.boot_crc:#010x}: {head}")
    log(f"  write range [{r.base:#x}, {r.limit:#x}), protocol constants {r.constants[0]:#010x} {r.constants[1]:#010x}")
    log(f"  image length {r.image_length:#x}, next offset {r.next_offset:#x}, erase started {r.words[0]:#x}, "
        f"last flash error {r.words[1]:#x}, manifest word {r.words[2]:#x}")
    log("  not reported by the protocol: the chip key and the flash id. The recovery mode starts only on a 1 MiB flash "
        "with id EB 60 14 or 85 60 14; tools/uboot_rescue.py prints both after --leave")


LEAVE_TEXT = """\
--leave sends command 6. What is read in the V23 boot loader's code: the recovery mode answers, and once the computer
has read that answer it writes the word usb_update_mode to RAM (not to the flash) and resets the processor core. On the
one real pedal tried, a BlackBox on V23, the chip's ROM then entered its USB boot state (4C4A:8057): the pedal left the
bus about 275 ms after the leave and came back about 500 ms later. No other pedal has been tried. If the ROM does not
stay there, the pedal simply restarts; nothing is written either way.

The USB boot state lasts only seconds while nothing talks to it, so a tool must be waiting for it. To install Gamut or
put M-VAVE's firmware back from the repository, run its tools/uboot_install.py instead (the rescue kit does not hold
it): it sends this same leave and goes on by itself. To use this helper, start the rescue tool first, in a second
Terminal:
    sudo python3 tools/uboot_rescue.py --package firmware/BlackBox_023.fwsc
Then run this again with --leave --accept-inferred. Nothing was sent to the pedal."""


def watch_bus(bus, seconds, log, since, until=None):
    """List the USB devices every bus.POLL s for seconds and log each appearance and disappearance of the WATCHED
    devices, the recovery mode's with since(the time it was seen gone); stop early when until appears. Opens nothing
    and sends nothing. Returns (the devices that appeared, when the recovery mode was first seen gone or None)."""
    log(f"watching the bus for {seconds:g} s (listing only: nothing is opened or sent; a listing every "
        f"{bus.POLL * 1000:.0f} ms)")
    end, on, seen, gone = bus.now() + seconds, {RECOVERY}, [], None
    while True:
        now, at = bus.present(), bus.now()
        for d in sorted(now - on):
            log(f"{d[0]:04X}:{d[1]:04X} appeared: {WATCHED[d]}")
            seen.append(d)
        for d in sorted(on - now):
            timed = f", seen gone {since(at)}" if d == RECOVERY else ""
            log(f"{d[0]:04X}:{d[1]:04X} left the bus: {WATCHED[d]}{timed}")
            if d == RECOVERY and gone is None:
                gone = at
        on = now
        if until in on or bus.now() >= end:
            return seen, gone
        bus.sleep(bus.POLL)


def came_back(seen, watch, log):
    """What the pedal started after it left the recovery mode, in words."""
    for d in seen[:1]:
        log(f"after leaving, the pedal came back as {d[0]:04X}:{d[1]:04X}, {WATCHED[d]}: {AFTER_DEPARTURE[d]}")
    if not seen:
        log(f"nothing appeared within {watch:g} s: the pedal powered off or hung")


def left_bus(bus, error):
    """Did a failed transfer mean the pedal left the bus? A listing only: nothing more is sent to it."""
    return isinstance(error, DeviceGone) or RECOVERY not in bus.present()


def run(bus, sync, leave, control_reply, watch, log):
    """The probe, then the leave when asked, then the bus watch. Returns the exit code."""
    dev = bus.open_recovery()
    if dev is None:
        log(f"no recovery device ({VID:04X}:{PID:04X}) found. Power the pedal off, hold HOME, the right footswitch and "
            "the knob's PUSH, power it on and keep holding until the screen shows RECOVERY, then run this again")
        return 1
    found = bus.now()
    stamped = lambda m: log(f"[{(bus.now() - found) * 1000:6.0f} ms] {m}")
    session = Recovery(dev, stamped, bus.now)
    hello = refused = None
    sent = False
    try:
        stamped(f"found {VID:04X}:{PID:04X} {dev.manufacturer!r} {dev.product!r}, device version {dev.bcd_device:#06x}")
        try:
            hello, bulk = session.probe(sync)
        except ScsiError as e:
            if not left_bus(bus, e):
                raise
            stamped(f"the pedal left the bus ({e}): the recovery mode ended on its own, {session.since(bus.now())}; "
                    "nothing more is sent")
        if hello is not None:
            describe(hello, bulk, stamped)
            if not leave:
                stamped("read-only probe finished: nothing was written; the bus watch shows whether the recovery mode "
                        "ends on its own")
            elif bulk is not None and not control_reply:
                refused = GuardError("the hello reply did not come over the bulk IN endpoint, and the pedal acts on "
                                     "command 6 only after its reply has been read there")
                stamped("leave: not sent (refused, see the end); the bus watch shows whether the recovery mode ends on "
                        "its own")
            else:
                if bulk is not None:
                    stamped("leave: sent although the hello reply came over the control endpoint only "
                            "(--accept-control-reply); the one real pedal tried acted on it all the same")
                try:
                    r = session.leave(hello)
                except ScsiError as e:
                    if not left_bus(bus, e):
                        raise
                    stamped(f"the pedal left the bus ({e}), {session.since(bus.now())}")
                    r = None
                sent = True
                stamped("leave: " + ("accepted, the pedal resets" if r else "sent; its reply did not arrive"))
    finally:
        dev.close()
        stamped("released the recovery device")
    seen, gone = watch_bus(bus, watch, stamped, session.since, until=UBOOT if sent else None)
    if gone is not None:
        came_back(seen, watch, stamped)
    if refused:
        raise refused
    if sent:
        if UBOOT in seen:
            stamped(f"the chip's USB boot state ({ur.VID:04X}:{ur.PID:04X}) appeared: tools/uboot_rescue.py takes over")
            return 0
        if gone is None:
            stamped(f"the pedal stayed in the recovery mode for {watch:g} s after command 6: it did not act on it. "
                    "Nothing was written; send this output back")
            return 5
        stamped(f"the USB boot state ({ur.VID:04X}:{ur.PID:04X}) did not appear within {watch:g} s. If the pedal "
                "restarted into its firmware, the core reset does not reach the USB boot state: stop and write nothing "
                "to this pedal (docs/RESCUE.md)")
        return 3
    if gone is None and hello is not None:
        stamped(f"the pedal stayed in the recovery mode for the whole watch ({watch:g} s): it did not end on its own")
        return 0
    stamped("send this output back: it shows when the recovery mode ended and what the pedal starts next")
    return 4


# ---------------------------------------------------------------- USB: libusb through ctypes, as tools/uboot_rescue.py
def vendor_endpoints(config):
    """(interface, bulk in, bulk out) of the vendor-specific (class 0xFF) interface in a raw configuration descriptor."""
    iface, eps, i = None, {}, 0
    while i + 2 <= len(config) and config[i]:
        kind = config[i + 1]
        if kind == 4:
            iface = config[i + 2] if config[i + 5] == 0xFF else None
        elif kind == 5 and iface is not None and config[i + 3] & 3 == 2:
            eps["in" if config[i + 2] & 0x80 else "out"] = config[i + 2]
        i += config[i]
    if iface is None or len(eps) != 2:
        raise RescueError("no vendor interface with two bulk endpoints on the recovery device")
    return iface, eps["in"], eps["out"]


class LibusbBus:
    POLL = 0.1
    now, sleep = staticmethod(time.monotonic), staticmethod(time.sleep)

    def __init__(self):
        self.usb = ur.Libusb()
        self.lib = self.usb.lib

    def _find(self, vid, pid, use):
        devs = ctypes.POINTER(ctypes.c_void_p)()
        n = self.lib.libusb_get_device_list(self.usb.ctx, ctypes.byref(devs))
        try:
            for i in range(max(n, 0)):
                desc = ur.DevDesc()
                if self.lib.libusb_get_device_descriptor(devs[i], ctypes.byref(desc)) == 0 and \
                        (desc.idVendor, desc.idProduct) == (vid, pid):
                    return use(devs[i], desc)
        finally:
            self.lib.libusb_free_device_list(devs, 1)
        return None

    def present(self):
        """The WATCHED devices on the bus now. Reads device descriptors only; opens nothing."""
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

    def open_recovery(self):
        return self._find(VID, PID, self._claim)

    def _claim(self, dev, desc):
        handle = ctypes.c_void_p()
        code = self.lib.libusb_open(dev, ctypes.byref(handle))
        if code < 0:
            raise RescueError(f"cannot open the recovery device ({self.usb.name(code)}). On Linux it needs a udev rule "
                              "or root; on macOS send this output to whoever helps you")
        buf = ctypes.create_string_buffer(512)
        got = self.lib.libusb_control_transfer(handle, 0x80, 6, 2 << 8, 0, buf, 512, 1000)
        if got < 9:
            self.lib.libusb_close(handle)
            raise RescueError("the recovery device did not give its configuration")
        iface, ep_in, ep_out = vendor_endpoints(buf.raw[:got])
        code = self.lib.libusb_claim_interface(handle, iface)
        if code < 0:
            self.lib.libusb_close(handle)
            raise RescueError(f"cannot claim the recovery device's interface ({self.usb.name(code)}). Another program "
                              "may hold it; close it and run this again")
        return LibusbRecovery(self.usb, handle, iface, ep_in, ep_out, desc)


class LibusbRecovery:
    def __init__(self, usb, handle, iface, ep_in, ep_out, desc):
        self.usb, self.lib, self.handle, self.iface, self.ep_in, self.ep_out = usb, usb.lib, handle, iface, ep_in, ep_out
        self.bcd_device = desc.bcdDevice
        self.manufacturer, self.product = self._string(desc.iManufacturer), self._string(desc.iProduct)

    def _string(self, index):
        if not index:
            return ""
        buf = ctypes.create_string_buffer(255)
        got = self.lib.libusb_control_transfer(self.handle, 0x80, 6, 3 << 8 | index, 0x0409, buf, 255, 1000)
        return buf.raw[2:got].decode("utf-16-le", "replace") if got > 2 else ""

    def _check(self, code, what):
        if code == ur.E_NO_DEVICE:
            raise DeviceGone("the pedal left the bus")
        if code == ur.E_TIMEOUT:
            raise Timeout(f"{what}: {self.usb.name(code)}")
        if code < 0:
            raise ScsiError(f"{what}: {self.usb.name(code)}")
        return code

    def control_in(self, request, n):
        """A vendor IN request with wValue and wIndex 0, as the recovery code requires; only those of REQUESTS."""
        if REQUESTS.get(request) != n:
            raise GuardError(f"vendor request {request:#x} of {n} bytes is not one this tool sends")
        buf = ctypes.create_string_buffer(n)
        got = self._check(self.lib.libusb_control_transfer(self.handle, 0xC1, request, 0, 0, buf, n, 500),
                          f"vendor request {request:#x}")
        return buf.raw[:got]

    def _bulk(self, ep, buf, n, ms, what):
        done = ctypes.c_int()
        self._check(self.lib.libusb_bulk_transfer(self.handle, ep, buf, n, ctypes.byref(done), ms), what)
        return done.value

    def bulk_out(self, data):
        """One transfer, never followed by a zero-length packet: one would drop the frame."""
        if self._bulk(self.ep_out, ctypes.create_string_buffer(data, len(data)), len(data), 1000, "frame") != len(data):
            raise ScsiError("the frame was not taken whole")

    def bulk_in(self, n, ms):
        buf = ctypes.create_string_buffer(n)
        return buf.raw[:self._bulk(self.ep_in, buf, n, ms, "reply")]

    def close(self):
        self.lib.libusb_release_interface(self.handle, self.iface)
        self.lib.libusb_close(self.handle)


def transport():
    return LibusbBus()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only helper for M-VAVE's recovery mode (V22/V23 boot loader, USB 3654:7940).")
    ap.add_argument("--sync", action="store_true",
                    help="send the sync request 0x42 before the hello (the second entry of a probe session)")
    ap.add_argument("--leave", action="store_true",
                    help="after the probe, send command 6, the leave to the chip's USB boot state")
    ap.add_argument("--accept-inferred", action="store_true",
                    help="with --leave: send it although its result is proven on one pedal only (see the text --leave "
                         "prints)")
    ap.add_argument("--accept-control-reply", action="store_true",
                    help="with --leave --accept-inferred: send command 6 also when the hello reply came over the "
                         "control endpoint (request 0x43) only, as the one real pedal tried did")
    ap.add_argument("--watch", type=float, default=60,
                    help="seconds to list the USB devices after the probe or the leave, to see whether and when the "
                         "pedal leaves the recovery mode and what it starts next (default 60)")
    a = ap.parse_args(argv)
    if a.accept_inferred and not a.leave:
        ap.error("--accept-inferred goes with --leave")
    if a.accept_control_reply and not (a.leave and a.accept_inferred):
        ap.error("--accept-control-reply goes with --leave --accept-inferred")
    if a.leave and not a.accept_inferred:
        print(LEAVE_TEXT)
        return 2
    log = lambda m: print(m, flush=True)
    try:
        return run(transport(), a.sync, a.leave, a.accept_control_reply, a.watch, log)
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
