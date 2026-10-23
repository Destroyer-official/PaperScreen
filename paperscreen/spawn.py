"""Spawning utilities for the detached daemon process.

Uses subprocess.Popen with detached flags so the daemon owns its
own console-less session and survives the caller exiting.
"""

from __future__ import annotations

import os
import subprocess
import sys

from . import winlib

IS_WINDOWS = sys.platform == "win32"


def start_detached(module_args: list) -> int:
    """Start daemon detached with correct working directory and module path. Returns pid, 0 on fail."""
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = pkg_root + (os.pathsep + env["PYTHONPATH"] if "PYTHONPATH" in env else "")

    if getattr(sys, "frozen", False):
        cmdline = [sys.executable, *module_args]
        cwd = os.path.dirname(sys.executable)
    else:
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        exe = pythonw if os.path.isfile(pythonw) else sys.executable
        cmdline = [exe, "-m", *module_args]
        cwd = pkg_root

    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_NO_WINDOW = 0x08000000

    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE

    try:
        p = subprocess.Popen(
            cmdline,
            cwd=cwd,
            env=env,
            creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
            startupinfo=si,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        return p.pid
    except Exception:
        return 0


DAEMON_MUTEX_NAME = "Local\\PaperScreenDaemonSingleInstanceMutex"


def is_daemon_running() -> bool:
    """Check if the PaperScreen daemon is actually running via the OS Named Mutex."""
    if not IS_WINDOWS:
        return False
    k32 = winlib.kernel32()
    SYNCHRONIZE = 0x00100000
    h = k32.OpenMutexW(SYNCHRONIZE, False, DAEMON_MUTEX_NAME)
    if h:
        k32.CloseHandle(h)
        return True
    return False


def is_alive(pid: int) -> bool:
    if not IS_WINDOWS or not pid or pid <= 0:
        return False
    import ctypes
    from ctypes import wintypes
    k32 = winlib.kernel32()
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    try:
        code = wintypes.DWORD()
        if k32.GetExitCodeProcess(h, ctypes.byref(code)):
            if code.value != STILL_ACTIVE:
                return False
            # Validate process executable to ensure unrelated PIDs are not misidentified
            buf = (wintypes.WCHAR * 1024)()
            size = wintypes.DWORD(1024)
            if hasattr(k32, "QueryFullProcessImageNameW"):
                if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    exe_name = buf.value.lower()
                    if not any(k in exe_name for k in ("python", "paperscreen")):
                        return False
            return True
        return False
    finally:
        k32.CloseHandle(h)


__all__ = [
    "start_detached",
    "is_daemon_running",
    "is_alive",
]

