#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""tools/pd40_recovery.py against a simulated pedal in M-VAVE's recovery mode (tests/recovery_sim.py): no device, the
probe's buffers and hello, the reply read over bulk IN or over the control endpoint, the pedal leaving the bus and what
comes back, the leave to the USB boot state, the refusal of every write command, bad answers. No hardware.
  python3 tests/test_pd40_recovery.py
"""
import contextlib, io, struct, sys, unittest, zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recovery_sim import SimBus, SimRecovery
import pd40_recovery as pr
from pd40_recovery import BadAnswer, GuardError, Recovery

PROBE = [pr.FRAME_BUFFER, pr.REPLY_BUFFER, pr.FRAME_BUFFER, pr.REPLY_BUFFER]   # the requests of a probe without sync
TO_CONTROL = "read over the control endpoint (request 0x43) because the bulk IN endpoint sent"


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
        self.assertEqual(bus.looked, 0, "no leave was sent, so the tool does not look at the bus")

    # ---- the simulated pedal does what the real one did
    def test_the_old_probe_gets_zeros_then_nothing(self):
        """Sync, hello, two bulk IN reads: what the merged helper and a scratch probe got from a real pedal on V23."""
        sim = SimRecovery()
        self.assertEqual(sim.control_in(pr.SYNC, 4), b"SBU2")
        sim.bulk_out(pr.frame(pr.HELLO, 1))
        raw = sim.bulk_in(64, 1000)
        self.assertEqual(raw, bytes(64))
        with self.assertRaisesRegex(BadAnswer, "not 'SBR2'"):
            pr.parse_reply(raw, pr.HELLO, 1)
        self.assertRaises(pr.Timeout, sim.bulk_in, 64, 2000)
        pr.parse_reply(sim.control_in(pr.REPLY_BUFFER, 64), pr.HELLO, 1)   # the reply was composed all the same

    def test_one_failed_access_ends_the_recovery_mode(self):
        sim = SimRecovery(sie_fails_at=2, after_reset="app")
        bus = SimBus(sim)
        sim.control_in(pr.FRAME_BUFFER, 24)
        self.assertRaises(pr.DeviceGone, sim.control_in, pr.REPLY_BUFFER, 64)
        self.assertRaises(pr.DeviceGone, sim.bulk_in, 64, 1000)
        self.assertEqual(bus.present(), set())
        bus.sleep(sim.reset_s)
        self.assertEqual(bus.present(), {pr.APP})

    # ---- the probe
    def test_probe_reads_the_buffers_and_the_hello_over_bulk_in_and_writes_nothing(self):
        sim = SimRecovery()
        rc, shown = self.run_tool(SimBus(sim))
        self.assertEqual(rc, 0, shown)
        self.assertEqual(sim.requests, PROBE, "no sync by default")
        self.assertEqual(self.commands(sim), [pr.HELLO])
        self.assertEqual([t for t in sim.transfers if t[0] != "control"], [("bulk out", pr.FRAME), ("bulk in", 64)],
                         "the frame is one transfer with no zero-length packet, the reply one read of 64 bytes")
        self.assert_no_write(sim)
        self.assertFalse(sim.left)
        self.assertTrue(sim.closed)
        for line in ("[     0 ms] found 3654:7940 'SINCO' 'PD40 BOOT Recovery'", "frame buffer (0x44): 24 B all zero",
                     "reply buffer (0x43): 64 B all zero", "frame buffer (0x44): 24 B 53425532010000000100",
                     "reply buffer (0x43): 64 B 53425232", "bulk IN read 1: 64 B 53425232",
                     "hello: status 0 (accepted), state 0", "read over the bulk IN endpoint",
                     "CRC-32 0xb19d96a1: M-VAVE V22 or V23", "write range [0x6000, 0x9f000)",
                     "protocol constants 0x07910040 0x00020000", "erase started 0x0, last flash error 0x0",
                     "not reported by the protocol: the chip key and the flash id",
                     "read-only probe finished: nothing was written",
                     "watching the bus for 60 s (listing only", "the pedal stayed in the recovery mode for the whole "
                     "watch (60 s): it did not end on its own"):
            self.assertIn(line, shown)
        self.assertNotIn("bulk IN read 2", shown)
        self.assertNotIn("buffers are not empty", shown)

    def test_with_the_sync_the_hello_comes_from_the_reply_buffer(self):
        """The real pedal's answer: zeros, then nothing. The hello result is still read, over the control endpoint."""
        sim = SimRecovery()
        rc, shown = self.run_tool(SimBus(sim), "--sync")
        self.assertEqual(rc, 0, shown)
        self.assertEqual(sim.requests, PROBE[:2] + [pr.SYNC] + PROBE[2:])
        frame_at = sim.transfers.index(("bulk out", pr.FRAME))
        self.assertNotIn(("control", pr.SYNC, 4), sim.transfers[frame_at:], "a sync after the frame drops its reply")
        self.assertIn("sync (0x42): 4 B 53425532", shown)
        self.assertIn("bulk IN read 1: 64 B all zero", shown)
        self.assertIn("bulk IN read 2: nothing within 300 ms", shown)
        self.assertIn(f"{TO_CONTROL} 64 zero bytes, then nothing", shown)
        self.assertIn("hello: status 0 (accepted), state 0", shown)
        self.assert_no_write(sim)

    def test_bulk_in_sending_zeros_without_a_sync(self):
        sim = SimRecovery(in_zeros=True)
        rc, shown = self.run_tool(SimBus(sim))
        self.assertEqual(rc, 0, shown)
        self.assertIn(f"{TO_CONTROL} 64 zero bytes, then nothing", shown)

    def test_a_reply_queued_behind_an_empty_packet(self):
        sim = SimRecovery(swallows=False)
        rc, shown = self.run_tool(SimBus(sim), "--sync")
        self.assertEqual(rc, 0, shown)
        self.assertIn("bulk IN read 1: 64 B all zero", shown)
        self.assertIn("bulk IN read 2: 64 B 53425232", shown)
        self.assertIn("read over the bulk IN endpoint", shown)

    def test_a_bulk_in_timeout_is_not_retried(self):
        sim = SimRecovery(fault="silent")
        rc, shown = self.run_tool(SimBus(sim))
        self.assertEqual(rc, 0, shown)
        self.assertIn("bulk IN read 1: nothing within 1000 ms", shown)
        self.assertEqual([t for t in sim.transfers if t[0] == "bulk in"], [("bulk in", 64)])
        self.assertIn(f"{TO_CONTROL} nothing", shown)

    def test_a_frame_that_did_not_arrive_whole(self):
        for fault, why in (("partial", "the frame arrived only in part"),
                           ("deaf", "the frame did not reach the frame buffer")):
            with self.subTest(fault=fault):
                sim = SimRecovery(fault=fault)
                rc, shown = self.run_tool(SimBus(sim))
                self.assertEqual(rc, 2, shown)
                self.assertIn("REFUSED: no reply to the hello: the bulk IN endpoint sent nothing, and the reply buffer "
                              "holds 64 zero bytes: " + why, shown)

    def test_probe_names_a_head_it_does_not_know(self):
        rc, shown = self.run_tool(SimBus(SimRecovery(boot_crc=0x12345678)))
        self.assertEqual(rc, 0, shown)
        self.assertIn("CRC-32 0x12345678: not a head this tool knows", shown)

    def test_probe_reports_an_update_started_by_another_tool(self):
        rc, shown = self.run_tool(SimBus(SimRecovery(state=2)))
        self.assertEqual(rc, 0, shown)
        self.assertIn("state 2 (an update was started by another tool)", shown)

    def test_probe_reports_buffers_another_tool_filled(self):
        sim = SimRecovery()
        sim.bulk_out(pr.frame(pr.HELLO, 9))
        sim.bulk_in(64, 1000)
        rc, shown = self.run_tool(SimBus(sim))
        self.assertEqual(rc, 0, shown)
        self.assertIn("the buffers are not empty: another tool spoke to the pedal", shown)

    # ---- the pedal leaves the bus on its own
    def test_the_pedal_leaving_ends_the_probe_and_starts_the_bus_watch(self):
        for after, said in (("uboot", "4C4A:8057 appeared: the chip's USB boot state"),
                            ("recovery", "3654:7940 appeared: the recovery mode"),
                            ("app", "3654:7756 appeared: the normal pedal (the stock V23 app)"),
                            (None, "nothing appeared within 60 s: the pedal powered off or hung")):
            with self.subTest(after=after):
                sim = SimRecovery(sie_fails_at=5, after_reset=after)
                bus = SimBus(sim)
                rc, shown = self.run_tool(bus, "--leave", "--accept-inferred")
                self.assertEqual(rc, 4, shown)
                self.assertEqual(len(sim.transfers), 5, "nothing is sent after the pedal left")
                self.assertEqual(self.commands(sim), [pr.HELLO])
                self.assertIn("the pedal left the bus (gone): the recovery mode ended on its own", shown)
                self.assertIn("watching the bus for 60 s (listing only", shown)
                self.assertIn("3654:7940 left the bus", shown)
                self.assertIn(said, shown)
                if after:
                    self.assertIn(f"[   500 ms] {said}", shown)
                    self.assertIn("after leaving, the pedal came back as", shown)
                self.assertIn("send this output back", shown)
                self.assertGreaterEqual(bus.t, 60, "the watch runs its whole time")

    def test_the_leaves_transfer_failing_as_the_pedal_leaves_starts_the_bus_watch(self):
        for at in (7, 8):                                # the leave's send, then the read of its reply
            with self.subTest(at=at):
                sim = SimRecovery(sie_fails_at=at, sie_error=pr.ScsiError)
                bus = SimBus(sim)
                rc, shown = self.run_tool(bus, "--leave", "--accept-inferred")
                self.assertEqual(rc, 0, shown)
                self.assertIn("its reply did not arrive", shown)
                self.assertIn("watching the bus for 60 s", shown)
                self.assertIn("4C4A:8057 appeared", shown)

    def test_the_frame_header_is_printed_before_the_send(self):
        header = pr.frame(pr.HELLO, 1)[:24].hex()
        for error in (pr.DeviceGone, pr.ScsiError):
            with self.subTest(error=error.__name__):
                sim = SimRecovery(sie_fails_at=3, sie_error=error)   # the hello's bulk OUT
                rc, shown = self.run_tool(SimBus(sim))
                self.assertEqual(rc, 4, shown)
                self.assertEqual(len(sim.frames), 0)
                self.assertRegex(shown, rf"\[ *\d+ ms\] frame header: {header} \(command 1, tag 1, length 0\)")
                self.assertLess(shown.index("frame header"), shown.index("the pedal left the bus"))

    def test_a_failed_transfer_with_the_pedal_still_there(self):
        sim = SimRecovery(fault="stall")
        rc, shown = self.run_tool(SimBus(sim))
        self.assertEqual(rc, 1, shown)
        self.assertIn("stopped answering", shown)
        self.assertEqual(len(sim.transfers), 1, "one failed access ends the probe")

    # ---- the leave
    def test_leave_stops_with_the_explanation_unless_accepted(self):
        sim = SimRecovery()
        bus = SimBus(sim)
        rc, shown = self.run_tool(bus, "--leave")
        self.assertEqual(rc, 2, shown)
        self.assertIn("resets the processor core", shown)
        self.assertIn("once the computer\nhas read that answer", shown)
        self.assertIn("On the\none real pedal tried", shown)
        self.assertIn("No other pedal has been tried", shown)
        self.assertIn("tools/uboot_install.py", shown)
        self.assertIn("Nothing was sent to the pedal", shown)
        self.assertEqual((bus.opened, sim.frames, sim.requests), (0, [], []), "the device was not even opened")
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            pr.main(["--accept-inferred"])

    def test_leave_reaches_the_usb_boot_state(self):
        sim = SimRecovery()
        bus = SimBus(sim)
        rc, shown = self.run_tool(bus, "--leave", "--accept-inferred")
        self.assertEqual(rc, 0, shown)
        self.assertEqual(self.commands(sim), [pr.HELLO, pr.LEAVE])
        self.assert_no_write(sim)
        self.assertIn("leave: accepted, the pedal resets", shown)
        self.assertIn("USB boot state (4C4A:8057) appeared: tools/uboot_rescue.py takes over", shown)
        self.assertLess(bus.t, 1, "the watch ends when the USB boot state appears")

    def test_leave_whose_reply_is_lost(self):
        sim = SimRecovery(sie_fails_at=8)                # the read of the leave's reply
        rc, shown = self.run_tool(SimBus(sim), "--leave", "--accept-inferred")
        self.assertEqual(rc, 0, shown)
        self.assertIn("its reply did not arrive", shown)

    def test_leave_when_the_rom_does_not_stay_in_the_usb_boot_state(self):
        sim = SimRecovery(after_reset="app")
        rc, shown = self.run_tool(SimBus(sim), "--leave", "--accept-inferred", "--watch", "2")
        self.assertEqual(rc, 3, shown)
        self.assertTrue(sim.left)
        self.assertIn("3654:7756 appeared: the normal pedal (the stock V23 app)", shown)
        self.assertIn("did not appear within 2 s", shown)
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

    def test_a_hello_read_from_the_reply_buffer_refuses_the_leave_and_watches_the_bus(self):
        for sim, argv in ((SimRecovery(), ["--sync"]), (SimRecovery(in_zeros=True), []),
                          (SimRecovery(fault="silent"), []), (SimRecovery(fault="short"), [])):
            with self.subTest(argv=argv, zeros=sim.in_zeros, fault=sim.fault):
                bus = SimBus(sim)
                rc, shown = self.run_tool(bus, *argv, "--leave", "--accept-inferred")
                self.assertEqual(rc, 2, shown)
                self.assertIn(TO_CONTROL, shown)
                self.assertIn("leave: not sent (refused, see the end)", shown)
                self.assertTrue(shown.endswith("REFUSED: the hello reply did not come over the bulk IN endpoint, and "
                                               "the pedal acts on command 6 only after its reply has been read there; "
                                               "nothing more was sent\n"), shown)
                self.assertEqual(self.commands(sim), [pr.HELLO])
                self.assertFalse(sim.left)
                self.assertGreaterEqual(bus.t, 60, "the bus is watched before the refusal")
        self.assertIn(f"{TO_CONTROL} the reply is 32 bytes, not 64", shown)

    def test_control_reply_goes_only_with_the_accepted_leave(self):
        for argv in (["--accept-control-reply"], ["--leave", "--accept-control-reply"],
                     ["--accept-inferred", "--accept-control-reply"]):
            with self.subTest(argv=argv):
                shown = io.StringIO()
                with self.assertRaises(SystemExit) as stop, contextlib.redirect_stderr(shown):
                    pr.main(argv)
                self.assertEqual(stop.exception.code, 2)
                self.assertIn("goes with --leave", shown.getvalue())

    def test_a_hello_read_from_the_reply_buffer_allows_the_leave_with_its_own_flag(self):
        """--accept-control-reply lets the one command 6 go out after a hello read over the control endpoint only."""
        for sim, argv in ((SimRecovery(), ["--sync"]), (SimRecovery(in_zeros=True), [])):
            with self.subTest(argv=argv, zeros=sim.in_zeros):
                bus = SimBus(sim)
                rc, shown = self.run_tool(bus, *argv, "--leave", "--accept-inferred", "--accept-control-reply")
                self.assertEqual(rc, 0, shown)
                self.assertIn(TO_CONTROL, shown)
                self.assertIn("leave: sent although the hello reply came over the control endpoint only", shown)
                self.assertEqual(self.commands(sim), [pr.HELLO, pr.LEAVE])
                self.assert_no_write(sim)
                self.assertTrue(sim.left)
                self.assertIn("4C4A:8057 appeared: the chip's USB boot state", shown)
                self.assertIn("after leaving, the pedal came back as 4C4A:8057, the chip's USB boot state", shown)
                self.assertNotIn("REFUSED", shown)
        # the bulk IN endpoint that sent zeros for the hello sends zeros for the leave too, and the pedal acts on it
        self.assertIn("frame: command 6, tag 2, 4608 bytes in one transfer\n[   300 ms] bulk IN read 1: 64 B all zero\n"
                      "[   300 ms] the pedal left the bus (gone), 0 ms after the last command sent (command 6, tag 2) "
                      "and 300 ms after the first access\n[   300 ms] leave: sent; its reply did not arrive", shown)

    def test_the_flag_changes_nothing_when_the_hello_came_over_bulk_in(self):
        sim = SimRecovery()
        rc, shown = self.run_tool(SimBus(sim), "--leave", "--accept-inferred", "--accept-control-reply")
        self.assertEqual(rc, 0, shown)
        self.assertEqual(self.commands(sim), [pr.HELLO, pr.LEAVE])
        self.assertNotIn("sent although", shown)

    def test_a_leave_the_pedal_does_not_take_is_not_repeated(self):
        """After a bulk IN timeout the hello reply still waits, and the pedal takes no frame: the leave fails, once."""
        sim = SimRecovery(fault="silent")
        rc, shown = self.run_tool(SimBus(sim), "--leave", "--accept-inferred", "--accept-control-reply")
        self.assertEqual(rc, 1, shown)
        self.assertIn("stopped answering", shown)
        self.assertEqual([t for t in sim.transfers if t[0] == "bulk out"], [("bulk out", pr.FRAME)] * 2)
        self.assertEqual(self.commands(sim), [pr.HELLO])
        self.assertFalse(sim.left)

    def test_a_pedal_that_stays_after_the_leave(self):
        sim = SimRecovery(stays=True)
        bus = SimBus(sim)
        rc, shown = self.run_tool(bus, "--leave", "--accept-inferred", "--watch", "5")
        self.assertEqual(rc, 5, shown)
        self.assertEqual(self.commands(sim), [pr.HELLO, pr.LEAVE])
        self.assertIn("leave: accepted, the pedal resets", shown)
        self.assertIn("the pedal stayed in the recovery mode for 5 s after command 6: it did not act on it", shown)
        self.assertNotIn("left the bus", shown)
        self.assertGreaterEqual(bus.t, 5)

    # ---- when the pedal leaves: the time since the last command sent and since the first access
    def test_the_recovery_mode_ending_on_its_own_after_the_probe_is_timed(self):
        """What a real pedal on V23 did: the mode ended within seconds of a probe that sent no leave."""
        for after, back in (("uboot", "4C4A:8057, the chip's USB boot state"),
                            ("app", "3654:7756, the normal pedal (the stock V23 app)")):
            with self.subTest(after=after):
                sim = SimRecovery(exits_after=2.5, after_reset=after)
                bus = SimBus(sim)
                rc, shown = self.run_tool(bus)
                self.assertEqual(rc, 4, shown)
                self.assertEqual(self.commands(sim), [pr.HELLO], "the watch sends nothing")
                self.assertIn("[  2500 ms] 3654:7940 left the bus: the recovery mode, seen gone 2500 ms after the last "
                              "command sent (command 1, tag 1) and 2500 ms after the first access", shown)
                self.assertIn(f"after leaving, the pedal came back as {back}", shown)
                self.assertIn("send this output back: it shows when the recovery mode ended", shown)
                self.assertGreaterEqual(bus.t, 60, "the watch runs its whole time")

    def test_the_departure_after_a_leave_is_timed_from_the_leave(self):
        sim = SimRecovery()                              # with the sync: bulk IN read 2 times out after 300 ms
        rc, shown = self.run_tool(SimBus(sim), "--sync", "--leave", "--accept-inferred", "--accept-control-reply")
        self.assertEqual(rc, 0, shown)
        self.assertIn("[   300 ms] 3654:7940 left the bus: the recovery mode, seen gone 0 ms after the last command "
                      "sent (command 6, tag 2) and 300 ms after the first access", shown)

    def test_every_phase_carries_its_time(self):
        for argv in ([], ["--leave", "--accept-inferred"]):
            with self.subTest(argv=argv):
                rc, shown = self.run_tool(SimBus(SimRecovery()), *argv)
                self.assertEqual(rc, 0, shown)
                for line in shown.splitlines():
                    self.assertRegex(line, r"^\[ *\d+ ms\] ")

    # ---- the refusals
    def test_every_write_command_is_refused_before_anything_is_sent(self):
        sim = SimRecovery()
        session = Recovery(sim, lambda m: None, lambda: 0.0)
        for command in (pr.MANIFEST, pr.BLOCK, pr.COMMIT, pr.START_APP):
            with self.subTest(command=command):
                with self.assertRaisesRegex(GuardError, "belongs to a write to the flash"):
                    session.send(command)
        for command in (0, 7, 8, 0xFF, 0xFFFFFFFF):
            with self.subTest(command=command):
                self.assertRaises(GuardError, session.send, command)
        self.assertEqual((sim.transfers, sim.frames, sim.write_attempts), ([], [], []))
        self.assertEqual(pr.ALLOWED, {pr.HELLO, pr.LEAVE})
        self.assertFalse(pr.ALLOWED & set(pr.WRITES))

    def test_frames_carry_no_payload(self):
        for command in pr.ALLOWED:
            f = pr.frame(command, 7)
            self.assertEqual(len(f), pr.FRAME)
            self.assertEqual(struct.unpack("<4sIIIII", f[:24]), (b"SBU2", command, 7, 0, 0, 0))
            self.assertEqual(f[24:], bytes(pr.FRAME - 24), "nothing after the header")

    def test_only_the_three_read_only_vendor_requests_are_sent(self):
        self.assertEqual(pr.REQUESTS, {0x42: 4, 0x43: 64, 0x44: 24})
        dev = pr.LibusbRecovery.__new__(pr.LibusbRecovery)
        for request, n in ((0x00, 64), (0x21, 64), (0x40, 64), (0x41, 4), (0x45, 24), (0x42, 64), (0x43, 24), (0x44, 64)):
            with self.subTest(request=hex(request), n=n):
                self.assertRaises(GuardError, dev.control_in, request, n)

    # ---- bad answers: the tool stops, and nothing more is sent (no leave even when asked)
    def test_bad_answers_stop_the_tool(self):
        expected = {"sync": "sync request answered", "magic": "not 'SBR2'", "crc": "CRC-32",
                    "tag": "tag 2", "command": "command 9", "constants": "another recovery version",
                    "status": "hello was answered with status 1"}
        for fault, why in expected.items():
            with self.subTest(fault=fault):
                sim = SimRecovery(fault=fault)
                bus = SimBus(sim)
                rc, shown = self.run_tool(bus, *(["--sync"] if fault == "sync" else []), "--leave", "--accept-inferred")
                self.assertEqual(rc, 2, shown)
                self.assertIn("REFUSED", shown)
                self.assertIn(why, shown)
                self.assertNotIn(pr.LEAVE, self.commands(sim))
                self.assertEqual((sim.left, bus.looked), (False, 0))
                self.assertTrue(sim.closed)

    def test_reply_checks(self):
        sim = SimRecovery()
        sim.bulk_out(pr.frame(pr.HELLO, 5))
        raw = sim.bulk_in(64, 1000)
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
