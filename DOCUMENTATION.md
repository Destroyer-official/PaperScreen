# PaperScreen: Architecture & Technical Reference Manual

This document provides a comprehensive technical overview of PaperScreen's internals, Windows API bindings, color science formulas, and process architecture.

---

## 1. System Architecture

PaperScreen is structured into clear separation-of-concerns layers, maintaining a strict zero-dependency promise (pure Python standard library + ctypes):

```
paperscreen/
├── __init__.py             Package metadata
├── __main__.py             CLI / Executable entry point
├── cli.py                  Argparse command router
├── config.py               JSON configuration manager (atomic I/O)
├── signals.py              Cross-process journal manager (atomic I/O)
├── logger.py               Lightweight rotating file logger (< 2 MB)
├── winlib.py               Raw Win32 ctypes bindings (Magnification, DXVA2, GDI, User32, CCD)
├── color_matrix.py         Pure-Python 5x5 color matrix math & colorimetry
├── paper_engine.py         High-level engine orchestration (apply, release, status)
├── backlight.py           Dual hardware backlight sync (DDC/CI + WMI)
├── cleartype.py            SystemParametersInfo font smoothing control
├── breaks.py               20-20-20 micro-break watchdog with idle tracking
├── toasts.py               Windows notification dispatcher (Balloon / WinRT)
├── tray.py                 Zero-dependency Win32 system tray & context menu
├── settings_gui.py         Native Tkinter display preferences & calibration GUI
├── spawn.py                Detached console-free process launcher
├── daemon.py               Resident background daemon holding the magnification effect
└── autostart_helper.py     Login launcher for Windows HKCU Run entry
```

---

## 2. Windows Magnification API Mechanics

### Fullscreen Color Transforms
The Desktop Window Manager (DWM) in Windows 8, 10, and 11 exposes hardware-accelerated color transformations via `Magnification.dll`:
- `MagInitialize()`: Initializes the magnification runtime. Must be called before setting effects.
- `MagSetFullscreenColorEffect(pEffect)`: Applies a 5x5 transformation matrix to the entire virtual desktop.
- `MagGetFullscreenColorEffect(pEffect)`: Queries the currently active color matrix.
- `MagUninitialize()`: Closes the magnification context.

### Session-Bound Lifecycle
A fundamental architectural trait of `MagSetFullscreenColorEffect` is that the color transform is **session-bound to the applying process**:
1. When `paperscreen on` is executed, it spawns a detached resident daemon process (`paperscreen.daemon`).
2. The daemon applies the matrix and holds the magnification session open.
3. If the daemon process is gracefully stopped (`paperscreen off`) or forcefully killed (`taskkill /F`), DWM **automatically reverts the desktop color matrix back to neutral identity**.
4. **Result**: A crash or abrupt termination can never leave the user's screen permanently stuck in a tinted state.

---

## 3. Color Science & Math Pipeline

### 5x5 Matrix Convention
In the Windows Magnification API (`MAGCOLOREFFECT`), pixel transformations follow the row-vector convention:

$$\mathbf{P}_{\text{out}} = \begin{pmatrix} r & g & b & a & 1 \end{pmatrix} \cdot \mathbf{M}$$

- Rows 0, 1, 2 index the input Red, Green, and Blue channels.
- Columns 0, 1, 2 index the output Red, Green, and Blue channels.
- Row 4 represents the **translation row** (constant per-channel offsets).
- Row 3 and Column 3 represent the Alpha channel (identity: `M[3][3] = 1.0`).

### Tone Mapping & Paper Simulation Formulas
For each output channel $c \in \{R, G, B\}$, with white-point chromaticity gains $g_c$ derived from Correlated Color Temperature ($K$):

1. **Luminance Calculation (Rec. 709 weights)**:
   $$L = 0.34 \cdot r + 0.36 \cdot g + 0.30 \cdot b$$

2. **Desaturation towards Luma**:
   $$x_c = (1 - d) \cdot \text{in}_c + d \cdot L$$
   where $d \in [0.0, 1.0]$ is the desaturation factor.

3. **Contrast Scaling around Mid-Gray**:
   $$y_c = k \cdot x_c + (1 - k) \cdot 0.5$$
   where $k$ is the contrast multiplier.

4. **Paper Tone Mapping (Black Floor & White Ceiling)**:
   $$\text{out}_c = g_c \cdot \lambda \cdot \left[ \text{floor} + (\text{ceiling} - \text{floor}) \cdot y_c \right]$$
   where:
   - $\text{floor} \approx 0.10$ lifts pure digital black (`#000000`) to soft charcoal (`#1E1C1A`).
   - $\text{ceiling} \approx 0.92$ compresses pure digital white (`#FFFFFF`) to diffuse parchment (`#F3EBDD`).
   - $\lambda \in [0.05, 1.0]$ scales overall luminance without altering display backlight PWM frequency.

### Inverted Paper Matrix
For dark-mode paper rendering, the transform inverts input values while maintaining paper tone bounds:
- Input pure black $(0, 0, 0)$ maps to warm parchment text ($\approx 0.90, 0.78, 0.68$).
- Input pure white $(1, 1, 1)$ maps to charcoal background ($\approx 0.10, 0.09, 0.08$).

---

## 4. Hardware Backlight Control Architecture

### Dual-Engine Synchronization
Different display hardware requires distinct control channels:

```
[Backlight Request]
       │
       ▼
[External Monitor?] ─── YES ───► [dxva2.dll: DDC/CI over HDMI/DP]
       │
       NO (Internal Laptop Panel)
       ▼
[WMI: root\wmi: WmiMonitorBrightnessMethods]
```

1. **External Monitors (DDC/CI via `dxva2.dll`)**:
   - Uses `GetNumberOfPhysicalMonitorsFromHMONITOR` and `GetPhysicalMonitorsFromHMONITOR`.
   - Sends VESA MCCS brightness opcodes via `GetMonitorBrightness` and `SetMonitorBrightness`.
   - Remembers previous brightness in `state.json` keyed by unique compound ID (`name #index`) to prevent collisions across identical multi-monitor setups.
2. **Internal Laptop Panels (WMI)**:
   - Queries `root\wmi: WmiMonitorBrightness.CurrentBrightness`.
   - Sets brightness via `root\wmi: WmiMonitorBrightnessMethods.WmiSetBrightness`.

---

## 5. Desktop Integration & Reliability

### Win32 System Tray (`tray.py`)
- Creates a hidden message-only window (`HWND_MESSAGE`).
- Adds a tray icon via `Shell_NotifyIconW` with flags `NIF_ICON | NIF_MESSAGE | NIF_TIP`.
- Handles `WM_RBUTTONUP` by setting foreground focus (`SetForegroundWindow`) and displaying a Win32 popup menu via `TrackPopupMenuEx`.

### Windows Explorer Recovery (`TaskbarCreated`)
When `explorer.exe` restarts, all notification tray icons are lost. PaperScreen registers the system-wide message:
```python
self.taskbar_created_msg = user32.RegisterWindowMessageW("TaskbarCreated")
```
When intercepted in `_wnd_proc`, PaperScreen immediately re-registers the tray icon (`NIM_ADD`), ensuring the icon never disappears permanently.

### Sleep / Wake Synchronization (`WM_POWERBROADCAST`)
When the operating system resumes from sleep or hibernation (`PBT_APMRESUMEAUTOMATIC`), DWM presentation buffers and graphics drivers may reset. PaperScreen intercepts the power broadcast and re-applies the active color matrix and backlight levels.

### OS-Level Single Instance Mutex
To prevent multiple background daemons from running concurrently, PaperScreen creates a Windows Named Mutex on launch:
```python
h_mutex = kernel32.CreateMutexW(None, True, "Local\\PaperScreenDaemonSingleInstanceMutex")
if kernel32.GetLastError() == 183: # ERROR_ALREADY_EXISTS
    return 0 # Exit gracefully
```

### Atomic Configuration Transactions
Both `config.json` and `state.json` write to temporary files (`.tmp`) before calling `os.replace()`. On Windows, `os.replace()` invokes `MoveFileExW` with `MOVEFILE_REPLACE_EXISTING`, guaranteeing atomic replacement that prevents file corruption during abrupt shutdowns.

---

## 6. Configuration Schema Reference

Configuration is stored in `%APPDATA%\PaperScreen\config.json`:

```json
{
  "preset": "paper",
  "kelvin": 4600,
  "desaturation": 0.35,
  "black_floor": 0.10,
  "white_ceiling": 0.92,
  "contrast": 1.0,
  "backlight_day": 60,
  "backlight_night": 30,
  "night_start_hour": 19,
  "night_end_hour": 7,
  "grayscale_smoothing": false,
  "restore_backlight_on_exit": true,
  "breaks_enabled": true,
  "break_interval_minutes": 20,
  "break_duration_seconds": 20,
  "smooth_transition_ms": 1000,
  "hotkey_toggle": true,
  "night_dim_matrix": false,
  "auto_pause_fullscreen": false,
  "excluded_apps": ["photoshop.exe", "figma.exe"]
}
```
