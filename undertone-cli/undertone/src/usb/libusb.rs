// SPDX-License-Identifier: GPL-3.0-only
//! The pedal over libusb on macOS and Linux (tools/uboot_rescue.py's `Libusb` and `LibusbMsc`, tools/pd40_recovery.py's
//! `LibusbBus` and `LibusbRecovery`): the chip's USB boot state through its mass-storage interface, which macOS and
//! Linux keep for their own driver, so taking it needs root; M-VAVE's recovery mode through its vendor interface.
use std::collections::BTreeSet;
use std::sync::Arc;
use std::time::{Duration, Instant};

use rusb::{Context, Device, DeviceHandle, UsbContext};
use undertone_protocol::bot::{Bulk, BulkOnly, mass_storage_endpoints, vendor_endpoints};
use undertone_protocol::recovery::{self, REQUESTS, WATCHED};
use undertone_protocol::uboot;
use undertone_protocol::{Bus, Clock, Error, Msc, RecoveryDevice};

const SUDO_HINT: &str = "macOS keeps its mass-storage driver on the pedal and libusb needs root to take the \
                             interface: run the command again with sudo in front of it (docs/RESCUE.md)";
const ROOT_HINT: &str = "macOS did not let go of the pedal even for root. Nothing was sent to it; send this output to \
                         whoever helps you (the other routes are in docs/RESCUE.md)";

pub struct LibusbBus {
    ctx: Context,
    start: Instant,
}

impl LibusbBus {
    pub fn new() -> Result<LibusbBus, Error> {
        let ctx = Context::new().map_err(|e| Error::Setup(format!("libusb_init: {e}")))?;
        Ok(LibusbBus {
            ctx,
            start: Instant::now(),
        })
    }

    fn find(&self, (vid, pid): (u16, u16)) -> Option<Device<Context>> {
        let devices = self.ctx.devices().ok()?;
        devices.iter().find(|d| {
            d.device_descriptor()
                .is_ok_and(|desc| (desc.vendor_id(), desc.product_id()) == (vid, pid))
        })
    }
}

fn hint() -> &'static str {
    if crate::kit::as_root() { ROOT_HINT } else { SUDO_HINT }
}

fn refused_access(e: rusb::Error) -> bool {
    matches!(e, rusb::Error::Access | rusb::Error::Busy | rusb::Error::NotSupported)
}

/// The raw configuration descriptor, as the Python tools read it: GET_DESCRIPTOR (configuration 0), 512 bytes.
fn configuration(handle: &DeviceHandle<Context>) -> Option<Vec<u8>> {
    let mut buf = [0u8; 512];
    let n = handle
        .read_control(0x80, 6, 2 << 8, 0, &mut buf, Duration::from_millis(1000))
        .ok()?;
    (n >= 9).then(|| buf[..n].to_vec())
}

fn transfer_error(e: rusb::Error, what: &str) -> Error {
    match e {
        rusb::Error::NoDevice => Error::Gone("the pedal left the bus".into()),
        _ => Error::Transfer(format!("{what}: {e}")),
    }
}

impl Bus for LibusbBus {
    fn poll(&self) -> f64 {
        0.05
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
        let Some(device) = self.find((uboot::VID, uboot::PID)) else {
            return Ok(None);
        };
        let handle = match device.open() {
            Ok(h) => h,
            Err(e) if refused_access(e) => {
                return Err(Error::Setup(format!("cannot open the pedal ({e}). {}", hint())));
            }
            Err(_) => return Ok(None),
        };
        let Some(config) = configuration(&handle) else {
            return Ok(None);
        };
        let (iface, ep_in, ep_out) = mass_storage_endpoints(&config)?;
        let _ = handle.detach_kernel_driver(iface); // macOS: root (or an entitlement); other answers are fine here
        match handle.claim_interface(iface) {
            Ok(()) => Ok(Some(Box::new(BulkOnly::new(Claimed { handle, iface }, ep_in, ep_out)))),
            Err(e) if refused_access(e) => Err(Error::Setup(format!(
                "cannot take the interface from macOS ({e}). {}",
                hint()
            ))),
            Err(_) => Ok(None),
        }
    }

    fn open_recovery(&mut self) -> Result<Option<Box<dyn RecoveryDevice>>, Error> {
        let Some(device) = self.find(recovery::RECOVERY) else {
            return Ok(None);
        };
        let handle = device.open().map_err(|e| {
            Error::Setup(format!(
                "cannot open the recovery device ({e}). On Linux it needs a udev rule or root; on macOS send this \
                 output to whoever helps you"
            ))
        })?;
        let config = configuration(&handle)
            .ok_or_else(|| Error::Setup("the recovery device did not give its configuration".into()))?;
        let (iface, ep_in, ep_out) = vendor_endpoints(&config)?;
        handle.claim_interface(iface).map_err(|e| {
            Error::Setup(format!(
                "cannot claim the recovery device's interface ({e}). Another program may hold it; close it and run \
                 this again"
            ))
        })?;
        let desc = device
            .device_descriptor()
            .map_err(|e| Error::Setup(format!("the recovery device: {e}")))?;
        let string = |i: Option<u8>| {
            i.and_then(|i| handle.read_string_descriptor_ascii(i).ok())
                .unwrap_or_default()
        };
        let names = (
            string(desc.manufacturer_string_index()),
            string(desc.product_string_index()),
        );
        Ok(Some(Box::new(LibusbRecovery {
            claimed: Claimed { handle, iface },
            ep_in,
            ep_out,
            names,
        })))
    }

    fn present(&mut self) -> Result<BTreeSet<(u16, u16)>, Error> {
        let devices = self
            .ctx
            .devices()
            .map_err(|e| Error::Transfer(format!("USB listing: {e}")))?;
        Ok(devices
            .iter()
            .filter_map(|d| {
                d.device_descriptor()
                    .ok()
                    .map(|desc| (desc.vendor_id(), desc.product_id()))
            })
            .filter(|id| WATCHED.contains(id))
            .collect())
    }
}

/// A claimed interface, released when dropped.
struct Claimed {
    handle: DeviceHandle<Context>,
    iface: u8,
}

impl Drop for Claimed {
    fn drop(&mut self) {
        let _ = self.handle.release_interface(self.iface);
    }
}

impl Bulk for Claimed {
    fn write(&mut self, endpoint: u8, data: &[u8], timeout_ms: u32) -> Result<usize, Error> {
        let t = Duration::from_millis(timeout_ms.into());
        self.handle
            .write_bulk(endpoint, data, t)
            .map_err(|e| self.failed(endpoint, e))
    }

    fn read(&mut self, endpoint: u8, len: usize, timeout_ms: u32) -> Result<Vec<u8>, Error> {
        let mut buf = vec![0u8; len];
        let t = Duration::from_millis(timeout_ms.into());
        let n = self
            .handle
            .read_bulk(endpoint, &mut buf, t)
            .map_err(|e| self.failed(endpoint, e))?;
        buf.truncate(n);
        Ok(buf)
    }
}

impl Claimed {
    /// A failed transfer; a stalled endpoint is cleared first.
    fn failed(&self, endpoint: u8, e: rusb::Error) -> Error {
        if e == rusb::Error::Pipe {
            let _ = self.handle.clear_halt(endpoint);
        }
        transfer_error(e, "USB transfer")
    }
}

struct LibusbRecovery {
    claimed: Claimed,
    ep_in: u8,
    ep_out: u8,
    names: (String, String),
}

impl RecoveryDevice for LibusbRecovery {
    fn names(&self) -> (String, String) {
        self.names.clone()
    }

    fn control_in(&mut self, request: u8, len: usize) -> Result<Vec<u8>, Error> {
        if !REQUESTS.contains(&(request, len)) {
            return Err(Error::Refused(format!(
                "vendor request {request:#x} of {len} bytes is not one this tool sends"
            )));
        }
        let mut buf = vec![0u8; len];
        let h = &self.claimed.handle;
        let n = h
            .read_control(0xC1, request, 0, 0, &mut buf, Duration::from_millis(500))
            .map_err(|e| transfer_error(e, &format!("vendor request {request:#x}")))?;
        buf.truncate(n);
        Ok(buf)
    }

    fn bulk_out(&mut self, data: &[u8]) -> Result<(), Error> {
        let n = self
            .claimed
            .handle
            .write_bulk(self.ep_out, data, Duration::from_millis(1000))
            .map_err(|e| transfer_error(e, "frame"))?;
        if n != data.len() {
            return Err(Error::Transfer("the frame was not taken whole".into()));
        }
        Ok(())
    }

    fn bulk_in(&mut self, len: usize, timeout_ms: u32) -> Result<Option<Vec<u8>>, Error> {
        let mut buf = vec![0u8; len];
        match self
            .claimed
            .handle
            .read_bulk(self.ep_in, &mut buf, Duration::from_millis(timeout_ms.into()))
        {
            Ok(n) => {
                buf.truncate(n);
                Ok(Some(buf))
            }
            Err(rusb::Error::Timeout) => Ok(None),
            Err(e) => Err(transfer_error(e, "reply")),
        }
    }
}
