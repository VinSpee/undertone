// SPDX-License-Identifier: GPL-3.0-only
//! undertone's commands as a person runs them, against tools/undertone.py's own runs: for each scenario of
//! protocol/tests/fixtures/record.py, the same window (times, backup and folder paths left out), the same exit code,
//! the same transfers to the simulated pedal and the same flash at the end.
use std::cell::RefCell;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::rc::Rc;

use serde_json::Value;
use undertone_protocol::crc::crc32;
use undertone_protocol::install::{self, Layout};
use undertone_protocol::sim::{Bench, Start, flash_image, noise, package};
use undertone_protocol::uboot::{FLASH_SIZE, LOADER_SIZE, hex, sha256};

use crate::commands::{self, Ctx, InstallFrom, Out};

/// A folder of its own under the system's temporary folder.
fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("undertone-test-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

#[derive(Clone, Default)]
struct Window(Rc<RefCell<Vec<u8>>>);

impl Write for Window {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        self.0.borrow_mut().extend_from_slice(buf);
        Ok(buf.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

fn layouts() -> Vec<Layout> {
    let (old, new) = (
        flash_image(0x4000, &noise(20, 0x8000), 0x9F000),
        flash_image(0x6000, &noise(23, 0x8000), 0x9F000),
    );
    let mut l = install::layouts();
    l[0].boot_crc = crc32(&old[..0x4000], 0);
    l[1].boot_crc = crc32(&new[..0x6000], 0);
    l
}

/// What the window showed, without what differs from run to run.
fn shown(text: &str, firmware: &Path) -> Vec<String> {
    text.replace(&firmware.display().to_string(), "FIRMWARE")
        .lines()
        .map(|l| {
            let l = match l.strip_prefix('[').and_then(|r| r.split_once("s] ")) {
                Some((t, rest)) if t.trim().parse::<f64>().is_ok() => format!("[time] {rest}"),
                _ => l.to_string(),
            };
            let words: Vec<String> = l
                .split(' ')
                .map(|w| {
                    if w.contains("blackbox-") && w.ends_with(".dump.bin") {
                        "BACKUP".into()
                    } else {
                        w.into()
                    }
                })
                .collect();
            words.join(" ")
        })
        .collect()
}

enum Cmd {
    Rescue,
    InstallOfficial,
    Check,
}

fn command(scenario: &str, cmd: Cmd, flash: Vec<u8>, starts: &[Start], answer: &str) {
    let all: Value = serde_json::from_str(include_str!("../../protocol/tests/fixtures/commands.json")).unwrap();
    let want = &all[scenario];
    let root = scratch(scenario);
    let firmware = root.join("firmware");
    std::fs::create_dir_all(&firmware).unwrap();
    let ota = b"OTA".repeat(100);
    let v20 = flash_image(0x4000, &noise(10, 0x8000), 0xA5000);
    let v23 = flash_image(0x6000, &noise(23, 0x8000), 0x9F000);
    std::fs::write(firmware.join("BlackBox_020.fwsc"), package(&v20, &ota, "BlackBox_020")).unwrap();
    std::fs::write(firmware.join("BlackBox_023.fwsc"), package(&v23, &ota, "BlackBox_023")).unwrap();

    let mut bench = Bench::new(flash, noise(1, LOADER_SIZE), starts);
    let window = Window::default();
    let mut out = Out::to(Box::new(window.clone()));
    let mut reader = |_: &str| Some(answer.to_string());
    let loader = || Ok(noise(1, LOADER_SIZE));
    let mut ctx = Ctx {
        root: root.clone(),
        out: &mut out,
        reader: &mut reader,
        bus: &mut bench,
        loader: &loader,
        backups: root.join("backups"),
        attempts: 10,
        layouts: layouts(),
        heads: install::HEADS.to_vec(),
        windows: false,
    };
    let code = match cmd {
        Cmd::Rescue => commands::cmd_rescue(&mut ctx, None, None),
        Cmd::InstallOfficial => {
            commands::cmd_install(&mut ctx, InstallFrom::Official(&firmware.join("BlackBox_023.fwsc")))
        }
        Cmd::Check => commands::cmd_check(&mut ctx),
    };
    let text = String::from_utf8(window.0.borrow().clone()).unwrap();
    let lines: Vec<Value> = shown(&text, &firmware).into_iter().map(Value::from).collect();
    assert_eq!(Value::from(lines), want["shown"], "{scenario}: the window");
    assert_eq!(code, want["code"].as_i64().unwrap() as i32, "{scenario}: the exit code");
    let transfers = bench.transcript().join("\n");
    assert_eq!(
        hex(&sha256(transfers.as_bytes())),
        want["transcript"],
        "{scenario}: the transfers"
    );
    assert_eq!(
        hex(&sha256(&bench.uboot.lock().flash)),
        want["flash"],
        "{scenario}: the flash"
    );
    let backups = std::fs::read_dir(root.join("backups")).map(|d| d.count()).unwrap_or(0);
    assert!(backups >= 1, "{scenario}: a backup was saved");
    let _ = std::fs::remove_dir_all(&root);
}

fn dark() -> Vec<u8> {
    let v23 = flash_image(0x6000, &noise(23, 0x8000), 0x9F000);
    let mut flash = noise(20, FLASH_SIZE);
    flash[..v23.len()].copy_from_slice(&v23);
    flash[0x4000..0xA3000].copy_from_slice(&noise(21, 0xA3000 - 0x4000));
    flash
}

fn on_v23() -> Vec<u8> {
    let mut flash = flash_image(0x6000, &noise(24, 0x8000), 0x9F000);
    flash.extend(noise(99, FLASH_SIZE - flash.len()));
    flash
}

#[test]
fn the_rescue_checks_asks_and_restores_as_python_does() {
    command("rescue", Cmd::Rescue, dark(), &[Start::Uboot, Start::Uboot], "yes");
}

#[test]
fn the_rescue_writes_nothing_without_a_yes() {
    command("rescue-not-confirmed", Cmd::Rescue, dark(), &[Start::Uboot], "no");
}

#[test]
fn a_refused_rescue_says_what_the_pedal_needs() {
    command(
        "rescue-refused",
        Cmd::Rescue,
        noise(22, FLASH_SIZE),
        &[Start::Uboot],
        "yes",
    );
}

#[test]
fn the_way_back_to_m_vaves_firmware_goes_through_the_recovery_mode_as_python_does() {
    command(
        "install-official",
        Cmd::InstallOfficial,
        on_v23(),
        &[Start::Recovery, Start::Recovery],
        "YES ",
    );
}

#[test]
fn the_check_names_the_pedal_as_python_does() {
    command("check", Cmd::Check, on_v23(), &[Start::Recovery], "");
}
