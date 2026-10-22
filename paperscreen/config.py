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
    "invert_luminance": False,     # invert luminance (dark paper / light text)
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
    "utc_offset_hours": None,       # optional UTC offset override in hours
}


def config_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_DIR_NAME)


def config_path() -> str:
    return os.path.join(config_dir(), CONFIG_NAME)


def _safe_int(val, default: int, lo: int | None = None, hi: int | None = None) -> int:
    try:
        if val is None:
            return default
        res = int(val)
        if lo is not None:
            res = max(lo, res)
        if hi is not None:
            res = min(hi, res)
        return res
    except (ValueError, TypeError):
        return default


def _safe_float(val, default: float, lo: float | None = None, hi: float | None = None) -> float:
    try:
        if val is None:
            return default
        res = float(val)
        if lo is not None:
            res = max(lo, res)
        if hi is not None:
            res = min(hi, res)
        return res
    except (ValueError, TypeError):
        return default


def _validate(cfg: dict) -> dict:
    out = dict(DEFAULTS)
    if not isinstance(cfg, dict):
        return out
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
    p_str = str(out.get("preset", "paper"))
    out["preset"] = p_str if p_str in VALID_PRESETS else "paper"
    out["kelvin"] = _safe_int(out.get("kelvin"), DEFAULTS["kelvin"], 1000, 15000)
    out["desaturation"] = _safe_float(out.get("desaturation"), DEFAULTS["desaturation"], 0.0, 1.0)
    out["black_floor"] = _safe_float(out.get("black_floor"), DEFAULTS["black_floor"], 0.0, 0.5)
    out["white_ceiling"] = _safe_float(out.get("white_ceiling"), DEFAULTS["white_ceiling"], 0.2, 1.0)
    out["contrast"] = _safe_float(out.get("contrast"), DEFAULTS["contrast"], 0.2, 2.0)
    out["backlight_day"] = _safe_int(out.get("backlight_day"), DEFAULTS["backlight_day"], 0, 100)
    out["backlight_night"] = _safe_int(out.get("backlight_night"), DEFAULTS["backlight_night"], 0, 100)
    out["night_start_hour"] = _safe_int(out.get("night_start_hour"), DEFAULTS["night_start_hour"], 0, 23)
    out["night_end_hour"] = _safe_int(out.get("night_end_hour"), DEFAULTS["night_end_hour"], 0, 23)
    out["invert_luminance"] = bool(out.get("invert_luminance", False))
    out["grayscale_smoothing"] = bool(out.get("grayscale_smoothing"))
    out["restore_backlight_on_exit"] = bool(out.get("restore_backlight_on_exit", True))
    out["breaks_enabled"] = bool(out.get("breaks_enabled", True))
    out["break_interval_minutes"] = _safe_int(out.get("break_interval_minutes"), DEFAULTS["break_interval_minutes"], 1, 60)
    out["break_duration_seconds"] = _safe_int(out.get("break_duration_seconds"), DEFAULTS["break_duration_seconds"], 5, 120)
    out["smooth_transition_ms"] = _safe_int(out.get("smooth_transition_ms"), DEFAULTS["smooth_transition_ms"], 0, 10000)
    out["hotkey_toggle"] = bool(out.get("hotkey_toggle", True))
    out["night_dim_matrix"] = bool(out.get("night_dim_matrix", False))
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
    if out.get("utc_offset_hours") is not None:
        try:
            out["utc_offset_hours"] = min(14.0, max(-14.0, float(out["utc_offset_hours"])))
        except (ValueError, TypeError):
            out["utc_offset_hours"] = None
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
    except (OSError, ValueError, TypeError):
        return dict(DEFAULTS)


def save(cfg: dict) -> str:
    os.makedirs(config_dir(), exist_ok=True)
    clean = _validate(cfg)
    target = config_path()
    tmp = target + f".{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2)
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

