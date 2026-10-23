# PaperScreen

A lightweight, zero-dependency display comfort and paper-reading engine for Windows.

[![CI](https://github.com/Destroyer-official/PaperScreen/actions/workflows/ci.yml/badge.svg)](https://github.com/Destroyer-official/PaperScreen/actions)
[![Release](https://img.shields.io/github/v/release/Destroyer-official/PaperScreen?include_prereleases&color=blue)](https://github.com/Destroyer-official/PaperScreen/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-brightgreen.svg)](https://www.python.org/)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6.svg)](https://www.microsoft.com/windows)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0%20runtime%20pkgs-success.svg)](#zero-dependencies)

---

## Overview

Emissive computer displays present high luminance contrast and saturated primaries that can lead to ocular dryness, reduced blink rates, and fatigue during extended reading and coding sessions.

**PaperScreen** adjusts your Windows desktop appearance through four integrated mechanisms:

1. **OS-Wide 5x5 Color Matrix Engine**: Tone-maps the entire virtual desktop using the Windows Magnification API (`MagSetFullscreenColorEffect`), lifting black to soft charcoal (`#15120F`), compressing peak white to warm parchment (`#EAC5A8`), and desaturating primaries.
2. **Dual-Channel Hardware Backlight Control**: Directly adjusts monitor backlight levels (0–100) via VESA DDC/CI over HDMI/DisplayPort and WMI for internal laptop panels. Includes no-op skipping to prevent monitor EEPROM wear.
3. **Session-Bound Grayscale Font Smoothing**: Temporarily switches ClearType subpixel rendering to standard grayscale via `SystemParametersInfoW` to eliminate colored fringing on tinted text, broadcasting `WM_SETTINGCHANGE` without altering permanent registry defaults.
4. **20-20-20 Eye Break Reminders**: An idle-aware background timer that prompts you every 20 minutes to look at an object 20 feet (~6 meters) away for 20 seconds.

> **Ergonomic & Scientific Context**: Peer-reviewed reviews (such as the 2023 Cochrane Systematic Review on blue-filtering spectacle lenses) confirm that blue filtration alone does not prevent digital eye strain. Clinical evidence (TFOS DEWS II, TFOS Lifestyle Report 2023) indicates that eye discomfort stems primarily from reduced blink frequency, ocular surface dryness, and luminance mismatches with ambient surroundings. PaperScreen addresses these factors through **ambient luminance matching, structured 20-20-20 micro-breaks, and glare attenuation**. Warm color transforms serve as software approximations for **circadian melatonin hygiene** (CIE S 026:2018).

---

## Color Presets

*Visual ergonomics literature generally favors positive polarity (dark text on a light background) for rapid reading and visual acuity. `inverted_paper` provides an alternative dark mode designed to invert background luminance while preserving syntax highlighting.*

| Preset | Target CCT | Desaturation | Black Floor | White Ceiling | Best For |
|---|---|---|---|---|---|
| `paper` *(default)* | ~4400 K | 65% | 0.10 | 0.90 | Daylight reading, technical writing, and general coding |
| `sepia` | ~3600 K | 70% | 0.12 | 0.86 | Warm document study and late afternoon work |
| `warm_reading` | ~3000 K | 55% | 0.12 | 0.84 | Extended PDF reading in dim ambient lighting |
| `eink` | 6500 K | 100% | 0.08 | 0.92 | Achromatic monochrome grayscale ($R = G = B$) |
| `eink_warm` | ~4000 K | 100% | 0.08 | 0.90 | Warm monochrome paperwhite simulation |
| `amber_candle` | ~2200 K | 75% | 0.08 | 0.82 | Deep evening amber with strong digital blue attenuation (~75–90%) |
| `nightpaper` | ~3200 K | 60% | 0.07 | 0.72 | Late-night work with software-level matrix dimming |
| `inverted_paper` | ~4400 K | 20% | 0.10 | 0.90 | Dark paper mode preserving relative chromatic syntax contrast |
| `custom` | Configurable | Configurable | Configurable | Configurable | Tuned via the visual calibration GUI (`--gui`) |
| `auto` | Dynamic | Dynamic | Dynamic | Dynamic | Automated day/night switching (clock-based or NOAA solar) |

---

## Installation

### Option A: Standalone Executable (Recommended, No Python Required)
1. Download `PaperScreen.exe` from the [Latest Release](https://github.com/Destroyer-official/PaperScreen/releases).
2. Run directly from PowerShell or Command Prompt:
   ```powershell
   .\PaperScreen.exe on
   ```

### Option B: Install via pip
```powershell
pip install git+https://github.com/Destroyer-official/PaperScreen.git
paperscreen on
```

### Option C: Run from Source (Zero External Dependencies)
```powershell
git clone https://github.com/Destroyer-official/PaperScreen.git
cd PaperScreen
python -m paperscreen on
```

---

## Desktop Integration & Controls

### Global Hotkeys
- **`Ctrl + Alt + P`**: Toggle Paper Mode on or off instantly.
- **`Ctrl + Alt + N`**: Cycle through presets (`Paper` &rarr; `Sepia` &rarr; `Warm Reading` &rarr; `E-Ink` &rarr; `Kindle Warm` &rarr; `Amber Candle` &rarr; `Night Paper` &rarr; `Inverted Paper`).

### System Tray Interface
When active, PaperScreen runs in the system tray with a custom parchment paper icon:
- **Left Click**: Open the context menu.
- **Double Click**: Toggle paper mode on/off.
- **Right Click**: Quick access to presets, backlight levels (`25%` to `100%`), 20-20-20 breaks, font smoothing toggle, and settings.

### Visual Preferences & Calibration GUI
Launch the built-in Tkinter preferences dialog to calibrate color temperature, desaturation, contrast, and black/white floors with real-time preview:
```powershell
python -m paperscreen settings
# Or
python -m paperscreen config --gui
```

### CLI Command Reference

| Command | Description |
|---|---|
| `paperscreen on` | Activate paper mode (launches resident daemon with tray icon) |
| `paperscreen on --preset amber_candle` | Activate with a specific preset |
| `paperscreen off` | Revert display to neutral identity, restore hardware state, and exit |
| `paperscreen toggle` | Toggle paper mode on or off |
| `paperscreen cycle` | Advance to the next preset (equivalent to `Ctrl+Alt+N`) |
| `paperscreen status` | Report active engine state, PID, preset, and monitor brightness |
| `paperscreen monitors` | List detected monitors and current DDC/WMI brightness levels |
| `paperscreen doctor` | Run environment diagnostics (APIs, DDC, HDR, conflicts) |
| `paperscreen doctor --repair` | Reset display matrix to identity, restore unrestored backlight, and reset smoothing |
| `paperscreen break --detached` | Run the 20-20-20 break timer in the background |
| `paperscreen autostart --enable` | Register PaperScreen in HKCU Run to start at Windows login |
| `paperscreen config --set key=value` | Update persistent configuration options |

---

## Reliability & Architecture

- **Session-Bound Magnification Effect**: The Windows Magnification API color effect is maintained by the resident daemon process. When stopped or terminated, DWM automatically reverts the color transform back to neutral identity; manual repair (`paperscreen doctor --repair`) is provided as an emergency recovery path.
- **Workstation Lock Isolation**: Listens for `WM_WTSSESSION_CHANGE` via Terminal Services (`wtsapi32.dll`) to reset transforms to neutral identity upon workstation lock (`Win+L`), preventing matrix leakage on the secure desktop or Windows Hello camera, and restoring active presets upon unlock.
- **Re-Entrant Locking & Idle Waiting**: Transition routines use `threading.RLock()` and a monotonic generation counter to prevent deadlocks when tray events arrive during animations. The main loop uses `MsgWaitForMultipleObjects` to achieve **0% idle CPU utilization** while responding instantly to messages.
- **Fail-Closed Cross-Process State Journal**: Hardware brightness and font-smoothing states are recorded in `%APPDATA%\PaperScreen\state.json`, protected by a 64-bit cross-process Windows Named Mutex (`Local\PaperScreenJournalMutex`) that fails closed if acquisition is blocked or times out. Atomic file replacement (`os.replace` after `os.fsync`) prevents corruption.
- **Offline Solar Circadian Calculation**: When `solar_circadian = true`, approximate sunrise and sunset times are computed locally using NOAA solar geometry algorithms (Meeus/Spencer formulas) from your system timezone or configured coordinates, without external network requests.
- **Explorer Recovery**: Intercepts the `TaskbarCreated` broadcast message to restore the notification tray icon if `explorer.exe` restarts.

---

## Hardware Compatibility & Limitations

- **DDC/CI Support**: External monitor backlight control requires a display and cable (HDMI, DisplayPort, or USB-C DisplayPort Alternate Mode) that passes DDC/CI I2C signals. Certain USB hubs, docks, or display converters do not pass DDC signals; in those cases, PaperScreen logs a diagnostic warning and relies on matrix tone-mapping.
- **Multi-Monitor Global Effect**: Because `MagSetFullscreenColorEffect` operates at the DWM virtual-desktop composition level, the color transform applies across all connected monitors simultaneously.
- **Windows HDR**: On displays running Windows HDR (Advanced Color / scRGB 16-bit floating point), Magnification API 8-bit transformations may be tone-mapped by the GPU display driver. Run `paperscreen doctor` to verify your display configuration.

---

## Testing

PaperScreen includes an automated test suite verifying matrix mathematics, circadian schedules, Win32 memory alignments, transactional recovery, and failure-path resilience:

```powershell
pytest -v
```

*86 automated tests, 100% pass rate.*

---

## License

Distributed under the [MIT License](LICENSE). Copyright (c) 2026 PaperScreen Contributors.
