// SPDX-License-Identifier: GPL-3.0-only
//! The guided flow, as tools/undertone_screens.py's `Guide`: a small state machine where each state shows one screen
//! and names the next. The tools and their checks are the protocol library's (through `run`); the guide only asks and
//! shows, and a write is reached only from the "replace the software?" screen's yes.
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use undertone_protocol::install::{CUSTOM, Layout, Source};
use undertone_protocol::reading::read_pedal;
use undertone_protocol::{Bus, Clock, Confirmed, Error, Msc, RecoveryDevice};

use super::look::Screen;
use crate::commands::{ends_on, path_file};
use crate::kit::{self, GUIDE};
use crate::run::{Env, Job, Kind, Outcome, run};

/// The states a restart under sudo starts at, for each task.
pub fn restart_state(task: &str) -> Option<State> {
    match task {
        "rescue" => Some(State::RescueCheck),
        "install" => Some(State::Install),
        "check" => Some(State::CheckWork),
        _ => None,
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum State {
    Menu,
    NeedAdmin,
    Rescue,
    RescueCheck,
    AskPath,
    NeedFile,
    Cannot,
    RescueReady,
    Confirm,
    NotNow,
    RescueWrite,
    Install,
    OwnFile,
    OwnReady,
    InstallCheck,
    InstallWrite,
    Check,
    CheckWork,
    GuideThenMenu,
}

/// A tool's run, handed to the view: it gets the line sink and returns the outcome. The view runs it on a thread of
/// its own while it draws, and sets the stop flag when the person leaves the wait for the pedal.
pub type WorkFn = Box<dyn FnOnce(&mut dyn FnMut(&str), Arc<AtomicBool>) -> Outcome + Send>;

/// The app area to install from a file, or from Gamut's release with None, checked.
pub type AppFn = Box<dyn Fn(Option<&Path>) -> std::result::Result<Source, Error>>;

/// How a screen is shown and answered: the full-screen view, the plain one, or a test's.
pub trait View {
    /// The key of the chosen choice, or "back" or "quit".
    fn ask(&mut self, screen: &Screen) -> String;
    /// Runs `job` while the screen shows what it does. "back" or "quit" while it looks for the pedal stops the wait
    /// (outcome code 130, its text the key).
    fn work(&mut self, screen: &Screen, job: WorkFn, log: &mut Log, write: bool, hint: &[String]) -> Outcome;
    /// What to tell the person if the program ends during the coming run.
    fn resume_note(&mut self, _note: Vec<String>) {}
}

/// The raw lines of every tool run, in a file beside the backups.
pub struct Log {
    folder: Option<PathBuf>,
    pub path: Option<PathBuf>,
    file: Option<std::fs::File>,
}

impl Log {
    pub fn new(folder: Option<PathBuf>) -> Log {
        Log {
            folder,
            path: None,
            file: None,
        }
    }

    pub fn write(&mut self, line: &str) {
        let Some(folder) = &self.folder else {
            return;
        };
        if self.file.is_none() && kit::make_dir(folder).is_ok() {
            let path = folder.join(format!(
                "undertone-{}.log",
                chrono::Local::now().format("%Y%m%d-%H%M%S")
            ));
            self.file = std::fs::OpenOptions::new().create(true).append(true).open(&path).ok();
            kit::hand_back(&path);
            self.path = Some(path);
        }
        if let Some(f) = &mut self.file {
            let _ = writeln!(f, "{} {line}", chrono::Local::now().format("%H:%M:%S"));
            let _ = f.flush();
        }
    }
}

/// What the person is told on the normal screen once the guided screens close.
#[derive(Debug, Default)]
pub struct Result {
    pub lines: Vec<String>,
    pub backup: Option<PathBuf>,
    pub code: i32,
    /// The task to start again at, under sudo.
    pub restart: Option<&'static str>,
}

/// Everything the guide reaches outside itself, so that a test can stand in for it.
pub struct World {
    /// The bus, opened on the first run (on Windows only an administrator may open it, and the screens come first).
    pub bus: Arc<Mutex<Option<Box<dyn Bus + Send>>>>,
    pub open_bus: Arc<dyn Fn() -> std::result::Result<Box<dyn Bus + Send>, Error> + Send + Sync>,
    pub loader: Arc<dyn Fn() -> std::result::Result<Vec<u8>, Error> + Send + Sync>,
    pub layouts: Vec<Layout>,
    pub heads: Vec<(u32, &'static str)>,
    pub backups: PathBuf,
    pub attempts: u32,
    /// The kit's folder, for its firmware folder.
    pub root: PathBuf,
    /// What to do before reaching the pedal, in words, when this process may not; None when it may.
    pub permission: Box<dyn Fn() -> Option<&'static str>>,
    /// The app area to install: the file given, else Gamut's, the one the release pin names.
    pub gamut: AppFn,
    pub open_url: Box<dyn FnMut(&str)>,
    pub windows: bool,
}

pub struct Guide<'v> {
    view: &'v mut dyn View,
    w: World,
    pub state: Option<State>,
    pub log: Log,
    pub result: Result,
    kind: Option<&'static str>,
    images: Vec<(String, Vec<u8>)>,
    source: Option<Source>,
    /// The file of the person's own chosen for the install, when it is not Gamut's release.
    own: Option<PathBuf>,
    outcome: Option<Outcome>,
    need_file: Option<&'static str>,
    confirmed: Option<Confirmed>,
    /// A write is under way: the screens end with the resume note if they end now.
    pub writing: Arc<AtomicBool>,
    partial: bool,
}

fn nothing_changes() -> [&'static str; 2] {
    [
        "First undertone checks your pedal and saves a copy of it.",
        "Nothing changes until you say yes.",
    ]
}

/// The choice that installs an app image of the person's own from the firmware folder.
const OWN: (&str, &str) = ("own", "a file of my own");
/// The most files of the person's own one screen lists.
const MAX_OWN: usize = 5;

const SHORT_A: &str = "M-VAVE V20";
const SHORT_B: &str = "M-VAVE V23";

impl<'v> Guide<'v> {
    pub fn new(view: &'v mut dyn View, w: World, start: &str, log: Log) -> Guide<'v> {
        let kind = match start {
            "rescue" => Some("rescue"),
            "install" => Some("install"),
            "check" => Some("check"),
            _ => None,
        };
        Guide {
            view,
            state: Some(restart_state(start).unwrap_or(State::Menu)),
            log,
            result: Result::default(),
            kind,
            images: vec![],
            source: None,
            own: None,
            outcome: None,
            need_file: None,
            confirmed: None,
            writing: Arc::new(AtomicBool::new(false)),
            partial: false,
            w,
        }
    }

    pub fn go(mut self) -> Result {
        while let Some(state) = self.state {
            self.state = self.step(state);
        }
        if let Some(path) = &self.log.path {
            self.result
                .lines
                .push(format!("details, if you ask for help: {}", path.display()));
        }
        self.result
    }

    fn step(&mut self, state: State) -> Option<State> {
        match state {
            State::Menu => self.menu(),
            State::NeedAdmin => self.need_admin(),
            State::Rescue => self.rescue(),
            State::RescueCheck => self.rescue_check(),
            State::AskPath => self.ask_path(),
            State::NeedFile => self.need_file(),
            State::Cannot => self.cannot(),
            State::RescueReady => self.rescue_ready(),
            State::Confirm => self.confirm(),
            State::NotNow => self.not_now(),
            State::RescueWrite => self.rescue_write(),
            State::Install => self.install(),
            State::OwnFile => self.own_file(),
            State::OwnReady => self.own_ready(),
            State::InstallCheck => self.install_check(),
            State::InstallWrite => self.install_write(),
            State::Check => self.check(),
            State::CheckWork => self.check_work(),
            State::GuideThenMenu => {
                (self.w.open_url)(GUIDE);
                Some(State::Menu)
            }
        }
    }

    // -- helpers
    fn choose(&mut self, screen: Screen, routes: &[(&str, Option<State>)]) -> Option<State> {
        let key = self.view.ask(&screen);
        if key == "quit" {
            return None;
        }
        routes.iter().find(|(k, _)| *k == key).and_then(|(_, s)| *s)
    }

    /// The state to show when this process may not reach the pedal, else None.
    fn permission(&self) -> Option<State> {
        (self.w.permission)().map(|_| State::NeedAdmin)
    }

    /// One run of a tool behind a screen. Its closing line goes to the log; its backup is kept for the end.
    fn work(&mut self, screen: Screen, kind: Kind, write: Option<Confirmed>) -> Outcome {
        let writes = write.is_some();
        let job_images = self.images.clone();
        let source = self.source.clone();
        let (bus, open_bus, loader) = (self.w.bus.clone(), self.w.open_bus.clone(), self.w.loader.clone());
        let (layouts, heads) = (self.w.layouts.clone(), self.w.heads.clone());
        let (backups, attempts, boot_state_only) = (self.w.backups.clone(), self.w.attempts, self.w.windows);
        let job: WorkFn = Box::new(move |lines, stop| {
            let mut bus = bus.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
            if bus.is_none() {
                match open_bus() {
                    Ok(b) => *bus = Some(b),
                    Err(e) => return Outcome::failed(&e),
                }
            }
            let Some(bus) = bus.as_mut() else {
                unreachable!("opened just above")
            };
            let mut watched = Watch {
                inner: bus.as_mut(),
                stop,
            };
            let loader = move || loader();
            let mut env = Env {
                bus: &mut watched,
                loader: &loader,
                layouts,
                heads,
                backups,
                attempts,
                boot_state_only,
            };
            let job = Job {
                kind,
                write,
                images: job_images,
                source: source.as_ref(),
            };
            let sink = std::cell::RefCell::new(lines);
            run(job, &mut env, &mut |m| (sink.borrow_mut())(m), &mut |m| {
                (sink.borrow_mut())(m)
            })
        });
        self.writing.store(writes, Ordering::SeqCst);
        let hint = self.hint();
        let note = self.resume_note();
        self.view.resume_note(note);
        let o = self.view.work(&screen, job, &mut self.log, writes, &hint);
        self.writing.store(false, Ordering::SeqCst);
        self.log.write(&o.text);
        if let Some(b) = &o.backup {
            self.result.backup = Some(b.clone());
        }
        o
    }

    /// What to tell the person when the screens end in the middle of a write.
    pub fn resume_note(&self) -> Vec<String> {
        let kind = match &self.own {
            Some(file) if self.kind == Some("install") => format!("install --gamut \"{}\"", file.display()),
            _ => self.kind.unwrap_or("rescue").to_string(),
        };
        resume_note(&kind, self.result.backup.as_deref().unwrap_or(&self.w.backups))
    }

    fn hint(&self) -> Vec<String> {
        vec![
            "Still looking. Plug straight into this computer, no hub.".into(),
            if self.kind == Some("rescue") {
                "Leave it plugged in: undertone catches it as it restarts.".into()
            } else {
                "Hold all three until its screen says RECOVERY.".into()
            },
        ]
    }

    // -- the states
    fn menu(&mut self) -> Option<State> {
        let screen = Screen::new("how can undertone help?", &["Have your pedal and its USB cable ready."]).choices(&[
            ("rescue", "fix a pedal that will not start"),
            ("install", "put gamut on my pedal"),
            ("check", "check my pedal"),
        ]);
        self.choose(
            screen,
            &[
                ("rescue", Some(State::Rescue)),
                ("install", Some(State::Install)),
                ("check", Some(State::Check)),
                ("back", None),
            ],
        )
    }

    fn need_admin(&mut self) -> Option<State> {
        if self.w.windows {
            let screen = Screen::new(
                "open undertone as administrator",
                &[
                    "Press the Windows key, type cmd, right-click Command Prompt,",
                    "choose Run as administrator, and start undertone there.",
                ],
            )
            .choices(&[("done", "close undertone")])
            .problem();
            return self.choose(screen, &[("done", None), ("back", Some(State::Menu))]);
        }
        let screen = Screen::new(
            "undertone needs your password",
            &[
                "Next, your computer asks for the password you log in with.",
                "Type it and press Enter. Nothing shows while you type.",
            ],
        )
        .choices(&[("go", "continue"), ("back", "back")]);
        let key = self.view.ask(&screen);
        if key != "go" {
            return if key == "back" { Some(State::Menu) } else { None };
        }
        self.result.restart = self.kind; // the program starts again under sudo, at this task
        None
    }

    fn rescue(&mut self) -> Option<State> {
        self.kind = Some("rescue");
        let screen =
            Screen::new("fix your pedal", &nothing_changes()).choices(&[("go", "start the check"), ("back", "back")]);
        let go = self.permission().unwrap_or(State::RescueCheck);
        self.choose(screen, &[("go", Some(go)), ("back", Some(State::Menu))])
    }

    fn rescue_check(&mut self) -> Option<State> {
        self.images = match crate::commands::official_images(&self.w.root.join("firmware"), None, None) {
            Ok(images) => images,
            Err(e) => return self.failed(Outcome::failed(&e), State::Rescue),
        };
        let screen = Screen::new(
            "checking your pedal",
            &["Unplug your pedal, then plug it straight into this computer."],
        );
        let o = self.work(screen, Kind::Rescue, None);
        let (code, file, flash) = (o.code, o.report.as_ref().and_then(|r| r.file.clone()), o.flash.clone());
        if code == 130 {
            return stopped(&o, State::Rescue);
        }
        self.outcome = Some(o);
        if code == 0 && file.is_some() {
            return Some(State::RescueReady);
        }
        if let Some(flash) = flash
            && (code == 0 || code == 2)
        {
            let r = read_pedal(&flash, &self.w.layouts);
            let has = |f: &str| self.images.iter().any(|(n, _)| n == f);
            if let Some(need) = path_file(r.path)
                && !has(need)
                && !(r.path == 'B' && has("BlackBox_022.fwsc"))
            {
                return self.need(r.path);
            }
            if r.path == 'C' && self.images.is_empty() {
                return Some(State::AskPath);
            }
            return Some(State::Cannot);
        }
        let o = self.outcome.take().expect("kept just above");
        self.failed(o, State::RescueCheck)
    }

    fn ask_path(&mut self) -> Option<State> {
        let screen = Screen::new(
            "one question first",
            &[
                "Did your pedal ever run M-VAVE's V22 or V23 software?",
                "Undertone could not tell from your pedal.",
            ],
        )
        .choices(&[("B", "yes, or not sure"), ("A", "no, never")]);
        let key = self.view.ask(&screen);
        match key.as_str() {
            "A" => self.need('A'),
            "B" => self.need('B'),
            "back" => Some(State::Rescue),
            _ => None,
        }
    }

    fn need(&mut self, path: char) -> Option<State> {
        self.need_file = path_file(path);
        Some(State::NeedFile)
    }

    fn need_file(&mut self) -> Option<State> {
        let file = self.need_file.unwrap_or("BlackBox_023.fwsc");
        let name = if Some(file) == path_file('A') { SHORT_A } else { SHORT_B };
        let firmware = self.w.root.join("firmware");
        self.result.lines = vec![
            format!(
                "Put M-VAVE's {file} in {}, then start undertone again.",
                firmware.display()
            ),
            "README.txt in that folder says where to get it.".into(),
        ];
        let line = format!("Undertone needs the {name} file to fix your pedal.");
        self.end(Screen::new(
            "one more file needed",
            &[&line, "The check changed nothing. Open the guide to get the file."],
        ))
    }

    fn cannot(&mut self) -> Option<State> {
        self.result.lines = vec![format!(
            "No M-VAVE file fits your pedal. Keep the copy and ask for help: {GUIDE}#if-it-does-not-work"
        )];
        self.result.code = 2;
        self.end(
            Screen::new(
                "this needs a closer look",
                &[
                    "Nothing was changed, and a copy of your pedal is saved.",
                    "Open the guide to see how to ask for help.",
                ],
            )
            .problem(),
        )
    }

    fn rescue_ready(&mut self) -> Option<State> {
        let file = self
            .outcome
            .as_ref()
            .and_then(|o| o.report.as_ref())
            .and_then(|r| r.file.clone());
        let ends = file.as_deref().map_or("own", ends_on);
        let line = format!("Undertone will put M-VAVE's {ends} software back on it.");
        let screen =
            Screen::new("your pedal can be fixed", &[&line]).choices(&[("go", "fix it now"), ("later", "not now")]);
        self.choose(
            screen,
            &[
                ("go", Some(State::Confirm)),
                ("later", Some(State::NotNow)),
                ("back", Some(State::Rescue)),
            ],
        )
    }

    fn confirm(&mut self) -> Option<State> {
        let screen = Screen::new(
            "replace the software?",
            &[
                "This replaces the software on your pedal.",
                "A copy of what is on it now is saved first. Continue?",
            ],
        )
        .choices(&[("no", "no, stop here"), ("yes", "yes, replace it")]);
        let key = self.view.ask(&screen);
        if key == "yes" {
            let report = self.outcome.as_ref().and_then(|o| o.report.as_ref());
            self.confirmed = report.and_then(|r| Confirmed::new(r, &key));
            return Some(if self.kind == Some("rescue") {
                State::RescueWrite
            } else {
                State::InstallWrite
            });
        }
        if key == "no" || key == "back" {
            Some(State::NotNow)
        } else {
            None
        }
    }

    fn not_now(&mut self) -> Option<State> {
        if self.partial {
            self.result.code = 1;
            self.result.lines = self.resume_note()[..2].to_vec();
            return self.end(
                Screen::new(
                    "your pedal may not start",
                    &[
                        "It may be partly updated.",
                        "Start undertone again: it continues where it stopped.",
                    ],
                )
                .problem(),
            );
        }
        self.result.lines = vec!["Nothing was changed on your pedal.".into()];
        self.end(Screen::new(
            "nothing was changed",
            &["Your pedal is as it was. The copy stays saved."],
        ))
    }

    fn rescue_write(&mut self) -> Option<State> {
        let file = self
            .outcome
            .as_ref()
            .and_then(|o| o.report.as_ref())
            .and_then(|r| r.file.clone())
            .unwrap_or_default();
        self.images.retain(|(n, _)| *n == file);
        let screen = Screen::new(
            "fixing your pedal",
            &[
                "Unplug your pedal, then plug it back in.",
                "Then leave the cable alone until undertone finishes.",
            ],
        );
        let yes = self.confirmed.take();
        let o = self.work(screen, Kind::Rescue, yes);
        if o.code == 130 {
            return stopped(&o, State::RescueReady);
        }
        if o.code != 0 {
            self.partial = true;
            return self.failed(o, State::Confirm);
        }
        self.result.lines = vec![
            "Your pedal is fixed. Everything put on it was checked.".into(),
            "Next: unplug the cable, switch your pedal off, wait 5 seconds, then switch it on.".into(),
        ];
        let mut lines = vec!["Unplug the cable, then switch your pedal off and on again."];
        if Some(file.as_str()) != path_file('A') {
            lines.push("To add Gamut later, use undertone, not an installer page.");
            lines.push("An installer page can stop this pedal starting again.");
            self.result
                .lines
                .push("Do not put Gamut on it from an installer page: use undertone instead.".into());
        }
        self.end(Screen::new("your pedal is fixed", &lines))
    }

    fn install(&mut self) -> Option<State> {
        self.kind = Some("install");
        self.own = None;
        let guide = [("guide", "open the guide"), ("back", "back")];
        let routes = [("guide", Some(State::GuideThenMenu)), ("back", Some(State::Menu))];
        if self.w.windows {
            let screen = Screen::new(
                "use a mac for now",
                &[
                    "Undertone cannot put Gamut on a pedal from Windows yet.",
                    "If your pedal starts, use the installer page instead.",
                ],
            )
            .choices(&guide);
            return self.choose(screen, &routes);
        }
        match (self.w.gamut)(None) {
            Ok(source) => self.source = Some(source),
            Err(e @ Error::Refused(_)) => return self.failed(Outcome::failed(&e), State::Install),
            Err(_) => {
                let screen = Screen::new(
                    "gamut is not here",
                    &[
                        "This copy of undertone does not come with Gamut.",
                        "If your pedal starts, use the installer page instead.",
                    ],
                )
                .choices(&[OWN, guide[0], guide[1]]);
                return self.choose(screen, &[(OWN.0, Some(State::OwnFile)), routes[0], routes[1]]);
            }
        }
        let screen = Screen::new("put gamut on your pedal", &nothing_changes()).choices(&[
            ("go", "start the check"),
            OWN,
            ("back", "back"),
        ]);
        let go = self.permission().unwrap_or(State::InstallCheck);
        self.choose(
            screen,
            &[
                ("go", Some(go)),
                (OWN.0, Some(State::OwnFile)),
                ("back", Some(State::Menu)),
            ],
        )
    }

    /// The .bin files in the kit's firmware folder, by name: where the person puts an app image of their own.
    fn own_files(&self) -> Vec<PathBuf> {
        let mut files: Vec<PathBuf> = std::fs::read_dir(self.w.root.join("firmware"))
            .map(|dir| {
                dir.filter_map(|e| e.ok().map(|e| e.path()))
                    .filter(|p| p.is_file() && p.extension().is_some_and(|x| x.eq_ignore_ascii_case("bin")))
                    .collect()
            })
            .unwrap_or_default();
        files.sort();
        files
    }

    fn own_file(&mut self) -> Option<State> {
        let firmware = self.w.root.join("firmware");
        let files = self.own_files();
        if files.is_empty() {
            let mut screen = Screen::new(
                "a file of your own",
                &[
                    "Put your .bin file in undertone's firmware folder,",
                    "then choose look again.",
                ],
            )
            .choices(&[("look", "look again"), ("back", "back")]);
            screen.aside = vec!["firmware folder:".into(), home_short(&firmware)];
            return self.choose(
                screen,
                &[("look", Some(State::OwnFile)), ("back", Some(State::Install))],
            );
        }
        let mut lines = vec!["Choose the file to put on your pedal."];
        if files.len() > MAX_OWN {
            lines.push("Only the first five files in the folder are shown.");
        }
        let mut screen = Screen::new("which file?", &lines);
        screen.choices = files
            .iter()
            .take(MAX_OWN)
            .enumerate()
            .map(|(i, f)| {
                (
                    i.to_string(),
                    f.file_name().unwrap_or_default().to_string_lossy().into_owned(),
                )
            })
            .collect();
        screen.choices.push(("back".into(), "back".into()));
        let key = self.view.ask(&screen);
        let Some(file) = key.parse::<usize>().ok().and_then(|i| files.get(i)) else {
            return if key == "back" { Some(State::Install) } else { None };
        };
        match (self.w.gamut)(Some(file)) {
            Ok(source) => {
                self.source = Some(source);
                self.own = Some(file.clone());
                Some(State::OwnReady)
            }
            Err(e) => {
                let o = Outcome::failed(&e);
                self.result.code = o.code;
                self.result.lines = vec![o.text.clone()];
                self.log.write(&o.text);
                let mut screen = Screen::new(
                    "undertone cannot use this file",
                    &[
                        "It is not an app image your pedal can start.",
                        "Nothing was changed on your pedal.",
                    ],
                )
                .choices(&[("again", "choose another file"), ("done", "done")])
                .problem();
                screen.aside = vec![e.message().to_string()];
                let key = self.view.ask(&screen);
                if key != "again" && key != "back" {
                    return None;
                }
                self.result = Result {
                    backup: self.result.backup.take(),
                    ..Result::default()
                };
                Some(State::OwnFile)
            }
        }
    }

    fn own_ready(&mut self) -> Option<State> {
        let custom = self.source.as_ref().is_some_and(|s| s.custom);
        let name = self
            .own
            .as_deref()
            .and_then(Path::file_name)
            .unwrap_or_default()
            .to_string_lossy();
        let kind = if custom {
            format!("This is a {CUSTOM}.")
        } else {
            "This file is the Gamut release.".into()
        };
        let mut screen = Screen::new("put your file on your pedal", &[kind.as_str(), nothing_changes()[1]])
            .choices(&[("go", "start the check"), ("back", "back")]);
        screen.aside = vec![name.into_owned()];
        let go = self.permission().unwrap_or(State::InstallCheck);
        self.choose(screen, &[("go", Some(go)), ("back", Some(State::OwnFile))])
    }

    fn hold(title: &str) -> Screen {
        Screen::new(
            title,
            &[
                "Switch your pedal off. Hold HOME, PUSH and the right",
                "footswitch, switch it on, and hold until it says RECOVERY.",
            ],
        )
        .pedal()
    }

    fn install_check(&mut self) -> Option<State> {
        let o = self.work(Self::hold("hold the three lit buttons"), Kind::Install, None);
        if o.code == 130 {
            return stopped(&o, State::Install);
        }
        if o.code != 0 {
            return self.failed(o, State::InstallCheck);
        }
        self.outcome = Some(o);
        let checked = "Your pedal is checked, and a copy is saved.";
        let screen = if self.own.is_some() {
            let custom = format!("Your file is a {CUSTOM}.");
            let mut lines = vec![checked];
            if self.source.as_ref().is_some_and(|s| s.custom) {
                lines.push(&custom);
            }
            Screen::new("ready to put your file on", &lines).choices(&[("go", "put it on"), ("later", "not now")])
        } else {
            Screen::new("ready to put gamut on", &[checked]).choices(&[("go", "put gamut on"), ("later", "not now")])
        };
        self.choose(
            screen,
            &[
                ("go", Some(State::Confirm)),
                ("later", Some(State::NotNow)),
                ("back", Some(State::Install)),
            ],
        )
    }

    fn install_write(&mut self) -> Option<State> {
        let yes = self.confirmed.take();
        let o = self.work(Self::hold("hold the three buttons again"), Kind::Install, yes);
        if o.code == 130 {
            return stopped(&o, State::Install);
        }
        if o.code != 0 {
            self.partial = true;
            return self.failed(o, State::Confirm);
        }
        let levels = o
            .report
            .as_ref()
            .and_then(|r| r.layout.as_ref())
            .map_or("", |l| l.levels.as_str());
        let first_run = undertone_protocol::install::FIRST_RUN.replace("{levels}", levels);
        if let Some(file) = &self.own {
            let custom = self.source.as_ref().is_some_and(|s| s.custom);
            let name = file.file_name().unwrap_or_default().to_string_lossy();
            self.result.lines = vec![
                format!(
                    "{name} is on your pedal{}. Everything put on it was checked.",
                    if custom { format!(" ({CUSTOM})") } else { String::new() }
                ),
                first_run,
            ];
            return self.end(Screen::new(
                "your file is on your pedal",
                &["Switch your pedal off and on again to start it."],
            ));
        }
        self.result.lines = vec![
            "Gamut is on your pedal. Everything put on it was checked.".into(),
            first_run,
        ];
        self.end(Screen::new(
            "gamut is on your pedal",
            &["Switch your pedal off and on again to start Gamut."],
        ))
    }

    fn check(&mut self) -> Option<State> {
        self.kind = Some("check");
        let screen = Screen::new(
            "check your pedal",
            &["Undertone reads your pedal and saves a copy.", "Nothing changes."],
        )
        .choices(&[("go", "start the check"), ("back", "back")]);
        let go = self.permission().unwrap_or(State::CheckWork);
        self.choose(screen, &[("go", Some(go)), ("back", Some(State::Menu))])
    }

    fn check_work(&mut self) -> Option<State> {
        let screen = if self.w.windows {
            Screen::new(
                "checking your pedal",
                &["Plug your pedal straight into this computer, with no hub."],
            )
        } else {
            Screen::new(
                "connect your pedal",
                &[
                    "Plug your pedal straight into this computer. If it starts,",
                    "switch it on holding HOME, PUSH and the right footswitch.",
                ],
            )
            .pedal()
        };
        let o = self.work(screen, Kind::Check, None);
        if o.code == 130 {
            return stopped(&o, State::Check);
        }
        if o.code != 0 {
            return self.failed(o, State::CheckWork);
        }
        let flash = o.flash.clone().unwrap_or_default();
        let r = read_pedal(&flash, &self.w.layouts);
        let ran = match r.path {
            'A' => "Your pedal ran M-VAVE V20 or older.",
            'B' => "Your pedal ran M-VAVE V22 or V23.",
            _ => "Undertone does not know this pedal.",
        };
        let now = match r.app.as_deref() {
            Some(app) if app.starts_with("an Undertone") => "It now runs Gamut.",
            Some("M-VAVE's own firmware") => "It now runs M-VAVE's own software.",
            _ => "It does not start. Start undertone again to fix it.",
        };
        self.result.lines = vec![
            format!("head: {}", r.family),
            format!("layout: {}", r.layout.as_deref().unwrap_or("not one undertone knows")),
            format!("app area: {}", r.app.as_deref().unwrap_or("unknown")),
        ];
        self.end(Screen::new(
            "your pedal is checked",
            &[ran, now, "A copy of your pedal is saved."],
        ))
    }

    /// A problem, in plain words; the tool's own line goes to the log and to the normal screen at the end.
    fn failed(&mut self, o: Outcome, again: State) -> Option<State> {
        self.result.code = o.code;
        self.result.lines = vec![o.text.clone()];
        let text = o.text.as_str();
        let lines = if text.contains("libusb not found") {
            [
                "This computer needs one small helper, libusb.",
                "The guide shows how to add it.",
            ]
        } else if o.code == 2 {
            [
                "A safety check stopped undertone before it changed anything.",
                "Your pedal is safe. Open the guide to see what to do.",
            ]
        } else if text.contains("gave up") {
            [
                "Your pedal kept restarting before undertone finished.",
                "Try again: it continues where it stopped.",
            ]
        } else if o.code == 3 || o.code == 5 {
            [
                "Your pedal did not get ready. Nothing was changed.",
                "Try again, holding HOME, PUSH and the right footswitch.",
            ]
        } else if text.contains("not found") || text.contains("CRC") || text.contains("not a") {
            [
                "An M-VAVE file in the kit is missing or damaged.",
                "Open the guide to see where to get it again.",
            ]
        } else {
            ["Nothing more was sent to your pedal.", "Try again, or open the guide."]
        };
        let screen = Screen::new("something went wrong", &lines)
            .choices(&[("again", "try again"), ("guide", "open the guide"), ("done", "done")])
            .problem();
        let key = self.view.ask(&screen);
        if key == "again" {
            self.result = Result {
                backup: self.result.backup.take(),
                ..Result::default()
            };
            return Some(again);
        }
        if key == "guide" {
            (self.w.open_url)(GUIDE);
        }
        None
    }

    fn end(&mut self, mut screen: Screen) -> Option<State> {
        screen.finished = !screen.problem;
        if let Some(b) = &self.result.backup {
            screen.aside = vec!["copy of your pedal:".into(), home_short(b)];
        }
        screen = screen.choices(&[("done", "done"), ("guide", "open the guide")]);
        loop {
            let key = self.view.ask(&screen);
            if key == "guide" {
                (self.w.open_url)(GUIDE);
                screen.lines.truncate(1);
                screen.lines.push("The guide is open in your browser.".into());
                continue;
            }
            return None;
        }
    }
}

/// The person left the wait for the pedal: q quits, Esc goes back.
fn stopped(o: &Outcome, back: State) -> Option<State> {
    if o.text == "quit" { None } else { Some(back) }
}

pub fn resume_note(kind: &str, backup: &Path) -> Vec<String> {
    vec![
        "Your pedal was being updated and may not start yet.".into(),
        format!("Plug it in and start undertone again (or run: undertone {kind}). It continues where it stopped."),
        format!("copy of your pedal: {}", backup.display()),
    ]
}

/// A path under the person's home folder as ~/..., as they would type it.
pub fn home_short(path: &Path) -> String {
    match path.strip_prefix(kit::user_home()) {
        Ok(rest) => format!("~/{}", rest.to_string_lossy().replace('\\', "/")),
        Err(_) => path.display().to_string(),
    }
}

/// A bus whose waits end when the stop flag is set, so that the screens can go back while it waits. Nothing has been
/// sent at those points.
struct Watch<'a> {
    inner: &'a mut (dyn Bus + Send),
    stop: Arc<AtomicBool>,
}

impl Watch<'_> {
    fn check(&self) -> std::result::Result<(), Error> {
        if self.stop.load(Ordering::SeqCst) {
            return Err(Error::Stopped(
                "stopped while waiting for the pedal; nothing was sent".into(),
            ));
        }
        Ok(())
    }
}

impl Bus for Watch<'_> {
    fn poll(&self) -> f64 {
        self.inner.poll()
    }

    fn clock(&self) -> Clock {
        self.inner.clock()
    }

    fn sleep(&mut self, seconds: f64) -> std::result::Result<(), Error> {
        self.check()?;
        self.inner.sleep(seconds)
    }

    fn open_uboot(&mut self) -> std::result::Result<Option<Box<dyn Msc>>, Error> {
        self.check()?;
        self.inner.open_uboot()
    }

    fn open_recovery(&mut self) -> std::result::Result<Option<Box<dyn RecoveryDevice>>, Error> {
        self.check()?;
        self.inner.open_recovery()
    }

    fn present(&mut self) -> std::result::Result<std::collections::BTreeSet<(u16, u16)>, Error> {
        self.inner.present()
    }
}
