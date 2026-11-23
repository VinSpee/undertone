#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""tools/pd40_install.py against a simulated BlackBox in M-VAVE's V22/V23 recovery mode (tests/recovery_sim.py) that
runs the write commands on a simulated flash: the dry run, the pedal's own check, the install of a Gamut app area at
0x6000 and the way back to M-VAVE's app area, what the V23 boot loader then starts, the refusals, a failure after the
erase and the install run again, the pedal leaving. Nothing below 0x6000 or from 0x9F000 up is ever written. No hardware.
  python3 tests/test_pd40_install.py [--built] [BlackBox_023.fwsc ...]
--built also installs the app areas the build made (build/apps/*/*-v23.bin); an official V22 or V23 package (not in this
repository) is also put back on a simulated pedal with its own head.
"""
import contextlib, io, random, struct, sys, tempfile, unittest, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))
from recovery_sim import SimBus, SimRecovery, v23_boot, GAMUT
from fw_layouts import flash_image
import pocketx_fw as fw
import pd40_install as pi
import pd40_recovery as pr
import pxpkg

BUILT = "--built" in sys.argv
OFFICIAL = [a for a in sys.argv[1:] if a.endswith(".fwsc")]
sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--built" and a not in OFFICIAL]
BASE, LIMIT = 0x6000, 0x9F000
TMP = tempfile.TemporaryDirectory()
WORK = Path(TMP.name)


def noise(seed, n):
    return random.Random(seed).randbytes(n)


def official_flash(base, seed, length):
    """An official-like flash.bin: fw_layouts' layout with a flash header the boot loader accepts (PocketX_016's)."""
    flash = bytearray(flash_image(base, noise(seed, 0x80000), length))
    flash[:32] = fw.enc(struct.pack("<H", fw.crc16(pxpkg.FLASH_HDR)) + pxpkg.FLASH_HDR)
    return bytes(flash)


def package(flash, product):
    path = WORK / f"{product}.fwsc"
    path.write_bytes(pxpkg.ufw(flash, b"OTA" * 100, product))
    return path


V23 = official_flash(BASE, 23, LIMIT)
V23_PKG = package(V23, "BlackBox_023")
OTHER = bytearray(official_flash(BASE, 22, LIMIT))
OTHER[0x5800] = 0                                 # a head of the same layout, not this pedal's
OTHER_PKG = package(bytes(OTHER), "BlackBox_022")
V20_PKG = package(official_flash(0x4000, 20, 0xA5000), "BlackBox_020")
# the pedal: the official V23 flash.bin, then its stock settings, user data and key_mac, which nothing may touch
PEDAL = V23 + noise(99, 0x100000 - LIMIT)

app = b"OP-PRODUCT:PocketX_900".ljust(32, b"\0") + noise(7, 0x58000)
with contextlib.redirect_stdout(io.StringIO()):
    pxpkg.build(app, b"OTA" * 100, WORK / "gamut", 99, None, ROOT / "firmware" / "sdk" / "packager")
GAMUT_BIN = WORK / "gamut" / "BlackBox_999-v23.bin"
GAMUT_PKG = WORK / "gamut" / "BlackBox_999.fwsc"
POCKET_PKG = WORK / "gamut" / "PocketX_999.fwsc"
AREA = GAMUT_BIN.read_bytes()


class Pd40Install(unittest.TestCase):
    def setUp(self):
        heads = dict(pr.HEADS)
        self.addCleanup(lambda: (pr.HEADS.clear(), pr.HEADS.update(heads)))
        pr.HEADS[zlib.crc32(V23[:BASE])] = "the synthetic V23 head of this test"

    def run_tool(self, bus, *argv):
        """main() as a user types it, with the bus replaced. Returns (exit code, what the window showed)."""
        self.addCleanup(setattr, pi, "transport", pi.transport)
        pi.transport = lambda: bus
        shown = io.StringIO()
        with contextlib.redirect_stdout(shown), contextlib.redirect_stderr(shown):
            rc = pi.main([str(a) for a in argv])
        return rc, shown.getvalue()

    def commands(self, sim):
        return [(struct.unpack_from("<I", f, 4)[0], struct.unpack_from("<I", f, 12)[0]) for f in sim.frames]   # command, argument

    def assert_outside_untouched(self, sim, pedal=PEDAL):
        self.assertEqual(sim.refused, [], "an erase or program outside [0x6000, 0x9F000) was asked")
        self.assertTrue(sim.flash[:BASE] == pedal[:BASE], "the head [0, 0x6000) changed")
        self.assertTrue(sim.flash[LIMIT:] == pedal[LIMIT:], "the flash from 0x9F000 up changed")

    def install(self, image, pedal=PEDAL, **kw):
        sim = SimRecovery(flash=pedal, **kw)
        bus = SimBus(sim)
        return (*self.run_tool(bus, image, "--write"), sim, bus)

    # ---- the dry run
    def test_the_dry_run_prints_every_frame_and_opens_nothing(self):
        def no_bus():
            raise AssertionError("the dry run opened the USB")
        self.addCleanup(setattr, pi, "transport", pi.transport)
        pi.transport = no_bus
        for image in (GAMUT_BIN, GAMUT_PKG, V23_PKG):
            with self.subTest(image=image.name):
                shown = io.StringIO()
                with contextlib.redirect_stdout(shown), contextlib.redirect_stderr(shown):
                    rc = pi.main([str(image)])
                shown = shown.getvalue()
                self.assertEqual(rc, 0, shown)
                self.assertIn("dry run: nothing is opened or sent", shown)
                self.assertIn("every check passed", shown)
                self.assertIn("frame 1 header: " + pr.frame(pr.HELLO, 1)[:24].hex() + " (hello)", shown)
                self.assertIn("(the manifest)", shown)
                self.assertIn("manifest   0: 534b5232", shown)
                self.assertIn("(block 152: image bytes [0x98000, 0x99000) to flash 0x9e000", shown)
                self.assertIn("(the erase of the sector at 0x6000)", shown)
                self.assertIn("(the commit)", shown)
                self.assertIn("(the start of the new app)", shown)
                self.assertIn("dry run finished: 311 frames; --verify sends the first 155 (nothing written), --write all",
                              shown)

    def test_the_dry_run_prints_the_frames_the_install_sends(self):
        """The same headers, tag for tag, as the session on the pedal (whose head is the known one)."""
        pr.HEADS.clear()
        pr.HEADS[pi.KNOWN_HEAD] = "known"
        rc, dry = self.run_tool(None, GAMUT_BIN)
        self.assertEqual(rc, 0, dry)
        sim = SimRecovery(flash=PEDAL, boot_crc=pi.KNOWN_HEAD)
        rc, shown = self.run_tool(SimBus(sim), GAMUT_BIN, "--write")
        self.assertEqual(rc, 0, shown)
        headers = [line.split("header: ")[1].split()[0] for line in dry.splitlines() if "header: " in line]
        self.assertEqual(headers, [f[:24].hex() for f in sim.frames])

    # ---- the pedal's own check
    def test_verify_runs_the_first_pass_and_writes_nothing(self):
        sim = SimRecovery(flash=PEDAL)
        rc, shown = self.run_tool(SimBus(sim), GAMUT_BIN, "--verify")
        self.assertEqual(rc, 0, shown)
        self.assertEqual(self.commands(sim), [(1, 0), (2, 0)] + [(3, o) for o in range(0, len(AREA), 4096)])
        self.assertEqual((sim.state, sim.erased, sim.programmed), (2, [], []))
        self.assertTrue(sim.flash == PEDAL)
        self.assertIn("first pass done: 153 blocks and the whole image's CRC-32 accepted, state 2: nothing was written",
                      shown)
        self.assertIn("nothing was written. It stays in the recovery mode", shown)

    # ---- the install and the way back
    def test_install_gamut_then_put_the_official_app_area_back(self):
        for image in (GAMUT_BIN, GAMUT_PKG):
            with self.subTest(image=image.name):
                rc, shown, sim, bus = self.install(image)
                self.assertEqual(rc, 0, shown)
                self.assertTrue(sim.flash[BASE:LIMIT] == AREA, "the area is Gamut's")
                self.assert_outside_untouched(sim)
                self.assertEqual(v23_boot(sim.flash), (BASE, 0x02000120), "the boot loader's four checks pass")
                self.assertEqual(sim.programmed[-1], BASE, "block 0, the area head, is written last")
                self.assertEqual(sim.erased[0], BASE, "the area head goes first: no half area can start")
                self.assertIn("second pass done: 153 blocks", shown)
                self.assertIn("1209:0001 appeared: Gamut", shown)
                self.assertIn("Gamut started: the install worked", shown)
                self.assertIn("node tools/op.mjs dsp", shown)
                rc, shown, back, _ = self.install(V23_PKG, pedal=bytes(sim.flash))
                self.assertEqual(rc, 0, shown)
                self.assertTrue(back.flash == PEDAL, "every byte of the pedal is official again")
                self.assertIn("3654:7756 appeared: the normal pedal (the stock V23 app)", shown)
                self.assertIn("M-VAVE's app started: the official app area is back", shown)

    def test_a_failure_after_the_erase_and_the_install_run_again(self):
        rc, shown, sim, _ = self.install(GAMUT_BIN, fails_at=BASE + 5 * 4096)
        self.assertEqual(rc, 2, shown)
        self.assertIn("status 7 (flash error)", shown)
        self.assertIn("The app area is erased or half written", shown)
        self.assertIsNone(v23_boot(sim.flash), "the area head is not written: the boot loader starts nothing")
        self.assert_outside_untouched(sim)
        self.assertNotIn((5, 0), self.commands(sim))
        for image, device in ((GAMUT_BIN, "Gamut started"), (V23_PKG, "M-VAVE's app started")):
            with self.subTest(again=image.name):
                rc, shown, again, _ = self.install(image, pedal=bytes(sim.flash))
                self.assertEqual(rc, 0, shown)
                self.assertIn(device, shown)
                self.assert_outside_untouched(again)

    def test_a_failed_start_after_the_commit_is_not_reported_as_an_erased_area(self):
        class Refuses(SimRecovery):
            def start(self, arg, payload):
                return 2
        sim = Refuses(flash=PEDAL)
        rc, shown = self.run_tool(SimBus(sim), GAMUT_BIN, "--write")
        self.assertNotEqual(rc, 0, shown)
        self.assertEqual(self.commands(sim)[-1][0], 5)
        self.assertNotIn("erased or half written", shown)
        self.assertIn("The new image is written and committed; only the start of the app was not confirmed", shown)
        self.assertEqual(v23_boot(sim.flash), (BASE, 0x02000120))

    def test_the_pedal_leaving_during_the_session(self):
        for at, erased in ((20, False), (400, True)):    # a transfer of the first pass, then of the second
            with self.subTest(at=at):
                rc, shown, sim, bus = self.install(GAMUT_BIN, sie_fails_at=at, after_reset="recovery")
                self.assertEqual(rc, 4, shown)
                self.assertIn("the recovery mode ended on its own; nothing more is sent", shown)
                self.assertEqual("The app area is erased" in shown, erased, shown)
                self.assertEqual(bus.looked, 0)
                self.assert_outside_untouched(sim)

    def test_the_new_app_not_appearing(self):
        broken = PEDAL[:0x20] + bytes(0x20) + PEDAL[0x40:]          # a head entry the boot loader refuses
        pr.HEADS[zlib.crc32(broken[:BASE])] = "a broken head"
        rc, shown, sim, _ = self.install(GAMUT_BIN, pedal=broken)
        self.assertEqual(rc, 3, shown)
        self.assertIn("the new app did not appear (nothing appeared within 60 s)", shown)

    # ---- the refusals: nothing more is sent, and nothing at all before the image passed its checks
    def test_images_that_are_refused(self):
        def changed(data, at):
            b = bytearray(data)
            b[at] ^= 1
            return bytes(b)
        bad = {"head.bin": (changed(AREA, 2), "not an app area head"),
               "data.bin": (changed(AREA, 0x2000), "its area head's data CRC fails"),
               "odd.bin": (AREA[:-1], "not a whole number of 4 KiB blocks"),
               "long.bin": (AREA + b"\xFF" * 4096, "longer than the write range"),
               "official.bin": (V23[BASE:], "give its .fwsc package")}
        for name, (data, why) in bad.items():
            (WORK / name).write_bytes(data)
        cases = [(WORK / n, why) for n, (_, why) in bad.items()] + [
            (POCKET_PKG, "is a Pocket X package"), (V20_PKG, "a package for the old head"),
            (WORK / "missing.bin", "No such file")]
        for path, why in cases:
            with self.subTest(image=path.name):
                sim = SimRecovery(flash=PEDAL)
                rc, shown = self.run_tool(SimBus(sim), path, "--write")
                self.assertEqual(rc, 1 if "missing" in path.name else 2, shown)
                self.assertIn(why, shown)
                self.assertEqual(sim.transfers, [], "the pedal was asked before the image was checked")

    def test_pedals_that_are_refused(self):
        cases = [(dict(in_zeros=True), GAMUT_BIN, "did not come over the bulk IN endpoint"),
                 (dict(state=2), GAMUT_BIN, "in state 2: another tool started an update"),
                 (dict(boot_crc=0x12345678), GAMUT_BIN, "0x12345678 is not a head this tool knows"),
                 (dict(), OTHER_PKG, "the package's head"),
                 (dict(fault="status"), GAMUT_BIN, "hello was answered with status 1")]
        for kw, image, why in cases:
            with self.subTest(why=why):
                sim = SimRecovery(flash=PEDAL, **kw)
                rc, shown = self.run_tool(SimBus(sim), image, "--write")
                self.assertEqual(rc, 2, shown)
                self.assertIn("REFUSED", shown)
                self.assertIn(why, shown)
                self.assertEqual(sim.write_attempts, [])
                self.assertTrue(sim.flash == PEDAL)

    def test_no_device_and_bad_arguments(self):
        rc, shown = self.run_tool(SimBus(), GAMUT_BIN, "--write")
        self.assertEqual(rc, 1, shown)
        self.assertIn("hold HOME, the right footswitch and the knob's PUSH", shown)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            pi.main([str(GAMUT_BIN), "--verify", "--write"])

    # ---- the protocol as read
    def test_the_manifest(self):
        image = pi.load_image(GAMUT_BIN)
        m = pi.manifest(image, 0xB19D96A1)
        self.assertEqual(len(m), 64 + 4 * 153)
        self.assertEqual(struct.unpack_from("<4s11I", m), (b"SKR2", 0x20000, 0x07910040, 0x100000, 0x6000, 0x9F000,
                                                          0x99000, zlib.crc32(AREA), 0xB19D96A1, 0x02000120, 153, 0))
        self.assertEqual(m[48:60], bytes(12))
        self.assertEqual(struct.unpack_from("<I", m, 60)[0], zlib.crc32(m[:60] + m[64:]), "over bytes 0..59 and the table")
        self.assertEqual(struct.unpack_from("<I", m, 64 + 4 * 152)[0], zlib.crc32(AREA[152 * 4096:]))
        sim = SimRecovery(flash=PEDAL)
        for payload, status in ((m, 5), (m[:60] + b"\0\0\0\0" + m[64:], 6), (m[:-4], 1)):
            sim.state = 0
            sim.bulk_out(pi.frame(pi.MANIFEST, 1, 0, payload))
            self.assertEqual(pr.parse_reply(sim.bulk_in(64, 1000), pi.MANIFEST, 1).status, status)

    def test_frames(self):
        f = pi.frame(pi.BLOCK_CMD, 3, 0x1000, b"x" * 4096)
        self.assertEqual(len(f), pr.FRAME)
        self.assertEqual(struct.unpack_from("<4sIIIII", f), (b"SBU2", 3, 3, 0x1000, 4096, zlib.crc32(b"x" * 4096)))
        self.assertEqual(pi.frame(pi.HELLO, 1), pr.frame(pr.HELLO, 1), "the hello is the read-only helper's")
        self.assertRaises(pr.GuardError, pi.frame, pr.LEAVE, 1)
        self.assertRaises(pr.GuardError, pi.frame, pi.BLOCK_CMD, 1, 0, b"x" * 4097)

    # ---- the files the build made, and the official packages when given
    @unittest.skipUnless(BUILT, "--built: the app areas the build made")
    def test_the_built_app_areas(self):
        built = sorted((ROOT / "build" / "apps").glob("*/*-v23.bin"))
        self.assertGreaterEqual(len(built), 2)
        for path in built:
            with self.subTest(image=path.name):
                rc, shown, sim, _ = self.install(path)
                self.assertEqual(rc, 0, shown)
                self.assertIn("1209:0001 appeared", shown)
                self.assert_outside_untouched(sim)

    @unittest.skipUnless(OFFICIAL, "an official V22 or V23 package")
    def test_official_packages(self):
        for name in OFFICIAL:
            with self.subTest(package=Path(name).name):
                _, L, tag, u = fw.load(name)
                fl = next(L[e["off"]:e["off"] + e["len"]] for e in u["ents"] if e["name"] == "flash.bin")
                pedal = fl + noise(98, 0x100000 - len(fl))
                self.assertEqual(zlib.crc32(fl[:BASE]), 0xB19D96A1, "the head of V22 and V23")
                rc, shown, sim, _ = self.install(GAMUT_BIN, pedal=pedal)
                self.assertEqual(rc, 0, shown)
                self.assertEqual(v23_boot(sim.flash), (BASE, 0x02000120))
                self.assert_outside_untouched(sim, pedal)
                rc, shown, back, _ = self.install(name, pedal=bytes(sim.flash))
                self.assertEqual(rc, 0, shown)
                self.assertTrue(back.flash == pedal, f"{tag} is back, byte for byte")


if __name__ == "__main__":
    unittest.main(verbosity=1)
