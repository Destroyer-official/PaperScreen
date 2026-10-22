"""Zero-dependency Windows System Tray Icon & Desktop UI for PaperScreen.

Features:
- Pure ctypes Win32 implementation (Shell_NotifyIconW, no third-party GUI dependencies).
- In-memory parchment paper icon (no external .ico file required).
- Dynamic right-click context menu (presets, backlight, 20-20-20 breaks, autostart, exit).
- Handles 'TaskbarCreated' broadcast to restore icon if Explorer restarts/crashes.
- Handles WM_POWERBROADCAST (system resume from sleep/hibernate) to reapply matrix.
- Handles WM_DISPLAYCHANGE (resolution or monitor plug/unplug events).
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from ctypes import wintypes
from typing import Callable, Optional

from . import backlight, cleartype, color_matrix, config, logger, signals, winlib

# Win32 Constants
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010

NIIF_NONE = 0x00000000
NIIF_INFO = 0x00000001

WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20

WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203

WM_POWERBROADCAST = 0x0218
PBT_APMRESUMEAUTOMATIC = 0x0012
WM_DISPLAYCHANGE = 0x007E

# Terminal Services / Session Notification
WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
NOTIFY_FOR_THIS_SESSION = 0

MF_STRING = 0x00000000
MF_POPUP = 0x00000010
MF_CHECKED = 0x00000008
MF_UNCHECKED = 0x00000000
MF_SEPARATOR = 0x00000800
MF_GRAYED = 0x00000001
MF_DISABLED = 0x00000002

TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002
TPM_LEFTALIGN = 0x0000
TPM_TOPALIGN = 0x0000

_shell32: Optional[ctypes.WinDLL] = None

def shell32() -> ctypes.WinDLL:
    """Cached wrapper for shell32.dll."""
    global _shell32
    if _shell32 is None:
        _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    return _shell32

# Menu Command IDs
CMD_HEADER = 1000
CMD_TOGGLE = 1001
CMD_TURN_ON = 1002
CMD_TURN_OFF = 1003

CMD_PRESET_PAPER = 1010
CMD_PRESET_SEPIA = 1011
CMD_PRESET_WARM_READING = 1012
CMD_PRESET_EINK = 1013
CMD_PRESET_EINK_WARM = 1014
CMD_PRESET_NIGHTPAPER = 1015
CMD_PRESET_INVERTED = 1016
CMD_PRESET_AUTO = 1017
CMD_PRESET_CUSTOM = 1018
CMD_PRESET_AMBER_CANDLE = 1019

CMD_BRI_100 = 1030
CMD_BRI_75 = 1031
CMD_BRI_60 = 1032
CMD_BRI_40 = 1033
CMD_BRI_25 = 1034

CMD_BREAK_TOGGLE = 1040
CMD_BREAK_NOW = 1041

CMD_SMOOTHING_TOGGLE = 1050
CMD_AUTOSTART_TOGGLE = 1051
CMD_DOCTOR = 1052
CMD_SETTINGS = 1060
CMD_SESSION_LOCK = 1080
CMD_SESSION_UNLOCK = 1081
CMD_LIVE_PREVIEW = 1082
CMD_EXIT = 1099


LRESULT = ctypes.c_ssize_t

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeout", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HICON),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


def _create_paper_icon(active: bool = True) -> wintypes.HICON:
    """Generate a clean 16x16 paper sheet icon in memory."""
    u32 = winlib.user32()
    g32 = winlib.gdi32()

    # Create 16x16 mask and color bitmaps
    width, height = 16, 16
    hdc_screen = u32.GetDC(None)
    hdc_mem = g32.CreateCompatibleDC(hdc_screen)

    # 32-bit ARGB
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = width
    bmi.biHeight = -height  # top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0  # BI_RGB

    p_bits = ctypes.c_void_p()
    hbm_color = g32.CreateDIBSection(
        hdc_screen, ctypes.byref(bmi), 0, ctypes.byref(p_bits), None, 0
    )

    hbm_mask = g32.CreateBitmap(width, height, 1, 1, None)

    # Color values (BGRA)
    # Active: warm parchment #F3EBDD with charcoal border #2E2A26
    # Inactive: muted slate gray #888888
    if active:
        bg_color = (0xDD, 0xEB, 0xF3, 0xFF)  # BGRA parchment
        border = (0x26, 0x2A, 0x2E, 0xFF)    # BGRA charcoal
        line_color = (0x99, 0xB0, 0xC0, 0xFF)
    else:
        bg_color = (0xC0, 0xC0, 0xC0, 0xFF)
        border = (0x55, 0x55, 0x55, 0xFF)
        line_color = (0x88, 0x88, 0x88, 0xFF)

    # Fill pixel array
    buffer = (ctypes.c_uint8 * (width * height * 4)).from_address(p_bits.value)
    for y in range(height):
        for x in range(width):
            idx = (y * width + x) * 4
            # Draw paper rectangle from x=2..13, y=1..14
            if 2 <= x <= 13 and 1 <= y <= 14:
                # Border
                if x == 2 or x == 13 or y == 1 or y == 14:
                    buffer[idx : idx + 4] = border
                # Simulated text lines
                elif y in (4, 7, 10) and 4 <= x <= 11:
                    buffer[idx : idx + 4] = line_color
                else:
                    buffer[idx : idx + 4] = bg_color
            else:
                # Transparent outside
                buffer[idx : idx + 4] = (0, 0, 0, 0)

    u32.ReleaseDC(None, hdc_screen)
    g32.DeleteDC(hdc_mem)

    ii = ICONINFO()
    ii.fIcon = True
    ii.hbmMask = hbm_mask
    ii.hbmColor = hbm_color
    h_icon = u32.CreateIconIndirect(ctypes.byref(ii))

    g32.DeleteObject(hbm_color)
    g32.DeleteObject(hbm_mask)
    return h_icon


class SystemTray:
    def __init__(self, on_command: Callable[[int], None]):
        self.on_command = on_command
        self.hwnd: Optional[wintypes.HWND] = None
        self.nid = NOTIFYICONDATAW()
        self.h_icon_active = None
        self.h_icon_inactive = None
        self.taskbar_created_msg = 0
        self.wnd_proc_delegate = None

    def create(self) -> bool:
        u32 = winlib.user32()
        k32 = ctypes.windll.kernel32

        # Icons
        self.h_icon_active = _create_paper_icon(active=True)
        self.h_icon_inactive = _create_paper_icon(active=False)

        # User32 function signatures to avoid 64-bit integer overflow
        u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u32.DefWindowProcW.restype = LRESULT
        u32.PostQuitMessage.argtypes = [ctypes.c_int]
        u32.PostQuitMessage.restype = None
        u32.DestroyWindow.argtypes = [wintypes.HWND]
        u32.DestroyWindow.restype = wintypes.BOOL
        u32.SetForegroundWindow.argtypes = [wintypes.HWND]
        u32.SetForegroundWindow.restype = wintypes.BOOL
        u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u32.PostMessageW.restype = wintypes.BOOL
        u32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
        u32.RegisterClassExW.restype = wintypes.ATOM
        u32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        u32.CreateWindowExW.restype = wintypes.HWND

        # Register TaskbarCreated message
        self.taskbar_created_msg = u32.RegisterWindowMessageW("TaskbarCreated")

        # Window class
        class_name = "PaperScreenTrayClass"
        h_inst = k32.GetModuleHandleW(None)

        WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )

        def _wnd_proc(hwnd, msg, wparam, lparam):
            try:
                res = self.dispatch_message(hwnd, msg, wparam, lparam)
                if res is not None:
                    return res
            except Exception as exc:
                logger.error(f"Unhandled error in tray window procedure: {exc}", exc)
            return u32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self.wnd_proc_delegate = WNDPROC(_wnd_proc)

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = 0
        wc.lpfnWndProc = ctypes.cast(self.wnd_proc_delegate, ctypes.c_void_p)
        wc.hInstance = h_inst
        wc.lpszClassName = class_name
        u32.RegisterClassExW(ctypes.byref(wc))

        # Hidden top-level window to properly receive shell and broadcast messages
        self.hwnd = u32.CreateWindowExW(
            0, class_name, "PaperScreen Tray", 0, 0, 0, 0, 0,
            None, None, h_inst, None
        )

        if not self.hwnd:
            logger.error("Failed to create tray hidden window")
            return False

        # Register for Windows session lock/unlock notifications
        try:
            wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
            wtsapi32.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
            wtsapi32.WTSRegisterSessionNotification.restype = wintypes.BOOL
            wtsapi32.WTSRegisterSessionNotification(self.hwnd, NOTIFY_FOR_THIS_SESSION)
        except Exception as exc:
            logger.debug(f"WTSRegisterSessionNotification registration failed: {exc}")

        self._add_icon()
        return True

    def _add_icon(self) -> None:
        j = signals.load()
        is_active = bool(j.get("active"))
        preset = j.get("preset", "paper")

        self.nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        self.nid.hWnd = self.hwnd
        self.nid.uID = 1
        self.nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP
        self.nid.uCallbackMessage = WM_TRAYICON
        self.nid.hIcon = self.h_icon_active if is_active else self.h_icon_inactive
        status_text = f"PaperScreen - {'Active: ' + preset.title() if is_active else 'Off'}"
        self.nid.szTip = status_text[:127]

        shell32().Shell_NotifyIconW(NIM_ADD, ctypes.byref(self.nid))

    def update_tooltip(self, text: str, active: bool = True) -> None:
        self.nid.uFlags = NIF_ICON | NIF_TIP
        self.nid.hIcon = self.h_icon_active if active else self.h_icon_inactive
        self.nid.szTip = text[:127]
        shell32().Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self.nid))

    def show_balloon(self, title: str, text: str) -> None:
        self.nid.uFlags = NIF_INFO
        self.nid.szInfo = text[:255]
        self.nid.szInfoTitle = title[:63]
        self.nid.dwInfoFlags = NIIF_INFO
        shell32().Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self.nid))

    def show_menu(self) -> None:
        if not self.hwnd:
            return
        u32 = winlib.user32()
        pt = wintypes.POINT()
        u32.GetCursorPos(ctypes.byref(pt))

        h_menu = u32.CreatePopupMenu()
        h_presets = u32.CreatePopupMenu()
        h_backlight = u32.CreatePopupMenu()
        h_breaks = u32.CreatePopupMenu()

        j = signals.load()
        cfg = config.load()
        is_active = bool(j.get("active"))
        cur_preset = j.get("preset") or cfg.get("preset", "paper")

        # Header item (disabled)
        hdr = f"PaperScreen ({cur_preset.title()})" if is_active else "PaperScreen (Disabled)"
        u32.AppendMenuW(h_menu, MF_STRING | MF_DISABLED, CMD_HEADER, hdr)
        u32.AppendMenuW(h_menu, MF_SEPARATOR, 0, None)

        # Toggle Active
        toggle_flags = MF_STRING | (MF_CHECKED if is_active else MF_UNCHECKED)
        u32.AppendMenuW(h_menu, toggle_flags, CMD_TOGGLE, "Enable Paper Mode")

        # Presets Submenu
        def _p_flags(name: str):
            return MF_STRING | (MF_CHECKED if (is_active and cur_preset == name) else MF_UNCHECKED)

        u32.AppendMenuW(h_presets, _p_flags("paper"), CMD_PRESET_PAPER, "Paper (4400 K Matte)")
        u32.AppendMenuW(h_presets, _p_flags("sepia"), CMD_PRESET_SEPIA, "Sepia (3600 K Antique)")
        u32.AppendMenuW(h_presets, _p_flags("warm_reading"), CMD_PRESET_WARM_READING, "Warm Reading (3000 K)")
        u32.AppendMenuW(h_presets, _p_flags("eink"), CMD_PRESET_EINK, "E-Ink Monochrome (6500 K)")
        u32.AppendMenuW(h_presets, _p_flags("eink_warm"), CMD_PRESET_EINK_WARM, "E-Ink Warm Paperwhite (4000 K)")
        u32.AppendMenuW(h_presets, _p_flags("amber_candle"), CMD_PRESET_AMBER_CANDLE, "Amber Candle (2200 K)")
        u32.AppendMenuW(h_presets, _p_flags("nightpaper"), CMD_PRESET_NIGHTPAPER, "Night Paper (3200 K)")
        u32.AppendMenuW(h_presets, _p_flags("inverted_paper"), CMD_PRESET_INVERTED, "Smart Dark Paper (Hue-Preserving)")
        u32.AppendMenuW(h_presets, _p_flags("custom"), CMD_PRESET_CUSTOM, "Custom (Calibrated)")
        u32.AppendMenuW(h_presets, MF_SEPARATOR, 0, None)
        u32.AppendMenuW(h_presets, _p_flags("auto"), CMD_PRESET_AUTO, "Auto Day/Night Sync")
        u32.AppendMenuW(h_menu, MF_POPUP, h_presets, "Presets")

        # Backlight Submenu
        cur_bri = j.get("backlight_level")
        u32.AppendMenuW(h_backlight, MF_STRING | (MF_CHECKED if cur_bri == 100 else 0), CMD_BRI_100, "100% (Maximum)")
        u32.AppendMenuW(h_backlight, MF_STRING | (MF_CHECKED if cur_bri == 75 else 0), CMD_BRI_75, "75%")
        u32.AppendMenuW(h_backlight, MF_STRING | (MF_CHECKED if cur_bri == 60 else 0), CMD_BRI_60, "60% (Day Default)")
        u32.AppendMenuW(h_backlight, MF_STRING | (MF_CHECKED if cur_bri == 40 else 0), CMD_BRI_40, "40%")
        u32.AppendMenuW(h_backlight, MF_STRING | (MF_CHECKED if cur_bri == 25 else 0), CMD_BRI_25, "25% (Night Default)")
        u32.AppendMenuW(h_menu, MF_POPUP, h_backlight, "Backlight (DDC/WMI)")

        # Breaks Submenu
        breaks_on = cfg.get("breaks_enabled", True)
        u32.AppendMenuW(h_breaks, MF_STRING | (MF_CHECKED if breaks_on else 0), CMD_BREAK_TOGGLE, "20-20-20 Reminders")
        u32.AppendMenuW(h_breaks, MF_STRING, CMD_BREAK_NOW, "Take Break Now (20s)")
        u32.AppendMenuW(h_menu, MF_POPUP, h_breaks, "Eye Breaks")

        u32.AppendMenuW(h_menu, MF_SEPARATOR, 0, None)

        # Grayscale Smoothing
        smooth_on = cfg.get("grayscale_smoothing", False)
        u32.AppendMenuW(h_menu, MF_STRING | (MF_CHECKED if smooth_on else 0), CMD_SMOOTHING_TOGGLE, "Grayscale Font Smoothing")

        # Autostart
        is_auto = False
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                winreg.QueryValueEx(k, "PaperScreen")
                is_auto = True
        except OSError:
            pass
        u32.AppendMenuW(h_menu, MF_STRING | (MF_CHECKED if is_auto else 0), CMD_AUTOSTART_TOGGLE, "Start with Windows")

        # Preferences, Diagnostics & Exit
        u32.AppendMenuW(h_menu, MF_STRING, CMD_SETTINGS, "Preferences & Settings...")
        u32.AppendMenuW(h_menu, MF_STRING, CMD_DOCTOR, "Diagnostics (Doctor)...")
        u32.AppendMenuW(h_menu, MF_SEPARATOR, 0, None)
        u32.AppendMenuW(h_menu, MF_STRING, CMD_EXIT, "Exit PaperScreen")

        # Mandatory for popup menu dismissal
        u32.SetForegroundWindow(self.hwnd)
        u32.TrackPopupMenu(
            h_menu, TPM_RIGHTBUTTON | TPM_LEFTALIGN | TPM_TOPALIGN, pt.x, pt.y, 0, self.hwnd, None
        )
        u32.DestroyMenu(h_menu)

    def dispatch_message(self, hwnd, msg, wparam, lparam) -> Optional[int]:
        if msg == self.taskbar_created_msg:
            self._add_icon()
            return 0
        if msg == WM_TRAYICON:
            if lparam in (WM_RBUTTONUP, WM_LBUTTONUP):
                self.show_menu()
            elif lparam == WM_LBUTTONDBLCLK:
                self.on_command(CMD_TOGGLE)
            return 0
        if msg == WM_COMMAND:
            cmd_id = int(wparam) & 0xFFFF
            self.on_command(cmd_id)
            return 0
        if msg == WM_POWERBROADCAST and wparam == PBT_APMRESUMEAUTOMATIC:
            logger.info("System resumed from sleep: refreshing display effects")
            self.on_command(CMD_HEADER)  # refresh trigger
            return 0
        if msg == WM_DISPLAYCHANGE:
            logger.info("Display topology/resolution changed: refreshing")
            self.on_command(CMD_HEADER)
            return 0
        if msg == WM_WTSSESSION_CHANGE:
            if wparam == WTS_SESSION_LOCK:
                logger.info("Session locked (Win+L / screensaver): resetting matrix to identity")
                self.on_command(CMD_SESSION_LOCK)
            elif wparam == WTS_SESSION_UNLOCK:
                logger.info("Session unlocked: restoring active paper preset")
                self.on_command(CMD_SESSION_UNLOCK)
            return 0
        if msg == WM_DESTROY:
            self.remove()
            winlib.user32().PostQuitMessage(0)
            return 0
        return None

    def remove(self) -> None:
        if self.hwnd:
            hwnd = self.hwnd
            self.hwnd = None
            try:
                wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
                wtsapi32.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
                wtsapi32.WTSUnRegisterSessionNotification.restype = wintypes.BOOL
                wtsapi32.WTSUnRegisterSessionNotification(hwnd)
            except Exception:
                pass
            shell32().Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))
            try:
                winlib.user32().DestroyWindow(hwnd)
            except Exception:
                pass


__all__ = [
    "SystemTray",
    "shell32",
    "CMD_HEADER",
    "CMD_TOGGLE",
    "CMD_TURN_ON",
    "CMD_TURN_OFF",
    "CMD_PRESET_PAPER",
    "CMD_PRESET_SEPIA",
    "CMD_PRESET_WARM_READING",
    "CMD_PRESET_EINK",
    "CMD_PRESET_EINK_WARM",
    "CMD_PRESET_NIGHTPAPER",
    "CMD_PRESET_INVERTED",
    "CMD_PRESET_AUTO",
    "CMD_PRESET_CUSTOM",
    "CMD_PRESET_AMBER_CANDLE",
    "CMD_BRI_100",
    "CMD_BRI_75",
    "CMD_BRI_60",
    "CMD_BRI_40",
    "CMD_BRI_25",
    "CMD_BREAK_TOGGLE",
    "CMD_BREAK_NOW",
    "CMD_SMOOTHING_TOGGLE",
    "CMD_AUTOSTART_TOGGLE",
    "CMD_DOCTOR",
    "CMD_SETTINGS",
    "CMD_SESSION_LOCK",
    "CMD_SESSION_UNLOCK",
    "CMD_LIVE_PREVIEW",
    "CMD_EXIT",
]
