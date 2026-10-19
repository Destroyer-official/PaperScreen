"""Optional ClearType control: switch font smoothing to grayscale while
paper mode is active to avoid subpixel color fringing on tinted output.

Uses SystemParametersInfo (SPI_GET/SETFONTSMOOTHINGTYPE), fully reversible.
Some apps require a re-render to pick the change up; logoff is NOT required
for most modern apps (Win10/11 re-rasterize on WM_SETTINGCHANGE broadcast).
"""

from __future__ import annotations

from . import winlib

_saved_state: list = []


def enable_grayscale_smoothing() -> dict:
    """Switch to standard (grayscale) font smoothing. Reversible."""
    current = winlib.get_font_smoothing_type()
    if current is None:
        return {"ok": False, "reason": "SPI_GETFONTSMOOTHINGTYPE failed"}
    if current == winlib.FE_FONTSMOOTHINGSTANDARD:
        return {"ok": True, "changed": False, "previous": current}
    if not _saved_state:
        _saved_state.append(current)
    ok = winlib.set_font_smoothing_type(winlib.FE_FONTSMOOTHINGSTANDARD)
    return {"ok": ok, "changed": True, "previous": current}


def restore_previous() -> dict:
    """Restore the smoothing mode saved by enable_grayscale_smoothing()."""
    if not _saved_state:
        return {"ok": True, "changed": False}
    prev = _saved_state.pop()
    ok = winlib.set_font_smoothing_type(prev)
    return {"ok": ok, "changed": True, "restored": prev}


def status() -> dict:
    v = winlib.get_font_smoothing_type()
    if v is None:
        return {"ok": False}
    return {
        "ok": True,
        "value": v,
        "mode": "grayscale" if v == winlib.FE_FONTSMOOTHINGSTANDARD else "cleartype",
    }
