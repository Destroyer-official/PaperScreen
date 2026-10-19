"""Optional ClearType control: switch font smoothing to grayscale while
paper mode is active to avoid subpixel color fringing on tinted output.

Uses SystemParametersInfo (SPI_GET/SETFONTSMOOTHINGTYPE), fully reversible.
Some apps require a re-render to pick the change up; logoff is NOT required
for most modern apps (Win10/11 re-rasterize on WM_SETTINGCHANGE broadcast).
"""

from __future__ import annotations

from typing import Optional
from . import signals, winlib

_saved_state: list = []


def enable_grayscale_smoothing() -> dict:
    """Switch to standard (grayscale) font smoothing. Reversible across processes."""
    current = winlib.get_font_smoothing_type()
    if current is None:
        return {"ok": False, "reason": "SPI_GETFONTSMOOTHINGTYPE failed"}
    if current == winlib.FE_FONTSMOOTHINGSTANDARD:
        return {"ok": True, "changed": False, "previous": current}

    # Persist previous state cross-process before applying change
    j = signals.load()
    if "cleartype_previous" not in j:
        signals.update(cleartype_previous=current)

    if not _saved_state:
        _saved_state.append(current)

    ok = winlib.set_font_smoothing_type(winlib.FE_FONTSMOOTHINGSTANDARD)
    if not ok:
        signals.update(cleartype_previous=None)
        if _saved_state:
            _saved_state.pop()
        return {"ok": False, "changed": False, "reason": "SPI_SETFONTSMOOTHINGTYPE failed"}

    return {"ok": True, "changed": True, "previous": current}


def restore_previous() -> dict:
    """Restore the smoothing mode saved by enable_grayscale_smoothing()."""
    j = signals.load()
    prev = j.get("cleartype_previous")
    if prev is None and _saved_state:
        prev = _saved_state[-1]

    if prev is None:
        return {"ok": True, "changed": False}

    ok = winlib.set_font_smoothing_type(prev)
    if ok:
        signals.update(cleartype_previous=None)
        if _saved_state:
            _saved_state.pop()
        return {"ok": True, "changed": True, "restored": prev}
    return {"ok": False, "changed": False, "reason": "SPI_SETFONTSMOOTHINGTYPE restore failed"}


def status() -> dict:
    v = winlib.get_font_smoothing_type()
    if v is None:
        return {"ok": False}
    return {
        "ok": True,
        "value": v,
        "mode": "grayscale" if v == winlib.FE_FONTSMOOTHINGSTANDARD else "cleartype",
    }


__all__ = [
    "enable_grayscale_smoothing",
    "restore_previous",
    "status",
]
