@echo off
setlocal

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_cinematic_shell_interactive.ps1"
if errorlevel 1 (
  echo.
  echo SGFX cinematic shell launcher failed.
  pause
)
