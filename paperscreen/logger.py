"""Lightweight rotating file logger for PaperScreen.

Writes to %APPDATA%/PaperScreen/paperscreen.log with zero third-party dependencies.
Keeps log file size bounded (< 2 MB) and rotates automatically.
Provides console output streaming and full traceback capture for crash debugging.
"""

from __future__ import annotations

import datetime
import os
import sys
import threading
import traceback
from typing import Optional

from .config import config_dir

LOG_FILENAME = "paperscreen.log"
MAX_BYTES = 2 * 1024 * 1024  # 2 MB
BACKUP_FILENAME = "paperscreen.log.old"

_log_lock = threading.Lock()

LEVEL_RANKS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 30,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}

_console_logging = os.environ.get("PAPERSCREEN_DEBUG") in ("1", "true", "True")
_min_level = "DEBUG" if _console_logging else "INFO"


def enable_console_logging(level: str = "DEBUG") -> None:
    """Enable real-time log streaming to sys.stderr."""
    global _console_logging, _min_level
    _console_logging = True
    _min_level = level.upper()


def disable_console_logging() -> None:
    """Disable real-time log streaming to sys.stderr."""
    global _console_logging
    _console_logging = False


def is_console_logging_enabled() -> bool:
    return _console_logging


def set_min_level(level: str) -> None:
    global _min_level
    _min_level = level.upper()


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
    """Append a timestamped log entry to file and optionally sys.stderr with full traceback."""
    lvl_upper = level.upper()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] [{lvl_upper:5s}] {msg}"
    if exc:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
        line += f"\n{tb}"
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

        if _console_logging:
            msg_rank = LEVEL_RANKS.get(lvl_upper, 20)
            thresh_rank = LEVEL_RANKS.get(_min_level, 10)
            if msg_rank >= thresh_rank:
                try:
                    sys.stderr.write(line)
                    sys.stderr.flush()
                except Exception:
                    pass


def info(msg: str) -> None:
    log("INFO", msg)


def warn(msg: str, exc: Optional[BaseException] = None) -> None:
    log("WARN", msg, exc)


def error(msg: str, exc: Optional[BaseException] = None) -> None:
    log("ERROR", msg, exc)


def debug(msg: str) -> None:
    log("DEBUG", msg)


def install_excepthook() -> None:
    """Install global sys.excepthook to log uncaught exceptions with full tracebacks."""
    orig_hook = sys.excepthook

    def _hook(exc_type, exc_val, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            orig_hook(exc_type, exc_val, exc_tb)
            return
        error(f"Uncaught exception: {exc_type.__name__}: {exc_val}", exc_val)
        orig_hook(exc_type, exc_val, exc_tb)

    sys.excepthook = _hook


# Automatically activate crash hook upon import
install_excepthook()
