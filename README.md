# PaperScreen 📜

> **The Zero-Dependency Paper Display & Circadian Engine for Windows**  
> *Transform your standard monitor into a glare-free paper surface for fatigue-free coding, reading, and deep work.*

[![CI](https://github.com/Destroyer-official/PaperScreen/actions/workflows/ci.yml/badge.svg)](https://github.com/Destroyer-official/PaperScreen/actions)
[![Release](https://img.shields.io/github/v/release/Destroyer-official/PaperScreen?include_prereleases&color=blue)](https://github.com/Destroyer-official/PaperScreen/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10+-brightgreen.svg)](https://www.python.org/)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows%208%20%7C%2010%20%7C%2011-0078D6.svg)](https://www.microsoft.com/windows)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0-success.svg)](#zero-dependencies)

---

## 📖 Overview

Standard computer monitors are emissive light sources blasting up to 400 cd/m² of unbuffered `#FFFFFF` light against pitch `#000000` blacks. This extreme 1000:1+ contrast ratio and harsh RGB saturation induce pupillary stress, reduce blink rates, and exacerbate digital eye strain.

**PaperScreen** transforms your Windows desktop into an authentic paper surface by combining **four evidence-backed interventions**:

1. **OS-Wide 5x5 Color Matrix Engine** (Windows Magnification API): Lifts pure digital black to soft charcoal (`#1E1C1A`), compresses white to unbleached parchment (`#F3EBDD`), and attenuates harsh primary color saturation.
2. **Dual-Channel Hardware Backlight Sync**: Real hardware brightness control (0–100) via DDC/CI over HDMI/DP for external monitors + WMI for internal laptop displays.
3. **20-20-20 Micro-Break Watchdog**: Idle-aware, non-annoying reminders (every 20 minutes, look 20 feet away for 20 seconds).
4. **Grayscale Font Smoothing**: Switches ClearType subpixel rendering to grayscale with a system-wide `WM_SETTINGCHANGE` broadcast, eliminating chromatic color fringing on tinted text.

> 🩺 **Medical & Scientific Honesty**: Blue-light filters do **not** cure eye strain ([Cochrane Systematic Review 2023, 17 RCTs](https://pubmed.ncbi.nlm.nih.gov/37593770/)). Eye strain is primarily caused by **reduced blink frequency, dry ocular surface, and luminance mismatch** ([TFOS Lifestyle Report 2023, PMID 37062428](https://pubmed.ncbi.nlm.nih.gov/37062428/)). PaperScreen's efficacy lies in **luminance matching + micro-breaks + rendering quality** — warm tinting is scientifically positioned for **circadian melatonin hygiene** (CIE S 026:2018), not marketing hype.

---

## 🎨 Color Presets

| Preset | Target CCT | Desaturation | Black Floor | White Ceiling | Preview (Hex) | Best For |
|---|---|---|---|---|---|---|
| `paper` *(default)* | 4600 K | 35% | 0.10 | 0.92 | `#1E1C1A` → `#F3EBDD` | Daylight coding, web reading, office work |
| `sepia` | 3800 K | 55% | 0.13 | 0.88 | `#211E1A` → `#EDE0C8` | Evening reading, antique book aesthetic |
| `warm_reading` | 3200 K | 40% | 0.12 | 0.86 | `#1C1610` → `#DEC298` | Long PDF & textbook reading in dim light |
| `eink` | 6500 K | 100% | 0.08 | 0.94 | `#141414` → `#F0F0F0` | High-contrast neutral monochrome |
| `eink_warm` | 4200 K | 100% | 0.08 | 0.92 | `#1B1612` → `#E8D8C0` | Kindle Paperwhite warm light emulation |
| `nightpaper` | 3400 K | 45% | 0.07 | 0.72 | `#120E0A` → `#B89E78` | Late night work (PWM-safe matrix dimming) |
| `inverted_paper` | 4600 K | 35% | 0.10 | 0.90 | `#E8DFC8` on `#1C1A18` | Dark-mode paper (charcoal background) |
| `auto` | Dynamic | Dynamic | Dynamic | Dynamic | Day ↔ Night | Automated circadian day/night transition |

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

### 1. Global Hotkey
Press **`Ctrl + Alt + P`** anywhere on Windows to toggle Paper Mode instantly.

### 2. Native System Tray Icon
When active, PaperScreen sits quietly in your taskbar notification area with a custom parchment paper icon:
- **Left Click**: Open context menu
- **Double Click**: Toggle Paper Mode on/off
- **Right Click**: 
  - Switch Presets (`Paper`, `Sepia`, `Warm Reading`, `E-Ink`, etc.)
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
python -m paperscreen on --preset sepia       # Activate with a specific preset
python -m paperscreen off                     # Restore normal display and exit
python -m paperscreen toggle                  # Instant one-touch toggle (script / macro friendly)
python -m paperscreen status                  # Show current active engine status

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

## 🛡️ Production Reliability & Safety

- **Session-Bound Safety**: The Magnification API color effect lives exclusively within the Desktop Window Manager (DWM). If the process crashes or is forcefully killed, Windows **automatically clears the effect** — you can never be left stuck with a tinted screen.
- **Explorer Crash Recovery**: Listens for the `TaskbarCreated` broadcast message to automatically restore the notification icon if `explorer.exe` restarts.
- **Sleep & Wake Synchronization**: Listens for `WM_POWERBROADCAST` to smoothly reapply transforms and backlight levels when your PC wakes from sleep or hibernation.
- **Auto-Pause for Games & Fullscreen**: Automatically pauses paper mode when a full-screen game, video, or color-sensitive program (e.g. `photoshop.exe`, `figma.exe`) is focused.
- **Atomic State Transactions**: Uses `os.replace` (Win32 `MoveFileExW`) to ensure configuration and state journals are never corrupted by unexpected power loss.
- **OS-Level Mutex**: Uses Windows Named Mutex (`Local\PaperScreenDaemonSingleInstanceMutex`) to prevent accidental duplicate instances.

---

## 🧪 Testing

PaperScreen includes a comprehensive test suite covering matrix math, blackbody physics, Win32 memory alignments, and backlight logic:

```powershell
python -m unittest discover -s tests -v
```
*Current test suite: 41 tests, 100% pass rate.*

---

## 📚 Technical Documentation

For deep technical details on the Magnification API, DDC/CI I2C protocol, WMI COM methods, and tone-mapping math, see [DOCUMENTATION.md](DOCUMENTATION.md) and [PLAN.md](PLAN.md).

---

## ⚖️ License

Distributed under the [MIT License](LICENSE). Copyright (c) 2026 PaperScreen Contributors.
