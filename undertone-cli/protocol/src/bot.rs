// SPDX-License-Identifier: GPL-3.0-only
//! USB mass storage's bulk-only transport, as tools/uboot_rescue.py's `LibusbMsc` sends it: a 31-byte command wrapper,
//! at most one data phase, a 13-byte status wrapper. Also the two interfaces the tools look for in a raw configuration
//! descriptor. The USB calls themselves are the program's (`Bulk`); this module only frames them.
use crate::{Error, Msc};

/// The bulk endpoints of one claimed interface. A stalled endpoint is cleared before the error is returned.
pub trait Bulk {
    /// One OUT transfer; the bytes taken.
    fn write(&mut self, endpoint: u8, data: &[u8], timeout_ms: u32) -> Result<usize, Error>;
    /// One IN transfer of at most `len` bytes.
    fn read(&mut self, endpoint: u8, len: usize, timeout_ms: u32) -> Result<Vec<u8>, Error>;
}

/// The command block wrapper (`uboot_rescue.cbw`).
pub fn cbw(tag: u32, cdb: &[u8], data_len: u32, data_in: bool) -> Vec<u8> {
    let mut w = b"USBC".to_vec();
    w.extend(tag.to_le_bytes());
    w.extend(data_len.to_le_bytes());
    w.push(if data_in { 0x80 } else { 0 });
    w.push(0);
    w.push(cdb.len() as u8);
    w.extend_from_slice(cdb);
    w.resize(31, 0);
    w
}

/// The command status wrapper's residue and status, checked against the tag (`uboot_rescue.parse_csw`).
pub fn parse_csw(raw: &[u8], tag: u32) -> Result<(u32, u8), Error> {
    let le = |o: usize| u32::from_le_bytes([raw[o], raw[o + 1], raw[o + 2], raw[o + 3]]);
    if raw.len() != 13 || &raw[..4] != b"USBS" || le(4) != tag {
        return Err(Error::Transfer("bad status wrapper".into()));
    }
    Ok((le(8), raw[12]))
}

/// A mass-storage device over its bulk endpoints.
pub struct BulkOnly<B> {
    pub bulk: B,
    ep_in: u8,
    ep_out: u8,
    tag: u32,
}

impl<B: Bulk> BulkOnly<B> {
    pub fn new(bulk: B, ep_in: u8, ep_out: u8) -> Self {
        BulkOnly {
            bulk,
            ep_in,
            ep_out,
            tag: 0,
        }
    }
}

impl<B: Bulk> Msc for BulkOnly<B> {
    fn execute(&mut self, cdb: &[u8], out: Option<&[u8]>, in_len: usize, timeout: u32) -> Result<Vec<u8>, Error> {
        self.tag = self.tag.wrapping_add(1);
        let data_len = out.map_or(in_len, <[u8]>::len) as u32;
        let wrapper = cbw(self.tag, cdb, data_len, out.is_none() && in_len > 0);
        self.bulk.write(self.ep_out, &wrapper, timeout)?;
        let mut data = vec![];
        let phase = match out {
            Some(o) => self.bulk.write(self.ep_out, o, timeout).map(drop),
            None if in_len > 0 => self.bulk.read(self.ep_in, in_len, timeout).map(|d| data = d),
            None => Ok(()),
        };
        let stalled = match phase {
            Ok(()) => false,
            Err(e @ Error::Gone(_)) => return Err(e),
            Err(_) => true,
        };
        let status = self
            .bulk
            .read(self.ep_in, 13, timeout)
            .and_then(|raw| parse_csw(&raw, self.tag))
            .map_err(|_| Error::Transfer("no status after the command".into()))?
            .1;
        if status != 0 || stalled {
            return Err(Error::Transfer("command failed".into()));
        }
        Ok(data)
    }
}

/// (interface, bulk in, bulk out) of the first interface whose class, subclass and protocol `wanted` accepts, with
/// exactly one bulk endpoint each way, in a raw configuration descriptor.
fn endpoints(config: &[u8], wanted: impl Fn(&[u8]) -> bool) -> Option<(u8, u8, u8)> {
    let (mut iface, mut ep_in, mut ep_out, mut i) = (None, None, None, 0);
    while i + 2 <= config.len() && config[i] != 0 {
        let d = &config[i..(i + config[i] as usize).min(config.len())];
        match d[1] {
            4 if d.len() >= 8 => {
                iface = wanted(&d[5..8]).then_some(d[2]);
                (ep_in, ep_out) = (None, None);
            }
            5 if iface.is_some() && d.len() >= 4 && d[3] & 3 == 2 => {
                if d[2] & 0x80 != 0 {
                    ep_in = Some(d[2])
                } else {
                    ep_out = Some(d[2])
                }
            }
            _ => {}
        }
        if let (Some(f), Some(i), Some(o)) = (iface, ep_in, ep_out) {
            return Some((f, i, o));
        }
        i += config[i] as usize;
    }
    None
}

/// The Mass Storage / SCSI / Bulk-Only interface of the chip's USB boot state (`uboot_rescue.mass_storage_endpoints`).
pub fn mass_storage_endpoints(config: &[u8]) -> Result<(u8, u8, u8), Error> {
    endpoints(config, |c| c == [8, 6, 0x50])
        .ok_or_else(|| Error::Setup("no Mass Storage Bulk-Only interface found on the device".into()))
}

/// The vendor-specific interface of M-VAVE's recovery mode (`pd40_recovery.vendor_endpoints`).
pub fn vendor_endpoints(config: &[u8]) -> Result<(u8, u8, u8), Error> {
    endpoints(config, |c| c[0] == 0xFF)
        .ok_or_else(|| Error::Setup("no vendor interface with two bulk endpoints on the recovery device".into()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_command_wrapper_is_the_python_tools_bytes() {
        // uboot_rescue.cbw(7, bytes.fromhex("fd05000000000200"), 512, True).hex()
        let w = cbw(7, &[0xFD, 0x05, 0, 0, 0, 0, 2, 0], 512, true);
        assert_eq!(
            crate::uboot::hex(&w),
            "555342430700000000020000800008fd050000000002000000000000000000"
        );
        assert_eq!(w.len(), 31);
    }

    #[test]
    fn the_status_wrapper_is_checked() {
        let ok = [b"USBS".as_slice(), &7u32.to_le_bytes(), &0u32.to_le_bytes(), &[0]].concat();
        assert_eq!(parse_csw(&ok, 7), Ok((0, 0)));
        assert!(parse_csw(&ok, 8).is_err());
        assert!(parse_csw(&ok[..12], 7).is_err());
    }

    /// A configuration with a HID interface first, then mass storage with its two bulk endpoints.
    const CONFIG: [u8; 41] = [
        9, 2, 41, 0, 2, 1, 0, 0x80, 50, // configuration
        9, 4, 0, 0, 1, 3, 0, 0, 0, // interface 0: HID
        7, 5, 0x83, 3, 8, 0, 10, // its interrupt endpoint
        9, 4, 1, 0, 2, 8, 6, 0x50, 0, // interface 1: mass storage, SCSI, bulk-only
        7, 5, 0x81, 2, 64, 0, 0, // bulk in
    ];

    #[test]
    fn the_interfaces_are_found_as_python_finds_them() {
        let mut config = CONFIG.to_vec();
        assert!(
            mass_storage_endpoints(&config).is_err(),
            "only one bulk endpoint so far"
        );
        config.extend([7, 5, 0x02, 2, 64, 0, 0]);
        assert_eq!(mass_storage_endpoints(&config), Ok((1, 0x81, 0x02)));
        assert!(vendor_endpoints(&config).is_err());
    }
}
