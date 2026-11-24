// SPDX-License-Identifier: GPL-3.0-only
//! The chip's USB boot state (USB 4C4A:8057, "WL80UBOOT1.00"), as tools/uboot_rescue.py speaks it: the mask ROM's and
//! JieLi's RAM loader's vendor SCSI commands, the guards that cannot be switched off, and the passes of a run (attach,
//! read, back up, compare, and with a confirmation write) that a rerun resumes.
use std::path::PathBuf;

use sha2::{Digest, Sha256};

use crate::crc::{CHIP_KEY, cipher, crc16};
use crate::fw::{self, Package, Unreadable};
use crate::install::Layout;
use crate::{Bus, Confirmed, Error, Msc};

pub const VID: u16 = 0x4C4A;
pub const PID: u16 = 0x8057;
pub const LOADER_URL: &str = "https://raw.githubusercontent.com/kagaimiq/jl-uboot-tool/\
                              c32b28e7a04f873f526ba929cb1bae9f05442fe9/data/loaderblobs/usb/wl82loader.bin";
pub const LOADER_SHA256: &str = "d41da6126760c9d66660bcc0cac8d27d221806c5e369a8036921efe68dca5376";
pub const LOADER_SIZE: usize = 24064;
pub const LOADER_AT: u32 = 0x1C0_2000;
pub const FLASH_SIZE: usize = 1 << 20;
pub const SECTOR: usize = 0x1000;
pub const IO: usize = 512;
pub const WRITE_FROM: usize = 0x4000;
pub const WRITE_LIMIT: usize = 0xFF000;

// the commands of the mask ROM and of the RAM loader (kagaimiq/jl-uboot-tool docs, fm1buddy), and the only ones this
// code can send
pub const WRITE_MEMORY: u16 = 0xFB06;
pub const JUMP: u16 = 0xFB08;
pub const READ_KEY: u16 = 0xFC09;
pub const ONLINE_DEVICE: u16 = 0xFC0A;
pub const USB_BUFFER: u16 = 0xFC14;
pub const READ_FLASH: u16 = 0xFD05;
pub const RUN_APP: u16 = 0xFC0C;
pub const ERASE_SECTOR: u16 = 0xFB01;
pub const WRITE_FLASH: u16 = 0xFB04;
const READ_ONLY_OPS: [u16; 7] = [
    WRITE_MEMORY,
    JUMP,
    READ_KEY,
    ONLINE_DEVICE,
    USB_BUFFER,
    READ_FLASH,
    RUN_APP,
];
const WRITE_OPS: [u16; 2] = [ERASE_SECTOR, WRITE_FLASH];

/// The only flash range a run may erase or write.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Window {
    pub lo: usize,
    pub hi: usize,
}

impl Window {
    /// The window of a rescue image that starts at 0: from 0x4000 to its end.
    pub fn for_image(size: usize) -> Result<Window, Error> {
        if !size.is_multiple_of(SECTOR) || !(WRITE_FROM < size && size <= WRITE_LIMIT) {
            return Err(Error::Refused(format!(
                "the image is {size:#x} bytes: it must be whole 4 KiB sectors and end in ({WRITE_FROM:#x}, \
                 {WRITE_LIMIT:#x}]"
            )));
        }
        Ok(Window {
            lo: WRITE_FROM,
            hi: size,
        })
    }

    pub fn holds(&self, addr: usize, n: usize) -> bool {
        self.lo <= addr && addr + n <= self.hi
    }
}

/// What the loader says about the chip.
#[derive(Debug, Clone, Copy)]
pub struct Chip {
    pub key: u16,
    pub flash_id: u32,
    pub size: usize,
    pub io: usize,
}

/// The boot state's protocol over a mass-storage transport. Without a window nothing can be erased or written.
pub struct Uboot<'a> {
    msc: &'a mut dyn Msc,
    window: Option<Window>,
}

impl<'a> Uboot<'a> {
    pub fn new(msc: &'a mut dyn Msc) -> Self {
        Uboot { msc, window: None }
    }

    fn command(&mut self, op: u16, args: &[u8], out: Option<&[u8]>, in_len: usize, how: How) -> Result<Vec<u8>, Error> {
        if !READ_ONLY_OPS.contains(&op) && !(self.window.is_some() && WRITE_OPS.contains(&op)) {
            return Err(Error::Refused(format!("command {op:04X} is not allowed in this run")));
        }
        let mut cdb = op.to_be_bytes().to_vec();
        cdb.extend_from_slice(args);
        cdb.resize(16, 0xFF);
        let mut err = None;
        for _ in 0..how.tries {
            let data = match self
                .msc
                .execute(&cdb, out, if how.answer { 16 } else { in_len }, how.timeout)
            {
                Ok(data) => data,
                Err(e @ Error::Gone(_)) => return Err(e),
                Err(e @ Error::Transfer(_)) => {
                    err = Some(e);
                    continue;
                }
                Err(e) => return Err(e),
            };
            if how.answer && (data.len() != 16 || u16::from_be_bytes([data[0], data[1]]) != op) {
                err = Some(Error::Transfer(format!("command {op:04X}: wrong answer")));
                continue;
            }
            if !how.answer && data.len() != in_len {
                err = Some(Error::Transfer(format!(
                    "command {op:04X}: {} of {in_len} bytes",
                    data.len()
                )));
                continue;
            }
            return Ok(if how.answer { data[2..].to_vec() } else { data });
        }
        Err(err.unwrap_or_else(|| Error::Transfer(format!("command {op:04X}: not sent"))))
    }

    /// SCSI INQUIRY: (vendor, product, revision).
    pub fn inquiry(&mut self) -> Result<(String, String, String), Error> {
        let data = self.msc.execute(&[0x12, 0, 0, 0, 0x24, 0], None, 36, 1000)?;
        let text = |a: usize, b: usize| {
            let s: String = fw::slice(&data, a, b)
                .iter()
                .map(|&c| if c < 0x80 { c as char } else { '\u{FFFD}' })
                .collect();
            s.trim().to_string()
        };
        Ok((text(8, 16), text(16, 32), text(32, 36)))
    }

    pub fn mem_write(&mut self, addr: u32, data: &[u8]) -> Result<(), Error> {
        if !(LOADER_AT <= addr && addr as usize + data.len() <= LOADER_AT as usize + LOADER_SIZE) {
            return Err(Error::Refused(format!(
                "memory write at {addr:#x}: only the loader's RAM may be written"
            )));
        }
        let mut args = addr.to_be_bytes().to_vec();
        args.extend_from_slice(&(data.len() as u16).to_be_bytes());
        args.push(0);
        args.extend_from_slice(&crc16(data, 0).to_le_bytes());
        self.command(WRITE_MEMORY, &args, Some(data), 0, How::DATA).map(drop)
    }

    /// Run the loader. Its answer may be lost; it runs when the chip key answers.
    pub fn jump(&mut self) -> Result<(), Error> {
        let mut args = LOADER_AT.to_be_bytes().to_vec();
        args.extend_from_slice(&1u16.to_be_bytes());
        ignore_transfer(self.command(
            JUMP,
            &args,
            None,
            0,
            How {
                tries: 1,
                ..How::ANSWER
            },
        ))
    }

    pub fn chip_key(&mut self) -> Result<u16, Error> {
        let a = self.command(READ_KEY, &0xAC6900u32.to_be_bytes(), None, 0, How::ANSWER)?;
        let k = cipher(&[a[5], a[4]]);
        Ok(k[0] as u16 | (k[1] as u16) << 8)
    }

    pub fn online_device(&mut self) -> Result<u32, Error> {
        let a = self.command(ONLINE_DEVICE, &[], None, 0, How::ANSWER)?;
        Ok(u32::from_le_bytes([a[2], a[3], a[4], a[5]]))
    }

    pub fn usb_buffer(&mut self) -> Result<u32, Error> {
        let a = self.command(
            USB_BUFFER,
            &[],
            None,
            0,
            How {
                tries: 2,
                timeout: 1000,
                ..How::ANSWER
            },
        )?;
        Ok(u32::from_be_bytes([a[0], a[1], a[2], a[3]]))
    }

    pub fn flash_read(&mut self, addr: usize, n: usize) -> Result<Vec<u8>, Error> {
        let mut args = (addr as u32).to_be_bytes().to_vec();
        args.extend_from_slice(&(n as u16).to_be_bytes());
        self.command(READ_FLASH, &args, None, n, How::DATA)
    }

    pub fn erase_sector(&mut self, addr: usize) -> Result<(), Error> {
        if !self
            .window
            .is_some_and(|w| addr.is_multiple_of(SECTOR) && w.holds(addr, SECTOR))
        {
            return Err(Error::Refused(format!("erase at {addr:#x} refused")));
        }
        let args = (addr as u32).to_be_bytes();
        self.command(
            ERASE_SECTOR,
            &args,
            None,
            0,
            How {
                timeout: 5000,
                ..How::ANSWER
            },
        )
        .map(drop)
    }

    pub fn flash_write(&mut self, addr: usize, data: &[u8]) -> Result<(), Error> {
        let fits = !data.is_empty() && addr % SECTOR + data.len() <= SECTOR;
        if !self.window.is_some_and(|w| fits && w.holds(addr, data.len())) {
            return Err(Error::Refused(format!("write at {addr:#x} refused")));
        }
        let mut args = (addr as u32).to_be_bytes().to_vec();
        args.extend_from_slice(&(data.len() as u16).to_be_bytes());
        args.push(0);
        args.extend_from_slice(&crc16(data, 0).to_le_bytes());
        self.command(WRITE_FLASH, &args, Some(data), 0, How::DATA).map(drop)
    }

    /// The pedal restarts into its firmware; it may restart before it answers.
    pub fn run_app(&mut self) -> Result<(), Error> {
        let how = How {
            tries: 1,
            timeout: 500,
            ..How::ANSWER
        };
        ignore_transfer(self.command(RUN_APP, &1u32.to_be_bytes(), None, 0, how))
    }

    pub fn read_range(&mut self, addr: usize, n: usize, io: usize) -> Result<Vec<u8>, Error> {
        let mut out = Vec::with_capacity(n);
        for a in (addr..addr + n).step_by(io) {
            out.extend(self.flash_read(a, io.min(addr + n - a))?);
        }
        Ok(out)
    }

    /// Erase, write in 512-byte pieces, read back and compare. NOR flash: a failed attempt is simply repeated.
    pub fn write_sector(&mut self, addr: usize, data: &[u8]) -> Result<(), Error> {
        for _ in 0..3 {
            self.erase_sector(addr)?;
            for off in (0..SECTOR).step_by(IO) {
                self.flash_write(addr + off, &data[off..off + IO])?;
            }
            if self.read_range(addr, SECTOR, IO)? == data {
                return Ok(());
            }
        }
        Err(Error::Refused(format!(
            "sector {addr:#x} reads back differently after 3 attempts"
        )))
    }
}

/// How one command is sent: with a 16-byte answer or a data phase, how many tries, its timeout in milliseconds.
#[derive(Clone, Copy)]
struct How {
    answer: bool,
    tries: u32,
    timeout: u32,
}

impl How {
    const ANSWER: How = How {
        answer: true,
        tries: 3,
        timeout: 2000,
    };
    const DATA: How = How {
        answer: false,
        tries: 3,
        timeout: 2000,
    };
}

/// A lost answer is not an error (`except ScsiError: pass`, which also covers a pedal that left the bus).
fn ignore_transfer(r: Result<Vec<u8>, Error>) -> Result<(), Error> {
    match r {
        Ok(_) | Err(Error::Transfer(_) | Error::Gone(_)) => Ok(()),
        Err(e) => Err(e),
    }
}

/// Steps 1 and 2: INQUIRY, the loader into RAM, run it, the chip key and the flash id. Refuses the wrong device, key or
/// size.
pub fn attach(dev: &mut Uboot, loader: &[u8], log: &mut dyn FnMut(&str)) -> Result<Chip, Error> {
    let mut found = None;
    for _ in 0..50 {
        match dev.inquiry() {
            Ok(v) => {
                found = Some(v);
                break;
            }
            Err(e @ Error::Gone(_)) => return Err(e),
            Err(Error::Transfer(_)) => std::thread::sleep(std::time::Duration::from_millis(200)),
            Err(e) => return Err(e),
        }
    }
    let (vendor, product, rev) = found.ok_or_else(|| Error::Transfer("the pedal does not answer INQUIRY".into()))?;
    log(&format!("INQUIRY: {vendor} {product} {rev}"));
    if vendor != "WL82" || !product.starts_with("UBOOT1.00") {
        return Err(Error::Refused(format!(
            "this is not the WL82 UBOOT1.00 boot state ({} {})",
            py_repr(&vendor),
            py_repr(&product)
        )));
    }
    for (i, piece) in loader.chunks(IO).enumerate() {
        dev.mem_write(LOADER_AT + (i * IO) as u32, piece)?;
    }
    let mut key = None;
    for _ in 0..3 {
        dev.jump()?;
        match dev.chip_key() {
            Ok(k) => {
                key = Some(k);
                break;
            }
            Err(e @ Error::Gone(_)) => return Err(e),
            Err(Error::Transfer(_)) => {}
            Err(e) => return Err(e),
        }
    }
    let key = key.ok_or_else(|| Error::Transfer("the loader did not start".into()))?;
    let flash_id = dev.online_device()?;
    let low = flash_id & 0xFF;
    let size = if (0x10..=0x18).contains(&low) { 1usize << low } else { 0 };
    log(&format!(
        "loader running: chip key {key:#06x}, flash id {flash_id:#08x} ({} KiB)",
        size / 1024
    ));
    if key != CHIP_KEY {
        return Err(Error::Refused(format!(
            "chip key {key:#06x} is not {CHIP_KEY:#06x}: this is not a BlackBox, nothing was written"
        )));
    }
    if size != FLASH_SIZE {
        return Err(Error::Refused(format!(
            "flash id {flash_id:#08x} is not a 1 MiB flash: nothing was written"
        )));
    }
    // as big as the loader's USB buffer allows (fm1buddy: two readings of 1 MiB at 512 B took 8 s)
    let mut top = match dev.usb_buffer() {
        Ok(b) => (b as usize).min(0x8000) / IO * IO,
        Err(e) if e.is_transfer() => IO,
        Err(e) => return Err(e),
    };
    let mut io = IO;
    while top > IO {
        match dev.flash_read(0, top) {
            Ok(d) if d.len() == top => {
                io = top;
                break;
            }
            Ok(_) | Err(Error::Transfer(_)) => {}
            Err(e) => return Err(e),
        }
        top /= 2;
    }
    Ok(Chip {
        key,
        flash_id,
        size,
        io,
    })
}

/// Python's `repr` of a short ASCII string, for the refusal's words.
pub(crate) fn py_repr(s: &str) -> String {
    if s.contains('\'') && !s.contains('"') {
        format!("\"{s}\"")
    } else {
        format!("'{}'", s.replace('\'', "\\'"))
    }
}

/// What a plan decided once the pedal's flash was read: the image the flash should hold from 0, the only window that
/// may be written, and the SHA-256 of what the person agrees to have written (None: this plan never writes).
pub struct Planned {
    pub image: Vec<u8>,
    pub window: Window,
    pub source: Option<[u8; 32]>,
    /// The file the image came from, when the plan chose one of several.
    pub file: Option<String>,
    /// The pedal's flash layout, when the plan named it.
    pub layout: Option<Layout>,
}

/// Decides, from the chip and the whole flash, what the flash should hold; or refuses this pedal.
pub type Plan<'a> = dyn FnMut(&Chip, &[u8]) -> Result<Planned, Error> + 'a;

pub fn sha256(data: &[u8]) -> [u8; 32] {
    Sha256::digest(data).into()
}

/// `uboot_rescue.whole_image`: the flash should hold `image` from 0, and [0x4000, its end) may be written.
pub fn whole_image(image: Vec<u8>) -> Result<Box<Plan<'static>>, Error> {
    let window = Window::for_image(image.len())?;
    let source = Some(sha256(&image));
    Ok(Box::new(move |_: &Chip, _: &[u8]| {
        Ok(Planned {
            image: image.clone(),
            window,
            source,
            file: None,
            layout: None,
        })
    }))
}

/// `undertone.matching`: of several rescue images, the first whose head [0, 0x4000) is the pedal's, else the first,
/// which the head check then refuses as always.
pub fn matching(images: Vec<(String, Vec<u8>)>) -> Result<Box<Plan<'static>>, Error> {
    if images.is_empty() {
        return Err(Error::Setup("no image to compare the pedal with".into()));
    }
    for (_, image) in &images {
        Window::for_image(image.len())?;
    }
    Ok(Box::new(move |_: &Chip, flash: &[u8]| {
        let (name, image) = images
            .iter()
            .find(|(_, i)| flash[..WRITE_FROM] == i[..WRITE_FROM])
            .unwrap_or(&images[0]);
        let window = Window::for_image(image.len())?;
        Ok(Planned {
            image: image.clone(),
            window,
            source: Some(sha256(image)),
            file: Some(name.clone()),
            layout: None,
        })
    }))
}

/// A plan that compares the pedal with its own flash: it names the pedal and never writes (`undertone check`).
pub fn own_flash() -> Box<Plan<'static>> {
    Box::new(|chip: &Chip, flash: &[u8]| {
        let image = flash[..WRITE_LIMIT.min(chip.size)].to_vec();
        Ok(Planned {
            window: Window::for_image(image.len())?,
            image,
            source: None,
            file: None,
            layout: None,
        })
    })
}

/// What a whole run did.
#[derive(Debug)]
pub struct Report {
    /// The sectors that differ from the image (and, in a write, were written).
    pub sectors: usize,
    /// The backup of the whole flash, saved before anything else.
    pub backup: PathBuf,
    /// The whole flash as read.
    pub flash: Vec<u8>,
    /// The file whose image the pedal matched, when the plan chose one of several.
    pub file: Option<String>,
    /// The pedal's flash layout, when the plan named it.
    pub layout: Option<Layout>,
    pub(crate) source: Option<[u8; 32]>,
    pub(crate) wrote: bool,
}

/// Saves the backup on the first pass that reads the flash, and says where; None on a later pass.
type SaveOnce<'a> = dyn FnMut(&[u8]) -> Result<Option<PathBuf>, Error> + 'a;

/// One try at steps 1 to 6 on an open device. Returns the sectors that differ (and were written) and the source.
fn rescue_pass(
    msc: &mut dyn Msc,
    loader: &[u8],
    plan: &mut Plan,
    write: Option<&Confirmed>,
    save_backup: &mut SaveOnce,
    log: &mut dyn FnMut(&str),
) -> Result<(usize, Vec<u8>, Planned), Error> {
    let mut dev = Uboot::new(msc);
    let chip = attach(&mut dev, loader, log)?;
    let flash = dev.read_range(0, chip.size, chip.io)?;
    log(&format!("flash read: {} KiB", flash.len() / 1024));
    if let Some(path) = save_backup(&flash)? {
        log(&format!("backup saved: {}", path.display()));
    }
    dev.online_device()?;
    let planned = plan(&chip, &flash)?;
    let Planned {
        image, window, source, ..
    } = &planned;
    let window = *window;
    if flash[..window.lo] != image[..window.lo] {
        return Err(Error::Refused(format!(
            "the flash head [0, {:#x}) is not the image's head: this package belongs to another layout; nothing was \
             written",
            window.lo
        )));
    }
    log(&format!("head [0, {:#x}) matches the image", window.lo));
    let todo: Vec<usize> = (window.lo..window.hi)
        .step_by(SECTOR)
        .filter(|&a| flash[a..a + SECTOR] != image[a..a + SECTOR])
        .collect();
    log(&format!(
        "{} of {} sectors in [{:#x}, {:#x}) differ",
        todo.len(),
        (window.hi - window.lo) / SECTOR,
        window.lo,
        window.hi
    ));
    if let Some(confirmed) = write {
        if *source != Some(confirmed.source) {
            return Err(Error::Refused(
                "the write was confirmed for another file than this run's; nothing was written".into(),
            ));
        }
        dev.window = Some(window);
        for (n, &addr) in todo.iter().enumerate() {
            dev.write_sector(addr, &image[addr..addr + SECTOR])?;
            if (n + 1) % 16 == 0 || n + 1 == todo.len() {
                log(&format!("  written {}/{}", n + 1, todo.len()));
            }
        }
    }
    dev.run_app()?;
    log("run-app sent: the pedal restarts");
    Ok((todo.len(), flash, planned))
}

/// Runs the passes until one completes; each is safe to repeat, since only differing sectors are written. Without a
/// confirmation nothing is erased or written. `open_device` waits for the pedal; `save_backup` writes the whole flash
/// to a file and returns where, and is called once, before the plan is even computed.
pub fn rescue(
    open_device: &mut dyn FnMut() -> Result<Box<dyn Msc>, Error>,
    loader: &[u8],
    plan: &mut Plan,
    write: Option<Confirmed>,
    save_backup: &mut dyn FnMut(&[u8]) -> Result<PathBuf, Error>,
    attempts: u32,
    log: &mut dyn FnMut(&str),
) -> Result<Report, Error> {
    let mut saved: Option<PathBuf> = None;
    for attempt in 1..=attempts {
        let mut msc = open_device()?;
        let mut save = |flash: &[u8]| -> Result<Option<PathBuf>, Error> {
            if saved.is_some() {
                return Ok(None);
            }
            let path = save_backup(flash)?;
            saved = Some(path.clone());
            Ok(Some(path))
        };
        let pass = rescue_pass(msc.as_mut(), loader, plan, write.as_ref(), &mut save, log);
        drop(msc);
        match pass {
            Ok((sectors, flash, planned)) => {
                let backup = saved.expect("a pass that completes has saved the backup");
                let Planned {
                    source, file, layout, ..
                } = planned;
                return Ok(Report {
                    sectors,
                    backup,
                    flash,
                    file,
                    layout,
                    source,
                    wrote: write.is_some(),
                });
            }
            Err(e) if e.is_transfer() => log(&format!(
                "the pedal went away or stopped answering ({}); waiting for it again ({attempt}/{attempts})",
                e.message()
            )),
            Err(e) => return Err(e),
        }
    }
    Err(Error::Setup(format!(
        "gave up after {attempts} tries; rerun the command, it resumes where it stopped"
    )))
}

/// Polls until the chip's USB boot state is on the bus and claims it at once: the window is only about 44 s
/// (`uboot_rescue.wait_for_pedal`).
pub fn wait_for_pedal(bus: &mut dyn Bus, windows: bool, log: &mut dyn FnMut(&str)) -> Result<Box<dyn Msc>, Error> {
    let mut announced = false;
    loop {
        if let Some(msc) = bus.open_uboot()? {
            return Ok(msc);
        }
        if !announced {
            log(&format!(
                "waiting for the pedal in its UBOOT state (USB 4C4A:8057; plug it straight into this computer){}",
                if windows {
                    ". If Windows offers to format a drive, click Cancel"
                } else {
                    ""
                }
            ));
            announced = true;
        }
        let poll = bus.poll();
        bus.sleep(poll)?;
    }
}

/// `uboot_rescue.load_image` for a package's bytes: its flash.bin, every CRC verified first.
pub fn package_image(raw: &[u8], name: &str) -> Result<Vec<u8>, Error> {
    let not = |Unreadable(m)| Error::Setup(format!("{name}: not a firmware package ({m})"));
    let package = Package::read(raw).map_err(not)?;
    let failed = package.checks();
    let failed = failed.failed();
    if !failed.is_empty() {
        return Err(Error::Setup(format!(
            "{name}: CRC check failed ({}); not using it",
            failed.join(", ")
        )));
    }
    let data = package
        .file("flash.bin")
        .ok_or_else(|| Error::Setup(format!("{name}: no flash.bin in it")))?;
    Window::for_image(data.len())?;
    Ok(data.to_vec())
}

/// `uboot_rescue.get_loader`'s check: the pinned wl82loader.bin, or why not.
pub fn check_loader(blob: &[u8], where_: &str) -> Result<(), Error> {
    if hex(&sha256(blob)) != LOADER_SHA256 || blob.len() != LOADER_SIZE {
        return Err(Error::Setup(format!(
            "{where_} is not the pinned wl82loader.bin (SHA-256 {LOADER_SHA256}); not using it"
        )));
    }
    Ok(())
}

pub fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
