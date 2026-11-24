// SPDX-License-Identifier: GPL-3.0-only
//! The pedal on Windows (tools/uboot_rescue.py's `WinDisks` and `WinScsi`). Windows keeps its own mass-storage driver
//! on the chip's USB boot state, as macOS does, but lets an administrator send any SCSI command through it
//! (IOCTL_SCSI_PASS_THROUGH_DIRECT): no libusb, no Zadig, no driver change. The pedal is the disk or drive letter that
//! answers INQUIRY as WL82 UBOOT1.00; INQUIRY only reads, so asking the other disks changes nothing. M-VAVE's recovery
//! mode is not reached on Windows, as in the Python tool. The calls into Windows are this program's only unsafe code.
#![allow(unsafe_code)]

use std::collections::BTreeSet;
use std::ffi::c_void;
use std::sync::Arc;
use std::time::{Duration, Instant};

use undertone_protocol::uboot::Uboot;
use undertone_protocol::{Bus, Clock, Error, Msc, RecoveryDevice};
use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, HANDLE, INVALID_HANDLE_VALUE};
use windows_sys::Win32::Storage::FileSystem::{CreateFileW, FILE_SHARE_READ, FILE_SHARE_WRITE, OPEN_EXISTING};
use windows_sys::Win32::Storage::IscsiDisc::{
    IOCTL_SCSI_PASS_THROUGH_DIRECT, SCSI_IOCTL_DATA_IN, SCSI_IOCTL_DATA_OUT, SCSI_IOCTL_DATA_UNSPECIFIED,
    SCSI_PASS_THROUGH_DIRECT,
};
use windows_sys::Win32::System::IO::DeviceIoControl;
use windows_sys::Win32::UI::Shell::IsUserAnAdmin;

pub const ADMIN_HINT: &str = "Windows lets only an administrator send these commands to the pedal: open a Command \
                              Prompt as administrator (right-click Start, Terminal (Admin)) and run undertone there \
                              (docs/RESCUE.md)";
/// Windows errors that mean the pedal left the bus: file or path not found, not ready, no such device, not connected.
const GONE: [u32; 5] = [2, 3, 21, 433, 1167];
const GENERIC_READ_WRITE: u32 = 0xC000_0000;

pub fn is_admin() -> bool {
    // SAFETY: IsUserAnAdmin takes no arguments and only reads the process token.
    unsafe { IsUserAnAdmin() != 0 }
}

fn paths() -> Vec<String> {
    (0..32)
        .map(|i| format!(r"\\.\PhysicalDrive{i}"))
        .chain(('A'..='Z').map(|c| format!(r"\\.\{c}:")))
        .chain((1..64).map(|i| format!(r"\\.\HarddiskVolume{i}")))
        .collect()
}

pub struct WinDisks {
    start: Instant,
}

impl WinDisks {
    pub fn new() -> Result<WinDisks, Error> {
        if !is_admin() {
            return Err(Error::Setup(ADMIN_HINT.into()));
        }
        Ok(WinDisks { start: Instant::now() })
    }
}

impl Bus for WinDisks {
    fn poll(&self) -> f64 {
        0.25
    }

    fn clock(&self) -> Clock {
        let start = self.start;
        Arc::new(move || start.elapsed().as_secs_f64())
    }

    fn sleep(&mut self, seconds: f64) -> Result<(), Error> {
        std::thread::sleep(Duration::from_secs_f64(seconds));
        Ok(())
    }

    fn open_uboot(&mut self) -> Result<Option<Box<dyn Msc>>, Error> {
        for path in paths() {
            let Some(mut disk) = WinScsi::open(&path) else {
                continue; // no such disk, or one Windows keeps to itself
            };
            if let Ok((vendor, product, _)) = Uboot::new(&mut disk).inquiry()
                && vendor == "WL82"
                && product.starts_with("UBOOT")
            {
                return Ok(Some(Box::new(disk)));
            }
        }
        Ok(None)
    }

    fn open_recovery(&mut self) -> Result<Option<Box<dyn RecoveryDevice>>, Error> {
        Ok(None)
    }

    fn present(&mut self) -> Result<BTreeSet<(u16, u16)>, Error> {
        Ok(BTreeSet::new())
    }
}

/// One opened disk or volume.
struct WinScsi {
    handle: HANDLE,
}

impl WinScsi {
    fn open(path: &str) -> Option<WinScsi> {
        let wide: Vec<u16> = path.encode_utf16().chain([0]).collect();
        // SAFETY: `wide` is a NUL-terminated UTF-16 path that lives across the call; the other arguments are plain
        // values or null, as CreateFileW allows.
        let handle = unsafe {
            CreateFileW(
                wide.as_ptr(),
                GENERIC_READ_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                std::ptr::null(),
                OPEN_EXISTING,
                0,
                std::ptr::null_mut(),
            )
        };
        (!handle.is_null() && handle != INVALID_HANDLE_VALUE).then_some(WinScsi { handle })
    }
}

impl Drop for WinScsi {
    fn drop(&mut self) {
        // SAFETY: the handle came from CreateFileW and is closed once, here.
        unsafe { CloseHandle(self.handle) };
    }
}

impl Msc for WinScsi {
    fn execute(&mut self, cdb: &[u8], out: Option<&[u8]>, in_len: usize, timeout: u32) -> Result<Vec<u8>, Error> {
        let mut buf: Vec<u8> = out.map_or_else(|| vec![0u8; in_len], <[u8]>::to_vec);
        let mut s = SCSI_PASS_THROUGH_DIRECT {
            Length: size_of::<SCSI_PASS_THROUGH_DIRECT>() as u16,
            TargetId: 1,
            CdbLength: cdb.len() as u8,
            TimeOutValue: timeout.div_ceil(1000).max(1),
            ..Default::default()
        };
        s.Cdb[..cdb.len()].copy_from_slice(cdb);
        (s.DataIn, s.DataTransferLength) = match out {
            Some(o) => (SCSI_IOCTL_DATA_OUT as u8, o.len() as u32),
            None if in_len > 0 => (SCSI_IOCTL_DATA_IN as u8, in_len as u32),
            None => (SCSI_IOCTL_DATA_UNSPECIFIED as u8, 0),
        };
        s.DataBuffer = if buf.is_empty() {
            std::ptr::null_mut()
        } else {
            buf.as_mut_ptr().cast::<c_void>()
        };
        let size = size_of::<SCSI_PASS_THROUGH_DIRECT>() as u32;
        let mut returned = 0u32;
        let sp = (&raw mut s).cast::<c_void>();
        // SAFETY: `s` is a valid SCSI_PASS_THROUGH_DIRECT used as both the in and out buffer, as the IOCTL requires;
        // its DataBuffer points into `buf`, which is DataTransferLength bytes long and outlives the call; the call is
        // synchronous (no OVERLAPPED).
        let ok = unsafe {
            DeviceIoControl(
                self.handle,
                IOCTL_SCSI_PASS_THROUGH_DIRECT,
                sp,
                size,
                sp,
                size,
                &mut returned,
                std::ptr::null_mut(),
            )
        };
        if ok == 0 {
            // SAFETY: reads the calling thread's last error, set by the failed call just before.
            let err = unsafe { GetLastError() };
            if GONE.contains(&err) {
                return Err(Error::Gone("the pedal left the bus".into()));
            }
            return Err(Error::Transfer(format!("SCSI pass-through: Windows error {err}")));
        }
        if s.ScsiStatus != 0 {
            return Err(Error::Transfer("command failed".into()));
        }
        if out.is_none() && in_len > 0 {
            buf.truncate(s.DataTransferLength as usize);
            return Ok(buf);
        }
        Ok(vec![])
    }
}
