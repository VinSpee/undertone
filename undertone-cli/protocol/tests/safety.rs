// SPDX-License-Identifier: GPL-3.0-only
//! The safety rules of DESIGN.md that a transcript of a good run cannot show: nothing is erased or written without the
//! person's yes to the file that was checked, the guards refuse what they must before anything is erased, the recovery
//! mode never gets a write command, and the real pedal's recorded frames are read as the Python tool read them.
use std::cell::RefCell;
use std::path::PathBuf;

use undertone_protocol::install::{self, LEAVE_WAIT, Layout};
use undertone_protocol::recovery::{self, Recovery, parse_reply};
use undertone_protocol::sim::{
    After, Bench, FakeClock, Fault, RecoveryOptions, Shared, SimPedal, SimRecovery, Start, flash_image, noise,
};
use undertone_protocol::uboot::{self, FLASH_SIZE, LOADER_SIZE, Report, Uboot, hex};
use undertone_protocol::{Bus, Confirmed, Error, Msc, exit};

fn loader() -> Vec<u8> {
    noise(1, LOADER_SIZE)
}

fn image(seed: u64) -> Vec<u8> {
    noise(seed, 0x10000)
}

/// A pedal whose head is `image`'s and whose app area is noise.
fn pedal_for(image: &[u8]) -> Shared<SimPedal> {
    let mut flash = noise(3, FLASH_SIZE);
    flash[..0x4000].copy_from_slice(&image[..0x4000]);
    Shared::new(SimPedal::new(flash, loader(), FakeClock::starting_at(100.0)))
}

fn rescue(pedal: &Shared<SimPedal>, image: Vec<u8>, write: Option<Confirmed>) -> Result<Report, Error> {
    let mut open = || -> Result<Box<dyn Msc>, Error> {
        let mut p = pedal.lock();
        if !p.present {
            p.reenumerate();
        }
        Ok(Box::new(pedal.clone()))
    };
    let mut plan = uboot::whole_image(image)?;
    let mut save = |_: &[u8]| Ok(PathBuf::from("BACKUP"));
    uboot::rescue(&mut open, &loader(), plan.as_mut(), write, &mut save, 3, &mut |_| {})
}

fn untouched(pedal: &Shared<SimPedal>) -> bool {
    let p = pedal.lock();
    p.erases().is_empty() && p.writes().is_empty()
}

// ---------------------------------------------------------------- the confirmation
#[test]
fn a_read_only_run_erases_and_writes_nothing() {
    let pedal = pedal_for(&image(2));
    let report = rescue(&pedal, image(2), None).unwrap();
    assert!(report.sectors > 0);
    assert!(untouched(&pedal));
}

#[test]
fn only_yes_confirms_a_write() {
    let report = rescue(&pedal_for(&image(2)), image(2), None).unwrap();
    for yes in ["yes", "YES", " Yes \n"] {
        assert!(Confirmed::new(&report, yes).is_some(), "{yes:?}");
    }
    for no in ["", "y", "no", "yes please", "ye s"] {
        assert!(Confirmed::new(&report, no).is_none(), "{no:?}");
    }
}

#[test]
fn a_write_needs_a_new_answer_and_a_check_that_only_identified_cannot_be_confirmed() {
    let pedal = pedal_for(&image(2));
    let yes = Confirmed::new(&rescue(&pedal_for(&image(2)), image(2), None).unwrap(), "yes").unwrap();
    let wrote = rescue(&pedal, image(2), Some(yes)).unwrap();
    assert!(
        Confirmed::new(&wrote, "yes").is_none(),
        "the report of a write confirms nothing"
    );

    let mut open = || -> Result<Box<dyn Msc>, Error> { Ok(Box::new(pedal_for(&image(2)))) };
    let mut save = |_: &[u8]| Ok(PathBuf::from("BACKUP"));
    let mut plan = uboot::own_flash();
    let check = uboot::rescue(&mut open, &loader(), plan.as_mut(), None, &mut save, 3, &mut |_| {}).unwrap();
    assert!(
        Confirmed::new(&check, "yes").is_none(),
        "a check that only identified the pedal confirms nothing"
    );
}

#[test]
fn a_confirmation_for_one_file_writes_no_other() {
    let yes = Confirmed::new(&rescue(&pedal_for(&image(2)), image(2), None).unwrap(), "yes").unwrap();
    let mut other = image(2);
    other[0x8000] ^= 1; // same head, another app area
    let pedal = pedal_for(&other);
    let e = rescue(&pedal, other, Some(yes)).unwrap_err();
    assert!(
        matches!(&e, Error::Refused(m) if m.contains("confirmed for another file")),
        "{e}"
    );
    assert!(untouched(&pedal));
}

#[test]
fn the_backup_is_saved_before_anything_is_compared() {
    let pedal = pedal_for(&image(5)); // a head that is not the image's: the run is refused after the backup
    let saved = RefCell::new(vec![]);
    let mut open = || -> Result<Box<dyn Msc>, Error> { Ok(Box::new(pedal.clone())) };
    let mut save = |flash: &[u8]| {
        saved.borrow_mut().push(flash.to_vec());
        Ok(PathBuf::from("BACKUP"))
    };
    let mut plan = uboot::whole_image(image(2)).unwrap();
    let e = uboot::rescue(&mut open, &loader(), plan.as_mut(), None, &mut save, 3, &mut |_| {}).unwrap_err();
    assert!(
        matches!(&e, Error::Refused(m) if m.contains("is not the image's head")),
        "{e}"
    );
    assert_eq!(saved.borrow().len(), 1);
    assert_eq!(saved.borrow()[0], pedal.lock().flash);
}

// ---------------------------------------------------------------- the guards
#[test]
fn the_wrong_chip_or_flash_is_refused_before_anything_is_erased() {
    type Change = fn(&mut SimPedal);
    let cases: [(Change, &str); 3] = [
        (
            |p| p.key = 0x1234,
            "chip key 0x1234 is not 0x980f: this is not a BlackBox, nothing was written",
        ),
        (
            |p| p.flash_id = 0xEB6015,
            "flash id 0xeb6015 is not a 1 MiB flash: nothing was written",
        ),
        (
            |p| p.vendor = "WL83".into(),
            "this is not the WL82 UBOOT1.00 boot state ('WL83' 'UBOOT1.00')",
        ),
    ];
    for (change, refusal) in cases {
        let pedal = pedal_for(&image(2));
        change(&mut pedal.lock());
        let yes = Confirmed::new(&rescue(&pedal_for(&image(2)), image(2), None).unwrap(), "yes").unwrap();
        let e = rescue(&pedal, image(2), Some(yes)).unwrap_err();
        assert_eq!(e, Error::Refused(refusal.into()));
        assert!(untouched(&pedal));
    }
}

#[test]
fn no_erase_or_write_without_the_window_and_none_outside_it() {
    let pedal = pedal_for(&image(2));
    let mut msc = pedal.clone();
    let mut dev = Uboot::new(&mut msc);
    assert_eq!(
        dev.erase_sector(0x5000),
        Err(Error::Refused("erase at 0x5000 refused".into()))
    );
    assert_eq!(
        dev.flash_write(0x5000, &[0; 512]),
        Err(Error::Refused("write at 0x5000 refused".into()))
    );
    assert_eq!(
        dev.mem_write(0x100, &[0; 16]),
        Err(Error::Refused(
            "memory write at 0x100: only the loader's RAM may be written".into()
        ))
    );
    assert!(pedal.lock().transcript.is_empty(), "nothing reached the pedal");
    assert!(
        uboot::Window::for_image(0x100000).is_err(),
        "never up to the end of the flash"
    );
    assert!(uboot::Window::for_image(0x4000).is_err(), "never only the head");
    assert!(uboot::Window::for_image(0x10800).is_err(), "only whole sectors");
}

fn layouts() -> Vec<Layout> {
    let (old, new) = (
        flash_image(0x4000, &noise(20, 0x8000), 0x9F000),
        flash_image(0x6000, &noise(23, 0x8000), 0x9F000),
    );
    let mut l = install::layouts();
    l[0].boot_crc = undertone_protocol::crc::crc32(&old[..0x4000], 0);
    l[1].boot_crc = undertone_protocol::crc::crc32(&new[..0x6000], 0);
    l
}

/// An install's dry run on a pedal in the boot state that holds `flash`, of the app area of `source_image`.
fn install_on(flash: Vec<u8>, source_image: &[u8], flash_id: u32) -> (Result<Report, Error>, Bench) {
    let layouts = layouts();
    let mut bench = Bench::new(flash, loader(), &[Start::Uboot]);
    bench.uboot.lock().flash_id = flash_id;
    let source = install::flash_source(source_image, "the test image", "the test image: its", &layouts).unwrap();
    let mut open = || install::boot_state(&mut bench, &layouts, &install::HEADS, &mut |_| {}, &mut |_| {});
    let mut quiet = |_: &str| {};
    let mut plan = install::plan_for(&source, &layouts, &mut quiet);
    let mut save = |_: &[u8]| Ok(PathBuf::from("BACKUP"));
    let r = uboot::rescue(&mut open, &loader(), plan.as_mut(), None, &mut save, 3, &mut |_| {});
    (r, bench)
}

fn with_rest(image: Vec<u8>) -> Vec<u8> {
    let mut flash = image.clone();
    flash.extend(noise(99, FLASH_SIZE - image.len()));
    flash
}

#[test]
fn an_install_refuses_an_unknown_head_an_unknown_flash_and_an_area_for_the_other_layout() {
    let old = flash_image(0x4000, &noise(20, 0x8000), 0x9F000);
    let new_source = flash_image(0x6000, &noise(24, 0x8000), 0x9F000);
    let mut strange = old.clone();
    strange[0x100] ^= 1;

    let (r, _) = install_on(with_rest(strange), &old, 0xEB6014);
    assert!(matches!(r, Err(Error::Refused(m)) if m.starts_with("the pedal's boot area is not one this tool knows")));
    let (r, _) = install_on(with_rest(old.clone()), &old, 0xEF4014);
    assert_eq!(
        r.unwrap_err(),
        Error::Refused("flash id 0xef4014 is not one this tool knows (0x856014, 0xeb6014): nothing was written".into())
    );
    let (r, bench) = install_on(with_rest(old), &new_source, 0xEB6014);
    assert!(matches!(r, Err(Error::Refused(m)) if m.contains("its boot area is not this pedal's")));
    assert!(bench.uboot.lock().erases().is_empty());
}

#[test]
fn a_backup_must_be_the_whole_flash() {
    let e = install::backup_area(&[0xFF; 0x80000], "blackbox.dump.bin", &layouts()).unwrap_err();
    assert_eq!(
        e,
        Error::Refused("blackbox.dump.bin is 524288 bytes, not a backup of the whole 1 MiB flash".into())
    );
}

#[test]
fn gamut_is_installed_only_from_the_release_pin() {
    let area = noise(5, 0x10000);
    let e = install::gamut_area(area, "BlackBox_950-v23.bin", &"0".repeat(64), &layouts()).unwrap_err();
    assert!(matches!(e, Error::Refused(m) if m.contains("is not the Gamut app area of the release pin")));
    let pin = "aa  build/apps/gamut/openpocket.bin\nbb  build/apps/gamut/BlackBox_950-v23.bin\n";
    assert_eq!(
        install::gamut_pin(pin),
        Some(("build/apps/gamut/BlackBox_950-v23.bin", "bb"))
    );
}

// ---------------------------------------------------------------- the recovery mode
#[test]
fn the_recovery_mode_never_gets_a_write_command() {
    for command in 2..=5 {
        let e = recovery::frame(command, 1).unwrap_err();
        assert!(
            matches!(e, Error::Refused(m) if m.contains("belongs to a write to the flash")),
            "{command}"
        );
    }
    assert!(recovery::frame(7, 1).is_err());
}

/// What a leave did: the boot state it reached (or why not), the bus, and the lines it said.
type Left = (Result<Option<Box<dyn Msc>>, Error>, Bench, Vec<String>);

fn recovery_run(options: RecoveryOptions) -> Left {
    let flash = with_rest(flash_image(0x6000, &noise(23, 0x8000), 0x9F000));
    let mut bench = Bench::new(flash, loader(), &[Start::Recovery]).recovery(vec![options]);
    let layouts = layouts();
    while !bench.present().unwrap().contains(&recovery::RECOVERY) {
        bench.sleep(0.05).unwrap();
    }
    let mut said = vec![];
    let r = install::leave(&mut bench, &layouts, &[], &mut |m| said.push(m.to_string()));
    (r, bench, said)
}

#[test]
fn the_leave_is_sent_only_on_a_known_head_and_in_the_states_that_take_it() {
    let defaults = RecoveryOptions {
        in_zeros: true,
        ..Default::default()
    };
    let (r, bench, _) = recovery_run(RecoveryOptions {
        state: 3,
        ..defaults.clone()
    });
    assert!(matches!(r, Err(Error::Refused(m)) if m.starts_with("the recovery mode is in state 3")));
    assert_eq!(bench.frames(), [recovery::HELLO]);

    for fault in [Fault::Status, Fault::Constants, Fault::Crc] {
        let (r, bench, _) = recovery_run(RecoveryOptions {
            fault: Some(fault),
            ..defaults.clone()
        });
        assert!(matches!(r, Err(Error::Refused(_))), "{fault:?}");
        assert_eq!(
            bench.frames(),
            [recovery::HELLO],
            "{fault:?}: no leave after a bad hello"
        );
    }
    for r in &bench_writes(defaults) {
        assert!(r.is_empty(), "no write command reached the recovery mode");
    }
}

fn bench_writes(options: RecoveryOptions) -> Vec<Vec<u32>> {
    let (r, bench, _) = recovery_run(options);
    assert!(r.unwrap().is_some());
    bench
        .recoveries
        .iter()
        .map(|rec| rec.lock().write_attempts.clone())
        .collect()
}

#[test]
fn after_the_leave_it_waits_for_the_boot_state_and_tells_the_two_failures_apart() {
    let defaults = RecoveryOptions {
        in_zeros: true,
        ..Default::default()
    };
    let (r, bench, _) = recovery_run(RecoveryOptions {
        stays: true,
        ..defaults.clone()
    });
    assert_eq!(r.err().map(|e| e.exit_code()), Some(exit::STAYED_IN_RECOVERY));
    assert!(
        bench.clock.now() - 100.0 >= LEAVE_WAIT,
        "it waited the whole {LEAVE_WAIT} s"
    );

    let (r, _, said) = recovery_run(RecoveryOptions {
        after_reset: After::App,
        ..defaults.clone()
    });
    let e = r.err().expect("no boot state");
    assert_eq!(e.exit_code(), exit::NO_BOOT_STATE);
    assert!(
        e.message()
            .starts_with("the chip's USB boot state did not appear within 75 s of the leave"),
        "{e}"
    );
    assert!(
        said.iter()
            .any(|l| l.ends_with("leave sent: waiting for the chip's USB boot state (USB 4C4A:8057)"))
    );

    let (r, _, said) = recovery_run(RecoveryOptions {
        reset_s: 70.056,
        ..defaults
    });
    assert!(
        r.unwrap().is_some(),
        "the 70-second leave of the owner's pedal is waited for"
    );
    assert!(
        said.last().unwrap().contains("the chip's USB boot state appeared 70"),
        "{said:?}"
    );
}

// ---------------------------------------------------------------- the real pedal's frames
/// The owner's V23 pedal on 24 November 2026: the frame headers it got and the hello reply its reply buffer held.
const REAL_HELLO: &str = "534255320100000001000000000000000000000000000000";
const REAL_LEAVE: &str = "534255320600000002000000000000000000000000000000";
const REAL_REPLY: &str = "5342523201000000010000000000000000000000000000000000000040009107000002000060000000f00900\
                          a1969db10000000000000000000000001a5ad2e8";

fn unhex(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
        .collect()
}

#[test]
fn the_frames_are_the_ones_the_real_pedal_got() {
    assert_eq!(hex(&recovery::frame(recovery::HELLO, 1).unwrap()[..24]), REAL_HELLO);
    assert_eq!(hex(&recovery::frame(recovery::LEAVE, 2).unwrap()[..24]), REAL_LEAVE);
    let frame = recovery::frame(recovery::HELLO, 1).unwrap();
    assert_eq!(frame.len(), 4608);
    assert!(frame[24..].iter().all(|&b| b == 0));
}

#[test]
fn the_real_pedals_hello_reply_reads_as_its_v23_head() {
    let r = parse_reply(&unhex(REAL_REPLY), recovery::HELLO, 1).unwrap();
    assert_eq!(
        (r.status, r.state, r.boot_crc, r.base, r.limit),
        (0, 0, 0xB19D96A1, 0x6000, 0x9F000)
    );
    let real = install::layouts();
    assert!(
        real.iter()
            .any(|l| (l.boot_crc, l.base as u32, l.limit as u32) == (r.boot_crc, r.base, r.limit))
    );
    let mut said = vec![];
    recovery::describe(&r, Some("64 zero bytes, then nothing"), &install::HEADS, &mut |m| {
        said.push(m.to_string())
    });
    assert_eq!(
        said[2],
        "  boot area [0, 0x6000) CRC-32 0xb19d96a1: M-VAVE V22 or V23 (the boot area of both official packages)"
    );
    let mut broken = unhex(REAL_REPLY);
    broken[20] ^= 1;
    assert!(
        parse_reply(&broken, recovery::HELLO, 1).is_err(),
        "a reply whose CRC-32 fails is refused"
    );
}

#[test]
fn a_hello_over_the_real_pedals_zero_reply_is_read_from_the_reply_buffer() {
    let clock = FakeClock::starting_at(0.0);
    let options = RecoveryOptions {
        in_zeros: true,
        boot_crc: 0xB19D96A1,
        ..Default::default()
    };
    let mut dev = Shared::new(SimRecovery::new(options, clock.clone()));
    let mut lines = vec![];
    let mut log = |m: &str| lines.push(m.to_string());
    let mut session = Recovery::new(&mut dev, &mut log, clock.clock());
    let (hello, bulk) = session.probe().unwrap();
    assert_eq!(hello.boot_crc, 0xB19D96A1);
    assert_eq!(bulk.as_deref(), Some("64 zero bytes, then nothing"));
    // the simulated V23 recovery mode answers with the real pedal's reply, byte for byte
    assert!(
        lines.contains(&format!("reply buffer (0x43): 64 B {REAL_REPLY}")),
        "{lines:#?}"
    );
}
