"""Raw Win32 API bindings for PaperScreen (ctypes only, no dependencies).

All kernel32/user32/gdi32/dxva2/Magnification interop lives here. Import this
module only on Windows. Functions raise PaperAPIError with GetLastError info.
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
from ctypes import wintypes
from typing import Iterator, List, Optional, Tuple

IS_WINDOWS = sys.platform == "win32"


class PaperAPIError(RuntimeError):
    """Raised when a Win32 call fails; message includes GetLastError."""


def _last_error(msg: str) -> PaperAPIError:
    code = ctypes.GetLastError()
    return PaperAPIError(f"{msg} (Win32 error {code})")


# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------

class MAGCOLOREFFECT(ctypes.Structure):
    _fields_ = [("transform", (ctypes.c_float * 5) * 5)]


class PHYSICAL_MONITOR(ctypes.Structure):
    _fields_ = [
        ("hPhysicalMonitor", wintypes.HANDLE),
        ("szPhysicalMonitorDescription", wintypes.WCHAR * 128),
    ]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]

# Backwards compatibility alias
DISPLAY_DEVICE = DISPLAY_DEVICEW


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


# ---------------------------------------------------------------------------
# DLL loading (lazy so import on non-Windows doesn't explode)
# ---------------------------------------------------------------------------

_user32: Optional[ctypes.WinDLL] = None
_dxva2: Optional[ctypes.WinDLL] = None
_mag: Optional[ctypes.WinDLL] = None
_gdi32: Optional[ctypes.WinDLL] = None


def user32() -> ctypes.WinDLL:
    global _user32
    if _user32 is None:
        _user32 = ctypes.WinDLL("user32", use_last_error=True)
    return _user32


def gdi32() -> ctypes.WinDLL:
    global _gdi32
    if _gdi32 is None:
        _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    return _gdi32


def dxva2() -> ctypes.WinDLL:
    global _dxva2
    if _dxva2 is None:
        _dxva2 = ctypes.WinDLL("dxva2", use_last_error=True)
    return _dxva2


def magnification() -> ctypes.WinDLL:
    global _mag
    if _mag is None:
        _mag = ctypes.WinDLL("Magnification", use_last_error=True)
    return _mag


_shell32: Optional[ctypes.WinDLL] = None


def shell32() -> ctypes.WinDLL:
    global _shell32
    if _shell32 is None:
        _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    return _shell32


# ---------------------------------------------------------------------------
# Magnification API (color engine)
# ---------------------------------------------------------------------------

_mag_initialized = False


def mag_initialize() -> bool:
    """MagInitialize(); idempotent."""
    global _mag_initialized
    dll = magnification()
    dll.MagInitialize.restype = wintypes.BOOL
    ok = bool(dll.MagInitialize())
    if ok:
        _mag_initialized = True
    return ok


def mag_uninitialize() -> bool:
    """MagUninitialize(); idempotent."""
    global _mag_initialized
    if not _mag_initialized:
        return True
    dll = magnification()
    dll.MagUninitialize.restype = wintypes.BOOL
    ok = bool(dll.MagUninitialize())
    _mag_initialized = not ok
    return ok


def _matrix_to_struct(matrix) -> MAGCOLOREFFECT:
    if len(matrix) != 5 or any(len(row) != 5 for row in matrix):
        raise PaperAPIError("matrix must be 5x5")
    eff = MAGCOLOREFFECT()
    for r in range(5):
        for c in range(5):
            eff.transform[r][c] = matrix[r][c]
    return eff


def mag_set_color_effect(matrix) -> bool:
    """MagSetFullscreenColorEffect with a 5x5 python matrix."""
    dll = magnification()
    dll.MagSetFullscreenColorEffect.restype = wintypes.BOOL
    dll.MagSetFullscreenColorEffect.argtypes = [ctypes.POINTER(MAGCOLOREFFECT)]
    if not _mag_initialized and not mag_initialize():
        raise _last_error("MagInitialize failed")
    eff = _matrix_to_struct(matrix)
    ok = bool(dll.MagSetFullscreenColorEffect(ctypes.byref(eff)))
    if not ok:
        raise _last_error("MagSetFullscreenColorEffect failed")
    return True


def mag_get_color_effect():
    """MagGetFullscreenColorEffect -> 5x5 python matrix (or None if fail)."""
    dll = magnification()
    try:
        dll.MagGetFullscreenColorEffect.argtypes = [ctypes.POINTER(MAGCOLOREFFECT)]
        dll.MagGetFullscreenColorEffect.restype = wintypes.BOOL
    except AttributeError:
        return None
    if not _mag_initialized and not mag_initialize():
        return None
    eff = MAGCOLOREFFECT()
    ok = bool(dll.MagGetFullscreenColorEffect(ctypes.byref(eff)))
    if not ok:
        return None
    return [[eff.transform[r][c] for c in range(5)] for r in range(5)]


# ---------------------------------------------------------------------------
# Physical monitors / DDC-CI (dxva2)
# ---------------------------------------------------------------------------

MONITOR_DEFAULTTOPRIMARY = 1
MONITOR_DEFAULTTONEAREST = 2


def enum_monitor_handles() -> List[Tuple[wintypes.HMONITOR, wintypes.HDC, wintypes.LPRECT]]:
    """Return list of (hMonitor, hdcMonitor, lprect) for all monitors."""
    result: List[Tuple[wintypes.HMONITOR, wintypes.HDC, wintypes.LPRECT]] = []
    EnumProc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, wintypes.LPRECT, wintypes.LPARAM
    )

    def _cb(hMonitor, hdcMonitor, lprect, lParam):
        result.append((hMonitor, hdcMonitor, lprect))
        return True

    cb = EnumProc(_cb)
    if not user32().EnumDisplayMonitors(0, None, cb, 0):
        raise _last_error("EnumDisplayMonitors failed")
    return result


def get_physical_monitors() -> List[Tuple[int, str]]:
    """Open physical monitors via DDC. Returns [(handle, description)].

    Handles must be released via destroy_physical_monitors().
    Guarantees that already-opened handles are destroyed if enumeration fails.
    """
    out: List[Tuple[int, str]] = []
    try:
        for hmon, _hdc, _rect in enum_monitor_handles():
            count = wintypes.DWORD()
            dll = dxva2()
            dll.GetNumberOfPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL
            dll.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [
                wintypes.HMONITOR, ctypes.POINTER(wintypes.DWORD)
            ]
            if not dll.GetNumberOfPhysicalMonitorsFromHMONITOR(hmon, ctypes.byref(count)):
                continue
            if count.value == 0:
                continue
            arr = (PHYSICAL_MONITOR * count.value)()
            dll.GetPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL
            dll.GetPhysicalMonitorsFromHMONITOR.argtypes = [
                wintypes.HMONITOR, wintypes.DWORD, ctypes.POINTER(PHYSICAL_MONITOR)
            ]
            if not dll.GetPhysicalMonitorsFromHMONITOR(hmon, count.value, arr):
                continue
            for i in range(count.value):
                out.append((arr[i].hPhysicalMonitor, arr[i].szPhysicalMonitorDescription or "?"))
        return out
    except Exception:
        if out:
            destroy_physical_monitors([h for h, _ in out])
        raise


def destroy_physical_monitors(handles: List[int]) -> bool:
    """Safely destroy physical monitor handles. Returns True if successful."""
    if not handles:
        return True
    try:
        dll = dxva2()
        arr = (PHYSICAL_MONITOR * len(handles))()
        for i, h in enumerate(handles):
            arr[i].hPhysicalMonitor = h
        dll.DestroyPhysicalMonitors.restype = wintypes.BOOL
        dll.DestroyPhysicalMonitors.argtypes = [wintypes.DWORD, ctypes.POINTER(PHYSICAL_MONITOR)]
        return bool(dll.DestroyPhysicalMonitors(len(handles), arr))
    except Exception:
        return False


@contextlib.contextmanager
def open_physical_monitors() -> Iterator[List[Tuple[int, str]]]:
    """Context manager for opened physical monitors ensuring handles are destroyed on exit."""
    monitors: List[Tuple[int, str]] = []
    try:
        monitors = get_physical_monitors()
        yield monitors
    finally:
        if monitors:
            destroy_physical_monitors([h for h, _ in monitors])


def ddc_get_raw_brightness(handle: int) -> Optional[Tuple[int, int, int]]:
    """GetMonitorBrightness(handle) -> (minimum, current, maximum) or None on failure."""
    dll = dxva2()
    dll.GetMonitorBrightness.restype = wintypes.BOOL
    dll.GetMonitorBrightness.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
    ]
    minimum = wintypes.DWORD()
    current = wintypes.DWORD()
    maximum = wintypes.DWORD()
    if not dll.GetMonitorBrightness(handle, ctypes.byref(minimum), ctypes.byref(current), ctypes.byref(maximum)):
        return None
    return (minimum.value, current.value, maximum.value)


def ddc_get_brightness(handle: int) -> Optional[int]:
    """GetMonitorBrightness(handle) -> current percentage (0..100) or None on failure."""
    raw = ddc_get_raw_brightness(handle)
    if raw is None:
        return None
    lo, cur, hi = raw
    if hi <= lo:
        return max(0, min(100, cur))
    return int(round((cur - lo) * 100.0 / (hi - lo)))


def ddc_set_brightness(handle: int, level: int) -> bool:
    """SetMonitorBrightness(handle, level 0..100) mapped onto the monitor's native range."""
    level = max(0, min(100, int(level)))
    raw = ddc_get_raw_brightness(handle)
    if raw is not None:
        lo, _cur, hi = raw
        if hi > lo:
            target = int(round(lo + (level / 100.0) * (hi - lo)))
            device_val = max(lo, min(hi, target))
        else:
            device_val = level
    else:
        device_val = level

    dll = dxva2()
    dll.SetMonitorBrightness.restype = wintypes.BOOL
    dll.SetMonitorBrightness.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    ok = bool(dll.SetMonitorBrightness(handle, wintypes.DWORD(device_val)))
    return ok


def ddc_get_contrast(handle: int) -> Optional[int]:
    dll = dxva2()
    try:
        dll.GetMonitorContrast.restype = wintypes.BOOL
        dll.GetMonitorContrast.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
        ]
    except AttributeError:
        return None
    minimum = wintypes.DWORD()
    current = wintypes.DWORD()
    maximum = wintypes.DWORD()
    if not dll.GetMonitorContrast(handle, ctypes.byref(minimum), ctypes.byref(current), ctypes.byref(maximum)):
        return None
    lo, hi, cur = minimum.value, maximum.value, current.value
    if hi <= lo:
        return cur
    return int(round((cur - lo) * 100.0 / (hi - lo)))


# ---------------------------------------------------------------------------
# SystemParametersInfo helpers (ClearType / font smoothing)
# ---------------------------------------------------------------------------

SPI_GETFONTSMOOTHINGTYPE = 0x200A
SPI_SETFONTSMOOTHINGTYPE = 0x200B
FE_FONTSMOOTHINGSTANDARD = 0x0001  # grayscale
FE_FONTSMOOTHINGCLEARTYPE = 0x0002  # RGB subpixel

SPIF_UPDATEINIFILE = 0x0001
SPIF_SENDCHANGE = 0x0002


def get_tick_count_64() -> int:
    """Safe 64-bit millisecond counter that does not wrap after 49.7 days."""
    k32 = ctypes.windll.kernel32
    try:
        k32.GetTickCount64.restype = ctypes.c_ulonglong
        return int(k32.GetTickCount64())
    except AttributeError:
        return int(k32.GetTickCount())


def get_font_smoothing_type() -> Optional[int]:
    """Return FE_FONTSMOOTHING* value or None if the call fails."""
    val = wintypes.UINT()
    ok = user32().SystemParametersInfoW(
        SPI_GETFONTSMOOTHINGTYPE, 0, ctypes.byref(val), 0
    )
    return val.value if ok else None


def set_font_smoothing_type(value: int) -> bool:
    """Set FE_FONTSMOOTHINGSTANDARD / FE_FONTSMOOTHINGCLEARTYPE with system broadcast.

    In the Win32 SystemParametersInfoW ABI for SPI_SETFONTSMOOTHINGTYPE, the 4th parameter pvParam
    is passed by value as a pointer-sized integer (PVOID/ULONG_PTR), NOT as an indirect pointer.
    Passing a pointer reference causes Windows to fail with ERROR_INVALID_PARAMETER (res=0).
    Using ctypes.c_void_p ensures standard pointer-width integer dispatch across 32-bit and 64-bit builds.

    We deliberately omit SPIF_UPDATEINIFILE so the change remains session-bound. If the application
    crashes or the workstation reboots, Windows automatically defaults back to the user's permanent
    registry settings, preventing stuck grayscale font smoothing.
    """
    ok = user32().SystemParametersInfoW(
        SPI_SETFONTSMOOTHINGTYPE, 0, ctypes.c_void_p(int(value)), SPIF_SENDCHANGE
    )
    return bool(ok)


# ---------------------------------------------------------------------------
# Gamma ramp fallback (when Magnification API is unavailable)
# ---------------------------------------------------------------------------

class GAMMA_RAMP(ctypes.Structure):
    _fields_ = [
        ("Red", wintypes.WORD * 256),
        ("Green", wintypes.WORD * 256),
        ("Blue", wintypes.WORD * 256),
    ]


def set_gamma_ramp(gains_rgb: Tuple[float, float, float], lift: float = 0.0) -> bool:
    """SetDeviceGammaRamp on all active monitors. gains 0..1, optional black lift.

    Uses per-monitor Device Contexts via CreateDCW(szDevice) to ensure proper
    multi-monitor hardware isolation rather than writing repeatedly to the primary DC.
    Note: many drivers clamp gamma ramps; used only as a fallback path.
    """
    r_gain, g_gain, b_gain = gains_rgb
    ramp = GAMMA_RAMP()
    for i in range(256):
        liftv = int(lift * 65535 * (1.0 - i / 255.0))
        base = int(65535 * (i / 255.0))
        ramp.Red[i] = max(0, min(65535, int(base * r_gain) + liftv))
        ramp.Green[i] = max(0, min(65535, int(base * g_gain) + liftv))
        ramp.Blue[i] = max(0, min(65535, int(base * b_gain) + liftv))

    ok_any = False
    u32 = user32()
    g32 = gdi32()

    for hmon, _hdc, _rect in enum_monitor_handles():
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        hdc = None
        is_created_dc = False

        if u32.GetMonitorInfoW(hmon, ctypes.byref(mi)) and mi.szDevice:
            dev_name = mi.szDevice
            hdc = g32.CreateDCW(dev_name, dev_name, None, None)
            is_created_dc = bool(hdc)

        if not hdc:
            hdc = u32.GetDC(None)
            is_created_dc = False

        if not hdc:
            continue

        try:
            if g32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp)):
                ok_any = True
        finally:
            if is_created_dc:
                g32.DeleteDC(hdc)
            else:
                u32.ReleaseDC(None, hdc)

    return ok_any


# ---------------------------------------------------------------------------
# Advanced Color / HDR Detection (Windows 10 1709+ / Windows 11 CCD API)
# ---------------------------------------------------------------------------

QDC_ONLY_ACTIVE_PATHS = 0x0002
DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME = 2
DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO = 9


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class DISPLAYCONFIG_PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", wintypes.DWORD),
        ("modeInfoIdx", wintypes.DWORD),
        ("statusFlags", wintypes.DWORD),
    ]


class DISPLAYCONFIG_RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", wintypes.UINT), ("Denominator", wintypes.UINT)]


class DISPLAYCONFIG_PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", wintypes.DWORD),
        ("modeInfoIdx", wintypes.DWORD),
        ("outputTechnology", wintypes.DWORD),
        ("rotation", wintypes.DWORD),
        ("scaling", wintypes.DWORD),
        ("refreshRate", DISPLAYCONFIG_RATIONAL),
        ("scanLineOrdering", wintypes.DWORD),
        ("targetAvailable", wintypes.BOOL),
        ("statusFlags", wintypes.DWORD),
    ]


class DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", DISPLAYCONFIG_PATH_SOURCE_INFO),
        ("targetInfo", DISPLAYCONFIG_PATH_TARGET_INFO),
        ("flags", wintypes.DWORD),
    ]


class DISPLAYCONFIG_DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("size", wintypes.DWORD),
        ("adapterId", LUID),
        ("id", wintypes.DWORD),
    ]


class DISPLAYCONFIG_TARGET_DEVICE_NAME(ctypes.Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("flags", wintypes.DWORD),
        ("outputTechnology", wintypes.DWORD),
        ("edidManufactureId", wintypes.WORD),
        ("edidProductCodeId", wintypes.WORD),
        ("connectorInstance", wintypes.DWORD),
        ("monitorFriendlyDeviceName", wintypes.WCHAR * 64),
        ("monitorDevicePath", wintypes.WCHAR * 128),
    ]


class DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO(ctypes.Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("value", wintypes.DWORD),
        ("colorEncoding", wintypes.DWORD),
        ("bitsPerColorChannel", wintypes.DWORD),
    ]


def get_advanced_color_info() -> List[dict]:
    """Query HDR / Advanced Color state for all active displays.

    Returns a list of dicts with display name, HDR support, and active HDR status.
    """
    if not IS_WINDOWS:
        return []
    u32 = user32()
    if not hasattr(u32, "GetDisplayConfigBufferSizes") or not hasattr(u32, "QueryDisplayConfig"):
        return []
    path_count = wintypes.UINT()
    mode_count = wintypes.UINT()
    res = u32.GetDisplayConfigBufferSizes(
        QDC_ONLY_ACTIVE_PATHS, ctypes.byref(path_count), ctypes.byref(mode_count)
    )
    if res != 0 or path_count.value == 0:
        return []
    paths = (DISPLAYCONFIG_PATH_INFO * path_count.value)()
    modes = (ctypes.c_byte * (mode_count.value * 64))()
    res = u32.QueryDisplayConfig(
        QDC_ONLY_ACTIVE_PATHS,
        ctypes.byref(path_count),
        paths,
        ctypes.byref(mode_count),
        modes,
        None,
    )
    if res != 0:
        return []
    displays = []
    for i in range(path_count.value):
        p = paths[i]
        target_name = DISPLAYCONFIG_TARGET_DEVICE_NAME()
        target_name.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME
        target_name.header.size = ctypes.sizeof(DISPLAYCONFIG_TARGET_DEVICE_NAME)
        target_name.header.adapterId = p.targetInfo.adapterId
        target_name.header.id = p.targetInfo.id
        name_ok = u32.DisplayConfigGetDeviceInfo(ctypes.byref(target_name)) == 0
        m_name = target_name.monitorFriendlyDeviceName if name_ok else f"Display {i+1}"

        color_info = DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO()
        color_info.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO
        color_info.header.size = ctypes.sizeof(DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO)
        color_info.header.adapterId = p.targetInfo.adapterId
        color_info.header.id = p.targetInfo.id
        if u32.DisplayConfigGetDeviceInfo(ctypes.byref(color_info)) == 0:
            val = color_info.value
            displays.append({
                "name": m_name,
                "hdr_supported": bool(val & 0x01),
                "hdr_enabled": bool(val & 0x02),
                "bits_per_channel": color_info.bitsPerColorChannel,
            })
        else:
            displays.append({
                "name": m_name,
                "hdr_supported": False,
                "hdr_enabled": False,
                "bits_per_channel": 8,
            })
    return displays


# ---------------------------------------------------------------------------
# Foreground Window & Fullscreen App Detection
# ---------------------------------------------------------------------------

def is_foreground_fullscreen() -> bool:
    """Check if the currently focused window is covering its display (e.g. game, movie).

    Uses SHQueryUserNotificationState for direct OS-level D3D exclusive fullscreen detection,
    with fallback to per-monitor boundary checking (properly handling multi-monitor topologies).
    """
    if not IS_WINDOWS:
        return False
    try:
        # 1) Direct shell notification state (detects full-screen Direct3D / exclusive games)
        try:
            s32 = shell32()
            if hasattr(s32, "SHQueryUserNotificationState"):
                p_state = wintypes.DWORD()
                res = s32.SHQueryUserNotificationState(ctypes.byref(p_state))
                # QUNS_BUSY = 2, QUNS_RUNNING_D3D_FULL_SCREEN = 3, QUNS_PRESENTATION_MODE = 4
                if res == 0 and p_state.value in (2, 3, 4):
                    return True
        except Exception:
            pass

        # 2) Window geometry check against the monitor hosting the foreground window
        u32 = user32()
        u32.GetForegroundWindow.restype = wintypes.HWND
        u32.GetDesktopWindow.restype = wintypes.HWND
        u32.GetShellWindow.restype = wintypes.HWND
        u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u32.GetWindowRect.restype = wintypes.BOOL

        hwnd = u32.GetForegroundWindow()
        if not hwnd:
            return False
        desktop = u32.GetDesktopWindow()
        shell = u32.GetShellWindow()
        if hwnd in (desktop, shell):
            return False

        rect = wintypes.RECT()
        if not u32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False

        w = rect.right - rect.left
        h = rect.bottom - rect.top

        # Query the specific monitor for this window (MONITOR_DEFAULTTONEAREST = 2)
        if hasattr(u32, "MonitorFromWindow"):
            hmon = u32.MonitorFromWindow(hwnd, 2)
            if hmon:
                mi = MONITORINFOEXW()
                mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
                if u32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                    mw = mi.rcMonitor.right - mi.rcMonitor.left
                    mh = mi.rcMonitor.bottom - mi.rcMonitor.top
                    return w >= mw and h >= mh

        # Fallback to primary screen metrics
        sw = u32.GetSystemMetrics(0)  # SM_CXSCREEN
        sh = u32.GetSystemMetrics(1)  # SM_CYSCREEN
        return w >= sw and h >= sh
    except Exception:
        return False


def get_foreground_process_name() -> str:
    """Return the lowercase executable name of the current foreground window (e.g. 'photoshop.exe')."""
    if not IS_WINDOWS:
        return ""
    try:
        import os
        u32 = user32()
        k32 = ctypes.windll.kernel32
        u32.GetForegroundWindow.restype = wintypes.HWND
        u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u32.GetWindowThreadProcessId.restype = wintypes.DWORD
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL

        hwnd = u32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h_proc = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h_proc:
            return ""
        try:
            buf = (ctypes.c_wchar * 1024)()
            sz = wintypes.DWORD(1024)
            k32.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
            ]
            k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
            if k32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(sz)):
                return os.path.basename(buf.value).lower()
        finally:
            k32.CloseHandle(h_proc)
    except Exception:
        pass
    return ""


def find_tray_window() -> int:
    """Find the HWND of the resident PaperScreen tray hidden window. Returns 0 if not found."""
    if not IS_WINDOWS:
        return 0
    u32 = user32()
    u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    u32.FindWindowW.restype = wintypes.HWND
    hwnd = u32.FindWindowW("PaperScreenTrayClass", "PaperScreen Tray")
    return int(hwnd) if hwnd else 0


def post_tray_command(cmd_id: int) -> bool:
    """Post a WM_COMMAND notification to the resident PaperScreen tray icon window."""
    hwnd = find_tray_window()
    if not hwnd:
        return False
    u32 = user32()
    u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u32.PostMessageW.restype = wintypes.BOOL
    return bool(u32.PostMessageW(hwnd, 0x0111, cmd_id, 0))


__all__ = [
    "IS_WINDOWS",
    "PaperAPIError",
    "MAGCOLOREFFECT",
    "PHYSICAL_MONITOR",
    "DISPLAY_DEVICEW",
    "DISPLAY_DEVICE",
    "MONITORINFOEXW",
    "GAMMA_RAMP",
    "FE_FONTSMOOTHINGSTANDARD",
    "FE_FONTSMOOTHINGCLEARTYPE",
    "get_tick_count_64",
    "mag_initialize",
    "mag_uninitialize",
    "mag_set_color_effect",
    "mag_get_color_effect",
    "enum_monitor_handles",
    "get_physical_monitors",
    "destroy_physical_monitors",
    "open_physical_monitors",
    "ddc_get_raw_brightness",
    "ddc_get_brightness",
    "ddc_set_brightness",
    "get_font_smoothing_type",
    "set_font_smoothing_type",
    "set_gamma_ramp",
    "get_advanced_color_info",
    "is_foreground_fullscreen",
    "get_foreground_process_name",
    "find_tray_window",
    "post_tray_command",
]


