# PaperScreen 📜

> **Zero Third-Party Dependency Paper Display & Circadian Engine for Windows**  
> *Transform your standard monitor into a matte, low-glare paper surface to help mitigate digital eye strain during coding, reading, and deep work.*

[![CI](https://github.com/Destroyer-official/PaperScreen/actions/workflows/ci.yml/badge.svg)](https://github.com/Destroyer-official/PaperScreen/actions)
[![Release](https://img.shields.io/github/v/release/Destroyer-official/PaperScreen?include_prereleases&color=blue)](https://github.com/Destroyer-official/PaperScreen/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10+-brightgreen.svg)](https://www.python.org/)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows%208%20%7C%2010%20%7C%2011-0078D6.svg)](https://www.microsoft.com/windows)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0%20runtime%20python%20pkgs-success.svg)](#zero-dependencies)

---

## 📖 Overview

Standard computer monitors are emissive light sources blasting up to 400 cd/m² of unbuffered `#FFFFFF` light against pitch `#000000` blacks. This high contrast ratio and saturated RGB primaries can contribute to pupillary fatigue, reduced blink rates, and ocular dryness.

**PaperScreen** transforms your Windows desktop appearance by combining **four ergonomic interventions**:

1. **OS-Wide 5x5 Color Matrix Engine** (Windows Magnification API): Algorithmic tone mapping that lifts pure digital black to charcoal (`#1E1C1A`), compresses white to unbleached parchment (`#F3EBDD`), and attenuates primary color saturation.
2. **Dual-Channel Hardware Backlight Sync**: Real hardware brightness control (0–100) mapped to device physical ranges via DDC/CI over HDMI/DP for external monitors + WMI for internal laptop displays.
3. **20-20-20 Micro-Break Watchdog**: Idle-aware, non-intrusive break reminders (every 20 minutes, look 20 feet away for 20 seconds).
4. **Grayscale Font Smoothing**: Switches ClearType subpixel rendering to grayscale with a system-wide `WM_SETTINGCHANGE` broadcast, reducing chromatic color fringing on tinted text.

> 🩺 **Medical & Scientific Honesty**: Blue-light software filters do **not** cure eye strain ([Cochrane Systematic Review 2023, 17 RCTs](https://pubmed.ncbi.nlm.nih.gov/37593770/)). Eye strain is primarily caused by **reduced blink frequency, incomplete blinks, ocular dryness, and excessive luminance mismatch** ([TFOS Lifestyle Report 2023, PMID 37062428](https://pubmed.ncbi.nlm.nih.gov/37062428/); [clinical incomplete blink analysis 2024–2026, PMID 39491645](https://pubmed.ncbi.nlm.nih.gov/39491645/)). PaperScreen's approach focuses on **ambient luminance matching, structured micro-breaks, and glare reduction**. Warm color transforms serve as software-level approximations for **circadian melatonin hygiene** (CIE S 026:2018), bounded by the physical colorimetry and panel characteristics of your display.

---

## 🎨 Color Presets

*Note: Target CCT values are approximate software color-transform models, not calibrated physical display emissions.*

| Preset | Target CCT | Desaturation | Black Floor | White Ceiling | Best For |
|---|---|---|---|---|---|
| `paper` *(default)* | ~4400 K | 65% | 0.10 | 0.90 | Daylight coding, web reading, authentic matte print look |
| `sepia` | ~3600 K | 70% | 0.12 | 0.86 | Antique book aesthetic & evening reading |
| `warm_reading` | ~3000 K | 55% | 0.12 | 0.84 | Long PDF & textbook study under dim ambient lighting |
| `eink` | 6500 K (Neutral) | 100% | 0.08 | 0.92 | Strictly achromatic neutral grayscale monochrome (R=G=B) |
| `eink_warm` | ~4000 K | 100% | 0.08 | 0.90 | Warm monochrome paper emulation |
| `amber_candle` | ~2200 K | 75% | 0.08 | 0.82 | Deep amber reading with heavy blue-channel attenuation |
| `nightpaper` | ~3200 K | 60% | 0.07 | 0.72 | Late night deep work (software-level matrix luminance reduction) |
| `inverted_paper` | ~4400 K | 20% | 0.10 | 0.90 | Dark Paper: contrast inversion preserving syntax distinction |
| `custom` | Dynamic | Dynamic | Dynamic | Dynamic | Real-time live slider calibration via GUI (`--gui`) |
| `auto` | Dynamic | Dynamic | Dynamic | Dynamic | Automated circadian day ↔ night sync (standard hours or NOAA solar) |

---

## 🚀 Installation & Getting Started

### Option A: Standalone Executable (No Python Required)
1. Download `PaperScreen.exe` from the [Latest Release](https://github.com/Destroyer-official/PaperScreen/releases).
2. Double-click `PaperScreen.exe` or run it from PowerShell:
   ```powershell
   .\PaperScreen.exe on
   ```

### Option B: Install via pip
```powershell
pip install git+https://github.com/Destroyer-official/PaperScreen.git
paperscreen on
```

### Option C: Run from Source (Zero Dependencies)
```powershell
git clone https://github.com/Destroyer-official/PaperScreen.git
cd PaperScreen
python -m paperscreen on
```

---

## 🖥️ Usage & Desktop Integration

### 1. Global Hotkeys
- **`Ctrl + Alt + P`**: Toggle Paper Mode instantly on / off.
- **`Ctrl + Alt + N`**: Cycle through paper presets on the fly (`Paper` ➔ `Sepia` ➔ `Warm Reading` ➔ `E-Ink` ➔ `Kindle Warm` ➔ `Amber Candle` ➔ `Night Paper` ➔ `Smart Dark Paper`).

### 2. Native System Tray Icon
When active, PaperScreen sits quietly in your taskbar notification area with a custom parchment paper icon:
- **Left Click**: Open context menu
- **Double Click**: Toggle Paper Mode on/off
- **Right Click**: 
  - Switch Presets (`Paper`, `Sepia`, `Amber Candle`, `Smart Dark Paper`, etc.)
  - Set Hardware Backlight (`25%`, `40%`, `60%`, `75%`, `100%`)
  - 20-20-20 Break Timer (Toggle, "Take Break Now")
  - Toggle Grayscale Font Smoothing
  - Open Visual Preferences & Calibration Dialog
  - Toggle "Start with Windows"
  - View Live Diagnostics (`Doctor`)

### 3. Visual Preferences & Calibration GUI
Fine-tune color temperature, desaturation, contrast, and black/white luminance limits with zero external dependencies:
```powershell
python -m paperscreen settings
# Or
python -m paperscreen config --gui
```

### 4. CLI Command Reference

```powershell
# Core Controls
python -m paperscreen on                      # Activate paper mode (spawns daemon + tray)
python -m paperscreen on --preset amber_candle # Activate with Daylight 2200K amber preset
python -m paperscreen cycle                   # Cycle to next paper preset (or Ctrl+Alt+N)
python -m paperscreen off                     # Restore normal display and exit
python -m paperscreen toggle                  # Instant one-touch toggle (script / macro friendly)
python -m paperscreen status                  # Show current active engine status

# NOAA Astronomical Solar Circadian Sync
python -m paperscreen config --set solar_circadian=true # Auto-switch using true solar sunrise/sunset

# Hardware & Diagnostics
python -m paperscreen doctor                  # Full system diagnostic (APIs, DDC, HDR)
python -m paperscreen monitors                # List connected monitors and brightness
python -m paperscreen matrix --preset paper   # Inspect 5x5 color transform matrix
python -m paperscreen log                     # View recent diagnostic log entries

# Break Reminders, GUI & Automation
python -m paperscreen settings                # Launch visual calibration GUI
python -m paperscreen break --detached        # Run 20-20-20 break timer in background
python -m paperscreen autostart --enable      # Automatically start PaperScreen at login
python -m paperscreen config --set kelvin=4800 --set backlight_day=55
```

---

## 🛡️ Reliability & State Recovery
 
- **DWM Session-Bound Magnification**: The Windows Magnification API color effect lives exclusively within the Desktop Window Manager (DWM) session. If the daemon process exits or is terminated, DWM automatically reverts the color transform to identity.
- **Session Lock & Unlock Isolation**: Registers for `WM_WTSSESSION_CHANGE` via Terminal Services (`wtsapi32.dll`) to reset transforms to neutral identity upon workstation lock (`Win+L`), preventing matrix leakage on the secure desktop or Windows Hello camera, and automatically restores your paper preset upon unlock.
- **Transactional Backlight & Smoothing Journal**: DDC/WMI hardware brightness and ClearType smoothing settings are stored in an on-disk journal synchronized with Windows Named Mutexes. If an operation is interrupted or a monitor fails to respond, original values are preserved for retry rather than discarded.
- **One-Touch Repair Command**: Run `paperscreen doctor --repair` at any time to reset the desktop matrix to neutral identity, reapply any unrestored hardware backlight levels, and restore standard font smoothing.
- **Explorer Restart Recovery**: Listens for the `TaskbarCreated` broadcast message to automatically restore the notification icon if `explorer.exe` restarts.
- **Sleep & Wake Synchronization**: Listens for `WM_POWERBROADCAST` to smoothly reapply transforms and backlight levels when your PC wakes from sleep or hibernation.
- **Auto-Pause for Fullscreen Apps**: Automatically pauses paper mode when a full-screen game, video, or color-sensitive program (e.g. `photoshop.exe`, `figma.exe`) is focused.
- **OS-Level Mutexes**: Uses Windows Named Mutexes (`Local\PaperScreenDaemonSingleInstanceMutex` and `Local\PaperScreenBreaksMutex`) to prevent duplicate instances with zero TOCTOU race conditions.

---

## 🧪 Testing

PaperScreen includes a comprehensive test suite covering color math, civil circadian rules, Win32 memory alignments, transactional recovery, and failure-path resilience:

```powershell
pytest
```
*Current test suite: 62 automated tests, 100% pass rate.*

---

## 📚 Technical Documentation

For deep technical details on the Magnification API, DDC/CI I2C protocol, WMI COM methods, and tone-mapping math, see [DOCUMENTATION.md](DOCUMENTATION.md) and [PLAN.md](PLAN.md).

---

## ⚖️ License

Distributed under the [MIT License](LICENSE). Copyright (c) 2026 PaperScreen Contributors.
