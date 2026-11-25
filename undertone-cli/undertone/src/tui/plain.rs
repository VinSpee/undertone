// SPDX-License-Identifier: GPL-3.0-only
//! Numbered questions and one line per step, for a pipe, a small or a colourless terminal, or a screen reader
//! (undertone_screens.PlainView).
use std::io::{BufRead, Write};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, mpsc};
use std::time::{Duration, Instant};

use undertone_protocol::exit;

use super::guide::{Log, View, WorkFn};
use super::look::{Caps, Depth, Screen};
use super::progress::{Phase, Progress, REFUSED, say_stopped};
use super::term::HINT_AFTER;
use crate::run::Outcome;

/// Reads one line the person typed after a prompt; None at the end of input.
pub type ReadLine = Box<dyn FnMut(&str) -> Option<String>>;

pub struct PlainView {
    out: Box<dyn Write>,
    read_line: ReadLine,
    kit: &'static str,
    caps: Caps,
    pub frames: Vec<String>,
    /// What to tell the person if a second Ctrl-C ends the program during a write.
    note: Vec<String>,
    /// Ctrl-C presses during the write under way, counted by the handler while `writing`.
    pub(super) presses: Arc<AtomicUsize>,
    pub(super) writing: Arc<AtomicBool>,
    /// Whether the Ctrl-C handler is installed: it is, at the first write, and not before.
    pub(super) caught: bool,
    /// How the program ends; a test's ends the view's thread instead.
    pub(super) end: fn(i32) -> !,
}

/// One Ctrl-C: during a write it is counted, for the view to answer as the full-screen view does; at any other time it
/// ends the program as the default does.
pub(super) fn press(writing: &AtomicBool, presses: &AtomicUsize, end: fn(i32) -> !) {
    if writing.load(Ordering::SeqCst) {
        presses.fetch_add(1, Ordering::SeqCst);
    } else {
        end(exit::STOPPED)
    }
}

impl PlainView {
    pub fn new(out: Box<dyn Write>, read_line: ReadLine, kit: &'static str) -> PlainView {
        let caps = Caps {
            depth: Depth::C16,
            theme: None,
            unicode: false,
            motion: false,
        };
        PlainView {
            out,
            read_line,
            kit,
            caps,
            frames: vec![],
            note: vec![],
            presses: Arc::new(AtomicUsize::new(0)),
            writing: Arc::new(AtomicBool::new(false)),
            caught: false,
            end: std::process::exit,
        }
    }

    /// Ctrl-C is the default (the program ends) until the first write: from then on `press` answers it.
    fn catch_interrupts(&mut self) {
        if std::mem::replace(&mut self.caught, true) {
            return;
        }
        let (writing, presses, end) = (self.writing.clone(), self.presses.clone(), self.end);
        // if it cannot be set, the default stays
        let _ = ctrlc::set_handler(move || press(&writing, &presses, end));
    }

    pub fn stdin() -> ReadLine {
        Box::new(|prompt| {
            print!("{prompt}");
            let _ = std::io::stdout().flush();
            let mut line = String::new();
            match std::io::stdin().lock().read_line(&mut line) {
                Ok(0) | Err(_) => None,
                Ok(_) => Some(line),
            }
        })
    }

    fn line(&mut self, text: &str) {
        let _ = writeln!(self.out, "{text}");
        let _ = self.out.flush();
    }

    fn head(&mut self, screen: &Screen) {
        if self.frames.is_empty() {
            let kit = self.kit;
            self.line(&format!("undertone - rescue kit {kit}"));
        }
        let mut block = vec![format!(
            "-- {}{}",
            if screen.problem { "problem: " } else { "" },
            screen.title
        )];
        block.extend(screen.lines.iter().cloned());
        block.extend(screen.aside.iter().cloned());
        self.frames.push(block.join("\n"));
        self.line("");
        for text in block {
            self.line(&text);
        }
    }
}

impl View for PlainView {
    fn resume_note(&mut self, note: Vec<String>) {
        self.note = note;
    }

    fn ask(&mut self, screen: &Screen) -> String {
        self.head(screen);
        for (i, (_, label)) in screen.choices.iter().enumerate() {
            self.line(&format!("  {}  {label}", i + 1));
        }
        let (n, default) = (screen.choices.len(), screen.selected);
        loop {
            let Some(answer) = (self.read_line)(&format!(
                "type a number, then press enter (enter alone: {}, b: back, q: quit): ",
                default + 1
            )) else {
                return "quit".into();
            };
            let answer = answer.trim().to_lowercase();
            match answer.as_str() {
                "" => return screen.choices[default].0.clone(),
                "b" | "back" => return "back".into(),
                "q" | "quit" => return "quit".into(),
                a => {
                    if let Ok(i) = a.parse::<usize>()
                        && (1..=n).contains(&i)
                    {
                        return screen.choices[i - 1].0.clone();
                    }
                }
            }
        }
    }

    fn work(&mut self, screen: &Screen, job: WorkFn, log: &mut Log, write: bool, hint: &[String]) -> Outcome {
        self.head(screen);
        if write {
            self.catch_interrupts();
        }
        self.presses.store(0, Ordering::SeqCst);
        let mut progress = Progress::new(write);
        let (tx, rx) = mpsc::channel::<String>();
        let stop = Arc::new(AtomicBool::new(false));
        let worker = std::thread::spawn(move || job(&mut |m| drop(tx.send(m.to_string())), stop));
        let (started, mut said, mut hinted, mut step) = (Instant::now(), None::<String>, false, None::<usize>);
        let mut refused = false;
        loop {
            match rx.recv_timeout(Duration::from_millis(250)) {
                Ok(line) => {
                    log.write(&line);
                    progress.feed(&line);
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {}
                Err(mpsc::RecvTimeoutError::Disconnected) => break,
            }
            // from the pedal's being found a write is under way: the first Ctrl-C only warns, the second ends it
            self.writing
                .store(write && progress.phase != Phase::Looking, Ordering::SeqCst);
            match self.presses.load(Ordering::SeqCst) {
                0 => {}
                1 if !refused => {
                    refused = true;
                    self.line(REFUSED);
                }
                1 => {}
                _ => {
                    say_stopped(&mut self.out, &self.note);
                    (self.end)(exit::STOPPED)
                }
            }
            let sentence = progress.sentence(&self.caps);
            if progress.phase == Phase::Writing {
                let tenth = (progress.fraction() * 10.0) as usize;
                if step != Some(tenth) {
                    step = Some(tenth);
                    self.line(&format!(
                        "updating your pedal: {}%",
                        (progress.fraction() * 100.0) as usize
                    ));
                }
            } else if said.as_deref() != Some(sentence.as_str()) {
                self.line(&sentence);
            }
            said = Some(sentence);
            if !hinted
                && matches!(progress.phase, Phase::Looking | Phase::Again)
                && started.elapsed().as_secs_f64() > HINT_AFTER
            {
                hinted = true;
                for h in hint {
                    self.line(h);
                }
            }
        }
        self.writing.store(false, Ordering::SeqCst);
        worker
            .join()
            .unwrap_or_else(|_| Outcome::failed(&undertone_protocol::Error::Setup("the tool stopped".into())))
    }
}
