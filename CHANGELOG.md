# Changelog

All notable changes to **PaperScreen** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.1] - 2026-10-19

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
