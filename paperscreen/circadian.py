"""Astronomical Solar Circadian Engine (pure Python, zero dependencies).

Computes exact astronomical sunrise, sunset, and solar noon using NOAA's
solar geometry algorithms (Spencer / Meeus formulas). Allows PaperScreen to
automatically synchronize color temperature and paper modes with the true
sunlight cycle at the user's location.
"""

from __future__ import annotations

import datetime
import math
from typing import Dict, Optional, Tuple


def calculate_solar_times(
    lat: float,
    lon: float,
    date: Optional[datetime.date] = None,
    utc_offset_hours: Optional[float] = None,
) -> Dict[str, Optional[datetime.time] | float | bool]:
    """Calculate astronomical sunrise, sunset, solar noon, and day length."""
    if date is None:
        date = datetime.date.today()
    if utc_offset_hours is None:
        try:
            offset = datetime.datetime.now().astimezone().utcoffset()
            utc_offset_hours = offset.total_seconds() / 3600.0 if offset else 0.0
        except Exception:
            utc_offset_hours = 0.0

    day_of_year = date.timetuple().tm_yday

    # Fractional year in radians
    gamma = 2.0 * math.pi / 365.0 * (day_of_year - 1 + (12.0 - 12.0) / 24.0)

    # Equation of time in minutes
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2.0 * gamma)
        - 0.040849 * math.sin(2.0 * gamma)
    )

    # Solar declination angle in radians
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2.0 * gamma)
        + 0.000907 * math.sin(2.0 * gamma)
        - 0.002697 * math.cos(3.0 * gamma)
        + 0.00148 * math.sin(3.0 * gamma)
    )

    lat_rad = math.radians(lat)
    zenith = math.radians(90.833)  # Official solar zenith (refraction corrected)

    cos_ha = (math.cos(zenith) / (math.cos(lat_rad) * math.cos(decl))) - (
        math.tan(lat_rad) * math.tan(decl)
    )

    # Handle extreme latitudes (polar day / night)
    if cos_ha > 1.0:
        return {
            "sunrise": None,
            "sunset": None,
            "solar_noon": None,
            "day_length_hours": 0.0,
            "polar_night": True,
            "polar_day": False,
        }
    elif cos_ha < -1.0:
        return {
            "sunrise": None,
            "sunset": None,
            "solar_noon": None,
            "day_length_hours": 24.0,
            "polar_night": False,
            "polar_day": True,
        }

    ha = math.degrees(math.acos(cos_ha))

    # UTC sunrise and sunset in minutes from midnight
    sunrise_utc_min = 720.0 - 4.0 * (lon + ha) - eqtime
    sunset_utc_min = 720.0 - 4.0 * (lon - ha) - eqtime
    solar_noon_utc_min = 720.0 - 4.0 * lon - eqtime

    # Convert to local time minutes
    sunrise_local_min = (sunrise_utc_min + utc_offset_hours * 60.0) % 1440.0
    sunset_local_min = (sunset_utc_min + utc_offset_hours * 60.0) % 1440.0
    solar_noon_local_min = (solar_noon_utc_min + utc_offset_hours * 60.0) % 1440.0

    sr_h, sr_m = int(sunrise_local_min // 60), int(sunrise_local_min % 60)
    ss_h, ss_m = int(sunset_local_min // 60), int(sunset_local_min % 60)
    sn_h, sn_m = int(solar_noon_local_min // 60), int(solar_noon_local_min % 60)

    return {
        "sunrise": datetime.time(sr_h, sr_m),
        "sunset": datetime.time(ss_h, ss_m),
        "solar_noon": datetime.time(sn_h, sn_m),
        "day_length_hours": round((2.0 * ha * 4.0) / 60.0, 2),
        "polar_night": False,
        "polar_day": False,
    }


def get_solar_schedule(
    cfg: Optional[dict] = None,
    date: Optional[datetime.date] = None,
    utc_offset_hours: Optional[float] = None,
) -> Dict:
    """Retrieve solar schedule based on user config and the system's civil timezone rules."""
    from . import config

    if cfg is None:
        cfg = config.load()

    lat = cfg.get("latitude")
    lon = cfg.get("longitude")

    is_approx = False
    approx_note = ""

    if utc_offset_hours is None and cfg.get("utc_offset_hours") is not None:
        try:
            utc_offset_hours = float(cfg["utc_offset_hours"])
        except (ValueError, TypeError):
            utc_offset_hours = None

    if utc_offset_hours is None:
        # Determine civil timezone from system
        try:
            ref_date = date or datetime.date.today()
            local_dt = datetime.datetime(ref_date.year, ref_date.month, ref_date.day, 12, 0).astimezone()
            sys_offset = local_dt.utcoffset().total_seconds() / 3600.0 if local_dt.utcoffset() else 0.0
        except Exception:
            sys_offset = 0.0

        if lat is not None and lon is not None:
            # Check if machine timezone is compatible with user's configured location
            try:
                solar_lon_offset = float(lon) / 15.0
                if abs(sys_offset - solar_lon_offset) <= 2.5:
                    # Machine is within the civil timezone of the coordinates; use machine's exact civil rules (including DST)
                    utc_offset_hours = sys_offset
                else:
                    # Coordinates are remote from current machine (e.g. testing or roaming without clock update)
                    utc_offset_hours = round(solar_lon_offset)
            except Exception:
                utc_offset_hours = sys_offset
        else:
            utc_offset_hours = sys_offset

    if lat is None or lon is None:
        # Fallback approximation: estimate longitude from civil timezone and use temperate 38° lat
        is_approx = True
        approx_note = (
            "Approximation based on system civil timezone and temperate latitude (38°). "
            "Set latitude and longitude in configuration for true location-specific solar timing."
        )
        lon = utc_offset_hours * 15.0
        lat = 38.0
    else:
        # Validate coordinates
        try:
            lat = max(-90.0, min(90.0, float(lat)))
            lon = max(-180.0, min(180.0, float(lon)))
        except (ValueError, TypeError):
            is_approx = True
            approx_note = "Invalid coordinates; using temperate fallback."
            lat = 38.0
            lon = utc_offset_hours * 15.0

    res = calculate_solar_times(lat, lon, date=date, utc_offset_hours=utc_offset_hours)
    res["is_approximation"] = is_approx
    if approx_note:
        res["note"] = approx_note
    return res


def is_solar_night(now: Optional[datetime.datetime] = None, cfg: Optional[dict] = None) -> bool:
    """Check if current time is outside daylight hours (before sunrise or after sunset)."""
    if now is None:
        now = datetime.datetime.now().astimezone()

    tz_offset = None
    if now.tzinfo is not None and now.utcoffset() is not None:
        tz_offset = now.utcoffset().total_seconds() / 3600.0

    info = get_solar_schedule(cfg, date=now.date(), utc_offset_hours=tz_offset)
    if info.get("polar_night"):
        return True
    if info.get("polar_day"):
        return False

    sr: datetime.time = info["sunrise"]  # type: ignore
    ss: datetime.time = info["sunset"]   # type: ignore

    cur_time = now.time()
    return cur_time < sr or cur_time >= ss


__all__ = [
    "calculate_solar_times",
    "get_solar_schedule",
    "is_solar_night",
]

