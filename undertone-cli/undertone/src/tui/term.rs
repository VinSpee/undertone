// SPDX-License-Identifier: GPL-3.0-only
//! The full-screen view in the terminal's alternate screen (undertone_screens.AnsiView), drawn with ratatui over
//! crossterm: each frame composed by `look`, its styles given the colours of the terminal's depth and theme. Keys come
//! as crossterm events: arrows or j/k move, a number picks, Enter chooses, Esc goes back, q quits.
use std::io::Stdout;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, mpsc};
use std::time::{Duration, Instant};

use ratatui::Terminal;
use ratatui::backend::CrosstermBackend;
use ratatui::crossterm::event::{self, Event, KeyCode, KeyEventKind, KeyModifiers};
use ratatui::crossterm::{cursor, execute, terminal};
use ratatui::style::{Color, Modifier, Style as Look};
use ratatui::text::{Line, Span};

use super::guide::{Log, View, WorkFn};
use super::look::{self, Caps, Depth, Foot, Row, Screen, Status, Theme, cube};
use super::progress::{Phase, Progress, REFUSED};
use crate::run::Outcome;

pub const HINT_AFTER: f64 = 30.0;
const FRAME_S: f64 = 0.05;

/// A key, by name: "up", "down", "enter", "back", "quit", "interrupt" or a digit.
fn key(timeout: Duration) -> Option<String> {
    if !event::poll(timeout).ok()? {
        return None;
    }
    let Event::Key(k) = event::read().ok()? else {
        return None;
    };
    if k.kind == KeyEventKind::Release {
        return None;
    }
    if k.modifiers.contains(KeyModifiers::CONTROL) && k.code == KeyCode::Char('c') {
        return Some("interrupt".into());
    }
    Some(
        match k.code {
            KeyCode::Up | KeyCode::Char('k') => "up",
            KeyCode::Down | KeyCode::Char('j') => "down",
            KeyCode::Enter | KeyCode::Char(' ') => "enter",
            KeyCode::Esc | KeyCode::Left | KeyCode::Backspace | KeyCode::Char('b') => "back",
            KeyCode::Char('q' | 'Q') => "quit",
            KeyCode::Char(c @ '1'..='9') => return Some(c.to_string()),
            _ => return None,
        }
        .into(),
    )
}

/// The colour of a token in this terminal.
fn colour(caps: &Caps, rgb: (u8, u8, u8)) -> Color {
    match caps.depth {
        Depth::TrueColor => Color::Rgb(rgb.0, rgb.1, rgb.2),
        _ => Color::Indexed(cube(rgb)),
    }
}

/// A style of the palette as ratatui's: the same escape codes `look::Palette::sgr` gives.
pub fn style(caps: &Caps, tokens: &[&str]) -> Look {
    let mut s = Look::default();
    for &t in tokens {
        s = match (t, caps.depth) {
            ("bold", _) => s.add_modifier(Modifier::BOLD),
            ("soft" | "line", Depth::C16) => s.fg(Color::DarkGray),
            ("lamp", Depth::C16) => s.fg(Color::Green),
            ("warn", Depth::C16) => s.fg(Color::Yellow),
            ("on_lamp", Depth::C16) => s.fg(Color::Black).bg(Color::LightGreen),
            ("on_warn", Depth::C16) => s.fg(Color::Black).bg(Color::Yellow),
            (t, _) => match (look::token_rgb(t, caps.theme), look::ground(t)) {
                (Some(rgb), _) => s.fg(colour(caps, rgb)),
                (_, Some(rgb)) => s.fg(colour(caps, look::INK)).bg(colour(caps, rgb)),
                _ => s,
            },
        };
    }
    s
}

fn line<'a>(caps: &Caps, row: &'a Row) -> Line<'a> {
    Line::from(
        row.iter()
            .map(|(t, s)| Span::styled(t.as_str(), style(caps, s)))
            .collect::<Vec<_>>(),
    )
}

pub struct TermView {
    terminal: Terminal<CrosstermBackend<Stdout>>,
    pub caps: Caps,
    kit: &'static str,
    t0: Instant,
    /// Ctrl-C was pressed: the guide ends, and the program says how to go on.
    pub interrupted: Arc<AtomicBool>,
    /// What to tell the person if a second Ctrl-C ends the program during a write.
    note: Vec<String>,
    /// The plain text of each frame shown, for a transcript.
    pub frames: Vec<String>,
}

impl TermView {
    pub fn new(caps: Caps, kit: &'static str) -> std::io::Result<TermView> {
        terminal::enable_raw_mode()?;
        execute!(std::io::stdout(), terminal::EnterAlternateScreen, cursor::Hide)?;
        let terminal = Terminal::new(CrosstermBackend::new(std::io::stdout()))?;
        Ok(TermView {
            terminal,
            caps,
            kit,
            t0: Instant::now(),
            interrupted: Arc::new(AtomicBool::new(false)),
            note: vec![],
            frames: vec![],
        })
    }

    fn draw(&mut self, screen: &Screen) {
        let tick = self.t0.elapsed().as_secs_f64();
        let (caps, kit) = (self.caps, self.kit);
        let started = Instant::now();
        let mut text = None;
        let _ = self.terminal.draw(|f| {
            let area = f.area();
            let frame = look::compose(screen, &caps, area.width, area.height, tick, kit);
            text = Some(look::plain(&frame));
            for (y, row) in frame.iter().enumerate().take(area.height as usize) {
                f.buffer_mut().set_line(0, y as u16, &line(&caps, row), area.width);
            }
        });
        if let Some(t) = text
            && self.frames.last() != Some(&t)
        {
            self.frames.push(t);
            let keep = self.frames.len().saturating_sub(400);
            self.frames.drain(..keep);
        }
        if started.elapsed() > Duration::from_millis(200) {
            self.caps.motion = false; // a slow terminal: no more motion
        }
    }

    pub fn restore() {
        let _ = execute!(std::io::stdout(), cursor::Show, terminal::LeaveAlternateScreen);
        let _ = terminal::disable_raw_mode();
    }
}

impl Drop for TermView {
    fn drop(&mut self) {
        Self::restore();
    }
}

impl View for TermView {
    fn resume_note(&mut self, note: Vec<String>) {
        self.note = note;
    }

    fn ask(&mut self, screen: &Screen) -> String {
        let mut sel = screen.selected;
        let n = screen.choices.len();
        loop {
            let shown = Screen {
                selected: sel,
                ..screen.clone()
            };
            self.draw(&shown);
            match key(Duration::from_secs(1)).as_deref() {
                Some("up") => sel = (sel + n - 1) % n,
                Some("down") => sel = (sel + 1) % n,
                Some(d) if d.parse::<usize>().is_ok_and(|d| (1..=n).contains(&d)) => {
                    sel = d.parse::<usize>().unwrap() - 1
                }
                Some("enter") => return screen.choices[sel].0.clone(),
                Some(k @ ("back" | "quit")) => return k.to_string(),
                Some("interrupt") => {
                    self.interrupted.store(true, Ordering::SeqCst);
                    return "quit".into();
                }
                _ => {}
            }
        }
    }

    fn work(&mut self, screen: &Screen, job: WorkFn, log: &mut Log, write: bool, hint: &[String]) -> Outcome {
        let mut progress = Progress::new(write);
        let stop = Arc::new(AtomicBool::new(false));
        let (tx, rx) = mpsc::channel::<String>();
        let worker = {
            let stop = stop.clone();
            std::thread::spawn(move || job(&mut |m| drop(tx.send(m.to_string())), stop))
        };
        let started = Instant::now();
        let (mut shown_bar, mut found_at, mut asked, mut refused) = (0.0f64, None::<Instant>, None::<String>, false);
        let mut interrupts = 0;
        loop {
            let mut done = false;
            loop {
                match rx.try_recv() {
                    Ok(line) => {
                        log.write(&line);
                        let was = progress.phase;
                        progress.feed(&line);
                        if progress.phase == Phase::Found && was != Phase::Found {
                            found_at = Some(Instant::now());
                        }
                        if progress.phase == Phase::Writing && was != Phase::Writing {
                            break;
                        }
                    }
                    Err(mpsc::TryRecvError::Empty) => break,
                    Err(mpsc::TryRecvError::Disconnected) => {
                        done = true;
                        break;
                    }
                }
            }
            if done {
                break;
            }
            let under_way = write && progress.phase != Phase::Looking;
            let waiting = matches!(progress.phase, Phase::Looking | Phase::Again) && !under_way;
            let status = if progress.phase == Phase::Writing {
                let target = progress.fraction();
                shown_bar += (target - shown_bar) * if self.caps.motion { 0.35 } else { 1.0 };
                if (target - shown_bar).abs() < 0.002 {
                    shown_bar = target;
                }
                Status::Bar(progress.sentence(&self.caps), shown_bar)
            } else if found_at.is_some_and(|t| t.elapsed() < Duration::from_millis(800)) {
                Status::Ok(Phase::Found.words().into()) // "found it" stays a moment
            } else {
                Status::Spin(progress.sentence(&self.caps))
            };
            let warn = if refused && under_way {
                vec![REFUSED.to_string()]
            } else if waiting && started.elapsed().as_secs_f64() > HINT_AFTER {
                hint.to_vec()
            } else {
                vec![]
            };
            let foot = if waiting { Foot::Wait } else { Foot::Busy };
            self.draw(&Screen {
                status: Some(status),
                warn,
                choices: vec![],
                foot,
                ..screen.clone()
            });
            let wait = Duration::from_secs_f64(if self.caps.motion { FRAME_S } else { 0.25 });
            if let Some(k @ ("back" | "quit" | "interrupt")) = key(wait).as_deref() {
                if under_way {
                    refused = true;
                    if k == "interrupt" {
                        interrupts += 1;
                        if interrupts >= 2 {
                            // a second Ctrl-C during the write: the program ends, as Python's does, and says how
                            // the next run resumes
                            Self::restore();
                            println!(
                                "\nstopped; running undertone again starts over, and a rescue resumes where it stopped"
                            );
                            for l in &self.note {
                                println!("{l}");
                            }
                            std::process::exit(undertone_protocol::exit::STOPPED);
                        }
                    }
                } else if waiting && !stop.load(Ordering::SeqCst) {
                    if k == "interrupt" {
                        self.interrupted.store(true, Ordering::SeqCst);
                    }
                    asked = Some(if k == "back" { "back".into() } else { "quit".into() });
                    stop.store(true, Ordering::SeqCst);
                }
            }
        }
        let mut o = worker
            .join()
            .unwrap_or_else(|_| Outcome::failed(&undertone_protocol::Error::Setup("the tool stopped".into())));
        if o.code == 130
            && let Some(k) = asked
        {
            o.text = k;
        }
        o
    }
}

/// Is the terminal's background light? From its answer to OSC 11, asked with a cursor position request after it,
/// which every terminal answers, so that the answer is read whole and nothing is left for the keys. None when it does
/// not say (Windows' console, or a terminal without OSC 11).
#[cfg(not(windows))]
pub fn background() -> Option<Theme> {
    use std::io::{Read, Write};
    terminal::enable_raw_mode().ok()?;
    let mut out = std::io::stdout();
    let _ = out.write_all(b"\x1b]11;?\x07\x1b[6n");
    let _ = out.flush();
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let (mut answer, mut byte) = (Vec::new(), [0u8; 1]);
        let mut stdin = std::io::stdin();
        while stdin.read(&mut byte).is_ok_and(|n| n == 1) {
            answer.push(byte[0]);
            // the cursor position report ends the answer: ESC [ row ; col R
            if byte[0] == b'R'
                && answer
                    .iter()
                    .rposition(|&b| b == 0x1b)
                    .is_some_and(|i| answer.get(i + 1) == Some(&b'['))
            {
                break;
            }
        }
        let _ = tx.send(answer);
    });
    let answer = rx.recv_timeout(Duration::from_millis(500)).ok();
    let _ = terminal::disable_raw_mode();
    theme_of(&String::from_utf8_lossy(&answer?))
}

#[cfg(windows)]
pub fn background() -> Option<Theme> {
    None
}

/// "dark" or "light" from an OSC 11 answer (rgb:RRRR/GGGG/BBBB), or None.
#[cfg_attr(windows, allow(dead_code))]
pub fn theme_of(answer: &str) -> Option<Theme> {
    let rest = &answer[answer.find("rgb:")? + 4..];
    let parts: Vec<&str> = rest.splitn(3, '/').collect();
    if parts.len() != 3 {
        return None;
    }
    let channel = |s: &str| {
        let hex: String = s.chars().take_while(char::is_ascii_hexdigit).collect();
        let v = u64::from_str_radix(&hex, 16).ok()?;
        Some(v as f64 / (16f64.powi(hex.len() as i32) - 1.0))
    };
    let (r, g, b) = (channel(parts[0])?, channel(parts[1])?, channel(parts[2])?);
    Some(if 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.5 {
        Theme::Light
    } else {
        Theme::Dark
    })
}
