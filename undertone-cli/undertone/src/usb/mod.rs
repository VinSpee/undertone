// SPDX-License-Identifier: GPL-3.0-only
//! This computer's way to the pedal: Windows' own mass-storage driver through SCSI pass-through, else libusb.
#[cfg(not(windows))]
mod libusb;
#[cfg(windows)]
mod windows;

use undertone_protocol::{Bus, Error};

#[cfg(windows)]
pub use windows::is_admin;

/// The bus, opened. On macOS the boot state's interface needs root; undertone asks for it before any run.
pub fn bus() -> Result<Box<dyn Bus>, Error> {
    #[cfg(not(windows))]
    return Ok(Box::new(libusb::LibusbBus::new()?));
    #[cfg(windows)]
    return Ok(Box::new(windows::WinDisks::new()?));
}
