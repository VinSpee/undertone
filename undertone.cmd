@echo off
REM SPDX-License-Identifier: GPL-3.0-only
REM undertone: rescue, install or check a BlackBox over its USB cable, on Windows (tools\undertone.py; the guide is
REM docs\RESCUE.md). With no command it shows its guided screens. Run it from a Command Prompt opened as
REM administrator: Windows lets only an administrator send the commands to the pedal, and undertone says so otherwise.
setlocal
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if defined PY goto run
echo undertone needs Python 3: install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
echo Nothing was sent to the pedal.
exit /b 1

:run
%PY% "%~dp0tools\undertone.py" %*
exit /b %errorlevel%
