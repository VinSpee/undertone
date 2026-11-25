// SPDX-License-Identifier: GPL-3.0-only
//! What the tool's lines mean, in one plain sentence, and while writing how far it is (undertone_screens.Progress).
use super::look::{Caps, glyph};

pub const REFUSED: &str = "do not unplug: your pedal is being updated";
pub const STOPPED: &str = "Stopped. Start undertone again to start over; a fix that was under way continues where it stopped.";

/// What the program says when a second Ctrl-C ends it during a write, in either view: the stopped line, then the note.
pub fn say_stopped(out: &mut dyn std::io::Write, note: &[String]) {
    let _ = writeln!(out, "\n{STOPPED}");
    for l in note {
        let _ = writeln!(out, "{l}");
    }
    let _ = out.flush();
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Phase {
    Looking,
    Again,
    Found,
    Reading,
    Saving,
    Checking,
    Writing,
    Restarting,
}

impl Phase {
    #[cfg(test)]
    pub fn name(self) -> &'static str {
        match self {
            Phase::Looking => "looking",
            Phase::Again => "again",
            Phase::Found => "found",
            Phase::Reading => "reading",
            Phase::Saving => "saving",
            Phase::Checking => "checking",
            Phase::Writing => "writing",
            Phase::Restarting => "restarting",
        }
    }

    pub fn words(self) -> &'static str {
        match self {
            Phase::Looking => "looking for your pedal",
            Phase::Again => "waiting for your pedal to come back",
            Phase::Found => "found it",
            Phase::Reading => "reading your pedal",
            Phase::Saving => "saving a copy of your pedal",
            Phase::Checking => "checking",
            Phase::Writing => "updating your pedal",
            Phase::Restarting => "restarting your pedal",
        }
    }
}

pub struct Progress {
    write: bool,
    pub phase: Phase,
    pub done: usize,
    pub total: usize,
}

/// The number at the start of `s` and the rest, as the Python regex `(\d+)` reads it.
fn number(s: &str) -> Option<(usize, &str)> {
    let digits = s.bytes().take_while(u8::is_ascii_digit).count();
    Some((s[..digits].parse().ok()?, &s[digits..]))
}

impl Progress {
    pub fn new(write: bool) -> Progress {
        Progress {
            write,
            phase: Phase::Looking,
            done: 0,
            total: 0,
        }
    }

    pub fn feed(&mut self, line: &str) {
        if line.starts_with("waiting for the pedal") {
            if self.phase != Phase::Looking {
                self.phase = Phase::Again;
            }
        } else if line.starts_with("the pedal went away") {
            self.phase = Phase::Again;
        } else if line.starts_with("pedal found")
            || line.contains("M-VAVE's recovery mode")
            || line.starts_with("leave sent")
        {
            self.phase = Phase::Found;
        } else if line.starts_with("loader running") || line.starts_with("INQUIRY") {
            self.phase = Phase::Reading;
        } else if line.starts_with("flash read") {
            self.phase = Phase::Saving;
        } else if line.starts_with("backup saved: ") {
            self.phase = Phase::Checking;
        } else if let Some((total, rest)) = number(line)
            && rest.starts_with(" of ")
            && number(&rest[4..]).is_some_and(|(_, r)| r.starts_with(" sectors"))
        {
            self.total = total;
            if self.write && total > 0 {
                self.phase = Phase::Writing;
            }
        } else if let Some(rest) = line.trim_start().strip_prefix("written ")
            && let Some((done, rest)) = number(rest)
            && let Some((total, _)) = rest.strip_prefix('/').and_then(number)
        {
            (self.phase, self.done, self.total) = (Phase::Writing, done, total);
        } else if line.starts_with("run-app sent") {
            self.phase = Phase::Restarting;
        }
    }

    pub fn fraction(&self) -> f64 {
        if self.total > 0 {
            self.done as f64 / self.total as f64
        } else {
            0.0
        }
    }

    pub fn sentence(&self, caps: &Caps) -> String {
        let text = self.phase.words();
        if matches!(self.phase, Phase::Found | Phase::Writing) {
            text.to_string()
        } else {
            format!("{text}{}", glyph(caps, "ellipsis"))
        }
    }
}
