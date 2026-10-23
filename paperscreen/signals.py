"""Persistent state journal so separate CLI processes can restore each
other's changes (e.g. `paperscreen on` then later `paperscreen off`).

Synchronized cross-process via Windows Named Mutex to prevent read-modify-write lost updates.
Lives beside config.json in %APPDATA%/PaperScreen/state.json.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
import time
from typing import Iterator, Optional

from .config import config_dir

STATE_NAME = "state.json"
JOURNAL_MUTEX_NAME = "Local\\PaperScreenJournalMutex"

_LOCAL_LOCK = threading.RLock()


@contextlib.contextmanager
def journal_lock(timeout_seconds: float = 5.0) -> Iterator[None]:
    """Acquire cross-process (and cross-thread) lock on the state journal.

    Fails closed: raises TimeoutError if lock cannot be acquired within timeout.
    """
    h_mutex = None
    acquired = False

    # First acquire in-process re-entrant lock
    if not _LOCAL_LOCK.acquire(timeout=timeout_seconds):
        raise TimeoutError(f"Could not acquire in-process journal lock within {timeout_seconds}s")

    try:
        if sys.platform == "win32":
            from . import winlib
            from ctypes import wintypes
            k32 = winlib.kernel32()
            timeout_ms = int(timeout_seconds * 1000)
            h_mutex = k32.CreateMutexW(None, False, JOURNAL_MUTEX_NAME)
            if not h_mutex:
                raise TimeoutError("CreateMutexW failed to create/open journal mutex")
            # 0x00000000 = WAIT_OBJECT_0, 0x00000080 = WAIT_ABANDONED
            res = k32.WaitForSingleObject(h_mutex, wintypes.DWORD(timeout_ms))
            if res not in (0x00000000, 0x00000080):
                raise TimeoutError(f"WaitForSingleObject on journal mutex timed out or failed (code 0x{res:X})")
            acquired = True
        else:
            acquired = True

        yield
    finally:
        if sys.platform == "win32" and h_mutex:
            if acquired:
                try:
                    winlib.kernel32().ReleaseMutex(h_mutex)
                except Exception:
                    pass
            try:
                winlib.kernel32().CloseHandle(h_mutex)
            except Exception:
                pass
        _LOCAL_LOCK.release()


def state_path() -> str:
    return os.path.join(config_dir(), STATE_NAME)


def _load_unlocked() -> dict:
    p = state_path()
    if not os.path.isfile(p):
        return {}
    for attempt in range(3):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (ValueError, json.JSONDecodeError):
            if attempt < 2:
                time.sleep(0.05)
            elif os.path.isfile(p):
                # Back up unparseable/corrupted JSON file so it does not block future runs
                try:
                    os.replace(p, f"{p}.corrupt")
                except OSError:
                    pass
                return {}
        except OSError:
            # Transient OS error (e.g. sharing violation / antivirus lock)
            # Never quarantine on transient I/O locks, preserve original state
            if attempt < 2:
                time.sleep(0.05)
            else:
                return {}
    return {}


def load() -> dict:
    with journal_lock():
        return _load_unlocked()


def update(**fields) -> dict:
    with journal_lock():
        data = _load_unlocked()
        for k, v in fields.items():
            if v is None:
                data.pop(k, None)
            else:
                data[k] = v
        _save_unlocked(data)
        return data


def _save_unlocked(data: dict) -> None:
    os.makedirs(config_dir(), exist_ok=True)
    target = state_path()
    tmp = target + f".{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except Exception:
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def save(data: dict) -> None:
    with journal_lock():
        _save_unlocked(data)


def clear() -> None:
    with journal_lock():
        try:
            os.remove(state_path())
        except OSError:
            pass


__all__ = [
    "journal_lock",
    "state_path",
    "load",
    "update",
    "save",
    "clear",
]
