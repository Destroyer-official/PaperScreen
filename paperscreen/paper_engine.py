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
    old_pid = journal.get("pid")
    report: dict = {"preset": preset, "matrix": None, "backlight": None, "smoothing": None, "status": "active"}

    if spawn.is_daemon_running():
        # daemon alive: update journal and signal preset change
        signals.update(
            active=True,
            preset=preset,
            status="ready",
            applied_at=datetime.datetime.now().isoformat(timespec="seconds"),
        )
        report["matrix"] = f"daemon pid {old_pid} updated" if old_pid else "daemon updated"
    else:
        signals.update(
            active=True,
            preset=preset,
            pid=None,
            status="starting",
            applied_at=datetime.datetime.now().isoformat(timespec="seconds"),
        )
        import sys
        target_args = ["daemon"] if getattr(sys, "frozen", False) else ["paperscreen.daemon"]
        pid = spawn.start_detached(target_args)
        if pid:
            daemon_ready = False
            deadline = time.time() + MAX_DAEMON_WAIT
            while time.time() < deadline:
                if spawn.is_daemon_running():
                    daemon_ready = True
                    break
                time.sleep(0.1)

            if daemon_ready:
                report["matrix"] = f"daemon pid {pid} started"
                report["status"] = "ready"
            else:
                signals.update(active=False, pid=None, status="failed")
                report["matrix"] = "daemon failed to start within timeout"
                report["status"] = "failed"
                return report
        else:
            # spawn failed: fall back to in-process effect (session-lifetime)
            try:
                winlib.mag_set_color_effect(color_matrix.preset(preset))
                report["matrix"] = "in-process fallback (clears when this process exits)"
                report["status"] = "fallback"
            except Exception as exc:
                signals.update(active=False, status="failed")
                report["matrix"] = f"in-process fallback failed: {exc}"
                report["status"] = "failed"
                return report

    if set_backlight:
        level = cfg["backlight_night"] if config.is_night() else cfg["backlight_day"]
        try:
            report["backlight"] = backlight.set_brightness(level, rollback_on_failure=True)
        except winlib.PaperAPIError as exc:
            report["backlight"] = {"error": str(exc)}

    if cfg["grayscale_smoothing"]:
        report["smoothing"] = cleartype.enable_grayscale_smoothing()

    return report


def release(reason: str = "manual") -> dict:
    """Deactivate paper mode: flag off; daemon reverts matrix and exits.
    Backlight + smoothing restored here (they're process-independent)."""
    cfg = config.load()
    report: dict = {"reason": reason, "matrix": None, "backlight": None, "smoothing": None}

    signals.update(active=False, status="stopping")

    # wait briefly for daemon to revert matrix (it does it on exit)
    if spawn.is_daemon_running():
        deadline = time.time() + MAX_DAEMON_WAIT
        while time.time() < deadline and spawn.is_daemon_running():
            time.sleep(0.1)
        if spawn.is_daemon_running():
            report["matrix"] = "daemon stop timed out"
            report["status"] = "timeout"
        else:
            report["matrix"] = "daemon reverted and exited"
            report["status"] = "stopped"
    else:
        # no daemon: make sure matrix is identity ourselves
        try:
            winlib.mag_set_color_effect(color_matrix.identity())
            report["matrix"] = "identity set directly"
            report["status"] = "stopped"
        except winlib.PaperAPIError as exc:
            report["matrix"] = f"error: {exc}"
            report["status"] = "error"

    if cfg.get("restore_backlight_on_exit", True):
        try:
            report["backlight"] = backlight.restore()
        except winlib.PaperAPIError as exc:
            report["backlight"] = {"error": str(exc)}
    else:
        report["backlight"] = {"skipped": "restore_backlight_on_exit is false"}

    try:
        report["smoothing"] = cleartype.restore_previous()
    except winlib.PaperAPIError as exc:
        report["smoothing"] = f"error: {exc}"

    if report.get("status") != "timeout":
        signals.update(active=False, pid=None, status="stopped")
    else:
        signals.update(status="timeout")
    return report


def status() -> dict:
    journal = signals.load()
    daemon_running = spawn.is_daemon_running()
    identity = color_matrix.identity()
    if daemon_running:
        is_identity = False
    else:
        try:
            current = winlib.mag_get_color_effect()
        except winlib.PaperAPIError:
            current = None
        is_identity = current is not None and all(
            abs(current[r][c] - identity[r][c]) < 1e-6 for r in range(5) for c in range(5)
        )
    pid = journal.get("pid")
    return {
        "engine_active": bool(journal.get("active")) and daemon_running,
        "daemon_pid": pid if daemon_running else None,
        "daemon_alive": daemon_running,
        "matrix_is_identity": is_identity,
        "preset": journal.get("preset"),
        "applied_at": journal.get("applied_at"),
        "backlight_level": journal.get("backlight_level"),
        "cleartype": cleartype.status(),
    }


__all__ = [
    "apply",
    "release",
    "status",
]
