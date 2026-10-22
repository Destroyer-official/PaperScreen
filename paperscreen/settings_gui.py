"""Zero-dependency Tkinter Settings & Calibration GUI for PaperScreen.

Features:
- Pure Python stdlib (tkinter + ttk), zero third-party packages.
- Live status header with 1-click Engine Toggle (Turn ON / Turn OFF).
- Real-time display calibration sliders (Kelvin, Desaturation, Black Floor, White Ceiling, Contrast).
- Instant 0ms IPC preview with resident daemon or direct in-process preview.
- Hardware backlight preview slider with background-threaded execution (no UI lag).
- Font smoothing & ClearType live toggle.
- Circadian hours, 20-20-20 break settings, and auto-pause app exclusions.
- Clean parchment-inspired design palette with Segoe UI typography.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from . import backlight, cleartype, color_matrix, config, paper_engine, signals, spawn, tray, winlib


class SettingsWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PaperScreen Preferences & Display Calibration")
        self.root.geometry("580x680")
        self.root.minsize(540, 620)

        # Style & Palette (Parchment theme)
        self.bg_color = "#F8F5EE"
        self.card_color = "#FFFFFF"
        self.text_color = "#2D2926"
        self.accent_color = "#5C4D3C"
        self.sub_color = "#7A7268"
        self.green_color = "#2E6B38"
        self.red_color = "#9E2A2B"

        self.root.configure(bg=self.bg_color)

        self.cfg = config.load()
        self._preview_timer: Optional[str] = None
        self._backlight_timer: Optional[str] = None
        self._status_poll_timer: Optional[str] = None
        self._user_adjusting = True
        self._slider_labels = []

        self._init_vars()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Apply initial preview ONLY if engine is currently active
        if self._is_engine_active() and self.var_live_preview.get():
            self._preview_timer = self.root.after(100, self._apply_live_preview)

        # Periodic status check keeps UI in sync with hotkey and tray actions
        self._status_poll_timer = self.root.after(500, self._poll_status_header)

    def _init_vars(self):
        j = signals.load()
        is_running = spawn.is_daemon_running()
        cur_preset = (j.get("preset") if is_running else None) or self.cfg.get("preset", "paper")
        self.var_preset = tk.StringVar(value=cur_preset)
        self.var_invert = tk.BooleanVar(value=(cur_preset == "inverted_paper"))

        # Sliders from active config or preset values
        kelvin = self.cfg.get("kelvin", 4400)
        desat = self.cfg.get("desaturation", 0.65)
        floor = self.cfg.get("black_floor", 0.10)
        ceiling = self.cfg.get("white_ceiling", 0.90)
        contrast = self.cfg.get("contrast", 1.04)

        if cur_preset in color_matrix.PRESET_VALUES and cur_preset != "custom":
            pv = color_matrix.PRESET_VALUES[cur_preset]
            kelvin = pv.get("kelvin", kelvin)
            desat = pv.get("desaturation", desat)
            floor = pv.get("black_floor", floor)
            ceiling = pv.get("white_ceiling", ceiling)
            contrast = pv.get("contrast", contrast)

        self.var_kelvin = tk.IntVar(value=int(kelvin))
        self.var_desat = tk.DoubleVar(value=round(desat * 100, 1))
        self.var_floor = tk.DoubleVar(value=round(floor * 100, 1))
        self.var_ceiling = tk.DoubleVar(value=round(ceiling * 100, 1))
        self.var_contrast = tk.DoubleVar(value=round(contrast, 2))

        self.var_bri_day = tk.IntVar(value=self.cfg.get("backlight_day", 60))
        self.var_bri_night = tk.IntVar(value=self.cfg.get("backlight_night", 30))
        self.var_start_hour = tk.IntVar(value=self.cfg.get("night_start_hour", 19))
        self.var_end_hour = tk.IntVar(value=self.cfg.get("night_end_hour", 7))

        self.var_breaks = tk.BooleanVar(value=self.cfg.get("breaks_enabled", True))
        self.var_break_interval = tk.IntVar(value=self.cfg.get("break_interval_minutes", 20))
        self.var_break_duration = tk.IntVar(value=self.cfg.get("break_duration_seconds", 20))

        self.var_smoothing = tk.BooleanVar(value=self.cfg.get("grayscale_smoothing", False))
        self.var_hotkey = tk.BooleanVar(value=self.cfg.get("hotkey_toggle", True))
        self.var_auto_pause = tk.BooleanVar(value=self.cfg.get("auto_pause_fullscreen", False))
        self.var_excluded = tk.StringVar(value=", ".join(self.cfg.get("excluded_apps", [])))

        self.var_live_preview = tk.BooleanVar(value=True)

    def _build_ui(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # ---------------- Header Status Bar ----------------
        self.header_frame = tk.Frame(self.root, bg="#EFECE4", padx=14, pady=10, relief="solid", bd=1)
        self.header_frame.pack(fill="x", padx=14, pady=(12, 4))

        header_left = tk.Frame(self.header_frame, bg="#EFECE4")
        header_left.pack(side="left", fill="both", expand=True)

        self.lbl_status = tk.Label(
            header_left, text="", font=("Segoe UI", 10, "bold"), bg="#EFECE4"
        )
        self.lbl_status.pack(anchor="w")

        self.lbl_substatus = tk.Label(
            header_left, text="", font=("Segoe UI", 8), bg="#EFECE4", fg=self.sub_color
        )
        self.lbl_substatus.pack(anchor="w")

        self.btn_toggle_engine = tk.Button(
            self.header_frame, text="", font=("Segoe UI", 9, "bold"),
            relief="flat", padx=14, pady=5, cursor="hand2",
            command=self._toggle_engine
        )
        self.btn_toggle_engine.pack(side="right")

        self._refresh_status_header()

        # ---------------- Notebook Tabs ----------------
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=self.bg_color)
        style.configure("TNotebook.Tab", background=self.bg_color, padding=[12, 6], font=("Segoe UI", 9, "bold"))
        style.map("TNotebook.Tab", background=[("selected", self.card_color)])

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=14, pady=8)

        # Tab 1: Color & Display Tuning
        tab_display = tk.Frame(notebook, bg=self.card_color, padx=16, pady=12)
        notebook.add(tab_display, text="Display & Matrix")
        self._build_display_tab(tab_display)

        # Tab 2: Circadian & Automation
        tab_circadian = tk.Frame(notebook, bg=self.card_color, padx=16, pady=12)
        notebook.add(tab_circadian, text="Circadian & Apps")
        self._build_circadian_tab(tab_circadian)

        # Tab 3: Ergonomics & Breaks
        tab_breaks = tk.Frame(notebook, bg=self.card_color, padx=16, pady=12)
        notebook.add(tab_breaks, text="Breaks & Font")
        self._build_breaks_tab(tab_breaks)

        # ---------------- Bottom Actions Bar ----------------
        bottom_bar = tk.Frame(self.root, bg=self.bg_color, padx=14, pady=8)
        bottom_bar.pack(fill="x", side="bottom")

        btn_save = tk.Button(
            bottom_bar, text="Save & Apply Changes", bg=self.accent_color, fg="#FFFFFF",
            activebackground="#423628", activeforeground="#FFFFFF",
            font=("Segoe UI", 9, "bold"), relief="flat", padx=16, pady=6, cursor="hand2",
            command=self._save_and_apply
        )
        btn_save.pack(side="right", padx=6)

        btn_reset = tk.Button(
            bottom_bar, text="Reset Defaults", bg="#EAE5DC", fg=self.text_color,
            font=("Segoe UI", 9), relief="flat", padx=12, pady=6, cursor="hand2",
            command=self._reset_defaults
        )
        btn_reset.pack(side="right", padx=6)

    def _is_engine_active(self) -> bool:
        if not spawn.is_daemon_running():
            return False
        j = signals.load()
        return bool(j.get("active", False))

    def _poll_status_header(self):
        try:
            self._refresh_status_header()
        except Exception:
            pass
        self._status_poll_timer = self.root.after(500, self._poll_status_header)

    def _refresh_status_header(self):
        active = self._is_engine_active()
        if active:
            j = signals.load()
            cur = (j.get("preset") or self.var_preset.get()).replace("_", " ").title()
            self.lbl_status.config(text=f"● PaperScreen: ACTIVE ({cur})", fg=self.green_color)
            self.lbl_substatus.config(text="Resident background daemon active with native tray controls")
            self.btn_toggle_engine.config(
                text="Turn OFF", bg="#F2D7D5", fg=self.red_color,
                activebackground="#D98880", activeforeground="#FFFFFF"
            )
        else:
            self.lbl_status.config(text="○ PaperScreen: INACTIVE", fg=self.sub_color)
            self.lbl_substatus.config(text="Controls below preview in real-time; click 'Turn ON' to activate resident engine")
            self.btn_toggle_engine.config(
                text="Turn ON", bg="#D4EFDF", fg=self.green_color,
                activebackground="#7DCEA0", activeforeground="#FFFFFF"
            )

    def _toggle_engine(self):
        if self._is_engine_active():
            # Turn OFF
            if self._preview_timer:
                try:
                    self.root.after_cancel(self._preview_timer)
                except Exception:
                    pass
                self._preview_timer = None

            # Revert display to neutral immediately
            try:
                winlib.mag_initialize()
                winlib.mag_set_color_effect(color_matrix.identity())
            except Exception:
                pass

            if spawn.is_daemon_running():
                hwnd = winlib.user32().FindWindowW("PaperScreenTrayClass", "PaperScreen Tray")
                if hwnd:
                    winlib.user32().PostMessageW(hwnd, 0x0111, tray.CMD_TOGGLE, 0)
                else:
                    paper_engine.release()
            else:
                signals.update(active=False)

            cfg = config.load()
            if cfg.get("restore_backlight_on_exit", True):
                try:
                    backlight.restore()
                except Exception:
                    pass
            try:
                cleartype.restore_previous()
            except Exception:
                pass

            self.root.after(50, self._refresh_status_header)
        else:
            # Turn ON
            signals.update(preview_matrix=None)
            cur_preset = self.var_preset.get()
            if getattr(self, "var_invert", None) and self.var_invert.get():
                cur_preset = "inverted_paper"
                self.var_preset.set("inverted_paper")

            if spawn.is_daemon_running():
                hwnd = winlib.user32().FindWindowW("PaperScreenTrayClass", "PaperScreen Tray")
                if hwnd:
                    signals.update(active=True, preset=cur_preset)
                    winlib.user32().PostMessageW(hwnd, 0x0111, tray.CMD_TOGGLE, 0)
                else:
                    paper_engine.apply(preset=cur_preset, set_backlight=True)
            else:
                paper_engine.apply(preset=cur_preset, set_backlight=True)

            self.root.after(100, self._refresh_status_header)

    def _build_display_tab(self, parent):
        # Preset Selector
        row_preset = tk.Frame(parent, bg=self.card_color)
        row_preset.pack(fill="x", pady=(0, 6))
        tk.Label(row_preset, text="Active Preset:", font=("Segoe UI", 9, "bold"), bg=self.card_color, fg=self.text_color).pack(side="left")

        presets = ["paper", "sepia", "warm_reading", "eink", "eink_warm", "amber_candle", "nightpaper", "inverted_paper", "custom", "auto"]
        self.cb_preset = ttk.Combobox(row_preset, textvariable=self.var_preset, values=presets, state="readonly", width=18)
        self.cb_preset.pack(side="right")
        self.cb_preset.bind("<<ComboboxSelected>>", self._on_preset_selected)

        # Invert / Dark Paper Mode checkbox
        row_invert = tk.Frame(parent, bg=self.card_color)
        row_invert.pack(fill="x", pady=(0, 6))
        tk.Checkbutton(
            row_invert, text="Invert Luminance (Dark Paper / Light Text)",
            variable=self.var_invert, bg=self.card_color, activebackground=self.card_color,
            font=("Segoe UI", 9), fg=self.text_color,
            command=self._on_invert_toggled
        ).pack(side="left")

        # Matrix tuning sliders
        self._add_matrix_slider(parent, "Color Temperature (Kelvin):", self.var_kelvin, 1000, 10000, 100, " K")
        self._add_matrix_slider(parent, "Desaturation (%):", self.var_desat, 0, 100, 1, "%")
        self._add_matrix_slider(parent, "Black Floor (Charcoal Lift %):", self.var_floor, 0, 40, 1, "%")
        self._add_matrix_slider(parent, "White Ceiling (Parchment Cap %):", self.var_ceiling, 50, 100, 1, "%")
        self._add_matrix_slider(parent, "Contrast Scale:", self.var_contrast, 0.4, 1.8, 0.05, "x")

        # Real-time preview checkbutton
        preview_frame = tk.Frame(parent, bg=self.card_color)
        preview_frame.pack(fill="x", pady=(8, 0))
        tk.Checkbutton(
            preview_frame, text="Real-Time Display Preview (changes reflect immediately on monitor)",
            variable=self.var_live_preview, bg=self.card_color, activebackground=self.card_color,
            font=("Segoe UI", 9, "italic"), fg=self.accent_color,
            command=self._on_preview_checkbox_toggled
        ).pack(side="left")

    def _on_preset_selected(self, event=None):
        name = self.var_preset.get()
        if name == "inverted_paper":
            self.var_invert.set(True)
        else:
            self.var_invert.set(False)

        if name in color_matrix.PRESET_VALUES:
            self._user_adjusting = False
            vals = color_matrix.PRESET_VALUES[name]
            self.var_kelvin.set(vals.get("kelvin", 4400))
            self.var_desat.set(round(vals.get("desaturation", 0.65) * 100, 1))
            self.var_floor.set(round(vals.get("black_floor", 0.10) * 100, 1))
            self.var_ceiling.set(round(vals.get("white_ceiling", 0.90) * 100, 1))
            self.var_contrast.set(round(vals.get("contrast", 1.04), 2))
            self._update_all_slider_labels()
            self._user_adjusting = True
        self._schedule_live_preview()

    def _on_invert_toggled(self):
        if self.var_invert.get():
            self.var_preset.set("inverted_paper")
        else:
            if self.var_preset.get() == "inverted_paper":
                self.var_preset.set("paper")
        self._schedule_live_preview()

    def _on_preview_checkbox_toggled(self):
        if not self.var_live_preview.get():
            if not self._is_engine_active():
                try:
                    winlib.mag_initialize()
                    winlib.mag_set_color_effect(color_matrix.identity())
                except Exception:
                    pass
            elif spawn.is_daemon_running():
                signals.update(preview_matrix=None)
                hwnd = winlib.user32().FindWindowW("PaperScreenTrayClass", "PaperScreen Tray")
                if hwnd:
                    winlib.user32().PostMessageW(hwnd, 0x0111, tray.CMD_HEADER, 0)
        else:
            self._schedule_live_preview()

    def _update_all_slider_labels(self):
        for var, lbl, res, unit in self._slider_labels:
            val = var.get()
            formatted = f"{float(val):.2f}" if isinstance(res, float) else f"{int(float(val))}"
            lbl.config(text=f"{formatted}{unit}")

    def _compute_current_matrix(self):
        p = self.var_preset.get()
        is_inverted = (p == "inverted_paper") or (getattr(self, "var_invert", None) and self.var_invert.get())
        if is_inverted:
            return color_matrix.inverted_paper_matrix(
                kelvin=float(self.var_kelvin.get()),
                desaturation=float(self.var_desat.get()) / 100.0,
                black_floor=float(self.var_floor.get()) / 100.0,
                white_ceiling=float(self.var_ceiling.get()) / 100.0,
            )
        elif p == "eink":
            return color_matrix.preset("eink")
        elif p == "eink_warm":
            return color_matrix.preset("eink_warm")
        else:
            return color_matrix.paper_matrix(
                kelvin=float(self.var_kelvin.get()),
                desaturation=float(self.var_desat.get()) / 100.0,
                black_floor=float(self.var_floor.get()) / 100.0,
                white_ceiling=float(self.var_ceiling.get()) / 100.0,
                contrast=float(self.var_contrast.get()),
            )

    def _schedule_live_preview(self):
        """Debounce preview application to 25ms so slider dragging is buttery smooth."""
        if self._preview_timer:
            self.root.after_cancel(self._preview_timer)
        self._preview_timer = self.root.after(25, self._apply_live_preview)

    def _apply_live_preview(self):
        self._preview_timer = None
        if not getattr(self, "var_live_preview", None) or not self.var_live_preview.get():
            return
        m = self._compute_current_matrix()
        if spawn.is_daemon_running():
            # Daemon owns the Magnification API session: pass preview matrix via signals & IPC
            signals.update(preview_matrix=m)
            hwnd = winlib.user32().FindWindowW("PaperScreenTrayClass", "PaperScreen Tray")
            if hwnd:
                winlib.user32().PostMessageW(hwnd, 0x0111, tray.CMD_LIVE_PREVIEW, 0)
        else:
            # Standalone GUI process: apply directly via local magnification session
            try:
                winlib.mag_initialize()
                winlib.mag_set_color_effect(m)
            except Exception:
                pass

    def destroy(self):
        """Cancel any pending timers and release UI resources."""
        if getattr(self, "_status_poll_timer", None):
            try:
                self.root.after_cancel(self._status_poll_timer)
            except Exception:
                pass
            self._status_poll_timer = None
        if self._preview_timer:
            try:
                self.root.after_cancel(self._preview_timer)
            except Exception:
                pass
            self._preview_timer = None
        if self._backlight_timer:
            try:
                self.root.after_cancel(self._backlight_timer)
            except Exception:
                pass
            self._backlight_timer = None

    def _on_close(self):
        self.destroy()

        j = signals.load()
        if spawn.is_daemon_running():
            signals.update(preview_matrix=None)
            hwnd = winlib.user32().FindWindowW("PaperScreenTrayClass", "PaperScreen Tray")
            if hwnd:
                winlib.user32().PostMessageW(hwnd, 0x0111, tray.CMD_HEADER, 0)
        elif not self._is_engine_active():
            try:
                winlib.mag_initialize()
                winlib.mag_set_color_effect(color_matrix.identity())
            except Exception:
                pass
        self.root.destroy()

    def _add_matrix_slider(self, parent, label_text, var, from_val, to_val, resolution, unit=""):
        frame = tk.Frame(parent, bg=self.card_color)
        frame.pack(fill="x", pady=5)

        header = tk.Frame(frame, bg=self.card_color)
        header.pack(fill="x")
        tk.Label(header, text=label_text, font=("Segoe UI", 9), bg=self.card_color, fg=self.text_color).pack(side="left")

        lbl_val = tk.Label(header, text=f"{var.get()}{unit}", font=("Segoe UI", 9, "bold"), bg=self.card_color, fg=self.accent_color)
        lbl_val.pack(side="right")
        self._slider_labels.append((var, lbl_val, resolution, unit))

        def _on_move(val):
            formatted = f"{float(val):.2f}" if isinstance(resolution, float) else f"{int(float(val))}"
            lbl_val.config(text=f"{formatted}{unit}")
            if self._user_adjusting:
                cur = self.var_preset.get()
                if cur == "inverted_paper" or (getattr(self, "var_invert", None) and self.var_invert.get()):
                    # Stay on inverted_paper so customization remains inverted
                    self.var_preset.set("inverted_paper")
                    if getattr(self, "var_invert", None):
                        self.var_invert.set(True)
                elif cur not in ("custom", ""):
                    self.var_preset.set("custom")
            self._schedule_live_preview()

        scale = tk.Scale(
            frame, from_=from_val, to=to_val, resolution=resolution, variable=var,
            orient="horizontal", showvalue=False, bg=self.card_color,
            troughcolor="#E6E0D4", activebackground=self.accent_color,
            highlightthickness=0, bd=0, command=_on_move
        )
        scale.pack(fill="x", pady=(2, 0))

    def _add_slider(self, parent, label_text, var, from_val, to_val, resolution, unit="", on_change=None):
        frame = tk.Frame(parent, bg=self.card_color)
        frame.pack(fill="x", pady=5)

        header = tk.Frame(frame, bg=self.card_color)
        header.pack(fill="x")
        tk.Label(header, text=label_text, font=("Segoe UI", 9), bg=self.card_color, fg=self.text_color).pack(side="left")

        lbl_val = tk.Label(header, text=f"{var.get()}{unit}", font=("Segoe UI", 9, "bold"), bg=self.card_color, fg=self.accent_color)
        lbl_val.pack(side="right")
        self._slider_labels.append((var, lbl_val, resolution, unit))

        def _on_move(val):
            formatted = f"{float(val):.2f}" if isinstance(resolution, float) else f"{int(float(val))}"
            lbl_val.config(text=f"{formatted}{unit}")
            if on_change:
                on_change(val)

        scale = tk.Scale(
            frame, from_=from_val, to=to_val, resolution=resolution, variable=var,
            orient="horizontal", showvalue=False, bg=self.card_color,
            troughcolor="#E6E0D4", activebackground=self.accent_color,
            highlightthickness=0, bd=0, command=_on_move
        )
        scale.pack(fill="x", pady=(2, 0))

    def _on_brightness_change(self, val):
        """Debounced background backlight adjustment: never blocks Tk UI thread."""
        if self._backlight_timer:
            self.root.after_cancel(self._backlight_timer)
        level = int(float(val))

        def _worker():
            try:
                backlight.set_brightness(level)
            except Exception:
                pass

        self._backlight_timer = self.root.after(80, lambda: threading.Thread(target=_worker, daemon=True).start())

    def _on_smoothing_toggle(self):
        try:
            if self.var_smoothing.get():
                cleartype.enable_grayscale_smoothing()
            else:
                cleartype.restore_previous()
        except Exception:
            pass

    def _build_circadian_tab(self, parent):
        # Backlight Levels
        tk.Label(parent, text="Hardware Backlight Targets (DDC/WMI)", font=("Segoe UI", 9, "bold"), bg=self.card_color, fg=self.text_color).pack(anchor="w", pady=(0, 4))
        self._add_slider(parent, "Daytime Brightness (Live Preview):", self.var_bri_day, 10, 100, 5, "%", on_change=self._on_brightness_change)
        self._add_slider(parent, "Nighttime Brightness:", self.var_bri_night, 0, 80, 5, "%")

        # Night Schedule Hours
        hours_frame = tk.Frame(parent, bg=self.card_color)
        hours_frame.pack(fill="x", pady=10)
        tk.Label(hours_frame, text="Night Window Hours (24h format):", font=("Segoe UI", 9), bg=self.card_color, fg=self.text_color).pack(anchor="w")

        sub_hours = tk.Frame(hours_frame, bg=self.card_color)
        sub_hours.pack(fill="x", pady=(4, 0))
        tk.Label(sub_hours, text="Start: ", bg=self.card_color).pack(side="left")
        tk.Spinbox(sub_hours, from_=0, to=23, width=4, textvariable=self.var_start_hour).pack(side="left", padx=(0, 16))
        tk.Label(sub_hours, text="End: ", bg=self.card_color).pack(side="left")
        tk.Spinbox(sub_hours, from_=0, to=23, width=4, textvariable=self.var_end_hour).pack(side="left")

        # Fullscreen & App Exclusions
        tk.Frame(parent, height=1, bg="#E6E0D4").pack(fill="x", pady=12)
        tk.Checkbutton(
            parent, text="Auto-pause when full-screen games or video players are focused",
            variable=self.var_auto_pause, bg=self.card_color, activebackground=self.card_color, font=("Segoe UI", 9)
        ).pack(anchor="w")

        tk.Label(parent, text="Excluded Executables (e.g. photoshop.exe, figma.exe):", font=("Segoe UI", 9), bg=self.card_color, fg=self.text_color).pack(anchor="w", pady=(10, 2))
        ent_ex = tk.Entry(parent, textvariable=self.var_excluded, bg="#FAF8F3", relief="solid", bd=1, font=("Segoe UI", 9))
        ent_ex.pack(fill="x")

    def _build_breaks_tab(self, parent):
        tk.Checkbutton(
            parent, text="Enable 20-20-20 Micro-Break Reminders",
            variable=self.var_breaks, bg=self.card_color, activebackground=self.card_color, font=("Segoe UI", 9, "bold")
        ).pack(anchor="w", pady=(0, 6))

        self._add_slider(parent, "Interval Between Breaks (Minutes):", self.var_break_interval, 5, 60, 5, " min")
        self._add_slider(parent, "Break Duration (Seconds):", self.var_break_duration, 10, 60, 5, " s")

        tk.Frame(parent, height=1, bg="#E6E0D4").pack(fill="x", pady=12)

        tk.Checkbutton(
            parent, text="Grayscale Font Smoothing (Mitigates ClearType subpixel color fringing)",
            variable=self.var_smoothing, bg=self.card_color, activebackground=self.card_color, font=("Segoe UI", 9),
            command=self._on_smoothing_toggle
        ).pack(anchor="w", pady=4)

        tk.Checkbutton(
            parent, text="Global Keyboard Shortcut Toggle (Ctrl + Alt + P)",
            variable=self.var_hotkey, bg=self.card_color, activebackground=self.card_color, font=("Segoe UI", 9)
        ).pack(anchor="w", pady=4)

    def _save_and_apply(self):
        # Build clean config dict
        cfg = dict(self.cfg)
        preset_name = self.var_preset.get()
        if getattr(self, "var_invert", None) and self.var_invert.get():
            preset_name = "inverted_paper"
            self.var_preset.set("inverted_paper")
        cfg["preset"] = preset_name
        cfg["kelvin"] = int(self.var_kelvin.get())
        cfg["desaturation"] = round(float(self.var_desat.get()) / 100.0, 4)
        cfg["black_floor"] = round(float(self.var_floor.get()) / 100.0, 4)
        cfg["white_ceiling"] = round(float(self.var_ceiling.get()) / 100.0, 4)
        cfg["contrast"] = round(float(self.var_contrast.get()), 2)

        cfg["backlight_day"] = int(self.var_bri_day.get())
        cfg["backlight_night"] = int(self.var_bri_night.get())
        cfg["night_start_hour"] = int(self.var_start_hour.get())
        cfg["night_end_hour"] = int(self.var_end_hour.get())

        cfg["breaks_enabled"] = bool(self.var_breaks.get())
        cfg["break_interval_minutes"] = int(self.var_break_interval.get())
        cfg["break_duration_seconds"] = int(self.var_break_duration.get())

        cfg["grayscale_smoothing"] = bool(self.var_smoothing.get())
        cfg["hotkey_toggle"] = bool(self.var_hotkey.get())
        cfg["auto_pause_fullscreen"] = bool(self.var_auto_pause.get())

        # Excluded apps
        raw_ex = self.var_excluded.get()
        cfg["excluded_apps"] = [x.strip().lower() for x in raw_ex.split(",") if x.strip()]

        config.save(cfg)
        self.cfg = cfg

        # Apply Font Smoothing
        if cfg["grayscale_smoothing"]:
            cleartype.enable_grayscale_smoothing()
        else:
            cleartype.restore_previous()

        # Apply Hardware Backlight Target
        target_bri = cfg["backlight_night"] if config.is_night() else cfg["backlight_day"]
        try:
            backlight.set_brightness(target_bri)
        except Exception:
            pass

        # If daemon is running, update it via IPC; if not running, start it so settings persist!
        if spawn.is_daemon_running():
            signals.update(preset=cfg["preset"], preview_matrix=None)
            hwnd = winlib.user32().FindWindowW("PaperScreenTrayClass", "PaperScreen Tray")
            if hwnd:
                winlib.user32().PostMessageW(hwnd, 0x0111, tray.CMD_HEADER, 0)
        else:
            paper_engine.apply(preset=cfg["preset"], set_backlight=True)

        self._refresh_status_header()
        messagebox.showinfo("PaperScreen", "Configuration saved and applied to your screen!", parent=self.root)

    def _reset_defaults(self):
        if messagebox.askyesno("PaperScreen", "Reset all settings to default factory values?", parent=self.root):
            config.save(dict(config.DEFAULTS))
            self.cfg = config.load()
            self._init_vars()
            self.root.destroy()
            open_settings_gui()


def open_settings_gui() -> int:
    """Launch the Tkinter GUI dialog."""
    # High-DPI awareness must be set BEFORE any Tk window initialization
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    app = SettingsWindow(root)
    root.mainloop()
    return 0


__all__ = [
    "SettingsWindow",
    "open_settings_gui",
]


if __name__ == "__main__":
    sys.exit(open_settings_gui())
