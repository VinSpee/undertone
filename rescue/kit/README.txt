OPENPOCKET RESCUE KIT FOR THE M-VAVE BLACKBOX
=============================================
Kit version {{VERSION}}

What this is
------------
The tool that restores the official firmware of a BlackBox that shows a black
screen or restarts in a loop, over its USB cable, with no extra hardware.
The guide, with what each step shows on screen:
https://github.com/VinSpee/undertone/blob/main/docs/RESCUE.md

The first run only reads the pedal and saves a backup. Nothing is written
until you add --write. A wrong firmware file is refused before anything is
written.

You need Python 3 (https://www.python.org/downloads/, tick "Add python.exe to
PATH"). On a Mac you also need libusb: brew install libusb. The first run
downloads one small loader file, so it needs internet once.

The firmware file
-----------------
The tool writes M-VAVE's official firmware back, so it needs M-VAVE's file.
Look in the firmware folder. If it holds no .fwsc file, this kit came without
M-VAVE's firmware: firmware\README.txt says where to get the file and what to
call it.

Which path is yours
-------------------
Path A. The pedal never ran M-VAVE V22 or V23 (it had V16, V17 or V20).
        File: firmware\BlackBox_020.fwsc
Path B. The pedal ran M-VAVE V22 or V23 at any time, or you are not sure.
        File: firmware\BlackBox_023.fwsc  (BlackBox_022.fwsc works the same)
Path C. Both files are refused. Stop. Do not try other files. Keep the backup.

You do not have to choose: put the files you have in the firmware folder.
undertone reads the pedal first and uses the file that matches it. If none
matches, it says which file the pedal needs, or that you are on path C.

The command
-----------
Unplug the pedal, type the line, and plug the pedal in when it says it is
waiting (or, in its screens, when it says it is looking for your pedal).

Mac or Linux (Terminal, in this folder; Linux has not been tested):
  ./undertone
It asks for your computer password (nothing shows while you type).

Windows (Command Prompt opened as administrator, in this folder; not
PowerShell):
  undertone
If Windows offers to format a drive, click Cancel. Never click Format.

Choose "fix a pedal that will not start". First it checks the pedal and saves
a backup; nothing is written. Then it asks before it writes anything. When it
is done, unplug the cable, switch the pedal off, wait 5 seconds and switch it
on. If a run stops in the middle, run it again: it continues.

The same without the screens, for a script or if you prefer to type:
  ./undertone rescue          (Windows: undertone rescue)
It shows the tool's own lines and asks you to type yes before the restore.
"./undertone check" only reads the pedal and saves a backup.

Under the hood, undertone runs tools/uboot_rescue.py, the same tool as
before. These lines still work and do the same as undertone rescue:
  Mac:      sudo python3 tools/uboot_rescue.py --package firmware/BlackBox_023.fwsc
            sudo python3 tools/uboot_rescue.py --write --package firmware/BlackBox_023.fwsc
  Windows:  RESCUE.bat --package firmware\BlackBox_023.fwsc
            RESCUE.bat --write --package firmware\BlackBox_023.fwsc

After path B, DO NOT INSTALL OPENPOCKET ON THE PEDAL FROM THE INSTALLER PAGE.
An installer that does not know the V22/V23 layout writes over the end of that
boot loader, and the pedal goes dark again. On such a pedal Gamut is installed
with undertone install from the Undertone repository instead (it runs
tools/uboot_install.py, which never writes the boot loader): see the guide's
section "Gamut on a BlackBox with V22 or V23". This kit holds that tool for
the way back to M-VAVE's firmware (./undertone install --official
firmware/BlackBox_023.fwsc), but not Gamut's own file.

Other files here
----------------
undertone, undertone.cmd, tools/undertone.py, tools/undertone_screens.py
    The command above, for Mac and Linux, and for Windows. It runs the tools
    below and changes nothing in what they do to a pedal.
tools/uboot_rescue.py, RESCUE.bat
    The rescue tool, and its Windows launcher.
tools/uboot_install.py, tools/pd40_install.py
    The tool behind undertone install (Mac only), and the checks it uses.
fingerprint.bat  (Mac: python3 tools/head_fingerprint.py)
    Reads your newest backup and says which firmware the pedal had. With a
    file name it reads that file: a backup, or a firmware file (.fwsc).
extract-flash.bat firmware\BlackBox_023.fwsc
    (Mac: python3 tools/extract_flash.py firmware/BlackBox_023.fwsc)
    Takes flash.bin out of a package, for use with --image in place of
    --package. You only need this if --package reports an error.
tools/pd40_recovery.py  (Mac: python3 tools/pd40_recovery.py)
    For a pedal on M-VAVE's V22 or V23 that shows RECOVERY (hold HOME, the
    right footswitch and the knob's PUSH at power-on). Reads what the pedal's
    recovery mode reports and writes nothing. Then it watches the USB
    devices for 60 seconds: if the pedal leaves the recovery mode, it shows
    when, and what the pedal starts next. Run it at once after RECOVERY
    appears: the pedal restarts by itself about 4 seconds after power-on.
    With --leave --accept-inferred --accept-control-reply it sends the one
    command that took the one real pedal tried to the USB boot state, where
    tools/uboot_rescue.py works; start that tool first, in a second window,
    because that state lasts only seconds. See the guide's section "A pedal
    on M-VAVE's V22 or V23" first.
SHA256SUMS.txt
    The SHA-256 of every file in this kit. Check one on Windows with
    certutil -hashfile RESCUE.bat SHA256
    and all of them on a Mac with  shasum -a 256 -c SHA256SUMS.txt

Backups are saved in the OpenPocket-rescue folder of your user (home) folder.

Status
------
The tool has restored one real pedal on path A, from a Mac. On path B it has
put the official V23 app back on one real pedal whose V23 boot loader was
intact, reached through the recovery mode's leave, from a Mac. A pedal that
went dark after an install for the old layout was tested against a simulated
pedal with M-VAVE's real V22 and V23 files, and it matches one community
report of a real pedal restored this way; the OpenPocket team has not run
that case on a real pedal, and has not run the Windows launcher on a real
pedal.

Credits and licences
--------------------
BlackBox_020.fwsc, BlackBox_022.fwsc and BlackBox_023.fwsc are the official
BlackBox firmware V20, V22 and V23, published by M-VAVE. They remain M-VAVE's
property. OpenPocket is not affiliated with M-VAVE or Donner.
RESCUE.bat and tools\ come from OpenPocket
(https://github.com/VinSpee/undertone, GPL-3.0-only; LICENSE.txt). The USB
boot protocol is documented by kagaimiq/jl-uboot-tool and konsumer/fm1buddy.
Flashing is at your own risk.
