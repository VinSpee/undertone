// SPDX-License-Identifier: GPL-3.0-only
//! Firmware packages read as tools/pocketx_fw.py reads them: for each package of tests/fixtures/record.py, the same
//! identity, the same checks in the same order, and what the rescue (`uboot_rescue.load_image`) and the install
//! (`uboot_install.official_area`) make of it, word for word.
use serde_json::{Value, json};
use undertone_protocol::fw::Package;
use undertone_protocol::install;
use undertone_protocol::sim::{flash_image, noise, package};
use undertone_protocol::uboot::{hex, package_image, sha256};

fn cases() -> Vec<(&'static str, Vec<u8>)> {
    let flash = flash_image(0x6000, &noise(23, 0x8000), 0x9F000);
    let mut damaged = flash.clone();
    damaged[0x6000 + 0x200] ^= 1;
    let ota = b"OTA".repeat(100);
    let official = package(&flash, &ota, "BlackBox_023");
    let mut broken = official.clone();
    broken[0] ^= 1;
    vec![
        ("broken-header", broken),
        ("official", official),
        ("ours", package(&flash, &ota, "BlackBox_950")),
        ("pocketx", package(&flash, &ota, "PocketX_016")),
        ("damaged", package(&damaged, &ota, "BlackBox_023")),
    ]
}

#[test]
fn packages_are_read_and_judged_as_python_does() {
    let want: Value = serde_json::from_str(include_str!("fixtures/packages.json")).unwrap();
    let (old, new) = (
        flash_image(0x4000, &noise(20, 0x8000), 0x9F000),
        flash_image(0x6000, &noise(23, 0x8000), 0x9F000),
    );
    let mut layouts = install::layouts();
    layouts[0].boot_crc = undertone_protocol::crc::crc32(&old[..0x4000], 0);
    layouts[1].boot_crc = undertone_protocol::crc::crc32(&new[..0x6000], 0);
    let name = "BlackBox_023.fwsc";
    for (case, raw) in cases() {
        let want = &want[case];
        let p = Package::read(&raw).unwrap();
        let checks: Vec<Value> = p.checks().all().map(|(n, ok)| json!([n, ok])).collect();
        assert_eq!(p.tag, want["tag"], "{case}: the identity");
        assert_eq!(Value::from(checks), want["checks"], "{case}: the checks");
        let rescue = match package_image(&raw, name) {
            Ok(image) => json!({ "ok": hex(&sha256(&image)) }),
            Err(e) => json!({ "error": e.message() }),
        };
        assert_eq!(rescue, want["rescue"], "{case}: the rescue's reading");
        let install = match install::official_area(&raw, name, &layouts) {
            Ok(s) => json!({ "what": s.what, "area": hex(&sha256(&s.area)) }),
            Err(e) => json!({ "refused": e.message() }),
        };
        assert_eq!(install, want["install"], "{case}: the install's reading");
    }
}
