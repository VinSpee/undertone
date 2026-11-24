# SPDX-License-Identifier: GPL-3.0-only
"""undertone's guided screens: what `undertone` shows when it is started with no command. One short question or one
action a screen, chosen with the arrow keys or a number and Enter; the pedal drawn when it needs the three buttons
held; one calm line of progress while a tool works, its raw lines kept in a log file. The tools and their checks are
undertone.py's (tools/uboot_rescue.py and tools/uboot_install.py); this file only asks and shows.

The look follows the site (docs/site.css): graphite text on the terminal's own ground, the pedal's lime lamp as the one
accent (the selected choice, the lamp, the bar), amber only for "your turn" and for a problem. Standard library only:
ANSI escape codes, keys read through termios (macOS, Linux) or msvcrt (Windows); no curses. Plain numbered questions
instead when the output is not a terminal, the terminal is smaller than 62 x 24, NO_COLOR is set or TERM is dumb.
Motion (the spinner, the lamp's pulse, the bar's easing) is off when UNDERTONE_NO_MOTION is set.
"""
import os, queue, re, select, shutil, subprocess, sys, threading, time, webbrowser
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

import undertone as u
from undertone import Job, Options, Outcome, ur, ui, GuardError, RescueError

WIDTH, MIN_COLS, MIN_ROWS = 60, 62, 24
KEEP_FRAMES = 400
HINT_AFTER = 30.0                              # s of looking before the fix hint
FRAME_S = 0.05

# ---------------------------------------------------------------- the palette (docs/site.css)
INK, LIME, AMBER = (11, 11, 10), (196, 245, 66), (232, 163, 61)
# token -> {theme: colour}; theme is "dark", "light" or None when the terminal did not say. Text is the terminal's own
# foreground. Lime is a ground for ink (15:1) or, as a line, a deeper lime that holds 3:1 on the light ground.
TOKENS = {
    "soft": {"dark": (169, 166, 155), "light": (85, 83, 77), None: (119, 119, 119)},
    "line": {"dark": (85, 83, 77), "light": (201, 198, 187), None: (128, 125, 117)},
    "lamp": {"dark": LIME, "light": (86, 125, 10), None: (109, 154, 20)},
    "warn": {"dark": (240, 180, 90), "light": (122, 74, 0), None: (170, 105, 0)},
}
GROUNDS = {"on_lamp": LIME, "on_warn": AMBER}  # always with ink on top
SIXTEEN = {"soft": "90", "line": "90", "lamp": "32", "warn": "33", "on_lamp": "30;102", "on_warn": "30;43"}


def cube(rgb):
    """The nearest colour of xterm's 256-colour cube."""
    steps = (0, 95, 135, 175, 215, 255)
    idx = [min(range(6), key=lambda i: abs(steps[i] - c)) for c in rgb]
    return 16 + 36 * idx[0] + 6 * idx[1] + idx[2]


class Palette:
    def __init__(self, depth, theme):
        self.depth, self.theme = depth, theme

    def _rgb(self, rgb, ground=False):
        if self.depth == "truecolor":
            return f"{48 if ground else 38};2;{rgb[0]};{rgb[1]};{rgb[2]}"
        return f"{48 if ground else 38};5;{cube(rgb)}"

    def sgr(self, style):
        """The escape for a style: a tuple of tokens, "bold" among them."""
        codes = []
        for t in style:
            if t == "bold":
                codes.append("1")
            elif self.depth == "16" and t in SIXTEEN:
                codes.append(SIXTEEN[t])
            elif t in TOKENS:
                codes.append(self._rgb(TOKENS[t][self.theme]))
            elif t in GROUNDS:
                codes += [self._rgb(INK), self._rgb(GROUNDS[t], True)]
        return f"\x1b[{';'.join(codes)}m" if codes else ""


# ---------------------------------------------------------------- glyphs, with the ASCII a legacy console shows
GLYPHS = {"spin": "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", "ok": "●", "warn": "◆", "pick": "›", "bar": "━", "rest": "─", "lamp": "▐▌",
          "dot": "·", "ellipsis": "…", "box": "╭╮╰╯─│"}
ASCII = {"spin": "-\\|/", "ok": "*", "warn": "!", "pick": ">", "bar": "=", "rest": "-", "lamp": "[]",
         "dot": "-", "ellipsis": "...", "box": "++++-|"}
ART_ASCII = str.maketrans("╭╮╰╯─│┌┐└┘◯◉▣▪", "++++-|++++Oo#.")

# The BlackBox from the front (tools/sim/pedal.html): the MASTER knob, the screen and the knob that is pressed for PUSH
# at the top; the row of seven keys, HOME first; the two footswitches. [P], [H] and [F] are the three controls to hold.
PEDAL = (
    "╭──────────────────────────────────────╮",
    "│   ◯            ┌──────────┐   [P]    │",
    "│ master         │ recovery │   push   │",
    "│                └──────────┘          │",
    "│  [H]  ▪   ▪   ▪   ▪   ▪   ▪          │",
    "│  home                                │",
    "│    ◯                        [F]      │",
    "│                          right foot  │",
    "╰──────────────────────────────────────╯",
)
HELD = {"P": "◉", "H": "▣", "F": "◉"}
LABELS = ("push", "home", "right foot")


@dataclass
class Caps:
    depth: str = "truecolor"                   # "truecolor", "256" or "16"
    theme: str = None                          # "dark", "light" or None
    unicode: bool = True
    motion: bool = True


@dataclass
class Screen:
    title: str
    lines: tuple = ()
    choices: tuple = ()                        # (key, label)
    selected: int = 0
    pedal: bool = False
    status: tuple = None                       # ("spin" | "ok" | "bar", text, fraction)
    warn: tuple = ()                           # amber lines under the status: something to fix, or your turn
    problem: bool = False                      # the title is a problem: an amber mark before it
    finished: bool = False                     # the task is done: the lamp's mark before the title
    aside: tuple = ()                          # quiet lines under the text: where the copy of the pedal is
    foot: str = "choose"                       # "choose", "wait" or "busy"


# ---------------------------------------------------------------- frames: rows of (text, style) runs
def glyph(caps, name):
    return (GLYPHS if caps.unicode else ASCII)[name]


def runs_width(runs):
    return sum(len(t) for t, _ in runs)


def pedal_art(caps, lit):
    """The pedal: its three controls on the lime ground when lit, as lime marks between beats of the pulse; their
    names in lime; the rest in the line colour."""
    rows = []
    for line in PEDAL:
        runs, i = [], 0
        while i < len(line):
            if line[i] == "[":
                g = HELD[line[i + 1]]
                runs.append((f" {g if caps.unicode else g.translate(ART_ASCII)} ",
                             ("on_lamp", "bold") if lit else ("lamp", "bold")))
                i += 3
                continue
            label = next((w for w in LABELS if line.startswith(w, i)), None)
            if label:
                runs.append((label, ("lamp", "bold")))
                i += len(label)
                continue
            runs.append((line[i] if caps.unicode else line[i].translate(ART_ASCII), ("line",)))
            i += 1
        rows.append(merge(runs))
    return rows


def merge(runs):
    out = []
    for t, s in runs:
        if out and out[-1][1] == s:
            out[-1] = (out[-1][0] + t, s)
        else:
            out.append((t, s))
    return out


def wrap(text, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    return lines + ([cur] if cur else [])


def compose(screen, caps, cols, rows, tick=0.0):
    """The whole frame: a list of rows, each a list of (text, style) runs, WIDTH wide and centred."""
    w = min(WIDTH, cols - 2)
    body = []
    lamp = glyph(caps, "lamp")
    kit = f"rescue kit {u.version()}"
    body.append([(lamp, ("lamp",)), (" undertone", ("bold",)), (" " * (w - len(lamp) - 10 - len(kit)), ()),
                 (kit, ("soft",))])
    body.append([(glyph(caps, "rest") * w, ("line",))])
    body.append([])
    mark = ([(glyph(caps, "warn") + " ", ("warn", "bold"))] if screen.problem else
            [(glyph(caps, "ok") + " ", ("lamp", "bold"))] if screen.finished else [])
    body.append(mark + [(screen.title, ("bold",))])
    body.append([])
    for line in screen.lines:
        body += [[(part, ())] for part in wrap(line, w)]
    for i, line in enumerate(screen.aside):
        body += ([[]] if i == 0 else []) + [[(part, ("soft",))] for part in wrap(line, w)]
    if screen.pedal:
        body.append([])
        lit = not caps.motion or int(tick / 0.6) % 2 == 0
        art = pedal_art(caps, lit)
        indent = (w - len(PEDAL[0])) // 2
        body += [[(" " * indent, ())] + r for r in art]
    if screen.choices:
        body.append([])
        body += choice_box(screen, caps, w)
    if screen.status:
        body.append([])
        body.append(status_row(screen.status, caps, w, tick))
    for i, line in enumerate(screen.warn):
        if i == 0:
            body.append([])
        mark = [(glyph(caps, "warn") + " ", ("warn", "bold"))] if i == 0 else [("  ", ())]
        body += [mark + [(part, ())] if j == 0 else [("  ", ()), (part, ())] for j, part in enumerate(wrap(line, w - 2))]
    foot = {"choose": "↑↓ move   enter choose   esc back   q quit",
            "wait": "esc back   q quit",
            "busy": "please wait: do not unplug your pedal"}[screen.foot]
    if not caps.unicode:
        foot = foot.replace("↑↓", "up/down")
    foot_style = ("warn",) if screen.foot == "busy" else ("soft",)
    left = max(0, (cols - w) // 2)
    top = 1 if rows >= len(body) + 4 else 0
    frame = [[] for _ in range(rows)]
    for i, r in enumerate(body[:rows - 2]):
        frame[top + i] = [(" " * left, ())] + r if r else []
    frame[rows - 2] = [(" " * left, ()), (foot, foot_style)]
    return frame


def choice_box(screen, caps, w):
    tl, tr, bl, br, h, v = glyph(caps, "box")
    inner = w - 2
    rows = [[(tl + h * inner + tr, ("line",))], [(v, ("line",)), (" " * inner, ()), (v, ("line",))]]
    for i, (_, label) in enumerate(screen.choices):
        num = f"{i + 1}"
        if i == screen.selected:
            text = f" {glyph(caps, 'pick')} {num}  {label}"
            rows.append([(v, ("line",)), (text.ljust(inner), ("on_lamp", "bold")), (v, ("line",))])
        else:
            rows.append([(v, ("line",)), ("   ", ()), (num, ("soft",)), (f"  {label}".ljust(inner - 4), ()),
                         (v, ("line",))])
    rows.append([(v, ("line",)), (" " * inner, ()), (v, ("line",))])
    rows.append([(bl + h * inner + br, ("line",))])
    return rows


def status_row(status, caps, w, tick):
    kind, text, fraction = status
    if kind == "spin":
        frames = glyph(caps, "spin")
        mark = frames[int(tick / 0.08) % len(frames)] if caps.motion else frames[0]
        return [(mark, ("lamp", "bold")), (f"  {text}", ())]
    if kind == "ok":
        return [(glyph(caps, "ok"), ("lamp", "bold")), (f"  {text}", ())]
    size = 24
    done = int(round(size * max(0.0, min(1.0, fraction))))
    pct = f"{int(round(100 * fraction)):3d}%"
    label = f"{text}".ljust(w - size - 6)
    return [(label, ()), (glyph(caps, "bar") * done, ("lamp", "bold")), (glyph(caps, "rest") * (size - done), ("line",)),
            (f"  {pct}", ("soft",))]


def plain(frame):
    return "\n".join("".join(t for t, _ in r).rstrip() for r in frame)


def ansi_row(runs, palette):
    out = []
    for t, s in runs:
        code = palette.sgr(s)
        out.append(f"{code}{t}\x1b[0m" if code else t)
    return "".join(out)


# ---------------------------------------------------------------- keys
UNIX_KEYS = {"\x1b[A": "up", "\x1bOA": "up", "\x1b[B": "down", "\x1bOB": "down", "\x1b[D": "back", "\x1bOD": "back",
             "\r": "enter", "\n": "enter", "\x1b": "back", "\x7f": "back", "q": "quit", "Q": "quit", "b": "back",
             "k": "up", "j": "down", "y": "y", "n": "n", " ": "enter"}
WINDOWS_KEYS = {"H": "up", "P": "down", "K": "back"}


def decode(seq):
    """A key name for the characters one key press sent on macOS or Linux, or None."""
    if seq in UNIX_KEYS:
        return UNIX_KEYS[seq]
    if len(seq) == 1 and seq.isdigit() and seq != "0":
        return seq
    return None


def decode_windows(first, second=None):
    """A key name for what msvcrt.getwch gave: one character, or a prefix (\\x00 or \\xe0) and a scan code."""
    if first in ("\x00", "\xe0"):
        return WINDOWS_KEYS.get(second)
    if first == "\x03":
        raise KeyboardInterrupt
    if first == "\x1b":
        return "back"
    if first == "\x08":
        return "back"
    return decode(first)


class UnixKeys:
    def __init__(self, fd):
        import termios, tty
        self.fd, self.termios = fd, termios
        self.saved = termios.tcgetattr(fd)
        tty.setcbreak(fd)                      # no echo, no line buffering; Ctrl-C still stops the program

    def restore(self):
        self.termios.tcsetattr(self.fd, self.termios.TCSADRAIN, self.saved)

    def _ready(self, timeout):
        return bool(select.select([self.fd], [], [], timeout)[0])

    def raw(self, timeout):
        """What one key press sent (an escape sequence whole), or None after timeout seconds."""
        if not self._ready(timeout):
            return None
        seq = os.read(self.fd, 1).decode("latin-1")
        while seq.startswith("\x1b") and len(seq) < 32 and self._ready(0.03):
            seq += os.read(self.fd, 1).decode("latin-1")
            if seq[1] in "[O" and len(seq) >= 3 and (seq[-1].isalpha() or seq[-1] == "~"):
                break
            if seq.endswith("\x07") or seq.endswith("\x1b\\"):
                break
        return seq

    def read(self, timeout):
        seq = self.raw(timeout)
        return None if seq is None else decode(seq)

    def background(self):
        """The terminal's background as "dark" or "light", from its answer to OSC 11; None when it does not answer."""
        os.write(sys.stdout.fileno(), b"\x1b]11;?\x07")
        answer, end = "", time.monotonic() + 0.2
        while time.monotonic() < end:
            seq = self.raw(max(0.0, end - time.monotonic()))
            if seq is None:
                break
            answer += seq
            if answer.endswith("\x07") or answer.endswith("\x1b\\"):
                break
        return theme_of(answer)


class WindowsKeys:
    def __init__(self):
        import msvcrt
        self.m = msvcrt

    def restore(self):
        pass

    def read(self, timeout):
        end = time.monotonic() + timeout
        while not self.m.kbhit():
            if time.monotonic() >= end:
                return None
            time.sleep(0.01)
        first = self.m.getwch()
        return decode_windows(first, self.m.getwch() if first in ("\x00", "\xe0") else None)

    def background(self):
        return None


def theme_of(answer):
    """ "dark" or "light" from an OSC 11 answer (rgb:RRRR/GGGG/BBBB), or None."""
    m = re.search(r"rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)", answer or "")
    if not m:
        return None
    r, g, b = (int(x, 16) / (16 ** len(x) - 1) for x in m.groups())
    return "light" if 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.5 else "dark"


def theme_from_env(env):
    """COLORFGBG ("15;0": light text on a dark ground) when OSC 11 gave nothing."""
    parts = env.get("COLORFGBG", "").split(";")
    if parts[-1].isdigit():
        return "light" if int(parts[-1]) in (7, 15) else "dark"
    return None


def depth_from_env(env):
    if env.get("COLORTERM") in ("truecolor", "24bit") or env.get("WT_SESSION"):
        return "truecolor"
    return "256" if "256" in env.get("TERM", "") else "16"


# ---------------------------------------------------------------- what the tools' lines mean
REFUSED = "do not unplug: your pedal is being updated"
PHASES = {"looking": "looking for your pedal", "again": "your pedal restarted. waiting for it", "found": "found it",
          "reading": "reading your pedal", "saving": "saving a copy of your pedal", "checking": "checking",
          "writing": "writing", "restarting": "restarting your pedal"}


class Progress:
    """Turns the tool's lines into one plain sentence and, while writing, how far it is."""

    def __init__(self, write):
        self.write, self.phase, self.done, self.total, self.backup = write, "looking", 0, 0, None

    def feed(self, line):
        if line.startswith("waiting for the pedal"):
            self.phase = "again" if self.phase not in ("looking",) else "looking"
        elif line.startswith("the pedal went away"):
            self.phase = "again"
        elif line.startswith("pedal found") or "M-VAVE's recovery mode" in line or line.startswith("leave sent"):
            self.phase = "found"
        elif line.startswith("loader running") or line.startswith("INQUIRY"):
            self.phase = "reading"
        elif line.startswith("flash read"):
            self.phase = "saving"
        elif line.startswith("backup saved: "):
            self.backup, self.phase = line[len("backup saved: "):], "checking"
        elif m := re.match(r"(\d+) of \d+ sectors", line):
            self.total = int(m[1])
            if self.write and self.total:
                self.phase = "writing"
        elif m := re.match(r"\s*written (\d+)/(\d+)", line):
            self.phase, self.done, self.total = "writing", int(m[1]), int(m[2])
        elif line.startswith("run-app sent"):
            self.phase = "restarting"

    @property
    def fraction(self):
        return self.done / self.total if self.total else 0.0

    def sentence(self, caps):
        text = PHASES[self.phase]
        return text if self.phase in ("found", "writing") else text + glyph(caps, "ellipsis")


# ---------------------------------------------------------------- the two ways to show a screen
class Log:
    """The raw lines of every tool run, in a file beside the backups."""

    def __init__(self, folder):
        self.path, self.f = None, None
        self.folder = Path(folder).expanduser()

    def write(self, line):
        if self.f is None:
            ur.make_dir(self.folder)
            self.path = self.folder / f"undertone-{datetime.now():%Y%m%d-%H%M%S}.log"
            self.f = open(self.path, "a", encoding="utf-8")
            ur.hand_back(self.path)
        self.f.write(f"{datetime.now():%H:%M:%S} {line}\n")
        self.f.flush()


def run_in_background(job_fn):
    """job_fn(log, say, stop) in a thread. Returns (thread, stop event, line queue, result box)."""
    stop, lines, box = threading.Event(), queue.Queue(), {}

    def target():
        try:
            box["outcome"] = job_fn(lines.put, lines.put, stop)
        except BaseException as e:            # (handed to the screen's thread)
            box["error"] = e
        finally:
            lines.put(None)
    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t, stop, lines, box


class AnsiView:
    """Full screen in the terminal's alternate buffer. Only the rows that change are written."""

    def __init__(self, out, keys, caps, size=None, clock=time.monotonic):
        self.out, self.keys, self.caps, self.clock = out, keys, caps, clock
        self.palette = Palette(caps.depth, caps.theme)
        self.size = size or (lambda: shutil.get_terminal_size((80, 24)))
        self.shown, self.t0, self.frames = [], clock(), []

    def __enter__(self):
        self.out.write("\x1b[?1049h\x1b[?25l\x1b[2J")
        self.out.flush()
        return self

    def __exit__(self, *exc):
        self.out.write("\x1b[0m\x1b[?25h\x1b[?1049l")
        self.out.flush()
        self.keys.restore()

    def draw(self, screen):
        cols, rows = self.size()
        frame = compose(screen, self.caps, cols, rows, self.clock() - self.t0)
        text = plain(frame)
        if not self.frames or self.frames[-1] != text:   # the screens as plain text, for a transcript; the last few
            self.frames.append(text)
            del self.frames[:-KEEP_FRAMES]
        rendered = [ansi_row(r, self.palette) for r in frame]
        if len(rendered) != len(self.shown):
            self.shown = [None] * len(rendered)
            self.out.write("\x1b[2J")
        started = time.monotonic()
        for i, row in enumerate(rendered):
            if row != self.shown[i]:
                self.out.write(f"\x1b[{i + 1};1H\x1b[2K{row}")
                self.shown[i] = row
        self.out.flush()
        if time.monotonic() - started > 0.2:  # a slow terminal: no more motion
            self.caps.motion = False

    def ask(self, screen):
        """The key of the chosen choice, or "back" or "quit"."""
        sel = screen.selected
        while True:
            self.draw(replace(screen, selected=sel))
            key = self.keys.read(1.0)
            if key == "up":
                sel = (sel - 1) % len(screen.choices)
            elif key == "down":
                sel = (sel + 1) % len(screen.choices)
            elif key and key.isdigit() and int(key) <= len(screen.choices):
                sel = int(key) - 1
            elif key == "enter":
                return screen.choices[sel][0]
            elif key in ("back", "quit"):
                return key

    def work(self, screen, job_fn, log, write=False, hint=()):
        """Runs job_fn while the screen shows what it does. Returns its Outcome; "back" or "quit" while it looks for
        the pedal stops the wait (Outcome code 130)."""
        progress = Progress(write)
        t, stop, lines, box = run_in_background(job_fn)
        started, shown_bar, found_at, done, asked, refused = self.clock(), 0.0, None, False, None, False
        while not done:
            while True:
                try:
                    line = lines.get_nowait()
                except queue.Empty:
                    break
                if line is None:
                    done = True
                    break
                log.write(line)
                was = progress.phase
                progress.feed(line)
                if progress.phase == "found" and was != "found":
                    found_at = self.clock()
                if progress.phase == "writing" and was != "writing":
                    break
            under_way = write and progress.phase != "looking"
            waiting = progress.phase in ("looking", "again") and not under_way
            if progress.phase == "writing":
                target = progress.fraction
                shown_bar += (target - shown_bar) * (0.35 if self.caps.motion else 1.0)
                if abs(target - shown_bar) < 0.002:
                    shown_bar = target
                status = ("bar", progress.sentence(self.caps), shown_bar)
            elif found_at is not None and self.clock() - found_at < 0.8:      # "found it" stays a moment
                status = ("ok", PHASES["found"], 0)
            else:
                status = ("spin", progress.sentence(self.caps), 0)
            warn = (REFUSED,) if refused and under_way else hint if waiting and self.clock() - started > HINT_AFTER else ()
            self.draw(replace(screen, status=status, warn=warn, choices=(),
                              foot="wait" if waiting else "busy"))
            key = self.keys.read(FRAME_S if self.caps.motion else 0.25)
            if key in ("back", "quit"):
                if under_way:
                    refused = True
                elif waiting and not stop.is_set():
                    asked = key
                    stop.set()
        t.join()
        if "error" in box:
            raise box["error"]
        o = box["outcome"]
        if o.code == 130 and asked:
            o.text = asked
        return o


class PlainView:
    """Numbered questions and one line per step, for a pipe, a small or a colourless terminal, or a screen reader."""

    def __init__(self, out, read_line=input, clock=time.monotonic):
        self.out, self.read_line, self.clock = out, read_line, clock
        self.caps = Caps(unicode=False, motion=False)
        self.frames = []

    def line(self, text=""):
        self.out.write(text + "\n")
        self.out.flush()

    def head(self, screen):
        if not self.frames:
            self.line(f"undertone - rescue kit {u.version()}")
        block = [f"-- {'problem: ' if screen.problem else ''}{screen.title}"] + list(screen.lines) + list(screen.aside)
        self.frames.append("\n".join(block))
        self.line()
        for text in block:
            self.line(text)

    def ask(self, screen):
        self.head(screen)
        for i, (_, label) in enumerate(screen.choices):
            self.line(f"  {i + 1}  {label}")
        default = screen.selected
        while True:
            try:
                answer = self.read_line(f"choose 1-{len(screen.choices)} (enter: {default + 1}, b back, q quit): ")
            except EOFError:
                return "quit"
            answer = answer.strip().lower()
            if answer == "":
                return screen.choices[default][0]
            if answer in ("b", "back"):
                return "back"
            if answer in ("q", "quit"):
                return "quit"
            if answer.isdigit() and 1 <= int(answer) <= len(screen.choices):
                return screen.choices[int(answer) - 1][0]

    def work(self, screen, job_fn, log, write=False, hint=()):
        self.head(screen)
        progress = Progress(write)
        t, stop, lines, box = run_in_background(job_fn)
        started, said, hinted, step = self.clock(), None, False, -1
        while True:
            try:
                line = lines.get(timeout=0.25)
            except queue.Empty:
                line = ""
            if line is None:
                break
            if line:
                log.write(line)
                progress.feed(line)
            sentence = progress.sentence(self.caps)
            if progress.phase == "writing":
                tenth = int(progress.fraction * 10)
                if tenth != step:
                    step = tenth
                    self.line(f"writing: {int(progress.fraction * 100)}%")
            elif sentence != said:
                self.line(sentence)
            said = sentence
            if not hinted and progress.phase in ("looking", "again") and self.clock() - started > HINT_AFTER:
                hinted = True
                for h in hint:
                    self.line(h)
        t.join()
        if "error" in box:
            raise box["error"]
        return box["outcome"]


# ---------------------------------------------------------------- the guided flow
RESTART = {"rescue": "rescue_check", "install": "install", "check": "check_work"}   # where a restart under sudo goes
SHORT = {"A": "M-VAVE V20", "B": "M-VAVE V23"}


def nothing_changes():
    return ["First a safe check: undertone saves a copy of your pedal.", "Nothing changes until you say so."]


@dataclass
class Result:
    """What the person is told on the normal screen once the guided screens close."""
    lines: list = field(default_factory=list)
    backup: Path = None
    code: int = 0
    restart: str = None                        # the task to start again at, under sudo


class Guide:
    """The screens, as a small state machine: each state shows one screen and names the next state."""

    def __init__(self, view, opts=None, start="menu", run=None, open_url=None):
        self.view, self.opts = view, opts or Options()
        self.state = RESTART.get(start, "menu")
        self.run_job = run or u.run
        self.open_url = open_url or open_in_browser
        self.log = Log(self.opts.backup_dir)
        self.result = Result()
        self.kind = start if start in RESTART else None
        self.images, self.source, self.outcome, self.need_file = {}, None, None, None
        self.writing = False
        self.trail = []

    def go(self):
        while self.state:
            self.trail.append(self.state)
            self.state = getattr(self, "s_" + self.state)()
        if self.log.path:
            self.log.f.close()
            self.result.lines.append(f"details: {self.log.path}")
        return self.result

    # -- helpers
    def choose(self, screen, routes):
        key = self.view.ask(screen)
        if key == "quit":
            return None
        return routes.get(key)

    def permission(self):
        """The state to show when this process may not reach the pedal, else None."""
        return "need_admin" if u.permission_problem() else None

    def work(self, screen, kind, write=False):
        """One run of a tool behind a screen. Its closing line goes to the log; its backup is kept for the end."""
        job = Job(kind, write, self.images, self.source, self.opts)
        self.writing = write
        o = self.view.work(screen, lambda log, say, stop: self.run_job(job, log, say, stop), self.log, write,
                           self.hint())
        self.writing = False
        self.log.write(o.text)
        if o.backup:
            self.result.backup = o.backup
        return o

    def resume_note(self):
        """What to tell the person when the screens end in the middle of a write."""
        where = self.result.backup or Path(self.opts.backup_dir).expanduser()
        return ["Your pedal was being updated and may not start yet.",
                f"Plug it in and run: undertone {self.kind}  (it continues where it stopped)",
                f"copy of your pedal: {where}"]

    def hint(self):
        return ("Still looking. Plug straight into this computer, no hub.",
                "A pedal that will not start shows up between restarts." if self.kind == "rescue" else
                "Hold all three until its screen says RECOVERY.")

    # -- the states
    def s_menu(self):
        return self.choose(Screen("what would you like to do?", ["Undertone works on your pedal over its USB cable."],
                                  (("rescue", "fix a pedal that will not start"), ("install", "put gamut on my pedal"),
                                   ("check", "check my pedal"))),
                           {"rescue": "rescue", "install": "install", "check": "check", "back": None})

    def s_need_admin(self):
        if ur.WINDOWS:
            return self.choose(Screen("open undertone as administrator", [
                "Press the Windows key, type cmd, right-click Command Prompt,",
                "choose Run as administrator, and start undertone there."], (("done", "done"),), problem=True),
                {"done": None, "back": "menu"})
        key = self.view.ask(Screen("undertone needs your password", [
            "Your computer asks for it once, to reach the pedal.", "Nothing shows while you type."],
            (("go", "continue"), ("back", "back"))))
        if key != "go":
            return "menu" if key == "back" else None
        self.result.restart = self.kind        # main() starts again under sudo, at this task
        return None

    def s_rescue(self):
        self.kind = "rescue"
        return self.choose(Screen("fix a pedal that will not start", nothing_changes(),
                                  (("go", "start the check"), ("back", "back"))),
                           {"go": self.permission() or "rescue_check", "back": "menu"})

    def s_rescue_check(self):
        try:
            self.images = u.official_images()
        except RescueError as e:
            return self.failed(Outcome(1, f"ERROR: {e}"), "rescue")
        o = self.work(Screen("checking your pedal", ["Unplug your pedal, then plug it straight into this computer."]),
                      "rescue")
        self.outcome = o
        if o.code == 130:
            return self.stopped(o, "rescue")
        if o.code == 0 and o.file:
            return "rescue_ready"
        if o.flash is not None and o.code in (0, 2):
            r = u.read_pedal(o.flash)
            need = u.PATH_FILE.get(r.path)
            if need and need not in self.images and not (r.path == "B" and "BlackBox_022.fwsc" in self.images):
                return self.need(r.path)
            if r.path == "C" and not self.images:
                return "ask_path"
            return "cannot"
        return self.failed(o, "rescue_check")

    def s_ask_path(self):
        key = self.view.ask(Screen("did your pedal ever run m-vave v22 or v23?",
                                   ["Undertone could not tell from your pedal."],
                                   (("B", "yes, or not sure"), ("A", "no, never"))))
        if key in ("A", "B"):
            return self.need(key)
        return "rescue" if key == "back" else None

    def need(self, path):
        self.need_file = u.PATH_FILE[path]
        return "need_file"

    def s_need_file(self):
        name = SHORT["A" if self.need_file == u.PATH_FILE["A"] else "B"]
        self.result.lines = [f"Put M-VAVE's {self.need_file} in {u.FIRMWARE}, then run undertone again.",
                             "firmware/README.txt in that folder says where to get it."]
        return self.end(Screen("one more file needed", [f"Your pedal needs {name} software from M-VAVE.",
                                                        "The guide shows where to get it."]))

    def s_cannot(self):
        self.result.lines = ["No official file fits this pedal. Keep the copy and ask for help: "
                             f"{u.GUIDE}#if-it-does-not-work"]
        self.result.code = 2
        return self.end(Screen("this pedal needs a closer look", [
            "Nothing was changed, and a copy of your pedal is saved.", "The guide says how to ask for help."],
            problem=True))

    def s_rescue_ready(self):
        ends = u.ENDS_ON.get(self.outcome.file, "its official firmware")
        return self.choose(Screen("your pedal can be fixed", [f"Undertone puts M-VAVE {ends} back on it."],
                                  (("go", "fix it now"), ("later", "not now"))),
                           {"go": "confirm", "later": "not_now", "back": "rescue"})

    def s_confirm(self):
        key = self.view.ask(Screen("replace the software?", ["This replaces the software on your pedal.",
                                                             "A copy is saved first. Continue?"],
                                   (("no", "no"), ("yes", "yes")), selected=0))
        if key == "yes":
            return "rescue_write" if self.kind == "rescue" else "install_write"
        return "not_now" if key in ("no", "back") else None

    def s_not_now(self):
        self.result.lines = ["Nothing was written to your pedal."]
        return self.end(Screen("nothing was changed", ["Your pedal is as it was. The copy stays saved."]))

    def s_rescue_write(self):
        file = self.outcome.file
        self.images = {file: self.images[file]}
        o = self.work(Screen("fixing your pedal", ["Unplug your pedal, then plug it back in.",
                                                   "Leave the cable alone while undertone works."]), "rescue", True)
        if o.code == 130:
            return self.stopped(o, "rescue_ready")
        if o.code:
            return self.failed(o, "confirm")
        self.result.lines = [o.text, "Next: unplug the cable, switch the pedal off, wait 5 seconds and switch it on."]
        lines = ["Unplug it, then switch it off and on again."]
        if file != u.PATH_FILE["A"]:
            lines.append("To add Gamut later, use undertone, not the installer page.")
            self.result.lines.append("Do not install Gamut on it from an installer page: use undertone install.")
        return self.end(Screen("your pedal is fixed", lines))

    def s_install(self):
        self.kind = "install"
        if ur.WINDOWS:
            return self.choose(Screen("this needs a mac for now", [
                "Putting Gamut on over USB is not ready on Windows.",
                "For a pedal that starts, use the installer page."], (("guide", "open the guide"), ("back", "back"))),
                {"guide": "guide_then_menu", "back": "menu"})
        try:
            self.source = u.gamut_source()
        except GuardError as e:
            return self.failed(Outcome(2, f"REFUSED: {e}"), "install")
        except RescueError:
            return self.choose(Screen("gamut is not in this folder", [
                "This works from the Undertone folder with Gamut built.",
                "For a pedal that starts, use the installer page."], (("guide", "open the guide"), ("back", "back"))),
                {"guide": "guide_then_menu", "back": "menu"})
        return self.choose(Screen("put gamut on your pedal", nothing_changes(),
                                  (("go", "start the check"), ("back", "back"))),
                           {"go": self.permission() or "install_check", "back": "menu"})

    def hold(self, title):
        return Screen(title, ["Switch your pedal off. Hold these three, switch it on,",
                              "and keep holding until its screen says RECOVERY."], pedal=True)

    def s_install_check(self):
        o = self.work(self.hold("hold the three lit buttons"), "install")
        self.outcome = o
        if o.code == 130:
            return self.stopped(o, "install")
        if o.code:
            return self.failed(o, "install_check")
        return self.choose(Screen("ready to put gamut on", ["Your pedal is checked, and a copy is saved."],
                                  (("go", "put gamut on"), ("later", "not now"))),
                           {"go": "confirm", "later": "not_now", "back": "install"})

    def s_install_write(self):
        o = self.work(self.hold("once more: hold the three"), "install", True)
        if o.code == 130:
            return self.stopped(o, "install")
        if o.code:
            return self.failed(o, "confirm")
        self.result.lines = [o.text, ui.FIRST_RUN.format(levels=o.layout.levels)]
        return self.end(Screen("gamut is on your pedal", ["Switch it off and on again to start Gamut."]))

    def s_check(self):
        self.kind = "check"
        return self.choose(Screen("check your pedal", ["Undertone reads your pedal and saves a copy.",
                                                       "Nothing changes."],
                                  (("go", "start the check"), ("back", "back"))),
                           {"go": self.permission() or "check_work", "back": "menu"})

    def s_check_work(self):
        if ur.WINDOWS:
            screen = Screen("checking your pedal", ["Plug your pedal straight into this computer, with no hub."])
        else:
            screen = Screen("connect your pedal", ["Plug it straight into this computer, with no hub.",
                                                   "If it starts, hold these three as you switch it on."], pedal=True)
        o = self.work(screen, "check")
        if o.code == 130:
            return self.stopped(o, "check")
        if o.code:
            return self.failed(o, "check_work")
        r = u.read_pedal(o.flash)
        title = {"A": "your pedal ran m-vave v20 or older", "B": "your pedal ran m-vave v22 or v23"}.get(
            r.path, "undertone does not know this pedal")
        now = ("It now runs Gamut." if r.app and r.app.startswith("an Undertone") else
               "It now runs M-VAVE's own software." if r.app == "M-VAVE's own firmware" else
               "Its software does not start: choose fix a pedal.")
        self.result.lines = [f"head: {r.family}", f"layout: {r.layout or 'not one undertone knows'}",
                             f"app area: {r.app or 'unknown'}"]
        return self.end(Screen(title, [now, "A copy of your pedal is saved."]))

    def stopped(self, o, back):
        """The person left the wait for the pedal: q quits, Esc goes back."""
        return None if o.text == "quit" else back

    def failed(self, o, again):
        """A problem, in plain words; the tool's own line goes to the log and to the normal screen at the end."""
        self.result.code = o.code
        self.result.lines = [o.text]
        text = o.text
        if "libusb not found" in text:
            lines = ["This computer needs one small helper, libusb.", "The guide shows how to add it."]
        elif o.code == 2:
            lines = ["Undertone stopped before changing anything.", "Your pedal is safe."]
        elif "gave up" in text:
            lines = ["Your pedal kept restarting before undertone finished.", "Try again: it continues where it stopped."]
        elif o.code in (3, 5):
            lines = ["Your pedal did not switch over. Nothing was written.", "Try again, holding the three buttons."]
        elif "not found" in text or "CRC" in text or "not a" in text:
            lines = ["A firmware file in the kit is missing or damaged.", "The guide shows where to get it again."]
        else:
            lines = ["Nothing more was sent to your pedal.", "Try again, or open the guide."]
        key = self.view.ask(Screen("something went wrong", lines,
                                   (("again", "try again"), ("guide", "open the guide"), ("done", "done")),
                                   problem=True))
        if key == "again":
            self.result = Result(backup=self.result.backup)
            return again
        if key == "guide":
            self.open_url(u.GUIDE)
        return None

    def end(self, screen):
        screen = replace(screen, finished=not screen.problem,
                         aside=("copy of your pedal:", home_short(self.result.backup)) if self.result.backup else ())
        while True:
            key = self.view.ask(replace(screen, choices=(("done", "done"), ("guide", "open the guide"))))
            if key == "guide":
                self.open_url(u.GUIDE)
                screen = replace(screen, lines=tuple(screen.lines[:1]) + ("The guide is open in your browser.",))
                continue
            return None

    def s_guide_then_menu(self):
        self.open_url(u.GUIDE)
        return "menu"


def home_short(path):
    """A path under the person's home folder as ~/..., as they would type it."""
    try:
        return "~/" + Path(path).relative_to(ur.user_home()).as_posix()
    except ValueError:
        return str(path)


def open_in_browser(url):
    """The guide in the person's browser: as that person, not as root, when undertone runs under sudo."""
    user = os.environ.get("SUDO_USER")
    try:
        if user and not ur.WINDOWS:
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen(["sudo", "-u", user, opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            webbrowser.open(url)
    except OSError:
        pass


# ---------------------------------------------------------------- start
def capabilities(env, stream):
    """Caps for a full-screen view, or None for the plain one."""
    if not stream.isatty() or not sys.stdin.isatty() or env.get("NO_COLOR") or env.get("TERM") == "dumb":
        return None
    cols, rows = shutil.get_terminal_size((0, 0))
    if cols < MIN_COLS or rows < MIN_ROWS:
        return None
    unicode = (not ur.WINDOWS or bool(env.get("WT_SESSION"))) and encodable(stream)
    return Caps(depth_from_env(env), theme_from_env(env), unicode, not env.get("UNDERTONE_NO_MOTION"))


def encodable(stream):
    try:
        "".join(GLYPHS.values()).join(PEDAL).encode(stream.encoding or "ascii")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def enable_windows_ansi():
    """Windows 10 and later: let the console read escape codes. False on an older console."""
    import ctypes
    k = ctypes.windll.kernel32
    h = k.GetStdHandle(-11)
    mode = ctypes.c_uint32()
    if not k.GetConsoleMode(h, ctypes.byref(mode)):
        return False
    return bool(k.SetConsoleMode(h, mode.value | 0x0004))


def main(argv, start="menu"):
    opts = Options()
    caps = capabilities(os.environ, sys.stdout)
    if caps and ur.WINDOWS and not enable_windows_ansi():
        caps = None
    guide = None
    try:
        if caps:
            keys = WindowsKeys() if ur.WINDOWS else UnixKeys(sys.stdin.fileno())
            if not ur.WINDOWS:
                caps.theme = keys.background() or caps.theme
            with AnsiView(sys.stdout, keys, caps) as view:
                guide = Guide(view, opts, start)
                result = guide.go()
        else:
            guide = Guide(PlainView(sys.stdout), opts, start)
            result = guide.go()
    except KeyboardInterrupt:
        print("\nstopped; running undertone again starts over, and a rescue resumes where it stopped")
        if guide and guide.writing:
            print(*guide.resume_note(), sep="\n")
        return 130
    except Exception:
        if guide and guide.writing:
            print(*guide.resume_note(), sep="\n", file=sys.stderr)
        raise
    if result.restart:                         # the password: start again under sudo, at the chosen task
        u.as_root(["--start", result.restart])
    if not result.lines and not result.backup:
        return result.code
    print()
    print(f"undertone {GLYPHS['dot'] if encodable(sys.stdout) else '-'} rescue kit {u.version()}")
    for line in result.lines:
        print(line)
    if result.backup:
        print(f"copy of your pedal: {result.backup}")
    return result.code
