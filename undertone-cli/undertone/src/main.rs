// SPDX-License-Identifier: GPL-3.0-only
//! undertone as one program: rescue a pedal that will not start, put Gamut on a pedal, or check what a pedal holds, over
//! its USB cable (tools/undertone.py). Nothing is written before the person types yes, and every run saves a backup of
//! the whole flash first. On macOS and Linux the pedal is reached as root: in a terminal undertone asks for the password
//! itself, through sudo. On Windows it runs as an administrator. The guided screens follow in a later build.
//! Exit codes: 0 done, 1 a setup problem or a failed transfer, 2 refused by a check, 3 and 5 after the recovery mode's
//! leave, 4 the write was not confirmed (nothing was written), 130 stopped.
use std::io::{BufRead, Write};
use std::path::PathBuf;
use std::process::ExitCode;

use clap::{Args, Parser, Subcommand};
use undertone_protocol::exit;

mod commands;
mod kit;
mod run;
#[cfg(test)]
mod tests;
mod usb;

use commands::{Ctx, InstallFrom, Out};

#[derive(Parser)]
#[command(name = "undertone", about = "Rescue, install or check a BlackBox over USB.",
          after_help = format!("The guide: {}", kit::GUIDE), disable_version_flag = true)]
struct Cli {
    /// print the version and exit
    #[arg(long)]
    version: bool,
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Subcommand)]
enum Command {
    /// restore M-VAVE's firmware on a pedal that will not start: a check, then the restore
    Rescue {
        /// M-VAVE's official .fwsc (default: the matching file in the firmware folder)
        #[arg(long, conflicts_with = "image")]
        package: Option<PathBuf>,
        /// a raw flash image (flash.bin) instead of a package
        #[arg(long)]
        image: Option<PathBuf>,
        #[command(flatten)]
        common: Common,
    },
    /// put Gamut, M-VAVE's firmware or a backup on a pedal: a dry run, then the write
    Install {
        /// Gamut's app area (default: the file the release pin names)
        #[arg(long, value_name = "FILE", conflicts_with_all = ["official", "restore"])]
        gamut: Option<PathBuf>,
        /// M-VAVE's official package: its app area, the way back
        #[arg(long, value_name = "FILE.fwsc", conflicts_with = "restore")]
        official: Option<PathBuf>,
        /// a whole-flash backup of this pedal: its app area
        #[arg(long, value_name = "DUMP.bin")]
        restore: Option<PathBuf>,
        #[command(flatten)]
        common: Common,
    },
    /// read-only: how the pedal was found, what it had; saves a backup
    Check {
        #[command(flatten)]
        common: Common,
    },
    /// print the version
    Version,
}

#[derive(Args)]
struct Common {
    /// wl82loader.bin (default: downloaded once and checked)
    #[arg(long)]
    loader: Option<PathBuf>,
    /// where backups go (default ~/OpenPocket-rescue)
    #[arg(long)]
    backup_dir: Option<PathBuf>,
    /// USB boot state windows to try
    #[arg(long, default_value_t = 10)]
    attempts: u32,
}

#[cfg(not(windows))]
const SUDO: &str = "talking to the pedal over USB needs root on macOS and Linux: the system keeps the pedal's USB disk \
                    for itself. Run it again with sudo in front (sudo ./undertone ...); nothing was sent to the pedal";
#[cfg(windows)]
const ADMIN: &str = "Windows lets only an administrator send these commands to the pedal: press the Windows key, type \
                     cmd, right-click Command Prompt, choose Run as administrator, go to this folder and run undertone \
                     there; nothing was sent to the pedal";

/// None when this process may reach the pedal, else what to do, in words.
fn permission_problem() -> Option<&'static str> {
    #[cfg(not(windows))]
    return (!kit::as_root()).then_some(SUDO);
    #[cfg(windows)]
    return (!usb::is_admin()).then_some(ADMIN);
}

/// May this process reach the pedal? In a terminal on macOS and Linux it starts itself again under sudo, which asks
/// for the password.
fn allowed(out: &mut Out) -> bool {
    let Some(problem) = permission_problem() else {
        return true;
    };
    #[cfg(not(windows))]
    if std::io::IsTerminal::is_terminal(&std::io::stdin()) && std::io::IsTerminal::is_terminal(&std::io::stdout()) {
        use std::os::unix::process::CommandExt;
        out.line(
            "This needs your computer password: the system keeps the pedal's USB disk for itself, and only an \
             administrator may take it. Nothing shows while you type.",
        );
        let exe = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("undertone"));
        let err = std::process::Command::new("sudo")
            .arg(exe)
            .args(std::env::args_os().skip(1))
            .exec();
        out.line(&format!("ERROR: could not start sudo ({err})"));
    }
    out.line(&format!("ERROR: {problem}"));
    false
}

fn read_line(prompt: &str) -> Option<String> {
    print!("{prompt}");
    let _ = std::io::stdout().flush();
    let mut line = String::new();
    match std::io::stdin().lock().read_line(&mut line) {
        Ok(0) | Err(_) => None,
        Ok(_) => Some(line),
    }
}

fn code(c: i32) -> ExitCode {
    ExitCode::from(c.clamp(0, 255) as u8)
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    if cli.version || matches!(cli.command, Some(Command::Version)) {
        println!("undertone, rescue kit {}", kit::version());
        return code(exit::DONE);
    }
    let Some(command) = cli.command else {
        eprintln!(
            "This build has no guided screens yet: run `undertone rescue`, `undertone install` or `undertone check`, \
             or the undertone of the rescue kit. Nothing was sent to the pedal."
        );
        return code(exit::FAILED);
    };
    let mut out = Out::stdout();
    if !allowed(&mut out) {
        return code(exit::FAILED);
    }
    let (Command::Rescue { common, .. } | Command::Install { common, .. } | Command::Check { common }) = &command
    else {
        unreachable!("version is answered above")
    };
    let mut bus = match usb::bus() {
        Ok(bus) => bus,
        Err(e) => {
            out.line(&format!("{e}"));
            return code(e.exit_code());
        }
    };
    let loader_path = common.loader.clone();
    let loader = move || kit::loader(loader_path.as_deref());
    let mut reader = read_line;
    let mut ctx = Ctx {
        root: kit::root(),
        out: &mut out,
        reader: &mut reader,
        bus: bus.as_mut(),
        loader: &loader,
        backups: common.backup_dir.clone().unwrap_or_else(kit::default_backups),
        attempts: common.attempts,
        layouts: undertone_protocol::install::layouts(),
        heads: undertone_protocol::install::HEADS.to_vec(),
        windows: cfg!(windows),
    };
    code(match &command {
        Command::Rescue { package, image, .. } => commands::cmd_rescue(&mut ctx, package.as_deref(), image.as_deref()),
        Command::Install {
            gamut,
            official,
            restore,
            ..
        } => {
            let from = match (official, restore) {
                (Some(p), _) => InstallFrom::Official(p),
                (_, Some(p)) => InstallFrom::Restore(p),
                _ => InstallFrom::Gamut(gamut.as_deref()),
            };
            commands::cmd_install(&mut ctx, from)
        }
        Command::Check { .. } => commands::cmd_check(&mut ctx),
        Command::Version => exit::DONE,
    })
}
