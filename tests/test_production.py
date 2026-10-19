"""Production test suite for PaperScreen: presets, config, logger, signals, Win32 structures."""

import ctypes
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


if __name__ == "__main__":
    unittest.main()
