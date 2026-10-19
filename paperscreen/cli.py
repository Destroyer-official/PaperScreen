"""Command-line interface: python -m paperscreen <command> [options]."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import backlight, breaks, cleartype, color_matrix, config, logger, paper_engine


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


ALL_PRESETS = [
    "paper",
    "sepia",
    "warm_reading",
    "eink",
    "eink_warm",
    "nightpaper",
    "inverted_paper",
    "auto",
]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="paperscreen",
        description="Make your monitor behave like paper (Windows).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_on = sub.add_parser("on", help="activate paper mode (runs daemon with system tray)")
    p_on.add_argument("--preset", choices=ALL_PRESETS, default=None)
    p_on.add_argument("--no-backlight", action="store_true", help="skip DDC/WMI backlight change")

    p_off = sub.add_parser("off", help="restore normal display")

    sub.add_parser("status", help="current engine + monitor state")
    sub.add_parser("monitors", help="list monitors and DDC/WMI brightness")

    p_br = sub.add_parser("break", help="run 20-20-20 break timer")
    p_br.add_argument("--interval", type=int, default=None, help="minutes between breaks")
    p_br.add_argument("--duration", type=int, default=None, help="break length seconds")
    p_br.add_argument("--detached", action="store_true", help="run in background (toast reminders)")
    p_br.add_argument("--console", action="store_true", help="console output instead of toasts")

    sub.add_parser("doctor", help="diagnose APIs, DDC, HDR, matrix round-trip, restore")

    p_matrix = sub.add_parser("matrix", help="preview a preset matrix")
    p_matrix.add_argument(
        "--preset",
        choices=["paper", "sepia", "warm_reading", "eink", "eink_warm", "nightpaper", "inverted_paper", "off"],
        default="paper",
    )

    p_auto = sub.add_parser("autostart", help="start paper mode + break timer when you log in")
    p_auto.add_argument("--enable", action="store_true")
    p_auto.add_argument("--disable", action="store_true")

    p_cfg = sub.add_parser("config")
    p_cfg.add_argument(
        "--set", action="append", default=None, metavar="KEY=VALUE",
        help="set config key (repeatable), then show config",
    )
    p_cfg.add_argument("--gui", action="store_true", help="open visual preferences GUI")

    sub.add_parser("toggle", help="toggle paper mode on/off instantly")
    sub.add_parser("settings", help="open visual preferences & calibration GUI")

    p_log = sub.add_parser("log", help="view recent PaperScreen logs")
    p_log.add_argument("-n", "--lines", type=int, default=30, help="number of lines to show")

    sub.add_parser("daemon", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    if args.command == "daemon":
        from . import daemon
        return daemon.daemon_main()

    if args.command == "toggle":
        st = paper_engine.status()
        if st.get("engine_active"):
            report = paper_engine.release()
            print("PaperScreen turned OFF.")
        else:
            report = paper_engine.apply()
            print(f"PaperScreen turned ON (preset: {report.get('preset')}).")
        return 0

    if args.command == "settings":
        from . import settings_gui
        return settings_gui.open_settings_gui()

    if args.command == "on":
        report = paper_engine.apply(preset=args.preset, set_backlight=not args.no_backlight)
        _print(report)
        return 0

    if args.command == "off":
        _print(paper_engine.release())
        return 0

    if args.command == "status":
        _print(paper_engine.status())
        return 0

    if args.command == "monitors":
        _print(backlight.list_monitors())
        return 0

    if args.command == "config":
        if getattr(args, "gui", False):
            from . import settings_gui
            return settings_gui.open_settings_gui()
        if args.set:
            cfg = config.load()
            for pair in args.set:
                if "=" not in pair:
                    print(f"bad --set syntax: {pair!r} (expected KEY=VALUE)", file=sys.stderr)
                    return 2
                k, v = pair.split("=", 1)
                if k not in config.DEFAULTS:
                    print(f"unknown key {k!r}; valid: {sorted(config.DEFAULTS)}", file=sys.stderr)
                    return 2
                try:
                    cfg[k] = json.loads(v)
                except ValueError:
                    cfg[k] = v
                if isinstance(cfg[k], str) and cfg[k].lower() in ("true", "false"):
                    cfg[k] = cfg[k].lower() == "true"
            config.save(cfg)
        _print(config.load())
        return 0

    if args.command == "break":
        cfg = config.load()
        interval = args.interval or cfg["break_interval_minutes"]
        duration = args.duration or cfg["break_duration_seconds"]
        if args.detached:
            rc = breaks.run_detached(interval, duration)
            print(
                "Break timer started in background (toast reminders)."
                if rc == 0
                else "Failed to start background timer.",
                file=sys.stderr if rc else sys.stdout,
            )
            return rc
        return breaks.run(interval, duration, console=args.console)

    if args.command == "autostart":
        return autostart(args.enable, args.disable)

    if args.command == "doctor":
        return doctor()

    if args.command == "matrix":
        m = color_matrix.preset(args.preset)
        print(f"preset {args.preset!r}:")
        for row in m:
            print("  " + " ".join(f"{v:6.3f}" for v in row))
        print("  black ->", tuple(round(v, 3) for v in color_matrix.apply_matrix(m, (0, 0, 0))))
        print("  white ->", tuple(round(v, 3) for v in color_matrix.apply_matrix(m, (1, 1, 1))))
        print("  gray  ->", tuple(round(v, 3) for v in color_matrix.apply_matrix(m, (0.5, 0.5, 0.5))))
        return 0

    if args.command == "log":
        path = logger.log_path()
        if not os.path.isfile(path):
            print(f"No log file found at {path}")
            return 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines[-args.lines:]:
                sys.stdout.write(line)
            return 0
        except OSError as exc:
            print(f"Failed to read log: {exc}", file=sys.stderr)
            return 1

    return 1


def autostart(enable: bool, disable: bool) -> int:
    """Manage HKCU Run entry: starts daemon + break timer at login."""
    if enable == disable:
        print("Specify exactly one of --enable / --disable", file=sys.stderr)
        return 2
    import winreg

    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    VALUE_NAME = "PaperScreen"
    if disable:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, VALUE_NAME)
            print("Autostart disabled.")
            return 0
        except FileNotFoundError:
            print("Autostart was not enabled.")
            return 0
        except OSError as exc:
            print(f"Failed: {exc}", file=sys.stderr)
            return 1

    # enable
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pythonw if os.path.isfile(pythonw) else sys.executable
    cmd = f'"{exe}" -m paperscreen.autostart_helper'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, cmd)
        print(f"Autostart enabled (runs at login: {cmd})")
        return 0
    except OSError as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1


def doctor() -> int:
    """Live diagnostics with guaranteed restore."""
    from . import winlib

    print("== PaperScreen doctor ==")
    ok = True

    # 1) Magnification API
    try:
        winlib.mag_initialize()
        print("[ok] Magnification API initialized")
    except Exception as exc:
        print(f"[FAIL] Magnification API: {exc}")
        return 1

    # 2) matrix round-trip
    try:
        paper = color_matrix.preset("paper")
        winlib.mag_set_color_effect(paper)
        after = winlib.mag_get_color_effect()
        match = all(abs(after[r][c] - paper[r][c]) < 1e-6 for r in range(5) for c in range(5))
        print(f"[{'ok' if match else 'FAIL'}] matrix set/get round-trip")
        ok = ok and match
        winlib.mag_set_color_effect(color_matrix.identity())
        ident = winlib.mag_get_color_effect()
        ident_ok = all(abs(ident[r][c] - (1.0 if r == c else 0.0)) < 1e-6 for r in range(5) for c in range(5))
        print(f"[{'ok' if ident_ok else 'WARN'}] identity restored")
    except Exception as exc:
        print(f"[FAIL] matrix round-trip: {exc}")
        ok = False

    # 3) DDC / WMI monitors
    try:
        mons = backlight.list_monitors()
        if mons:
            for m in mons:
                state = f"brightness={m['brightness']}% via {m.get('method', 'unknown').upper()}" if m.get("brightness") is not None else "no brightness control"
                status_tag = "ok" if m.get("brightness") is not None else "warn"
                print(f"[{status_tag}] monitor {m['name']!r} ({m['id']}): {state}")
        else:
            print("[warn] no physical monitors or WMI panels found (backlight sync unavailable)")
    except Exception as exc:
        print(f"[warn] Backlight hardware enumeration: {exc}")

    # 4) HDR / Advanced Color
    try:
        hdr_info = winlib.get_advanced_color_info()
        if hdr_info:
            for h in hdr_info:
                if h["hdr_enabled"]:
                    print(f"[warn] monitor {h['name']!r}: HDR is active ({h['bits_per_channel']}-bit) - DWM wide color mapping")
                else:
                    print(f"[ok] monitor {h['name']!r}: SDR ({h['bits_per_channel']}-bit) optimal for matrix transformation")
        else:
            print("[info] advanced color query not supported or no paths found (defaulting to SDR)")
    except Exception as exc:
        print(f"[info] HDR query: {exc}")

    # 5) font smoothing
    try:
        st = cleartype.status()
        print(f"[ok] font smoothing: {st.get('mode')}")
    except Exception as exc:
        print(f"[warn] font smoothing query: {exc}")

    # 6) toasts
    from . import toasts
    if toasts.show("PaperScreen doctor", "Toast test — if you can read this, break reminders will work."):
        print("[ok] toast notifications")
    else:
        print("[warn] toasts unavailable (break reminders fall back to console)")

    # 7) conflicts
    conflicts = []
    try:
        import subprocess
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq flux.exe"], capture_output=True, text=True).stdout
        if "flux.exe" in out:
            conflicts.append("f.lux (flux.exe) is running — stacked color transforms!")
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq LightBulb.exe"], capture_output=True, text=True).stdout
        if "LightBulb.exe" in out:
            conflicts.append("LightBulb is running — stacked color transforms!")
    except Exception:
        pass
    if conflicts:
        for c in conflicts:
            print(f"[warn] conflict: {c}")
    else:
        print("[ok] no known gamma-tool conflicts running")

    # 8) autostart status
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            winreg.QueryValueEx(k, "PaperScreen")
        print("[ok] autostart is enabled")
    except FileNotFoundError:
        print("[info] autostart not configured (optional: paperscreen autostart --enable)")

    # 9) log file
    print(f"[info] log file: {logger.log_path()}")

    print("== done ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
