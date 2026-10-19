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
    """Start `pythonw -m <module...> <args>` or `PaperScreen.exe <args>` detached. Returns pid, 0 on fail."""
    import os
    if getattr(sys, "frozen", False):
        cmdline = [sys.executable, *module_args]
    else:
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        exe = pythonw if os.path.isfile(pythonw) else sys.executable
        cmdline = [exe, "-m", *module_args]
    args = " ".join(_quote(a) for a in cmdline)
    si = _STARTUPINFO()
    si.cb = ctypes.sizeof(_STARTUPINFO)
    pi = _PROCESS_INFORMATION()
    ok = kernel32.CreateProcessW(
        None, args, None, None, False,
        DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        None, None, ctypes.byref(si), ctypes.byref(pi)
    )
    if not ok:
        return 0
    pid = pi.dwProcessId
    kernel32.CloseHandle(pi.hProcess)
    kernel32.CloseHandle(pi.hThread)
    return pid


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
            return code.value == STILL_ACTIVE
        return False
    finally:
        kernel32.CloseHandle(h)
