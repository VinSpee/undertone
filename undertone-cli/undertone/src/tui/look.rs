// SPDX-License-Identifier: GPL-3.0-only
//! The look of the guided screens, as tools/undertone_screens.py draws them: one short screen at a time, about 60
//! columns wide and centred; graphite text on the terminal's own ground, the pedal's lime lamp as the one accent (the
//! chosen choice, the lamp, the bar), amber only for "your turn" and for a problem. A screen is composed into rows of
//! (text, style) runs; a palette turns a style into the escape codes of the terminal's colour depth.

/// The width of the screens, and the smallest terminal the full-screen view takes.
pub const WIDTH: usize = 60;
pub const MIN_COLS: u16 = 62;
pub const MIN_ROWS: u16 = 24;

/// A style: tokens of the palette, "bold" among them.
pub type Style = Vec<&'static str>;
/// A row of the screen: runs of text in one style.
pub type Row = Vec<(String, Style)>;

/// What the terminal can show.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Caps {
    pub depth: Depth,
    pub theme: Option<Theme>,
    pub unicode: bool,
    pub motion: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Depth {
    TrueColor,
    C256,
    C16,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Theme {
    Dark,
    Light,
}

pub type Rgb = (u8, u8, u8);
/// The ink on the lime and amber grounds.
pub const INK: Rgb = (11, 11, 10);
const LIME: Rgb = (196, 245, 66);
const AMBER: Rgb = (232, 163, 61);

/// A token's colour in each theme (dark, light, unknown): text is the terminal's own foreground; lime is a ground for
/// ink (15:1) or, as a line, a deeper lime that holds 3:1 on the light ground.
fn token(name: &str) -> Option<[Rgb; 3]> {
    Some(match name {
        "soft" => [(169, 166, 155), (85, 83, 77), (119, 119, 119)],
        "line" => [(85, 83, 77), (201, 198, 187), (128, 125, 117)],
        "lamp" => [LIME, (86, 125, 10), (109, 154, 20)],
        "warn" => [(240, 180, 90), (122, 74, 0), (170, 105, 0)],
        _ => return None,
    })
}

/// A token's colour in a theme, or None for a token that is not a colour.
pub fn token_rgb(name: &str, theme: Option<Theme>) -> Option<Rgb> {
    let i = match theme {
        Some(Theme::Dark) => 0,
        Some(Theme::Light) => 1,
        None => 2,
    };
    token(name).map(|c| c[i])
}

/// The grounds, always with ink on top.
pub fn ground(name: &str) -> Option<Rgb> {
    match name {
        "on_lamp" => Some(LIME),
        "on_warn" => Some(AMBER),
        _ => None,
    }
}

/// The 16-colour codes, as undertone_screens.SIXTEEN gives them (the terminal view uses their colour names).
#[cfg(test)]
fn sixteen(name: &str) -> Option<&'static str> {
    Some(match name {
        "soft" | "line" => "90",
        "lamp" => "32",
        "warn" => "33",
        "on_lamp" => "30;102",
        "on_warn" => "30;43",
        _ => return None,
    })
}

/// The nearest colour of xterm's 256-colour cube.
pub fn cube(rgb: Rgb) -> u8 {
    const STEPS: [i32; 6] = [0, 95, 135, 175, 215, 255];
    let near = |c: u8| (0..6).min_by_key(|&i| (STEPS[i] - c as i32).abs()).unwrap_or(0) as u8;
    16 + 36 * near(rgb.0) + 6 * near(rgb.1) + near(rgb.2)
}

/// The escape codes of undertone_screens.Palette, against which the terminal view's colours are tested.
#[cfg(test)]
pub struct Palette {
    pub depth: Depth,
    pub theme: Option<Theme>,
}

#[cfg(test)]
impl Palette {
    fn rgb(&self, rgb: Rgb, ground: bool) -> String {
        let layer = if ground { 48 } else { 38 };
        match self.depth {
            Depth::TrueColor => format!("{layer};2;{};{};{}", rgb.0, rgb.1, rgb.2),
            _ => format!("{layer};5;{}", cube(rgb)),
        }
    }

    /// The escape for a style.
    pub fn sgr(&self, style: &[&str]) -> String {
        let mut codes = vec![];
        for &t in style {
            if t == "bold" {
                codes.push("1".to_string());
            } else if let (Depth::C16, Some(c)) = (self.depth, sixteen(t)) {
                codes.push(c.to_string());
            } else if let Some(rgb) = token_rgb(t, self.theme) {
                codes.push(self.rgb(rgb, false));
            } else if let Some(g) = ground(t) {
                codes.push(self.rgb(INK, false));
                codes.push(self.rgb(g, true));
            }
        }
        if codes.is_empty() {
            String::new()
        } else {
            format!("\x1b[{}m", codes.join(";"))
        }
    }
}

/// A glyph, with the ASCII a legacy console shows.
pub fn glyph(caps: &Caps, name: &str) -> &'static str {
    let (unicode, ascii) = match name {
        "spin" => ("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", "-\\|/"),
        "ok" => ("●", "*"),
        "warn" => ("◆", "!"),
        "pick" => ("›", ">"),
        "bar" => ("━", "="),
        "rest" => ("─", "-"),
        "lamp" => ("▐▌", "[]"),
        "dot" => ("·", "-"),
        "ellipsis" => ("…", "..."),
        "box" => ("╭╮╰╯─│", "++++-|"),
        _ => ("", ""),
    };
    if caps.unicode { unicode } else { ascii }
}

fn to_ascii(c: char) -> char {
    match c {
        '╭' | '╮' | '╰' | '╯' | '┌' | '┐' | '└' | '┘' => '+',
        '─' => '-',
        '│' => '|',
        '◯' => 'O',
        '◉' => 'o',
        '▣' => '#',
        '▪' => '.',
        other => other,
    }
}

/// The BlackBox from the front (tools/sim/pedal.html): the MASTER knob, the screen and the knob that is pressed for
/// PUSH at the top; the row of seven keys, HOME first; the two footswitches. [P], [H] and [F] are the three controls
/// to hold.
pub const PEDAL: [&str; 9] = [
    "╭──────────────────────────────────────╮",
    "│   ◯            ┌──────────┐   [P]    │",
    "│ master         │ recovery │   push   │",
    "│                └──────────┘          │",
    "│  [H]  ▪   ▪   ▪   ▪   ▪   ▪          │",
    "│  home                                │",
    "│    ◯                        [F]      │",
    "│                          right foot  │",
    "╰──────────────────────────────────────╯",
];
const LABELS: [&str; 3] = ["push", "home", "right foot"];

fn held(c: char) -> char {
    match c {
        'H' => '▣',
        _ => '◉',
    }
}

/// Characters of a string, as Python counts its length.
pub fn width(s: &str) -> usize {
    s.chars().count()
}

/// Python's `str.ljust`.
fn ljust(s: &str, n: usize) -> String {
    format!("{s}{}", " ".repeat(n.saturating_sub(width(s))))
}

pub fn merge(runs: Vec<(String, Style)>) -> Row {
    let mut out: Row = vec![];
    for (t, s) in runs {
        match out.last_mut() {
            Some(last) if last.1 == s => last.0.push_str(&t),
            _ => out.push((t, s)),
        }
    }
    out
}

/// The pedal: its three controls on the lime ground when lit, as lime marks between beats of the pulse; their names in
/// lime; the rest in the line colour.
pub fn pedal_art(caps: &Caps, lit: bool) -> Vec<Row> {
    PEDAL
        .iter()
        .map(|line| {
            let chars: Vec<char> = line.chars().collect();
            let (mut runs, mut i) = (vec![], 0);
            while i < chars.len() {
                if chars[i] == '[' {
                    let g = held(chars[i + 1]);
                    let g = if caps.unicode { g } else { to_ascii(g) };
                    let style = if lit {
                        vec!["on_lamp", "bold"]
                    } else {
                        vec!["lamp", "bold"]
                    };
                    runs.push((format!(" {g} "), style));
                    i += 3;
                    continue;
                }
                let rest: String = chars[i..].iter().collect();
                if let Some(label) = LABELS.iter().find(|w| rest.starts_with(*w)) {
                    runs.push((label.to_string(), vec!["lamp", "bold"]));
                    i += width(label);
                    continue;
                }
                let c = if caps.unicode { chars[i] } else { to_ascii(chars[i]) };
                runs.push((c.to_string(), vec!["line"]));
                i += 1;
            }
            merge(runs)
        })
        .collect()
}

/// Python's greedy word wrap of undertone_screens.
pub fn wrap(text: &str, width_: usize) -> Vec<String> {
    let (mut lines, mut cur) = (vec![], String::new());
    for w in text.split_whitespace() {
        if !cur.is_empty() && width(&cur) + 1 + width(w) > width_ {
            lines.push(std::mem::take(&mut cur));
            cur = w.to_string();
        } else if cur.is_empty() {
            cur = w.to_string();
        } else {
            cur = format!("{cur} {w}");
        }
    }
    if !cur.is_empty() {
        lines.push(cur);
    }
    lines
}

/// What a tool is doing, under the screen's text.
#[derive(Clone, Debug, PartialEq)]
pub enum Status {
    Spin(String),
    Ok(String),
    Bar(String, f64),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Foot {
    Choose,
    Wait,
    Busy,
}

/// One screen: a short title, a few lines, the choices; the pedal when it needs the three buttons held; the status
/// while a tool works.
#[derive(Clone, Debug, PartialEq)]
pub struct Screen {
    pub title: String,
    pub lines: Vec<String>,
    /// (key, label)
    pub choices: Vec<(String, String)>,
    pub selected: usize,
    pub pedal: bool,
    pub status: Option<Status>,
    /// Amber lines under the status: something to fix, or your turn.
    pub warn: Vec<String>,
    /// The title is a problem: an amber mark before it.
    pub problem: bool,
    /// The task is done: the lamp's mark before the title.
    pub finished: bool,
    /// Quiet lines under the text: where the copy of the pedal is.
    pub aside: Vec<String>,
    pub foot: Foot,
}

impl Screen {
    pub fn new(title: &str, lines: &[&str]) -> Screen {
        Screen {
            title: title.into(),
            lines: lines.iter().map(|l| l.to_string()).collect(),
            choices: vec![],
            selected: 0,
            pedal: false,
            status: None,
            warn: vec![],
            problem: false,
            finished: false,
            aside: vec![],
            foot: Foot::Choose,
        }
    }

    pub fn choices(mut self, choices: &[(&str, &str)]) -> Screen {
        self.choices = choices.iter().map(|(k, l)| (k.to_string(), l.to_string())).collect();
        self
    }

    pub fn problem(mut self) -> Screen {
        self.problem = true;
        self
    }

    pub fn pedal(mut self) -> Screen {
        self.pedal = true;
        self
    }
}

fn plain_runs(text: &str) -> (String, Style) {
    (text.to_string(), vec![])
}

/// Python's round(), which rounds half to even.
fn round_half_even(x: f64) -> f64 {
    let r = x.round();
    if (x - x.trunc()).abs() == 0.5 {
        2.0 * (x / 2.0).round()
    } else {
        r
    }
}

/// The whole frame: `rows` rows of (text, style) runs, the screen WIDTH wide and centred.
pub fn compose(screen: &Screen, caps: &Caps, cols: u16, rows: u16, tick: f64, kit: &str) -> Vec<Row> {
    let (cols, rows) = (cols as usize, rows as usize);
    let w = WIDTH.min(cols.saturating_sub(2));
    let mut body: Vec<Row> = vec![];
    let lamp = glyph(caps, "lamp");
    let kit = format!("rescue kit {kit}");
    let gap = w.saturating_sub(width(lamp) + 10 + width(&kit));
    body.push(vec![
        (lamp.into(), vec!["lamp"]),
        (" undertone".into(), vec!["bold"]),
        (" ".repeat(gap), vec![]),
        (kit, vec!["soft"]),
    ]);
    body.push(vec![(glyph(caps, "rest").repeat(w), vec!["line"])]);
    body.push(vec![]);
    let mut title: Row = if screen.problem {
        vec![(format!("{} ", glyph(caps, "warn")), vec!["warn", "bold"])]
    } else if screen.finished {
        vec![(format!("{} ", glyph(caps, "ok")), vec!["lamp", "bold"])]
    } else {
        vec![]
    };
    title.push((screen.title.clone(), vec!["bold"]));
    body.push(title);
    body.push(vec![]);
    for line in &screen.lines {
        body.extend(wrap(line, w).iter().map(|part| vec![plain_runs(part)]));
    }
    for (i, line) in screen.aside.iter().enumerate() {
        if i == 0 {
            body.push(vec![]);
        }
        body.extend(wrap(line, w).into_iter().map(|part| vec![(part, vec!["soft"])]));
    }
    if screen.pedal {
        body.push(vec![]);
        let lit = !caps.motion || (tick / 0.6) as i64 % 2 == 0;
        let indent = (w.saturating_sub(width(PEDAL[0]))) / 2;
        for r in pedal_art(caps, lit) {
            let mut row = vec![(" ".repeat(indent), vec![])];
            row.extend(r);
            body.push(row);
        }
    }
    if !screen.choices.is_empty() {
        body.push(vec![]);
        body.extend(choice_box(screen, caps, w));
    }
    if let Some(status) = &screen.status {
        body.push(vec![]);
        body.push(status_row(status, caps, w, tick));
    }
    for (i, line) in screen.warn.iter().enumerate() {
        if i == 0 {
            body.push(vec![]);
        }
        let mark = if i == 0 {
            (format!("{} ", glyph(caps, "warn")), vec!["warn", "bold"])
        } else {
            ("  ".to_string(), vec![])
        };
        for (j, part) in wrap(line, w.saturating_sub(2)).into_iter().enumerate() {
            body.push(if j == 0 {
                vec![mark.clone(), (part, vec![])]
            } else {
                vec![("  ".into(), vec![]), (part, vec![])]
            });
        }
    }
    let foot = match screen.foot {
        Foot::Choose => "↑↓ move   enter choose   esc back   q quit",
        Foot::Wait => "esc back   q quit",
        Foot::Busy => "please wait: do not unplug your pedal",
    };
    let foot = if caps.unicode {
        foot.to_string()
    } else {
        foot.replace("↑↓", "up/down")
    };
    let foot_style = if screen.foot == Foot::Busy {
        vec!["warn"]
    } else {
        vec!["soft"]
    };
    let left = cols.saturating_sub(w) / 2;
    let top = usize::from(rows >= body.len() + 4);
    let mut frame: Vec<Row> = vec![vec![]; rows];
    for (i, r) in body.into_iter().take(rows.saturating_sub(2)).enumerate() {
        frame[top + i] = if r.is_empty() {
            vec![]
        } else {
            let mut row = vec![(" ".repeat(left), vec![])];
            row.extend(r);
            row
        };
    }
    if rows >= 2 {
        frame[rows - 2] = vec![(" ".repeat(left), vec![]), (foot, foot_style)];
    }
    frame
}

fn choice_box(screen: &Screen, caps: &Caps, w: usize) -> Vec<Row> {
    let b: Vec<char> = glyph(caps, "box").chars().collect();
    let (tl, tr, bl, br, h, v) = (b[0], b[1], b[2], b[3], b[4], b[5]);
    let inner = w - 2;
    let line = |s: String| (s, vec!["line"]);
    let edge = || (v.to_string(), vec!["line"]);
    let mut rows = vec![
        vec![line(format!("{tl}{}{tr}", h.to_string().repeat(inner)))],
        vec![edge(), (" ".repeat(inner), vec![]), edge()],
    ];
    for (i, (_, label)) in screen.choices.iter().enumerate() {
        let num = format!("{}", i + 1);
        if i == screen.selected {
            let text = format!(" {} {num}  {label}", glyph(caps, "pick"));
            rows.push(vec![edge(), (ljust(&text, inner), vec!["on_lamp", "bold"]), edge()]);
        } else {
            rows.push(vec![
                edge(),
                ("   ".into(), vec![]),
                (num, vec!["soft"]),
                (ljust(&format!("  {label}"), inner - 4), vec![]),
                edge(),
            ]);
        }
    }
    rows.push(vec![edge(), (" ".repeat(inner), vec![]), edge()]);
    rows.push(vec![line(format!("{bl}{}{br}", h.to_string().repeat(inner)))]);
    rows
}

fn status_row(status: &Status, caps: &Caps, w: usize, tick: f64) -> Row {
    match status {
        Status::Spin(text) => {
            let frames: Vec<char> = glyph(caps, "spin").chars().collect();
            let mark = if caps.motion {
                frames[(tick / 0.08) as usize % frames.len()]
            } else {
                frames[0]
            };
            vec![(mark.to_string(), vec!["lamp", "bold"]), (format!("  {text}"), vec![])]
        }
        Status::Ok(text) => vec![
            (glyph(caps, "ok").into(), vec!["lamp", "bold"]),
            (format!("  {text}"), vec![]),
        ],
        Status::Bar(text, fraction) => {
            let size = 24usize;
            let done = round_half_even(size as f64 * fraction.clamp(0.0, 1.0)) as usize;
            let pct = format!("{:3}%", round_half_even(100.0 * fraction) as i64);
            vec![
                (ljust(text, w.saturating_sub(size + 6)), vec![]),
                (glyph(caps, "bar").repeat(done), vec!["lamp", "bold"]),
                (glyph(caps, "rest").repeat(size - done), vec!["line"]),
                (format!("  {pct}"), vec!["soft"]),
            ]
        }
    }
}

/// The frame as plain text, each row's trailing spaces cut.
pub fn plain(frame: &[Row]) -> String {
    frame
        .iter()
        .map(|r| {
            r.iter()
                .map(|(t, _)| t.as_str())
                .collect::<String>()
                .trim_end()
                .to_string()
        })
        .collect::<Vec<_>>()
        .join("\n")
}

/// A row with its escape codes.
#[cfg(test)]
pub fn ansi_row(row: &Row, palette: &Palette) -> String {
    row.iter()
        .map(|(t, s)| {
            let code = palette.sgr(s);
            if code.is_empty() {
                t.clone()
            } else {
                format!("{code}{t}\x1b[0m")
            }
        })
        .collect()
}

#[cfg(test)]
pub fn digest(frame: &[Row], palette: &Palette) -> String {
    let runs: Vec<String> = frame
        .iter()
        .map(|r| r.iter().map(|(t, s)| format!("{t}\x1f{}\x1e", s.join(","))).collect())
        .collect();
    let ansi: Vec<String> = frame.iter().map(|r| ansi_row(r, palette)).collect();
    let text = format!("{}\n\n{}", runs.join("\n"), ansi.join("\n"));
    undertone_protocol::uboot::hex(&undertone_protocol::uboot::sha256(text.as_bytes()))
}
