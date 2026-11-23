# SPDX-License-Identifier: GPL-3.0-only
"""A simulated BlackBox in M-VAVE's recovery mode (USB 3654:7940), for tests/test_pd40_recovery.py and
tests/test_pd40_install.py (no hardware).

It answers as the V23 boot loader's recovery code was read to answer, packet by packet. The bulk OUT endpoint takes
packets of 1 to 64 bytes into a 4608-byte frame from "SBU2"; a zero-length packet drops the partial frame, and no packet
is taken while a reply waits unread. A complete frame composes a 64-byte reply from "SBR2", with a CRC-32 over its first
60 bytes, into the reply buffer and arms the bulk IN endpoint with it, unless a packet is armed there already. The
vendor requests are 0x42 (sync), 0x43 (the reply buffer) and 0x44 (the first 24 bytes of the frame buffer).

Two behaviours of the real pedal on V23 are reproduced by default. The sync request's flush of the idle IN endpoint
leaves an empty 64-byte packet armed, so the reply to the next frame is never sent: the old probe's sync and hello get 64
zero bytes, then nothing (in_zeros instead sends zeros in place of every reply, and zeros_for in place of the replies
to those commands, while the reply buffer holds the real reply, as on the real pedal; reading the zeros counts as
reading the reply; swallows=False sends the reply after the empty packet). And one failed access to the USB
controller (sie_fails_at, counted in the computer's transfers) ends the mode at once: the pedal leaves the bus, as
command 6 does once its reply has been read, and after reset_s seconds comes back as after_reset: "uboot" (the chip's
USB boot state), "recovery", "app" (the stock V23 app), "gamut" or None. Two more departures can be set: exits_after
ends the mode on its own that many seconds after the computer's last access, as a real pedal on V23 did within seconds
of a probe that sent no leave, and stays makes the pedal answer command 6 without ever acting on it. A bulk IN read that
times out takes its whole timeout on the bus's clock.

It keeps every transfer; the write commands 2 to 5 are also kept in write_attempts, which the read-only helper's tests
require to stay empty. A fault makes it answer badly in one way; "partial" loses the frame's last packet and "deaf" takes
none.

Given a flash (flash=), it also runs the write commands as the V23 boot loader's code was read to run them, on that
flash: 2 the manifest, 3 a block (only checked in state 1; erased, programmed and read back in state 3, where block 0 is
kept in RAM), 4 with argument 2 the erase of the sector at 0x6000 and with argument 4 the commit (block 0 written last),
5 the start of the new app. Its flash driver refuses every erase and program outside [0x6000, 0x9F000). After command 5
the pedal comes back as whatever v23_boot finds on the flash: the app's own USB device, or nothing when the boot loader
would not start it. Without a flash the write commands are answered "wrong state" and change nothing.
"""
import struct, sys, zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import pd40_recovery as pr
import pocketx_fw as fw
from uboot_rescue import DeviceGone, ScsiError

V23_BOOT_CRC = 0xB19D96A1
FAULTS = ("sync", "silent", "short", "magic", "crc", "tag", "command", "constants", "status", "stall", "partial", "deaf")
GAMUT = (0x1209, 0x0001)                          # the USB device of Gamut and of every firmware of this project
AFTER_RESET = {"uboot": pr.UBOOT, "recovery": pr.RECOVERY, "app": pr.APP, "gamut": GAMUT, None: None}
FLASH_SIZE, BASE, LIMIT, BLOCK, ENTRY = 0x100000, 0x6000, 0x9F000, 4096, 0x02000120


def v23_boot(flash):
    """What the V22/V23 boot loader starts (its function 0x1164, as read): the flash header under the key 0xFFFF, the
    head's entries up to app_dir_head, each by its CRC16, then the first 32 bytes at that entry's address under the
    chip key. Nothing else is checked. Returns (the app area's address, the entry address), or None: the boot loader
    then resets the chip again and again."""
    hdr = fw.enc(flash[:32])
    if fw.crc16(hdr[2:32]) != struct.unpack_from("<H", hdr)[0]:
        return None
    o = 0x20
    while True:
        e = fw.jlfs_entry(fw.enc(flash[o:o + 32]), 0)
        if not e["hdr_ok"]:
            return None
        if e["name"] == "app_dir_head":
            break
        o += 32
    head = fw.jlfs_entry(fw.sfc(flash[e["addr"]:e["addr"] + 32], 0), 0)
    return (e["addr"], head["addr"]) if head["hdr_ok"] else None


class SimRecovery:
    manufacturer, product, bcd_device = "SINCO", "PD40 BOOT Recovery", 0x0100

    def __init__(self, state=0, boot_crc=None, fault=None, in_zeros=False, swallows=True, sie_fails_at=None,
                 after_reset="uboot", reset_s=0.5, sie_error=DeviceGone, flash=None, fails_at=None,
                 exits_after=None, stays=False, zeros_for=()):
        assert fault in (None, *FAULTS) and after_reset in AFTER_RESET
        self.flash = None if flash is None else bytearray(bytes(flash).ljust(FLASH_SIZE, b"\xFF"))
        if boot_crc is None:                      # computed over the flash at entry, as read
            boot_crc = V23_BOOT_CRC if flash is None else zlib.crc32(self.flash[:BASE])
        self.state, self.boot_crc, self.fault, self.in_zeros, self.swallows = state, boot_crc, fault, in_zeros, swallows
        self.zeros_for = frozenset(zeros_for)     # the commands whose replies come as zeros on bulk IN
        self.sie_fails_at, self.after_reset, self.reset_s = sie_fails_at, after_reset, reset_s
        self.sie_error = sie_error                # what the computer sees of the failed access
        self.fails_at = fails_at                  # a flash address whose program fails (status 7)
        self.exits_after, self.stays, self.last_access = exits_after, stays, 0.0
        self.transfers, self.frames, self.write_attempts, self.requests = [], [], [], []
        self.accumulated, self.armed, self.waiting = b"", [], False   # armed: the packets queued on bulk IN
        self.last_reply, self.frame_buffer = bytes(64), bytes(pr.FRAME)
        self.present, self.left, self.starting, self.closed, self.departed_at = True, False, False, False, None
        self.next_device = None
        self.manifest, self.table, self.length, self.image_crc, self.word = None, [], 0, 0, 0
        self.next, self.running, self.last_block, self.block0 = 0, 0, None, None
        self.erase_started, self.flash_error = 0, 0
        self.erased, self.programmed, self.refused = [], [], []
        self.clock, self.wait = (lambda: 0.0), (lambda s: None)   # the bus's, once on one

    def close(self):
        self.closed = True

    def access(self, kind, *what):
        """Every transfer of the computer: the pedal must be there, and one failed access ends the mode."""
        self.tick()
        if not self.present:
            raise DeviceGone("gone")
        self.last_access = self.clock()
        self.transfers.append((kind, *what))
        if self.sie_fails_at is not None and len(self.transfers) >= self.sie_fails_at:
            self.depart()
            raise self.sie_error("gone")

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
        payload = data[24:24 + length]
        if length > 4096 or zlib.crc32(payload) != crc:
            return self.reply(command, tag, 1)
        if command in (2, 3, 4, 5):
            self.write_attempts.append(command)
            if self.flash is None:
                return self.reply(command, tag, 2)
        run = {1: self.hello, 2: self.take_manifest, 3: self.block, 4: self.erase_or_commit, 5: self.start,
               6: self.leave}.get(command)
        return self.reply(command, tag, run(arg, payload) if run else 1)

    def hello(self, arg, payload):
        return 1 if arg or payload else 0

    def leave(self, arg, payload):
        if arg or payload:
            return 1
        if self.state not in (0, 6):
            return 2
        self.left = True
        return 0

    def take_manifest(self, arg, p):
        """Command 2, in the order of the code's checks (0x6124..0x62FE)."""
        if arg or not 0 <= len(p) - 64 <= 612:
            return 1
        (magic, version, consts, size, base, limit, length, image_crc, boot_crc, entry, count, word, *zeros,
         crc) = struct.unpack_from("<4s15I", p)
        if (magic, version, consts, size, base) != (b"SKR2", 0x20000, 0x07910040, FLASH_SIZE, BASE):
            return 1
        if not length or length % BLOCK or limit != LIMIT or length > LIMIT - base:
            return 1
        if count != length // BLOCK or count > 153 or len(p) != 64 + 4 * count or entry != ENTRY or any(zeros):
            return 1
        if zlib.crc32(p[:60] + p[64:]) != crc:
            return 6
        if boot_crc != self.boot_crc:
            return 5
        if self.state not in (0, 6):
            if p == self.manifest:
                return 0
            if self.state in (3, 4):
                return 2
        self.manifest, self.length, self.image_crc, self.word = p, length, image_crc, word
        self.table = list(struct.unpack_from(f"<{count}I", p, 64))
        self.state, self.next, self.running, self.last_block = 1, 0, 0, None
        return 0

    def block(self, offset, p):
        """Command 3 (0x6300..0x639E, 0x64F4..0x6558): strictly in order, each against the manifest's table."""
        if len(p) != BLOCK or offset % BLOCK:
            return 1
        if offset >= self.length or self.length - offset < BLOCK:
            return 4
        if self.state not in (1, 2, 3, 4):
            return 2
        crc = zlib.crc32(p)
        if crc != self.table[offset // BLOCK]:
            return 6
        if self.last_block == (offset, crc):
            return 0                              # the same block again: already taken
        if self.state not in (1, 3):
            return 2
        if offset != self.next:
            return 8
        if self.state == 3:
            if offset == 0:
                self.block0 = p                   # written by the commit, last
            elif not self.program(BASE + offset, p):
                self.flash_error = 7
                return 7
        self.running = zlib.crc32(p, self.running)
        self.next, self.last_block = self.next + BLOCK, (offset, crc)
        if self.next == self.length:
            if self.running != self.image_crc:
                return 6
            self.state = 2 if self.state == 1 else 4
        return 0

    def erase_or_commit(self, arg, payload):
        """Command 4 (0x63A0..0x63FC, 0x6480..0x6584)."""
        if payload:
            return 1
        if arg == 2:
            if self.state in (3, 4, 5):
                return 0
            if self.state != 2:
                return 2
            self.erase_started = 1
            if not self.erase(BASE):
                return 7
            self.state, self.next, self.running, self.last_block = 3, 0, 0, None
            return 0
        if arg == 4:
            if self.state == 5:
                return 0
            if self.state != 4:
                return 2
            if zlib.crc32(self.block0 + bytes(self.flash[BASE + BLOCK:BASE + self.length])) != self.image_crc:
                return 6
            if not self.program(BASE, self.block0):
                return 7
            if zlib.crc32(self.flash[BASE:BASE + self.length]) != self.image_crc:
                return 6
            self.state = 5
            return 0
        return 1

    def start(self, arg, payload):
        """Command 5: once its reply has been read, the pedal resets into the new app (without usb_update_mode)."""
        if arg or payload:
            return 1
        if self.state != 5:
            return 2
        self.starting = True
        return 0

    def in_range(self, at, n):
        if BASE <= at and at + n <= LIMIT:
            return True
        self.refused.append((at, n))              # the driver refuses it; the tests require that none was asked
        return False

    def erase(self, at):
        if not self.in_range(at, BLOCK):
            return False
        self.flash[at:at + BLOCK] = b"\xFF" * BLOCK
        self.erased.append(at)
        return True

    def program(self, at, data):
        """One block: its sector erased (block 0's by command 4 with argument 2), programmed and read back."""
        if not self.in_range(at, len(data)) or at == self.fails_at:
            return False
        if at != BASE and not self.erase(at):
            return False
        self.flash[at:at + len(data)] = data
        self.programmed.append(at)
        return True

    def boots_as(self):
        """The device a reset into the app brings: none when the boot loader starts nothing (v23_boot), else the app's
        own: Gamut's when the area holds an OpenPocket product field, the stock app's otherwise."""
        found = self.flash is not None and v23_boot(self.flash)
        if not found:
            return None
        return GAMUT if b"OP-PRODUCT:" in fw.sfc(bytes(self.flash[found[0]:LIMIT]), 0) else pr.APP

    def reply(self, command, tag, status):
        if self.fault == "status" and command == 1:
            status = 1
        words = [command, tag, status, self.state, self.next, self.length, 0x07910040, 0x00020000, BASE, LIMIT,
                 self.boot_crc, self.erase_started, self.flash_error, self.word]
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
            zeros = self.in_zeros or command in self.zeros_for
            self.armed.append(bytes(64) if zeros else raw[:32] if self.fault == "short" else raw)

    def bulk_in(self, n, ms):
        self.access("bulk in", n)
        if not self.armed:
            self.wait(ms / 1000)
            raise pr.Timeout("timeout")           # macOS then clears the halt, which flushes an empty endpoint
        raw = self.armed.pop(0)
        self.waiting = bool(self.armed)
        if (self.left and not self.stays) or self.starting:
            self.depart()                         # commands 5 and 6 act once their reply has been read
        return raw[:n]

    def depart(self, at=None):
        """A core reset, with usb_update_mode but after command 5: off the bus, then after reset_s seconds whatever
        starts next."""
        self.present, self.armed, self.departed_at = False, [], self.clock() if at is None else at
        self.next_device = self.boots_as() if self.starting else AFTER_RESET[self.after_reset]

    def tick(self):
        """The mode ending on its own exits_after seconds after the computer's last access."""
        if self.present and self.exits_after is not None and self.clock() >= self.last_access + self.exits_after:
            self.depart(self.last_access + self.exits_after)


class SimBus:
    """The computer's USB bus with the pedal on it, or nothing (device None). Its clock moves only when it sleeps."""
    POLL = 0.1

    def __init__(self, device=None):
        self.device, self.opened, self.looked, self.t = device, 0, 0, 0.0
        if device is not None:
            device.clock, device.wait = self.now, self.sleep

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
        d.tick()
        if d.present:
            return {pr.RECOVERY}
        return {d.next_device} if d.next_device and self.t >= d.departed_at + d.reset_s else set()
