// SPDX-License-Identifier: GPL-3.0-only
//! Where undertone's files are: the folder it runs from (the rescue kit's or the repository's), M-VAVE's firmware in its
//! `firmware` folder, the backups in the home of the person who typed `sudo`, and JieLi's loader, downloaded once and
//! checked (tools/uboot_rescue.py's `user_home`, `hand_back`, `make_dir`, `rescue`'s backup and `get_loader`).
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;

use undertone_protocol::Error;
use undertone_protocol::uboot::{LOADER_URL, check_loader};

/// The kit's number (rescue/VERSION when this program was built).
pub const VERSION: &str = include_str!("../../../rescue/VERSION");
pub const GUIDE: &str = "https://github.com/VinSpee/undertone/blob/main/docs/RESCUE.md";

pub fn version() -> &'static str {
    VERSION.trim()
}

/// The folder undertone works from: the one this program is in.
pub fn root() -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(Path::to_path_buf))
        .unwrap_or_else(|| PathBuf::from("."))
}

/// Running as root (under sudo) on macOS or Linux.
#[cfg(not(windows))]
pub fn as_root() -> bool {
    Command::new("id")
        .arg("-u")
        .output()
        .is_ok_and(|o| String::from_utf8_lossy(&o.stdout).trim() == "0")
}

/// The home of the person who typed sudo, not root's.
pub fn user_home() -> PathBuf {
    #[cfg(not(windows))]
    if let Ok(name) = std::env::var("SUDO_USER")
        && !name.is_empty()
        && name.bytes().all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
        && as_root()
        && let Ok(out) = Command::new("sh").arg("-c").arg(format!("eval echo ~{name}")).output()
    {
        let home = String::from_utf8_lossy(&out.stdout).trim().to_string();
        if home.starts_with('/') {
            return PathBuf::from(home);
        }
    }
    std::env::home_dir().unwrap_or_else(|| PathBuf::from("."))
}

/// Under sudo, give a file or folder this program made back to the person who typed it.
pub fn hand_back(path: &Path) {
    #[cfg(not(windows))]
    if let (Ok(uid), Ok(gid)) = (std::env::var("SUDO_UID"), std::env::var("SUDO_GID"))
        && let (Ok(uid), Ok(gid)) = (uid.parse(), gid.parse())
    {
        let _ = std::os::unix::fs::chown(path, Some(uid), Some(gid));
    }
    #[cfg(windows)]
    let _ = path;
}

/// Makes a folder and every missing parent, each handed back.
pub fn make_dir(path: &Path) -> Result<(), Error> {
    let missing: Vec<PathBuf> = path
        .ancestors()
        .filter(|p| !p.exists())
        .map(Path::to_path_buf)
        .collect();
    fs::create_dir_all(path).map_err(|e| Error::Setup(format!("cannot make {}: {e}", path.display())))?;
    for p in missing.iter().rev() {
        hand_back(p);
    }
    Ok(())
}

pub fn default_backups() -> PathBuf {
    user_home().join("OpenPocket-rescue")
}

/// Writes the whole flash to `blackbox-<time>.dump.bin` in `folder`, synced to disk and checked, and hands it back.
pub fn save_backup(folder: &Path, flash: &[u8]) -> Result<PathBuf, Error> {
    make_dir(folder)?;
    let path = folder.join(format!(
        "blackbox-{}.dump.bin",
        chrono::Local::now().format("%Y%m%d-%H%M%S")
    ));
    let write = || -> std::io::Result<()> {
        let mut f = fs::File::create(&path)?;
        f.write_all(flash)?;
        f.flush()?;
        f.sync_all()
    };
    write().map_err(|e| Error::Setup(format!("cannot write the backup {}: {e}", path.display())))?;
    hand_back(&path);
    if fs::metadata(&path).map(|m| m.len()).ok() != Some(flash.len() as u64) {
        return Err(Error::Setup(format!("the backup {} is incomplete", path.display())));
    }
    Ok(path)
}

fn read(path: &Path) -> Result<Vec<u8>, Error> {
    fs::read(path).map_err(|e| Error::Setup(format!("cannot read {}: {}", path.display(), reason(&e))))
}

/// The words of an I/O error, as Python's `strerror`.
pub fn reason(e: &std::io::Error) -> String {
    let s = e.to_string();
    s.split(" (os error").next().unwrap_or(&s).to_string()
}

/// Where the downloaded loader is kept: this computer's cache folder for programs.
fn loader_cache() -> PathBuf {
    let home = user_home();
    let base = if cfg!(windows) {
        std::env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join("AppData").join("Local"))
    } else if cfg!(target_os = "macos") {
        home.join("Library").join("Caches")
    } else {
        home.join(".cache")
    };
    base.join("undertone").join("wl82loader.bin")
}

/// The pinned wl82loader.bin: `--loader FILE`, else a cached copy (this program's, or the Python tool's in the kit's
/// build/cache), else downloaded with the computer's own curl. Its SHA-256 is checked each time.
pub fn loader(path: Option<&Path>) -> Result<Vec<u8>, Error> {
    if let Some(path) = path {
        let blob = read(path)?;
        check_loader(&blob, &path.display().to_string())?;
        return Ok(blob);
    }
    let cache = loader_cache();
    for cached in [cache.clone(), root().join("build").join("cache").join("wl82loader.bin")] {
        if let Ok(blob) = fs::read(&cached)
            && check_loader(&blob, "").is_ok()
        {
            return Ok(blob);
        }
    }
    let part = cache.with_extension("part");
    if let Some(folder) = cache.parent() {
        make_dir(folder)?;
    }
    let got = Command::new("curl")
        .args(["-fsSL", "--max-time", "30", "-o"])
        .arg(&part)
        .arg(LOADER_URL)
        .status();
    if !got.is_ok_and(|s| s.success()) {
        let _ = fs::remove_file(&part);
        return Err(Error::Setup(format!(
            "could not download the loader; download {LOADER_URL} and pass --loader FILE"
        )));
    }
    let blob = read(&part)?;
    if let Err(e) = check_loader(&blob, LOADER_URL) {
        let _ = fs::remove_file(&part);
        return Err(e);
    }
    fs::rename(&part, &cache).map_err(|e| Error::Setup(format!("cannot keep the loader: {e}")))?;
    hand_back(&cache);
    Ok(blob)
}
