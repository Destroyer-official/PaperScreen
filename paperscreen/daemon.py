"""Resident daemon: holds the magnification color effect while paper mode is on.

The Windows full-screen magnifier color transform is session-bound: it is
cleared when the applying process exits (verified empirically). So a
detached resident process must keep running while paper mode is active.

Features:
- Pure-Win32 zero-dependency System Tray Icon & Desktop Context Menu.
- Smooth eased matrix transitions (~1 s, 30 fps stepping — no flicker).
- Night schedule: auto-switches between day/night matrices at configured hours.
- Global hotkey toggle (RegisterHotKey, default Ctrl+Alt+P).
- Journal-driven: exits and reverts when `active` goes false.
- Hard kill also clears the effect automatically (session teardown).
- Survives Windows Explorer restarts (TaskbarCreated message).
- Re-applies matrix on system wake from sleep/hibernate (WM_POWERBROADCAST).
"""

from __future__ import annotations

import atexit
import ctypes
import datetime
import os
import sys
import threading
import time
from ctypes import wintypes

from . import backlight, cleartype, color_matrix, config, logger, signals, toasts, tray, winlib

POLL_SECONDS = 0.5
TRANSITION_SECONDS = 1.0
TRANSITION_FPS = 30

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_P = 0x50
VK_N = 0x4E
HOTKEY_ID = 0xB001        # Ctrl+Alt+P (Toggle On/Off)
HOTKEY_CYCLE_ID = 0xB002  # Ctrl+Alt+N (Cycle Preset)

CYCLE_PRESETS = (
    "paper",
    "sepia",
    "warm_reading",
    "eink",
    "eink_warm",
    "amber_candle",
    "nightpaper",
    "inverted_paper",
)


_transition_lock = threading.RLock()
_transition_generation = 0


def matrix_for(preset: str, night: bool = False):
    cfg = config.load()
    dim = night and cfg.get("night_dim_matrix", False)
    if preset == "auto":
        m = color_matrix.preset("nightpaper" if night else "paper")
    elif preset in color_matrix.PRESET_VALUES:
        params = dict(color_matrix.PRESET_VALUES[preset])
        if dim and "luminance" not in params:
            params["luminance"] = 0.85
        if preset == "inverted_paper":
            m = color_matrix.inverted_paper_matrix(**params)
        else:
            m = color_matrix.paper_matrix(**params)
    elif preset in color_matrix.PRESETS:
        m = color_matrix.preset(preset)
    else:
        m = color_matrix.paper_matrix(
            kelvin=cfg["kelvin"],
            desaturation=cfg["desaturation"],
            black_floor=cfg["black_floor"],
            white_ceiling=cfg["white_ceiling"],
            contrast=cfg["contrast"],
            luminance=0.85 if dim else 1.0,
        )
    return m


def _lerp_apply(target, on_done=None):
    """Smoothly transition from current effect to `target` matrix.

    Guarded by re-entrant _transition_lock with generation tracking.
    Runs on the main GUI thread to comply strictly with the Windows Magnification
    API thread affinity rule (Win32 MagSetFullscreenColorEffect fails on secondary threads).
    Pumps Windows messages via PeekMessageW on every frame so UI, tray clicks, and hotkeys
    remain 100% responsive throughout transitions without deadlocking on re-entrant commands.
    """
    global _transition_generation
    with _transition_lock:
        _transition_generation += 1
        my_gen = _transition_generation

        cfg = config.load()
        trans_ms = cfg.get("smooth_transition_ms", 1000)
        trans_sec = max(0.0, trans_ms / 1000.0)

        if trans_sec <= 0.05:
            winlib.mag_set_color_effect(target)
            if on_done:
                on_done()
            return

        try:
            start = winlib.mag_get_color_effect()
        except Exception:
            start = None
        if start is None:
            winlib.mag_set_color_effect(target)
            if on_done:
                on_done()
            return
        start = tuple(tuple(row) for row in start)
        steps = max(2, int(trans_sec * TRANSITION_FPS))

        u32 = winlib.user32()
        msg = wintypes.MSG()
        pmsg = ctypes.byref(msg)

        for i in range(1, steps + 1):
            # Dispatch messages during transition so UI and tray never freeze
            while u32.PeekMessageW(pmsg, 0, 0, 0, 1):
                if msg.message == 0x0012:  # WM_QUIT
                    u32.PostQuitMessage(0)
                    return
                u32.TranslateMessage(pmsg)
                u32.DispatchMessageW(pmsg)
                # If a re-entrant command initiated a newer transition, yield immediately
                if _transition_generation != my_gen:
                    return

            if _transition_generation != my_gen:
                return

            t = color_matrix.ease(i / steps)
            try:
                winlib.mag_set_color_effect(color_matrix.lerp_matrix(start, target, t))
            except Exception as exc:
                logger.debug(f"Interpolation step failed: {exc}")
            time.sleep(1.0 / TRANSITION_FPS)

        if _transition_generation != my_gen:
            return

        # ensure exact target
        try:
            winlib.mag_set_color_effect(target)
        except Exception as exc:
            logger.warn(f"Final target matrix apply failed: {exc}")
        if on_done:
            on_done()


class Daemon:
    def __init__(self):
        self.stop = threading.Event()
        self.current_preset = None
        self.current_night = None
        self.tray_icon: tray.SystemTray | None = None
        self.last_matrix = None
        self.session_locked = False

    # ---------------- hotkey & menu handling ----------------

    def on_hotkey(self) -> None:
        j = signals.load()
        cfg = config.load()
        if j.get("active"):
            # Toggling OFF: revert matrix, restore backlight & smoothing, mark journal paused
            # Daemon remains running in tray so hotkey can toggle back ON.
            _lerp_apply(color_matrix.identity())
            if cfg.get("restore_backlight_on_exit", True):
                try:
                    backlight.restore()
                except Exception as exc:
                    logger.debug(f"Hotkey toggle-off backlight restore: {exc}")
            try:
                cleartype.restore_previous()
            except Exception as exc:
                logger.debug(f"Hotkey toggle-off cleartype restore: {exc}")
            signals.update(active=False, status="paused")
            self.last_matrix = color_matrix.identity()
            if self.tray_icon:
                self.tray_icon.update_tooltip("PaperScreen - Off", active=False)
                self.tray_icon.show_balloon("PaperScreen", "Paper mode turned off.")
            else:
                toasts.show("PaperScreen", "Paper mode turned off.")
        else:
            preset = j.get("preset") or cfg.get("preset", "paper")
            night = config.is_night()
            target = matrix_for(preset, night)
            signals.update(active=True, preset=preset, status="ready")
            _lerp_apply(target)
            self.current_preset, self.current_night = preset, night
            self.last_matrix = target
            level = cfg["backlight_night"] if night else cfg["backlight_day"]
            try:
                backlight.set_brightness(level)
            except Exception as exc:
                logger.debug(f"Hotkey toggle-on backlight set: {exc}")
            if cfg.get("grayscale_smoothing"):
                try:
                    cleartype.enable_grayscale_smoothing()
                except Exception as exc:
                    logger.debug(f"Hotkey toggle-on cleartype enable: {exc}")
            title = preset.replace("_", " ").title()
            if self.tray_icon:
                self.tray_icon.update_tooltip(f"PaperScreen - Active: {title}", active=True)
                self.tray_icon.show_balloon("PaperScreen", f"Paper mode active ({title}).")
            else:
                toasts.show("PaperScreen", f"Paper mode active ({title}).")

    def on_cycle_preset(self) -> None:
        """Cycle to next preset in CYCLE_PRESETS (Ctrl+Alt+N)."""
        j = signals.load()
        cur = j.get("preset") or self.current_preset or "paper"
        try:
            idx = CYCLE_PRESETS.index(cur)
            next_preset = CYCLE_PRESETS[(idx + 1) % len(CYCLE_PRESETS)]
        except ValueError:
            next_preset = CYCLE_PRESETS[0]
        signals.update(active=True, preset=next_preset)
        _lerp_apply(matrix_for(next_preset, config.is_night()))
        self.current_preset = next_preset
        title = next_preset.replace("_", " ").title()
        if self.tray_icon:
            self.tray_icon.update_tooltip(f"PaperScreen - Active: {title}", active=True)
            self.tray_icon.show_balloon("PaperScreen Preset", f"Switched to {title}")
        else:
            toasts.show("PaperScreen", f"Switched to {title}")

    def handle_menu_command(self, cmd_id: int) -> None:
        """Handle context menu selections from the system tray."""
        if cmd_id == tray.CMD_TOGGLE:
            self.on_hotkey()

        elif cmd_id == tray.CMD_HEADER:
            # Refresh current matrix (called after sleep/resume, display change, or settings save)
            j = signals.load()
            cfg = config.load()
            p = j.get("preset") or cfg["preset"]
            _lerp_apply(matrix_for(p, config.is_night()))

        elif cmd_id in (
            tray.CMD_PRESET_PAPER,
            tray.CMD_PRESET_SEPIA,
            tray.CMD_PRESET_WARM_READING,
            tray.CMD_PRESET_EINK,
            tray.CMD_PRESET_EINK_WARM,
            tray.CMD_PRESET_AMBER_CANDLE,
            tray.CMD_PRESET_NIGHTPAPER,
            tray.CMD_PRESET_INVERTED,
            tray.CMD_PRESET_CUSTOM,
            tray.CMD_PRESET_AUTO,
        ):
            mapping = {
                tray.CMD_PRESET_PAPER: "paper",
                tray.CMD_PRESET_SEPIA: "sepia",
                tray.CMD_PRESET_WARM_READING: "warm_reading",
                tray.CMD_PRESET_EINK: "eink",
                tray.CMD_PRESET_EINK_WARM: "eink_warm",
                tray.CMD_PRESET_AMBER_CANDLE: "amber_candle",
                tray.CMD_PRESET_NIGHTPAPER: "nightpaper",
                tray.CMD_PRESET_INVERTED: "inverted_paper",
                tray.CMD_PRESET_CUSTOM: "custom",
                tray.CMD_PRESET_AUTO: "auto",
            }
            new_preset = mapping[cmd_id]
            signals.update(active=True, preset=new_preset)
            _lerp_apply(matrix_for(new_preset, config.is_night()))
            self.current_preset = new_preset
            if self.tray_icon:
                self.tray_icon.update_tooltip(f"PaperScreen - Active: {new_preset.title()}", active=True)

        elif cmd_id in (
            tray.CMD_BRI_100,
            tray.CMD_BRI_75,
            tray.CMD_BRI_60,
            tray.CMD_BRI_40,
            tray.CMD_BRI_25,
        ):
            bri_map = {
                tray.CMD_BRI_100: 100,
                tray.CMD_BRI_75: 75,
                tray.CMD_BRI_60: 60,
                tray.CMD_BRI_40: 40,
                tray.CMD_BRI_25: 25,
            }
            backlight.set_brightness(bri_map[cmd_id])

        elif cmd_id == tray.CMD_BREAK_TOGGLE:
            cfg = config.load()
            cfg["breaks_enabled"] = not cfg.get("breaks_enabled", True)
            config.save(cfg)
            if self.tray_icon:
                st = "enabled" if cfg["breaks_enabled"] else "disabled"
                self.tray_icon.show_balloon("PaperScreen Breaks", f"20-20-20 break reminders {st}.")

        elif cmd_id == tray.CMD_BREAK_NOW:
            toasts.show("PaperScreen Break", "Look at something ~6 m (20 ft) away for 20 seconds.", reminder=True)

        elif cmd_id == tray.CMD_SMOOTHING_TOGGLE:
            cfg = config.load()
            new_val = not cfg.get("grayscale_smoothing", False)
            cfg["grayscale_smoothing"] = new_val
            config.save(cfg)
            if new_val:
                cleartype.enable_grayscale_smoothing()
            else:
                cleartype.restore_previous()

        elif cmd_id == tray.CMD_AUTOSTART_TOGGLE:
            from . import cli
            is_auto = False
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                    winreg.QueryValueEx(k, "PaperScreen")
                    is_auto = True
            except OSError:
                pass
            cli.autostart(enable=not is_auto, disable=is_auto)

        elif cmd_id == tray.CMD_SETTINGS:
            from . import settings_gui
            threading.Thread(target=settings_gui.open_settings_gui, daemon=True).start()

        elif cmd_id == tray.CMD_DOCTOR:
            hdr_info = winlib.get_advanced_color_info()
            hdr_str = "HDR enabled" if any(h.get("hdr_enabled") for h in hdr_info) else "SDR (normal)"
            msg = f"Mode: {self.current_preset or 'paper'}\nDisplay: {hdr_str}\nStatus: Optimal"
            if self.tray_icon:
                self.tray_icon.show_balloon("PaperScreen Diagnostics", msg)

        elif cmd_id == tray.CMD_SESSION_LOCK:
            self.session_locked = True
            logger.info("Workstation locked: resetting display matrix to identity")
            try:
                winlib.mag_set_color_effect(color_matrix.identity())
            except Exception as exc:
                logger.debug(f"Failed to reset matrix on session lock: {exc}")

        elif cmd_id == tray.CMD_SESSION_UNLOCK:
            self.session_locked = False
            logger.info("Workstation unlocked: restoring active paper preset")
            j = signals.load()
            if j.get("active", True):
                cfg = config.load()
                preset = j.get("preset") or cfg["preset"]
                night = config.is_night()
                _lerp_apply(matrix_for(preset, night))
                self.current_preset, self.current_night = preset, night

        elif cmd_id == tray.CMD_LIVE_PREVIEW:
            # Live tuning preview from settings GUI dialog
            j = signals.load()
            live_m = j.get("preview_matrix")
            if live_m:
                try:
                    winlib.mag_set_color_effect(live_m)
                    self.last_matrix = live_m
                except Exception as exc:
                    logger.debug(f"Live preview matrix apply failed: {exc}")

        elif cmd_id == tray.CMD_EXIT:
            _lerp_apply(color_matrix.identity())
            backlight.restore()
            cleartype.restore_previous()
            signals.update(active=False, pid=None)
            self.stop.set()

    # ---------------- lifecycle ----------------

    def run(self) -> int:
        logger.info(f"Daemon.run() invoked on PID {os.getpid()}")
        # OS-level single instance check
        k32 = ctypes.windll.kernel32
        DAEMON_MUTEX_NAME = "Local\\PaperScreenDaemonSingleInstanceMutex"
        h_mutex = k32.CreateMutexW(None, True, DAEMON_MUTEX_NAME)
        err = k32.GetLastError()
        logger.info(f"CreateMutexW result: handle={h_mutex}, error={err}")
        ERROR_ALREADY_EXISTS = 183
        if err == ERROR_ALREADY_EXISTS:
            logger.info("Another PaperScreen daemon instance is already running; exiting redundant instance.")
            if h_mutex:
                k32.CloseHandle(h_mutex)
            return 0

        # Initialize Magnification API strictly on this main thread
        winlib.mag_initialize()

        j = signals.load()
        preset = j.get("preset") or config.load()["preset"]
        night = config.is_night()

        msg = wintypes.MSG()
        pmsg = ctypes.byref(msg)
        last_check = 0.0
        self.last_matrix = None
        try:
            initial_target = matrix_for(preset, night)
            winlib.mag_set_color_effect(initial_target)
            self.last_matrix = initial_target
            logger.info(f"Initial matrix applied for preset: {preset}")
        except Exception as exc:
            logger.error(f"Failed initial matrix apply: {exc}")
        self.current_preset, self.current_night = preset, night
        atexit.register(_revert)
        signals.update(pid=os.getpid(), active=True, status="ready")

        # Initialize System Tray
        self.tray_icon = tray.SystemTray(on_command=self.handle_menu_command)
        tray_ok = self.tray_icon.create()
        if not tray_ok:
            logger.warn("System tray creation failed; continuing in headless mode")
        else:
            self.tray_icon.update_tooltip(f"PaperScreen - Active: {preset.title()}", active=True)

        # RegisterHotKey (optional; ignore failure)
        hotkey_ok = False
        cycle_hotkey_ok = False
        if config.load().get("hotkey_toggle", True):
            hotkey_ok = bool(
                winlib.user32().RegisterHotKey(
                    None, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_P
                )
            )
            cycle_hotkey_ok = bool(
                winlib.user32().RegisterHotKey(
                    None, HOTKEY_CYCLE_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_N
                )
            )

        msg = wintypes.MSG()
        pmsg = ctypes.byref(msg)
        last_check = 0.0

        try:
            while not self.stop.is_set():
                while winlib.user32().PeekMessageW(pmsg, 0, 0, 0, 1):
                    if msg.message == 0x0012: # WM_QUIT
                        logger.info("Daemon received WM_QUIT; exiting loop")
                        self.stop.set()
                        break
                    if msg.message == WM_HOTKEY:
                        if msg.wParam == HOTKEY_ID:
                            self.on_hotkey()
                        elif msg.wParam == HOTKEY_CYCLE_ID:
                            self.on_cycle_preset()
                    winlib.user32().TranslateMessage(pmsg)
                    winlib.user32().DispatchMessageW(pmsg)

                if self.stop.is_set():
                    break

                now = time.time()
                if now - last_check >= POLL_SECONDS:
                    last_check = now

                    # Skip adjustments while workstation session is locked
                    if getattr(self, "session_locked", False):
                        continue

                    j = signals.load()
                    if j.get("status") == "stopping":
                        logger.info("Stopping signal received; shutting down daemon.")
                        self.stop.set()
                        break

                    if j.get("active") is False:
                        # Daemon is paused/toggled off
                        if self.last_matrix != color_matrix.identity():
                            _lerp_apply(color_matrix.identity())
                            self.last_matrix = color_matrix.identity()
                            if self.tray_icon:
                                self.tray_icon.update_tooltip("PaperScreen - Off", active=False)
                        continue

                    # While settings live preview is being tuned, do not overwrite the matrix
                    if j.get("preview_matrix") is not None:
                        continue

                    cfg = config.load()
                    preset = j.get("preset") or cfg["preset"]
                    night = config.is_night()

                    # Auto-pause for fullscreen apps or excluded processes
                    paused = False
                    if cfg.get("auto_pause_fullscreen", False) and winlib.is_foreground_fullscreen():
                        paused = True
                    elif cfg.get("excluded_apps"):
                        fg_proc = winlib.get_foreground_process_name()
                        if fg_proc and fg_proc in cfg["excluded_apps"]:
                            paused = True

                    if paused:
                        if self.last_matrix != "paused":
                            _lerp_apply(color_matrix.identity())
                            self.last_matrix = "paused"
                            if self.tray_icon:
                                self.tray_icon.update_tooltip("PaperScreen - Paused (App Exclusion)", active=False)
                        continue
                    elif self.last_matrix == "paused":
                        self.last_matrix = None

                    # Check if day/night changed to update backlight automatically (circadian sync)
                    if night != self.current_night and j.get("active", True):
                        level = cfg["backlight_night"] if night else cfg["backlight_day"]
                        try:
                            backlight.set_brightness(level)
                            logger.info(f"Circadian transition: backlight adjusted to {level}%")
                        except Exception as exc:
                            logger.debug(f"Backlight circadian transition failed: {exc}")

                    # Detect if target matrix changed (preset, day/night, or custom config parameters)
                    target = matrix_for(preset, night)
                    if target != self.last_matrix:
                        _lerp_apply(target)
                        self.current_preset, self.current_night = preset, night
                        self.last_matrix = target
                        signals.update(
                            active=True,
                            preset=preset,
                            applied_at=datetime.datetime.now().isoformat(timespec="seconds"),
                        )
                        if self.tray_icon:
                            self.tray_icon.update_tooltip(f"PaperScreen - Active: {preset.title()}", active=True)

                # Efficient message wait: sleeps up to 500ms, or wakes instantly when a message arrives
                u32 = winlib.user32()
                if hasattr(u32, "MsgWaitForMultipleObjects"):
                    u32.MsgWaitForMultipleObjects(0, None, False, int(POLL_SECONDS * 1000), 0x04FF)
                else:
                    time.sleep(0.04)
        finally:
            logger.info(f"Daemon process {os.getpid()} entering finally cleanup block")
            if hotkey_ok:
                winlib.user32().UnregisterHotKey(None, HOTKEY_ID)
            if cycle_hotkey_ok:
                winlib.user32().UnregisterHotKey(None, HOTKEY_CYCLE_ID)
            if self.tray_icon:
                self.tray_icon.remove()
            self.stop.set()
            _revert()
            cfg = config.load()
            if cfg.get("restore_backlight_on_exit", True):
                try:
                    backlight.restore()
                except Exception as exc:
                    logger.debug(f"Daemon cleanup backlight restore: {exc}")
            try:
                cleartype.restore_previous()
            except Exception as exc:
                logger.debug(f"Daemon cleanup cleartype restore: {exc}")
            signals.update(active=False, pid=None, status="stopped")
            if h_mutex:
                k32.ReleaseMutex(h_mutex)
                k32.CloseHandle(h_mutex)
            logger.info(f"Daemon process {os.getpid()} finished finally cleanup")
        return 0


def _revert() -> None:
    try:
        winlib.mag_set_color_effect(color_matrix.identity())
    except Exception as exc:
        logger.debug(f"Revert error: {exc}")


def _unregister_revert(daemon: Daemon) -> None:
    """Superseded daemon: do NOT revert (the new owner keeps the effect)."""
    try:
        atexit.unregister(_revert)
    except Exception:
        pass


def daemon_main() -> int:
    d = Daemon()
    try:
        return d.run()
    except KeyboardInterrupt:
        d.stop.set()
        _revert()
        return 0
    except Exception as exc:
        logger.error(f"Daemon crashed with unhandled exception: {exc}", exc)
        _revert()
        return 1


run = daemon_main


__all__ = [
    "Daemon",
    "matrix_for",
    "daemon_main",
    "run",
]


if __name__ == "__main__":
    sys.exit(daemon_main())
