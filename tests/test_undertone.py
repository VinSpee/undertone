#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""tools/undertone.py and its guided screens (tools/undertone_screens.py), with no hardware: the commands rescue,
install and check against the simulated pedals of tests/uboot_sim.py and tests/test_uboot_install.py (the restore, the
dry run and the install, each only after a typed yes; the refusals and their advice); the guided screens as a state
machine with a stand-in for the tools; the key reader's mapping; the theme and colour depth from the terminal; and the
guided rescue end to end on a simulated pedal, driven by key presses, in the full-screen view and in the plain one.
  python3 tests/test_undertone.py [--transcript FILE]
--transcript also writes the plain frames of the guided rescue to FILE (docs/undertone-guided-rescue.txt).
"""
import contextlib, io, os, random, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPT = None
if "--transcript" in sys.argv:
    i = sys.argv.index("--transcript")
    TRANSCRIPT = Path(sys.argv[i + 1])
    del sys.argv[i:i + 2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))
import test_uboot_install as tu                # its simulated bus, layouts and Gamut area
import uboot_sim
from fw_layouts import flash_image
import pxpkg
import undertone as u
import undertone_screens as s
from undertone_screens import Screen, Guide, Caps
ur, ui = u.ur, u.ui

WORK = Path(tu.WORK)
LOADER = tu.LOADER
DARK = (0x4000, 0xA3000)                       # what an install for the old layout writes, whatever the head


def noise(seed, n):
    return random.Random(seed).randbytes(n)


FIRMWARE = WORK / "firmware"
FIRMWARE.mkdir()
for n, (v, (base, length)) in enumerate({"020": (0x4000, 0xA5000), "023": (0x6000, 0x9F000)}.items()):
    (FIRMWARE / f"BlackBox_{v}.fwsc").write_bytes(
        pxpkg.ufw(flash_image(base, noise(10 + n, 0x80000), length), b"OTA" * 100, f"BlackBox_{v}"))
IMAGE = {v: ur.load_image(package=FIRMWARE / f"BlackBox_{v}.fwsc") for v in ("020", "023")}


def dark_pedal(version):
    """A pedal that had this official firmware and went dark after an install for the old layout."""
    flash = bytearray(noise(20, ur.FLASH_SIZE))
    flash[:len(IMAGE[version])] = IMAGE[version]
    flash[DARK[0]:DARK[1]] = noise(21, DARK[1] - DARK[0])
    return bytes(flash)


class SimUsb:
    """The pedal's USB boot state: not there at the first look (or for `absent` seconds), then there, and back again
    after each restart."""
    POLL = 0.01

    def __init__(self, sim, absent=0.0):
        self.sim, self.calls, self.until = sim, 0, time.monotonic() + absent

    def open_pedal(self):
        self.calls += 1
        return None if self.calls == 1 or time.monotonic() < self.until else self.sim.reenumerate()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.backups = Path(tempfile.mkdtemp(dir=WORK))
        self.opts = u.Options(None, str(self.backups), 10)
        for patch in (mock.patch.object(u, "FIRMWARE", FIRMWARE), mock.patch.object(ur, "get_loader", lambda p=None: LOADER),
                      mock.patch.object(u, "permission_problem", lambda: None),
                      mock.patch.object(ui, "LAYOUTS", (tu.OLD, tu.NEW)), mock.patch.object(ui, "GAMUT_PIN", tu.PIN),
                      *(mock.patch.object(ui, name, load) for name, load in tu.LOADS.items()),
                      mock.patch.dict(tu.pr.HEADS, {tu.NEW.boot_crc: "the synthetic V23 head of this test"})):
            patch.start()
            self.addCleanup(patch.stop)

    def rescue_pedal(self, flash, absent=0.0):
        sim = uboot_sim.SimPedal(flash, LOADER)
        patch = mock.patch.object(u, "rescue_transport", lambda: SimUsb(sim, absent))
        patch.start()
        self.addCleanup(patch.stop)
        return sim

    def bench(self, layout, runs=2):
        bench = tu.Bench(tu.PEDALS[layout], starts=(("recovery",) if layout is tu.NEW else ("uboot",)) * runs)
        patch = mock.patch.object(u, "install_transport", lambda: bench)
        patch.start()
        self.addCleanup(patch.stop)
        return bench

    def command(self, name, answer, **args):
        """A command as typed, with the answer typed at its prompt. Returns (exit code, what the window showed)."""
        a = u.parser().parse_args([name])
        for k, v in args.items():
            setattr(a, k, v)
        a.opts = self.opts
        shown = io.StringIO()
        with contextlib.redirect_stderr(shown):
            rc = u.COMMANDS[name](a, u.Out(shown), lambda prompt: (shown.write(prompt), answer)[1])
        return rc, shown.getvalue()

    def backups_saved(self):
        return sorted(self.backups.glob("blackbox-*.dump.bin"))


class Commands(Fixture):
    def test_rescue_checks_then_restores_only_after_yes(self):
        before = dark_pedal("023")
        sim = self.rescue_pedal(before)
        rc, shown = self.command("rescue", "no")
        self.assertEqual(rc, u.NOT_CONFIRMED, shown)
        self.assertEqual((sim.erases(), sim.writes()), ([], []), shown)
        self.assertIn("head [0, 0x4000) matches the image", shown)
        self.assertIn("The pedal matches BlackBox_023.fwsc", shown)
        self.assertIn("Stopped. Nothing was written. Backup:", shown)
        self.assertTrue(self.backups_saved() and self.backups_saved()[0].read_bytes() == before, "the backup")
        rc, shown = self.command("rescue", "yes")
        self.assertEqual(rc, 0, shown)
        self.assertTrue(bytes(sim.flash[:len(IMAGE["023"])]) == IMAGE["023"], "the pedal holds the V23 image")
        self.assertTrue(all(DARK[0] <= a < len(IMAGE["023"]) for a in sim.erases() + sim.writes()))
        self.assertIn("sectors written and verified", shown)
        self.assertIn("Do not install Gamut on this pedal from an installer page", shown)
        self.assertIn("undertone - rescue a pedal that will not start\nrescue kit", shown)

    def test_rescue_picks_the_file_whose_head_is_the_pedals(self):
        sim = self.rescue_pedal(dark_pedal("020"))
        rc, shown = self.command("rescue", "yes")
        self.assertEqual(rc, 0, shown)
        self.assertIn("The pedal matches BlackBox_020.fwsc", shown)
        self.assertTrue(bytes(sim.flash[:len(IMAGE["020"])]) == IMAGE["020"])
        self.assertNotIn("Do not install Gamut", shown)

    def test_rescue_keeps_the_tools_refusal_and_names_the_file_the_pedal_needs(self):
        before = dark_pedal("023")
        sim = self.rescue_pedal(before)
        fp = u.hf.fingerprint(before)
        with mock.patch.dict(u.hf.HEADS, {fp: ("M-VAVE V22 or V23", "Path B: use firmware/BlackBox_023.fwsc")}):
            rc, shown = self.command("rescue", "yes", package=str(FIRMWARE / "BlackBox_020.fwsc"))
        self.assertEqual(rc, 2, shown)
        self.assertIn("REFUSED: the flash head [0, 0x4000) is not the image's head", shown)
        self.assertIn("The pedal had M-VAVE V22 or V23.", shown)
        self.assertIn("Next: put M-VAVE's BlackBox_023.fwsc in the firmware folder", shown)
        self.assertNotIn("Type yes", shown)
        self.assertEqual((sim.erases(), sim.writes()), ([], []))
        self.assertTrue(self.backups_saved(), "the backup comes first")

    def test_rescue_with_no_file_reads_the_pedal_and_says_which_file(self):
        before = dark_pedal("020")
        sim = self.rescue_pedal(before)
        fp = u.hf.fingerprint(before)
        with mock.patch.object(u, "FIRMWARE", WORK / "empty"), \
                mock.patch.dict(u.hf.HEADS, {fp: ("M-VAVE V16, V17 or V20", "Path A: use firmware/BlackBox_020.fwsc")}):
            rc, shown = self.command("rescue", "yes")
        self.assertEqual(rc, 1, shown)
        self.assertIn("Check finished, nothing was written", shown)
        self.assertIn("Next: put M-VAVE's BlackBox_020.fwsc in the firmware folder", shown)
        self.assertEqual((sim.erases(), sim.writes()), ([], []))

    def test_a_damaged_file_stops_before_the_pedal_is_asked(self):
        raw = bytearray((FIRMWARE / "BlackBox_023.fwsc").read_bytes())
        raw[len(raw) // 2] ^= 1
        bad = WORK / "damaged.fwsc"
        bad.write_bytes(raw)
        sim = self.rescue_pedal(dark_pedal("023"))
        rc, shown = self.command("rescue", "yes", package=str(bad))
        self.assertEqual((rc, sim.seen), (1, []), shown)
        self.assertIn("CRC check failed", shown)

    def test_install_dry_run_then_gamut_only_after_yes(self):
        for layout in (tu.NEW, tu.OLD):
            with self.subTest(layout=layout.name):
                bench = self.bench(layout, runs=1)
                rc, shown = self.command("install", "nope")
                self.assertEqual(rc, u.NOT_CONFIRMED, shown)
                self.assertEqual((bench.uboot.erases(), bench.uboot.writes()), ([], []))
                self.assertIn("Dry run finished, nothing was written", shown)
                bench = self.bench(layout)
                rc, shown = self.command("install", "yes")
                self.assertEqual(rc, 0, shown)
                self.assertTrue(bench.uboot.flash[layout.base:layout.base + len(tu.AREA)] == tu.AREA)
                self.assertTrue(bench.uboot.flash[:layout.base] == tu.PEDALS[layout][:layout.base], "the boot area")
                self.assertIn("First-run check", shown)
                self.assertIn(f"PWR {layout.levels} (BOOT LEVELS)", shown)

    def test_install_keeps_the_refusal_of_a_package_for_the_other_layout(self):
        bench = self.bench(tu.NEW)
        rc, shown = self.command("install", "yes", official=str(tu.PACKAGES[tu.OLD]))
        self.assertEqual(rc, 2, shown)
        self.assertIn("REFUSED", shown)
        self.assertEqual((bench.uboot.erases(), bench.uboot.writes()), ([], []))

    def test_install_says_plainly_when_gamut_is_not_in_the_folder(self):
        with mock.patch.object(ui, "GAMUT_PIN", WORK / "no-pin"):
            rc, shown = self.command("install", "yes")
        self.assertEqual(rc, 1, shown)
        self.assertIn("Gamut's file is not in this folder", shown)

    def test_check_reads_names_and_writes_nothing(self):
        bench = self.bench(tu.NEW, runs=1)
        rc, shown = self.command("check", "")
        self.assertEqual(rc, 0, shown)
        self.assertEqual((bench.uboot.erases(), bench.uboot.writes()), ([], []))
        self.assertIn("found in:  M-VAVE recovery mode", shown)
        self.assertIn(f"layout:    {tu.NEW.name}", shown)
        self.assertIn("app area:  M-VAVE's own firmware", shown)
        self.assertTrue(self.backups_saved()[0].read_bytes() == tu.PEDALS[tu.NEW])

    def test_no_permission_no_pedal(self):
        out = io.StringIO()
        with mock.patch.object(u, "permission_problem", lambda: u.SUDO), mock.patch.object(sys.stdin, "isatty", lambda: False):
            self.assertFalse(u.allowed(u.Out(out), ["rescue"]))
        self.assertIn("needs root on macOS and Linux", out.getvalue())

    def test_a_write_job_must_name_one_file(self):
        with self.assertRaises(ValueError):
            u.run(u.Job("rescue", True, dict(IMAGE)), print)
        with self.assertRaises(ValueError):
            u.run(u.Job("check", True), print)

    def test_version_and_help(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(u.main(["version"]), 0)
        self.assertRegex(out.getvalue(), r"^undertone, rescue kit \d+\n$")
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            u.main(["--help"])
        self.assertIn("rescue", out.getvalue())


class Launchers(unittest.TestCase):
    """The two files a person types. The Windows one cannot run here: only its line endings are checked."""

    def test_the_windows_launcher_has_crlf_line_endings(self):
        raw = (ROOT / "undertone.cmd").read_bytes()
        self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"))

    def test_the_unix_launcher_runs_undertone(self):
        import subprocess
        r = subprocess.run(["sh", str(ROOT / "undertone"), "version"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"^undertone, rescue kit \d+$")
        self.assertTrue(os.access(ROOT / "undertone", os.X_OK))


# ---------------------------------------------------------------- the screens
class Keys(unittest.TestCase):
    def test_unix_keys(self):
        for seq, name in (("\x1b[A", "up"), ("\x1bOB", "down"), ("\r", "enter"), ("\n", "enter"), ("\x1b", "back"),
                          ("\x1b[D", "back"), ("q", "quit"), ("b", "back"), ("3", "3"), ("0", None), ("x", None),
                          ("\x1b[C", None)):
            self.assertEqual(s.decode(seq), name, repr(seq))

    def test_windows_keys(self):
        self.assertEqual(s.decode_windows("\xe0", "H"), "up")
        self.assertEqual(s.decode_windows("\x00", "P"), "down")
        self.assertEqual(s.decode_windows("\r"), "enter")
        self.assertEqual(s.decode_windows("\x1b"), "back")
        self.assertEqual(s.decode_windows("2"), "2")
        with self.assertRaises(KeyboardInterrupt):
            s.decode_windows("\x03")

    def test_the_terminal_says_its_theme_and_depth(self):
        self.assertEqual(s.theme_of("\x1b]11;rgb:ffff/ffff/fefe\x07"), "light")
        self.assertEqual(s.theme_of("\x1b]11;rgb:0b0b/0b0b/0a0a\x1b\\"), "dark")
        self.assertIsNone(s.theme_of(""))
        self.assertEqual(s.theme_from_env({"COLORFGBG": "0;15"}), "light")
        self.assertEqual(s.theme_from_env({"COLORFGBG": "15;default;0"}), "dark")
        self.assertIsNone(s.theme_from_env({}))
        self.assertEqual(s.depth_from_env({"COLORTERM": "truecolor"}), "truecolor")
        self.assertEqual(s.depth_from_env({"TERM": "xterm-256color"}), "256")
        self.assertEqual(s.depth_from_env({"TERM": "xterm"}), "16")

    def test_plain_view_when_not_a_terminal_or_no_colour(self):
        tty = io.StringIO()
        tty.isatty = lambda: True
        with mock.patch.object(sys.stdin, "isatty", lambda: True), \
                mock.patch.object(s.shutil, "get_terminal_size", lambda d=None: os.terminal_size((100, 30))):
            self.assertIsNotNone(s.capabilities({"TERM": "xterm-256color"}, tty))
            self.assertIsNone(s.capabilities({"NO_COLOR": "1"}, tty))
            self.assertIsNone(s.capabilities({"TERM": "dumb"}, tty))
            self.assertFalse(s.capabilities({"UNDERTONE_NO_MOTION": "1"}, tty).motion)
        with mock.patch.object(sys.stdin, "isatty", lambda: True), \
                mock.patch.object(s.shutil, "get_terminal_size", lambda d=None: os.terminal_size((60, 30))):
            self.assertIsNone(s.capabilities({}, tty), "too narrow")
        self.assertIsNone(s.capabilities({}, io.StringIO()))


class Frames(unittest.TestCase):
    def test_every_row_fits_and_the_selected_choice_is_lit(self):
        for caps in (Caps(), Caps(depth="16", unicode=False)):
            for cols, rows in ((80, 24), (100, 30), (62, 24)):
                screen = Screen("hold the three lit buttons", ["Switch your pedal off."], pedal=True,
                                status=("spin", "looking", 0), warn=("Use a cable straight into this computer.",))
                frame = s.compose(screen, caps, cols, rows)
                self.assertEqual(len(frame), rows)
                self.assertTrue(all(s.runs_width(r) <= cols for r in frame), (cols, rows))
                menu = s.compose(Screen("what?", (), (("a", "one"), ("b", "two")), selected=1), caps, cols, rows)
                lit = [r for r in menu if any("on_lamp" in st for _, st in r)]
                self.assertEqual(len(lit), 1)
                self.assertIn("2  two", "".join(t for t, _ in lit[0]))

    def test_ascii_when_the_console_has_no_unicode(self):
        text = s.plain(s.compose(Screen("t", (), (("a", "one"),), pedal=True, status=("bar", "writing", 0.5)),
                                 Caps(unicode=False), 80, 24))
        self.assertTrue(all(ord(c) < 128 for c in text), text)

    def test_palette_depths(self):
        for depth in ("truecolor", "256", "16"):
            for theme in ("dark", "light", None):
                code = s.Palette(depth, theme).sgr(("on_lamp", "bold"))
                self.assertTrue(code.startswith("\x1b[") and code.endswith("m"), (depth, theme))

    def test_progress_reads_the_tools_lines(self):
        p = s.Progress(write=True)
        for line, phase in (("waiting for the pedal in its UBOOT state", "looking"), ("pedal found", "found"),
                            ("loader running: chip key 0x980f", "reading"), ("flash read: 1024 KiB", "saving"),
                            ("backup saved: /tmp/b.bin", "checking"), ("head [0, 0x4000) matches the image", "checking"),
                            ("32 of 155 sectors in [0x4000, 0x9f000) differ", "writing"),
                            ("  written 16/32", "writing"), ("run-app sent: the pedal restarts", "restarting")):
            p.feed(line)
            self.assertEqual(p.phase, phase, line)
        self.assertEqual(p.backup, "/tmp/b.bin")
        p.feed("the pedal went away or stopped answering (x); waiting for it again (1/10)")
        self.assertEqual(p.phase, "again")


class Scripted:
    """A view that answers each screen from a script of (words of the title, choice key) and records the screens."""

    def __init__(self, script, outcomes=()):
        self.script, self.outcomes, self.seen, self.jobs = list(script), list(outcomes), [], []

    def ask(self, screen):
        self.seen.append(screen.title)
        want, key = self.script.pop(0)
        assert want in screen.title, (want, screen.title)
        return key

    def work(self, screen, job_fn, log, write=False, hint=()):
        self.seen.append(screen.title)
        return job_fn(None, None, threading.Event())


class StateMachine(Fixture):
    def guide(self, script, outcomes, start="menu"):
        view = Scripted(script)
        jobs = []

        def run(job, log, say, stop):
            jobs.append(job)
            return outcomes.pop(0)
        opened = []
        g = Guide(view, self.opts, start, run=run, open_url=opened.append)
        return g, view, jobs, opened

    def test_menu_quit(self):
        g, view, jobs, _ = self.guide([("what would you like", "quit")], [])
        self.assertEqual(g.go().code, 0)
        self.assertEqual(jobs, [])

    def test_declining_the_write_writes_nothing(self):
        found = u.Outcome(0, "Read-only run finished", 3, self.backups / "b.bin", b"", "BlackBox_023.fwsc")
        g, view, jobs, _ = self.guide([("what would", "rescue"), ("fix a pedal", "go"), ("can be fixed", "go"),
                                       ("replace", "no"), ("nothing was changed", "done")], [found])
        r = g.go()
        self.assertEqual([j.write for j in jobs], [False])
        self.assertEqual(r.backup, self.backups / "b.bin")
        self.assertIn("Nothing was written to your pedal.", r.lines)

    def test_yes_writes_the_one_matching_file(self):
        found = u.Outcome(0, "Read-only run finished", 3, None, b"", "BlackBox_023.fwsc")
        done = u.Outcome(0, "Done: 3 sectors written and verified. Power-cycle the pedal. Backup: b", 3)
        g, view, jobs, opened = self.guide([("what would", "rescue"), ("fix a pedal", "go"), ("can be fixed", "go"),
                                            ("replace", "yes"), ("is fixed", "guide"), ("is fixed", "done")],
                                           [found, done])
        r = g.go()
        self.assertEqual([(j.write, list(j.images)) for j in jobs],
                         [(False, ["BlackBox_023.fwsc", "BlackBox_020.fwsc"]), (True, ["BlackBox_023.fwsc"])])
        self.assertEqual(opened, [u.GUIDE])
        self.assertIn("Do not install Gamut on it from an installer page: use undertone install.", r.lines)

    def test_going_back_while_looking_returns_to_the_start_of_the_task(self):
        g, view, jobs, _ = self.guide([("what would", "rescue"), ("fix a pedal", "go"), ("fix a pedal", "back"),
                                       ("what would", "quit")], [u.Outcome(130, "back")])
        g.go()
        self.assertEqual(view.seen, ["what would you like to do?", "fix a pedal that will not start",
                                     "checking your pedal", "fix a pedal that will not start",
                                     "what would you like to do?"])

    def test_try_again_after_a_failed_write_asks_before_writing(self):
        found = u.Outcome(0, "Read-only run finished", 3, None, b"", "BlackBox_023.fwsc")
        failed = u.Outcome(1, "ERROR: gave up after 10 tries; rerun the command, it resumes where it stopped")
        g, view, jobs, _ = self.guide([("what would", "rescue"), ("fix a pedal", "go"), ("can be fixed", "go"),
                                       ("replace", "yes"), ("went wrong", "again"), ("replace", "no"),
                                       ("may not start", "done")], [found, failed])
        r = g.go()
        self.assertEqual([j.write for j in jobs], [False, True])
        self.assertNotIn("nothing was changed", view.seen)
        self.assertEqual(r.code, 1)
        self.assertIn("Plug it in and run: undertone rescue  (it continues where it stopped)", r.lines)

    def test_a_stop_in_the_middle_of_a_write_says_how_to_resume(self):
        found = u.Outcome(0, "Read-only run finished", 3, self.backups / "b.bin", b"", "BlackBox_023.fwsc")

        def run(job, log, say, stop):
            if job.write:
                raise KeyboardInterrupt
            return found
        g = Guide(Scripted([("what would", "rescue"), ("fix a pedal", "go"), ("can be fixed", "go"),
                            ("replace", "yes")]), self.opts, run=run)
        with self.assertRaises(KeyboardInterrupt):
            g.go()
        self.assertTrue(g.writing)
        note = "\n".join(g.resume_note())
        self.assertIn("undertone rescue", note)
        self.assertIn(str(self.backups / "b.bin"), note)

    def test_an_unknown_pedal_is_left_alone(self):
        refused = u.Outcome(2, "REFUSED: the flash head", 0, None, dark_pedal("023"))
        g, view, jobs, _ = self.guide([("what would", "rescue"), ("fix a pedal", "go"), ("closer look", "done")],
                                      [refused])
        self.assertEqual(g.go().code, 2)
        self.assertEqual(len(jobs), 1)

    def test_a_problem_offers_try_again(self):
        failed = u.Outcome(1, "ERROR: gave up after 10 tries; rerun the command, it resumes where it stopped")
        found = u.Outcome(0, "Read-only run finished", 3, None, b"", "BlackBox_023.fwsc")
        g, view, jobs, _ = self.guide([("what would", "rescue"), ("fix a pedal", "go"), ("went wrong", "again"),
                                       ("can be fixed", "later"), ("nothing was changed", "done")], [failed, found])
        g.go()
        self.assertEqual(len(jobs), 2)
        self.assertIn("something went wrong", view.seen)

    def test_the_password_restarts_at_the_task(self):
        with mock.patch.object(u, "permission_problem", lambda: u.SUDO), mock.patch.object(ur, "WINDOWS", False):
            g, view, jobs, _ = self.guide([("what would", "check"), ("check your pedal", "go"),
                                           ("needs your password", "go")], [])
            self.assertEqual(g.go().restart, "check")
        g, view, jobs, _ = self.guide([], [u.Outcome(130, "back")], start="check")
        g.view.script = [("check your pedal", "quit")]
        g.go()
        self.assertEqual(view.seen[0], "connect your pedal")

    def test_install_without_gamut_says_where_it_works(self):
        with mock.patch.object(ui, "GAMUT_PIN", WORK / "no-pin"), mock.patch.object(ur, "WINDOWS", False):
            g, view, jobs, _ = self.guide([("what would", "install"), ("not in this folder", "back"),
                                           ("what would", "quit")], [])
            g.go()
        self.assertEqual(jobs, [])


# ---------------------------------------------------------------- end to end: key presses, a simulated pedal
class KeyScript:
    """Key presses, each sent once the screen shows the given words; nothing while the screen shows something else."""

    def __init__(self, view_frames, script):
        self.frames, self.script = view_frames, list(script)

    def read(self, timeout):
        if self.script and self.frames and self.script[0][0] in self.frames[-1]:
            return self.script.pop(0)[1]
        threading.Event().wait(min(timeout, 0.01))
        return None

    def restore(self):
        pass


class WorkKeys:
    """Presses back, then q, once the screen says the pedal restarted; lets the job finish once the screen refuses."""

    def __init__(self, view, release):
        self.view, self.release, self.sent = view, release, []

    def read(self, timeout):
        text = self.view.frames[-1] if self.view.frames else ""
        if "your pedal restarted" in text and len(self.sent) < 2:
            self.sent.append("back" if not self.sent else "quit")
            return self.sent[-1]
        if s.REFUSED in text and len(self.sent) == 2:
            self.release.set()
        threading.Event().wait(0.01)
        return None

    def restore(self):
        pass


class WriteIsNotInterrupted(Fixture):
    def run_work(self, write):
        release, stopped = threading.Event(), []

        def job(log, say, stop):
            say("pedal found")
            say("the pedal went away or stopped answering (x); waiting for it again (1/10)")
            (release if write else stop).wait(5)
            stopped.append(stop.is_set())
            return u.Outcome(130 if stop.is_set() else 0, "done")
        view = s.AnsiView(io.StringIO(), None, Caps(motion=False), size=lambda: os.terminal_size((80, 24)))
        view.keys = WorkKeys(view, release)
        o = view.work(s.Screen("fixing your pedal", []), job, s.Log(self.backups), write)
        return o, stopped, view

    def test_back_and_q_do_nothing_while_a_write_waits_for_the_restarted_pedal(self):
        o, stopped, view = self.run_work(True)
        self.assertEqual((o.code, stopped), (0, [False]))
        self.assertIn(s.REFUSED, "\n".join(view.frames))

    def test_back_still_leaves_a_wait_that_is_not_a_write(self):
        o, stopped, view = self.run_work(False)
        self.assertEqual((o.code, stopped), (130, [True]))
        self.assertNotIn(s.REFUSED, "\n".join(view.frames))


class EndToEnd(Fixture):
    RESCUE = [("what would you like", "1"), ("what would you like", "enter"), ("fix a pedal that", "enter"),
              ("your pedal can be fixed", "enter"), ("replace the software", "down"), ("replace the software", "enter"),
              ("your pedal is fixed", "enter")]

    def test_the_guided_rescue_on_a_simulated_pedal(self):
        before = dark_pedal("023")
        sim = self.rescue_pedal(before, absent=0.4)
        out = io.StringIO()
        view = s.AnsiView(out, None, Caps(motion=False), size=lambda: os.terminal_size((80, 24)))
        view.keys = KeyScript(view.frames, self.RESCUE)
        with view:
            result = Guide(view, self.opts).go()
        self.assertEqual(view.keys.script, [], "every key was used")
        self.assertTrue(bytes(sim.flash[:len(IMAGE["023"])]) == IMAGE["023"], "the pedal holds the V23 image")
        text = "\n".join(view.frames)
        for words in ("looking for your pedal", "found it", "writing",
                      "This replaces the software on your pedal.", "A copy is saved first. Continue?"):
            self.assertIn(words, text)
        self.assertNotIn("sectors", text, "no raw tool output on the screens")
        self.assertTrue(out.getvalue().startswith("\x1b[?1049h") and out.getvalue().endswith("\x1b[?25h\x1b[?1049l"))
        self.assertTrue(any(l.startswith("details: ") for l in result.lines))
        log = Path(next(l for l in result.lines if l.startswith("details: "))[9:]).read_text()
        self.assertIn("sectors written and verified", log)
        self.assertEqual(result.backup.parent, self.backups)
        if TRANSCRIPT:                         # (the test's own folder, as the person's would read)
            TRANSCRIPT.write_text(transcript(f.replace(str(self.backups), "~/OpenPocket-rescue") for f in view.frames))

    def test_the_guided_rescue_in_plain_questions(self):
        before = dark_pedal("020")
        sim = self.rescue_pedal(before)
        answers = iter(["1", "", "", "2", ""])
        out = io.StringIO()
        result = Guide(s.PlainView(out, lambda prompt: (out.write(prompt), next(answers))[1]), self.opts).go()
        self.assertTrue(bytes(sim.flash[:len(IMAGE["020"])]) == IMAGE["020"])
        shown = out.getvalue()
        self.assertIn("  1  no\n  2  yes", shown)
        self.assertIn("saving a copy of your pedal...", shown)
        self.assertIn("writing: 100%", shown)
        self.assertEqual(result.code, 0)

    def test_enter_alone_on_the_question_writes_nothing(self):
        sim = self.rescue_pedal(dark_pedal("023"))
        answers = iter(["1", "", "", "", ""])
        out = io.StringIO()
        Guide(s.PlainView(out, lambda prompt: next(answers)), self.opts).go()
        self.assertEqual((sim.erases(), sim.writes()), ([], []))
        self.assertIn("nothing was changed", out.getvalue())


def transcript(frames):
    """The screens of a run as plain text, one after the other, each in a frame of its own."""
    rule = "+" + "-" * 80 + "+"
    shots = []
    for f in frames:
        lines = f.split("\n")
        shots.append("\n".join([rule] + ["|" + l.ljust(80) + "|" for l in lines] + [rule]))
    return ("The guided rescue of `undertone`, run by tests/test_undertone.py on a simulated pedal at 80 x 24, motion "
            "off: every screen it drew, in order.\n\n" + "\n\n".join(shots) + "\n")


if __name__ == "__main__":
    unittest.main(verbosity=1)
