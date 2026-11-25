// SPDX-License-Identifier: GPL-3.0-only
//! The commands `rescue`, `install` and `check`, as tools/undertone.py prints and asks them: a calm header, the tool's
//! own lines with their time, a question that needs a typed yes before any write, and the next step in words.
use std::io::{IsTerminal, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;

use undertone_protocol::install::{self, Layout, Source};
use undertone_protocol::reading::{Reading, read_pedal};
use undertone_protocol::uboot::{Window, package_image};
use undertone_protocol::{Bus, Confirmed, Error, exit};

use crate::kit::{self, GUIDE};
use crate::run::{Env, Job, Kind, Outcome, run};

/// M-VAVE's files in the firmware folder, tried in this order.
pub const OFFICIAL: [&str; 3] = ["BlackBox_023.fwsc", "BlackBox_022.fwsc", "BlackBox_020.fwsc"];
/// The file of each path of docs/RESCUE.md.
pub fn path_file(path: char) -> Option<&'static str> {
    match path {
        'A' => Some("BlackBox_020.fwsc"),
        'B' => Some("BlackBox_023.fwsc"),
        _ => None,
    }
}
/// The official firmware each file ends on.
pub fn ends_on(file: &str) -> &str {
    match file {
        "BlackBox_020.fwsc" => "V20",
        "BlackBox_022.fwsc" => "V22",
        "BlackBox_023.fwsc" => "V23",
        other => other,
    }
}

pub const KEY_HOLD: &str = "When this says it is waiting: on a BlackBox with M-VAVE's V22 or V23 head, switch it off, \
                            hold HOME, the right footswitch and the knob's PUSH, switch it on and keep holding until \
                            the screen shows RECOVERY. A pedal already in the chip's USB boot state is taken as it is.";

/// The Gamut app area of the release pin, by its file name and SHA-256 (firmware/apps/gamut/release.sha256).
const GAMUT_PIN: &str = include_str!("../../../firmware/apps/gamut/release.sha256");

/// Where the commands find their files and send their output.
pub struct Ctx<'a> {
    /// The folder of the kit or repository: its `firmware` folder and Gamut's build.
    pub root: PathBuf,
    pub out: &'a mut Out,
    /// Reads one line the person typed; None at the end of input.
    pub reader: &'a mut dyn FnMut(&str) -> Option<String>,
    pub bus: &'a mut dyn Bus,
    pub loader: &'a dyn Fn() -> Result<Vec<u8>, Error>,
    pub backups: PathBuf,
    pub attempts: u32,
    /// The flash layouts and recovery heads undertone knows (the tests give synthetic ones).
    pub layouts: Vec<Layout>,
    pub heads: Vec<(u32, &'static str)>,
    /// Whether this computer is Windows, where only the chip's USB boot state is reachable.
    pub windows: bool,
}

impl Ctx<'_> {
    fn firmware(&self) -> PathBuf {
        self.root.join("firmware")
    }

    /// One run; the recovery mode's lines are timed as the tool's own when `say_timed`, else printed as they come.
    fn run(&mut self, job: Job, say_timed: bool) -> Outcome {
        let mut env = Env {
            bus: &mut *self.bus,
            loader: self.loader,
            layouts: self.layouts.clone(),
            heads: self.heads.clone(),
            backups: self.backups.clone(),
            attempts: self.attempts,
            boot_state_only: self.windows,
        };
        let out = std::cell::RefCell::new(&mut *self.out);
        let mut log = |m: &str| out.borrow_mut().log(m);
        let mut say = |m: &str| {
            if say_timed {
                out.borrow_mut().log(m)
            } else {
                out.borrow_mut().line(m)
            }
        };
        run(job, &mut env, &mut log, &mut say)
    }

    /// True only when the person types yes; returns what they typed.
    fn confirm(&mut self, question: &str) -> String {
        self.out.line("");
        (self.reader)(&format!("{question} Type yes to go on, anything else to stop: ")).unwrap_or_default()
    }
}

/// Plain lines with a calm header; bold and the lamp only on a terminal that takes colour.
pub struct Out {
    stream: Box<dyn Write>,
    rich: bool,
    t0: Instant,
}

impl Out {
    pub fn stdout() -> Out {
        let rich = std::io::stdout().is_terminal()
            && std::env::var_os("NO_COLOR").is_none()
            && std::env::var("TERM").ok().as_deref() != Some("dumb");
        Out {
            stream: Box::new(std::io::stdout()),
            rich,
            t0: Instant::now(),
        }
    }

    #[cfg(test)]
    pub fn to(stream: Box<dyn Write>) -> Out {
        Out {
            stream,
            rich: false,
            t0: Instant::now(),
        }
    }

    pub fn line(&mut self, text: &str) {
        let _ = writeln!(self.stream, "{text}");
        let _ = self.stream.flush();
    }

    pub fn strong(&mut self, text: &str) {
        let text = if self.rich {
            format!("\x1b[1m{text}\x1b[0m")
        } else {
            text.to_string()
        };
        self.line(&text);
    }

    pub fn header(&mut self, what: &str) {
        self.line("");
        if self.rich {
            self.strong(&format!("\x1b[38;2;196;245;66m●\x1b[0m undertone · {what}"));
        } else {
            self.line(&format!("undertone - {what}"));
        }
        self.line(&format!("rescue kit {}", kit::version()));
        self.line("");
    }

    pub fn log(&mut self, m: &str) {
        if m == "pedal found" {
            self.t0 = Instant::now();
        }
        let t = self.t0.elapsed().as_secs_f64();
        self.line(&format!("[{t:6.1}s] {m}"));
    }
}

fn finished(out: &mut Out, o: &Outcome) -> i32 {
    if o.code != 0 {
        out.line("");
        out.strong(&o.text);
        if let Some(b) = &o.backup {
            out.line(&format!("Backup: {}", b.display()));
        }
    }
    o.code
}

fn read(path: &Path) -> Result<Vec<u8>, Error> {
    std::fs::read(path).map_err(|e| Error::Setup(format!("cannot read {}: {}", path.display(), kit::reason(&e))))
}

fn name(path: &Path) -> String {
    path.file_name()
        .map_or_else(|| path.display().to_string(), |n| n.to_string_lossy().into_owned())
}

/// {file name: flash image} to try: the file given, else M-VAVE's files found in the firmware folder.
pub fn official_images(
    firmware: &Path,
    package: Option<&Path>,
    image: Option<&Path>,
) -> Result<Vec<(String, Vec<u8>)>, Error> {
    if let Some(image) = image {
        let data = read(image)?;
        Window::for_image(data.len())?;
        return Ok(vec![(name(image), data)]);
    }
    if let Some(package) = package {
        if !package.exists() {
            return Err(Error::Setup(format!(
                "{} not found: pass --package FILE.fwsc (the official BlackBox package) or --image flash.bin",
                package.display()
            )));
        }
        return Ok(vec![(
            name(package),
            package_image(&read(package)?, &package.display().to_string())?,
        )]);
    }
    let mut images = vec![];
    for file in OFFICIAL {
        let path = firmware.join(file);
        if path.exists() {
            images.push((
                file.to_string(),
                package_image(&read(&path)?, &path.display().to_string())?,
            ));
        }
    }
    Ok(images)
}

pub fn cmd_rescue(ctx: &mut Ctx, package: Option<&Path>, image: Option<&Path>) -> i32 {
    ctx.out.header("rescue a pedal that will not start");
    let images = match official_images(&ctx.firmware(), package, image) {
        Ok(images) => images,
        Err(e) => return finished(ctx.out, &Outcome::failed(&e)),
    };
    ctx.out
        .line("Step 1 of 2: a read-only check. It saves a backup of the whole pedal and writes nothing.");
    ctx.out
        .line("Unplug the pedal. When this says it is waiting, plug it straight into this computer, with no hub.");
    ctx.out.line("");
    let o = ctx.run(
        Job {
            kind: Kind::Rescue,
            write: None,
            images: images.clone(),
            source: None,
        },
        true,
    );
    if o.code != 0 {
        finished(ctx.out, &o);
        if o.code == exit::REFUSED
            && let Some(flash) = &o.flash
        {
            advise(ctx, flash, &images);
        }
        return o.code;
    }
    ctx.out.line("");
    ctx.out.line(&o.text);
    let report = o.report.expect("a run that passed has its report");
    if images.is_empty() {
        return advise(ctx, &report.flash, &images);
    }
    let file = report
        .file
        .clone()
        .expect("a rescue with files names the one the pedal matched");
    ctx.out.line("");
    ctx.out.strong(&format!(
        "The pedal matches {file}. The restore puts M-VAVE's official {} back.",
        ends_on(&file)
    ));
    let answer = ctx.confirm("Step 2 writes the pedal's app area.");
    let Some(yes) = Confirmed::new(&report, &answer) else {
        ctx.out.line(&format!(
            "Stopped. Nothing was written. Backup: {}",
            report.backup.display()
        ));
        return exit::NOT_CONFIRMED;
    };
    ctx.out.line("");
    ctx.out.line(
        "Step 2 of 2: the restore. Unplug the pedal and plug it in again when this says it is waiting. Do not touch \
         the cable while it writes.",
    );
    ctx.out.line("");
    let chosen = images.into_iter().filter(|(n, _)| *n == file).collect();
    let o = ctx.run(
        Job {
            kind: Kind::Rescue,
            write: Some(yes),
            images: chosen,
            source: None,
        },
        true,
    );
    if o.code != 0 {
        return finished(ctx.out, &o);
    }
    ctx.out.line("");
    ctx.out.strong(&o.text);
    ctx.out
        .line("Next: unplug the cable, switch the pedal off, wait 5 seconds and switch it on.");
    if Some(file.as_str()) != path_file('A') {
        ctx.out.line(
            "Do not install Gamut on this pedal from an installer page: it would go dark again. Use `undertone \
             install` (the guide's section \"Gamut on a BlackBox with V22 or V23\").",
        );
    }
    exit::DONE
}

/// After a refusal or a run with no file: which file the pedal needs, from its head.
fn advise(ctx: &mut Ctx, flash: &[u8], images: &[(String, Vec<u8>)]) -> i32 {
    let r = read_pedal(flash, &ctx.layouts);
    ctx.out.line("");
    ctx.out.line(&format!("The pedal had {}.", r.family));
    let has = |f: &str| images.iter().any(|(n, _)| n == f);
    if let Some(need) = path_file(r.path)
        && !has(need)
        && !(r.path == 'B' && has("BlackBox_022.fwsc"))
    {
        let firmware = ctx.firmware();
        ctx.out.strong(&format!(
            "Next: put M-VAVE's {need} in the firmware folder ({}) and run undertone rescue again. \
             firmware/README.txt says where to get it.",
            firmware.display()
        ));
        return exit::FAILED;
    }
    if r.path == 'C' {
        ctx.out.strong(&format!(
            "Next: stop here. No official file fits this pedal; do not try others. Keep the backup and ask for help \
             with the guide: {GUIDE}#if-it-does-not-work"
        ));
        return exit::REFUSED;
    }
    exit::FAILED
}

/// The app area to install: the file given, a test build or custom firmware among them, else Gamut's, the one the
/// release pin names, under the kit's folder.
pub fn gamut_source(root: &Path, path: Option<&Path>, layouts: &[Layout]) -> Result<Source, Error> {
    let (pinned, digest) = install::gamut_pin(GAMUT_PIN)
        .ok_or_else(|| Error::Setup(format!("{} names no app area (*-v23.bin)", install::GAMUT_PIN)))?;
    let file = path.map_or_else(|| root.join(pinned), Path::to_path_buf);
    if !file.exists() {
        return Err(Error::Setup(match path {
            None => format!(
                "Gamut's file is not in this folder: the rescue kit holds only M-VAVE's way back. Install Gamut from \
                 the Undertone repository after `node tools/op.mjs package`, or from the installer page when the \
                 pedal starts ({GUIDE}#gamut-on-a-blackbox-with-v22-or-v23)"
            ),
            Some(p) => format!(
                "{} not found: build Gamut first (node tools/op.mjs package), or pass --gamut FILE",
                p.display()
            ),
        }));
    }
    install::app_area(read(&file)?, &name(&file), digest, layouts)
}

pub enum InstallFrom<'a> {
    Gamut(Option<&'a Path>),
    Official(&'a Path),
    Restore(&'a Path),
}

pub fn install_source(root: &Path, from: InstallFrom, layouts: &[Layout]) -> Result<Source, Error> {
    match from {
        InstallFrom::Official(p) => install::official_area(&read(p)?, &name(p), layouts),
        InstallFrom::Restore(p) => install::backup_area(&read(p)?, &name(p), layouts),
        InstallFrom::Gamut(p) => gamut_source(root, p, layouts),
    }
}

pub fn cmd_install(ctx: &mut Ctx, from: InstallFrom) -> i32 {
    ctx.out.header("put Gamut on a pedal");
    if ctx.windows {
        let e = Error::Setup(
            "this tool does not run on Windows: M-VAVE's recovery mode has not been tried there. undertone rescue \
             restores the official firmware (docs/RESCUE.md)"
                .into(),
        );
        return finished(ctx.out, &Outcome::failed(&e));
    }
    let source = match install_source(&ctx.root, from, &ctx.layouts) {
        Ok(s) => s,
        Err(e) => return finished(ctx.out, &Outcome::failed(&e)),
    };
    if source.custom {
        ctx.out.strong(&format!(
            "This is a {}: its SHA-256 is not the release pin's. undertone checks that the boot loader would start \
             it and that it stays inside the app area, not what it does.",
            install::CUSTOM
        ));
    }
    ctx.out.line(&format!(
        "Step 1 of 2: a dry run with {}. It saves a backup and writes nothing.",
        source.what
    ));
    ctx.out.line(KEY_HOLD);
    ctx.out.line("");
    let o = ctx.run(
        Job {
            kind: Kind::Install,
            write: None,
            images: vec![],
            source: Some(&source),
        },
        false,
    );
    if o.code != 0 {
        return finished(ctx.out, &o);
    }
    ctx.out.line("");
    ctx.out.line(&o.text);
    let report = o.report.expect("a run that passed has its report");
    let answer = ctx.confirm(&format!("Step 2 writes {} to the pedal's app area.", source.what));
    let Some(yes) = Confirmed::new(&report, &answer) else {
        ctx.out.line(&format!(
            "Stopped. Nothing was written. Backup: {}",
            report.backup.display()
        ));
        return exit::NOT_CONFIRMED;
    };
    ctx.out.line("");
    ctx.out.line(&format!(
        "Step 2 of 2: the write. {KEY_HOLD} Do not touch the cable while it writes."
    ));
    ctx.out.line("");
    let o = ctx.run(
        Job {
            kind: Kind::Install,
            write: Some(yes),
            images: vec![],
            source: Some(&source),
        },
        false,
    );
    if o.code != 0 {
        return finished(ctx.out, &o);
    }
    ctx.out.line("");
    ctx.out.strong(&o.text);
    let levels = o
        .report
        .as_ref()
        .and_then(|r| r.layout.as_ref())
        .map_or("", |l| l.levels.as_str());
    ctx.out.line(&if source.boot.is_none() {
        install::FIRST_RUN.replace("{levels}", levels)
    } else {
        "Next: power-cycle the pedal.".to_string()
    });
    exit::DONE
}

pub fn cmd_check(ctx: &mut Ctx) -> i32 {
    ctx.out.header("check a pedal");
    ctx.out
        .line("A read-only check: it finds the pedal, saves a backup of the whole pedal and writes nothing.");
    ctx.out.line(if ctx.windows {
        "Plug the pedal straight into this computer, with no hub."
    } else {
        KEY_HOLD
    });
    ctx.out.line("");
    let o = ctx.run(
        Job {
            kind: Kind::Check,
            write: None,
            images: vec![],
            source: None,
        },
        false,
    );
    if o.code != 0 {
        return finished(ctx.out, &o);
    }
    let report = o.report.as_ref().expect("a run that passed has its report");
    let r: Reading = read_pedal(&report.flash, &ctx.layouts);
    let found = if o.from_recovery {
        "M-VAVE recovery mode, then the chip USB boot state"
    } else {
        "the chip USB boot state"
    };
    ctx.out.line("");
    ctx.out.line(&format!("found in:  {found}"));
    ctx.out.line(&format!("head:      {}", r.family));
    ctx.out.line(&format!(
        "layout:    {}",
        r.layout.as_deref().unwrap_or("not one undertone knows")
    ));
    ctx.out
        .line(&format!("app area:  {}", r.app.as_deref().unwrap_or("unknown")));
    ctx.out.line(&format!("backup:    {}", report.backup.display()));
    ctx.out.line("");
    ctx.out.strong(match r.path {
        'A' => "To restore it: undertone rescue, with BlackBox_020.fwsc in the firmware folder.",
        'B' => "To restore it: undertone rescue, with BlackBox_023.fwsc in the firmware folder.",
        _ => "No official file of this kit fits this pedal. Keep the backup and ask for help with the guide.",
    });
    exit::DONE
}
