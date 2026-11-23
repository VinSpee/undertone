#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""tools/pd40_recovery.py against a simulated pedal in M-VAVE's recovery mode (tests/recovery_sim.py): no device, the
probe's sync and hello, the leave to the USB boot state, the refusal of every write command, bad answers. No hardware.
  python3 tests/test_pd40_recovery.py
"""
import contextlib, io, struct, sys, unittest, zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recovery_sim import SimBus, SimRecovery
import pd40_recovery as pr
from pd40_recovery import BadAnswer, GuardError, Recovery


class Pd40Recovery(unittest.TestCase):
    def run_tool(self, bus, *argv):
        """main() as a user types it, with the bus replaced. Returns (exit code, what the window showed)."""
        self.addCleanup(setattr, pr, "transport", pr.transport)
        pr.transport = lambda: bus
        shown = io.StringIO()
        with contextlib.redirect_stdout(shown), contextlib.redirect_stderr(shown):
            rc = pr.main(list(argv))
        return rc, shown.getvalue()

    def commands(self, sim):
        return [struct.unpack("<I", f[4:8])[0] for f in sim.frames]

    def assert_no_write(self, sim):
        self.assertEqual(sim.write_attempts, [], "a write command reached the pedal")
        self.assertTrue(set(self.commands(sim)) <= {pr.HELLO, pr.LEAVE}, self.commands(sim))

    # ---- no device
    def test_no_device(self):
        bus = SimBus()
        rc, shown = self.run_tool(bus)
        self.assertEqual(rc, 1, shown)
        self.assertIn("no recovery device (3654:7940) found", shown)
        self.assertIn("hold HOME, the right footswitch and the knob's PUSH", shown)
        rc, shown = self.run_tool(bus, "--leave", "--accept-inferred")
        self.assertEqual(rc, 1, shown)
        self.assertEqual(bus.looked, 0, "no leave was sent, so the tool does not look for the USB boot state")

    # ---- the probe
    def test_probe_reads_sync_and_hello_and_writes_nothing(self):
        sim = SimRecovery()
        rc, shown = self.run_tool(SimBus(sim))
        self.assertEqual(rc, 0, shown)
        self.assertEqual(sim.requests, [pr.SYNC])
        self.assertEqual(self.commands(sim), [pr.HELLO])
        self.assert_no_write(sim)
        self.assertFalse(sim.left)
        self.assertTrue(sim.closed)
        for line in ("found 3654:7940 'SINCO' 'PD40 BOOT Recovery'", "sync: SBU2", "hello: status 0 (accepted), state 0",
                     "CRC-32 0xb19d96a1: M-VAVE V22 or V23", "write range [0x6000, 0x9f000)",
                     "protocol constants 0x07910040 0x00020000", "not reported by the protocol: the chip key and the flash id",
                     "read-only probe finished: nothing was written"):
            self.assertIn(line, shown)

    def test_probe_names_a_head_it_does_not_know(self):
        rc, shown = self.run_tool(SimBus(SimRecovery(boot_crc=0x12345678)))
        self.assertEqual(rc, 0, shown)
        self.assertIn("CRC-32 0x12345678: not a head this tool knows", shown)

    def test_probe_reports_an_update_started_by_another_tool(self):
        rc, shown = self.run_tool(SimBus(SimRecovery(state=2)))
        self.assertEqual(rc, 0, shown)
        self.assertIn("state 2 (an update was started by another tool)", shown)

    # ---- the leave
    def test_leave_stops_with_the_explanation_unless_accepted(self):
        sim = SimRecovery()
        bus = SimBus(sim)
        rc, shown = self.run_tool(bus, "--leave")
        self.assertEqual(rc, 2, shown)
        self.assertIn("inferred, not proven", shown)
        self.assertIn("Nothing was sent to the pedal", shown)
        self.assertEqual((bus.opened, sim.frames, sim.requests), (0, [], []), "the device was not even opened")
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            pr.main(["--accept-inferred"])

    def test_leave_reaches_the_usb_boot_state(self):
        sim = SimRecovery()
        rc, shown = self.run_tool(SimBus(sim), "--leave", "--accept-inferred")
        self.assertEqual(rc, 0, shown)
        self.assertEqual(self.commands(sim), [pr.HELLO, pr.LEAVE])
        self.assert_no_write(sim)
        self.assertIn("leave: accepted, the pedal resets", shown)
        self.assertIn("USB boot state (4C4A:8057) appeared: tools/uboot_rescue.py takes over", shown)

    def test_leave_whose_reply_is_lost(self):
        sim = SimRecovery(reply_to_leave=False)
        rc, shown = self.run_tool(SimBus(sim), "--leave", "--accept-inferred")
        self.assertEqual(rc, 0, shown)
        self.assertIn("left before its reply arrived", shown)

    def test_leave_when_the_rom_does_not_stay_in_the_usb_boot_state(self):
        sim = SimRecovery(rom_ignores_mark=True)
        rc, shown = self.run_tool(SimBus(sim), "--leave", "--accept-inferred", "--watch", "0.05")
        self.assertEqual(rc, 3, shown)
        self.assertTrue(sim.left)
        self.assertIn("did not appear within 0.05 s", shown)
        self.assertIn("stop and write nothing to this pedal", shown)

    def test_leave_is_not_sent_while_an_update_is_in_progress(self):
        for state in (1, 2, 3, 4, 5):
            with self.subTest(state=state):
                sim = SimRecovery(state=state)
                rc, shown = self.run_tool(SimBus(sim), "--leave", "--accept-inferred")
                self.assertEqual(rc, 2, shown)
                self.assertIn(f"REFUSED: the recovery mode is in state {state}", shown)
                self.assertEqual(self.commands(sim), [pr.HELLO])
        rc, shown = self.run_tool(SimBus(SimRecovery(state=6)), "--leave", "--accept-inferred")
        self.assertEqual(rc, 0, shown)

    # ---- the refusals
    def test_every_write_command_is_refused_before_anything_is_sent(self):
        sim = SimRecovery()
        session = Recovery(sim)
        for command in (pr.MANIFEST, pr.BLOCK, pr.COMMIT, pr.START_APP):
            with self.subTest(command=command):
                with self.assertRaisesRegex(GuardError, "belongs to a write to the flash"):
                    session.command(command)
        for command in (0, 7, 8, 0xFF, 0xFFFFFFFF):
            with self.subTest(command=command):
                self.assertRaises(GuardError, session.command, command)
        self.assertEqual((sim.frames, sim.write_attempts), ([], []))
        self.assertEqual(pr.ALLOWED, {pr.HELLO, pr.LEAVE})
        self.assertFalse(pr.ALLOWED & set(pr.WRITES))

    def test_frames_carry_no_payload(self):
        for command in pr.ALLOWED:
            f = pr.frame(command, 7)
            self.assertEqual(len(f), pr.FRAME)
            self.assertEqual(struct.unpack("<4sIIIII", f[:24]), (b"SBU2", command, 7, 0, 0, 0))
            self.assertEqual(f[24:], bytes(pr.FRAME - 24), "nothing after the header")

    def test_only_the_sync_vendor_request_is_sent(self):
        dev = pr.LibusbRecovery.__new__(pr.LibusbRecovery)
        for request in (0x43, 0x44, 0x00, 0x21):
            with self.subTest(request=hex(request)):
                self.assertRaises(GuardError, dev.control_in, request, 64)

    # ---- bad answers: the tool stops, and nothing more is sent (no leave even when asked)
    def test_bad_answers_stop_the_tool(self):
        expected = {"sync": "sync request answered", "short": "32 bytes", "magic": "not 'SBR2'", "crc": "CRC-32",
                    "tag": "tag 2", "command": "command 9", "constants": "another recovery version",
                    "status": "hello was answered with status 1"}
        for fault, why in expected.items():
            with self.subTest(fault=fault):
                sim = SimRecovery(fault=fault)
                bus = SimBus(sim)
                rc, shown = self.run_tool(bus, "--leave", "--accept-inferred")
                self.assertEqual(rc, 2, shown)
                self.assertIn("REFUSED", shown)
                self.assertIn(why, shown)
                self.assertNotIn(pr.LEAVE, self.commands(sim))
                self.assertEqual((sim.left, bus.looked), (False, 0))
                self.assertTrue(sim.closed)

    def test_a_silent_device(self):
        sim = SimRecovery(fault="silent")
        rc, shown = self.run_tool(SimBus(sim), "--leave", "--accept-inferred")
        self.assertEqual(rc, 1, shown)
        self.assertIn("stopped answering", shown)
        self.assertEqual(self.commands(sim), [pr.HELLO])

    def test_reply_checks(self):
        sim = SimRecovery()
        sim.bulk_out(pr.frame(pr.HELLO, 5))
        raw = sim.bulk_in(64)
        r = pr.parse_reply(raw, pr.HELLO, 5)
        self.assertEqual((r.status, r.state, r.base, r.limit, r.boot_crc), (0, 0, 0x6000, 0x9F000, 0xB19D96A1))
        self.assertRaises(BadAnswer, pr.parse_reply, raw, pr.HELLO, 6)
        self.assertRaises(BadAnswer, pr.parse_reply, raw, pr.LEAVE, 5)
        self.assertRaises(BadAnswer, pr.parse_reply, raw[:63], pr.HELLO, 5)
        flipped = bytearray(raw)
        flipped[20] ^= 1
        self.assertRaises(BadAnswer, pr.parse_reply, bytes(flipped), pr.HELLO, 5)

    def test_the_crc_is_zlibs(self):
        """The boot loader's CRC-32 (polynomial 0xEDB88320, start and end inverted) is zlib's: the empty payload's is 0."""
        self.assertEqual(zlib.crc32(b""), 0)
        self.assertEqual(zlib.crc32(b"123456789"), 0xCBF43926)

    # ---- the USB transport
    def test_finds_the_vendor_interface(self):
        # the configuration descriptor in the V23 boot loader, byte for byte: one interface of class 0xFF, bulk IN 0x81
        # and bulk OUT 0x01 of 64 bytes
        cfg = bytes.fromhex("090220000101008032" "0904000002ff000000" "07058102400000" "07050102400000")
        self.assertEqual(pr.vendor_endpoints(cfg), (0, 0x81, 0x01))
        msc = bytes.fromhex("0902200001010080c80904000002080650000705810240000107050102400001")
        self.assertRaises(pr.RescueError, pr.vendor_endpoints, msc)


if __name__ == "__main__":
    unittest.main(verbosity=1)
