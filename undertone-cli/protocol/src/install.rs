// SPDX-License-Identifier: GPL-3.0-only
//! The install through the chip's USB boot state on both flash layouts, as tools/uboot_install.py plans it: the pedal's
//! layout named by the CRC-32 of its boot area, an image composed of the pedal's own boot area and the app area given,
//! and only that app area written. Also the way to the boot state from M-VAVE's recovery mode: one hello, the leave.
use crate::crc::crc32;
use crate::fw::{Package, Unreadable, check_area};
use crate::recovery::{self, RECOVERY, Recovery};
use crate::uboot::{Chip, FLASH_SIZE, Plan, Planned, SECTOR, Window, hex, sha256};
use crate::{Bus, Error, Msc};

/// A flash layout of the official firmware.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Layout {
    pub name: String,
    /// The app area starts here; [0, base) is the boot area, never written.
    pub base: usize,
    /// Nothing from here up is written: its newest firmware's stock settings.
    pub limit: usize,
    /// CRC-32 of the boot area.
    pub boot_crc: u32,
    /// The supply levels Gamut finds, as its boot screen shows them.
    pub levels: String,
}

/// The two layouts, and the only ones accepted.
pub fn layouts() -> Vec<Layout> {
    vec![
        Layout {
            name: "the old head (M-VAVE V16, V17 and V20)".into(),
            base: 0x4000,
            limit: 0xA5000,
            boot_crc: 0x5A21_21FF,
            levels: "3 11".into(),
        },
        Layout {
            name: "M-VAVE's V22/V23 head".into(),
            base: 0x6000,
            limit: 0x9F000,
            boot_crc: recovery::V23_HEAD,
            levels: "7 15".into(),
        },
    ]
}

/// The heads the recovery mode's hello may name, in words.
pub const HEADS: [(u32, &str); 1] = [(
    recovery::V23_HEAD,
    "M-VAVE V22 or V23 (the boot area of both official packages)",
)];

/// The flash ids seen on a real pedal, and the other one the V22/V23 boot loader accepts.
pub const FLASH_IDS: [u32; 2] = [0x85_6014, 0xEB_6014];

/// Seconds to wait for the chip's USB boot state after the leave. tools/uboot_install.py waits 10 s, but on the owner's
/// pedal the boot state once appeared 70,056 ms after the leave (DESIGN.md, rule 11). Nothing is sent while it waits.
pub const LEAVE_WAIT: f64 = 75.0;

/// The layout of a flash image that starts at 0, by its boot area's CRC-32. Refused for any other head.
pub fn layout_of<'l>(flash: &[u8], whose: &str, layouts: &'l [Layout]) -> Result<&'l Layout, Error> {
    if let Some(l) = layouts
        .iter()
        .find(|l| flash.len() >= l.base && crc32(&flash[..l.base], 0) == l.boot_crc)
    {
        return Ok(l);
    }
    let crc = |l: &Layout| crc32(&flash[..l.base.min(flash.len())], 0);
    let seen: Vec<String> = layouts
        .iter()
        .map(|l| format!("[0, {:#x}) {:#010x}", l.base, crc(l)))
        .collect();
    let known: Vec<String> = layouts
        .iter()
        .map(|l| format!("{}, {:#010x}", l.name, l.boot_crc))
        .collect();
    Err(Error::Refused(format!(
        "{whose} boot area is not one this tool knows (CRC-32 of {}; known: {}). An app area written to the wrong place \
         overwrites a boot loader, so nothing is written to another head",
        seen.join(", "),
        known.join("; ")
    )))
}

/// The app area to write. `boot`: the boot area the pedal must hold, byte for byte, when the area belongs to one (an
/// official package's, a backup's); None for Gamut's area, which is the same on every known layout.
#[derive(Debug, Clone)]
pub struct Source {
    pub what: String,
    pub area: Vec<u8>,
    pub boot: Option<Vec<u8>>,
}

/// Where the release pin is kept, for the refusal's words.
pub const GAMUT_PIN: &str = "firmware/apps/gamut/release.sha256";

/// The file and SHA-256 of Gamut's app area (`*-v23.bin`) in the release pin's text.
pub fn gamut_pin(text: &str) -> Option<(&str, &str)> {
    text.lines()
        .filter_map(|line| line.split_once("  "))
        .map(|(digest, name)| (name, digest))
        .find(|(name, _)| name.ends_with("-v23.bin"))
}

/// Gamut's app area: the bytes of the release pin (`digest`), and no other build.
pub fn gamut_area(area: Vec<u8>, name: &str, digest: &str, layouts: &[Layout]) -> Result<Source, Error> {
    if hex(&sha256(&area)) != digest {
        return Err(Error::Refused(format!(
            "{name} is not the Gamut app area of the release pin (SHA-256 {digest}, in {GAMUT_PIN}): only the pinned \
             release is installed this way"
        )));
    }
    let room = layouts.iter().map(|l| l.limit - l.base).min().unwrap_or(0);
    let identity = check_area(&area, 0, room)?;
    let identity = identity.as_deref().unwrap_or("None");
    Ok(Source {
        what: format!("Gamut's app area {name}, identity {identity}"),
        area,
        boot: None,
    })
}

/// The app area of a flash image that carries its own boot area: an official flash.bin, or a backup.
pub fn flash_source(image: &[u8], what: &str, whose: &str, layouts: &[Layout]) -> Result<Source, Error> {
    let layout = layout_of(image, whose, layouts)?;
    let area = crate::fw::slice(image, layout.base, layout.limit).to_vec();
    if let Err(e) = check_area(&area, layout.base, layout.limit) {
        return Err(Error::Refused(format!(
            "{whose} app area at {:#x} is not one the boot loader would start: {}",
            layout.base,
            e.message()
        )));
    }
    Ok(Source {
        what: format!("{what}, for {}", layout.name),
        area,
        boot: Some(image[..layout.base].to_vec()),
    })
}

/// M-VAVE's app area from its official BlackBox package, every CRC of the package checked first.
pub fn official_area(raw: &[u8], name: &str, layouts: &[Layout]) -> Result<Source, Error> {
    let unreadable = |Unreadable(m)| Error::Refused(format!("{name}: not a readable package ({m})"));
    let package = Package::read(raw).map_err(unreadable)?;
    let checks = package.checks();
    let failed = checks.failed();
    if !failed.is_empty() {
        return Err(Error::Refused(format!(
            "{name}: the package is damaged ({})",
            failed.join(", ")
        )));
    }
    let tag = &package.tag;
    let number = tag
        .strip_prefix("BlackBox_")
        .filter(|n| !n.is_empty() && n.bytes().all(|b| b.is_ascii_digit()));
    if !number.is_some_and(|n| n.parse::<u64>().is_ok_and(|n| n < 900)) {
        return Err(Error::Refused(format!(
            "{name} (identity {}) is not one of M-VAVE's official BlackBox packages",
            crate::uboot::py_repr(tag)
        )));
    }
    let flash = package
        .file("flash.bin")
        .ok_or_else(|| unreadable(Unreadable("no flash.bin in it".into())))?;
    flash_source(
        flash,
        &format!("M-VAVE's app area from {name} ({tag})"),
        &format!("{name}: its"),
        layouts,
    )
}

/// The app area of a whole-flash backup (`blackbox-<time>.dump.bin`) that undertone or uboot_rescue.py saved.
pub fn backup_area(dump: &[u8], name: &str, layouts: &[Layout]) -> Result<Source, Error> {
    if dump.len() != FLASH_SIZE {
        return Err(Error::Refused(format!(
            "{name} is {} bytes, not a backup of the whole 1 MiB flash",
            dump.len()
        )));
    }
    flash_source(
        dump,
        &format!("the app area of the backup {name}"),
        &format!("{name}: its"),
        layouts,
    )
}

/// The [start, end) runs of 4 KiB sectors in [lo, hi) where flash and image differ.
fn runs(flash: &[u8], image: &[u8], lo: usize, hi: usize) -> Vec<(usize, usize)> {
    let mut out: Vec<(usize, usize)> = Vec::new();
    for a in (lo..hi).step_by(SECTOR) {
        if flash[a..a + SECTOR] != image[a..a + SECTOR] {
            match out.last_mut() {
                Some(run) if run.1 == a => run.1 = a + SECTOR,
                _ => out.push((a, a + SECTOR)),
            }
        }
    }
    out
}

/// The plan of an install: once the pedal's flash is read, the image it should hold (its own boot area, then the
/// source's app area) and the only window that may be written; or a refusal.
pub fn plan_for<'a>(source: &'a Source, layouts: &'a [Layout], log: &'a mut dyn FnMut(&str)) -> Box<Plan<'a>> {
    let digest = sha256(&source.area);
    Box::new(move |chip: &Chip, flash: &[u8]| {
        if !FLASH_IDS.contains(&chip.flash_id) {
            let known: Vec<String> = FLASH_IDS.iter().map(|i| format!("{i:#08x}")).collect();
            return Err(Error::Refused(format!(
                "flash id {:#08x} is not one this tool knows ({}): nothing was written",
                chip.flash_id,
                known.join(", ")
            )));
        }
        let layout = layout_of(flash, "the pedal's", layouts)?;
        log(&format!(
            "boot area [0, {:#x}) CRC-32 {:#010x}: {}; its app area is in [{:#x}, {:#x})",
            layout.base, layout.boot_crc, layout.name, layout.base, layout.limit
        ));
        if source.boot.as_deref().is_some_and(|boot| boot != &flash[..layout.base]) {
            return Err(Error::Refused(format!(
                "{}: its boot area is not this pedal's, which has {}. Written here it would not start, or would \
                 overwrite the end of the boot loader; nothing was written",
                source.what, layout.name
            )));
        }
        let end = layout.base + source.area.len();
        if end > layout.limit {
            return Err(Error::Refused(format!(
                "{} would end at {end:#x}, past {:#x}; nothing was written",
                source.what, layout.limit
            )));
        }
        log(&format!(
            "image: the pedal's own boot area, then {} in [{:#x}, {end:#x})",
            source.what, layout.base
        ));
        let mut image = flash[..layout.base].to_vec();
        image.extend_from_slice(&source.area);
        let differ: Vec<String> = runs(flash, &image, layout.base, end)
            .iter()
            .map(|(lo, hi)| format!("[{lo:#x}, {hi:#x})"))
            .collect();
        log(&format!(
            "the sectors that differ, the only ones --write erases and writes: {}",
            if differ.is_empty() {
                "none".to_string()
            } else {
                differ.join(" ")
            }
        ));
        Ok(Planned {
            image,
            window: Window {
                lo: layout.base,
                hi: end,
            },
            source: Some(digest),
            file: None,
            layout: Some(layout.clone()),
        })
    })
}

pub const WAITING: &str = "\
waiting for the pedal; nothing is sent until it appears. Either:
  - a BlackBox on M-VAVE's V22 or V23 head: switch it off, hold HOME, the right footswitch and the knob's PUSH, switch
    it on and keep holding until the screen shows RECOVERY (USB 3654:7940). The tool then sends the leave by itself
  - a pedal already in the chip's USB boot state (USB 4C4A:8057): it is taken as it is
Plug it straight into this computer, with no hub.";

pub const FIRST_RUN: &str = "\
First-run check (docs/RESCUE.md): power-cycle the pedal. The boot screen's line PWR shows the supply levels the boot
loader left; on this pedal it should read `PWR {levels} (BOOT LEVELS)`. Then, with the pedal on USB:
    node tools/op.mjs dsp 2>&1 | tee gamut-dsp.log
It plays every saved preset for 6 s and reads the load, the peak, the late blocks and the bypass; exit 0 means no
preset was late or bypassed. Play through each preset and listen for crackles.";

/// Did a failed transfer mean the pedal left the bus? A listing only: nothing more is sent to it.
fn left_bus(bus: &mut dyn Bus, error: &Error) -> Result<bool, Error> {
    Ok(matches!(error, Error::Gone(_)) || !bus.present()?.contains(&RECOVERY))
}

/// From M-VAVE's recovery mode to the chip's USB boot state: the hello, the single leave, then the boot state taken the
/// moment it appears. None when the recovery mode ended before the leave was sent. `say` prints a line with its time in
/// milliseconds since the device was found.
pub fn leave(
    bus: &mut dyn Bus,
    layouts: &[Layout],
    heads: &[(u32, &str)],
    say: &mut dyn FnMut(&str),
) -> Result<Option<Box<dyn Msc>>, Error> {
    let Some(mut dev) = bus.open_recovery()? else {
        return Ok(None);
    };
    let clock = bus.clock();
    let found = clock();
    let stamp = clock.clone();
    let mut stamped = move |m: &str| say(&format!("[{:6.0} ms] {m}", (stamp() - found) * 1000.0));
    let (manufacturer, product) = dev.names();
    stamped(&format!(
        "found {:04X}:{:04X} {}: M-VAVE's recovery mode",
        recovery::VID,
        recovery::PID,
        recovery::names(&manufacturer, &product)
    ));
    let (result, sent, since) = {
        let mut session = Recovery::new(dev.as_mut(), &mut stamped, clock.clone());
        let result = hello_and_leave(&mut session, layouts, heads);
        (result, session.sent, session.since(clock()))
    };
    drop(dev);
    match result {
        Ok(()) => {}
        Err(e) if e.is_transfer() => {
            if !left_bus(bus, &e)? {
                return Err(e);
            }
            if sent.map(|s| s.0) != Some(recovery::LEAVE) {
                stamped(&format!(
                    "the pedal left the bus ({}), {since}: the recovery mode ended before the leave was sent. It ends \
                     about 4 s after power-on. Enter it again; this tool is still waiting",
                    e.message()
                ));
                return Ok(None);
            }
        }
        Err(e) => return Err(e),
    }
    let sent = sent.map_or(found, |s| s.2);
    stamped("leave sent: waiting for the chip's USB boot state (USB 4C4A:8057)");
    while clock() - sent < LEAVE_WAIT {
        if let Some(msc) = bus.open_uboot()? {
            stamped(&format!(
                "the chip's USB boot state appeared {:.0} ms after the leave",
                (clock() - sent) * 1000.0
            ));
            return Ok(Some(msc));
        }
        let poll = bus.poll();
        bus.sleep(poll)?;
    }
    if bus.present()?.contains(&RECOVERY) {
        return Err(Error::StayedInRecovery(format!(
            "the pedal stayed in the recovery mode for {LEAVE_WAIT} s after the leave: it did not act on it. Nothing \
             was written; send this output back"
        )));
    }
    Err(Error::NoBootState(format!(
        "the chip's USB boot state did not appear within {LEAVE_WAIT} s of the leave. Nothing was written. If RECOVERY \
         had been on the screen for some seconds, the pedal's own reset came first: run this again and enter the \
         recovery mode only once it is waiting. If the pedal restarts into its firmware every time, send this output \
         back"
    )))
}

/// The hello, its reply in words, the check of the head it names, and the leave.
fn hello_and_leave(session: &mut Recovery, layouts: &[Layout], heads: &[(u32, &str)]) -> Result<(), Error> {
    let (hello, bulk) = session.probe()?;
    recovery::describe(&hello, bulk.as_deref(), heads, &mut |m| session.say(m));
    let known = |l: &Layout| (l.boot_crc, l.base as u32, l.limit as u32) == (hello.boot_crc, hello.base, hello.limit);
    if !layouts.iter().any(known) {
        return Err(Error::Refused(format!(
            "the pedal's boot area CRC-32 {:#010x} is not a head this tool knows: the leave is not sent, and the pedal \
             restarts by itself",
            hello.boot_crc
        )));
    }
    if bulk.is_some() {
        session.say(
            "the hello reply came over the control endpoint only, as on the one real pedal tried, which acted on the \
             leave all the same",
        );
    }
    session.leave(&hello)?;
    Ok(())
}

/// The pedal in the chip's USB boot state, claimed. Waits for it, or for M-VAVE's recovery mode, and sends nothing until
/// one of them is on the bus. `log` prints with the boot state's time stamp, `say` with the recovery session's.
pub fn boot_state(
    bus: &mut dyn Bus,
    layouts: &[Layout],
    heads: &[(u32, &str)],
    log: &mut dyn FnMut(&str),
    say: &mut dyn FnMut(&str),
) -> Result<Box<dyn Msc>, Error> {
    let mut told = false;
    loop {
        let mut msc = bus.open_uboot()?;
        if msc.is_none() && bus.present()?.contains(&RECOVERY) {
            msc = leave(bus, layouts, heads, say)?;
            told = false;
        }
        if let Some(msc) = msc {
            return Ok(msc);
        }
        if !told {
            log(WAITING);
            told = true;
        }
        let poll = bus.poll();
        bus.sleep(poll)?;
    }
}
