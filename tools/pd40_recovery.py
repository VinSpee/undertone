#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""pd40_recovery.py - a read-only helper for M-VAVE's recovery mode on a BlackBox with the V22 or V23 boot loader.

M-VAVE's V22/V23 boot loader carries a recovery mode of its own: the screen shows RECOVERY and the pedal is a WinUSB
device, USB 3654:7940 "PD40 BOOT Recovery". It starts when the three controls HOME, the right footswitch and the knob's
PUSH are held at power-on, when the stock V23 app receives the SysEx F0 22 24 35 7D F7, or when an app returns to the
boot loader. On such a pedal the chip's USB boot state (4C4A:8057), where tools/uboot_rescue.py works, is no longer
reached the old way. This tool reads what the recovery mode says about the pedal and, when asked, sends the one command
that leaves it for the USB boot state. docs/RESCUE.md, "A pedal on M-VAVE's V22 or V23", has the steps.

  tools/pd40_recovery.py                              read-only probe: find 3654:7940, its sync request, hello
  tools/pd40_recovery.py --leave --accept-inferred    the probe, then command 6: leave to the chip's USB boot state

It never writes to the pedal's flash. The protocol's write commands (2 manifest, 3 block, 4 erase and commit, 5 start
the new app) and every vendor request but the sync are refused before anything is sent; frames carry no payload. The
protocol was read in the V23 boot loader's code (frames of 4608 bytes from "SBU2", 64-byte replies from "SBR2", CRC-32
as zlib's). That the chip's ROM then stays in its USB boot state is inferred, not proven: --leave stops with the
explanation unless --accept-inferred is given too.

One-time install (macOS): `brew install libusb`. The recovery device's interface is vendor-specific and no macOS driver
holds it, so the probe should need no sudo (not yet tried on a real pedal). tools/uboot_rescue.py, which takes over
after --leave, needs sudo. Linux and Windows have not been tried; on Windows set LIBUSB_PATH to libusb-1.0.dll.
Exit codes: 0 done, 1 setup problem or no recovery device, 2 refused or a bad answer (nothing more was sent),
3 the pedal left the recovery mode but the USB boot state did not appear, 130 stopped by Ctrl-C.
"""
import argparse, ctypes, struct, sys, time, zlib
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import uboot_rescue as ur
from uboot_rescue import DeviceGone, GuardError, RescueError, ScsiError

VID, PID = 0x3654, 0x7940
FRAME, REPLY = 4608, 64                        # a frame is always 4608 bytes; a reply 64
SYNC = 0x42                                    # vendor IN request (bmRequestType 0xC1): restarts the endpoints, "SBU2"
HELLO, MANIFEST, BLOCK, COMMIT, START_APP, LEAVE = 1, 2, 3, 4, 5, 6
ALLOWED = frozenset({HELLO, LEAVE})            # the only commands this tool can send; neither carries data
WRITES = {MANIFEST: "manifest", BLOCK: "block", COMMIT: "erase and commit", START_APP: "start the new app"}
PROTOCOL = (0x07910040, 0x00020000, 0x6000, 0x9F000)   # constants and the write range [base, limit) every reply carries
HEADS = {0xB19D96A1: "M-VAVE V22 or V23 (the boot area of both official packages)"}
STATUS = {0: "accepted", 1: "malformed", 2: "wrong state", 4: "out of range", 5: "boot CRC is not this pedal's",
          6: "CRC error", 7: "flash error", 8: "block out of order"}
LEAVE_STATES = (0, 6)                          # command 6 is accepted in these states only


class BadAnswer(GuardError):
    """The device answered in a way the protocol does not allow. Nothing more is sent to it."""


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
    words: tuple                               # three more state words, not identified


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


class Recovery:
    """The recovery protocol over a transport: dev.control_in(request, n), dev.bulk_out(data), dev.bulk_in(n)."""

    def __init__(self, dev):
        self.dev, self.tag = dev, 0

    def sync(self):
        got = self.dev.control_in(SYNC, 4)
        if got != b"SBU2":
            raise BadAnswer(f"the sync request answered {bytes(got)!r}, not 'SBU2'")

    def command(self, command):
        data = frame(command, self.tag + 1)
        self.tag += 1
        self.dev.bulk_out(data)
        return parse_reply(self.dev.bulk_in(REPLY), command, self.tag)

    def hello(self):
        r = self.command(HELLO)
        if r.status:
            raise BadAnswer(f"hello was answered with status {r.status} ({STATUS.get(r.status, 'unknown')})")
        return r

    def leave(self, hello):
        """Command 6. The pedal replies, then writes usb_update_mode to RAM and resets; a lost reply is not an error."""
        if hello.state not in LEAVE_STATES:
            raise GuardError(f"the recovery mode is in state {hello.state}: another tool started an update, and "
                             "command 6 is refused there. Power-cycle the pedal into the recovery mode again first")
        try:
            r = self.command(LEAVE)
        except (DeviceGone, ScsiError):
            return None
        if r.status:
            raise BadAnswer(f"leave was answered with status {r.status} ({STATUS.get(r.status, 'unknown')})")
        return r


def describe(r, log):
    head = HEADS.get(r.boot_crc, "not a head this tool knows: the pedal's head is not an official V22/V23 head")
    log(f"hello: status {r.status} ({STATUS[0]}), state {r.state}"
        + (" (no update started)" if r.state == 0 else " (an update was started by another tool)"))
    log(f"  boot area [0, {r.base:#x}) CRC-32 {r.boot_crc:#010x}: {head}")
    log(f"  write range [{r.base:#x}, {r.limit:#x}), protocol constants {r.constants[0]:#010x} {r.constants[1]:#010x}")
    log(f"  image length {r.image_length:#x}, next offset {r.next_offset:#x}, other words "
        + " ".join(f"{w:#x}" for w in r.words))
    log("  not reported by the protocol: the chip key and the flash id. The recovery mode starts only on a 1 MiB flash "
        "with id EB 60 14 or 85 60 14; tools/uboot_rescue.py prints both after --leave")


LEAVE_TEXT = """\
--leave sends command 6. What is read in the V23 boot loader's code: the recovery mode answers, writes the word
usb_update_mode to RAM (not to the flash) and resets the chip. What is inferred, not proven: that the chip's ROM then
stays in its USB boot state (4C4A:8057) instead of starting the boot loader again. Nobody has run it on a real pedal.
If the inference is wrong the pedal simply restarts into its firmware; nothing is written either way. Then there is
no way from this pedal to the USB boot state: stop and write nothing to it.

Start the rescue tool first, in a second Terminal, so it is waiting when the USB boot state appears:
    sudo python3 tools/uboot_rescue.py --package firmware/BlackBox_023.fwsc
Then run this again with --leave --accept-inferred. Nothing was sent to the pedal."""


def watch_for_uboot(bus, seconds, log):
    """After the leave: does 4C4A:8057 appear within seconds? Only looks at the bus; opens nothing."""
    end = time.monotonic() + seconds
    while True:
        if bus.uboot_present():
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(bus.POLL)


def run(bus, leave, watch, log):
    """The probe, then the leave when asked. Returns the exit code."""
    dev = bus.open_recovery()
    if dev is None:
        log(f"no recovery device ({VID:04X}:{PID:04X}) found. Power the pedal off, hold HOME, the right footswitch and "
            "the knob's PUSH, power it on and keep holding until the screen shows RECOVERY, then run this again")
        return 1
    try:
        log(f"found {VID:04X}:{PID:04X} {dev.manufacturer!r} {dev.product!r}, device version {dev.bcd_device:#06x}")
        session = Recovery(dev)
        session.sync()
        log("sync: SBU2")
        hello = session.hello()
        describe(hello, log)
        if not leave:
            log("read-only probe finished: nothing was written, the pedal stays in the recovery mode")
            return 0
        r = session.leave(hello)
        log("leave: " + ("accepted, the pedal resets" if r else "sent; the pedal left before its reply arrived"))
    finally:
        dev.close()
    if watch_for_uboot(bus, watch, log):
        log(f"the chip's USB boot state ({ur.VID:04X}:{ur.PID:04X}) appeared: tools/uboot_rescue.py takes over")
        return 0
    log(f"the USB boot state ({ur.VID:04X}:{ur.PID:04X}) did not appear within {watch:g} s. If the pedal restarted into "
        "its firmware, the inference behind --leave is wrong: stop and write nothing to this pedal (docs/RESCUE.md)")
    return 3


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

    def uboot_present(self):
        return bool(self._find(ur.VID, ur.PID, lambda dev, desc: True))

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
        if code < 0:
            raise ScsiError(f"{what}: {self.usb.name(code)}")
        return code

    def control_in(self, request, n):
        if request != SYNC:
            raise GuardError(f"vendor request {request:#x} is not one this tool sends")
        buf = ctypes.create_string_buffer(n)
        got = self._check(self.lib.libusb_control_transfer(self.handle, 0xC1, request, 0, self.iface, buf, n, 1000),
                          "sync request")
        return buf.raw[:got]

    def _bulk(self, ep, buf, n, what):
        done = ctypes.c_int()
        self._check(self.lib.libusb_bulk_transfer(self.handle, ep, buf, n, ctypes.byref(done), 2000), what)
        return done.value

    def bulk_out(self, data):
        if self._bulk(self.ep_out, ctypes.create_string_buffer(data, len(data)), len(data), "frame") != len(data):
            raise ScsiError("the frame was not taken whole")

    def bulk_in(self, n):
        buf = ctypes.create_string_buffer(n)
        return buf.raw[:self._bulk(self.ep_in, buf, n, "reply")]

    def close(self):
        self.lib.libusb_release_interface(self.handle, self.iface)
        self.lib.libusb_close(self.handle)


def transport():
    return LibusbBus()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only helper for M-VAVE's recovery mode (V22/V23 boot loader, USB 3654:7940).")
    ap.add_argument("--leave", action="store_true", help="after the probe, send command 6: leave to the chip's USB boot state")
    ap.add_argument("--accept-inferred", action="store_true",
                    help="with --leave: send it although its result is inferred, not proven (see the text --leave prints)")
    ap.add_argument("--watch", type=float, default=15, help="seconds to look for the USB boot state after --leave (default 15)")
    a = ap.parse_args(argv)
    if a.accept_inferred and not a.leave:
        ap.error("--accept-inferred goes with --leave")
    if a.leave and not a.accept_inferred:
        print(LEAVE_TEXT)
        return 2
    log = lambda m: print(m, flush=True)
    try:
        return run(transport(), a.leave, a.watch, log)
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
