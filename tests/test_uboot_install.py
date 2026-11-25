#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""tools/uboot_install.py against one simulated pedal that is in M-VAVE's recovery mode (tests/recovery_sim.py), in the
chip's USB boot state (tests/uboot_sim.py), or off the bus: the dry run, the install of Gamut and the way back from an
official package and from a backup, on both flash layouts (the old head, app area at 0x4000, and the V22/V23 head, at
0x6000); any other app image (--image, such as a test build's) after a typed yes, with a warning when the boot loader
would not start it; the leave from the recovery mode and the USB boot state taken the moment it appears; the refusals
of an unknown head, of an app area for the other layout, of an image that is not whole sectors, too long or begins with
a boot area, of another chip or flash, each before any erase; the resume. Nothing below the app area's start or from
the layout's limit up is ever written. No hardware.
  python3 tests/test_uboot_install.py [--built] [BlackBox_020.fwsc BlackBox_023.fwsc ...]
The heads are synthetic ones built to the two layouts (tests/fw_layouts.py). --built also installs the Gamut app area
the build made, against the real release pin; an official package (not in this repository) is also used on a simulated
pedal with its own head, which must be one of the two the tool knows.
"""
import contextlib, dataclasses, hashlib, io, random, sys, tempfile, unittest, zlib
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))
import uboot_sim
from recovery_sim import SimRecovery, v23_boot
from fw_layouts import bootable_flash
import pocketx_fw as fw
import pd40_recovery as pr
import pxpkg
import uboot_install as ui
import uboot_rescue as ur

BUILT = "--built" in sys.argv
OFFICIAL = [a for a in sys.argv[1:] if a.endswith(".fwsc")]
sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--built" and a not in OFFICIAL]
SECTOR, ENTRY = ur.SECTOR, 0x02000120
TMP = tempfile.TemporaryDirectory()
WORK = Path(TMP.name)


def noise(seed, n):
    return random.Random(seed).randbytes(n)


def package(flash, product):
    path = WORK / f"{product}.fwsc"
    path.write_bytes(pxpkg.ufw(flash, b"OTA" * 100, product))
    return path


def pedal_with(flash_bin):
    """A pedal that holds this official flash.bin, then its stock settings, user data and key_mac."""
    return flash_bin + noise(99, ur.FLASH_SIZE - len(flash_bin))


def differing(flash, layout, area=None):
    """The sectors of the pedal's app area that are not Gamut's (or area's)."""
    area = AREA if area is None else area
    return [layout.base + o for o in range(0, len(area), SECTOR)
            if flash[layout.base + o:layout.base + o + SECTOR] != area[o:o + SECTOR]]


LOADER = noise(1, ur.LOADER_SIZE)
REAL_LAYOUTS = ui.LAYOUTS
OLD, NEW = REAL_LAYOUTS                           # the two layouts, with the synthetic heads' CRCs below
# (small apps: the sectors past them are 0xFF in every image, so a run writes some 25 sectors, not 153)
V20 = bootable_flash(OLD.base, noise(20, 0x18000), OLD.limit)
V23 = bootable_flash(NEW.base, noise(23, 0x18000), NEW.limit)
OLD = dataclasses.replace(OLD, boot_crc=zlib.crc32(V20[:OLD.base]))
NEW = dataclasses.replace(NEW, boot_crc=zlib.crc32(V23[:NEW.base]))
V20_PKG, V23_PKG = package(V20, "BlackBox_020"), package(V23, "BlackBox_023")
PEDALS = {OLD: pedal_with(V20), NEW: pedal_with(V23)}
PACKAGES = {OLD: V20_PKG, NEW: V23_PKG}

app = b"OP-PRODUCT:PocketX_900".ljust(32, b"\0") + noise(7, 0x10000)
with contextlib.redirect_stdout(io.StringIO()):
    pxpkg.build(app, b"OTA" * 100, WORK / "gamut", 99, None, ROOT / "firmware" / "sdk" / "packager")
GAMUT_BIN = WORK / "gamut" / "BlackBox_999-v23.bin"
AREA = GAMUT_BIN.read_bytes()
PIN = WORK / "release.sha256"
PIN.write_text(f"{hashlib.sha256(AREA).hexdigest()}  {GAMUT_BIN}\n")
# another build of this project, as a test channel makes one (node tools/op.mjs package-test rate48)
test_app = b"OP-PRODUCT:PocketX_942".ljust(32, b"\0") + noise(8, 0x10000)
with contextlib.redirect_stdout(io.StringIO()):
    pxpkg.build(test_app, b"OTA" * 100, WORK / "rate48", 42, None, ROOT / "firmware" / "sdk" / "packager")
IMAGE_BIN = WORK / "rate48" / "BlackBox_942-v23.bin"
IMAGE = IMAGE_BIN.read_bytes()


def once_per_file(load):
    """load, with each file's checks run once per test run: they are pure Python and take seconds."""
    done = {}

    def cached(path=None):
        try:
            key = (ui.GAMUT_PIN, path and hashlib.sha256(Path(path).read_bytes()).digest())
        except OSError:
            return load(path)
        if key not in done:
            done[key] = load(path)
        return done[key]
    return cached


LOADS = {name: once_per_file(getattr(ui, name)) for name in ("gamut_area", "image_area", "official_area", "backup_area")}


class Bench:
    """The computer's USB bus with one pedal on it. starts says how the pedal comes each time the bus has been empty
    for a second: "recovery" (the three controls held at power-on) or "uboot" (already in the chip's USB boot state).
    From the recovery mode the pedal goes where its simulation says (recovery: SimRecovery's arguments for each entry
    in turn, the last for every later one); the USB boot state lasts boot_window seconds unless the computer has claimed
    it by then, and in its n-th appearance it drops off the bus after drops[n] commands. After give_up seconds the
    person presses Ctrl-C."""
    POLL = 0.05

    def __init__(self, flash, starts=("recovery",), boot_window=3.0, give_up=120.0, recovery=({},), drops=(), **uboot):
        self.clock = uboot_sim.FakeClock()
        self.uboot = uboot_sim.SimPedal(flash, LOADER, self.clock, **uboot)
        self.uboot.present = False
        self.starts, self.boot_window, self.recovery, self.drops = list(starts), boot_window, list(recovery), list(drops)
        self.end = self.clock.t + give_up
        self.mode, self.rec, self.recoveries, self.claims, self.calls = "off", None, [], [], 0
        self.empty_since = self.clock.t

    def now(self):
        return self.clock.t

    def sleep(self, s):
        self.clock.t += s
        if self.clock.t > self.end:
            raise KeyboardInterrupt

    def appear(self, at):
        self.uboot.reenumerate()
        if self.drops:
            self.uboot.drop_at = len(self.uboot.seen) + self.drops.pop(0)
        self.mode, self.appeared, self.claimed = "uboot", at, False

    def step(self):
        self.calls += 1
        t = self.clock.t
        if self.mode == "recovery":
            self.rec.tick()
            if not self.rec.present:
                self.mode = "gap" if self.rec.next_device == pr.UBOOT else "off"
        if self.mode == "gap" and t >= self.rec.departed_at + self.rec.reset_s:
            self.appear(self.rec.departed_at + self.rec.reset_s)
        if self.mode == "uboot" and (not self.uboot.present or not self.claimed and t >= self.appeared + self.boot_window):
            self.uboot.present, self.mode = False, "off"
        if self.mode != "off":
            self.empty_since = None
        elif self.empty_since is None:
            self.empty_since = t
        if self.mode == "off" and self.starts and t >= self.empty_since + 1:
            self.empty_since = None
            if self.starts.pop(0) == "uboot":
                self.appear(t)
            else:
                flash = bytes(self.uboot.flash)
                kw = self.recovery[min(len(self.recoveries), len(self.recovery) - 1)]
                self.rec = SimRecovery(boot_crc=zlib.crc32(flash[:0x6000]), in_zeros=True, **kw)
                self.rec.clock, self.rec.wait = self.now, self.sleep
                self.recoveries.append(self.rec)
                self.mode = "recovery"

    def present(self):
        self.step()
        return {"recovery": {pr.RECOVERY}, "uboot": {pr.UBOOT}}.get(self.mode, set())

    def open_recovery(self):
        self.step()
        return self.rec if self.mode == "recovery" else None

    def open_uboot(self):
        self.step()
        if self.mode != "uboot":
            return None
        if not self.claimed:
            self.claimed = True
            self.claims.append(self.clock.t - self.appeared)
        return self.uboot

    def frames(self):
        """The commands the recovery mode got, over every entry."""
        return [int.from_bytes(f[4:8], "little") for r in self.recoveries for f in r.frames]


class UbootInstall(unittest.TestCase):
    def setUp(self):
        self.new_backups()
        for patch in (mock.patch.object(ui, "LAYOUTS", (OLD, NEW)), mock.patch.object(ui, "GAMUT_PIN", PIN),
                      *(mock.patch.object(ui, name, load) for name, load in LOADS.items()),
                      mock.patch.object(ur, "get_loader", lambda path=None: LOADER),
                      mock.patch.dict(pr.HEADS, {NEW.boot_crc: "the synthetic V23 head of this test"})):
            patch.start()
            self.addCleanup(patch.stop)

    def new_backups(self):
        self.backups = Path(tempfile.mkdtemp(dir=WORK))

    def run_tool(self, bench, *argv):
        """main() as a user types it, with the bus replaced. Returns (exit code, what the window showed)."""
        with mock.patch.object(ui, "transport", lambda: bench):
            shown = io.StringIO()
            with contextlib.redirect_stdout(shown), contextlib.redirect_stderr(shown):
                rc = ui.main([str(a) for a in argv] + ["--backup-dir", str(self.backups)])
        return rc, shown.getvalue()

    def bench(self, layout, flash=None, **kw):
        kw.setdefault("starts", ("recovery",) if layout is NEW else ("uboot",))
        return Bench(PEDALS[layout] if flash is None else flash, **kw)

    def assert_untouched(self, bench, before, shown=""):
        self.assertEqual((bench.uboot.erases(), bench.uboot.writes()), ([], []), shown)
        self.assertTrue(bytes(bench.uboot.flash) == before, "the flash changed")

    def assert_only_the_area(self, bench, layout, before, end=None):
        """Every erase and write fell in the app area, and nothing outside it changed."""
        end = end or layout.limit
        touched = bench.uboot.erases() + bench.uboot.writes()
        self.assertTrue(all(layout.base <= a < end for a in touched), "an erase or write outside the app area")
        self.assertTrue(bench.uboot.flash[:layout.base] == before[:layout.base], "the boot area changed")
        self.assertTrue(bench.uboot.flash[end:] == before[end:], f"the flash from {end:#x} up changed")

    # ---- the dry run
    def test_the_dry_run_reads_backs_up_compares_and_writes_nothing(self):
        for layout, window in ((NEW, "[0x6000, 0x9f000)"), (OLD, "[0x4000, 0x9d000)")):
            with self.subTest(layout=layout.name):
                n = len(differing(PEDALS[layout], layout))
                self.new_backups()
                bench = self.bench(layout)
                rc, shown = self.run_tool(bench)
                self.assertEqual(rc, 0, shown)
                self.assert_untouched(bench, PEDALS[layout], shown)
                self.assertEqual([p.read_bytes() for p in self.backups.glob("*.dump.bin")], [PEDALS[layout]])
                self.assertIn("dry run: nothing will be written", shown)
                self.assertIn(f"boot area [0, {layout.base:#x}) CRC-32 {layout.boot_crc:#010x}: {layout.name}", shown)
                self.assertIn(f"head [0, {layout.base:#x}) matches the image", shown)
                self.assertIn(f"{n} of 153 sectors in {window} differ", shown)
                self.assertIn(f"Dry run finished, nothing was written. {n} sectors differ", shown)
                self.assertEqual(bench.uboot.seen[-1][0], ur.RUN_APP, "the pedal restarts into its firmware")

    # ---- from the recovery mode to the USB boot state
    def test_the_recovery_mode_gets_one_hello_and_the_leave(self):
        bench = self.bench(NEW)
        rc, shown = self.run_tool(bench)
        self.assertEqual(rc, 0, shown)
        self.assertEqual(bench.frames(), [pr.HELLO, pr.LEAVE])
        self.assertEqual(bench.recoveries[0].write_attempts, [])
        self.assertIn("waiting for the pedal; nothing is sent until it appears", shown)
        self.assertIn("the hello reply came over the control endpoint only", shown)
        self.assertRegex(shown, r"the chip's USB boot state appeared \d+ ms after the leave")
        self.assertIn("pedal found in the chip's USB boot state", shown)

    def test_nothing_is_sent_while_no_pedal_is_there(self):
        bench = Bench(PEDALS[NEW], starts=(), give_up=5)
        rc, shown = self.run_tool(bench)
        self.assertEqual(rc, 130, shown)
        self.assertEqual((bench.recoveries, bench.uboot.seen), ([], []))
        self.assertEqual(shown.count("waiting for the pedal"), 1)

    def test_the_usb_boot_state_is_taken_the_moment_it_appears(self):
        """It lasts only seconds while nothing talks to it: here 0.2 s."""
        bench = self.bench(NEW, boot_window=0.2)
        rc, shown = self.run_tool(bench, "--write")
        self.assertEqual(rc, 0, shown)
        self.assertEqual(len(bench.claims), 1)
        self.assertLessEqual(bench.claims[0], bench.POLL)
        self.assertTrue(bench.uboot.flash[NEW.base:NEW.limit] == AREA)

    def test_the_recovery_mode_ending_before_the_leave(self):
        """The pedal's own reset comes first: the tool sends nothing more, keeps waiting, and takes the next entry."""
        bench = Bench(PEDALS[NEW], starts=("recovery", "recovery"), recovery=(dict(sie_fails_at=5, after_reset="app"), {}))
        rc, shown = self.run_tool(bench, "--write")
        self.assertEqual(rc, 0, shown)
        self.assertIn("the recovery mode ended before the leave was sent", shown)
        self.assertEqual(bench.frames(), [pr.HELLO, pr.HELLO, pr.LEAVE])
        self.assertTrue(bench.uboot.flash[NEW.base:NEW.limit] == AREA)

    def test_a_leave_that_does_not_bring_the_usb_boot_state(self):
        for kw, code, why in ((dict(after_reset="app"), 3, "the chip's USB boot state did not appear within 10 s"),
                              (dict(stays=True), 5, "the pedal stayed in the recovery mode for 10 s after the leave")):
            with self.subTest(code=code):
                bench = self.bench(NEW, recovery=(kw,))
                rc, shown = self.run_tool(bench, "--write")
                self.assertEqual(rc, code, shown)
                self.assertIn(why, shown)
                self.assertEqual(bench.uboot.seen, [])
                self.assert_untouched(bench, PEDALS[NEW])

    def test_a_recovery_mode_that_is_refused_gets_no_leave(self):
        other = bytearray(PEDALS[NEW])
        other[0x5800] ^= 1                                # another boot area: not a head this tool knows
        cases = ((dict(), bytes(other), "is not a head this tool knows: the leave is not sent"),
                 (dict(state=2), None, "in state 2: another tool started an update"),
                 (dict(fault="status"), None, "hello was answered with status 1"),
                 (dict(fault="crc"), None, "no reply to the hello"))
        for kw, flash, why in cases:
            with self.subTest(why=why):
                bench = self.bench(NEW, flash, recovery=(kw,))
                rc, shown = self.run_tool(bench, "--write")
                self.assertEqual(rc, 2, shown)
                self.assertIn(why, shown)
                self.assertEqual(bench.frames(), [pr.HELLO])
                self.assertEqual(bench.uboot.seen, [])

    # ---- the install and the ways back, on both layouts
    def test_install_gamut_then_the_ways_back(self):
        for layout, levels in ((NEW, "PWR 7 15 (BOOT LEVELS)"), (OLD, "PWR 3 11 (BOOT LEVELS)")):
            with self.subTest(layout=layout.name):
                before, end = PEDALS[layout], layout.base + len(AREA)
                todo = differing(before, layout)
                self.new_backups()
                bench = self.bench(layout)
                saved = []
                bench.uboot.on_first_write = lambda: saved.extend(p.read_bytes() for p in self.backups.glob("*.bin"))
                rc, shown = self.run_tool(bench, "--write")
                self.assertEqual(rc, 0, shown)
                self.assertEqual(saved, [before], "the backup was complete on disk before the first write")
                self.assertTrue(bench.uboot.flash[layout.base:end] == AREA, "the area is Gamut's")
                self.assert_only_the_area(bench, layout, before, end)
                self.assertEqual(bench.uboot.erases(), todo, "each sector that differed, once, and no other")
                self.assertEqual(v23_boot(bench.uboot.flash), (layout.base, ENTRY), "the boot loader's checks pass")
                self.assertIn(f"Done: {len(todo)} sectors written and verified, on {layout.name}", shown)
                self.assertIn(levels, shown)
                self.assertIn("node tools/op.mjs dsp", shown)
                self.assertEqual(bench.frames(), [pr.HELLO, pr.LEAVE] if layout is NEW else [])
                gamut = bytes(bench.uboot.flash)
                backup = WORK / f"before-gamut-{layout.base:x}.dump.bin"
                backup.write_bytes(next(self.backups.glob("*.dump.bin")).read_bytes())
                for way in (("--official", PACKAGES[layout]), ("--restore", backup)):
                    with self.subTest(way=way[0]):
                        self.new_backups()
                        back = self.bench(layout, gamut)
                        rc, shown = self.run_tool(back, *way, "--write")
                        self.assertEqual(rc, 0, shown)
                        self.assertTrue(bytes(back.uboot.flash) == before, "every byte of the pedal is as before Gamut")
                        self.assert_only_the_area(back, layout, gamut)
                        self.assertIn("Power-cycle the pedal.", shown)
                        self.assertNotIn("op.mjs dsp", shown)

    def test_a_rerun_after_success_writes_nothing(self):
        bench = self.bench(NEW)
        self.assertEqual(self.run_tool(bench, "--write")[0], 0)
        again = self.bench(NEW, bytes(bench.uboot.flash))
        rc, shown = self.run_tool(again, "--write")
        self.assertEqual(rc, 0, shown)
        self.assertIn("0 of 153 sectors in [0x6000, 0x9f000) differ", shown)
        self.assertEqual((again.uboot.erases(), again.uboot.writes()), ([], []))

    def test_it_resumes_when_the_pedal_drops_off(self):
        """The USB boot state ends in the middle of the write. The same run waits for the pedal again and writes only
        what still differs; so does the command run again after it gave up."""
        for layout in (NEW, OLD):
            start, end, todo = self.bench(layout).starts[0], layout.base + len(AREA), differing(PEDALS[layout], layout)
            with self.subTest(layout=layout.name, how="the same run"):
                bench = self.bench(layout, starts=(start, start), drops=(250,))
                rc, shown = self.run_tool(bench, "--write")
                self.assertEqual(rc, 0, shown)
                self.assertIn("the pedal went away or stopped answering (gone); waiting for it again (1/10)", shown)
                self.assertEqual(shown.count("waiting for the pedal; nothing is sent"), 2)
                self.assertEqual(sorted(set(bench.uboot.erases())), todo)
                self.assertLessEqual(len(bench.uboot.erases()), len(todo) + 1, "only the sectors that still differed")
                self.assertTrue(bench.uboot.flash[layout.base:end] == AREA)
                self.assert_only_the_area(bench, layout, PEDALS[layout], end)
            with self.subTest(layout=layout.name, how="the command again"):
                bench = self.bench(layout, drops=(250,))
                rc, shown = self.run_tool(bench, "--write", "--attempts", "1")
                self.assertEqual(rc, 1, shown)
                self.assertIn("gave up after 1 tries; rerun the command, it resumes where it stopped", shown)
                done = len(set(bench.uboot.erases()))
                self.assertTrue(0 < done < len(todo))
                again = self.bench(layout, bytes(bench.uboot.flash))
                rc, shown = self.run_tool(again, "--write")
                self.assertEqual(rc, 0, shown)
                self.assertLessEqual(len(again.uboot.erases()), len(todo) + 1 - done, "only the sectors that still differed")
                self.assertTrue(again.uboot.flash[layout.base:end] == AREA)
                self.assert_only_the_area(again, layout, PEDALS[layout], end)

    # ---- the refusals, each before any erase
    def test_an_app_area_for_the_other_layout_is_refused(self):
        """The known way to make a V22/V23 pedal dark is an old-layout image written over it."""
        dumps = {}
        for layout in (OLD, NEW):
            dumps[layout] = WORK / f"backup-{layout.base:x}.dump.bin"
            dumps[layout].write_bytes(PEDALS[layout])
        for layout, other in ((NEW, OLD), (OLD, NEW)):
            for way in (("--official", PACKAGES[other]), ("--restore", dumps[other])):
                for write in ((), ("--write",)):
                    with self.subTest(pedal=layout.name, way=way[0], write=bool(write)):
                        bench = self.bench(layout)
                        rc, shown = self.run_tool(bench, *way, *write)
                        self.assertEqual(rc, 2, shown)
                        self.assertIn(f"for {other.name}: its boot area is not this pedal's, which has {layout.name}",
                                      shown)
                        self.assertIn("would overwrite the end of the boot loader; nothing was written", shown)
                        self.assert_untouched(bench, PEDALS[layout], shown)

    def test_an_unknown_head_is_refused(self):
        for layout in (OLD, NEW):
            with self.subTest(layout=layout.name):
                flash = bytearray(PEDALS[layout])
                flash[layout.base - 0x800] ^= 1
                bench = self.bench(layout, bytes(flash), starts=("uboot",))
                rc, shown = self.run_tool(bench, "--write")
                self.assertEqual(rc, 2, shown)
                self.assertIn("REFUSED: the pedal's boot area is not one this tool knows (CRC-32 of [0, 0x4000) 0x", shown)
                self.assertIn(f"{OLD.name}, {OLD.boot_crc:#010x}; {NEW.name}, {NEW.boot_crc:#010x}", shown)
                self.assert_untouched(bench, bytes(flash), shown)
                self.assertEqual(len(list(self.backups.glob("*.dump.bin"))), 1, "the backup is kept all the same")
            self.new_backups()

    def test_another_chip_or_flash_is_refused(self):
        for kw, why in ((dict(key=0x1234), "chip key 0x1234 is not 0x980f"),
                        (dict(flash_id=0xEB6015), "is not a 1 MiB flash"),
                        (dict(flash_id=0xC84014), "flash id 0xc84014 is not one this tool knows"),
                        (dict(vendor="XXXX"), "this is not the WL82 UBOOT1.00 boot state")):
            with self.subTest(why=why):
                bench = Bench(PEDALS[NEW], starts=("uboot",), **kw)
                rc, shown = self.run_tool(bench, "--write")
                self.assertEqual(rc, 2, shown)
                self.assertIn(why, shown)
                self.assert_untouched(bench, PEDALS[NEW], shown)
        accepted = Bench(PEDALS[NEW], starts=("uboot",), flash_id=0x856014)
        self.assertEqual(self.run_tool(accepted, "--write")[0], 0)

    def test_files_that_are_refused_before_the_pedal_is_looked_for(self):
        def changed(data, at):
            b = bytearray(data)
            b[at] ^= 1
            return bytes(b)
        half = bytearray(PEDALS[NEW])
        half[NEW.base:NEW.base + SECTOR] = b"\xFF" * SECTOR      # as a write that was cut leaves it
        files = {"other-build.bin": changed(AREA, 0x3000), "half.dump.bin": bytes(half), "short.dump.bin": PEDALS[NEW][:-1],
                 "unknown-head.dump.bin": changed(PEDALS[NEW], 0x5800), "damaged.fwsc": changed(V23_PKG.read_bytes(), 0x9000)}
        for name, data in files.items():
            (WORK / name).write_bytes(data)
        pocket, ours = WORK / "gamut" / "PocketX_999.fwsc", WORK / "gamut" / "BlackBox_999.fwsc"
        cases = [(("--gamut", WORK / "other-build.bin"), 2, "is not the Gamut app area of the release pin"),
                 (("--gamut", WORK / "missing.bin"), 1, "build Gamut first"),
                 (("--restore", WORK / "half.dump.bin"), 2, "its app area at 0x6000 is not one the boot loader would start"),
                 (("--restore", WORK / "short.dump.bin"), 2, "not a backup of the whole 1 MiB flash"),
                 (("--restore", WORK / "unknown-head.dump.bin"), 2, "its boot area is not one this tool knows"),
                 (("--restore", WORK / "missing.bin"), 1, "cannot read"),
                 (("--official", WORK / "damaged.fwsc"), 2, "the package is damaged"),
                 (("--official", package(changed(V23, 0x5800), "BlackBox_022")), 2, "its boot area is not one this tool knows"),
                 (("--official", pocket), 2, "is not one of M-VAVE's official BlackBox packages"),
                 (("--official", ours), 2, "is not one of M-VAVE's official BlackBox packages"),
                 (("--official", GAMUT_BIN), 2, "not a readable package")]
        for argv, code, why in cases:
            with self.subTest(argv=argv[0], file=argv[1].name):
                bench = self.bench(NEW)
                rc, shown = self.run_tool(bench, *argv, "--write")
                self.assertEqual(rc, code, shown)
                self.assertIn(why, shown)
                self.assertEqual(bench.calls, 0, "the bus was looked at before the file passed its checks")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            ui.main(["--official", str(V23_PKG), "--restore", str(WORK / "half.dump.bin")])

    # ---- another app area of this project: --image
    def typed(self, *answers):
        """input() answering in turn; a question past them fails the test."""
        it = iter(answers)

        def answer():
            a = next(it, None)
            if a is None:
                raise AssertionError("asked once more than expected")
            if a is EOFError:
                raise EOFError
            return a
        return mock.patch("builtins.input", answer)

    def test_an_image_dry_run_confirmed_write_and_the_way_back(self):
        digest = hashlib.sha256(IMAGE).hexdigest()
        for layout, official in ((NEW, "BlackBox_023.fwsc"), (OLD, "BlackBox_020.fwsc")):
            with self.subTest(layout=layout.name):
                before, end = PEDALS[layout], layout.base + len(IMAGE)
                todo = differing(before, layout, IMAGE)
                self.new_backups()
                bench = self.bench(layout)
                with self.typed():
                    rc, shown = self.run_tool(bench, "--image", IMAGE_BIN)
                self.assertEqual(rc, 0, shown)
                self.assert_untouched(bench, before, shown)
                self.assertIn(f"the app area {IMAGE_BIN}, identity BlackBox_942, SHA-256 {digest}", shown)
                self.assertIn("the sectors that differ, the only ones --write erases and writes: "
                              f"[{todo[0]:#x}, ", shown)
                self.assertIn(f"--official {official} --write", shown)
                self.assertIn("tools/uboot_install.py --restore ", shown)
                self.new_backups()
                bench = self.bench(layout)
                with self.typed("yes"):
                    rc, shown = self.run_tool(bench, "--image", IMAGE_BIN, "--write")
                self.assertEqual(rc, 0, shown)
                self.assertIn("it is not the release's app area. Type yes", shown)
                self.assertTrue(bench.uboot.flash[layout.base:end] == IMAGE, "the area is the image's")
                self.assert_only_the_area(bench, layout, before, end)
                self.assertEqual(bench.uboot.erases(), todo, "each sector that differed, once, and no other")
                self.assertEqual(v23_boot(bench.uboot.flash), (layout.base, ENTRY), "the boot loader's checks pass")
                self.assertIn(f"Done: {len(todo)} sectors written and verified, on {layout.name}", shown)
                self.assertIn(f"--official {official} --write", shown)
                self.assertNotIn("op.mjs dsp", shown)
                back = self.bench(layout, bytes(bench.uboot.flash))
                with self.typed():
                    rc, shown = self.run_tool(back, "--write")
                self.assertEqual(rc, 0, shown)
                self.assertTrue(back.uboot.flash[layout.base:layout.base + len(AREA)] == AREA, "the release is back")
                self.assert_only_the_area(back, layout, bytes(bench.uboot.flash))

    def test_an_image_is_written_only_after_a_typed_yes(self):
        for answers in (("",), ("y",), ("YES please",), (EOFError,)):
            with self.subTest(answer=answers[0]):
                bench = self.bench(NEW)
                with self.typed(*answers):
                    rc, shown = self.run_tool(bench, "--image", IMAGE_BIN, "--write")
                self.assertEqual(rc, 4, shown)
                self.assertIn("not confirmed: nothing was sent to the pedal", shown)
                self.assertEqual(bench.calls, 0, "the bus was looked at before the yes")
        bench = self.bench(NEW)
        with self.typed():                                   # the release's own bytes: no question
            rc, shown = self.run_tool(bench, "--image", GAMUT_BIN, "--write")
        self.assertEqual(rc, 0, shown)
        self.assertTrue(bench.uboot.flash[NEW.base:NEW.limit] == AREA)

    def test_an_image_resumes_when_the_pedal_drops_off(self):
        end, todo = NEW.base + len(IMAGE), differing(PEDALS[NEW], NEW, IMAGE)
        bench = self.bench(NEW, drops=(250,))
        with self.typed("yes"):
            rc, shown = self.run_tool(bench, "--image", IMAGE_BIN, "--write", "--attempts", "1")
        self.assertEqual(rc, 1, shown)
        done = len(set(bench.uboot.erases()))
        self.assertTrue(0 < done < len(todo))
        again = self.bench(NEW, bytes(bench.uboot.flash))
        with self.typed("yes"):
            rc, shown = self.run_tool(again, "--image", IMAGE_BIN, "--write")
        self.assertEqual(rc, 0, shown)
        self.assertLessEqual(len(again.uboot.erases()), len(todo) + 1 - done, "only the sectors that still differed")
        self.assertTrue(again.uboot.flash[NEW.base:end] == IMAGE)
        self.assert_only_the_area(again, NEW, PEDALS[NEW], end)

    def test_a_custom_image_installs_after_the_warning_and_a_typed_yes(self):
        """No app area head the boot loader knows: it warns, and writes after the yes; the boot area stays."""
        custom = noise(5, 0x20000)
        path = WORK / "custom.bin"
        path.write_bytes(custom)
        for layout in (NEW, OLD):
            with self.subTest(layout=layout.name):
                before, end = PEDALS[layout], layout.base + len(custom)
                self.new_backups()
                bench = self.bench(layout)
                with self.typed():
                    rc, shown = self.run_tool(bench, "--image", path)
                self.assertEqual(rc, 0, shown)
                self.assert_untouched(bench, before, shown)
                self.assertIn("WARNING: the boot loader would not start this image (its first 32 bytes are not an app "
                              "area head", shown)
                self.assertIn(f"the app area {path}, SHA-256 {hashlib.sha256(custom).hexdigest()}", shown)
                self.assertIn("--official BlackBox_0", shown)
                self.new_backups()
                bench = self.bench(layout)
                with self.typed("yes"):
                    rc, shown = self.run_tool(bench, "--image", path, "--write")
                self.assertEqual(rc, 0, shown)
                self.assertLess(shown.index("WARNING"), shown.index("Type yes"), "the warning comes before the question")
                self.assertTrue(bench.uboot.flash[layout.base:end] == custom)
                self.assert_only_the_area(bench, layout, before, end)
                back = self.bench(layout, bytes(bench.uboot.flash), starts=("uboot",))
                rc, shown = self.run_tool(back, "--official", PACKAGES[layout], "--write")
                self.assertEqual(rc, 0, shown)
                self.assertTrue(bytes(back.uboot.flash) == before, "the official firmware is back, byte for byte")

    def test_images_that_are_refused(self):
        roomy = max(l.limit - l.base for l in (OLD, NEW))
        files = {"truncated.bin": IMAGE[:-1], "empty.bin": b"", "oversized.bin": IMAGE + b"\xFF" * (roomy - len(IMAGE) + SECTOR),
                 "v20-flash.bin": V20, "v23-flash.bin": V23, "v23-boot-area.bin": V23[:NEW.base] + IMAGE[:0x10000]}
        for name, data in files.items():
            (WORK / name).write_bytes(data)
        cases = [("truncated.bin", 2, "not a whole number of 4 KiB sectors"),
                 ("empty.bin", 2, "not a whole number of 4 KiB sectors"),
                 ("oversized.bin", 2, "more than the largest app area of a known layout"),
                 ("v20-flash.bin", 2, "more than the largest app area of a known layout"),
                 ("v23-flash.bin", 2, "starts with a flash head"),
                 ("v23-boot-area.bin", 2, "starts with a flash head"),
                 ("missing.bin", 1, "cannot read")]
        for name, code, why in cases:
            with self.subTest(file=name):
                bench = self.bench(NEW)
                with self.typed("yes"):
                    rc, shown = self.run_tool(bench, "--image", WORK / name, "--write")
                self.assertEqual(rc, code, shown)
                self.assertIn(why, shown)
                self.assertNotIn("Type yes", shown)
                self.assertEqual(bench.calls, 0, "the bus was looked at before the file passed its checks")
        for package in (WORK / "rate48" / "BlackBox_942.fwsc", V23_PKG):
            with self.subTest(file=package.name):
                bench = self.bench(NEW)
                rc, shown = self.run_tool(bench, "--image", package, "--write")
                self.assertEqual(rc, 2, shown)
                self.assertEqual(bench.calls, 0)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            ui.main(["--image", str(IMAGE_BIN), "--gamut", str(GAMUT_BIN)])

    def test_an_image_for_the_old_layout_only_is_refused_on_the_new_head(self):
        """It fits [0x4000, 0xA5000) but not [0x6000, 0x9F000): refused once the pedal's layout is known."""
        wide = WORK / "wide.bin"
        wide.write_bytes(IMAGE + b"\xFF" * (OLD.limit - OLD.base - len(IMAGE)))
        bench = self.bench(NEW)
        with self.typed("yes"):
            rc, shown = self.run_tool(bench, "--image", wide, "--write")
        self.assertEqual(rc, 2, shown)
        self.assertIn(f"would end at {NEW.base + OLD.limit - OLD.base:#x}, past {NEW.limit:#x}; nothing was written", shown)
        self.assert_untouched(bench, PEDALS[NEW], shown)
        bench = self.bench(OLD)
        with self.typed("yes"):
            rc, shown = self.run_tool(bench, "--image", wide, "--write")
        self.assertEqual(rc, 0, shown)
        self.assert_only_the_area(bench, OLD, PEDALS[OLD])

    def test_the_window_guard_holds_whatever_the_plan(self):
        """The plan gives the window, and uboot_rescue's Uboot refuses every erase and write outside it."""
        sim = uboot_sim.SimPedal(PEDALS[NEW], LOADER)
        dev = ur.Uboot(sim)
        image, window = ui.plan_for(ui.gamut_area(), lambda m: None, [])(ur.Chip(0x980F, 0xEB6014, 1 << 20, 512),
                                                                         PEDALS[NEW])
        self.assertEqual((window, image[:NEW.base]), (ur.Window(NEW.base, NEW.limit), PEDALS[NEW][:NEW.base]))
        dev.window = window
        ur.attach(dev, LOADER, lambda m: None)
        for addr in (0, 0x4000, 0x5000, NEW.limit, 0xFF000):
            self.assertRaises(ur.GuardError, dev.erase_sector, addr)
            self.assertRaises(ur.GuardError, dev.flash_write, addr, b"x" * 512)
        self.assertEqual((sim.erases(), sim.writes()), ([], []))

    def test_macos_needs_sudo_before_the_pedal_is_switched_on(self):
        with mock.patch.object(ui.sys, "platform", "darwin"), mock.patch.object(ur, "as_root", lambda: False):
            shown = io.StringIO()
            with contextlib.redirect_stdout(shown), contextlib.redirect_stderr(shown):
                rc = ui.main([])
        self.assertEqual(rc, 1, shown.getvalue())
        self.assertIn("run the command again with sudo", shown.getvalue())

    # ---- the real heads, pin and files
    def test_the_two_known_heads(self):
        self.assertEqual([(l.base, l.limit, l.boot_crc) for l in REAL_LAYOUTS],
                         [(0x4000, 0xA5000, 0x5A2121FF), (0x6000, 0x9F000, 0xB19D96A1)])
        self.assertEqual(REAL_LAYOUTS[1].boot_crc, next(iter(pr.HEADS)), "the head the recovery helper knows")

    @unittest.skipUnless(BUILT, "--built: the Gamut app area the build made, against the release pin")
    def test_the_built_gamut_is_the_pinned_one(self):
        with mock.patch.object(ui, "GAMUT_PIN", ROOT / "firmware" / "apps" / "gamut" / "release.sha256"):
            for layout in (OLD, NEW):
                with self.subTest(layout=layout.name):
                    bench = self.bench(layout)
                    rc, shown = self.run_tool(bench, "--write")
                    self.assertEqual(rc, 0, shown)
                    self.assertEqual(v23_boot(bench.uboot.flash), (layout.base, ENTRY))
                    self.assert_only_the_area(bench, layout, PEDALS[layout])

    @unittest.skipUnless(OFFICIAL, "an official BlackBox package")
    def test_official_packages(self):
        """M-VAVE's own flash.bin as the pedal, with the tool's real table of heads."""
        with mock.patch.object(ui, "LAYOUTS", REAL_LAYOUTS):
            for name in OFFICIAL:
                with self.subTest(package=Path(name).name):
                    _, L, tag, u = fw.load(name)
                    fl = next(L[e["off"]:e["off"] + e["len"]] for e in u["ents"] if e["name"] == "flash.bin")
                    layout = ui.layout_of(fl, tag)
                    self.assertEqual(layout.base, fw.app_base(fl), "the layout named by the CRC is the head's own")
                    before = pedal_with(fl)
                    bench = Bench(before, starts=("recovery",) if layout.base == 0x6000 else ("uboot",))
                    rc, shown = self.run_tool(bench, "--write")
                    self.assertEqual(rc, 0, shown)
                    self.assertEqual(v23_boot(bench.uboot.flash), (layout.base, ENTRY))
                    self.assert_only_the_area(bench, layout, before, layout.base + len(AREA))
                    back = Bench(bytes(bench.uboot.flash), starts=("uboot",))
                    rc, shown = self.run_tool(back, "--official", name, "--write")
                    self.assertEqual(rc, 0, shown)
                    self.assertTrue(bytes(back.uboot.flash) == before, f"{tag} is back, byte for byte")
                    for other in OFFICIAL:
                        if ui.official_area(other).boot != fl[:layout.base]:
                            wrong = Bench(before, starts=("uboot",))
                            rc, shown = self.run_tool(wrong, "--official", other, "--write")
                            self.assertEqual(rc, 2, shown)
                            self.assert_untouched(wrong, before, shown)


if __name__ == "__main__":
    unittest.main(verbosity=1)
