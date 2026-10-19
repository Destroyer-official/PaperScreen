"""Autostart helper: launched by the HKCU Run key at login.

Starts the paper daemon (holding the matrix) and the background break
timer, both detached and console-free. Safe to run multiple times: the
daemon journal and break lock prevent duplicates.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    from . import breaks, paper_engine, config

    cfg = config.load()
    if cfg.get("preset", "paper") != "off":
        paper_engine.apply(set_backlight=True)
    if cfg.get("breaks_enabled", True):
        breaks.run_detached(cfg["break_interval_minutes"], cfg["break_duration_seconds"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
