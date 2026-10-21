"""Spawning utilities for the detached daemon process.

Uses subprocess.Popen with detached flags so the daemon owns its
own console-less session and survives the caller exiting.
"""

from __future__ import annotations

import os
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
else:
    kernel32 = None


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
    if not IS_WINDOWS or kernel32 is None:
        return False
    from ctypes import wintypes
    SYNCHRONIZE = 0x00100000
    kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    h = kernel32.OpenMutexW(SYNCHRONIZE, False, DAEMON_MUTEX_NAME)
    if h:
        kernel32.CloseHandle(h)
        return True
    return False


def is_alive(pid: int) -> bool:
    if not IS_WINDOWS or kernel32 is None or not pid or pid <= 0:
        return False
    from ctypes import wintypes
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    try:
        code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
            if code.value != STILL_ACTIVE:
                return False
            # Validate process executable to ensure unrelated PIDs are not misidentified
            buf = (wintypes.WCHAR * 1024)()
            size = wintypes.DWORD(1024)
            if hasattr(kernel32, "QueryFullProcessImageNameW"):
                if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    exe_name = buf.value.lower()
                    if not any(k in exe_name for k in ("python", "paperscreen")):
                        return False
            return True
        return False
    finally:
        kernel32.CloseHandle(h)


__all__ = [
    "start_detached",
    "is_daemon_running",
    "is_alive",
]

