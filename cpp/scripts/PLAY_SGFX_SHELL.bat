@echo off
REM === One-click SGFX cinematic shell launcher (David) ===
REM Runs the already-built exe directly. No rebuild. Stays open until you close it.
REM Full experience: splash -> hero -> menu -> fly into the Seriengrafik planet -> 3D Car -> live BMW.
REM
REM Cars are picked inside the 3D Car UI. To start on a specific car, pass its export path:
REM   PLAY_SGFX_SHELL.bat "C:\3D Car git\digital-3d-car-models\cars\BMW\G70_EVO\export\exported.ramses"

setlocal enabledelayedexpansion
set "SCRIPT_DIR=%~dp0"
set "EXE_DIR=%SCRIPT_DIR%..\build\vs2022-ramses-28.16\Release"
set "BMW_CARS_ROOT=C:\3D Car git\digital-3d-car-models\cars\BMW"

if not exist "%EXE_DIR%\sgfx_cine_cinematic_shell.exe" (
  echo.
  echo ERROR: shell exe not found at:
  echo   %EXE_DIR%\sgfx_cine_cinematic_shell.exe
  echo.
  pause
  exit /b 1
)

if not exist "%BMW_CARS_ROOT%" (
  echo.
  echo NOTE: BMW cars root was not found:
  echo   %BMW_CARS_ROOT%
  echo The shell will run ^(planet + menu^) but the 3D Car zone will be empty.
  echo.
) else (
  echo BMW cars root: %BMW_CARS_ROOT%
)

if "%~1"=="" (
  echo Initial car: picker default ^(registry order^)
  pushd "%EXE_DIR%"
  echo.
  echo Launching SGFX cinematic shell... close the window or press Esc/Exit to quit.
  echo  Controls: arrows/WASD + Enter to navigate the menu.
  echo  Fly into "Modules / Pipelines" for the Seriengrafik planet, then the 3D Car node for the live car.
  echo.
  sgfx_cine_cinematic_shell.exe --interactive --hub-planet --hub-nodes --fusion-cars-root "%BMW_CARS_ROOT%" --asset-root "assets" --font-root "assets\fonts"
) else (
  echo Initial car export: %~1
  pushd "%EXE_DIR%"
  echo.
  echo Launching SGFX cinematic shell... close the window or press Esc/Exit to quit.
  echo  Controls: arrows/WASD + Enter to navigate the menu.
  echo  Fly into "Modules / Pipelines" for the Seriengrafik planet, then the 3D Car node for the live car.
  echo.
  sgfx_cine_cinematic_shell.exe --interactive --hub-planet --hub-nodes --fusion-cars-root "%BMW_CARS_ROOT%" --fusion-scene-file "%~1" --asset-root "assets" --font-root "assets\fonts"
)
set "RC=%ERRORLEVEL%"
popd

if not "%RC%"=="0" (
  echo.
  echo Shell exited with code %RC%.
  pause
)
endlocal
