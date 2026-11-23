# SPDX-License-Identifier: GPL-3.0-only
"""A simulated BlackBox in M-VAVE's recovery mode (USB 3654:7940), for tests/test_pd40_recovery.py (no hardware).

It answers as the V23 boot loader's recovery code was read to answer, packet by packet. The bulk OUT endpoint takes
packets of 1 to 64 bytes into a 4608-byte frame from "SBU2"; a zero-length packet drops the partial frame, and no packet
is taken while a reply waits unread. A complete frame composes a 64-byte reply from "SBR2", with a CRC-32 over its first
60 bytes, into the reply buffer and arms the bulk IN endpoint with it, unless a packet is armed there already. The
vendor requests are 0x42 (sync), 0x43 (the reply buffer) and 0x44 (the first 24 bytes of the frame buffer).

Two behaviours of the real pedal on V23 are reproduced by default. The sync request's flush of the idle IN endpoint
leaves an empty 64-byte packet armed, so the reply to the next frame is never sent: the old probe's sync and hello get 64
zero bytes, then nothing (in_zeros instead sends zeros in place of every reply; swallows=False sends the reply after
the empty packet). And one failed access to the USB
controller (sie_fails_at, counted in the computer's transfers) ends the mode at once: the pedal leaves the bus, as
command 6 does once its reply has been read, and after reset_s seconds comes back as after_reset: "uboot" (the chip's
USB boot state), "recovery", "app" (the stock V23 app) or None.

It keeps every transfer; the write commands 2 to 5 are also kept in write_attempts, which the tests require to stay
empty. A fault makes it answer badly in one way; "partial" loses the frame's last packet and "deaf" takes none.
"""
import struct, sys, zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import pd40_recovery as pr
from uboot_rescue import DeviceGone, ScsiError

V23_BOOT_CRC = 0xB19D96A1
FAULTS = ("sync", "silent", "short", "magic", "crc", "tag", "command", "constants", "status", "stall", "partial", "deaf")
AFTER_RESET = {"uboot": pr.UBOOT, "recovery": pr.RECOVERY, "app": pr.APP, None: None}


class SimRecovery:
    manufacturer, product, bcd_device = "SINCO", "PD40 BOOT Recovery", 0x0100

    def __init__(self, state=0, boot_crc=V23_BOOT_CRC, fault=None, in_zeros=False, swallows=True, sie_fails_at=None,
                 after_reset="uboot", reset_s=0.5):
        assert fault in (None, *FAULTS) and after_reset in AFTER_RESET
        self.state, self.boot_crc, self.fault, self.in_zeros, self.swallows = state, boot_crc, fault, in_zeros, swallows
        self.sie_fails_at, self.after_reset, self.reset_s = sie_fails_at, after_reset, reset_s
        self.transfers, self.frames, self.write_attempts, self.requests = [], [], [], []
        self.accumulated, self.armed, self.waiting = b"", [], False   # armed: the packets queued on bulk IN
        self.last_reply, self.frame_buffer = bytes(64), bytes(pr.FRAME)
        self.present, self.left, self.closed, self.departed_at = True, False, False, None
        self.clock = lambda: 0.0                  # the bus's, once on one

    def close(self):
        self.closed = True

    def access(self, kind, *what):
        """Every transfer of the computer: the pedal must be there, and one failed access ends the mode."""
        if not self.present:
            raise DeviceGone("gone")
        self.transfers.append((kind, *what))
        if self.sie_fails_at is not None and len(self.transfers) >= self.sie_fails_at:
            self.depart()
            raise DeviceGone("gone")

    def control_in(self, request, n):
        self.access("control", request, n)
        self.requests.append(request)
        if self.fault == "stall":
            raise ScsiError("stall")
        if request == 0x42 and n == 4:
            self.accumulated, self.waiting = b"", False
            if not self.armed:
                self.armed = [bytes(64)]          # the flush of an idle endpoint arms an empty packet
            return b"SBUX" if self.fault == "sync" else b"SBU2"
        if request == 0x43 and n == 64:
            return self.last_reply
        if request == 0x44 and n == 24:
            return self.frame_buffer[:24]
        raise ScsiError("stall")

    def bulk_out(self, data):
        data = bytes(data)
        self.access("bulk out", len(data))
        if self.waiting:
            raise pr.Timeout("frame: the pedal takes no packet while a reply waits")
        if not data:
            self.accumulated = b""                # a zero-length packet drops the partial frame
            return
        if self.fault == "deaf":
            return
        for i in range(0, len(data) - (64 if self.fault == "partial" else 0), 64):
            self.accumulated += data[i:i + 64]
            self.frame_buffer = self.accumulated + self.frame_buffer[len(self.accumulated):]
            if len(self.accumulated) == pr.FRAME:
                self.frames.append(self.accumulated)
                self.accumulated = b""
                self.handle(self.frames[-1])

    def handle(self, data):
        magic, command, tag, arg, length, crc = struct.unpack("<4sIIIII", data[:24])
        if magic != b"SBU2":
            return self.reply(0, 0, 1)
        if length > 4096 or zlib.crc32(data[24:24 + length]) != crc:
            return self.reply(command, tag, 1)
        if command in (2, 3, 4, 5):
            self.write_attempts.append(command)
            return self.reply(command, tag, 2)
        if command == 1:
            return self.reply(command, tag, 0 if arg | length == 0 else 1)
        if command == 6:
            if arg | length:
                return self.reply(command, tag, 1)
            if self.state not in (0, 6):
                return self.reply(command, tag, 2)
            self.left = True
            return self.reply(command, tag, 0)
        return self.reply(command, tag, 1)

    def reply(self, command, tag, status):
        if self.fault == "status" and command == 1:
            status = 1
        words = [command, tag, status, self.state, 0, 0, 0x07910040, 0x00020000, 0x6000, 0x9F000, self.boot_crc, 0, 0, 0]
        if self.fault == "constants":
            words[7] = 0x00030000
        if self.fault == "tag":
            words[1] += 1
        if self.fault == "command":
            words[0] = 9
        raw = struct.pack("<4s14I", b"SBR2", *words)
        if self.fault == "magic":
            raw = b"SBR3" + raw[4:]
        raw += struct.pack("<I", zlib.crc32(raw) ^ (1 if self.fault == "crc" else 0))
        self.last_reply, self.waiting = raw, True
        if (not self.armed or not self.swallows) and self.fault != "silent":
            self.armed.append(bytes(64) if self.in_zeros else raw[:32] if self.fault == "short" else raw)

    def bulk_in(self, n, ms):
        self.access("bulk in", n)
        if not self.armed:
            raise pr.Timeout("timeout")           # macOS then clears the halt, which flushes an empty endpoint
        raw = self.armed.pop(0)
        self.waiting = bool(self.armed)
        if self.left:
            self.depart()                         # command 6 acts once its reply has been read
        return raw[:n]

    def depart(self):
        """usb_update_mode and a core reset: off the bus, then after reset_s seconds whatever starts next."""
        self.present, self.armed, self.departed_at = False, [], self.clock()


class SimBus:
    """The computer's USB bus with the pedal on it, or nothing (device None). Its clock moves only when it sleeps."""
    POLL = 0.1

    def __init__(self, device=None):
        self.device, self.opened, self.looked, self.t = device, 0, 0, 0.0
        if device is not None:
            device.clock = self.now

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def open_recovery(self):
        if self.device is None or not self.device.present:
            return None
        self.opened += 1
        return self.device

    def present(self):
        self.looked += 1
        d = self.device
        if d is None:
            return set()
        if d.present:
            return {pr.RECOVERY}
        after = AFTER_RESET[d.after_reset]
        return {after} if after and self.t >= d.departed_at + d.reset_s else set()
