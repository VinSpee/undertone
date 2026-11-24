// SPDX-License-Identifier: GPL-3.0-only
//! One pass of a tool, as tools/undertone.py's `run` makes it: wait for the pedal, back it up, compare, and with a
//! confirmation write. Every check, refusal and write is the protocol library's; this file only picks the plan and puts
//! the result in words.
use std::cell::RefCell;
use std::path::PathBuf;

use undertone_protocol::install::{self, Layout, Source};
use undertone_protocol::uboot::{self, Report};
use undertone_protocol::{Bus, Confirmed, Error, Msc, exit};

use crate::kit;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Rescue,
    Install,
    Check,
}

/// What a run does. `images`: a rescue's {file name, flash image} to compare, the first match chosen; empty: identify
/// only. `source`: an install's app area.
pub struct Job<'a> {
    pub kind: Kind,
    pub write: Option<Confirmed>,
    pub images: Vec<(String, Vec<u8>)>,
    pub source: Option<&'a Source>,
}

impl Job<'_> {
    /// A run that only reads and names the pedal: a check, or a rescue with no file to compare.
    pub fn identifies(&self) -> bool {
        self.kind == Kind::Check || (self.kind == Kind::Rescue && self.images.is_empty())
    }
}

/// How the run reaches the pedal and keeps what it read.
pub struct Env<'a> {
    pub bus: &'a mut dyn Bus,
    pub loader: &'a dyn Fn() -> Result<Vec<u8>, Error>,
    pub layouts: Vec<Layout>,
    pub heads: Vec<(u32, &'static str)>,
    pub backups: PathBuf,
    pub attempts: u32,
    /// Wait for the chip's USB boot state only, as on Windows, where a check cannot use the recovery mode.
    pub boot_state_only: bool,
}

/// What a run did, in words.
pub struct Outcome {
    /// The tool's exit code.
    pub code: i32,
    /// Its closing line.
    pub text: String,
    pub report: Option<Report>,
    /// The whole flash as read, also when the run was then refused.
    pub flash: Option<Vec<u8>>,
    /// The backup, also when the run was then refused.
    pub backup: Option<PathBuf>,
    /// The pedal came from M-VAVE's recovery mode.
    pub from_recovery: bool,
}

impl Outcome {
    pub fn failed(e: &Error) -> Outcome {
        let text = match e {
            Error::Transfer(m) | Error::Gone(m) => {
                format!("ERROR: the pedal stopped answering ({m}); nothing was written")
            }
            _ => e.to_string(),
        };
        Outcome {
            code: e.exit_code(),
            text,
            report: None,
            flash: None,
            backup: None,
            from_recovery: false,
        }
    }
}

pub fn run(job: Job, env: &mut Env, log: &mut dyn FnMut(&str), say: &mut dyn FnMut(&str)) -> Outcome {
    assert!(
        job.write.is_none() || (job.kind == Kind::Install || (job.kind == Kind::Rescue && job.images.len() == 1)),
        "only a rescue with one file or an install writes"
    );
    let from_recovery = RefCell::new(false);
    let seen_flash: RefCell<Option<Vec<u8>>> = RefCell::new(None);
    let seen_backup: RefCell<Option<PathBuf>> = RefCell::new(None);
    let (log, say) = (RefCell::new(log), RefCell::new(say));
    let logged = |m: &str| (log.borrow_mut())(m);
    let said = |m: &str| {
        if m.contains("M-VAVE's recovery mode") {
            *from_recovery.borrow_mut() = true;
        }
        (say.borrow_mut())(m)
    };
    let shape = job_shape(&job);
    let identifies = job.identifies();
    let result = (|| {
        let loader = (env.loader)()?;
        let (mut l1, mut l2, l3, mut s1) = (logged, logged, logged, said);
        let mut inner = match (job.kind, job.source) {
            (Kind::Install, Some(source)) => install::plan_for(source, &env.layouts, &mut l1),
            _ if identifies => {
                logged("check: the pedal is compared with its own flash, so nothing differs and nothing is written");
                uboot::own_flash()
            }
            _ => uboot::matching(job.images.clone())?,
        };
        let mut plan = |chip: &uboot::Chip, flash: &[u8]| {
            *seen_flash.borrow_mut() = Some(flash.to_vec());
            inner(chip, flash)
        };
        let install_route = job.kind == Kind::Install || (job.kind == Kind::Check && !env.boot_state_only);
        let (bus, layouts, heads) = (&mut *env.bus, &env.layouts, &env.heads);
        let mut opened = || -> Result<Box<dyn Msc>, Error> {
            let msc = if install_route {
                install::boot_state(bus, layouts, heads, &mut l2, &mut s1)?
            } else {
                uboot::wait_for_pedal(bus, env.boot_state_only, &mut l2)?
            };
            l3("pedal found");
            Ok(msc)
        };
        let backups = env.backups.clone();
        let mut save = |flash: &[u8]| {
            let path = kit::save_backup(&backups, flash)?;
            *seen_backup.borrow_mut() = Some(path.clone());
            Ok(path)
        };
        uboot::rescue(
            &mut opened,
            &loader,
            &mut plan,
            job.write,
            &mut save,
            env.attempts,
            &mut |m| logged(m),
        )
    })();
    let (from_recovery, flash, backup) = (
        from_recovery.into_inner(),
        seen_flash.into_inner(),
        seen_backup.into_inner(),
    );
    match result {
        Ok(report) => {
            let text = closing(&shape, &report);
            Outcome {
                code: exit::DONE,
                text,
                report: Some(report),
                flash,
                backup,
                from_recovery,
            }
        }
        Err(e) => Outcome {
            from_recovery,
            flash,
            backup,
            ..Outcome::failed(&e)
        },
    }
}

/// What the closing line needs to know about the job.
struct Shape {
    kind: Kind,
    identifies: bool,
    write: bool,
    what: String,
}

fn job_shape(job: &Job) -> Shape {
    Shape {
        kind: job.kind,
        identifies: job.identifies(),
        write: job.write.is_some(),
        what: job.source.map(|s| s.what.clone()).unwrap_or_default(),
    }
}

/// The tool's own last line.
fn closing(job: &Shape, r: &Report) -> String {
    let (n, backup) = (r.sectors, r.backup.display());
    if job.identifies {
        return format!("Check finished, nothing was written. Backup: {backup}");
    }
    match (job.kind, job.write) {
        (Kind::Rescue, true) => {
            format!("Done: {n} sectors written and verified. Power-cycle the pedal. Backup: {backup}")
        }
        (Kind::Rescue, false) => {
            format!("Read-only run finished, nothing was written. {n} sectors differ from the image. Backup: {backup}")
        }
        (_, true) => format!(
            "Done: {n} sectors written and verified, on {}. Backup: {backup}",
            r.layout.as_ref().map_or("the pedal", |l| l.name.as_str())
        ),
        (_, false) => format!(
            "Dry run finished, nothing was written. {n} sectors differ from {}. The pedal restarts into its firmware. \
             Backup: {backup}",
            job.what
        ),
    }
}
