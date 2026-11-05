@echo off
REM Mailpit launcher wrapper (bypasses PowerShell ExecutionPolicy)
REM Usage: start-mailpit.cmd            -> start
REM        start-mailpit.cmd -Stop      -> stop
REM        start-mailpit.cmd -Status    -> status

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-mailpit.ps1" %*
