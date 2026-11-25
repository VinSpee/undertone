// SPDX-License-Identifier: GPL-3.0-only
//! What a backup says about the pedal, in words: the firmware generation of its head (rescue/kit/tools/
//! head_fingerprint.py), the path of docs/RESCUE.md it is on, its flash layout and what its app area would start
//! (`undertone.read_pedal`).
use crate::fw::check_area;
use crate::install::{Layout, layout_of};
use crate::uboot::{hex, sha256};

const HEAD: usize = 0x4000;

/// SHA-256 of [0, 0x4000) of each official flash.bin, and of OpenPocket's own packages: (family, what to do).
const HEADS: [(&str, &str, &str); 4] = [
    (
        "d540d2217091c3eb8948bcdcc7133375256cf2d764cf9d024870255e1554ddcf",
        "M-VAVE V16, V17 or V20",
        "Path A: use firmware/BlackBox_020.fwsc",
    ),
    (
        "ef3dfea17ea81ba38a9a58f89f3d53f65a487d548d438db2ff0708b3c18daa29",
        "M-VAVE V22 or V23",
        "Path B: use firmware/BlackBox_023.fwsc (or BlackBox_022.fwsc)",
    ),
    (
        "dd49e3c322bd57c5aab62d70e7d6512344b0c39fa56253c5ec04f6984229e452",
        "M-VAVE V8 or V9",
        "Path C: no file of this kit matches. Stop and keep the backup",
    ),
    (
        "f2a7de218f81711034e88066c295cb77338592719cc08a53433c0d7874220f72",
        "an OpenPocket package's head",
        "Path C: no file of this kit matches. Stop and keep the backup",
    ),
];
const UNKNOWN: (&str, &str) = (
    "not known to this kit",
    "Path C: stop, keep the backup and send this output to whoever is helping you",
);

/// The family of a flash image's head, and what to do (`head_fingerprint.describe`).
pub fn describe(flash: &[u8]) -> (&'static str, &'static str) {
    let fp = hex(&sha256(&flash[..HEAD.min(flash.len())]));
    HEADS
        .iter()
        .find(|(h, _, _)| *h == fp)
        .map_or(UNKNOWN, |&(_, family, action)| (family, action))
}

/// What a backup says about the pedal.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Reading {
    /// The firmware generation its head belongs to.
    pub family: &'static str,
    /// "A", "B" or "C", as in docs/RESCUE.md.
    pub path: char,
    /// The flash layout, or None.
    pub layout: Option<String>,
    /// What its app area would start, or None when the layout is unknown.
    pub app: Option<String>,
}

pub fn read_pedal(flash: &[u8], layouts: &[Layout]) -> Reading {
    let (family, action) = describe(flash);
    let path = action
        .strip_prefix("Path ")
        .and_then(|a| a.chars().next())
        .unwrap_or('C');
    let layout = layout_of(flash, "the pedal's", layouts).ok();
    let app = layout.map(
        |l| match check_area(crate::fw::slice(flash, l.base, l.limit), l.base, l.limit) {
            Ok(Some(identity)) => format!("an Undertone app ({identity})"),
            Ok(None) => "M-VAVE's own firmware".to_string(),
            Err(e) => format!("nothing that starts ({})", e.message()),
        },
    );
    Reading {
        family,
        path,
        layout: layout.map(|l| l.name.clone()),
        app,
    }
}
