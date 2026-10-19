"""Lightweight rotating file logger for PaperScreen.

Writes to %APPDATA%/PaperScreen/paperscreen.log with zero third-party dependencies.
Keeps log file size bounded (< 2 MB) and rotates automatically.
"""

from __future__ import annotations

import datetime
import os
import sys
import threading
from typing import Optional

from .config import config_dir

LOG_FILENAME = "paperscreen.log"
MAX_BYTES = 2 * 1024 * 1024  # 2 MB
BACKUP_FILENAME = "paperscreen.log.old"

_log_lock = threading.Lock()


def log_path() -> str:
    return os.path.join(config_dir(), LOG_FILENAME)


def _rotate_if_needed(path: str) -> None:
    try:
        if os.path.isfile(path) and os.path.getsize(path) >= MAX_BYTES:
            backup = os.path.join(config_dir(), BACKUP_FILENAME)
            if os.path.isfile(backup):
                os.remove(backup)
            os.rename(path, backup)
    except OSError:
        pass


def log(level: str, msg: str, exc: Optional[BaseException] = None) -> None:
    """Append a timestamped log entry."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] [{level.upper():5s}] {msg}"
    if exc:
        line += f" | Exception: {type(exc).__name__}: {exc}"
    line += "\n"

    with _log_lock:
        try:
            os.makedirs(config_dir(), exist_ok=True)
            path = log_path()
            _rotate_if_needed(path)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass


def info(msg: str) -> None:
    log("INFO", msg)


def warn(msg: str, exc: Optional[BaseException] = None) -> None:
    log("WARN", msg, exc)


def error(msg: str, exc: Optional[BaseException] = None) -> None:
    log("ERROR", msg, exc)


def debug(msg: str) -> None:
    log("DEBUG", msg)
