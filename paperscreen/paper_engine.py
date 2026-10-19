"""PaperScreen engine: apply/release the paper effect via a resident daemon.

Architecture (verified against Windows behavior):
- The full-screen magnifier color transform is SESSION-BOUND: it vanishes
  when the applying process exits. Therefore `on` spawns a detached daemon
  that holds the effect; `off` flips the journal flag and the daemon reverts
  and exits. Killing the daemon also clears the effect (session teardown),
  so no stuck-tint state is possible.
- DDC backlight changes ARE persistent hardware state, so they are applied
  by the CLI process directly and journaled for cross-process restore.
"""

from __future__ import annotations

import datetime
import time

from . import backlight, cleartype, color_matrix, config, signals, spawn, winlib

MAX_DAEMON_WAIT = 10


def apply(preset: str = None, set_backlight: bool = True) -> dict:
    """Activate paper mode by spawning the daemon. Returns status dict."""
    cfg = config.load()
    preset = preset or cfg["preset"]
    if preset == "auto":
        preset = "auto"  # daemon resolves day/night matrices dynamically

    journal = signals.load()
    # already running daemon takes the new preset via journal
    signals.update(
        active=True,
        preset=preset,
        applied_at=datetime.datetime.now().isoformat(timespec="seconds"),
    )

    report: dict = {"preset": preset, "matrix": None, "backlight": None, "smoothing": None}

    old_pid = journal.get("pid")
    if old_pid and spawn.is_alive(int(old_pid)):
        # daemon alive: it polls the journal and will pick up the new preset
        report["matrix"] = f"daemon pid {old_pid} updated"
    else:
        import sys
        target_args = ["daemon"] if getattr(sys, "frozen", False) else ["paperscreen.daemon"]
        pid = spawn.start_detached(target_args)
        if pid:
            report["matrix"] = f"daemon pid {pid} started"
            deadline = time.time() + MAX_DAEMON_WAIT
            while time.time() < deadline:
                j = signals.load()
                if j.get("pid") == pid:
                    break
                time.sleep(0.1)
        else:
            # spawn failed: fall back to in-process effect (session-lifetime)
            winlib.mag_set_color_effect(color_matrix.preset(preset))
            report["matrix"] = "in-process fallback (clears when this process exits)"

    if set_backlight:
        level = cfg["backlight_night"] if config.is_night() else cfg["backlight_day"]
        try:
            report["backlight"] = backlight.set_brightness(level)
        except winlib.PaperAPIError as exc:
            report["backlight"] = {"error": str(exc)}

    if cfg["grayscale_smoothing"]:
        report["smoothing"] = cleartype.enable_grayscale_smoothing()

    return report


def release(reason: str = "manual") -> dict:
    """Deactivate paper mode: flag off; daemon reverts matrix and exits.
    Backlight + smoothing restored here (they're process-independent)."""
    report: dict = {"reason": reason, "matrix": None, "backlight": None, "smoothing": None}

    journal = signals.load()
    pid = journal.get("pid")
    signals.update(active=False)

    # wait briefly for daemon to revert matrix (it does it on exit)
    if pid and spawn.is_alive(int(pid)):
        deadline = time.time() + MAX_DAEMON_WAIT
        while time.time() < deadline and spawn.is_alive(int(pid)):
            time.sleep(0.1)
        report["matrix"] = "daemon reverted and exited"
    else:
        # no daemon: make sure matrix is identity ourselves
        try:
            winlib.mag_set_color_effect(color_matrix.identity())
            report["matrix"] = "identity set directly"
        except winlib.PaperAPIError as exc:
            report["matrix"] = f"error: {exc}"

    try:
        report["backlight"] = backlight.restore()
    except winlib.PaperAPIError as exc:
        report["backlight"] = {"error": str(exc)}

    try:
        report["smoothing"] = cleartype.restore_previous()
    except winlib.PaperAPIError as exc:
        report["smoothing"] = f"error: {exc}"

    return report


def status() -> dict:
    journal = signals.load()
    try:
        current = winlib.mag_get_color_effect()
    except winlib.PaperAPIError:
        current = None
    identity = color_matrix.identity()
    is_identity = current is not None and all(
        abs(current[r][c] - identity[r][c]) < 1e-6 for r in range(5) for c in range(5)
    )
    pid = journal.get("pid")
    return {
        "engine_active": bool(journal.get("active")),
        "daemon_pid": pid,
        "daemon_alive": spawn.is_alive(int(pid)) if pid else False,
        "matrix_is_identity": is_identity,
        "preset": journal.get("preset"),
        "applied_at": journal.get("applied_at"),
        "backlight_level": journal.get("backlight_level"),
        "cleartype": cleartype.status(),
    }
