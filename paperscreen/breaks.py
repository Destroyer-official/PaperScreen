"""20-20-20 break reminder with toasts and idle-awareness.

Evidence: regular breaks are the best-supported digital-eye-strain
mitigation (TFOS Lifestyle 2023, PMID 37062428); adherence is the
bottleneck (PMID 41322997) -> gentle escalating toasts, idle-aware.

Console fallback when toasts are unavailable. Detachable via
`paperscreen break --detached` so the timer survives closing the terminal.
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
import time

from . import config, toasts

GENTLE = "Look at something ~6 m (20 ft) away for 20 seconds."
ESCALATING = [
    GENTLE,
    "Still here? Your eyes need a focus change - glance out a window.",
    "Break skipped. Blink 10 times slowly, then look far away for 20 s.",
]


_BREAKS_MUTEX_NAME = "Local\\PaperScreenBreaksMutex"
_breaks_mutex_handle = None


def _lock_path() -> str:
    return os.path.join(config.config_dir(), "breaks.lock")


def _acquire_lock() -> bool:
    """Acquire single-instance lock via OS Named Mutex and write PID file."""
    global _breaks_mutex_handle
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.windll.kernel32
            ERROR_ALREADY_EXISTS = 183
            h = k32.CreateMutexW(None, wintypes.BOOL(True), wintypes.LPCWSTR(_BREAKS_MUTEX_NAME))
            if not h or k32.GetLastError() == ERROR_ALREADY_EXISTS:
                if h:
                    k32.CloseHandle(h)
                return False
            _breaks_mutex_handle = h
        except Exception:
            pass

    # Record PID file for diagnostic/management tools
    try:
        os.makedirs(config.config_dir(), exist_ok=True)
        with open(_lock_path(), "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass
    return True


def _release_lock() -> None:
    """Release OS Named Mutex and clean up PID file."""
    global _breaks_mutex_handle
    if _breaks_mutex_handle:
        try:
            import ctypes
            ctypes.windll.kernel32.ReleaseMutex(_breaks_mutex_handle)
            ctypes.windll.kernel32.CloseHandle(_breaks_mutex_handle)
        except Exception:
            pass
        _breaks_mutex_handle = None
    try:
        os.remove(_lock_path())
    except OSError:
        pass


def _user_idle_seconds() -> float:
    """Seconds since last user keyboard/mouse input (0 if unavailable)."""
    try:
        from . import winlib
        import ctypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        info = LASTINPUTINFO()
        info.cb = ctypes.sizeof(LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            # dwTime is 32-bit tick count from GetTickCount; compare modulo 2^32 or with tick64
            now_tick = winlib.get_tick_count_64() & 0xFFFFFFFF
            millis = (now_tick - info.dwTime) & 0xFFFFFFFF
            return max(0.0, millis / 1000.0)
    except Exception:
        pass
    return 0.0


def _notify(index: int, console: bool) -> None:
    msg = ESCALATING[min(index, len(ESCALATING) - 1)]
    if console:
        now = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] BREAK: {msg}", flush=True)
    else:
        toasts.show("PaperScreen break", msg, reminder=True)


def run(interval_minutes: int = 20, duration_seconds: int = 20,
        console: bool = False, escalate_after: int = 2) -> int:
    """Blocking reminder loop with monotonic wall-clock timing. Ctrl+C to stop."""
    if not _acquire_lock():
        print("Another break timer is already running.", file=sys.stderr)
        return 1
    if not console:
        print(f"Break timer running (reminders every {interval_minutes} min). Ctrl+C to stop.",
              flush=True)
    skipped = 0
    interval_sec = interval_minutes * 60
    try:
        while True:
            # Monotonic wall-clock wait (resilient to sleep/wake)
            deadline = time.monotonic() + interval_sec
            while time.monotonic() < deadline:
                time.sleep(1.0)

            # Idle > 2 min likely means user is already resting/away
            if _user_idle_seconds() > 120:
                continue

            _notify(skipped, console)

            # Break window
            was_active = _user_idle_seconds() < 10
            break_deadline = time.monotonic() + duration_seconds
            while time.monotonic() < break_deadline:
                time.sleep(1.0)

            if was_active and _user_idle_seconds() < 10:
                skipped += 1
            else:
                skipped = 0
    except KeyboardInterrupt:
        if not console:
            print("\nBreak timer stopped.")
        return 0
    finally:
        _release_lock()


def run_detached(interval_minutes: int, duration_seconds: int) -> int:
    """Spawn a detached break timer via pythonw (no console flash)."""
    import sys as _sys

    args = [
        _sys.executable, "-m", "paperscreen.breaks",
        str(interval_minutes), str(duration_seconds), "--console-quiet",
    ]
    pythonw = os.path.join(os.path.dirname(_sys.executable), "pythonw.exe")
    if os.path.isfile(pythonw):
        args[0] = pythonw
    try:
        subprocess.Popen(
            args,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        return 0
    except OSError:
        return 1


__all__ = [
    "run",
    "run_detached",
    "GENTLE",
    "ESCALATING",
]


if __name__ == "__main__":
    a = sys.argv[1:]
    quiet = "--console-quiet" in a
    a = [x for x in a if x != "--console-quiet"]
    interval = int(a[0]) if a else 20
    duration = int(a[1]) if len(a) > 1 else 20
    sys.exit(run(interval, duration, console=quiet))
