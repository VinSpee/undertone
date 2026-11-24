// SPDX-License-Identifier: GPL-3.0-only
//! The port against the Python tools, byte for byte: each scenario of tests/fixtures/record.py runs here with the same
//! inputs against the ported simulated pedals, and must send the same transfers, log the same lines, end with the same
//! result and leave the same flash as tools/uboot_rescue.py and tools/uboot_install.py did.
use std::cell::RefCell;
use std::path::PathBuf;

use serde_json::Value;
use undertone_protocol::install::{self, Layout, Source};
use undertone_protocol::sim::{Bench, FakeClock, Shared, SimPedal, Start, flash_image, noise};
use undertone_protocol::uboot::{self, FLASH_SIZE, LOADER_SIZE, Report, hex, sha256};
use undertone_protocol::{Confirmed, Error, Msc};

fn fixtures() -> Value {
    serde_json::from_str(include_str!("fixtures/transcripts.json")).expect("transcripts.json is JSON")
}

/// What one run did, in the fixture's shape.
struct Run {
    transcript: Vec<String>,
    log: Vec<String>,
    result: Result<Report, Error>,
    flash: Vec<u8>,
}

fn assert_matches(name: &str, run: &Run) {
    let all = fixtures();
    let want = &all[name];
    let strings = |v: &Value| -> Vec<String> {
        v.as_array()
            .expect("a list")
            .iter()
            .map(|s| s.as_str().expect("a string").to_string())
            .collect()
    };
    let log: Vec<String> = run
        .log
        .iter()
        .map(|m| {
            if m.starts_with("backup saved: ") {
                "backup saved: BACKUP".to_string()
            } else {
                m.clone()
            }
        })
        .collect();
    assert_eq!(log, strings(&want["log"]), "{name}: the log");
    assert_eq!(run.transcript, strings(&want["transcript"]), "{name}: the transfers");
    let result = &want["result"];
    match &run.result {
        Ok(report) => {
            assert_eq!(result["code"], 0, "{name}: the Python run failed: {result}");
            assert_eq!(
                report.sectors as u64,
                result["sectors"].as_u64().unwrap(),
                "{name}: the sectors"
            );
        }
        Err(e) => {
            assert_eq!(
                i64::from(e.exit_code()),
                result["code"].as_i64().unwrap(),
                "{name}: {e}"
            );
            assert_eq!(e.message(), result["error"].as_str().unwrap(), "{name}");
        }
    }
    assert_eq!(
        hex(&sha256(&run.flash)),
        want["flash"].as_str().unwrap(),
        "{name}: the flash"
    );
}

fn loader() -> Vec<u8> {
    noise(1, LOADER_SIZE)
}

// ---------------------------------------------------------------- the rescue
fn image() -> Vec<u8> {
    noise(2, 0x10000)
}

fn crashed_flash() -> Vec<u8> {
    let (image, mut flash) = (image(), noise(3, FLASH_SIZE));
    flash[..0x4000].copy_from_slice(&image[..0x4000]);
    for s in [5, 6] {
        flash[s * 0x1000..(s + 1) * 0x1000].copy_from_slice(&image[s * 0x1000..(s + 1) * 0x1000]);
    }
    flash
}

fn rescue(write: Option<Confirmed>, drop_at: Option<usize>) -> Run {
    let pedal = Shared::new(SimPedal::new(crashed_flash(), loader(), FakeClock::starting_at(100.0)));
    pedal.lock().drop_at = drop_at;
    let mut open = || -> Result<Box<dyn Msc>, Error> {
        let mut p = pedal.lock();
        if !p.present {
            p.reenumerate();
        }
        Ok(Box::new(pedal.clone()))
    };
    let mut log = vec![];
    let mut plan = uboot::whole_image(image()).unwrap();
    let mut save = |_: &[u8]| Ok(PathBuf::from("BACKUP"));
    let result = uboot::rescue(&mut open, &loader(), plan.as_mut(), write, &mut save, 10, &mut |m| {
        log.push(m.to_string())
    });
    let p = pedal.lock();
    Run {
        transcript: p.transcript.clone(),
        log,
        result,
        flash: p.flash.clone(),
    }
}

/// The person's yes after a read-only run like the one before the write.
fn yes_after(check: Run) -> Confirmed {
    Confirmed::new(&check.result.expect("the read-only run passes"), "yes").expect("a read-only run can be confirmed")
}

#[test]
fn the_rescue_read_only_run_sends_what_python_sends() {
    let run = rescue(None, None);
    assert_matches("rescue-read-only", &run);
}

#[test]
fn the_rescue_write_sends_what_python_sends() {
    let run = rescue(Some(yes_after(rescue(None, None))), None);
    assert_matches("rescue-write", &run);
}

#[test]
fn the_rescue_resumes_as_python_does_after_the_pedal_drops_off() {
    let run = rescue(Some(yes_after(rescue(None, None))), Some(150));
    assert_matches("rescue-resume", &run);
}

// ---------------------------------------------------------------- the install, on each layout
fn images() -> (Vec<u8>, Vec<u8>) {
    (
        flash_image(0x4000, &noise(20, 0x8000), 0x9F000),
        flash_image(0x6000, &noise(23, 0x8000), 0x9F000),
    )
}

/// The two layouts, with the synthetic heads' CRCs.
fn layouts() -> Vec<Layout> {
    let (old, new) = images();
    let mut l = install::layouts();
    l[0].boot_crc = undertone_protocol::crc::crc32(&old[..0x4000], 0);
    l[1].boot_crc = undertone_protocol::crc::crc32(&new[..0x6000], 0);
    l
}

fn install(old: bool, write: Option<Confirmed>) -> Run {
    let (old_image, new_image) = images();
    let image = if old { old_image } else { new_image };
    let mut flash = image.clone();
    flash.extend(noise(99, FLASH_SIZE - image.len()));
    let mut bench = Bench::new(flash, loader(), if old { &[Start::Uboot] } else { &[Start::Recovery] });
    let layouts = layouts();
    let heads = [(layouts[1].boot_crc, "the synthetic V23 head of this test")];
    let source_image = if old {
        flash_image(0x4000, &noise(21, 0x8000), 0x9F000)
    } else {
        flash_image(0x6000, &noise(24, 0x8000), 0x9F000)
    };
    let source: Source =
        install::flash_source(&source_image, "the test image", "the test image: its", &layouts).unwrap();
    let lines = RefCell::new(vec![]);
    let log = |m: &str| lines.borrow_mut().push(m.to_string());
    let (mut log_a, log_b, mut log_c, mut say) = (log, log, log, log);
    let result = {
        let mut open = || -> Result<Box<dyn Msc>, Error> {
            let msc = install::boot_state(&mut bench, &layouts, &heads, &mut log_a, &mut say)?;
            log_b("pedal found in the chip's USB boot state");
            Ok(msc)
        };
        let mut plan = install::plan_for(&source, &layouts, &mut log_c);
        let mut save = |_: &[u8]| Ok(PathBuf::from("BACKUP"));
        uboot::rescue(&mut open, &loader(), plan.as_mut(), write, &mut save, 10, &mut |m| {
            log(m)
        })
    };
    let flash = bench.uboot.lock().flash.clone();
    Run {
        transcript: bench.transcript(),
        log: lines.into_inner(),
        result,
        flash,
    }
}

#[test]
fn the_install_on_the_old_head_sends_what_python_sends() {
    assert_matches("install-old-dry-run", &install(true, None));
    assert_matches(
        "install-old-write",
        &install(true, Some(yes_after(install(true, None)))),
    );
}

#[test]
fn the_install_from_the_recovery_mode_sends_what_python_sends() {
    assert_matches("install-new-dry-run", &install(false, None));
    assert_matches(
        "install-new-write",
        &install(false, Some(yes_after(install(false, None)))),
    );
}
