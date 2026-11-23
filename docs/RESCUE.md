# Rescuing a BlackBox over USB from a Mac or Windows (no extra hardware)

## Quick start: rescue a BlackBox that will not boot

Use this when the pedal shows a black screen or keeps restarting, and the installer page cannot reach it. You need the
USB cable and a Mac or a Windows PC. The first run only checks the pedal and saves a backup. Nothing is written until the
second run.

> **Warning.** Do not install Gamut from an installer page on a pedal that ran M-VAVE V22 or V23, not even after a
> successful rescue. An install over MIDI writes from `0x4000`, over the end of the V22/V23 boot loader, and the pedal
> goes dark again. This project's installer page, `node tools/op.mjs flash` and the update loader in its packages
> refuse such a pedal and write nothing; older installers, upstream's among them, do not. On such a pedal Gamut is
> installed with a command instead, through the chip's USB boot state:
> [Gamut on a BlackBox with V22 or V23](#gamut-on-a-blackbox-with-v22-or-v23).

> **Status.** Path A's tool has restored one real pedal, from a Mac. On path B the same tool has put the official V23
> app back on one real pedal whose V23 boot loader was intact, reached through the recovery mode's leave
> ([below](#a-pedal-on-m-vaves-v22-or-v23)). A pedal that went dark after an install for the old layout is verified in
> simulation only: the kit's files were run against a simulated pedal with M-VAVE's real V22 and V23 packages, and the
> pedal ended on the exact official image. This matches one community report of a real pedal restored this way
> ([issue 31](https://github.com/isod89/openpocket/issues/31)). The Undertone team has not run that case on a real
> pedal, and has not run the Windows launcher on a real pedal.

### 1. Find your path

The rescue writes M-VAVE's official firmware back, and the firmware file must match the firmware the pedal had before
Gamut. Ask one question: did this pedal ever run M-VAVE V22 or V23? It did if you updated it with M-VAVE's own
updater after July 2026, or if it came with V22 or V23.

| Path | The pedal had | Firmware file | The pedal ends on |
| --- | --- | --- | --- |
| A | V16, V17 or V20, and never V22 or V23 | `BlackBox_020.fwsc` | Official V20 |
| B | V22 or V23 at any time, or you are not sure | `BlackBox_023.fwsc` | Official V23 |
| C | Something else: both files are refused | None | Stop. Keep the backup |

The check in step 4 is the test, and it writes nothing. With the right file it prints
`head [0, 0x4000) matches the image`. With the wrong file it ends with `REFUSED`. Then run the check again with the
other path's file. If both files are refused, you are on path C: stop, do not try other files, and keep the backup.

V22 and V23 are one group. `BlackBox_022.fwsc` works the same way on either pedal, and the pedal then ends on V22.

### 2. Downloads

- [Python 3](https://www.python.org/downloads/). On Windows, tick "Add python.exe to PATH" on the installer's first
  screen. No driver is needed.
- The rescue kit, `OpenPocket-rescue-kit-<number>.zip`, from the Rescue card of the installer page, or built from
  this repository. Unzip it. It makes
  one folder, `OpenPocket-rescue-kit`. [The rescue kit](#the-rescue-kit) below says what is in it.
- The firmware file for your path, in the kit's `firmware` folder under the name in the table above. The kit from this
  repository does not hold M-VAVE's firmware. Two places have it:
  - The full kit at [openpocket.vinspee.me/rescue](https://openpocket.vinspee.me/rescue/) holds the V20, V22 and V23
    files in its `firmware` folder. Use that kit as it is, or copy the file from it.
  - [M-VAVE's download page](https://www.m-vave.com/appdownload) offers the current BlackBox file. In November 2026 that
    was V23. It is called `BlackBox.fwsc`: rename it to `BlackBox_023.fwsc`.
- Mac only: [Homebrew](https://brew.sh), then `brew install libusb` in Terminal, once. Linux needs `python3` and
  `libusb-1.0` and has not been tested.

### 3. Open a prompt in the kit folder

**Windows.** Press the Windows key, type `cmd`, right-click "Command Prompt" and choose "Run as administrator". Click
Yes. Use Command Prompt, not PowerShell: the lines below do not work in PowerShell. Open the `OpenPocket-rescue-kit`
folder in File Explorer until you see `RESCUE.bat`, click the address bar and copy the location. In the prompt type
`cd /d "`, right-click to paste, type `"` and press Enter.

**Mac.** Open Terminal. Type `cd ` (with a space after it), drag the `OpenPocket-rescue-kit` folder onto the Terminal
window, and press Enter.

### 4. Check and back up. Nothing is written

Unplug the pedal. Type the line for your path and press Enter. When it says it is waiting for the pedal, plug the pedal
straight into the computer, with no hub.

| | Path B: V22 or V23, or not sure | Path A: V16, V17 or V20 |
| --- | --- | --- |
| Windows | `RESCUE.bat --package firmware\BlackBox_023.fwsc` | `RESCUE.bat --package firmware\BlackBox_020.fwsc` |
| Mac | `sudo python3 tools/uboot_rescue.py --package firmware/BlackBox_023.fwsc` | `sudo python3 tools/uboot_rescue.py --package firmware/BlackBox_020.fwsc` |

On Windows, if it offers to format a drive, click Cancel. Never click Format. On a Mac, type your password when asked
(nothing shows while you type). If the Mac offers to install developer tools, click Install, then type the line again.
The first run downloads one small loader file, so it needs internet once.

The right file ends like this. The times, the count and the backup's name differ on your pedal:

```
[   0.0s] backup saved: ...OpenPocket-rescue/blackbox-20261119-230057.dump.bin
[   0.0s] head [0, 0x4000) matches the image
[   0.0s] 155 of 155 sectors in [0x4000, 0x9f000) differ
[   0.0s] run-app sent: the pedal restarts

Read-only run finished, nothing was written. 155 sectors differ from the image. Backup: ...
```

The wrong file ends like this instead. The pedal is not harmed. Unplug it and run the other path's line:

```
REFUSED: the flash head [0, 0x4000) is not the image's head: this package belongs to another layout; nothing was written
```

The backup is in the `OpenPocket-rescue` folder of your home (user) folder. Keep it: it is the only copy of what the
pedal held before the rescue.

### 5. Restore

Only after the check printed `head [0, 0x4000) matches the image`. Unplug the pedal, type the line with the same file,
and plug the pedal in when it is waiting. Do not touch the cable while it writes.

| | Path B | Path A |
| --- | --- | --- |
| Windows | `RESCUE.bat --write --package firmware\BlackBox_023.fwsc` | `RESCUE.bat --write --package firmware\BlackBox_020.fwsc` |
| Mac | `sudo python3 tools/uboot_rescue.py --write --package firmware/BlackBox_023.fwsc` | `sudo python3 tools/uboot_rescue.py --write --package firmware/BlackBox_020.fwsc` |

It shows the same lines as the check, counts the sectors it writes, and ends with `Done`. If it stops in the middle,
run the same line again: it continues where it stopped.

### 6. Restart

Unplug the cable. Switch the pedal off, wait 5 seconds, switch it on. The pedal should start on M-VAVE's official
firmware: V20 after path A, V23 after path B. Settings saved on the pedal may be reset. The backup holds what was there
before.

**Path B: do not install Gamut on this pedal from the installer page.** It would go dark again, for the reason in the
warning at the top of this page. The install for such a pedal is a command:
[Gamut on a BlackBox with V22 or V23](#gamut-on-a-blackbox-with-v22-or-v23).

### If it does not work

| What you see | What to do |
| --- | --- |
| `REFUSED`, one file | The file is for another firmware than your pedal had. Nothing was written. Run the check with the other path's file. |
| `REFUSED`, both files (path C) | Stop. Do not try other files and do not use `--write`. Keep the backup. Run the fingerprint helper below and [open an issue](https://github.com/VinSpee/undertone/issues) with its output and the window's text. The other route is the SD-card recovery in `flash/`, which needs an ESP32-S3 board. |
| `ERROR ... CRC check failed`, or `not a firmware package` | The firmware file is damaged or is not a BlackBox firmware file. Nothing was sent to the pedal. Get the file again. |
| `ERROR ... not found` | The firmware file is not in the kit's `firmware` folder under the name in the line you typed. |
| "not recognized", or `cd /d` fails | The window is PowerShell. Open Command Prompt as in step 3. |
| It stops in the middle, or says it gave up | Run the same line again. It continues where it stopped. |
| No screen after step 6 | Keep the backup and [open an issue](https://github.com/VinSpee/undertone/issues) with the window's text. |

[Other symptoms](#other-symptoms), near the end of this page, lists more.

## The rescue kit

The kit is one zip that unpacks to one folder, `OpenPocket-rescue-kit`. Its number is in the zip's name and in its
`README.txt`. The folder's name never changes, so the commands above stay the same from kit to kit.

| File | What it is |
| --- | --- |
| `RESCUE.bat`, `tools/uboot_rescue.py`, `tools/pocketx_fw.py` | The rescue tool of this repository, unchanged |
| `tools/pd40_recovery.py` | Reads M-VAVE's recovery mode on a V22 or V23 pedal and sends its leave to the USB boot state ([below](#a-pedal-on-m-vaves-v22-or-v23)) |
| `fingerprint.bat`, `tools/head_fingerprint.py` | Says which firmware a backup or a firmware file belongs to |
| `extract-flash.bat`, `tools/extract_flash.py` | Takes `flash.bin` out of a package, for `--image` |
| `firmware/README.txt` | The three file names, their SHA-256, and where to get the files |
| `README.txt`, `LICENSE.txt`, `SHA256SUMS.txt` | One page of instructions, the GPL-3.0 text, the SHA-256 of every file |

The kit holds none of M-VAVE's firmware. A kit with M-VAVE's V20, V22 and V23 packages, the full kit, is published on
the project's own site only and never in this repository or its releases.

**The two helpers.** Both only read files on the computer. They need no pedal, no administrator and no `sudo`.

| | Windows | Mac |
| --- | --- | --- |
| Which firmware the pedal had, from the newest backup | `fingerprint.bat` | `python3 tools/head_fingerprint.py` |
| Which firmware a file is | `fingerprint.bat firmware\BlackBox_023.fwsc` | `python3 tools/head_fingerprint.py firmware/BlackBox_023.fwsc` |
| `flash.bin` out of a package | `extract-flash.bat firmware\BlackBox_023.fwsc` | `python3 tools/extract_flash.py firmware/BlackBox_023.fwsc` |

The fingerprint is the SHA-256 of the first `0x4000` bytes of the flash. `d540d2217091` is a V16, V17 or V20 pedal
(path A). `ef3dfea17ea8` is a V22 or V23 pedal (path B). You need the extraction only if `--package` stops with an
`ERROR` about the file: run steps 4 and 5 with `--image BlackBox_023-flash.bin` in place of `--package ...`.

**Checking the download.** The installer page shows the kit's SHA-256 beside its download button. Compare it with
`certutil -hashfile OpenPocket-rescue-kit-6.zip SHA256` on Windows or `shasum -a 256 OpenPocket-rescue-kit-6.zip` on a
Mac, with your kit's number in the name.

**Building it.** `node tools/op.mjs kit` (or `make kit`) writes the zip and `manifest.json` into `docs/rescue/`, where
the installer page looks for them. It needs only Python 3. The same sources give the same bytes on every computer, and
`rescue/kit.sha256` pins them. [`rescue/README.md`](../rescue/README.md) has the rules for changing the kit and for
building the full kit.

## How it works

Use this when the pedal restarts in a loop or shows a black screen after an install, and the installer's rescue mode
cannot finish. Between crashes the pedal sits
about 44 seconds in the JieLi mask-ROM USB boot state ("UBOOT": USB 4C4A:8057, shown by macOS as `WL80UBOOT1.00`). The
mask ROM is chip ROM, so it cannot be damaged. `tools/uboot_rescue.py` waits for that state, loads JieLi's RAM loader and
rewrites the app area of the flash from the official package, then restarts the pedal.

The installer page cannot do this part. In this state the pedal is a USB mass-storage device, and browsers refuse web pages
access to every mass-storage interface (WebUSB's protected classes), on every system and whatever driver is installed. The
page can only reach a pedal that answers over MIDI; the rescue below is a command that runs on the computer.

## One-time setup (macOS)

```
brew install libusb
```

That is all. The tool is one Python 3 file that calls libusb through `ctypes` (no `pip install`). It needs two files:

- The official package, `~/Documents/BlackBox (2).fwsc` (BlackBox_016) by default, or `--package FILE.fwsc`, or a raw flash
  image with `--image flash.bin`. Every CRC of a package is checked before it is used.
- JieLi's `wl82loader.bin`, downloaded once into the git-ignored `build/cache/` from kagaimiq/jl-uboot-tool (commit
  `c32b28e`, the same pin as `flash/installer-fm1buddy-pocketx.bat`) and checked against SHA-256
  `d41da6126760c9d66660bcc0cac8d27d221806c5e369a8036921efe68dca5376` on every run. It is not in this repository. `make clean`
  removes the cache; `--loader FILE` uses a copy you downloaded yourself.

## One-time setup (Windows)

Install Python 3 from [python.org](https://www.python.org/downloads/) and tick "Add python.exe to PATH". Nothing else: no
libusb, no Zadig, no driver change. Windows keeps its own mass-storage driver on the pedal, and the tool sends the same
commands through it (SCSI pass-through, the way kagaimiq/jl-uboot-tool reaches these chips on Windows). Windows lets only an
administrator do that, so the tool runs in a Command Prompt opened as administrator. The files are the same as on a Mac:
the official package (pass it with `--package`) and `wl82loader.bin`, downloaded and checked as above.

## The commands

`make rescue` and `make rescue-write` (or `node tools/op.mjs rescue [--write]`, the entry point next to `flash`) run the tool with
`sudo` for you and pass options on (`make rescue ARGS="--package FILE.fwsc"`). `make doctor` shows whether libusb, the package and
the loader are in place. The `sudo python3 tools/uboot_rescue.py` lines below are the same thing written out.

macOS keeps its own mass-storage driver on the pedal in this state, and libusb needs root to take the interface from it.
Plug the pedal straight into the Mac (no hub), start the command, and it waits for the pedal and starts by itself the moment
it appears.

1. **Read-only first.** Nothing is written to the pedal's flash; the loader goes to RAM only.

```
make rescue                              # = sudo python3 tools/uboot_rescue.py
```

It checks that the pedal answers INQUIRY as `WL82 UBOOT1.00`, loads the loader, reads the chip key (must be `0x980F`) and
the flash id (must be a 1 MiB flash), saves a backup of the whole flash to `~/OpenPocket-rescue/blackbox-<time>.dump.bin`,
compares the pedal's head `[0, 0x4000)` with the image's, reports how many sectors differ, and sends run-app. Keep this
backup: it is the only copy of what the pedal held before the rescue.

On Windows, open a Command Prompt as administrator (press the Windows key, type `cmd`, right-click "Command Prompt",
"Run as administrator"; not PowerShell), go to the Undertone folder and run the same tool through `RESCUE.bat`:

```
cd /d C:\path\to\openpocket
RESCUE.bat --package "C:\Users\you\Downloads\BlackBox.fwsc"            (read-only)
RESCUE.bat --write --package "C:\Users\you\Downloads\BlackBox.fwsc"    (the rescue, after the read-only run passed)
```

The backup goes to `%USERPROFILE%\OpenPocket-rescue`. Windows may say it found a drive and offer to format it while the
pedal is in this state: click **Cancel**, never Format. The tool finds the pedal among the disks by asking each one to name
itself (SCSI INQUIRY, which reads nothing and changes nothing) and only goes on with the one that answers `WL82 UBOOT1.00`.

2. **The rescue**, only after the read-only run has passed:

```
make rescue-write                        # = sudo python3 tools/uboot_rescue.py --write
```

Same steps, then for every 4 KiB sector in `[0x4000, end of the image)` that differs: erase, write, read back, compare. When it prints
`Done`, power-cycle the pedal. If the pedal drops out of UBOOT in the middle (it reboots into the crashing app and comes
back), the tool waits and starts again by itself; running it again later also resumes. Only the sectors that still differ are
written, so a rerun is short.

Options (after `ARGS=` with make): `--check` (prerequisites only), `--package`, `--image`, `--loader`, `--backup-dir DIR`, `--attempts N` (UBOOT windows to try, default 10).
Exit codes: 0 done, 1 setup problem (libusb, root, files), 2 refused by a safety check, 130 stopped by Ctrl-C.

## A pedal on M-VAVE's V22 or V23

Use this for a BlackBox whose V22 or V23 boot loader is intact: a pedal that runs the official V22 or V23, one that runs
Gamut installed as in [the next section](#gamut-on-a-blackbox-with-v22-or-v23), or one whose app no longer starts but
which still shows `RECOVERY` with the key combination of step 1. M-VAVE's boot loader has a recovery mode of its own, and
that mode is the way from such a pedal to the chip's USB boot state, where `uboot_rescue.py` and `uboot_install.py`
work. `tools/pd40_recovery.py` reads the recovery mode and can send its one leave command. It never writes to the
pedal's flash.

To install Gamut or to put M-VAVE's firmware back, go to the next section: `tools/uboot_install.py` sends the same
hello and leave by itself. This section is for looking at a pedal without writing, and for the rescue kit, which holds
the helper and `uboot_rescue.py` only.

**What a real pedal did.** One BlackBox on the official V23, on 23 November 2026:

- The recovery device appeared with the key combination. The hello was accepted (status 0, state 0, the boot area of
  the official V22 and V23), but its reply came over the control endpoint only: the bulk IN endpoint sent 64 zero
  bytes, then nothing.
- The recovery mode ended about 4 seconds after power-on every time, whatever the computer did: with no computer
  attached, after a probe that sent one hello, and in the middle of a flash write. The likely cause is the chip's
  long-press reset, which resets a BlackBox about 4.3 s after power-on unless software turns it off
  (`docs/HARDWARE-HANDBOOK.md`, section 4), and which the recovery code never turns off. That cause is inferred: the
  reset source was not read on this pedal.
- The leave worked. After `--leave --accept-inferred --accept-control-reply` the pedal left the bus about 275 ms later
  and came back as the chip's USB boot state (`4C4A:8057`) about 500 ms after that. `uboot_rescue.py`, already waiting
  under `sudo`, took it, read the chip key `0x980f` and the flash id `0xeb6014` (1024 KiB), saved a backup and wrote.
- The USB boot state lasts only a few seconds when nothing talks to it. The tool that uses it must be waiting before
  the pedal is switched on.

1. **Enter the recovery mode.** Switch the pedal off. Hold HOME, the right footswitch and the knob's PUSH, switch it
   on, and keep holding until the screen shows `RECOVERY`. The Mac then lists `PD40 BOOT Recovery` (USB `3654:7940`)
   in `ioreg -p IOUSB` or in System Information. The pedal restarts by itself about 4 seconds after power-on, so start
   the command of step 2 or 3 first where it can wait, or at once.
2. **Read it.** Nothing is written.

   ```
   python3 tools/pd40_recovery.py 2>&1 | tee recovery-probe.log
   ```

   Every transfer is printed with its bytes and its time in milliseconds. Expect `hello: status 0 (accepted), state 0`,
   the write range `[0x6000, 0x9f000)`, and the boot area's CRC-32 `0xb19d96a1`, which is the head of the official V22
   and V23. Any other CRC means the pedal's head is not that head: stop. The line under `hello` says whether the reply
   came over the bulk IN endpoint or only over the control endpoint. The protocol does not report the chip key or the
   flash id.

   After the probe the helper releases the device and lists the USB devices for 60 seconds (`--watch` changes that); it
   sends nothing more. When the pedal leaves the bus, it logs the time since the last command it sent and since its
   first access, for example `3654:7940 left the bus: the recovery mode, seen gone 2480 ms after the last command sent
   (command 1, tag 1) and 2510 ms after the first access`, and ends with exit code 4. Its last lines say what came
   back: the chip's USB boot state (`4C4A:8057`), the recovery mode again, the normal pedal (the stock app,
   `3654:7756`), or nothing.
3. **The leave, with the rescue tool waiting.** This is the route for the kit, and the one the real pedal took. Start
   the rescue tool's read-only run first, in a second Terminal, so that it is waiting:
   `sudo python3 tools/uboot_rescue.py --package firmware/BlackBox_023.fwsc` in the kit folder, or
   `make rescue ARGS="--package BlackBox_023.fwsc"` in the repository. Then enter the recovery mode and run at once:

   ```
   python3 tools/pd40_recovery.py --leave --accept-inferred --accept-control-reply 2>&1 | tee recovery-leave.log
   ```

   It sends the hello and the single command 6, and watches the bus. Expect `the chip's USB boot state (4C4A:8057)
   appeared`, and in the other Terminal the rescue tool's chip key, backup and head check, as in the quick start. What
   the other endings mean:

   - Exit code 3: the pedal left after the leave but the USB boot state did not appear. If the pedal's own reset came
     first, enter the recovery mode again and run the command sooner. If the pedal restarts into its firmware every
     time, stop and write nothing to it.
   - Exit code 5: the pedal stayed in the recovery mode. It did not act on command 6.
   - `REFUSED`: without `--accept-control-reply` the leave is not sent when the hello reply came over the control
     endpoint only, and without `--accept-inferred` it is never sent. The text says why.

**What is verified and what is not.**

| | Status |
| --- | --- |
| The key combination, the recovery device, the hello accepted over the control endpoint only | Seen on one real BlackBox on V23 |
| The recovery mode ending about 4 s after power-on, whatever the computer does | Seen on that pedal in every run. The cause, the chip's long-press reset, is inferred |
| The leave, also when the hello reply came over the control endpoint only, and the USB boot state after it | Seen on that pedal: gone about 275 ms after the leave, back as `4C4A:8057` about 500 ms later |
| Any other pedal, and a pedal on V22 | Not tried. V22 and V23 carry the same boot loader, byte for byte |
| The helper's probe, bus watch, timing of a departure, leave, refusals and handling of bad answers | Verified against a simulated recovery mode (`tests/test_pd40_recovery.py`, and the kit's own copy in `tests/test_rescue_kit.py`) |
| USB IDs, strings and descriptors of the recovery mode | Verified: byte for byte in the V23 boot loader |
| The frame and reply format, the CRC-32 (zlib's), the requests `0x43` and `0x44`, command 6 and what it does: it answers, writes `usb_update_mode` to RAM, not to the flash, and resets the processor core once its reply has been read | Read in the V23 boot loader's code; the leave's effect seen on that pedal |
| The helper on Linux or Windows | Not tried. On Windows, set `LIBUSB_PATH` to `libusb-1.0.dll` |

**Administrator rights.** The recovery mode's interface is vendor-specific and no macOS driver holds it, so the helper
runs without `sudo`. `uboot_rescue.py` needs `sudo` on a Mac and an administrator's Command Prompt on Windows, as
above.

**Safety rules.** The helper sends two commands only: 1 (hello) and 6 (leave), with no data. It refuses the
protocol's write commands, 2 (manifest), 3 (block), 4 (erase and commit) and 5 (start the new app), before anything is
sent, and every vendor request but `0x42` (only with `--sync`, and never between the hello and the reads of its reply),
`0x43` and `0x44`. It sends one hello per run and never repeats a transfer that failed: after a bulk IN read that gets
nothing it reads nothing more there, and when the pedal leaves the bus it only lists the USB devices. It stops at the
first answer it does not expect and sends nothing more. It sends the leave only from state 0 or 6, the states in which
the recovery mode accepts it, and only when the hello reply came over the bulk IN endpoint or `--accept-control-reply`
is given as well. That flag changes only whether the one command 6 may go out; it adds no command and no request.

Exit codes: 0 done (after a probe without the leave: the pedal stayed in the recovery mode for the whole watch), 1 setup
problem, no recovery device or a failed transfer, 2 refused or a bad answer, 3 the pedal left after the leave but the
USB boot state did not appear, 4 the pedal left the recovery mode on its own during the probe or the watch after it, 5
the pedal stayed in the recovery mode after the leave, 130 stopped by Ctrl-C.

## Gamut on a BlackBox with V22 or V23

**Status.** Gamut runs on one real BlackBox that came from M-VAVE's official V23, with no downgrade. It was installed
on 23 November 2026 through the chip's USB boot state, by hand: the leave of the section above, `uboot_rescue.py`
waiting in a second Terminal, and an image put together by hand. `tools/uboot_install.py` does the same steps in one
command. That command has been run against simulated pedals only, not yet on a real one. The installer page still
refuses a BlackBox on V22 or V23 and sends nothing to it.

The same command also installs on the old flash layout and puts M-VAVE's firmware back on either layout. It reads the
pedal's boot area, names the layout, and refuses anything else.

### Which route applies

| The pedal | Install or update Gamut | Back to M-VAVE's firmware |
| --- | --- | --- |
| Old head (M-VAVE V16, V17, V20), and it starts | The installer page, over USB MIDI. Nothing changes there | The installer page, with the official file |
| Old head, restarting in a loop or dark | The quick start with `BlackBox_020.fwsc`, then the installer page. Or `uboot_install.py`, while the pedal is in its USB boot state | The quick start, or `uboot_install.py --official BlackBox_020.fwsc` |
| V22 or V23 head, boot loader intact (it starts, or shows `RECOVERY` with the three controls) | `uboot_install.py`, this section | `uboot_install.py --official BlackBox_023.fwsc`, this section |
| V22 or V23 pedal that went dark after an install for the old layout | The quick start, path B, first. It restores the end of the boot loader, which `uboot_install.py` never writes | The quick start, path B |
| Any other head | Not with `uboot_install.py`: it refuses a boot area it does not know | The installer page or the quick start, as before |

On the old head, `uboot_install.py` has been run against simulated pedals only. Use the installer page there when the
pedal starts.

### Why it works

These facts come from reading the V22/V23 boot loader's code (V22 and V23 carry the same boot loader, byte for byte):

| | V20 and older | V22 and V23 |
| --- | --- | --- |
| Boot loader | `[0xA0, 0x38D0)` | `[0xA0, 0x5CA0)` |
| App area (`app_dir_head`) | `0x4000` | `0x6000` |
| Stock settings (`VM`), radio (`BTIF`), user area, `key_mac` | `0xA5000`, `0xBE000`, `0xBF000`, `0xFF000` | `0x9F000`, `0xBE000`, `0xBF000`, `0xFF000` |
| CRC-32 of the boot area `[0, app area)` | `0x5A2121FF` (V16, V17, V20) | `0xB19D96A1` |
| Supply levels the boot loader sets | none (VDC14 3, SYSVDD 11 stay) | VDC14 7, SYSVDD 15, VDDIOM 4 |

- **The boot loader starts the app area at `0x6000` after four CRC16 checks only:** the flash header (32 bytes at 0,
  key `0xFFFF`), each head entry up to `app_dir_head`, and the first 32 bytes at `0x6000` under the chip key `0x980F`.
  It does not check the area's data CRC, any length, version or identity. It maps `0x02000000` to the start of the area
  and calls `0x02000120`, so Gamut runs there unchanged. The real pedal confirmed it: Gamut started.
- **Gamut's app area is the same bytes on both layouts.** Each package's area is `0x99000` bytes, and its bytes do not
  depend on where it sits. At `0x6000` it fills `[0x6000, 0x9F000)` exactly and ends where the stock settings begin; at
  `0x4000` it fills `[0x4000, 0x9D000)`. The build writes it as a file of its own beside the BlackBox package,
  `build/apps/gamut/BlackBox_950-v23.bin`; its SHA-256 is in the release pin, `firmware/apps/gamut/release.sha256`,
  and `uboot_install.py` installs no other build.
- **In the USB boot state the whole flash can be read and written**, so the tool, not the pedal, keeps the write
  inside the app area. `uboot_install.py` composes the image from the pedal's own boot area and the app area, and its
  writer refuses every erase and write outside `[0x6000, 0x9F000)` on this layout (`[0x4000, 0xA5000)` on the old one).
  It never changes the boot loader, the stock settings, the radio records, the user area or `key_mac`.
- **Gamut's own data stays where it is on every pedal:** NAM models from `0xC0000`, its update staging at `0xE0000`,
  presets at `0xF0000`, IRs from `0xF4000`, all inside the stock user area, as on the old head. Gamut never writes the
  stock settings, the radio records or `key_mac`. It reads its data with direct flash reads, not through the mapped
  window, so the window's other start (`0x6000`) changes nothing for it.

### Why not through the recovery mode's own write

M-VAVE's recovery mode can rewrite `[0x6000, 0x9F000)` itself, and an earlier version of this guide installed that
way with `tools/pd40_install.py --write`. That write cannot finish on this chip, and the tool now refuses it.

On the real pedal the recovery mode ended about 4.3 s after power-on, in the middle of the flash write of block 8,
and left the app area erased and half written. The pedal's own check of the image, the first pass, took 1.9 s and fits. The write needs
about 14 s: 153 blocks at about 74 ms each, set by the flash's erase and program times. It cannot continue across
entries either: each entry clears the recovery state, and the write pass starts again at the first block. The
protocol has no command that could turn the reset off.

The protocol, as read: frames of 4608 bytes from `SBU2` (command, tag, argument, payload length, payload CRC-32, at most
4096 bytes of payload) and 64-byte replies from `SBR2` (status, state, next offset, image length, the write range, the
head's CRC-32).

| Command | State before → after | What it does | Sent by this repository's tools |
| --- | --- | --- | --- |
| 1 hello | any | the reply only | yes |
| 2 manifest | 0 → 1 | the image's length, CRC-32 and one CRC-32 per 4 KiB block, the CRC-32 of the pedal's `[0, 0x6000)`, the entry `0x02000120` | `pd40_install.py --verify` |
| 3 block | 1 → 2 | each block checked against the table, in order, and the whole image's CRC-32 after the last. **Nothing is written** | `pd40_install.py --verify` |
| 4, argument 2 | 2 → 3 | erases the sector at `0x6000`: from here the pedal starts no app until the commit | never |
| 3 block | 3 → 4 | each block erased, programmed and read back; block 0 is kept in RAM | never |
| 4, argument 4 | 4 → 5 | checks the whole image, writes block 0 (the area head) last, checks again | never |
| 5 start | 5 | resets into the new app | never |
| 6 leave | 0 or 6 | resets the processor core; the chip's ROM then enters its USB boot state | `pd40_recovery.py --leave`, `uboot_install.py` |

`tools/pd40_install.py` keeps the dry run and `--verify`, the pedal's own check of an image, which writes nothing:
`python3 tools/pd40_install.py build/apps/gamut/BlackBox_950-v23.bin --verify --accept-control-reply`, started the
moment the screen shows `RECOVERY`. The install does not need it.

### The supply levels

On this head the boot loader leaves VDC14 at 7, SYSVDD at 15 and VDDIOM at 4, the stock firmware's levels. Gamut keeps
the levels it finds (`firmware/base/start.h`). On the old head it finds 3 and 11, at which it was tuned. On the real
pedal the boot screen read `PWR 7 15 (BOOT LEVELS)`, as expected for this head. When v30 copied the stock firmware's
whole power setup (these levels and also the 1.3 V supply moved to the DC-DC), a Pocket X measured 77 % processor load
instead of 61 % with crackles; which part of that setup caused it was never shown (`docs/HARDWARE-HANDBOOK.md`,
section 4). The V23 boot loader sets the levels but not the DC-DC.

Gamut could set its own levels at its start: the registers are the ones it reads for its boot screen, and
`firmware/bsp/chip/fm1_sys.h` has the functions that raise them, which v30 used. Lowering them has never been done by any
firmware of this project (those functions only raise), the handbook warns that some units read flash and RAM wrong at
the low levels under load, and the higher levels are the ones M-VAVE's own firmware runs at all the time. So the levels
are left as they are, and the load at them is measured by the first-run check below.

### Before the first run

1. A Mac with Python 3 and libusb (`brew install libusb`). The tool needs `sudo`: macOS keeps its mass-storage driver
   on the USB boot state. Linux has not been tried. The tool does not run on Windows.
2. Gamut is built: `node tools/op.mjs package`, which ends with `release pin: gamut's image and packages are the
   release's`. The tool installs `build/apps/gamut/BlackBox_950-v23.bin` and refuses a file that is not the pin's.
3. You have M-VAVE's `BlackBox_023.fwsc` for the way back (from M-VAVE, or the full rescue kit's `firmware` folder).
4. The pedal is plugged straight into the Mac, with no hub, and you know the key hold: pedal off, hold HOME, the right
   footswitch and the knob's PUSH, switch on, keep holding until the screen shows `RECOVERY`.

The first run downloads JieLi's `wl82loader.bin` once and checks its SHA-256, as the rescue tool does. Keep every output
(`2>&1 | tee FILE`).

### The install

The order matters in every run: **start the command first, wait until it says it is waiting, and only then switch the
pedal on with the three controls held.** The recovery mode ends about 4 seconds after power-on, and the USB boot state
after it lasts only seconds while nothing talks to it.

1. **The dry run. Nothing is written.**

   ```
   sudo python3 tools/uboot_install.py 2>&1 | tee gamut-usb-dry.log       # or: make usb-install
   ```

   It checks the app area, prints `waiting for the pedal; nothing is sent until it appears`, and waits. Do the key
   hold. Expect, in this order:

   ```
   [     0 ms] found 3654:7940 'SINCO' 'PD40 BOOT Recovery': M-VAVE's recovery mode
   [   ... ms] hello: status 0 (accepted), state 0 (no update started)
   [   ... ms] leave sent: waiting for the chip's USB boot state (USB 4C4A:8057)
   [   ... ms] the chip's USB boot state appeared ... ms after the leave
   [   0.0s] pedal found in the chip's USB boot state
   [   ...s] loader running: chip key 0x980f, flash id 0xeb6014 (1024 KiB)
   [   ...s] flash read: 1024 KiB
   [   ...s] backup saved: ...OpenPocket-rescue/blackbox-<time>.dump.bin
   [   ...s] boot area [0, 0x6000) CRC-32 0xb19d96a1: M-VAVE's V22/V23 head; its app area is in [0x6000, 0x9f000)
   [   ...s] head [0, 0x6000) matches the image
   [   ...s] 153 of 153 sectors in [0x6000, 0x9f000) differ
   [   ...s] run-app sent: the pedal restarts

   Dry run finished, nothing was written. 153 sectors differ ...
   ```

   The pedal restarts into the firmware it had. Keep the backup: it is the copy of the whole flash from before Gamut.
   Any `REFUSED` here: stop and send the log back.

2. **The write.** The same command with `--write`, and the same key hold once it is waiting:

   ```
   sudo python3 tools/uboot_install.py --write 2>&1 | tee gamut-usb-write.log       # or: make usb-install ARGS=--write
   ```

   It shows the same lines, saves another backup before the first erase, then counts the sectors it writes (`written
   16/153` and so on) and ends with `Done: 153 sectors written and verified`. Each sector is erased, written, read back
   and compared. Do not touch the pedal or the cable until the tool ends.

3. **The first-run check.** Switch the pedal off and on. On the boot screen, note the line `PWR`: on this head it should
   read `PWR 7 15 (BOOT LEVELS)`. Then, with the pedal on USB:

   ```
   node tools/op.mjs dsp 2>&1 | tee gamut-v23-dsp.log
   ```

   It plays every saved preset for 6 seconds and reads the load, the peak, the late blocks and the safety bypass. Exit
   code 0 means no preset was late or bypassed. Play through the presets and listen for crackles. Late blocks, the
   bypass or crackles mean Gamut needs its own supply levels on this head; put the official app back meanwhile if they
   bother you.

Updating Gamut later on this pedal works the same way, with the new release's `BlackBox_950-v23.bin`. The installer
page cannot update it: its update loader reads this head, refuses it, and writes nothing.

### If it stops

Every run resumes. The tool reads the flash again, compares, and writes only the sectors that still differ. The boot
area is never written, so the key hold and the recovery mode stay available after any interruption.

| What the log shows | What it means | Do |
| --- | --- | --- |
| It stays at `waiting for the pedal` | neither the recovery mode nor the USB boot state is on the bus | do the key hold again, until the screen shows `RECOVERY`; check the cable and the port. Ctrl-C stops the tool |
| `the recovery mode ended before the leave was sent` | the pedal's own reset came first | the tool is still waiting: do the key hold again |
| `ERROR: the chip's USB boot state did not appear` (exit code 3) | the pedal left after the leave and did not come back in the USB boot state | run the command again and do the key hold only once it is waiting. If the pedal restarts into its firmware every time, stop and send the log back |
| `ERROR: the pedal stayed in the recovery mode` (exit code 5) | it did not act on the leave | nothing was written. Send the log back |
| `the pedal went away or stopped answering ... waiting for it again (1/10)` | the USB boot state ended in the middle of the run | the tool waits: do the key hold again. It continues where it stopped |
| `gave up after 10 tries` | the same, ten times | run the command again; it resumes. Send the log back: it shows how long the USB boot state lasts on this pedal |
| `REFUSED` | a check stopped the run; the line says which. Nothing was written after it | do not try other files. Keep the backup and send the log back |
| The write stopped part of the way and the pedal no longer starts | the app area is half written | do the key hold and run the same command again. To go back instead, run it with `--official BlackBox_023.fwsc --write` |
| `RECOVERY` no longer appears with the three controls | the boot loader itself is damaged; this tool never writes it, so something else did | the chip's USB boot state then appears by itself: use the quick start with `BlackBox_023.fwsc` |
| Gamut starts, then crashes twice in a row | Gamut's boot guard asks for the chip's USB boot state (seen on the old head, inferred on this one) | start the command with `--official BlackBox_023.fwsc --write` and do the key hold, or let it take the USB boot state when the pedal enters it |

### The way back

M-VAVE's firmware, from its official package. The file is never part of this repository:

```
sudo python3 tools/uboot_install.py --official BlackBox_023.fwsc 2>&1 | tee official-usb-dry.log
sudo python3 tools/uboot_install.py --official BlackBox_023.fwsc --write 2>&1 | tee official-usb-write.log
```

Do the key hold for each run, once it is waiting. The package's boot area must be the pedal's, byte for byte, so the V20
file is refused on a V22/V23 pedal and the V22/V23 files on an old-head pedal. `BlackBox_022.fwsc` works the same way
and the pedal then ends on V22. The tool writes the package's app area to `[0x6000, 0x9F000)`. The boot area was never
changed, so the pedal then holds what M-VAVE's own update leaves below `0x9F000`, byte for byte. The stock user area
from `0xBF000` still holds what Gamut stored there, as after a return to the official firmware on the old head. On the
real pedal this restore was done once, with `uboot_rescue.py` and the official V23 image after the recovery-mode write
had failed: it wrote 9 sectors and took seconds.

A backup of this pedal, saved by an earlier run of this tool or of `uboot_rescue.py`:

```
sudo python3 tools/uboot_install.py --restore ~/OpenPocket-rescue/blackbox-<time>.dump.bin --write
```

It writes the backup's app area only, `[0x6000, 0x9F000)` here. The backup's boot area must be the pedal's, and its app
area must be one the boot loader would start, so a backup taken while the app area was half written is refused.
Nothing from `0x9F000` up is restored from it.

### A pedal on the old head

The same command works when the pedal's boot area is the old head's (M-VAVE V16, V17 and V20). The old boot loader
has no recovery mode, so the tool waits for the USB boot state itself: a pedal that restarts in a loop is there
between crashes, and the installer page's `Enter UBOOT mode` button (Advanced options) sends a pedal that runs Gamut
there. The tool then writes Gamut's app area to `[0x4000, 0x9D000)`, or with `--official BlackBox_020.fwsc` the
package's app area from `0x4000`, or with `--restore` the backup's `[0x4000, 0xA5000)`. That range ends where V20's
stock settings begin. V16's begin at `0xA3000`, inside it, so on such a pedal the V20 package and a backup put their
own bytes there. This path has been run against simulated pedals only. When the pedal
starts, the installer page remains the route.

### Safety rules of the tool

- The default is a dry run. Writing needs `--write`.
- Before anything is opened: Gamut's app area must have the SHA-256 of the release pin and pass the area's own checks
  (its head under the chip key, the entry `0x02000120`, each file's CRC). An official package must pass every CRC, be
  a BlackBox package of M-VAVE's, and carry a boot area the tool knows. A backup must be a whole 1 MiB dump with a boot
  area the tool knows and an app area the boot loader would start.
- In the recovery mode it sends one hello and one leave, with the helper's checks, and nothing else. A boot area CRC-32
  it does not know gets no leave.
- Before any erase: the chip key must be `0x980F` and the flash id `EB 60 14` (seen on the real pedal) or `85 60 14`
  (the other one the V22/V23 boot loader accepts); the CRC-32 of the pedal's boot area must be `0x5A2121FF` or
  `0xB19D96A1`; an official package's or a backup's boot area must be the pedal's, byte for byte; the backup of the
  whole flash must be complete on disk.
- It never erases or writes below the app area's start (`0x6000`, or `0x4000` on the old head) or from the layout's
  limit up (`0x9F000`, or `0xA5000`). The writer refuses such a command whatever the plan says, and only a fixed list
  of loader commands can be sent, as in `uboot_rescue.py`.

Exit codes: 0 done, 1 setup problem or a failed transfer, 2 refused by a check, 3 the pedal left after the leave but
the USB boot state did not appear, 5 the pedal stayed in the recovery mode after the leave, 130 stopped by Ctrl-C.

### The installer page

The page refuses a BlackBox on official V22 or later and sends nothing to it, because its update loader writes from
`0x4000` and would overwrite the end of this boot loader. Its refusal names this section. A pedal on this head that
runs Gamut reports Gamut, not the official firmware, so the page's own check does not see the head; its update loader
then reads the head, refuses it and writes nothing. Update with `uboot_install.py`.

### What is verified and what is not

| | Status |
| --- | --- |
| The route: the key hold, the leave, the USB boot state taken by a tool that was waiting, the flash read and backed up, 153 sectors written and verified, Gamut started | Done on one real BlackBox from official V23, by hand with `pd40_recovery.py`, `uboot_rescue.py` and a hand-made image |
| The way back on that pedal | Done once with `uboot_rescue.py` and the official V23 image, after the recovery-mode write had failed: 9 sectors |
| The boot loader starts Gamut at `0x6000`; the boot screen reads `PWR 7 15 (BOOT LEVELS)` | Seen on that pedal |
| `uboot_install.py` itself: the one command, its image composition, its guards, the leave and the claim in one process | Verified against simulated pedals only (`tests/test_uboot_install.py`): not yet run on a real pedal |
| Its plan on real data | Computed from that pedal's backups, with no pedal attached: 153 sectors differ for Gamut over official V23, 9 for official V23 over the half-written area, and the V20 package, a backup with another head and the half-written backup are refused |
| The old head with `uboot_install.py` | Simulated only. `uboot_rescue.py` has restored one real old-head pedal |
| A pedal whose reset also cuts the USB boot state short | Not known. On the one pedal the state lasted for the whole read and write once a tool held it. If it is cut, the tool resumes at the next key hold |
| Other V22 or V23 pedals, a pedal on V22, a flash with the id `85 60 14` | Not tried |
| A recovery-mode write | Cannot finish on the pedal tried; `pd40_install.py --write` refuses. Its `--verify` passed on that pedal in 1.9 s |
| Gamut's processor load and sound at the V23 supply levels | The first-run check measures it; no result is recorded here |
| The stock V23 app with Gamut's data in its user area | Not known |
| Linux | Not tried |

## BlackBox V21 factory sounds

The official BlackBox V21 download installs the firmware but contains no sound bank.
Gamut's NAM, preset and loader storage overlap parts of the stock sound bank.
V21 checks all 20 amp and 20 cabinet records at startup and disables the sound bank
when any of them are invalid. In that state M-EFCS cannot restore it one model at a time.

Use the web installer to install the official [BlackBox V21 package](https://www.m-vave.com/appdownload)
if the pedal is running another version. When it shows `BlackBox_021`, click **Verify factory sounds**.
If the check fails, use the steps below on a Mac with M-EFCS, Python 3 and libusb installed
(`brew install libusb`). Connect only the BlackBox and close other apps using the pedal.
The recovery port uses USB Mass Storage, which [WebUSB protects](https://wicg.github.io/webusb/#has-a-protected-interface-class).
The installer can enter recovery mode over MIDI, and the Terminal tool handles the flash transfer.

1. In Terminal, from the Undertone repository, start the read-only check with the same V21 file.
   Replace the example path with the location of your download.

   ```sh
   sudo python3 tools/blackbox_v21_factory.py --package ~/Downloads/BlackBox.fwsc
   ```

2. When Terminal is waiting for UBOOT, click **Enter BlackBox USB recovery** under step 3
   in the installer. The tool checks the complete installed V21 firmware against the download,
   saves a flash backup in `~/OpenPocket-rescue`, and reboots the pedal.
3. Once the read-only check passes, run the same command with `--write` and click the
   recovery button again when Terminal is ready. This replaces the 20 factory amps,
   20 cabs and 80 presets. The tool checks the entire flash after writing. It only
   writes sectors in the factory bank at `0xBF000..0xFCFFF`.
4. After the pedal returns, click **Verify factory sounds** in the installer. This
   compares every record the running firmware returns with the vendor's factory bank.

The tool uses the AM4 files included in the installed M-EFCS app. If they are stored
elsewhere, pass `--assets DIRECTORY` containing `blackbox_am4_ampCab.bin` and
`blackbox_am4_preset.bin`. The files must match the AM4 bank in M-VAVE's official Windows
updater. If USB disconnects during a write, re-enter recovery and rerun the write.
Keep the first flash backup.

## What the first real run showed

The first run on a real, looping BlackBox was done by the captain, who reported that the rescue worked ("the rescue worked!").
Only the files the tool left behind are recorded here; the captain's terminal output was not kept.

| Item | What the files show |
| --- | --- |
| Backups | Two, in `~/OpenPocket-rescue`: `blackbox-20261105-213039.dump.bin` and `blackbox-20261105-213135.dump.bin`, 1,048,576 bytes each (a 1 MiB flash), written 56 s apart. They are byte for byte identical (same SHA-256), so both hold the flash from before any write. |
| What the pedal held | Application `BlackBox_936`, the Bluetooth test image that caused the loop. Its app area passes the package's own CRC checks. |
| Head `[0, 0x4000)` | Identical to the head of the official BlackBox_016 `flash.bin`, so the head check passes. |
| Sectors to write | 159 of the 160 sectors in `[0x4000, 0xA3000)` differed from BlackBox_016 (first `0x4000`, last `0xA2000`). |
| Restored package | BlackBox_016 (`BlackBox (2).fwsc`, the tool's default image). |
| Chip key, flash id | Unknown: they are printed, not saved. The tool's checks (key `0x980F`, 1 MiB flash) passed, because it went on to write. |
| Length of the UBOOT window, sectors written, time taken | Unknown: not saved. A later run should keep its output (`make rescue 2>&1 \| tee rescue.log`). |

The two backups' times are consistent with a read-only run followed by the `--write` run, but no file records which was which.

## Safety rules

- The default is read-only. Writing needs `--write`.
- Writes are limited to whole 4 KiB sectors in `[0x4000, end of the image)`; that is `[0x4000, 0xA5000)` for the V20
  package and `[0x4000, 0x9F000)` for the V22 and V23 packages. The end comes from the package and can never be above `0xFF000`. The head `[0, 0x4000)` (header,
  second-stage boot loader, chip key) and everything above the image (Bluetooth trims, user data) are never touched.
- Only a fixed list of loader commands can be sent. Chip erase (`FB02`) and key burn (`FC12`) are not on it. In a read-only
  run the erase and write commands are not on it either.
- It stops without writing when the device is not `WL82 UBOOT1.00`, the chip key is not `0x980F`, the flash is not 1 MiB, or
  the pedal's head differs from the image's head (a package for another layout: the V20 file on a pedal that ran V22
  or V23, or the other way round).
- The backup is complete on disk before the first erase.
- After a restore, do not reinstall the Bluetooth test image until the cause of the crash loop is understood: the loop came
  from that image.

## Other symptoms

| Symptom | Cause and next step |
| --- | --- |
| `libusb not found` | `brew install libusb` (or set `LIBUSB_PATH`). |
| Windows: `only an administrator` | Open the Command Prompt as administrator and run `RESCUE.bat` there. |
| Windows: `Python 3 is not installed` | Install it from python.org (tick "Add python.exe to PATH"). If typing `python` opens the Microsoft Store, install from python.org instead; `RESCUE.bat` uses its `py` launcher. |
| `cannot take the interface from macOS (LIBUSB_ERROR_ACCESS)` | Run the command with `sudo`. |
| Waits forever | The pedal is not in UBOOT right now. It is there about 44 s out of every 70 s while it loops; check `ioreg -p IOUSB` for `WL80UBOOT1.00` (Windows: a new disk drive in Device Manager), a data cable and a direct port. |
| `REFUSED` | A safety check stopped it; the message names which. Nothing was written. `the flash head [0, 0x4000) is not the image's head` means the file of the other path: see the quick start, step 1. |
| `gave up after N tries` | The pedal kept leaving UBOOT before the run could finish. Rerun: it resumes. |
| Still nothing | The SD-card recovery in `flash/` (fm1buddy on an ESP32-S3) is the other route. |

## Credits

The USB boot protocol is documented by [kagaimiq/jl-uboot-tool](https://github.com/kagaimiq/jl-uboot-tool) (MIT) and
[konsumer/fm1buddy](https://github.com/konsumer/fm1buddy) (GPL-3.0); `tools/uboot_rescue.py` is a new implementation of the
same commands for macOS and Windows. Tests: `make rescue-check` runs it against a simulated pedal (`tests/uboot_sim.py`), with no hardware.
`tests/test_rescue_kit.py` runs the kit's own files against the same simulated pedal on a V20, a V22 and a V23 flash head.
