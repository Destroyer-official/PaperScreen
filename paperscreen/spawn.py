"""Spawning utilities for the detached daemon process.

Uses ctypes CreateProcessW with DETACHED_PROCESS so the daemon owns its
own console-less session and survives the caller exiting.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

kernel32 = ctypes.windll.kernel32
kernel32.CreateProcessW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.BOOL,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.LPCWSTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
]
kernel32.CreateProcessW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


class _STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _quote(s: str) -> str:
    if " " in s or "\t" in s:
        return f'"{s}"'
    return s


def start_detached(module_args: list) -> int:
    """Start daemon detached with correct working directory and module path. Returns pid, 0 on fail."""
    import os
    import subprocess
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

    DETACHED_PROCESS = 0x00000008
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
    SYNCHRONIZE = 0x00100000
    kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    h = kernel32.OpenMutexW(SYNCHRONIZE, False, DAEMON_MUTEX_NAME)
    if h:
        kernel32.CloseHandle(h)
        return True
    return False


def is_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
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

