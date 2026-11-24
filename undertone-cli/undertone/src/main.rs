// SPDX-License-Identifier: GPL-3.0-only
//! undertone as one program: the commands of tools/undertone.py, and with no command its guided screens. This first
//! build only answers `version`; the protocol, the commands and the screens follow (DESIGN.md, "Stages"). Until then it
//! sends nothing to a pedal.
use std::process::ExitCode;

use clap::{Parser, Subcommand};
use undertone_protocol::exit;

const KIT: &str = include_str!("../../../rescue/VERSION");
const GUIDE: &str = "https://github.com/VinSpee/undertone/blob/main/docs/RESCUE.md";
const NOT_YET: &str = "this build of undertone cannot reach a pedal yet: use the undertone of the rescue kit \
                       (docs/RESCUE.md). Nothing was sent to the pedal";

#[derive(Parser)]
#[command(name = "undertone", about = "Rescue, install or check a BlackBox over USB.",
          after_help = format!("The guide: {GUIDE}"), disable_version_flag = true)]
struct Cli {
    /// print the version and exit
    #[arg(long)]
    version: bool,
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Subcommand)]
enum Command {
    /// print the version
    Version,
}

/// How this program reaches the pedal, in words.
fn usb() -> String {
    #[cfg(not(windows))]
    {
        let v = rusb::version();
        format!("libusb {}.{}.{}, built in", v.major(), v.minor(), v.micro())
    }
    #[cfg(windows)]
    {
        "Windows' own mass-storage driver (SCSI pass-through)".to_string()
    }
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    if cli.version || matches!(cli.command, Some(Command::Version)) {
        println!("undertone, rescue kit {}", KIT.trim());
        println!("usb: {}", usb());
        return ExitCode::from(exit::DONE as u8);
    }
    eprintln!("ERROR: {NOT_YET}");
    ExitCode::from(exit::FAILED as u8)
}
