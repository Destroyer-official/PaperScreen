"""Backlight control via DDC/CI with graceful WMI fallback for laptops.

Chain: DDC/CI (dxva2) -> WMI (internal laptop panels) -> no-op with warning.
Never raises for unavailable hardware; reports what it did.
Supports multi-monitor setups with identical display names.
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import List, Optional

from . import logger, signals, winlib
from .winlib import PaperAPIError

_BACKLIGHT_LOCK = threading.Lock()
_LAST_SET_TIME = 0.0
_LAST_SET_LEVEL = None


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

def _extract_original(val) -> Optional[int]:
    """Extract integer brightness from either legacy int or structured dict."""
    if isinstance(val, int):
        return val
    if isinstance(val, dict):
        orig = val.get("original")
        if isinstance(orig, int):
            return orig
    return None


def list_monitors() -> List[dict]:
    """Info dict per monitor (current brightness if readable)."""
    out = []
    try:
        with winlib.open_physical_monitors() as opened:
            for i, (handle, name) in enumerate(opened):
                cur = winlib.ddc_get_brightness(handle)
                if i > 0:
                    time.sleep(0.05)  # I2C recovery between monitors
                out.append({
                    "id": f"{name} #{i+1}",
                    "name": name,
                    "brightness": cur,
                    "ddc": cur is not None,
                    "method": "ddc" if cur is not None else "unsupported",
                })
    except PaperAPIError as exc:
        logger.warn(f"Failed to enumerate DDC monitors: {exc}")

    # Check for internal laptop display independently
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


def set_brightness(level: int, remember: bool = True, rollback_on_failure: bool = False) -> dict:
    """Set brightness 0..100 on all DDC/WMI monitors. Returns report.

    Remembers previous values in on-disk journal so `paperscreen off` restores them.
    Keys monitors uniquely by compound ID so identical models do not collide.
    If rollback_on_failure is True, rolls back already changed monitors if a subsequent monitor fails.
    """
    global _LAST_SET_TIME, _LAST_SET_LEVEL
    level = max(0, min(100, int(level)))
    report = {"requested": level, "set": [], "failed": [], "skipped": [], "rolled_back": False}

    with _BACKLIGHT_LOCK:
        now = time.monotonic()
        # Trailing-edge deduplication: skip redundant write if same level requested within 150ms
        if level == _LAST_SET_LEVEL and (now - _LAST_SET_TIME) < 0.15:
            report["skipped"].append({"reason": "debounced"})
            return report

        _LAST_SET_TIME = now
        _LAST_SET_LEVEL = level

        journal = signals.load()
        previous_by_key: dict = dict(journal.get("backlight_previous", {}))

        try:
            with winlib.open_physical_monitors() as opened:
                for i, item in enumerate(opened):
                    handle, name = item[0], item[1]
                    dev_id = getattr(item, "device_id", "")
                    key = f"{name} #{i+1}"
                    prev = winlib.ddc_get_brightness(handle)
                    time.sleep(0.05)  # I2C recovery window between read and write
                    if prev is None:
                        report["failed"].append({"name": key, "reason": "read brightness failed"})
                        continue
                    if prev == level:
                        report["skipped"].append({"name": key, "reason": "already_at_level", "brightness": level})
                        if remember and key not in previous_by_key:
                            previous_by_key[key] = {
                                "original": prev,
                                "status": "active",
                                "set_level": level,
                                "device_id": dev_id,
                                "name": name,
                            }
                        continue
                    if winlib.ddc_set_brightness(handle, level):
                        time.sleep(0.15)  # DDC write settling time for monitor microcontroller
                        report["set"].append({"name": key, "from": prev, "to": level, "method": "ddc"})
                        if remember and key not in previous_by_key:
                            previous_by_key[key] = {
                                "original": prev,
                                "status": "active",
                                "set_level": level,
                                "device_id": dev_id,
                                "name": name,
                            }
                    else:
                        report["failed"].append({"name": key, "reason": "SetMonitorBrightness failed"})
                        if rollback_on_failure:
                            break
        except PaperAPIError as exc:
            logger.warn(f"DDC set_brightness error: {exc}")

    # Rollback DDC changes if failure occurred and rollback requested
    if rollback_on_failure and report["failed"] and report["set"]:
        logger.warn("Activation failure detected; rolling back already modified monitors")
        try:
            with winlib.open_physical_monitors() as opened:
                for i, (handle, name) in enumerate(opened):
                    key = f"{name} #{i+1}"
                    for s in report["set"]:
                        if s["name"] == key:
                            winlib.ddc_set_brightness(handle, s["from"])
                            previous_by_key.pop(key, None)
        except Exception as exc:
            logger.error(f"Rollback error: {exc}")
        report["rolled_back"] = True
        report["set"] = []
        return report

    # Independent WMI internal laptop panel adjustment
    wmi_prev = _wmi_get_brightness()
    if wmi_prev is not None:
        wmi_key = "Internal Display #1"
        if wmi_prev == level:
            report["skipped"].append({"name": wmi_key, "reason": "already_at_level", "brightness": level})
            if remember and wmi_key not in previous_by_key:
                previous_by_key[wmi_key] = {"original": wmi_prev, "status": "active", "set_level": level}
        elif _wmi_set_brightness(level):
            report["set"].append({"name": wmi_key, "from": wmi_prev, "to": level, "method": "wmi"})
            if remember and wmi_key not in previous_by_key:
                previous_by_key[wmi_key] = {"original": wmi_prev, "status": "active", "set_level": level}
        else:
            report["failed"].append({"name": wmi_key, "reason": "WMI set brightness failed"})

    if remember and report["set"]:
        signals.update(backlight_previous=previous_by_key, backlight_level=level)

    return report


def restore() -> dict:
    """Restore brightness from the on-disk journal transactional record.
    
    Retains entries for any monitors that fail to restore so subsequent
    retries or `paperscreen doctor --repair` can restore them.
    """
    report = {"restored": [], "failed": [], "pending": []}
    journal = signals.load()
    previous_by_key: dict = dict(journal.get("backlight_previous", {}))
    if not previous_by_key:
        return report

    restored_keys = set()

    try:
        with winlib.open_physical_monitors() as opened:
            for i, item in enumerate(opened):
                handle, name = item[0], item[1]
                dev_id = getattr(item, "device_id", "")
                key = f"{name} #{i+1}"

                # 1. Exact compound key match (e.g. "Dell U2720Q #1")
                entry = previous_by_key.get(key)
                matched_key = key

                # 2. Match by hardware device_id if enumeration order or port shifted
                if entry is None and dev_id:
                    for k, v in list(previous_by_key.items()):
                        if isinstance(v, dict) and v.get("device_id") == dev_id and k not in restored_keys:
                            entry = v
                            matched_key = k
                            break

                # 3. Match by model name or topology-shifted key (e.g. was #2, now enumerated as #1)
                if entry is None:
                    if name in previous_by_key and name not in restored_keys:
                        entry = previous_by_key[name]
                        matched_key = name
                    else:
                        for k, v in list(previous_by_key.items()):
                            if (k.startswith(f"{name} #") or k == name) and k not in restored_keys:
                                entry = v
                                matched_key = k
                                break

                prev_val = _extract_original(entry)
                if prev_val is not None:
                    cur = winlib.ddc_get_brightness(handle)
                    if cur == prev_val:
                        report["restored"].append({"name": matched_key, "to": prev_val, "method": "ddc", "skipped": "already_at_level"})
                        restored_keys.add(matched_key)
                        continue
                    if winlib.ddc_set_brightness(handle, prev_val):
                        time.sleep(0.15)  # DDC write settling time
                        report["restored"].append({"name": matched_key, "to": prev_val, "method": "ddc"})
                        restored_keys.add(matched_key)
                    else:
                        report["failed"].append({"name": matched_key, "reason": "DDC set failed"})
    except PaperAPIError as exc:
        logger.warn(f"DDC restore error: {exc}")

    # Restore WMI internal display if present in journal
    wmi_key = "Internal Display #1"
    if wmi_key in previous_by_key:
        wmi_val = _extract_original(previous_by_key[wmi_key])
        if wmi_val is not None:
            if _wmi_set_brightness(wmi_val):
                report["restored"].append({"name": wmi_key, "to": wmi_val, "method": "wmi"})
                restored_keys.add(wmi_key)
            else:
                report["failed"].append({"name": wmi_key, "reason": "WMI restore failed"})

    # Transactional journal update: only remove successfully restored monitors
    for rk in restored_keys:
        previous_by_key.pop(rk, None)

    report["pending"] = list(previous_by_key.keys())

    if not previous_by_key:
        signals.update(backlight_previous=None, backlight_level=None)
    else:
        signals.update(backlight_previous=previous_by_key)

    return report


def repair() -> dict:
    """Scan journal for unrestored/pending backlight records and attempt restoration."""
    return restore()


__all__ = [
    "MonitorBrightness",
    "list_monitors",
    "set_brightness",
    "restore",
    "repair",
]
