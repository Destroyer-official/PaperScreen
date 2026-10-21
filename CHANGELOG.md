# Changelog

All notable changes to **PaperScreen** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.4] - 2026-10-21

### Fixed
- **Daemon Transition Deadlock**: Converted `_transition_lock` to `threading.RLock()` and added generation tracking (`_transition_generation`) to prevent deadlocks when window messages or tray actions are dispatched mid-transition.
- **Hardware State Restoration on Toggle**: Fixed `on_hotkey()` and tray toggle so disabling paper mode restores backlight and ClearType font smoothing without terminating the background daemon, allowing seamless two-way toggling.
- **Hardware EEPROM Protection**: Skipped redundant no-op DDC/CI brightness writes and settling delays when the monitor is already at the target brightness level.
- **Zero-CPU Idle Waiting**: Replaced 25 Hz busy-polling loop with `MsgWaitForMultipleObjects(..., QS_ALLINPUT)`, eliminating idle CPU usage while waking with sub-millisecond latency.
- **State Journal Resilience**: Restricted `.corrupt` backup quarantine strictly to `ValueError` (corrupted JSON) rather than transient `OSError` (antivirus or file sharing locks). Added `flush()` and `os.fsync()` before atomic file replacement.
- **Configuration Crash Resilience**: Added `TypeError` handling and safe numeric conversions in `config._validate()` to prevent crashes when values are `None` or invalid types. Added `utc_offset_hours` to default schema.
- **Session-Only Font Smoothing**: Removed `SPIF_UPDATEINIFILE` from `winlib.set_font_smoothing_type()`, ensuring font smoothing modifications are session-bound and do not alter the user's permanent registry defaults.
- **Multi-Monitor Fullscreen Detection**: Integrated `SHQueryUserNotificationState` and per-monitor geometry checks via `MonitorFromWindow`.
- **Standalone Binary Packaging**: Added `--onefile` to `build_exe.py` and updated release workflow checksum generation for standard `sha256sum -c` compatibility.
- **Exported Symbols (`__all__`)**: Corrected module exports across `color_matrix.py`, `paper_engine.py`, and `daemon.py`.

### Changed
- **Documentation & Color Calibration**: Replaced outdated prototype values in documentation with measured matrix outputs (Paper white `#EAC5A8`, Paper black `#15120F`), clarified paper-balanced luma weights, and refined scientific context.
- **Test Suite**: Expanded test suite to 74 automated unit, reliability, and transactional tests with 100% pass rate.

---

## [1.0.3] - 2026-10-20

### Added
- **NOAA Astronomical Solar Circadian Engine (`circadian.py`)**: Computes exact astronomical sunrise and sunset times offline using Meeus solar geometry equations from system timezone or configured GPS coordinates.
- **Amber Candle Preset**: 2200 K warm amber reading profile with significant blue-channel attenuation.
- **Preset Cycling Hotkey**: Global hotkey `Ctrl+Alt+N` and CLI commands `paperscreen cycle` / `paperscreen next` to cycle presets on the fly.
- **Hue-Preserving Inverted Paper**: Dark paper mode with cross-channel coupling designed to invert background/foreground luminance while maintaining chromatic syntax distinction.

---

## [1.0.2] - 2026-10-20

### Fixed
- **Tkinter Python 3.14 Compatibility**: Used list-based tracking for slider labels to resolve unhashable type issues in Python 3.14 runtime.
- **Tray LOWORD Masking**: Masked `wparam & 0xFFFF` on `WM_COMMAND` dispatch to avoid integer overflow and missing attribute errors.

---

### Added
- **Visual Preferences & Calibration GUI (`settings_gui.py`)**: Zero-dependency Tkinter dialog for fine-tuning Kelvin, desaturation, black floor, white ceiling, contrast, circadian backlight targets, 20-20-20 breaks, and excluded apps with live instant preview.
- **CLI `toggle` Subcommand**: Added `paperscreen toggle` to flip the paper display state on or off instantly from scripts, Stream Decks, or hotkey daemons.
- **CLI `settings` Subcommand & Flag**: Added `paperscreen settings` and `paperscreen config --gui` to launch the preferences GUI directly.
- **Expanded Test Coverage**: Extended production unit test suite to 41 comprehensive tests with 100% pass rate.

### Fixed
- **Win32 GUID & LRESULT Types**: Implemented explicit ctypes `GUID` and pointer-sized `LRESULT` structures in `tray.py` to ensure reliable compatibility across all Python 3.10+ Windows runtimes.
- **System Tray Preferences Hook**: Added direct "Preferences & Settings..." menu item to the system tray context menu.

---

## [1.0.0] - 2026-10-19

### Added
- **Native Win32 System Tray**: Zero-dependency `Shell_NotifyIconW` desktop interface with live dynamic context menu (presets, backlight, breaks, autostart, diagnostics).
- **In-Memory High-DPI Tray Icon**: 16x16 parchment paper icon dynamically generated via GDI DIB sections without requiring external asset files.
- **Explorer Crash Recovery**: Intercepts Windows `TaskbarCreated` broadcast message to automatically recreate the tray icon if `explorer.exe` crashes or restarts.
- **Sleep & Power Event Synchronization**: Intercepts `WM_POWERBROADCAST` to reapply the color matrix and restore hardware backlight levels upon system wake from sleep/hibernate.
- **Topology Change Detection**: Intercepts `WM_DISPLAYCHANGE` to re-query display geometry and refresh active transforms.
- **Dual Hardware Backlight Control**: Added WMI (`WmiMonitorBrightnessMethods`) fallback for internal laptop displays alongside DDC/CI (`dxva2.dll`) for external monitors.
- **Advanced Color & HDR Awareness**: Implemented Windows CCD API integration (`QueryDisplayConfig` / `DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO`) to diagnose HDR/WCG states in `doctor`.
- **New Presets**:
  - `warm_reading` (3200 K, 40% desaturation, gentle contrast compression for PDFs and documentation).
  - `eink_warm` (4200 K amber monochrome Kindle Paperwhite warm light emulation).
  - `inverted_paper` (Dark charcoal `#1C1A18` background with warm parchment `#E8DFC8` text).
- **Auto-Pause for Fullscreen & Excluded Apps**: Detects when full-screen games, media players, or color-sensitive software (e.g. Photoshop, Figma) are active, temporarily reverting the screen to identity until unfocused.
- **Diagnostic Logging Subsystem**: Lightweight rotating file logger writing to `%APPDATA%\PaperScreen\paperscreen.log` with `paperscreen log` CLI command.
- **OS-Level Named Mutex**: Implemented `Local\PaperScreenDaemonSingleInstanceMutex` to prevent concurrent daemon collisions.
- **Atomic File Operations**: Safe `os.replace` transactions for `config.json` and `state.json` to prevent file corruption during unexpected power loss.
- **Standalone Binary Packaging**: Created PyInstaller build automation (`build_exe.py`) generating a 2.1 MB self-contained `PaperScreen.exe`.
- **Automated CI/CD Workflows**: Added GitHub Actions workflows for continuous integration and automated release asset publishing.
- **Production Test Suite**: Expanded unit tests to 37 test cases with 100% pass rate.

### Fixed
- **ClearType Font Smoothing Broadcast Bug**: Added `SPIF_UPDATEINIFILE | SPIF_SENDCHANGE` flags to `SystemParametersInfoW(SPI_SETFONTSMOOTHINGTYPE)` so top-level windows re-render font smoothing immediately without sign-out.
- **Timer Overflow Bug**: Replaced 32-bit `GetTickCount()` in idle calculations with 64-bit `GetTickCount64()` to prevent integer wrap-around on systems running past 49.7 days of uptime.
- **Multi-Monitor Identifier Collisions**: Unique compound keying (`name #index`) prevents identical monitor models from overwriting each other's remembered brightness states.
- **Relative Import Failure in Frozen Executable**: Enabled absolute import fallback in `paperscreen/__main__.py` to support PyInstaller frozen binaries.
