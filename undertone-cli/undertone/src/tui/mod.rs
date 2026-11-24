// SPDX-License-Identifier: GPL-3.0-only
//! undertone's guided screens: what `undertone` shows when it is started with no command (tools/undertone_screens.py).
//! One short question or one action a screen, chosen with the arrow keys or a number and Enter; the pedal drawn when it
//! needs the three buttons held; one calm line of progress while a tool works, its raw lines kept in a log file. Plain
//! numbered questions instead when the output is not a terminal, the terminal is smaller than 62 x 24, NO_COLOR is set
//! or TERM is dumb. Motion (the spinner, the lamp's pulse, the bar's easing) is off when UNDERTONE_NO_MOTION is set.
use std::io::IsTerminal;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use undertone_protocol::{exit, install};

pub mod guide;
pub mod look;
pub mod plain;
pub mod progress;
#[cfg(feature = "sim")]
mod sim;
pub mod term;
#[cfg(test)]
mod tests;

use guide::{Guide, Log, World};
use look::{Caps, Depth, MIN_COLS, MIN_ROWS, Theme};

/// Caps for a full-screen view, or None for the plain one.
pub fn capabilities(get: &dyn Fn(&str) -> Option<String>, terminal: bool, size: Option<(u16, u16)>) -> Option<Caps> {
    if !terminal || get("NO_COLOR").is_some() || get("TERM").as_deref() == Some("dumb") {
        return None;
    }
    let (cols, rows) = size?;
    if cols < MIN_COLS || rows < MIN_ROWS {
        return None;
    }
    let wt = get("WT_SESSION").is_some();
    let depth = if matches!(get("COLORTERM").as_deref(), Some("truecolor" | "24bit")) || wt {
        Depth::TrueColor
    } else if get("TERM").is_some_and(|t| t.contains("256")) {
        Depth::C256
    } else {
        Depth::C16
    };
    Some(Caps {
        depth,
        theme: theme_from_env(get),
        unicode: !cfg!(windows) || wt,
        motion: get("UNDERTONE_NO_MOTION").is_none(),
    })
}

/// COLORFGBG ("15;0": light text on a dark ground) when the terminal did not answer OSC 11.
fn theme_from_env(get: &dyn Fn(&str) -> Option<String>) -> Option<Theme> {
    let v = get("COLORFGBG")?;
    let last: u32 = v.rsplit(';').next()?.parse().ok()?;
    Some(if last == 7 || last == 15 {
        Theme::Light
    } else {
        Theme::Dark
    })
}

/// The guide in the person's browser: as that person, not as root, when undertone runs under sudo.
fn open_in_browser(url: &str) {
    use std::process::{Command, Stdio};
    let quiet = |c: &mut Command| {
        let _ = c.stdout(Stdio::null()).stderr(Stdio::null()).spawn();
    };
    if cfg!(windows) {
        quiet(Command::new("cmd").args(["/c", "start", "", url]));
        return;
    }
    let opener = if cfg!(target_os = "macos") { "open" } else { "xdg-open" };
    match std::env::var("SUDO_USER") {
        Ok(user) if !user.is_empty() => quiet(Command::new("sudo").args(["-u", &user, opener, url])),
        _ => quiet(Command::new(opener).arg(url)),
    }
}

fn world(root: PathBuf, backups: PathBuf, loader: Option<PathBuf>, windows: bool) -> World {
    let layouts = install::layouts();
    let gamut_root = root.clone();
    let gamut_layouts = layouts.clone();
    World {
        bus: Arc::new(Mutex::new(None)),
        open_bus: Arc::new(crate::usb::bus),
        loader: Arc::new(move || crate::kit::loader(loader.as_deref())),
        layouts,
        heads: install::HEADS.to_vec(),
        backups,
        attempts: 10,
        root,
        permission: Box::new(crate::permission_problem),
        gamut: Box::new(move || crate::commands::gamut_source(&gamut_root, None, &gamut_layouts)),
        open_url: Box::new(open_in_browser),
        windows,
    }
}

/// The guided screens, from `start` ("menu", or the task to go on with after a restart under sudo). Returns the exit
/// code.
pub fn main(start: &str) -> i32 {
    let size = ratatui::crossterm::terminal::size().ok();
    let terminal = std::io::stdout().is_terminal() && std::io::stdin().is_terminal();
    let mut caps = capabilities(&|k| std::env::var(k).ok(), terminal, size);
    if let Some(c) = &mut caps
        && !cfg!(windows)
    {
        c.theme = term::background().or(c.theme);
    }
    let backups = crate::kit::default_backups();
    #[cfg(feature = "sim")]
    let w = sim::world().unwrap_or_else(|| world(crate::kit::root(), backups.clone(), None, cfg!(windows)));
    #[cfg(not(feature = "sim"))]
    let w = world(crate::kit::root(), backups.clone(), None, cfg!(windows));
    let kit = crate::kit::version();
    let log = Log::new(Some(w.backups.clone()));
    let (result, interrupted) = match caps.map(|c| term::TermView::new(c, kit)) {
        Some(Ok(mut view)) => {
            let interrupted = view.interrupted.clone();
            let result = Guide::new(&mut view, w, start, log).go();
            drop(view);
            (result, interrupted.load(std::sync::atomic::Ordering::SeqCst))
        }
        _ => {
            let mut view = plain::PlainView::new(Box::new(std::io::stdout()), plain::PlainView::stdin(), kit);
            (Guide::new(&mut view, w, start, log).go(), false)
        }
    };
    if interrupted {
        println!("\nstopped; running undertone again starts over, and a rescue resumes where it stopped");
        return exit::STOPPED;
    }
    if let Some(task) = result.restart {
        crate::restart_as_root(&["--start", task]);
    }
    if result.lines.is_empty() && result.backup.is_none() {
        return result.code;
    }
    let dot = if cfg!(windows) && std::env::var_os("WT_SESSION").is_none() {
        "-"
    } else {
        "·"
    };
    println!();
    println!("undertone {dot} rescue kit {kit}");
    for line in &result.lines {
        println!("{line}");
    }
    if let Some(b) = &result.backup {
        println!("copy of your pedal: {}", b.display());
    }
    result.code
}
