# SPDX-License-Identifier: GPL-3.0-only
"""A simulated BlackBox in M-VAVE's recovery mode (USB 3654:7940), for tests/test_pd40_recovery.py (no hardware).

It answers as the V23 boot loader's recovery code was read to answer: the sync request 0x42, frames of exactly 4608
bytes from "SBU2" on the bulk OUT endpoint, a 64-byte reply from "SBR2" with a CRC-32 over its first 60 bytes. Command 6
in state 0 or 6 replies, then the pedal leaves the bus and the chip's USB boot state appears (or not, with
rom_ignores_mark). It keeps every frame it took; the write commands 2 to 5 are also kept in write_attempts, which the
tests require to stay empty. A fault makes it answer badly in one way.
"""
import struct, sys, zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import pd40_recovery as pr
from uboot_rescue import DeviceGone, ScsiError

V23_BOOT_CRC = 0xB19D96A1
FAULTS = ("sync", "silent", "short", "magic", "crc", "tag", "command", "constants", "status")


class SimRecovery:
    manufacturer, product, bcd_device = "SINCO", "PD40 BOOT Recovery", 0x0100

    def __init__(self, state=0, boot_crc=V23_BOOT_CRC, fault=None, rom_ignores_mark=False, reply_to_leave=True):
        assert fault in (None, *FAULTS)
        self.state, self.boot_crc, self.fault = state, boot_crc, fault
        self.rom_ignores_mark, self.reply_to_leave = rom_ignores_mark, reply_to_leave
        self.frames, self.write_attempts, self.requests = [], [], []
        self.pending, self.last_reply, self.last_frame = None, bytes(64), bytes(24)
        self.present, self.left, self.uboot, self.closed = True, False, False, False

    def close(self):
        self.closed = True

    def control_in(self, request, n):
        if not self.present:
            raise DeviceGone("gone")
        self.requests.append(request)
        if request == 0x42:
            self.pending = None                    # restarts the endpoints
            return b"SBUX" if self.fault == "sync" else b"SBU2"
        if request == 0x43:
            return self.last_reply[:n]
        if request == 0x44:
            return self.last_frame[:n]
        raise ScsiError("stall")

    def bulk_out(self, data):
        if not self.present:
            raise DeviceGone("gone")
        data = bytes(data)
        self.frames.append(data)
        self.last_frame = data[:24]
        if len(data) != pr.FRAME:
            return                                 # not a frame: no reply
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
            return self.reply(command, tag, 0) if self.reply_to_leave else self.leave_now()
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
        self.last_reply = raw
        self.pending = raw[:32] if self.fault == "short" else raw

    def leave_now(self):
        """The recovery code writes usb_update_mode to RAM and resets: off the bus, then the ROM's USB boot state."""
        self.present, self.pending = False, None
        self.uboot = not self.rom_ignores_mark

    def bulk_in(self, n):
        if not self.present:
            raise DeviceGone("gone")
        if self.pending is None or self.fault == "silent":
            raise ScsiError("timeout")
        raw, self.pending = self.pending, None
        if self.left:
            self.leave_now()
        return raw[:n]


class SimBus:
    """The computer's USB bus with the pedal on it, or nothing (device None)."""
    POLL = 0

    def __init__(self, device=None):
        self.device, self.opened, self.looked = device, 0, 0

    def open_recovery(self):
        if self.device is None or not self.device.present:
            return None
        self.opened += 1
        return self.device

    def uboot_present(self):
        self.looked += 1
        return bool(self.device and self.device.uboot)
