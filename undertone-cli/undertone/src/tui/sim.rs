// SPDX-License-Identifier: GPL-3.0-only
//! The guided screens against a simulated pedal, for a run of the real program in a pseudo-terminal: built only with
//! the `sim` feature, and chosen with UNDERTONE_SIM=rescue|install|check. The pedal is the protocol library's simulated
//! one, slowed a little so that the spinner and the bar can be seen; nothing reaches a real pedal.
use std::collections::BTreeSet;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use undertone_protocol::crc::crc32;
use undertone_protocol::install::{self, Source};
use undertone_protocol::sim::{Bench, Start, app_area, flash_image, noise, package};
use undertone_protocol::uboot::{FLASH_SIZE, LOADER_SIZE};
use undertone_protocol::{Bus, Clock, Error, Msc, RecoveryDevice};

use super::guide::World;

struct Slow(Bench);

struct SlowMsc(Box<dyn Msc>);

impl Msc for SlowMsc {
    fn execute(&mut self, cdb: &[u8], out: Option<&[u8]>, in_len: usize, timeout: u32) -> Result<Vec<u8>, Error> {
        std::thread::sleep(Duration::from_micros(700));
        self.0.execute(cdb, out, in_len, timeout)
    }
}

impl Bus for Slow {
    fn poll(&self) -> f64 {
        self.0.poll()
    }

    fn clock(&self) -> Clock {
        self.0.clock()
    }

    fn sleep(&mut self, seconds: f64) -> Result<(), Error> {
        std::thread::sleep(Duration::from_secs_f64(seconds.min(0.05)));
        self.0.sleep(seconds)
    }

    fn open_uboot(&mut self) -> Result<Option<Box<dyn Msc>>, Error> {
        Ok(self.0.open_uboot()?.map(|m| Box::new(SlowMsc(m)) as Box<dyn Msc>))
    }

    fn open_recovery(&mut self) -> Result<Option<Box<dyn RecoveryDevice>>, Error> {
        self.0.open_recovery()
    }

    fn present(&mut self) -> Result<BTreeSet<(u16, u16)>, Error> {
        self.0.present()
    }
}

pub fn world() -> Option<World> {
    let scenario = std::env::var("UNDERTONE_SIM").ok()?;
    let root = std::env::temp_dir().join(format!("undertone-sim-{}", std::process::id()));
    let firmware = root.join("firmware");
    std::fs::create_dir_all(&firmware).ok()?;
    let v23 = flash_image(0x6000, &noise(23, 0x8000), 0x9F000);
    std::fs::write(
        firmware.join("BlackBox_023.fwsc"),
        package(&v23, &b"OTA".repeat(100), "BlackBox_023"),
    )
    .ok()?;
    let (flash, starts) = if scenario == "rescue" {
        let mut dark = noise(20, FLASH_SIZE);
        dark[..v23.len()].copy_from_slice(&v23);
        dark[0x4000..0xA3000].copy_from_slice(&noise(21, 0xA3000 - 0x4000));
        (dark, vec![Start::Uboot, Start::Uboot, Start::Uboot])
    } else {
        let mut flash = flash_image(0x6000, &noise(24, 0x8000), 0x9F000);
        flash.extend(noise(99, FLASH_SIZE - flash.len()));
        (flash, vec![Start::Recovery, Start::Recovery, Start::Recovery])
    };
    let mut layouts = install::layouts();
    layouts[1].boot_crc = crc32(&v23[..0x6000], 0);
    let bus: Box<dyn Bus + Send> = Box::new(Slow(Bench::new(flash, noise(1, LOADER_SIZE), &starts)));
    let gamut = Source {
        what: "Gamut's app area of the simulation".into(),
        area: v23[0x6000..0x9F000].to_vec(),
        boot: None,
        custom: false,
    };
    // a test build for "a file of my own"
    std::fs::write(
        firmware.join("BlackBox_951-v23.bin"),
        app_area("BlackBox_951", 51, 0x10000),
    )
    .ok()?;
    let (own_root, own_layouts) = (root.clone(), layouts.clone());
    Some(World {
        bus: Arc::new(Mutex::new(Some(bus))),
        open_bus: Arc::new(|| Err(Error::Setup("the simulation is the bus".into()))),
        loader: Arc::new(|| Ok(noise(1, LOADER_SIZE))),
        layouts,
        heads: install::HEADS.to_vec(),
        backups: root.join("backups"),
        attempts: 10,
        root,
        permission: Box::new(|| None),
        gamut: Box::new(move |file| match file {
            None => Ok(gamut.clone()),
            Some(file) => crate::commands::gamut_source(&own_root, Some(file), &own_layouts),
        }),
        open_url: Box::new(|_| {}),
        windows: false,
    })
}
