// SPDX-License-Identifier: GPL-3.0-only
//! The pedal's firmware files, read as tools/pocketx_fw.py reads them: an official .fwsc package and its CRCs, the flash
//! head's entries, the app area; and the checks of an app area on its own (`pd40_install.check_area`).
use crate::Error;
use crate::crc::{crc16, enc, sfc};

/// Why a file could not be read as a package (Python's ValueError, IndexError or struct.error).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Unreadable(pub String);

fn short(what: &str) -> Unreadable {
    Unreadable(format!("{what} is cut short"))
}

fn le16(b: &[u8], o: usize) -> u16 {
    u16::from_le_bytes([b[o], b[o + 1]])
}

fn le32(b: &[u8], o: usize) -> u32 {
    u32::from_le_bytes([b[o], b[o + 1], b[o + 2], b[o + 3]])
}

/// `data[from..to]` clamped to the data, as a Python slice is.
pub(crate) fn slice(data: &[u8], from: usize, to: usize) -> &[u8] {
    let to = to.min(data.len());
    &data[from.min(to)..to]
}

/// One 32-byte JLFS entry of the flash head or of the app area.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Entry {
    pub hcrc: u16,
    pub dcrc: u16,
    pub addr: u32,
    pub len: u32,
    pub attr: u8,
    pub name: String,
    pub hdr_ok: bool,
}

/// `pocketx_fw.jlfs_entry`: the entry at `o` of decrypted bytes.
pub fn entry(dec: &[u8], o: usize) -> Result<Entry, Unreadable> {
    let e = dec.get(o..o + 32).ok_or_else(|| short("a JLFS entry"))?;
    let raw = &e[16..32];
    let name = raw.split(|&b| b == 0).next().unwrap_or(&[]);
    let name = name.split(|&b| b == 0xFF).next().unwrap_or(&[]);
    Ok(Entry {
        hcrc: le16(e, 0),
        dcrc: le16(e, 2),
        addr: le32(e, 4),
        len: le32(e, 8),
        attr: e[12],
        name: name.iter().map(|&b| b as char).collect(),
        hdr_ok: crc16(&e[2..32], 0) == le16(e, 0),
    })
}

/// Python's `str.isprintable` for a name decoded as Latin-1.
fn printable(name: &str) -> bool {
    name.chars()
        .all(|c| matches!(c as u32, 0x20..=0x7E | 0xA1..=0xAC | 0xAE..=0xFF))
}

/// `pocketx_fw.app_base`: where the app area starts, the address the head's `app_dir_head` entry names.
pub fn app_base(flash: &[u8]) -> Result<usize, Unreadable> {
    let mut o = 0x20;
    while o + 32 <= flash.len() {
        let e = entry(&enc(&flash[o..o + 32], 0xFFFF), 0)?;
        if !e.hdr_ok {
            break;
        }
        if e.name == "app_dir_head" {
            let addr = e.addr as usize;
            if !addr.is_multiple_of(0x1000) || addr + 0x120 > flash.len() {
                return Err(Unreadable(format!(
                    "app_dir_head at {addr:#x} is not a sector inside the {:#x}-byte flash",
                    flash.len()
                )));
            }
            return Ok(addr);
        }
        o += 32;
    }
    Err(Unreadable("no app_dir_head entry in the flash head".into()))
}

/// The app area's head and the entries after it, up to the first without a printable name (`pocketx_fw.flash_parse`,
/// and the same walk in `pd40_install.check_area`); offsets are from the area's start.
fn area_entries(area: &[u8]) -> Result<Vec<Entry>, Unreadable> {
    let mut ents = vec![entry(area, 0)?];
    let mut o = 0x20;
    while o < 0x120 {
        let e = entry(area, o)?;
        if e.name.is_empty() || !printable(&e.name) {
            break;
        }
        ents.push(e);
        o += 32;
    }
    Ok(ents)
}

/// The entries after the area head that hold file data in the area (`pocketx_fw.area_files`): regions (attr bit 0x10)
/// are addressed from the start of the flash, and the V22 and V23 VM region carries a CRC for data outside the package.
fn is_file(e: &Entry) -> bool {
    e.dcrc != 0xFFFF && e.attr & 0x10 == 0
}

/// Named checks, in the order Python's dict keeps them.
#[derive(Debug, Default)]
pub struct Checks(Vec<(String, bool)>);

impl Checks {
    fn set(&mut self, name: String, ok: bool) {
        match self.0.iter_mut().find(|(n, _)| *n == name) {
            Some(c) => c.1 = ok,
            None => self.0.push((name, ok)),
        }
    }

    /// Every check, in order, with whether it passed.
    pub fn all(&self) -> impl Iterator<Item = (&str, bool)> {
        self.0.iter().map(|(n, ok)| (n.as_str(), *ok))
    }

    /// The names of the checks that failed.
    pub fn failed(&self) -> Vec<&str> {
        self.0.iter().filter(|(_, ok)| !ok).map(|(n, _)| n.as_str()).collect()
    }
}

/// `pocketx_fw.flash_checks` on a decrypted flash.
fn flash_checks(dec: &[u8], checks: &mut Checks) -> Result<(), Unreadable> {
    let base = app_base(dec)?;
    let ents = area_entries(dec.get(base..).ok_or_else(|| short("the app area"))?)?;
    let head = &ents[0];
    checks.set("app_area_head entry crc".into(), head.hdr_ok);
    let data = slice(dec, base + 0x20, base + head.len as usize);
    checks.set("app_area_head data crc".into(), crc16(data, 0) == head.dcrc);
    for e in &ents[1..] {
        checks.set(format!("{} entry crc", e.name), e.hdr_ok);
        if is_file(e) {
            let at = base + e.addr as usize;
            let data = slice(dec, at, at + e.len as usize);
            checks.set(format!("{} data crc", e.name), crc16(data, 0) == e.dcrc);
        }
    }
    Ok(())
}

/// One entry of a package's UFW list.
#[derive(Debug, Clone)]
pub struct UfwEntry {
    pub crc: u16,
    pub off: usize,
    pub len: usize,
    pub name: String,
}

/// An official or OpenPocket .fwsc package (`pocketx_fw.load`): its logical UFW image, its identity and its list.
#[derive(Debug, Clone)]
pub struct Package {
    pub logical: Vec<u8>,
    pub tag: String,
    hdr: Vec<u8>,
    hcrc: u16,
    lcrc: u16,
    count: usize,
    pub entries: Vec<UfwEntry>,
}

const NSLOT: usize = 20;
const UNUSED: u8 = 0x7D;

impl Package {
    /// The .fwsc file's bytes, read: the 20 identity markers taken out, the header and list decrypted.
    pub fn read(raw: &[u8]) -> Result<Package, Unreadable> {
        if raw.len() < NSLOT * 0x30 {
            return Err(short("the package"));
        }
        let (mut logical, mut tag) = (Vec::with_capacity(raw.len()), String::new());
        for i in 0..NSLOT {
            logical.extend_from_slice(&raw[i * 0x30..i * 0x30 + 0x2F]);
            let m = raw[i * 0x30 + 0x2F];
            if m != UNUSED {
                tag.push(m.wrapping_sub(i as u8 + 1) as char);
            }
        }
        logical.extend_from_slice(&raw[NSLOT * 0x30..]);
        let hdr = enc(logical.get(..0x40).ok_or_else(|| short("the UFW header"))?, 0xFFFF);
        let count = le16(&hdr, 8) as usize;
        let mut entries = Vec::with_capacity(count);
        for i in 0..count {
            let o = 0x40 + i * 0x50;
            let e = enc(logical.get(o..o + 0x50).ok_or_else(|| short("the UFW list"))?, 0xFFFF);
            let name = e[0x40..0x50].split(|&b| b == 0).next().unwrap_or(&[]);
            let name =
                String::from_utf8(name.to_vec()).map_err(|_| Unreadable("an entry's name is not UTF-8".into()))?;
            entries.push(UfwEntry {
                crc: le16(&e, 4),
                off: le32(&e, 8) as usize,
                len: le32(&e, 12) as usize,
                name,
            });
        }
        Ok(Package {
            hcrc: le16(&hdr, 0),
            lcrc: le16(&hdr, 2),
            hdr,
            count,
            logical,
            tag,
            entries,
        })
    }

    /// The bytes of the entry `name`, cut to the image as Python slices them.
    pub fn file(&self, name: &str) -> Option<&[u8]> {
        let e = self.entries.iter().find(|e| e.name == name)?;
        Some(slice(&self.logical, e.off, e.off + e.len))
    }

    /// Every CRC of the package (`pocketx_fw.package_checks`): the UFW header and list, flash.bin and its entries,
    /// ota.bin and tail.bin.
    pub fn checks(&self) -> Checks {
        let mut ok = Checks::default();
        ok.set("ufw header crc".into(), crc16(&self.hdr[2..0x40], 0) == self.hcrc);
        let list = slice(&self.logical, 0x40, 0x40 + self.count * 0x50);
        ok.set("ufw list crc".into(), crc16(list, 0) == self.lcrc);
        for e in &self.entries {
            let d = slice(&self.logical, e.off, e.off + e.len);
            if e.name == "flash.bin" {
                ok.set("flash.bin crc".into(), crc16(d, 0) == e.crc);
                let decrypted = app_base(d).map(|base| [&d[..base], &sfc(&d[base..], 0)[..]].concat());
                if let Err(Unreadable(why)) = decrypted.and_then(|dec| flash_checks(&dec, &mut ok)) {
                    ok.set(why, false);
                }
            }
            if e.name == "ota.bin" || e.name == "tail.bin" {
                ok.set(format!("{} crc", e.name), crc16(d, 0) == e.crc);
            }
        }
        ok
    }
}

/// The entry address every BlackBox app area starts at.
pub const ENTRY: u32 = 0x0200_0120;
const BLOCK: usize = 4096;

/// `pd40_install.check_area`: the checks of an app area on its own, as the boot loader and pocketx_fw read it, for a
/// layout that keeps it in [base, limit). The identity in its OP-PRODUCT field, or None; refused with the first failure.
pub fn check_area(area: &[u8], base: usize, limit: usize) -> Result<Option<String>, Error> {
    let refuse = |m: String| Err(Error::Refused(m));
    if area.is_empty() || !area.len().is_multiple_of(BLOCK) {
        return refuse(format!(
            "the image is {} bytes, not a whole number of 4 KiB blocks",
            area.len()
        ));
    }
    if area.len() > limit - base {
        return refuse(format!(
            "the image is {:#x} bytes, longer than the write range [{base:#x}, {limit:#x})",
            area.len()
        ));
    }
    let dec = sfc(area, 0);
    let unreadable = |Unreadable(m)| Error::Refused(m);
    let ents = area_entries(&dec).map_err(unreadable)?;
    let head = &ents[0];
    if !head.hdr_ok || head.name != "app_area_head" {
        return refuse(
            "its first 32 bytes are not an app area head under the chip key 0x980F: the boot loader would not start it"
                .into(),
        );
    }
    if head.addr != ENTRY {
        return refuse(format!("its entry is {:#x}, not {ENTRY:#x}", head.addr));
    }
    if head.len as usize > area.len() || crc16(slice(&dec, 0x20, head.len as usize), 0) != head.dcrc {
        return refuse("its area head's data CRC fails".into());
    }
    for e in ents[1..].iter().filter(|e| is_file(e)) {
        let (at, end) = (e.addr as usize, e.addr as usize + e.len as usize);
        if !e.hdr_ok || end > area.len() || crc16(&dec[at..end], 0) != e.dcrc {
            return refuse(format!("its file {} fails its CRC", e.name));
        }
    }
    Ok(product(&dec))
}

/// The identity in `OP-PRODUCT:<letters>_<digits>`, the first such field.
fn product(dec: &[u8]) -> Option<String> {
    const FIELD: &[u8] = b"OP-PRODUCT:";
    let mut from = 0;
    while let Some(i) = dec[from..].windows(FIELD.len()).position(|w| w == FIELD) {
        let rest = &dec[from + i + FIELD.len()..];
        let letters = rest.iter().take_while(|b| b.is_ascii_alphabetic()).count();
        let digits = rest
            .get(letters + 1..)
            .map_or(0, |r| r.iter().take_while(|b| b.is_ascii_digit()).count());
        if letters > 0 && rest.get(letters) == Some(&b'_') && digits > 0 {
            return Some(String::from_utf8_lossy(&rest[..letters + 1 + digits]).into_owned());
        }
        from += i + 1;
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_product_field_is_found_as_the_python_regex_finds_it() {
        assert_eq!(product(b"xxOP-PRODUCT:BlackBox_950\0"), Some("BlackBox_950".into()));
        assert_eq!(product(b"OP-PRODUCT:_1 OP-PRODUCT:PocketX_9"), Some("PocketX_9".into()));
        assert_eq!(product(b"OP-PRODUCT:BlackBox_"), None);
    }

    #[test]
    fn a_short_package_is_unreadable_not_a_panic() {
        assert!(Package::read(&[0u8; 100]).is_err());
        assert!(Package::read(&[0u8; 20 * 0x30]).is_err());
    }
}
