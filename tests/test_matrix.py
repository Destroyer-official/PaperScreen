"""Unit tests for the pure matrix math and config (no win32 required)."""

import unittest

from paperscreen import color_matrix, config


class MatrixTests(unittest.TestCase):
    def test_identity_is_neutral(self):
        m = color_matrix.identity()
        for rgb in [(0, 0, 0), (1, 1, 1), (0.5, 0.5, 0.5), (0.2, 0.7, 0.9)]:
            self.assertEqual(color_matrix.apply_matrix(m, rgb), rgb)

    def test_black_lifted_to_charcoal(self):
        m = color_matrix.preset("paper")
        out = color_matrix.apply_matrix(m, (0, 0, 0))
        for ch in out:
            self.assertGreaterEqual(ch, 0.05, "black floor should lift to charcoal")
            self.assertLess(ch, 0.25)

    def test_white_not_blazing(self):
        m = color_matrix.preset("paper")
        out = color_matrix.apply_matrix(m, (1, 1, 1))
        for ch in out:
            self.assertLessEqual(ch, 0.96)
            self.assertGreater(ch, 0.5)

    def test_white_is_warm_not_blue(self):
        m = color_matrix.preset("paper")
        r, g, b = color_matrix.apply_matrix(m, (1, 1, 1))
        self.assertGreaterEqual(r, b, "paper white must not be cooler than neutral")
        self.assertGreaterEqual(g, b)

    def test_paper_reduces_saturation(self):
        # pure red should not stay pure red
        m = color_matrix.preset("paper")
        r, g, b = color_matrix.apply_matrix(m, (1, 0, 0))
        self.assertGreater(g, 0.02, "red channel should bleed into green after desat")
        self.assertGreater(b, 0.01, "red channel should bleed into blue after desat")

    def test_eink_is_gray(self):
        m = color_matrix.preset("eink")
        r, g, b = color_matrix.apply_matrix(m, (0.9, 0.3, 0.1))
        # after full desaturation, warm input maps to same gray for each channel set
        # check a strong color desaturates: r close to g+b weighted
        self.assertLess(abs(r - b), 0.15)

    def test_presets_differ(self):
        a = color_matrix.preset("paper")
        b = color_matrix.preset("sepia")
        self.assertNotEqual(a, b)

    def test_structure_rows_valid(self):
        for name in ("paper", "sepia", "eink"):
            m = color_matrix.preset(name)
            self.assertEqual(list(m[3]), [0, 0, 0, 1, 0], f"{name}: alpha row")
            self.assertEqual(m[4][4], 1.0, f"{name}: translation row terminator")
            self.assertEqual(m[4][3], 0.0)

    def test_kelvin_bounds(self):
        self.assertEqual(color_matrix.kelvin_to_rgb(500), color_matrix.kelvin_to_rgb(1000))
        self.assertEqual(color_matrix.kelvin_to_rgb(20000), color_matrix.kelvin_to_rgb(15000))

    def test_gains_norm(self):
        r, g, b = color_matrix.tint_gains(4600)
        self.assertAlmostEqual(max(r, g, b), 1.0, "gains normalized so no channel clips")
        self.assertLess(b, 1.0, "warmer => blue attenuated")
        self.assertGreaterEqual(r, g, "warm point keeps red strongest")

    def test_luminance_scaling(self):
        base = color_matrix.paper_matrix(luminance=1.0)
        dim = color_matrix.paper_matrix(luminance=0.5)
        for rgb in [(1, 1, 1), (0.5, 0.5, 0.5), (0, 0, 0)]:
            a = color_matrix.apply_matrix(base, rgb)
            b = color_matrix.apply_matrix(dim, rgb)
            for ch in range(3):
                self.assertLess(b[ch], a[ch] + 1e-6, "dimming must reduce output")
                if a[ch] > 0.01:
                    self.assertAlmostEqual(b[ch], a[ch] * 0.5, places=5)

    def test_nightpaper_dimmer_than_paper(self):
        day = color_matrix.apply_matrix(color_matrix.preset("paper"), (1, 1, 1))
        night = color_matrix.apply_matrix(color_matrix.preset("nightpaper"), (1, 1, 1))
        self.assertLess(sum(night), sum(day), "nightpaper must be dimmer overall")

    def test_lerp_endpoints(self):
        a = color_matrix.identity()
        b = color_matrix.preset("paper")
        self.assertEqual(color_matrix.lerp_matrix(a, b, 0.0), a)
        self.assertEqual(color_matrix.lerp_matrix(a, b, 1.0), b)

    def test_ease_monotonic(self):
        vals = [color_matrix.ease(i / 20) for i in range(21)]
        self.assertEqual(vals[0], 0.0)
        self.assertEqual(vals[-1], 1.0)
        for i in range(1, len(vals)):
            self.assertGreaterEqual(vals[i], vals[i - 1])

    def test_auto_preset_config_valid(self):
        clean = config._validate({"preset": "auto"})
        self.assertEqual(clean["preset"], "auto")
        clean2 = config._validate({"preset": "nightpaper"})
        self.assertEqual(clean2["preset"], "nightpaper")


class ConfigTests(unittest.TestCase):
    def test_defaults_valid(self):
        clean = config._validate({})
        self.assertEqual(clean, config.DEFAULTS)

    def test_round_trip(self):
        cfg = dict(config.DEFAULTS)
        cfg["kelvin"] = 5000
        clean = config._validate(cfg)
        self.assertEqual(clean["kelvin"], 5000)
        cfg2 = config._validate(clean)
        self.assertEqual(clean, cfg2)

    def test_clamps(self):
        clean = config._validate({"kelvin": 99999, "desaturation": 12, "break_interval_minutes": -5})
        self.assertEqual(clean["kelvin"], 15000)
        self.assertEqual(clean["desaturation"], 1.0)
        self.assertEqual(clean["break_interval_minutes"], 1)

    def test_unknown_keys_dropped(self):
        clean = config._validate({"malware": True})
        self.assertNotIn("malware", clean)

    def test_night_window(self):
        import datetime
        # 19..07 wraps midnight
        self.assertTrue(config.is_night(datetime.datetime(2026, 1, 1, 22, 0)))
        self.assertTrue(config.is_night(datetime.datetime(2026, 1, 1, 3, 0)))
        self.assertFalse(config.is_night(datetime.datetime(2026, 1, 1, 12, 0)))


if __name__ == "__main__":
    unittest.main()
