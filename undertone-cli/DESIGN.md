# undertone as one program

`undertone` rescues a BlackBox that will not start, puts Gamut on a BlackBox, or checks what a pedal holds, over its
USB cable. Today it is a Python command (`tools/undertone.py`, its guided screens `tools/undertone_screens.py`, the
launchers `undertone` and `undertone.cmd`), and it needs Python 3 and, on a Mac, Homebrew's libusb. This folder builds
the same command as one Rust program that needs nothing installed. The Python command is the specification and stays
the fallback until the owner has proven the program on a real pedal.

So far the folder holds the workspace, this design, the CI, the protocol library and the program's commands
`rescue`, `install` and `check`, each tested against the Python command's own runs on simulated pedals. Nothing in it
has run on a real pedal yet. The guided screens and the release follow; [Stages](#stages) lists them.

## Layout

| Path | What it is |
| --- | --- |
| `protocol/` | The library `undertone-protocol`: the pedal's protocols, checks and plans, with no USB code and no `unsafe` |
| `undertone/` | The program: the USB transports, the commands, the guided screens |
| `rust-toolchain.toml` | The pinned Rust release, 1.99.1 |
| `Cargo.lock` | Every dependency at an exact version |

The folder sits at the top of the repository beside `formal/` and `site/`, because it is a project of its own with its
own build, not a script in `tools/`.

## Crates

Few dependencies, each pinned with `=` in `Cargo.toml` and locked in `Cargo.lock`:

- **USB on macOS and Linux: `rusb` with its `vendored` feature.** It builds libusb 1.0.27 from source into the
  program, so it needs no Homebrew and no system library. On Linux it finds devices through netlink and does not load
  libudev. Windows does not use it (see [Windows](#windows)).
- **USB on Windows: `windows-sys`** (stage 3), for `CreateFileW` and `DeviceIoControl` with
  `IOCTL_SCSI_PASS_THROUGH_DIRECT`, as `tools/uboot_rescue.py` calls them through ctypes.
- **Screens: `ratatui` with `crossterm`** (stage 4). crossterm reads keys and sets the terminal mode on macOS, Linux
  and Windows, which the Python screens do by hand with termios and msvcrt.
- **Arguments: `clap`** with only the derive, help, usage and error-context features. The commands and options are
  those of `tools/undertone.py`.
- **SHA-256: `sha2`** (stage 2), for the loader pin, the Gamut release pin and the source digest of a confirmation.
  CRC-32 (zlib's) and JieLi's CRC-16 are a few lines each and are written out, as in `tools/pocketx_fw.py`.

There is no async runtime. One worker thread runs a tool while the screen's thread draws and reads keys; they talk
over a channel of log lines and one stop flag, as `undertone_screens.run_in_background` does with a queue and an event.
The loader is downloaded with the computer's own `curl` (macOS, Linux and Windows 10 and later ship it), so the program
carries no TLS code. Its SHA-256 is checked either way, and `--loader FILE` still works offline.

## Protocol and screens

The protocol crate ports `tools/uboot_rescue.py`, the plan of `tools/uboot_install.py`, `tools/pd40_recovery.py`'s
hello and leave, and the checks of `tools/pocketx_fw.py`, `tools/pd40_install.py` (`check_area`) and
`rescue/kit/tools/head_fingerprint.py`. It reaches a device only through two traits:

- `Msc`, the chip's USB boot state as a mass-storage device: `execute(cdb, out, in_len, timeout)`. libusb's bulk-only
  transport implements it on macOS and Linux, SCSI pass-through on Windows, and the simulated pedal in the tests.
- `RecoveryDevice`, M-VAVE's recovery mode: a vendor IN request, one bulk OUT frame, one bulk IN read.

The bus that finds devices, and the clock and sleep the waits use, are passed in the same way, so the tests run every
wait on a fake clock as the Python simulators do.

**The write needs a confirmation.** Every function that can erase or write takes a `Confirmed` value. Its field is
private and it has one constructor, which takes the report of the read-only run and the person's answer, and returns a
value only for "yes" (typed on the command line, or the "yes" choice of the guided "replace the software?" screen). It
carries the SHA-256 of the source that run compared, and the write refuses any other source. A run that writes consumes it, so
a retry after a failed write needs a new answer: the re-confirmation rule is enforced by the type, not by a check that
could be forgotten. The protocol crate has `#![forbid(unsafe_code)]`.

**The screens are a state machine over the protocol.** The guided flow is `undertone_screens.Guide`, state for state:
each state shows one screen and names the next. The screen is drawn from a plain description (title, lines, choices,
status, warning), which a full-screen view renders with ratatui and a plain view prints as numbered questions, as
`AnsiView` and `PlainView` do. The copy, the states and the order are the Python screens', word for word.

## The Python tools are the specification

The port reads `tools/uboot_rescue.py`, `tools/uboot_install.py`, `tools/pd40_recovery.py`, `tools/undertone.py` and
`tools/undertone_screens.py` line by line, and keeps their commands, frames, messages and exit codes. These rules are
kept, each with a test:

1. **A read-only run first.** A rescue starts with the check, an install with the dry run. Both read the whole flash,
   save a backup, compare, send run-app and write nothing. The write is a second run, after the answer.
2. **A backup before any write.** Every run reads the whole 1 MiB flash and saves it before the plan is even computed:
   `~/OpenPocket-rescue/blackbox-YYYYMMDD-HHMMSS.dump.bin` in the home of the person who typed `sudo`, synced to disk,
   its size checked, and handed back to that person. One backup per run, on its first pass; `--backup-dir` changes the
   folder. The guided screens also write the tools' raw lines to `undertone-<time>.log` beside it.
3. **An explicit answer before any write.** On the command line the question ends in "Type yes to go on, anything
   else to stop"; only `yes` (any case, spaces trimmed) goes on, end of input is no, and no ends with exit 4 and
   "Stopped. Nothing was written." In the guided screens a separate "replace the software?" screen asks, with "no"
   chosen at first.
4. **No back or quit during a write.** Esc and q stop the wait for the pedal (nothing was sent), but once a write is
   under way they only show, in amber, "do not unplug: your pedal is being updated". Ctrl-C during a write prints the
   resume note: the pedal may not start yet, run the same command again and it continues where it stopped, and where
   the backup is.
5. **A new answer after a failed write.** "Try again" after a failed write goes back to the confirmation screen, and
   the end screen says the pedal may be partly updated.
6. **Boot area checks.** A layout is named by the CRC-32 of its boot area: the old head (M-VAVE V16, V17 and V20),
   `[0, 0x4000)` with CRC-32 `0x5A2121FF` and the app area in `[0x4000, 0xA5000)`; M-VAVE's V22/V23 head, `[0, 0x6000)`
   with `0xB19D96A1` and the app area in `[0x6000, 0x9F000)`. Any other head is refused. An official package's or a
   backup's boot area must be the pedal's byte for byte, and an app area must end at or below its layout's limit. A
   rescue image's head `[0, 0x4000)` must be the pedal's, and the image must be whole 4 KiB sectors ending in
   `(0x4000, 0xFF000]`. In the recovery mode the hello's boot CRC-32, base and limit must name a known layout before
   the leave is sent.
7. **Chip checks.** INQUIRY must answer `WL82` and `UBOOT1.00`. The chip key, read through JieLi's cipher, must be
   `0x980F`, and the flash 1 MiB. An install also requires the flash id `0xEB6014` or `0x856014`.
8. **Only the allowed commands.** Without a write window the only commands are memory write (only into the loader's
   RAM, `[0x1C02000, +24064)`), jump, read key, online device, USB buffer, read flash and run-app. Erase sector and
   write flash need the window, and each must be sector-aligned and inside it. Chip erase (`FB02`) and key burn
   (`FC12`) cannot be sent at all. In the recovery mode only hello (1) and leave (6) are sent, the leave only in state
   0 or 6, only the vendor requests `0x42`, `0x43` and `0x44` at their fixed lengths, every frame 4608 bytes in one
   transfer with no zero-length packet, and every reply is checked (`SBR2`, its CRC-32, the echoed command and tag,
   the protocol's constants).
9. **Pinned files.** JieLi's `wl82loader.bin` must have SHA-256 `d41da612…5376` and 24064 bytes. Gamut's app area must
   be the release pin's (`firmware/apps/gamut/release.sha256`, compiled into the program). An official package must
   pass every CRC of `pocketx_fw.package_checks` and be one of M-VAVE's BlackBox packages (identity below 900). A
   backup to restore must be exactly 1 MiB, and its app area one the boot loader would start.
10. **Each sector verified, and runs that resume.** For each 4 KiB sector that differs: erase, write in 512-byte
    pieces, read back and compare, up to 3 times. When the pedal leaves the bus the run waits for it again, up to
    `--attempts` (10) times, and a rerun writes only the sectors that still differ.
11. **The waits.** A rescue waits for the chip's USB boot state with no time limit, polling every 50 ms, and claims it
    the moment it appears: a pedal that restarts in a loop is in that state about 44 s out of every 70 s. An install
    waits as long for the boot state or the recovery mode, and after the leave waits for the boot state. The Python
    tool gives up 10 s after the leave (`LEAVE_WAIT`), but on the owner's pedal on 24 November 2026 the boot state
    appeared 70,056 ms after the leave and the install went on (one open probably blocked for about a minute). The port
    waits 75 s after the leave, so that the run the owner saw succeed also succeeds here; it sends nothing while it
    waits. After the leave it still tells a pedal that stayed in the recovery mode (exit 5) from one that left and did
    not come back (exit 3).
12. **The hints.** After 30 s of looking: "Still looking. Plug straight into this computer, no hub.", then "A pedal
    that will not start shows up between restarts." for a rescue or "Hold all three until its screen says RECOVERY."
    for an install. On Windows the wait adds "If Windows offers to format a drive, click Cancel". A problem is told in
    the plain words of `Guide.failed`, and the tool's own line goes to the log and to the screen at the end.
13. **Rights.** On macOS and Linux the program starts itself again under `sudo` with the chosen task, after the
    "undertone needs your password" screen. On Windows it needs an administrator.
14. **Exit codes.** 0 done, 1 a setup problem or a failed transfer, 2 refused by a check, 3 the boot state did not
    appear after the leave, 4 not confirmed, 5 the pedal stayed in the recovery mode, 130 stopped.

## Builds

| Target | Built on | Tests run | Notes |
| --- | --- | --- | --- |
| `aarch64-apple-darwin` | macOS 15, Apple silicon | yes | libusb built in; links only macOS's own frameworks |
| `x86_64-apple-darwin` | macOS 15, Apple silicon | no | cross-built; the runner cannot run it |
| `x86_64-unknown-linux-musl` | Ubuntu 24.04, x86_64 | yes | static: runs on any distribution |
| `aarch64-unknown-linux-musl` | Ubuntu 24.04, arm64 | yes | static |
| `x86_64-pc-windows-msvc` | Windows Server 2025 | yes | the C runtime linked in (`.cargo/config.toml`) |

`.github/workflows/undertone-cli.yml` runs on a pull request or a push to main that touches this folder, and by hand.
It checks the format and clippy once, then builds each target natively on its own runner, runs the tests where the
runner can, builds the release program, and fails when it is over the size budget or, on Linux, not static. Locally,
build only for this computer: `cargo test` and `cargo build --release` in this folder.

Linux uses musl so that one file runs on every distribution. libusb's Linux code needs four kernel headers that musl's
compiler does not see (`linux/types.h`, `linux/netlink.h`, `linux/magic.h`, `asm/types.h`); CI adds the runner's
kernel header folders after musl's own.

## Rights and drivers

### macOS

macOS keeps its mass-storage driver on the chip's USB boot state, and libusb needs root to take the
interface, as the owner's runs with the Python tool showed. The program asks for the password through `sudo` and
starts itself again as root, as `tools/undertone.py` does. M-VAVE's recovery mode is a vendor interface that no macOS
driver holds. No Homebrew and no libusb install are needed any more.

### Linux

Untested with the Python tool too. The kernel's `usb-storage` driver holds the boot state, so the program
needs root to detach it, through `sudo` as on macOS.

### Windows

`tools/uboot_rescue.py` needs no driver on Windows, and neither does this program. Windows keeps its own mass-storage
driver on the pedal, and an administrator may send any SCSI command through it (`IOCTL_SCSI_PASS_THROUGH_DIRECT`). The
tool finds the pedal by asking each disk and drive letter for INQUIRY, which only reads. So there is no Zadig, no WinUSB
and no libusb on Windows; libusb could not even reach the pedal there without replacing Windows' driver, which is why
the program does not use it on Windows. What a Windows user must do: run the program as an administrator, and click
Cancel if Windows offers to format a drive. The program can guide the first itself: started without the right, it asks
Windows to start it again as administrator (`ShellExecuteW` with `runas`, the standard Windows prompt), instead of the
Python tool's instructions for an administrator's Command Prompt. Opened by a double-click, it waits for Enter at the
end so that its window does not vanish. An install stays macOS and Linux only, as in the Python tool (`undertone
install` on Windows says so and sends nothing), because M-VAVE's recovery mode has not been tried on Windows; it is a
WinUSB device, so libusb might reach it there without Zadig, but that needs a Windows test with a real pedal first.

## Signing, Gatekeeper and SmartScreen

The Python command runs through a signed interpreter, so neither macOS nor Windows questions it. An unsigned program
downloaded with a browser is questioned:

- **macOS.** On Apple silicon the linker signs the program ad hoc, which lets it run, but a file downloaded with a
  browser, or unzipped from such a download, carries the quarantine mark. Gatekeeper then refuses to open it: "Apple
  could not verify “undertone” is free of malware". The person must open System Settings, Privacy & Security, and
  click Open Anyway, or run `xattr -d com.apple.quarantine undertone` once. A file downloaded with `curl` has no mark.
  Signing with a Developer ID and notarizing (Apple Developer Program, a yearly fee) removes the prompt.
- **Windows.** A downloaded unsigned `.exe` makes SmartScreen show "Windows protected your PC"; the person must click
  More info, then Run anyway. On a Windows 11 PC with Smart App Control turned on, an unsigned program is blocked with
  no way to run it. Authenticode signing (a code-signing certificate, or Microsoft's Trusted Signing service for a monthly fee) removes Smart App
  Control's block; SmartScreen still warns until the signed program builds reputation.

Signing needs an account and a certificate that only the owner can take out; it is not part of these stages. Until
then the guide must give the macOS and Windows steps above, and the Python command stays offered beside the program.

## Size

The budget is 4 MiB for one release program; CI fails above it. This stage measures about 0.7 MiB on macOS
(Apple silicon) with libusb built in. The release profile optimizes for size, with link-time optimization, one codegen
unit and the symbols stripped.

## Tests

- **The same transfers as Python.** `protocol/tests/fixtures/record.py` runs `tools/uboot_rescue.py` and
  `tools/uboot_install.py`, unchanged, against the Python tests' simulated pedals (`tests/uboot_sim.py`,
  `tests/recovery_sim.py`, the bus of `tests/test_uboot_install.py`) and writes every transfer, every log line, the
  result and the flash the pedal ends with to `transcripts.json`. `protocol/tests/transcripts.rs` runs the same
  scenarios, with the same inputs, through the port and the ported simulators, and must match all four byte for
  byte: the rescue's read-only run, its restore, its resume after the pedal drops off the bus, and the install's dry
  run and write on each flash layout, from the boot state and from the recovery mode. CI records the transcripts again
  and fails when they changed, so a change to the Python tools cannot leave the port behind unnoticed. Test images are
  noise and `tests/fw_layouts.py`'s images, never M-VAVE's files.
- **Packages read as Python reads them.** `protocol/tests/packages.rs` compares, for good, damaged and foreign
  packages, the identity, every CRC check in order, and what the rescue and the install make of each, word for word
  (`packages.json`, from the same script).
- **The safety rules.** `protocol/tests/safety.rs`: nothing is erased or written without a `Confirmed`; only "yes"
  makes one; a confirmation for one file writes no other; a run that wrote, or a check that only identified the
  pedal, cannot be confirmed; the backup is saved before the image is compared; a wrong chip key, flash size, vendor,
  flash id, head or boot area is refused before any erase; no erase or write outside the window; the recovery mode
  never gets a write command, nor a leave after a bad hello or in another state; the two failures after the leave are
  told apart, and the owner's 70-second leave is waited for.
- **The real pedal's bytes.** The hello and leave frame headers of the owner's dry run
  (`534255320100000001000000000000000000000000000000` and `534255320600000002000000000000000000000000000000`) and the
  hello reply its reply buffer held, which reads as the V22/V23 head; the simulated recovery mode answers with that
  reply byte for byte.
- **The simulated pedals** (`protocol/src/sim.rs`, behind the `sim` feature for the program's own tests) are ports of
  `tests/uboot_sim.py` (NOR flash that a write can only clear, an erase that sets a sector to `0xFF`, the loader's 3 s
  watchdog on a fake clock, a pedal that drops off the bus after N commands), of `tests/recovery_sim.py`'s hello and
  leave packet by packet, of the bus that `tests/test_uboot_install.py` puts the pedal on, and of the image and package
  builders `tests/fw_layouts.py` and `tools/pxpkg.py`.
- **The commands as a person runs them.** `undertone/src/tests.rs` runs `rescue` (check, yes, restore), a rescue
  answered no, a refused rescue with its advice, the way back to M-VAVE's firmware through the recovery mode, and a
  check, and must show the same window as `tools/undertone.py` (times and paths aside), end with the same exit code,
  send the same transfers and leave the same flash (`commands.json`, from the same script). The Python goldens
  describe the macOS and Linux route, so the tests set `Ctx.windows` to false and every runner takes that route; the
  Windows route (no install, the "click Cancel" hint, a wait on the boot state only) has no test yet.
- **The screens** (stage 4). Each state's screen as plain text compared with the Python screens' text; pictures of the
  full-screen view at 80 x 24 and 100 x 30, dark and light, rendered through a pseudo-terminal and set beside the
  Python gallery; the guided rescue and install driven by key presses against the simulated pedal.

Nothing here runs on a real pedal. Each stage's pull request says what the owner should check on a pedal and on
Windows.

## Stages

Each is its own pull request, complete and green, stacked on the one before while that one waits to merge:

1. This design, the workspace and the CI.
2. The protocol library: the framing, the commands, the checks and the plans, with the byte-for-byte tests, the safety
   tests and the simulated pedals. The write cannot be reached without a `Confirmed`.
3. The program's USB transports (libusb on macOS and Linux, SCSI pass-through on Windows), the rights each system
   needs, and the commands `rescue`, `install` and `check` with the Python command's plain output and questions.
4. The guided screens over that protocol, with the Python screens' states, copy and look: one screen at a time, the
   pulse on the three buttons to hold, the spinner and the thin progress bar, truecolor with 256- and 16-colour
   fallbacks, `NO_COLOR`, ASCII glyphs where Unicode cannot be shown, `UNDERTONE_NO_MOTION`, centred in about 60
   columns.
5. The release: the programs of the matrix with SHA-256 sums from the release workflow (built by hand or on a branch,
   never published by it), the rescue kit and the site offering the program beside the Python launcher (a new kit
   number with its pin refreshed), and `docs/RESCUE.md` and the installer's Rescue card updated. The Python command
   stays the fallback until the owner has proven the program on a real pedal.
