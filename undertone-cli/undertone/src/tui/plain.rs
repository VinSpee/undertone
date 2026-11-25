// SPDX-License-Identifier: GPL-3.0-only
//! Numbered questions and one line per step, for a pipe, a small or a colourless terminal, or a screen reader
//! (undertone_screens.PlainView).
use std::io::{BufRead, Write};
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, mpsc};
use std::time::{Duration, Instant};

use super::guide::{Log, View, WorkFn};
use super::look::{Caps, Depth, Screen};
use super::progress::{Phase, Progress};
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
        }
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
        let mut progress = Progress::new(write);
        let (tx, rx) = mpsc::channel::<String>();
        let stop = Arc::new(AtomicBool::new(false));
        let worker = std::thread::spawn(move || job(&mut |m| drop(tx.send(m.to_string())), stop));
        let (started, mut said, mut hinted, mut step) = (Instant::now(), None::<String>, false, None::<usize>);
        loop {
            match rx.recv_timeout(Duration::from_millis(250)) {
                Ok(line) => {
                    log.write(&line);
                    progress.feed(&line);
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {}
                Err(mpsc::RecvTimeoutError::Disconnected) => break,
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
        worker
            .join()
            .unwrap_or_else(|_| Outcome::failed(&undertone_protocol::Error::Setup("the tool stopped".into())))
    }
}
