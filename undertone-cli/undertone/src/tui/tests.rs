// SPDX-License-Identifier: GPL-3.0-only
//! The guided screens against tools/undertone_screens.py's own (protocol/tests/fixtures/record.py): every screen of
//! the flows composed in each colour depth, theme and size to the same rows, styles and escape codes; the terminal
//! view's colours the same as those codes; and each flow, driven by the same choices against the same simulated pedal,
//! walking through the same screens, progress and outcomes to the same end.
use std::cell::RefCell;
use std::rc::Rc;
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex};

use ratatui::style::{Color, Modifier};
use serde_json::{Value, json};
use undertone_protocol::crc::crc32;
use undertone_protocol::install::{self, Layout, Source};
use undertone_protocol::sim::{Bench, Start, flash_image, noise, package};
use undertone_protocol::uboot::{FLASH_SIZE, LOADER_SIZE, hex, sha256};
use undertone_protocol::{Bus, Error};

use super::guide::{Guide, Log, View, WorkFn, World};
use super::look::{self, Caps, Depth, Foot, Palette, Screen, Status, Theme};
use super::progress::{Phase, Progress};
use super::term;
use crate::run::Outcome;

fn fixture(name: &str) -> Value {
    let text = match name {
        "frames" => include_str!("../../../protocol/tests/fixtures/frames.json"),
        _ => include_str!("../../../protocol/tests/fixtures/guided.json"),
    };
    serde_json::from_str(text).unwrap()
}

fn strings(v: &Value) -> Vec<String> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|s| s.as_str().unwrap().to_string())
        .collect()
}

fn screen_from(v: &Value) -> Screen {
    let status = v["status"].as_array().map(|s| {
        let text = s[1].as_str().unwrap().to_string();
        match s[0].as_str().unwrap() {
            "spin" => Status::Spin(text),
            "ok" => Status::Ok(text),
            _ => Status::Bar(text, s[2].as_f64().unwrap()),
        }
    });
    Screen {
        title: v["title"].as_str().unwrap().into(),
        lines: strings(&v["lines"]),
        choices: v["choices"]
            .as_array()
            .unwrap()
            .iter()
            .map(|c| (c[0].as_str().unwrap().into(), c[1].as_str().unwrap().into()))
            .collect(),
        selected: v["selected"].as_u64().unwrap() as usize,
        pedal: v["pedal"].as_bool().unwrap(),
        status,
        warn: strings(&v["warn"]),
        problem: v["problem"].as_bool().unwrap(),
        finished: v["finished"].as_bool().unwrap(),
        aside: strings(&v["aside"]),
        foot: match v["foot"].as_str().unwrap() {
            "wait" => Foot::Wait,
            "busy" => Foot::Busy,
            _ => Foot::Choose,
        },
    }
}

fn screen_json(s: &Screen) -> Value {
    let status = s.status.as_ref().map(|st| match st {
        Status::Spin(t) => json!(["spin", t, 0.0]),
        Status::Ok(t) => json!(["ok", t, 0.0]),
        Status::Bar(t, f) => json!(["bar", t, f]),
    });
    let foot = match s.foot {
        Foot::Choose => "choose",
        Foot::Wait => "wait",
        Foot::Busy => "busy",
    };
    json!({
        "title": s.title, "lines": s.lines, "choices": s.choices.iter().map(|(k, l)| json!([k, l])).collect::<Vec<_>>(),
        "selected": s.selected, "pedal": s.pedal, "status": status, "warn": s.warn, "problem": s.problem,
        "finished": s.finished,
        "aside": s.aside.iter().map(|a| if a.contains("blackbox-") { "BACKUP".to_string() } else { a.clone() })
            .collect::<Vec<_>>(),
        "foot": foot,
    })
}

fn caps_from(v: &Value) -> Caps {
    Caps {
        depth: match v[0].as_str().unwrap() {
            "truecolor" => Depth::TrueColor,
            "256" => Depth::C256,
            _ => Depth::C16,
        },
        theme: match v[1].as_str() {
            Some("dark") => Some(Theme::Dark),
            Some("light") => Some(Theme::Light),
            _ => None,
        },
        unicode: v[2].as_bool().unwrap(),
        motion: v[3].as_bool().unwrap(),
    }
}

#[test]
fn every_screen_is_composed_as_python_composes_it() {
    for (i, f) in fixture("frames").as_array().unwrap().iter().enumerate() {
        let screen = screen_from(&f["screen"]);
        let caps = caps_from(&f["caps"]);
        let (cols, rows) = (
            f["size"][0].as_u64().unwrap() as u16,
            f["size"][1].as_u64().unwrap() as u16,
        );
        let frame = look::compose(&screen, &caps, cols, rows, f["tick"].as_f64().unwrap(), "7");
        let plain: Vec<String> = look::plain(&frame).split('\n').map(String::from).collect();
        assert_eq!(plain, strings(&f["plain"]), "frame {i}: {}", screen.title);
        let palette = Palette {
            depth: caps.depth,
            theme: caps.theme,
        };
        assert_eq!(
            look::digest(&frame, &palette),
            f["digest"].as_str().unwrap(),
            "frame {i}: {}",
            screen.title
        );
    }
}

/// The SGR codes a ratatui colour stands for, foreground or background.
fn codes(c: Color, ground: bool) -> String {
    let layer = if ground { 48 } else { 38 };
    match c {
        Color::Rgb(r, g, b) => format!("{layer};2;{r};{g};{b}"),
        Color::Indexed(n) => format!("{layer};5;{n}"),
        Color::DarkGray => "90".into(),
        Color::Green => "32".into(),
        Color::Yellow if ground => "43".into(),
        Color::Yellow => "33".into(),
        Color::Black => "30".into(),
        Color::LightGreen if ground => "102".into(),
        other => format!("{other:?}"),
    }
}

#[test]
fn the_terminal_view_gives_each_style_the_palettes_colours() {
    let styles: [&[&str]; 9] = [
        &["soft"],
        &["line"],
        &["lamp"],
        &["lamp", "bold"],
        &["warn"],
        &["warn", "bold"],
        &["on_lamp", "bold"],
        &["on_warn"],
        &["bold"],
    ];
    for depth in [Depth::TrueColor, Depth::C256, Depth::C16] {
        for theme in [Some(Theme::Dark), Some(Theme::Light), None] {
            let caps = Caps {
                depth,
                theme,
                unicode: true,
                motion: false,
            };
            let palette = Palette { depth, theme };
            for tokens in styles {
                let s = term::style(&caps, tokens);
                let mut got = vec![];
                if s.add_modifier.contains(Modifier::BOLD) {
                    got.push("1".to_string());
                }
                got.extend(s.fg.map(|c| codes(c, false)));
                got.extend(s.bg.map(|c| codes(c, true)));
                let want = palette.sgr(tokens);
                let want = want.trim_start_matches("\x1b[").trim_end_matches('m');
                let mut want: Vec<String> = want.split(';').map(String::from).collect();
                // the 16-colour grounds are one code pair in Python's table ("30;102"); compare code by code
                want.sort();
                let mut got: Vec<String> = got.join(";").split(';').map(String::from).collect();
                got.sort();
                assert_eq!(got, want, "{depth:?} {theme:?} {tokens:?}");
            }
        }
    }
}

#[test]
fn an_osc_11_answer_names_the_theme() {
    assert_eq!(term::theme_of("\x1b]11;rgb:ffff/ffff/ffff\x07"), Some(Theme::Light));
    assert_eq!(term::theme_of("\x1b]11;rgb:1414/1414/1313\x1b\\"), Some(Theme::Dark));
    assert_eq!(term::theme_of("\x1b[12;1R"), None);
}

/// Answers each question with the next scripted choice and runs each tool at once, keeping what it saw.
struct Recording {
    keys: Vec<String>,
    seen: Rc<RefCell<Vec<Value>>>,
}

impl View for Recording {
    fn ask(&mut self, screen: &Screen) -> String {
        let key = self.keys.remove(0);
        self.seen
            .borrow_mut()
            .push(json!({"ask": screen_json(screen), "key": key}));
        key
    }

    fn work(&mut self, screen: &Screen, job: WorkFn, _log: &mut Log, write: bool, hint: &[String]) -> Outcome {
        let mut progress = Progress::new(write);
        let mut phases: Vec<&str> = vec![];
        let o = job(
            &mut |line| {
                progress.feed(line);
                if phases.last() != Some(&progress.phase.name()) {
                    phases.push(progress.phase.name());
                }
            },
            Arc::new(AtomicBool::new(false)),
        );
        let text = shown(&o.text);
        self.seen.borrow_mut().push(json!({
            "work": screen_json(screen), "write": write, "hint": hint, "phases": phases, "code": o.code, "text": text,
        }));
        o
    }
}

/// A line without what differs from run to run: the backup's path.
fn shown(text: &str) -> String {
    text.split(' ')
        .map(|w| {
            if w.contains("blackbox-") && w.ends_with(".dump.bin") {
                "BACKUP"
            } else {
                w
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

fn layouts() -> Vec<Layout> {
    let (old, new) = (
        flash_image(0x4000, &noise(20, 0x8000), 0x9F000),
        flash_image(0x6000, &noise(23, 0x8000), 0x9F000),
    );
    let mut l = install::layouts();
    l[0].boot_crc = crc32(&old[..0x4000], 0);
    l[1].boot_crc = crc32(&new[..0x6000], 0);
    l
}

struct Flow {
    flash: Vec<u8>,
    starts: Vec<Start>,
    keys: &'static [&'static str],
    drops: Vec<usize>,
    attempts: u32,
    password: bool,
}

fn guided(name: &str, flow: Flow) {
    let want = &fixture("guided")[name];
    let root = std::env::temp_dir().join(format!("undertone-guided-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&root);
    let firmware = root.join("firmware");
    std::fs::create_dir_all(&firmware).unwrap();
    let ota = b"OTA".repeat(100);
    let v23 = flash_image(0x6000, &noise(23, 0x8000), 0x9F000);
    std::fs::write(
        firmware.join("BlackBox_020.fwsc"),
        package(&flash_image(0x4000, &noise(10, 0x8000), 0xA5000), &ota, "BlackBox_020"),
    )
    .unwrap();
    std::fs::write(firmware.join("BlackBox_023.fwsc"), package(&v23, &ota, "BlackBox_023")).unwrap();

    let bench = Bench::new(flow.flash, noise(1, LOADER_SIZE), &flow.starts).drops(&flow.drops);
    let pedal = bench.uboot.clone();
    let bus: Box<dyn Bus + Send> = Box::new(bench);
    let opened = Rc::new(RefCell::new(vec![]));
    let opened_in = opened.clone();
    let gamut = Source {
        what: "Gamut's app area of the test".into(),
        area: v23[0x6000..0x9F000].to_vec(),
        boot: None,
    };
    let w = World {
        bus: Arc::new(Mutex::new(Some(bus))),
        open_bus: Arc::new(|| Err(Error::Setup("the bench is the bus".into()))),
        loader: Arc::new(|| Ok(noise(1, LOADER_SIZE))),
        layouts: layouts(),
        heads: install::HEADS.to_vec(),
        backups: root.join("backups"),
        attempts: flow.attempts,
        root: root.clone(),
        permission: if flow.password {
            Box::new(|| Some("needs root"))
        } else {
            Box::new(|| None)
        },
        gamut: Box::new(move || Ok(gamut.clone())),
        open_url: Box::new(move |url| opened_in.borrow_mut().push(url.to_string())),
        windows: false,
    };
    let seen = Rc::new(RefCell::new(vec![]));
    let mut view = Recording {
        keys: flow.keys.iter().map(|k| k.to_string()).collect(),
        seen: seen.clone(),
    };
    let result = Guide::new(&mut view, w, "menu", Log::new(None)).go();
    let got = json!({
        "screens": *seen.borrow(), "opened": *opened.borrow(), "code": result.code, "restart": result.restart,
        "lines": result.lines.iter().map(|l| shown(l)).collect::<Vec<_>>(), "backup": result.backup.is_some(),
        "flash": hex(&sha256(&pedal.lock().flash)),
    });
    for (i, (g, w)) in got["screens"]
        .as_array()
        .unwrap()
        .iter()
        .zip(want["screens"].as_array().unwrap())
        .enumerate()
    {
        assert_eq!(g, w, "{name}: step {i}");
    }
    assert_eq!(got, *want, "{name}");
    let _ = std::fs::remove_dir_all(&root);
}

fn dark() -> Vec<u8> {
    let v23 = flash_image(0x6000, &noise(23, 0x8000), 0x9F000);
    let mut flash = noise(20, FLASH_SIZE);
    flash[..v23.len()].copy_from_slice(&v23);
    flash[0x4000..0xA3000].copy_from_slice(&noise(21, 0xA3000 - 0x4000));
    flash
}

fn on_v23() -> Vec<u8> {
    let mut flash = flash_image(0x6000, &noise(24, 0x8000), 0x9F000);
    flash.extend(noise(99, FLASH_SIZE - flash.len()));
    flash
}

fn flow(flash: Vec<u8>, starts: &[Start], keys: &'static [&'static str]) -> Flow {
    Flow {
        flash,
        starts: starts.to_vec(),
        keys,
        drops: vec![],
        attempts: 10,
        password: false,
    }
}

use Start::{Recovery as R, Uboot as U};

#[test]
fn the_guided_rescue_walks_the_python_screens() {
    guided("rescue", flow(dark(), &[U, U], &["rescue", "go", "go", "yes", "done"]));
    guided("rescue-not-now", flow(dark(), &[U], &["rescue", "go", "later", "done"]));
    guided(
        "rescue-cannot",
        flow(noise(22, FLASH_SIZE), &[U], &["rescue", "go", "guide", "done"]),
    );
}

#[test]
fn a_failed_write_needs_a_new_yes() {
    let keys = &["rescue", "go", "go", "yes", "again", "no", "done"];
    guided(
        "rescue-fails-then-no",
        Flow {
            drops: vec![100_000, 100],
            attempts: 1,
            ..flow(dark(), &[U, U], keys)
        },
    );
}

#[test]
fn the_guided_install_and_check_walk_the_python_screens() {
    guided(
        "install",
        flow(on_v23(), &[R, R], &["install", "go", "go", "yes", "done"]),
    );
    guided("check", flow(on_v23(), &[R], &["check", "go", "done"]));
    guided(
        "password",
        Flow {
            password: true,
            ..flow(on_v23(), &[], &["check", "go", "go"])
        },
    );
    guided(
        "back-and-quit",
        flow(on_v23(), &[], &["install", "back", "check", "back", "quit"]),
    );
}

#[test]
fn progress_reads_the_tools_lines_as_python_does() {
    let mut p = Progress::new(true);
    for line in [
        "waiting for the pedal",
        "pedal found",
        "INQUIRY: WL82",
        "flash read: 1024 KiB",
        "backup saved: x",
    ] {
        p.feed(line);
    }
    assert_eq!(p.phase, Phase::Checking);
    p.feed("12 of 155 sectors in [0x4000, 0x9f000) differ");
    assert_eq!((p.phase, p.total), (Phase::Writing, 12));
    p.feed("  written 3/12");
    assert_eq!((p.done, p.fraction()), (3, 0.25));
    p.feed("the pedal went away or stopped answering (gone); waiting for it again (1/10)");
    assert_eq!(p.phase, Phase::Again);
}
