"""Backlight control via DDC/CI with graceful WMI fallback for laptops.

Chain: DDC/CI (dxva2) -> WMI (internal laptop panels) -> no-op with warning.
Never raises for unavailable hardware; reports what it did.
Supports multi-monitor setups with identical display names.
"""

from __future__ import annotations

import subprocess
from typing import List, Optional

from . import logger, signals, winlib
from .winlib import PaperAPIError


class MonitorBrightness:
    """One monitor's last-known state for restore purposes."""

    def __init__(self, handle: int, name: str, previous: Optional[int], key: str):
        self.handle = handle
        self.name = name
        self.previous = previous
        self.key = key


# ---------------------------------------------------------------------------
# WMI Fallback for Internal Laptop Displays
# ---------------------------------------------------------------------------

def _wmi_get_brightness() -> Optional[int]:
    """Query internal laptop display brightness via WMI."""
    try:
        cmd = [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightness -ErrorAction Stop).CurrentBrightness"
        ]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=3, creationflags=flags)
        if res.returncode == 0 and res.stdout.strip().isdigit():
            return int(res.stdout.strip())
    except Exception as exc:
        logger.debug(f"WMI brightness query: {exc}")
    return None


def _wmi_set_brightness(level: int) -> bool:
    """Set internal laptop display brightness via WMI."""
    level = max(0, min(100, int(level)))
    try:
        cmd = [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            f"(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop) | ForEach-Object {{ $_.WmiSetBrightness(0, {level}) }}"
        ]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=4, creationflags=flags)
        return res.returncode == 0
    except Exception as exc:
        logger.debug(f"WMI brightness set: {exc}")
        return False


# ---------------------------------------------------------------------------
# Public Backlight API
# ---------------------------------------------------------------------------

def list_monitors() -> List[dict]:
    """Info dict per monitor (current brightness if readable)."""
    out = []
    opened = []
    try:
        opened = winlib.get_physical_monitors()
        for i, (handle, name) in enumerate(opened):
            cur = winlib.ddc_get_brightness(handle)
            out.append({
                "id": f"{name} #{i+1}",
                "name": name,
                "brightness": cur,
                "ddc": cur is not None,
                "method": "ddc" if cur is not None else "unsupported",
            })
    except PaperAPIError as exc:
        logger.warn(f"Failed to enumerate DDC monitors: {exc}")
    finally:
        if opened:
            winlib.destroy_physical_monitors([h for h, _ in opened])

    # If no DDC monitors found, check for internal laptop display
    if not out:
        wmi_val = _wmi_get_brightness()
        if wmi_val is not None:
            out.append({
                "id": "Internal Display #1",
                "name": "Internal Laptop Display",
                "brightness": wmi_val,
                "ddc": False,
                "method": "wmi",
            })

    return out


def set_brightness(level: int, remember: bool = True) -> dict:
    """Set brightness 0..100 on all DDC/WMI monitors. Returns report.

    Remembers previous values in on-disk journal so `paperscreen off` restores them.
    Keys monitors uniquely by compound ID so identical models do not collide.
    """
    level = max(0, min(100, int(level)))
    report = {"requested": level, "set": [], "failed": [], "skipped": []}
    journal = signals.load()
    previous_by_key: dict = journal.get("backlight_previous", {})
    handles = []

    try:
        opened = winlib.get_physical_monitors()
        for i, (handle, name) in enumerate(opened):
            handles.append(handle)
            key = f"{name} #{i+1}"
            prev = winlib.ddc_get_brightness(handle)
            if prev is None:
                report["failed"].append({"name": key, "reason": "read brightness failed"})
                continue
            if winlib.ddc_set_brightness(handle, level):
                report["set"].append({"name": key, "from": prev, "to": level, "method": "ddc"})
                if remember and key not in previous_by_key:
                    previous_by_key[key] = prev
            else:
                report["failed"].append({"name": key, "reason": "SetMonitorBrightness failed"})
    except PaperAPIError as exc:
        logger.warn(f"DDC set_brightness error: {exc}")
    finally:
        if handles:
            winlib.destroy_physical_monitors(handles)

    # WMI fallback if no DDC monitors were set
    if not report["set"]:
        wmi_prev = _wmi_get_brightness()
        if wmi_prev is not None:
            wmi_key = "Internal Display #1"
            if _wmi_set_brightness(level):
                report["set"].append({"name": wmi_key, "from": wmi_prev, "to": level, "method": "wmi"})
                if remember and wmi_key not in previous_by_key:
                    previous_by_key[wmi_key] = wmi_prev
            else:
                report["failed"].append({"name": wmi_key, "reason": "WMI set brightness failed"})

    if remember and report["set"]:
        signals.update(backlight_previous=previous_by_key, backlight_level=level)

    return report


def restore() -> dict:
    """Restore brightness from the on-disk journal (best-effort)."""
    report = {"restored": [], "failed": []}
    journal = signals.load()
    previous_by_key: dict = journal.get("backlight_previous", {})
    if not previous_by_key:
        return report

    handles = []
    try:
        opened = winlib.get_physical_monitors()
        handles = [handle for handle, _ in opened]

        for i, (handle, name) in enumerate(opened):
            key = f"{name} #{i+1}"
            # Also fallback to matching bare name for backwards compatibility
            prev = previous_by_key.get(key)
            if prev is None:
                prev = previous_by_key.get(name)

            if isinstance(prev, int):
                if winlib.ddc_set_brightness(handle, prev):
                    report["restored"].append({"name": key, "to": prev, "method": "ddc"})
                else:
                    report["failed"].append({"name": key, "reason": "DDC set failed"})
    except PaperAPIError as exc:
        logger.warn(f"DDC restore error: {exc}")
    finally:
        if handles:
            try:
                winlib.destroy_physical_monitors(handles)
            except PaperAPIError:
                pass

    # Restore WMI internal display if present in journal
    wmi_key = "Internal Display #1"
    if wmi_key in previous_by_key:
        target = previous_by_key[wmi_key]
        if isinstance(target, int) and _wmi_set_brightness(target):
            report["restored"].append({"name": wmi_key, "to": target, "method": "wmi"})
        else:
            report["failed"].append({"name": wmi_key, "reason": "WMI restore failed"})

    journal.pop("backlight_previous", None)
    journal.pop("backlight_level", None)
    signals.save(journal)
    return report
