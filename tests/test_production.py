"""Production test suite for PaperScreen: presets, config, logger, signals, Win32 structures."""

import ctypes
import datetime
import os
import tempfile
import unittest
from unittest.mock import patch

from paperscreen import backlight, breaks, color_matrix, config, logger, signals, winlib


class ProductionPresetsTests(unittest.TestCase):
    def test_all_presets_exist_and_generate_5x5(self):
        for name in color_matrix.PRESETS:
            m = color_matrix.preset(name)
            self.assertEqual(len(m), 5, f"{name} must have 5 rows")
            for row in m:
                self.assertEqual(len(row), 5, f"{name} must have 5 cols")

    def test_warm_reading_preset(self):
        m = color_matrix.preset("warm_reading")
        # White should be warm (red > green > blue)
        r, g, b = color_matrix.apply_matrix(m, (1, 1, 1))
        self.assertGreater(r, g)
        self.assertGreater(g, b)
        # Black should be lifted
        br, bg, bb = color_matrix.apply_matrix(m, (0, 0, 0))
        self.assertGreaterEqual(br, 0.08)

    def test_eink_warm_preset(self):
        m = color_matrix.preset("eink_warm")
        # Full desaturation with warm amber tint (r > g > b)
        r, g, b = color_matrix.apply_matrix(m, (0.8, 0.2, 0.1))
        self.assertGreater(r, g)
        self.assertGreater(g, b)
        # White input produces amber paper white
        wr, wg, wb = color_matrix.apply_matrix(m, (1, 1, 1))
        self.assertGreater(wr, wb)
        self.assertLessEqual(wr, 0.95)


    def test_amber_candle_preset(self):
        m = color_matrix.preset("amber_candle")
        # White should produce rich warm amber (r >> g > b) with heavy blue suppression
        wr, wg, wb = color_matrix.apply_matrix(m, (1, 1, 1))
        self.assertGreater(wr, wg)
        self.assertGreater(wg, wb)
        self.assertLess(wb, 0.20, "amber candle must heavily quench blue light for circadian protection")
        # Black should be soft paper floor
        br, bg, bb = color_matrix.apply_matrix(m, (0, 0, 0))
        self.assertGreaterEqual(br, 0.05)

    def test_inverted_paper_preset(self):
        m = color_matrix.preset("inverted_paper")
        # Inverted: black input (0,0,0) -> warm parchment text (~0.8-0.9)
        tr, tg, tb = color_matrix.apply_matrix(m, (0, 0, 0))
        self.assertGreater(tr, 0.75, "black input should map to bright parchment")
        self.assertGreater(tg, 0.70)
        self.assertGreater(tr, tb, "parchment text must be warm")

        # Inverted: white input (1,1,1) -> dark charcoal background (~0.08-0.12)
        br, bg, bb = color_matrix.apply_matrix(m, (1, 1, 1))
        self.assertLess(br, 0.18, "white input should map to dark charcoal background")
        self.assertLess(bg, 0.18)
        self.assertLess(bb, 0.18)

        # Smart Inversion Hue Preservation: Red input stays red, Blue input stays blue!
        rr, rg, rb = color_matrix.apply_matrix(m, (1.0, 0.0, 0.0))
        self.assertGreater(rr, rg, "red input must preserve red dominance")
        self.assertGreater(rr, rb, "red input must preserve red dominance")

        ur, ug, ub = color_matrix.apply_matrix(m, (0.0, 0.0, 1.0))
        self.assertGreater(ub, ur, "blue input must preserve blue dominance")
        self.assertGreater(ub, ug, "blue input must preserve blue dominance")


class ConfigValidationTests(unittest.TestCase):
    def test_all_new_presets_allowed_in_config(self):
        for p in color_matrix.PRESETS:
            clean = config._validate({"preset": p})
            self.assertEqual(clean["preset"], p)

    def test_auto_pause_and_excluded_apps_validation(self):
        clean = config._validate({
            "auto_pause_fullscreen": True,
            "excluded_apps": ["Photoshop.exe", "  Figma.EXE  ", ""],
        })
        self.assertTrue(clean["auto_pause_fullscreen"])
        self.assertEqual(clean["excluded_apps"], ["photoshop.exe", "figma.exe"])

    def test_boolean_config_string_and_type_coercion(self):
        # Strings like "false", "0", "off" must evaluate to False (never truthy Python str)
        clean_false = config._validate({
            "invert_luminance": "false",
            "breaks_enabled": "0",
            "grayscale_smoothing": "off",
            "hotkey_toggle": "no",
        })
        self.assertFalse(clean_false["invert_luminance"])
        self.assertFalse(clean_false["breaks_enabled"])
        self.assertFalse(clean_false["grayscale_smoothing"])
        self.assertFalse(clean_false["hotkey_toggle"])

        # Strings like "true", "1", "yes", "on" must evaluate to True
        clean_true = config._validate({
            "invert_luminance": "true",
            "breaks_enabled": "1",
            "grayscale_smoothing": "on",
            "hotkey_toggle": "yes",
        })
        self.assertTrue(clean_true["invert_luminance"])
        self.assertTrue(clean_true["breaks_enabled"])
        self.assertTrue(clean_true["grayscale_smoothing"])
        self.assertTrue(clean_true["hotkey_toggle"])

        # Invalid string/None falls back to default
        clean_fallback = config._validate({
            "invert_luminance": "invalid_string",
            "breaks_enabled": None,
        })
        self.assertEqual(clean_fallback["invert_luminance"], config.DEFAULTS["invert_luminance"])
        self.assertEqual(clean_fallback["breaks_enabled"], config.DEFAULTS["breaks_enabled"])

    def test_solar_circadian_validation(self):
        clean = config._validate({
            "solar_circadian": True,
            "latitude": 40.71,
            "longitude": -74.01,
        })
        self.assertTrue(clean["solar_circadian"])
        self.assertAlmostEqual(clean["latitude"], 40.71)
        self.assertAlmostEqual(clean["longitude"], -74.01)

    def test_config_save_load_in_temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(config, "config_dir", return_value=tmpdir):
                cfg = dict(config.DEFAULTS)
                cfg["preset"] = "warm_reading"
                cfg["kelvin"] = 3200
                config.save(cfg)
                loaded = config.load()
                self.assertEqual(loaded["preset"], "warm_reading")
                self.assertEqual(loaded["kelvin"], 3200)


class CircadianTests(unittest.TestCase):
    def test_noaa_solar_calculation_valid(self):
        from paperscreen import circadian
        # Test known coordinates (New York City)
        times = circadian.calculate_solar_times(40.71, -74.01, utc_offset_hours=-4.0)
        self.assertFalse(times["polar_night"])
        self.assertFalse(times["polar_day"])
        self.assertIsNotNone(times["sunrise"])
        self.assertIsNotNone(times["sunset"])
        self.assertGreater(times["day_length_hours"], 8.0)
        self.assertLess(times["day_length_hours"], 16.0)

    def test_leap_year_solar_calculation(self):
        from paperscreen import circadian
        # In leap year 2028 (Feb 29)
        leap_date = datetime.date(2028, 2, 29)
        times = circadian.calculate_solar_times(40.71, -74.01, date=leap_date, utc_offset_hours=-5.0)
        self.assertIsNotNone(times["sunrise"])
        self.assertIsNotNone(times["sunset"])
        self.assertFalse(times["polar_night"])

    def test_solar_is_night_logic(self):
        from paperscreen import circadian
        # Midday time (12:00 PM local) should not be night in temperate regions
        noon = datetime.datetime(2026, 6, 21, 12, 0, 0)
        # Deep night (2:00 AM local) should definitely be night
        night = datetime.datetime(2026, 6, 21, 2, 0, 0)
        
        cfg = {"latitude": 40.71, "longitude": -74.01}
        self.assertFalse(circadian.is_solar_night(noon, cfg))
        self.assertTrue(circadian.is_solar_night(night, cfg))


class LoggerTests(unittest.TestCase):
    def test_logger_writes_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(logger, "config_dir", return_value=tmpdir):
                logger.info("Test info message")
                logger.warn("Test warning message")
                logger.error("Test error message")
                log_file = logger.log_path()
                self.assertTrue(os.path.isfile(log_file))
                with open(log_file, "r", encoding="utf-8") as f:
                    content = f.read()
                self.assertIn("Test info message", content)
                self.assertIn("Test warning message", content)
                self.assertIn("Test error message", content)

    def test_logger_console_streaming_and_tracebacks(self):
        import io
        fake_stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(logger, "config_dir", return_value=tmpdir):
                with patch("sys.stderr", fake_stderr):
                    logger.enable_console_logging(level="DEBUG")
                    self.assertTrue(logger.is_console_logging_enabled())
                    try:
                        raise ValueError("Simulated crash")
                    except ValueError as exc:
                        logger.error("Crash encountered", exc)
                    
                    stderr_content = fake_stderr.getvalue()
                    self.assertIn("Crash encountered", stderr_content)
                    self.assertIn("ValueError: Simulated crash", stderr_content)
                    self.assertIn("Traceback (most recent call last):", stderr_content)
                    
                    logger.disable_console_logging()
                    self.assertFalse(logger.is_console_logging_enabled())



class SignalsTests(unittest.TestCase):
    def test_signals_journal_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(signals, "config_dir", return_value=tmpdir):
                signals.save({"active": True, "preset": "sepia", "pid": 1234})
                data = signals.load()
                self.assertTrue(data.get("active"))
                self.assertEqual(data.get("preset"), "sepia")
                self.assertEqual(data.get("pid"), 1234)

                signals.update(preset="warm_reading")
                data2 = signals.load()
                self.assertEqual(data2.get("preset"), "warm_reading")
                self.assertEqual(data2.get("pid"), 1234)

                signals.clear()
                data3 = signals.load()
                self.assertEqual(data3, {})


class Win32StructureAndTimingTests(unittest.TestCase):
    def test_magcoloreffect_size(self):
        # 5x5 float matrix = 25 * 4 = 100 bytes
        self.assertEqual(ctypes.sizeof(winlib.MAGCOLOREFFECT), 100)

    def test_physical_monitor_size(self):
        # HANDLE (8 bytes on 64-bit) + WCHAR*128 (256 bytes) = 264 bytes
        self.assertEqual(ctypes.sizeof(winlib.PHYSICAL_MONITOR), 264)

    def test_get_tick_count_64_returns_positive(self):
        tick = winlib.get_tick_count_64()
        self.assertIsInstance(tick, int)
        self.assertGreater(tick, 0)

    def test_idle_seconds_non_negative(self):
        idle = breaks._user_idle_seconds()
        self.assertIsInstance(idle, float)
        self.assertGreaterEqual(idle, 0.0)

    def test_advanced_color_info_query(self):
        # Must return a list (empty or populated with dicts) without crashing
        res = winlib.get_advanced_color_info()
        self.assertIsInstance(res, list)
        if res:
            item = res[0]
            self.assertIn("name", item)
            self.assertIn("hdr_supported", item)
            self.assertIn("hdr_enabled", item)
    def test_foreground_fullscreen_detection(self):
        # Must return a boolean without throwing an exception
        res = winlib.is_foreground_fullscreen()
        self.assertIsInstance(res, bool)

    def test_foreground_process_name_detection(self):
        # Must return a string without throwing an exception
        res = winlib.get_foreground_process_name()
        self.assertIsInstance(res, str)



class BacklightLogicTests(unittest.TestCase):
    def test_list_monitors_returns_list(self):
        mons = backlight.list_monitors()
        self.assertIsInstance(mons, list)
        for m in mons:
            self.assertIn("name", m)
            self.assertIn("id", m)
            self.assertIn("ddc", m)
            self.assertIn("method", m)


class TrayStructureTests(unittest.TestCase):
    def test_guid_structure(self):
        from paperscreen import tray
        g = tray.GUID()
        self.assertEqual(ctypes.sizeof(g), 16)

    def test_notifyicondata_structure(self):
        from paperscreen import tray
        nid = tray.NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(tray.NOTIFYICONDATAW)
        self.assertEqual(nid.cbSize, ctypes.sizeof(tray.NOTIFYICONDATAW))
        self.assertGreaterEqual(nid.cbSize, 500)


class CliSubcommandTests(unittest.TestCase):
    def test_cli_toggle_dispatches(self):
        from paperscreen import cli
        with patch("paperscreen.paper_engine.status", return_value={"engine_active": False}), \
             patch("paperscreen.paper_engine.apply", return_value={"preset": "paper"}) as mock_apply:
            rc = cli.main(["toggle"])
            self.assertEqual(rc, 0)
            mock_apply.assert_called_once()

    def test_cli_toggle_when_active(self):
        from paperscreen import cli
        with patch("paperscreen.paper_engine.status", return_value={"engine_active": True}), \
             patch("paperscreen.paper_engine.release", return_value={}) as mock_release:
            rc = cli.main(["toggle"])
            self.assertEqual(rc, 0)
            mock_release.assert_called_once()

    def test_cli_cycle_preset(self):
        from paperscreen import cli
        with patch("paperscreen.paper_engine.status", return_value={"engine_active": True, "preset": "paper"}), \
             patch("paperscreen.signals.update") as mock_update:
            rc = cli.main(["cycle"])
            self.assertEqual(rc, 0)
            mock_update.assert_called_once_with(active=True, preset="sepia")


if __name__ == "__main__":
    unittest.main()


