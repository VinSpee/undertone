// SPDX-License-Identifier: GPL-3.0-only
//! The pedal's USB protocols as the Python tools speak them: the chip's USB boot state (tools/uboot_rescue.py), the
//! install plan for both flash layouts (tools/uboot_install.py) and M-VAVE's recovery mode (tools/pd40_recovery.py).
//! This crate holds no USB code. Every transfer goes through the two traits below, so the same code runs against a real
//! pedal and against the simulated one of the tests. DESIGN.md lists what is ported and the rules it keeps.
#![forbid(unsafe_code)]

use std::fmt;

/// A failure, sorted as the Python tools sort their exceptions. Each kind ends the program with one exit code.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error {
    /// A safety check refused to go on (`GuardError`). Nothing more is sent to the pedal.
    Refused(String),
    /// A setup problem: no access to the pedal, a missing or damaged file, no loader (`RescueError`).
    Setup(String),
    /// A transfer failed; the pedal may answer again after it restarts (`ScsiError`).
    Transfer(String),
    /// The pedal left the bus, usually because it restarted (`DeviceGone`).
    Gone(String),
}

impl Error {
    /// The exit code of the Python tools for this failure: 2 refused, 1 for everything else.
    pub fn exit_code(&self) -> i32 {
        match self {
            Error::Refused(_) => exit::REFUSED,
            Error::Setup(_) | Error::Transfer(_) | Error::Gone(_) => exit::FAILED,
        }
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Refused(m) => write!(f, "REFUSED: {m}"),
            Error::Setup(m) | Error::Transfer(m) | Error::Gone(m) => write!(f, "ERROR: {m}"),
        }
    }
}

impl std::error::Error for Error {}

/// The exit codes of tools/undertone.py and tools/uboot_install.py.
pub mod exit {
    pub const DONE: i32 = 0;
    /// A setup problem or a failed transfer.
    pub const FAILED: i32 = 1;
    /// Refused by a check; nothing more was sent.
    pub const REFUSED: i32 = 2;
    /// The pedal left the recovery mode after the leave, but the chip's USB boot state did not appear.
    pub const NO_BOOT_STATE: i32 = 3;
    /// The write was not confirmed; nothing was written.
    pub const NOT_CONFIRMED: i32 = 4;
    /// The pedal stayed in the recovery mode after the leave.
    pub const STAYED_IN_RECOVERY: i32 = 5;
    /// Stopped by the person (Ctrl-C, or leaving the wait for the pedal).
    pub const STOPPED: i32 = 130;
}

/// The chip's USB boot state (USB 4C4A:8057) as a mass-storage device: one SCSI command, with at most one data phase.
/// `out` is sent after the command; otherwise `in_len` bytes are read back. tools/uboot_rescue.py's
/// `msc.execute(cdb, out, in_len, timeout_ms)`, which libusb's bulk-only transport and Windows' SCSI pass-through both
/// provide.
pub trait Msc {
    fn execute(&mut self, cdb: &[u8], out: Option<&[u8]>, in_len: usize, timeout_ms: u32) -> Result<Vec<u8>, Error>;
}

/// The vendor interface of M-VAVE's recovery mode (USB 3654:7940): tools/pd40_recovery.py's `dev`.
pub trait RecoveryDevice {
    /// A vendor IN request (0xC1) with wValue and wIndex 0.
    fn control_in(&mut self, request: u8, len: usize) -> Result<Vec<u8>, Error>;
    /// One bulk OUT transfer, never followed by a zero-length packet.
    fn bulk_out(&mut self, data: &[u8]) -> Result<(), Error>;
    /// One bulk IN read; `None` when nothing came within `timeout_ms`.
    fn bulk_in(&mut self, len: usize, timeout_ms: u32) -> Result<Option<Vec<u8>>, Error>;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn errors_end_with_the_python_tools_exit_codes() {
        assert_eq!(Error::Refused("x".into()).exit_code(), 2);
        assert_eq!(Error::Setup("x".into()).exit_code(), 1);
        assert_eq!(Error::Transfer("x".into()).exit_code(), 1);
        assert_eq!(Error::Gone("x".into()).exit_code(), 1);
    }

    #[test]
    fn errors_read_as_the_python_tools_closing_lines() {
        assert_eq!(
            Error::Refused("chip key 0x1234 is not 0x980f".into()).to_string(),
            "REFUSED: chip key 0x1234 is not 0x980f"
        );
        assert_eq!(
            Error::Setup("libusb not found".into()).to_string(),
            "ERROR: libusb not found"
        );
    }
}
