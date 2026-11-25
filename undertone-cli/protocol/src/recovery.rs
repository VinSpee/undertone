// SPDX-License-Identifier: GPL-3.0-only
//! M-VAVE's recovery mode on a BlackBox with the V22 or V23 boot loader (USB 3654:7940, "PD40 BOOT Recovery"), as
//! tools/pd40_recovery.py speaks it: one hello, then the single leave to the chip's USB boot state. Frames of 4608 bytes
//! from "SBU2", 64-byte replies from "SBR2", CRC-32 as zlib's. The commands that write (2 to 5) cannot be composed here,
//! and only the vendor requests 0x43 and 0x44 are sent.
use crate::crc::crc32;
use crate::uboot::py_repr;
use crate::{Clock, Error, RecoveryDevice};

pub const VID: u16 = 0x3654;
pub const PID: u16 = 0x7940;
pub const FRAME: usize = 4608;
pub const REPLY: usize = 64;
pub const REPLY_BUFFER: u8 = 0x43;
pub const FRAME_BUFFER: u8 = 0x44;
pub const HELLO: u32 = 1;
pub const LEAVE: u32 = 6;
/// The constants and the write range [base, limit) every reply carries.
pub const PROTOCOL: (u32, u32, u32, u32) = (0x0791_0040, 0x0002_0000, 0x6000, 0x9F000);
const LEAVE_STATES: [u32; 2] = [0, 6];
const FIRST_READ_MS: u32 = 1000;
const SECOND_READ_MS: u32 = 300;
pub const RECOVERY: (u16, u16) = (VID, PID);
pub const UBOOT: (u16, u16) = (crate::uboot::VID, crate::uboot::PID);

fn status_name(status: u32) -> &'static str {
    match status {
        0 => "accepted",
        1 => "malformed",
        2 => "wrong state",
        4 => "out of range",
        5 => "boot CRC is not this pedal's",
        6 => "CRC error",
        7 => "flash error",
        8 => "block out of order",
        _ => "unknown",
    }
}

/// The frame of hello or leave: "SBU2", the command, the tag, argument 0, length 0, CRC-32 0, then zeros. No other
/// command can be composed.
pub fn frame(command: u32, tag: u32) -> Result<Vec<u8>, Error> {
    if command != HELLO && command != LEAVE {
        return Err(Error::Refused(match command {
            2 => "command 2 (manifest) belongs to a write to the flash: this tool never sends it".into(),
            3 => "command 3 (block) belongs to a write to the flash: this tool never sends it".into(),
            4 => "command 4 (erase and commit) belongs to a write to the flash: this tool never sends it".into(),
            5 => "command 5 (start the new app) belongs to a write to the flash: this tool never sends it".into(),
            _ => format!("command {command} is not one this tool sends (only {HELLO} hello and {LEAVE} leave)"),
        }));
    }
    let mut f = Vec::with_capacity(FRAME);
    f.extend_from_slice(b"SBU2");
    for word in [command, tag, 0, 0, 0] {
        f.extend_from_slice(&word.to_le_bytes());
    }
    f.resize(FRAME, 0);
    Ok(f)
}

/// A checked 64-byte reply.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Reply {
    pub command: u32,
    pub tag: u32,
    pub status: u32,
    pub state: u32,
    pub next_offset: u32,
    pub image_length: u32,
    pub constants: (u32, u32),
    pub base: u32,
    pub limit: u32,
    pub boot_crc: u32,
    /// Erase started, last flash error, the manifest's word at offset 68.
    pub words: (u32, u32, u32),
}

/// The 64-byte reply, checked: "SBR2", the command and tag echoed, the CRC-32 of its first 60 bytes, the constants.
pub fn parse_reply(raw: &[u8], command: u32, tag: u32) -> Result<Reply, Error> {
    let bad = |m: String| Err(Error::Refused(m));
    if raw.len() != REPLY {
        return bad(format!("the reply is {} bytes, not {REPLY}", raw.len()));
    }
    let w = |i: usize| u32::from_le_bytes([raw[4 * i], raw[4 * i + 1], raw[4 * i + 2], raw[4 * i + 3]]);
    if &raw[..4] != b"SBR2" {
        return bad(format!("the reply starts with {}, not 'SBR2'", bytes_repr(&raw[..4])));
    }
    let crc = crc32(&raw[..60], 0);
    if w(15) != crc {
        return bad(format!(
            "the reply's CRC-32 {:#010x} is not that of its contents ({crc:#010x})",
            w(15)
        ));
    }
    if (w(1), w(2)) != (command, tag) {
        return bad(format!(
            "the reply is for command {} tag {}, not command {command} tag {tag}",
            w(1),
            w(2)
        ));
    }
    let r = Reply {
        command: w(1),
        tag: w(2),
        status: w(3),
        state: w(4),
        next_offset: w(5),
        image_length: w(6),
        constants: (w(7), w(8)),
        base: w(9),
        limit: w(10),
        boot_crc: w(11),
        words: (w(12), w(13), w(14)),
    };
    if (r.constants.0, r.constants.1, r.base, r.limit) != PROTOCOL {
        return bad(format!(
            "the reply's constants or write range are not the ones read in the V23 boot loader ({:#x} {:#x} [{:#x}, \
             {:#x})): another recovery version",
            r.constants.0, r.constants.1, r.base, r.limit
        ));
    }
    Ok(r)
}

/// Python's `repr` of bytes.
fn bytes_repr(b: &[u8]) -> String {
    let inner: String = b
        .iter()
        .map(|&c| match c {
            b'\\' => "\\\\".into(),
            b'\'' => "\\'".into(),
            b'\t' => "\\t".into(),
            b'\n' => "\\n".into(),
            b'\r' => "\\r".into(),
            0x20..=0x7E => (c as char).to_string(),
            _ => format!("\\x{c:02x}"),
        })
        .collect();
    format!("b'{inner}'")
}

fn dump(raw: &[u8]) -> String {
    let body = if raw.iter().any(|&b| b != 0) {
        crate::uboot::hex(raw)
    } else {
        "all zero".into()
    };
    format!("{} B {body}", raw.len())
}

/// Why `raw` is not the reply to `command` and `tag`, in words; None when it is.
fn what_came(raw: Option<&[u8]>, command: u32, tag: u32) -> Option<String> {
    let raw = match raw {
        None => return Some("nothing".into()),
        Some(r) => r,
    };
    if !raw.is_empty() && raw.iter().all(|&b| b == 0) {
        return Some(format!("{} zero bytes", raw.len()));
    }
    parse_reply(raw, command, tag).err().map(|e| e.message().to_string())
}

/// The recovery protocol over one opened device. `log` prints a line with the time since the device was found; `now` is
/// the clock that time is measured on.
pub struct Recovery<'a> {
    dev: &'a mut dyn RecoveryDevice,
    log: &'a mut dyn FnMut(&str),
    now: Clock,
    tag: u32,
    first: Option<f64>,
    /// (command, tag, when) of the last frame sent.
    pub sent: Option<(u32, u32, f64)>,
}

impl<'a> Recovery<'a> {
    pub fn new(dev: &'a mut dyn RecoveryDevice, log: &'a mut dyn FnMut(&str), now: Clock) -> Self {
        Recovery {
            dev,
            log,
            now,
            tag: 0,
            first: None,
            sent: None,
        }
    }

    /// A line in the session's log.
    pub fn say(&mut self, m: &str) {
        (self.log)(m)
    }

    fn access(&mut self) {
        if self.first.is_none() {
            self.first = Some((self.now)());
        }
    }

    /// How long before `at` the last command was sent and the first transfer started, in words.
    pub fn since(&self, at: f64) -> String {
        let first = format!(
            "{:.0} ms after the first access",
            (at - self.first.unwrap_or(at)) * 1000.0
        );
        match self.sent {
            None => format!("before any command was sent, {first}"),
            Some((command, tag, when)) => format!(
                "{:.0} ms after the last command sent (command {command}, tag {tag}) and {first}",
                (at - when) * 1000.0
            ),
        }
    }

    fn request(&mut self, request: u8, len: usize, what: &str) -> Result<Vec<u8>, Error> {
        self.access();
        let got = self.dev.control_in(request, len)?;
        (self.log)(&format!("{what} ({request:#x}): {}", dump(&got)));
        Ok(got)
    }

    fn send(&mut self, command: u32) -> Result<(), Error> {
        let data = frame(command, self.tag + 1)?;
        self.tag += 1;
        let tag = self.tag;
        (self.log)(&format!(
            "frame header: {} (command {command}, tag {tag}, length 0)",
            crate::uboot::hex(&data[..24])
        ));
        self.access();
        self.dev.bulk_out(&data)?;
        self.sent = Some((command, tag, (self.now)()));
        (self.log)(&format!(
            "frame: command {command}, tag {tag}, {} bytes in one transfer",
            data.len()
        ));
        Ok(())
    }

    /// One bulk IN read of exactly 64 bytes; None when nothing came within `ms`.
    fn read(&mut self, ms: u32, what: &str) -> Result<Option<Vec<u8>>, Error> {
        self.access();
        let got = self.dev.bulk_in(REPLY, ms)?;
        match &got {
            None => (self.log)(&format!("{what}: nothing within {ms} ms")),
            Some(g) => (self.log)(&format!("{what}: {}", dump(g))),
        }
        Ok(got)
    }

    /// The buffers, one hello, the buffers again, then its reply over bulk IN. Returns the hello reply, and None when it
    /// came over bulk IN, or else what the bulk IN endpoint sent in its place.
    pub fn probe(&mut self) -> Result<(Reply, Option<String>), Error> {
        let mut before = self.request(FRAME_BUFFER, 24, "frame buffer")?;
        before.extend(self.request(REPLY_BUFFER, REPLY, "reply buffer")?);
        if before.iter().any(|&b| b != 0) {
            (self.log)("the buffers are not empty: another tool spoke to the pedal since it entered the recovery mode");
        }
        self.send(HELLO)?;
        let head = self.request(FRAME_BUFFER, 24, "frame buffer")?;
        let kept = self.request(REPLY_BUFFER, REPLY, "reply buffer")?;
        let (raw, bulk) = self.await_reply(HELLO)?;
        if let Some(raw) = raw {
            return Ok((check(parse_reply(&raw, HELLO, self.tag)?)?, None));
        }
        let bulk = bulk.unwrap_or_default();
        if let Some(why) = what_came(Some(&kept), HELLO, self.tag) {
            let got = if kept.iter().any(|&b| b != 0) {
                ""
            } else if head == frame(HELLO, self.tag)?[..24] {
                ": the frame arrived only in part"
            } else {
                ": the frame did not reach the frame buffer"
            };
            return Err(Error::Refused(format!(
                "no reply to the hello: the bulk IN endpoint sent {bulk}, and the reply buffer holds {why}{got}"
            )));
        }
        Ok((check(parse_reply(&kept, HELLO, self.tag)?)?, Some(bulk)))
    }

    /// Up to two bulk IN reads for the reply to `command`, the second only after something else came.
    fn await_reply(&mut self, command: u32) -> Result<(Option<Vec<u8>>, Option<String>), Error> {
        let mut came = vec![];
        for (ms, what) in [(FIRST_READ_MS, "bulk IN read 1"), (SECOND_READ_MS, "bulk IN read 2")] {
            let raw = self.read(ms, what)?;
            match what_came(raw.as_deref(), command, self.tag) {
                None => return Ok((raw, None)),
                Some(why) => came.push(why),
            }
            if raw.is_none() {
                break; // a second read after a timeout could only disturb the device
            }
        }
        Ok((None, Some(came.join(", then "))))
    }

    /// Command 6. The pedal acts on it once its reply has been read; a lost reply is not an error.
    pub fn leave(&mut self, hello: &Reply) -> Result<Option<Reply>, Error> {
        if !LEAVE_STATES.contains(&hello.state) {
            return Err(Error::Refused(format!(
                "the recovery mode is in state {}: another tool started an update, and command 6 is refused there. \
                 Power-cycle the pedal into the recovery mode again first",
                hello.state
            )));
        }
        self.send(LEAVE)?;
        let (raw, bulk) = self.await_reply(LEAVE)?;
        let Some(raw) = raw else {
            (self.log)(&format!(
                "leave: the bulk IN endpoint sent {} in place of its reply",
                bulk.unwrap_or_default()
            ));
            return Ok(None);
        };
        let r = parse_reply(&raw, LEAVE, self.tag)?;
        if r.status != 0 {
            return Err(Error::Refused(format!(
                "leave was answered with status {} ({})",
                r.status,
                status_name(r.status)
            )));
        }
        Ok(Some(r))
    }
}

fn check(r: Reply) -> Result<Reply, Error> {
    if r.status != 0 {
        return Err(Error::Refused(format!(
            "hello was answered with status {} ({})",
            r.status,
            status_name(r.status)
        )));
    }
    Ok(r)
}

/// The known head of the recovery mode: the boot area of both official V22 and V23 packages.
pub const V23_HEAD: u32 = 0xB19D_96A1;

/// The hello reply, in words (`pd40_recovery.describe`).
pub fn describe(r: &Reply, bulk: Option<&str>, heads: &[(u32, &str)], log: &mut dyn FnMut(&str)) {
    let head = heads.iter().find(|(crc, _)| *crc == r.boot_crc).map_or(
        "not a head this tool knows: the pedal's head is not an official V22/V23 head",
        |(_, name)| name,
    );
    let state = if r.state == 0 {
        " (no update started)"
    } else {
        " (an update was started by another tool)"
    };
    log(&format!(
        "hello: status {} (accepted), state {}{state}",
        r.status, r.state
    ));
    log(&match bulk {
        None => "  read over the bulk IN endpoint".into(),
        Some(b) => format!(
            "  read over the control endpoint (request {REPLY_BUFFER:#x}) because the bulk IN endpoint sent {b}"
        ),
    });
    log(&format!(
        "  boot area [0, {:#x}) CRC-32 {:#010x}: {head}",
        r.base, r.boot_crc
    ));
    log(&format!(
        "  write range [{:#x}, {:#x}), protocol constants {:#010x} {:#010x}",
        r.base, r.limit, r.constants.0, r.constants.1
    ));
    log(&format!(
        "  image length {:#x}, next offset {:#x}, erase started {:#x}, last flash error {:#x}, manifest word {:#x}",
        r.image_length, r.next_offset, r.words.0, r.words.1, r.words.2
    ));
    log(
        "  not reported by the protocol: the chip key and the flash id. The recovery mode starts only on a 1 MiB flash \
         with id EB 60 14 or 85 60 14; tools/uboot_rescue.py prints both after --leave",
    );
}

/// The device's names as the Python tool shows them, `'SINCO' 'PD40 BOOT Recovery'`.
pub fn names(manufacturer: &str, product: &str) -> String {
    format!("{} {}", py_repr(manufacturer), py_repr(product))
}
