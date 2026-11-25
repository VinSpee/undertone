// SPDX-License-Identifier: GPL-3.0-only
//! Simulated pedals for the tests, ported from the Python tests' own: the chip's USB boot state (tests/uboot_sim.py),
//! M-VAVE's recovery mode as the V23 boot loader answers hello and leave (tests/recovery_sim.py), the bus a pedal comes
//! and goes on (the `Bench` of tests/test_uboot_install.py), and flash images built to the two layouts
//! (tests/fw_layouts.py). Each keeps every transfer it saw, in the transcript format of
//! tests/fixtures/record.py, so a run can be compared with the Python tool's run byte for byte.
use std::collections::BTreeSet;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};

use crate::crc::{cipher, crc16, crc32, enc, sfc};
use crate::recovery::{FRAME, RECOVERY, UBOOT};
use crate::uboot::{self, LOADER_AT, LOADER_SIZE, SECTOR};
use crate::{Bus, Clock, Error, Msc, RecoveryDevice};

/// A clock that moves only when the bus sleeps or a command takes time.
#[derive(Clone, Default)]
pub struct FakeClock(Arc<AtomicU64>);

impl FakeClock {
    pub fn starting_at(t: f64) -> FakeClock {
        let c = FakeClock::default();
        c.set(t);
        c
    }

    pub fn now(&self) -> f64 {
        f64::from_bits(self.0.load(Ordering::SeqCst))
    }

    pub fn set(&self, t: f64) {
        self.0.store(t.to_bits(), Ordering::SeqCst)
    }

    pub fn advance(&self, s: f64) {
        self.set(self.now() + s)
    }

    pub fn clock(&self) -> Clock {
        let c = self.clone();
        Arc::new(move || c.now())
    }
}

/// The noise of the tests: an xorshift64* stream, the same in tests/fixtures/record.py.
pub fn noise(seed: u64, n: usize) -> Vec<u8> {
    let mut x = seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) | 1;
    (0..n)
        .map(|_| {
            x ^= x >> 12;
            x ^= x << 25;
            x ^= x >> 27;
            (x.wrapping_mul(0x2545_F491_4F6C_DD1D) >> 56) as u8
        })
        .collect()
}

const WATCHDOG: f64 = 3.0;

/// The pedal in the chip's USB boot state: the mask ROM's and the RAM loader's commands on a NOR flash (a write can only
/// clear bits, an erase sets a sector to 0xFF), the loader's 3 s watchdog, and a pedal that drops off the bus after a
/// number of commands.
pub struct SimPedal {
    pub flash: Vec<u8>,
    loader: Vec<u8>,
    pub key: u16,
    pub flash_id: u32,
    pub vendor: String,
    pub buffer: usize,
    clock: FakeClock,
    /// (opcode, address) of every command that reached the device.
    pub seen: Vec<(u16, u32)>,
    pub transcript: Vec<String>,
    ram: Vec<u8>,
    running: bool,
    last: Option<f64>,
    /// Drop off the bus when this many commands have been seen in all.
    pub drop_at: Option<usize>,
    pub present: bool,
}

impl SimPedal {
    pub fn new(flash: Vec<u8>, loader: Vec<u8>, clock: FakeClock) -> SimPedal {
        SimPedal {
            flash,
            loader,
            key: 0x980F,
            flash_id: 0xEB_6014,
            vendor: "WL82".into(),
            buffer: 0x8000,
            clock,
            seen: vec![],
            transcript: vec![],
            ram: vec![0; LOADER_SIZE],
            running: false,
            last: None,
            drop_at: None,
            present: true,
        }
    }

    /// The pedal rebooted and is in the boot state again: the ROM only, the loader gone, the flash as it was left.
    pub fn reenumerate(&mut self) {
        self.running = false;
        self.ram = vec![0; LOADER_SIZE];
        self.last = None;
        self.present = true;
        self.drop_at = None;
    }

    pub fn writes(&self) -> Vec<u32> {
        self.seen
            .iter()
            .filter(|(op, _)| *op == uboot::WRITE_FLASH)
            .map(|(_, a)| *a)
            .collect()
    }

    pub fn erases(&self) -> Vec<u32> {
        self.seen
            .iter()
            .filter(|(op, _)| *op == uboot::ERASE_SECTOR)
            .map(|(_, a)| *a)
            .collect()
    }

    fn execute(&mut self, cdb: &[u8], out: Option<&[u8]>, in_len: usize, timeout: u32) -> Result<Vec<u8>, Error> {
        self.transcript.push(match out {
            Some(o) => format!(
                "scsi {} out={}:{:08x} in={in_len} t={timeout}",
                uboot::hex(cdb),
                o.len(),
                crc32(o, 0)
            ),
            None => format!("scsi {} in={in_len} t={timeout}", uboot::hex(cdb)),
        });
        let gone = || Err(Error::Gone("gone".into()));
        let bad = |m: &str| Err(Error::Transfer(m.into()));
        if !self.present {
            return gone();
        }
        if self.drop_at.is_some_and(|n| self.seen.len() >= n) {
            self.present = false;
            return gone();
        }
        self.clock.advance(0.002);
        let t = self.clock.now();
        if self.running && self.last.is_some_and(|last| t - last > WATCHDOG) {
            self.running = false; // the loader reset the chip
            self.present = false;
            return Err(Error::Gone("watchdog".into()));
        }
        self.last = Some(t);
        if cdb[0] == 0x12 {
            let mut d = vec![0, 0, 0, 0, 0x1f, 0, 0, 0];
            d.extend(format!("{:<8}", self.vendor).bytes());
            d.extend(format!("{:<16}", "UBOOT1.00").bytes());
            d.extend(b"1.00");
            d.truncate(in_len);
            return Ok(d);
        }
        let op = u16::from_be_bytes([cdb[0], cdb[1]]);
        let be32 = |o: usize| u32::from_be_bytes([cdb[o], cdb[o + 1], cdb[o + 2], cdb[o + 3]]);
        let be16 = |o: usize| u16::from_be_bytes([cdb[o], cdb[o + 1]]) as usize;
        self.seen.push((op, be32(2)));
        let reply = |body: &[u8]| {
            let mut r = cdb[..2].to_vec();
            r.extend_from_slice(body);
            r.resize(16, 0);
            Ok(r)
        };
        let data_crc = u16::from_le_bytes([cdb[9], cdb[10]]);
        match op {
            uboot::WRITE_MEMORY => {
                let (addr, n, out) = (be32(2), be16(6), out.unwrap_or(&[]));
                let off = addr.wrapping_sub(LOADER_AT) as usize;
                if out.len() != n || crc16(out, 0) != data_crc || addr < LOADER_AT || off + n > self.ram.len() {
                    return bad("bad data");
                }
                self.ram[off..off + n].copy_from_slice(out);
                Ok(vec![])
            }
            uboot::JUMP => {
                self.running = be32(2) == LOADER_AT && self.ram[..self.loader.len()] == self.loader[..];
                reply(&[])
            }
            _ if !self.running => bad("the loader is not running"),
            uboot::READ_KEY => {
                let ks = cipher(&[0, 0]);
                reply(&[0, 0, 0, 0, (self.key >> 8) as u8 ^ ks[1], self.key as u8 ^ ks[0]])
            }
            uboot::ONLINE_DEVICE => {
                let mut body = vec![3, 0];
                body.extend(self.flash_id.to_le_bytes());
                reply(&body)
            }
            uboot::USB_BUFFER => reply(&(self.buffer as u32).to_be_bytes()),
            uboot::READ_FLASH => {
                let (addr, n) = (be32(2) as usize, be16(6));
                if n > self.buffer || addr + n > self.flash.len() {
                    return bad("bad read");
                }
                Ok(self.flash[addr..addr + n].to_vec())
            }
            uboot::ERASE_SECTOR => {
                let addr = be32(2) as usize;
                assert_eq!(addr % SECTOR, 0);
                self.flash[addr..addr + SECTOR].fill(0xFF);
                reply(&[])
            }
            uboot::WRITE_FLASH => {
                let (addr, n, out) = (be32(2) as usize, be16(6), out.unwrap_or(&[]));
                if out.len() != n || crc16(out, 0) != data_crc {
                    return bad("bad data");
                }
                for (i, b) in out.iter().enumerate() {
                    self.flash[addr + i] &= b;
                }
                Ok(vec![])
            }
            uboot::RUN_APP => {
                self.running = false;
                self.present = false;
                reply(&[])
            }
            _ => bad(&format!("unknown command {op:04X}")),
        }
    }
}

/// A shared simulated pedal: the test keeps one handle to look at its flash, the code under test gets another.
pub struct Shared<T>(pub Arc<Mutex<T>>);

impl<T> Clone for Shared<T> {
    fn clone(&self) -> Self {
        Shared(self.0.clone())
    }
}

impl<T> Shared<T> {
    pub fn new(t: T) -> Shared<T> {
        Shared(Arc::new(Mutex::new(t)))
    }

    pub fn lock(&self) -> MutexGuard<'_, T> {
        self.0.lock().expect("a simulated pedal is never poisoned")
    }
}

impl Msc for Shared<SimPedal> {
    fn execute(&mut self, cdb: &[u8], out: Option<&[u8]>, in_len: usize, timeout_ms: u32) -> Result<Vec<u8>, Error> {
        self.lock().execute(cdb, out, in_len, timeout_ms)
    }
}

/// Where the pedal goes after it leaves the recovery mode.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum After {
    Uboot,
    Recovery,
    App,
    Nothing,
}

/// One way of answering badly, as tests/recovery_sim.py's faults.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Fault {
    Status,
    Constants,
    Crc,
}

/// How the simulated recovery mode behaves; the defaults are the real V23 pedal's.
#[derive(Clone, Debug)]
pub struct RecoveryOptions {
    pub state: u32,
    pub boot_crc: u32,
    pub fault: Option<Fault>,
    /// Zeros in place of every reply on bulk IN, while the reply buffer holds the real reply, as on the real pedal.
    pub in_zeros: bool,
    pub after_reset: After,
    pub reset_s: f64,
    /// The mode ends on its own this many seconds after the computer's last access.
    pub exits_after: Option<f64>,
    /// It answers command 6 without ever acting on it.
    pub stays: bool,
}

impl Default for RecoveryOptions {
    fn default() -> Self {
        RecoveryOptions {
            state: 0,
            boot_crc: crate::recovery::V23_HEAD,
            fault: None,
            in_zeros: false,
            after_reset: After::Uboot,
            reset_s: 0.5,
            exits_after: None,
            stays: false,
        }
    }
}

/// M-VAVE's recovery mode, packet by packet, for hello and leave. The write commands 2 to 5 are answered "wrong state"
/// and kept in `write_attempts`, which every test requires to stay empty.
pub struct SimRecovery {
    o: RecoveryOptions,
    clock: FakeClock,
    pub transcript: Vec<String>,
    pub frames: Vec<u32>,
    pub write_attempts: Vec<u32>,
    accumulated: Vec<u8>,
    armed: Vec<Vec<u8>>,
    waiting: bool,
    last_reply: Vec<u8>,
    frame_buffer: Vec<u8>,
    pub present: bool,
    left: bool,
    pub departed_at: Option<f64>,
    pub next_device: Option<(u16, u16)>,
    last_access: f64,
}

impl SimRecovery {
    pub fn new(o: RecoveryOptions, clock: FakeClock) -> SimRecovery {
        SimRecovery {
            o,
            clock,
            transcript: vec![],
            frames: vec![],
            write_attempts: vec![],
            accumulated: vec![],
            armed: vec![],
            waiting: false,
            last_reply: vec![0; 64],
            frame_buffer: vec![0; FRAME],
            present: true,
            left: false,
            departed_at: None,
            next_device: None,
            last_access: 0.0,
        }
    }

    fn access(&mut self, line: String) -> Result<(), Error> {
        self.tick();
        if !self.present {
            return Err(Error::Gone("gone".into()));
        }
        self.last_access = self.clock.now();
        self.transcript.push(line);
        Ok(())
    }

    /// The mode ending on its own `exits_after` seconds after the computer's last access.
    pub fn tick(&mut self) {
        if let Some(after) = self.o.exits_after
            && self.present
            && self.clock.now() >= self.last_access + after
        {
            self.depart(Some(self.last_access + after));
        }
    }

    fn depart(&mut self, at: Option<f64>) {
        self.present = false;
        self.armed.clear();
        self.departed_at = Some(at.unwrap_or_else(|| self.clock.now()));
        self.next_device = match self.o.after_reset {
            After::Uboot => Some(UBOOT),
            After::Recovery => Some(RECOVERY),
            After::App => Some(crate::recovery::APP),
            After::Nothing => None,
        };
    }

    fn handle(&mut self, data: &[u8]) {
        let w = |i: usize| u32::from_le_bytes([data[4 * i], data[4 * i + 1], data[4 * i + 2], data[4 * i + 3]]);
        if &data[..4] != b"SBU2" {
            self.frames.push(w(1));
            return self.reply(0, 0, 1);
        }
        let (command, tag, arg, length, crc) = (w(1), w(2), w(3), w(4) as usize, w(5));
        self.frames.push(command);
        let payload = &data[24..24 + length.min(FRAME - 24)];
        if length > 4096 || crc32(payload, 0) != crc {
            return self.reply(command, tag, 1);
        }
        let status = match command {
            1 => u32::from(arg != 0 || length != 0),
            6 if arg != 0 || length != 0 => 1,
            6 if self.o.state != 0 && self.o.state != 6 => 2,
            6 => {
                self.left = true;
                0
            }
            2..=5 => {
                self.write_attempts.push(command);
                2
            }
            _ => 1,
        };
        self.reply(command, tag, status)
    }

    fn reply(&mut self, command: u32, tag: u32, status: u32) {
        let status = if self.o.fault == Some(Fault::Status) && command == 1 {
            1
        } else {
            status
        };
        let version = if self.o.fault == Some(Fault::Constants) {
            0x0003_0000
        } else {
            0x0002_0000
        };
        let words = [
            command,
            tag,
            status,
            self.o.state,
            0,
            0,
            0x0791_0040,
            version,
            0x6000,
            0x9F000,
            self.o.boot_crc,
        ];
        let mut raw = b"SBR2".to_vec();
        for w in words.iter().chain(&[0, 0, 0]) {
            raw.extend(w.to_le_bytes());
        }
        let crc = crc32(&raw, 0) ^ u32::from(self.o.fault == Some(Fault::Crc));
        raw.extend(crc.to_le_bytes());
        self.last_reply = raw.clone();
        self.waiting = true;
        if self.armed.is_empty() {
            self.armed.push(if self.o.in_zeros { vec![0; 64] } else { raw });
        }
    }
}

impl RecoveryDevice for Shared<SimRecovery> {
    fn names(&self) -> (String, String) {
        ("SINCO".into(), "PD40 BOOT Recovery".into())
    }

    fn control_in(&mut self, request: u8, len: usize) -> Result<Vec<u8>, Error> {
        let mut d = self.lock();
        d.access(format!("ctl {request:#04x} {len}"))?;
        match (request, len) {
            (0x43, 64) => Ok(d.last_reply.clone()),
            (0x44, 24) => Ok(d.frame_buffer[..24].to_vec()),
            _ => Err(Error::Transfer("stall".into())),
        }
    }

    fn bulk_out(&mut self, data: &[u8]) -> Result<(), Error> {
        let mut d = self.lock();
        d.access(format!("out {} {:08x}", data.len(), crc32(data, 0)))?;
        if d.waiting {
            return Err(Error::Transfer(
                "frame: the pedal takes no packet while a reply waits".into(),
            ));
        }
        for packet in data.chunks(64) {
            d.accumulated.extend_from_slice(packet);
            let n = d.accumulated.len();
            let acc = d.accumulated.clone();
            d.frame_buffer[..n].copy_from_slice(&acc);
            if n == FRAME {
                d.accumulated.clear();
                d.handle(&acc);
            }
        }
        Ok(())
    }

    fn bulk_in(&mut self, len: usize, timeout_ms: u32) -> Result<Option<Vec<u8>>, Error> {
        let mut d = self.lock();
        d.access(format!("in {len} {timeout_ms}"))?;
        if d.armed.is_empty() {
            d.clock.advance(f64::from(timeout_ms) / 1000.0);
            return Ok(None);
        }
        let mut raw = d.armed.remove(0);
        d.waiting = !d.armed.is_empty();
        if d.left && !d.o.stays {
            d.depart(None); // command 6 acts once its reply has been read
        }
        raw.truncate(len);
        Ok(Some(raw))
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Start {
    Recovery,
    Uboot,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Mode {
    Off,
    Recovery,
    Gap,
    Uboot,
}

/// The computer's USB bus with one pedal on it (tests/test_uboot_install.py's `Bench`). `starts` says how the pedal
/// comes each time the bus has been empty for a second; from the recovery mode it goes where its options say (one per
/// entry, the last for every later one); the boot state lasts `boot_window` seconds unless it has been claimed by then,
/// and in its n-th appearance it drops off the bus after `drops[n]` commands. After `give_up` seconds the person stops.
pub struct Bench {
    pub clock: FakeClock,
    pub uboot: Shared<SimPedal>,
    starts: Vec<Start>,
    boot_window: f64,
    recovery: Vec<RecoveryOptions>,
    drops: Vec<usize>,
    end: f64,
    mode: Mode,
    rec: Option<Shared<SimRecovery>>,
    pub recoveries: Vec<Shared<SimRecovery>>,
    /// Seconds from each appearance of the boot state to its claim.
    pub claims: Vec<f64>,
    appeared: f64,
    claimed: bool,
    empty_since: Option<f64>,
}

pub const POLL: f64 = 0.05;

impl Bench {
    pub fn new(flash: Vec<u8>, loader: Vec<u8>, starts: &[Start]) -> Bench {
        let clock = FakeClock::starting_at(100.0);
        let mut pedal = SimPedal::new(flash, loader, clock.clone());
        pedal.present = false;
        Bench {
            end: clock.now() + 120.0,
            empty_since: Some(clock.now()),
            uboot: Shared::new(pedal),
            clock,
            starts: starts.to_vec(),
            boot_window: 3.0,
            recovery: vec![RecoveryOptions {
                in_zeros: true,
                ..Default::default()
            }],
            drops: vec![],
            mode: Mode::Off,
            rec: None,
            recoveries: vec![],
            claims: vec![],
            appeared: 0.0,
            claimed: false,
        }
    }

    pub fn boot_window(mut self, s: f64) -> Bench {
        self.boot_window = s;
        self
    }

    pub fn give_up(mut self, s: f64) -> Bench {
        self.end = self.clock.now() + s;
        self
    }

    pub fn recovery(mut self, options: Vec<RecoveryOptions>) -> Bench {
        self.recovery = options;
        self
    }

    pub fn drops(mut self, drops: &[usize]) -> Bench {
        self.drops = drops.to_vec();
        self
    }

    /// The commands the recovery mode got, over every entry.
    pub fn frames(&self) -> Vec<u32> {
        self.recoveries.iter().flat_map(|r| r.lock().frames.clone()).collect()
    }

    /// Every transfer, the recovery mode's then the boot state's, as tests/fixtures/record.py writes them.
    pub fn transcript(&self) -> Vec<String> {
        let mut t: Vec<String> = self
            .recoveries
            .iter()
            .flat_map(|r| r.lock().transcript.clone())
            .collect();
        t.extend(self.uboot.lock().transcript.clone());
        t
    }

    fn appear(&mut self, at: f64) {
        let mut u = self.uboot.lock();
        u.reenumerate();
        if !self.drops.is_empty() {
            let n = self.drops.remove(0);
            u.drop_at = Some(u.seen.len() + n);
        }
        drop(u);
        self.mode = Mode::Uboot;
        self.appeared = at;
        self.claimed = false;
    }

    fn step(&mut self) {
        let t = self.clock.now();
        if self.mode == Mode::Recovery {
            let rec = self.rec.clone().expect("a recovery mode is on the bus");
            let mut r = rec.lock();
            r.tick();
            if !r.present {
                self.mode = if r.next_device == Some(UBOOT) {
                    Mode::Gap
                } else {
                    Mode::Off
                };
            }
        }
        if self.mode == Mode::Gap {
            let rec = self.rec.clone().expect("the pedal left a recovery mode");
            let at = {
                let r = rec.lock();
                r.departed_at.unwrap_or(t) + r.o.reset_s
            };
            if t >= at {
                self.appear(at);
            }
        }
        if self.mode == Mode::Uboot
            && (!self.uboot.lock().present || !self.claimed && t >= self.appeared + self.boot_window)
        {
            self.uboot.lock().present = false;
            self.mode = Mode::Off;
        }
        if self.mode != Mode::Off {
            self.empty_since = None;
        } else if self.empty_since.is_none() {
            self.empty_since = Some(t);
        }
        if self.mode == Mode::Off && !self.starts.is_empty() && self.empty_since.is_some_and(|e| t >= e + 1.0) {
            self.empty_since = None;
            if self.starts.remove(0) == Start::Uboot {
                self.appear(t);
            } else {
                let flash_head = self.uboot.lock().flash[..0x6000].to_vec();
                let i = self.recoveries.len().min(self.recovery.len() - 1);
                let options = RecoveryOptions {
                    boot_crc: crc32(&flash_head, 0),
                    ..self.recovery[i].clone()
                };
                let rec = Shared::new(SimRecovery::new(options, self.clock.clone()));
                self.recoveries.push(rec.clone());
                self.rec = Some(rec);
                self.mode = Mode::Recovery;
            }
        }
    }
}

impl Bus for Bench {
    fn poll(&self) -> f64 {
        POLL
    }

    fn clock(&self) -> Clock {
        self.clock.clock()
    }

    fn sleep(&mut self, seconds: f64) -> Result<(), Error> {
        self.clock.advance(seconds);
        if self.clock.now() > self.end {
            return Err(Error::Stopped("the person stopped the wait".into()));
        }
        Ok(())
    }

    fn open_uboot(&mut self) -> Result<Option<Box<dyn Msc>>, Error> {
        self.step();
        if self.mode != Mode::Uboot {
            return Ok(None);
        }
        if !self.claimed {
            self.claimed = true;
            self.claims.push(self.clock.now() - self.appeared);
        }
        Ok(Some(Box::new(self.uboot.clone())))
    }

    fn open_recovery(&mut self) -> Result<Option<Box<dyn RecoveryDevice>>, Error> {
        self.step();
        Ok(match (&self.mode, &self.rec) {
            (Mode::Recovery, Some(rec)) => Some(Box::new(rec.clone())),
            _ => None,
        })
    }

    fn present(&mut self) -> Result<BTreeSet<(u16, u16)>, Error> {
        self.step();
        Ok(match self.mode {
            Mode::Recovery => BTreeSet::from([RECOVERY]),
            Mode::Uboot => BTreeSet::from([UBOOT]),
            _ => BTreeSet::new(),
        })
    }
}

fn entry(name: &str, addr: u32, len: u32, attr: u8, dcrc: u16) -> Vec<u8> {
    let mut e = vec![0u8; 32];
    e[2..4].copy_from_slice(&dcrc.to_le_bytes());
    e[4..8].copy_from_slice(&addr.to_le_bytes());
    e[8..12].copy_from_slice(&len.to_le_bytes());
    e[12] = attr;
    e[16..16 + name.len()].copy_from_slice(name.as_bytes());
    let crc = crc16(&e[2..32], 0);
    e[..2].copy_from_slice(&crc.to_le_bytes());
    e
}

/// A flash with its app area at `base` (tests/fw_layouts.py's `flash_image`): head entries under ENC, then the area under
/// the chip key with an app, its config and two regions.
pub fn flash_image(base: usize, app: &[u8], length: usize) -> Vec<u8> {
    const CFG: &[u8] = b"cfg_toolcfg_toolcfg_toolcfg_toolcfg_toolcfg_toolcfg_toolcfg_tool";
    let mut head = vec![0xFFu8; base];
    head[..0x20].copy_from_slice(&[[0x20, 0x02].as_slice(), &[0; 30]].concat());
    let entries = [
        entry("uboot.boot", 0xA0, 0x100, 0, 0xFFFF),
        entry("isd_config.ini", 0x1A0, 0x20, 0, 0xFFFF),
        entry("app_dir_head", base as u32, 0xFFFF_FFFF, 0x81, 0xFFFF),
        entry("key_mac", 0xFF000, 0x1000, 0, 0xFFFF),
    ];
    for (i, e) in entries.iter().enumerate() {
        head[0x20 + i * 32..0x40 + i * 32].copy_from_slice(&enc(e, 0xFFFF));
    }
    let mut area = vec![0xFFu8; length - base];
    let (app_at, cfg_at) = (0x120, 0x120 + app.len());
    let end = cfg_at + CFG.len();
    area[app_at..cfg_at].copy_from_slice(app);
    area[cfg_at..end].copy_from_slice(CFG);
    area[0x20..0x40].copy_from_slice(&entry("app.bin", app_at as u32, app.len() as u32, 0x82, crc16(app, 0)));
    area[0x40..0x60].copy_from_slice(&entry(
        "cfg_tool.bin",
        cfg_at as u32,
        CFG.len() as u32,
        0x82,
        crc16(CFG, 0),
    ));
    area[0x60..0x80].copy_from_slice(&entry("VM", length as u32, 0xBE000 - length as u32, 0x12, 0x01FF));
    area[0x80..0xA0].copy_from_slice(&entry("PRCT", 0, length as u32, 0x92, 0xFFFF));
    let head_entry = entry(
        "app_area_head",
        0x200_0120,
        end as u32,
        0x83,
        crc16(&area[0x20..end], 0),
    );
    area[..0x20].copy_from_slice(&head_entry);
    head.extend(sfc(&area, 0));
    head
}

/// An app area of `len` bytes, as the build writes one beside its BlackBox package (`*-v23.bin`): `flash_image`'s area,
/// its app holding the identity `product` in its OP-PRODUCT field.
pub fn app_area(product: &str, seed: u64, len: usize) -> Vec<u8> {
    let mut app = format!("OP-PRODUCT:{product}\0").into_bytes();
    app.extend(noise(seed, 0x2000));
    flash_image(0x6000, &app, 0x6000 + len)[0x6000..].to_vec()
}

/// A .fwsc package of `flash` and `ota` with the identity `product` (tools/pxpkg.py's `ufw`).
pub fn package(flash: &[u8], ota: &[u8], product: &str) -> Vec<u8> {
    let mut off = 0x400usize;
    let mut ents = vec![];
    for (i, (typ, name, d)) in [(0u16, "flash.bin", flash), (100, "ota.bin", ota)]
        .into_iter()
        .enumerate()
    {
        off = (off + 0xFF) & !0xFF;
        let mut e = vec![0u8; 0x50];
        e[0..2].copy_from_slice(&typ.to_le_bytes());
        e[2..4].copy_from_slice(&(i as u16).to_le_bytes());
        e[4..6].copy_from_slice(&crc16(d, 0).to_le_bytes());
        e[8..12].copy_from_slice(&(off as u32).to_le_bytes());
        e[12..16].copy_from_slice(&(d.len() as u32).to_le_bytes());
        e[16..20].copy_from_slice(&((d.len() as u32 + 31) & !31).to_le_bytes());
        e[0x40..0x40 + name.len()].copy_from_slice(name.as_bytes());
        ents.push((e, off, d));
        off += d.len();
    }
    let total = off;
    let mut hdr = vec![0u8; 0x40];
    hdr[4..8].copy_from_slice(&(total as u32).to_le_bytes());
    hdr[8..10].copy_from_slice(&(ents.len() as u16).to_le_bytes());
    hdr[10..16].copy_from_slice(&[0x04, 0x00, 0x00, 0x02, 0x00, 0x00]);
    hdr[16..22].copy_from_slice(b"AC791N");
    let lst: Vec<u8> = ents.iter().flat_map(|(e, _, _)| enc(e, 0xFFFF)).collect();
    let list_crc = crc16(&lst, 0);
    hdr[2..4].copy_from_slice(&list_crc.to_le_bytes());
    let hdr_crc = crc16(&hdr[2..0x40], 0);
    hdr[0..2].copy_from_slice(&hdr_crc.to_le_bytes());
    let mut logical = vec![0xFFu8; total];
    logical[..0x40].copy_from_slice(&enc(&hdr, 0xFFFF));
    logical[0x40..0x40 + lst.len()].copy_from_slice(&lst);
    for (_, o, d) in &ents {
        logical[*o..*o + d.len()].copy_from_slice(d);
    }
    let product = product.as_bytes();
    let mut raw = vec![];
    for i in 0..20 {
        raw.extend_from_slice(&logical[i * 0x2F..(i + 1) * 0x2F]);
        raw.push(product.get(i).map_or(0x7D, |&c| c.wrapping_add(i as u8 + 1)));
    }
    raw.extend_from_slice(&logical[20 * 0x2F..]);
    raw
}
