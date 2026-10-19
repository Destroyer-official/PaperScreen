"""Configuration management: JSON file in %APPDATA%/PaperScreen/config.json.

Defaults are conservative; every field validated; round-trip tested.
"""

from __future__ import annotations

import json
import os

APP_DIR_NAME = "PaperScreen"
CONFIG_NAME = "config.json"

DEFAULTS = {
    "preset": "paper",            # paper | sepia | eink | eink_warm | warm_reading | amber_candle | nightpaper | inverted_paper | custom | auto | off
    "kelvin": 4400,
    "desaturation": 0.65,
    "black_floor": 0.10,
    "white_ceiling": 0.90,
    "contrast": 1.04,
    "backlight_day": 60,          # DDC brightness when ambient unknown
    "backlight_night": 30,
    "night_start_hour": 19,       # 24h local time; night preset applied after
    "night_end_hour": 7,
    "grayscale_smoothing": False,  # ClearType -> grayscale while active
    "restore_backlight_on_exit": True,
    "breaks_enabled": True,
    "break_interval_minutes": 20,
    "break_duration_seconds": 20,
    "smooth_transition_ms": 1000,   # matrix transition duration
    "hotkey_toggle": True,          # Ctrl+Alt+P toggles paper mode
    "night_dim_matrix": False,      # dim via matrix at night (PWM-safe)
    "auto_pause_fullscreen": False, # temporarily revert matrix when running fullscreen games/videos
    "excluded_apps": [],            # list of .exe names (e.g. ["photoshop.exe", "figma.exe"]) where paper mode pauses
    "solar_circadian": False,       # calculate true astronomical sunrise/sunset
    "latitude": None,               # optional GPS latitude (e.g. 40.71)
    "longitude": None,              # optional GPS longitude (e.g. -74.00)
}


def config_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_DIR_NAME)


def config_path() -> str:
    return os.path.join(config_dir(), CONFIG_NAME)


def _validate(cfg: dict) -> dict:
    out = dict(DEFAULTS)
    for k, v in cfg.items():
        if k not in DEFAULTS:
            continue  # unknown keys dropped silently (forward compat)
        out[k] = v
    VALID_PRESETS = (
        "paper",
        "sepia",
        "eink",
        "warm_reading",
        "eink_warm",
        "amber_candle",
        "nightpaper",
        "inverted_paper",
        "custom",
        "auto",
        "off",
    )
    out["preset"] = str(out["preset"]) if out["preset"] in VALID_PRESETS else "paper"
    out["kelvin"] = min(15000, max(1000, int(out["kelvin"])))
    out["desaturation"] = min(1.0, max(0.0, float(out["desaturation"])))
    out["black_floor"] = min(0.5, max(0.0, float(out["black_floor"])))
    out["white_ceiling"] = min(1.0, max(0.2, float(out["white_ceiling"])))
    out["contrast"] = min(2.0, max(0.2, float(out["contrast"])))
    out["backlight_day"] = min(100, max(0, int(out["backlight_day"])))
    out["backlight_night"] = min(100, max(0, int(out["backlight_night"])))
    out["night_start_hour"] = min(23, max(0, int(out["night_start_hour"])))
    out["night_end_hour"] = min(23, max(0, int(out["night_end_hour"])))
    out["grayscale_smoothing"] = bool(out["grayscale_smoothing"])
    out["restore_backlight_on_exit"] = bool(out["restore_backlight_on_exit"])
    out["breaks_enabled"] = bool(out["breaks_enabled"])
    out["break_interval_minutes"] = min(60, max(1, int(out["break_interval_minutes"])))
    break_dur = int(out["break_duration_seconds"])
    out["break_duration_seconds"] = min(120, max(5, break_dur))
    out["smooth_transition_ms"] = min(10000, max(0, int(out["smooth_transition_ms"])))
    out["hotkey_toggle"] = bool(out["hotkey_toggle"])
    out["night_dim_matrix"] = bool(out["night_dim_matrix"])
    out["auto_pause_fullscreen"] = bool(out.get("auto_pause_fullscreen", False))
    if isinstance(out.get("excluded_apps"), list):
        out["excluded_apps"] = [str(a).lower().strip() for a in out["excluded_apps"] if str(a).strip()]
    else:
        out["excluded_apps"] = []
    out["solar_circadian"] = bool(out.get("solar_circadian", False))
    if out.get("latitude") is not None:
        try:
            out["latitude"] = min(90.0, max(-90.0, float(out["latitude"])))
        except (ValueError, TypeError):
            out["latitude"] = None
    if out.get("longitude") is not None:
        try:
            out["longitude"] = min(180.0, max(-180.0, float(out["longitude"])))
        except (ValueError, TypeError):
            out["longitude"] = None
    return out


def load() -> dict:
    path = config_path()
    if not os.path.isfile(path):
        return dict(DEFAULTS)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return dict(DEFAULTS)
        return _validate(data)
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save(cfg: dict) -> str:
    os.makedirs(config_dir(), exist_ok=True)
    clean = _validate(cfg)
    target = config_path()
    tmp = target + f".{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2)
        os.replace(tmp, target)
    except Exception:
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise
    return target


def is_night(now=None) -> bool:
    """True if local hour is inside the night window (or outside solar daylight).

    If solar_circadian is enabled, uses astronomical solar times.
    Otherwise compares against night_start_hour and night_end_hour:
      - Default window (e.g. 19 to 7) wraps midnight: True when h >= 19 or h < 7.
      - Non-wrapping window (e.g. 21 to 23): True when 21 <= h < 23.
    """
    import datetime
    cfg = load()
    if now is None:
        now = datetime.datetime.now().astimezone()
    if cfg.get("solar_circadian"):
        try:
            from . import circadian
            return circadian.is_solar_night(now, cfg)
        except Exception:
            pass
    h = now.hour
    start, end = cfg["night_start_hour"], cfg["night_end_hour"]
    if start <= end:
        return start <= h < end
    return h >= start or h < end


__all__ = [
    "DEFAULTS",
    "config_dir",
    "config_path",
    "load",
    "save",
    "is_night",
]

