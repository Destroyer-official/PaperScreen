"""Reliability, failure-path, and transactional recovery test suite for PaperScreen.

Covers:
- Transactional backlight restoration and partial failure retention
- Rollback safety on interrupted activation
- Display API brightness range normalization (e.g. non-0..100 min/max ranges)
- Cross-process ClearType persistence and restoration
- Daemon startup timeout detection and failure reporting
- State journal concurrency and mutex synchronization
- Strict achromatic neutrality of E-Ink preset across diverse inputs
- Inverted paper matrix gamut response and chromatic distinction
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from paperscreen import backlight, cleartype, color_matrix, config, paper_engine, signals, winlib


class TransactionalBacklightTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.patch_config = patch.object(config, "config_dir", return_value=self.tmpdir.name)
        self.patch_signals = patch.object(signals, "config_dir", return_value=self.tmpdir.name)
        self.patch_config.start()
        self.patch_signals.start()
        signals.clear()

    def tearDown(self):
        self.patch_signals.stop()
        self.patch_config.stop()
        self.tmpdir.cleanup()

    def test_partial_failure_retains_failed_monitor_in_journal(self):
        """If 1 of 2 monitors fails during restoration, the failed monitor must be kept in journal."""
        # Setup initial state in journal with 2 monitors
        signals.update(
            backlight_previous={
                "Dell U2720Q #1": {"original": 80, "status": "active"},
                "LG UltraFine #2": {"original": 65, "status": "active"},
            },
            backlight_level=30,
        )

        mock_monitors = [
            (101, "Dell U2720Q"),
            (102, "LG UltraFine"),
        ]

        def fake_ddc_set(handle, level):
            # Monitor 1 succeeds, monitor 2 fails
            if handle == 101:
                return True
            return False

        with patch("paperscreen.winlib.open_physical_monitors") as mock_open, \
             patch("paperscreen.winlib.ddc_set_brightness", side_effect=fake_ddc_set):
            
            mock_open.return_value.__enter__.return_value = mock_monitors
            mock_open.return_value.__exit__.return_value = None

            report = backlight.restore()

            self.assertEqual(len(report["restored"]), 1)
            self.assertEqual(report["restored"][0]["name"], "Dell U2720Q #1")
            self.assertEqual(len(report["failed"]), 1)
            self.assertEqual(report["failed"][0]["name"], "LG UltraFine #2")
            self.assertIn("LG UltraFine #2", report["pending"])

            # Verify on-disk journal retained LG UltraFine
            j = signals.load()
            self.assertIn("LG UltraFine #2", j.get("backlight_previous", {}))
            self.assertNotIn("Dell U2720Q #1", j.get("backlight_previous", {}))

    def test_activation_rollback_on_failure(self):
        """If monitor 2 fails during activation with rollback_on_failure, monitor 1 is rolled back."""
        mock_monitors = [
            (101, "MonitorA"),
            (102, "MonitorB"),
        ]

        calls = []

        def fake_get_b(handle):
            return 70 if handle == 101 else 60

        def fake_set_b(handle, level):
            calls.append((handle, level))
            if handle == 101:
                return True
            return False  # monitor 2 fails

        with patch("paperscreen.winlib.open_physical_monitors") as mock_open, \
             patch("paperscreen.winlib.ddc_get_brightness", side_effect=fake_get_b), \
             patch("paperscreen.winlib.ddc_set_brightness", side_effect=fake_set_b):

            mock_open.return_value.__enter__.return_value = mock_monitors
            mock_open.return_value.__exit__.return_value = None

            report = backlight.set_brightness(30, remember=True, rollback_on_failure=True)

            self.assertTrue(report.get("rolled_back"))
            self.assertEqual(report["set"], [])
            # Verify monitor 1 was restored back to 70
            self.assertIn((101, 70), calls)

    def test_restore_backlight_on_exit_config_respected(self):
        """When restore_backlight_on_exit is False, paper_engine.release skips backlight restoration."""
        cfg = dict(config.DEFAULTS)
        cfg["restore_backlight_on_exit"] = False
        config.save(cfg)

        with patch("paperscreen.backlight.restore") as mock_restore, \
             patch("paperscreen.spawn.is_daemon_running", return_value=False), \
             patch("paperscreen.winlib.mag_set_color_effect"):
            
            report = paper_engine.release()
            mock_restore.assert_not_called()
            self.assertIn("skipped", report["backlight"])


class BrightnessNormalizationTests(unittest.TestCase):
    def test_ddc_set_brightness_maps_non_standard_ranges(self):
        """Verify 0..100 logical percentage is scaled to monitor's physical min/max."""
        # Monitor with min=20, max=80
        # 50% logical -> 20 + 0.5*(80-20) = 50
        # 100% logical -> 80
        # 0% logical -> 20
        captured_vals = []

        def fake_set_brightness_api(handle, val):
            captured_vals.append(val.value if hasattr(val, "value") else val)
            return True

        with patch("paperscreen.winlib.ddc_get_raw_brightness", return_value=(20, 50, 80)), \
             patch.object(winlib.dxva2(), "SetMonitorBrightness", side_effect=fake_set_brightness_api):
            
            winlib.ddc_set_brightness(999, 50)
            self.assertEqual(captured_vals[-1], 50)

            winlib.ddc_set_brightness(999, 100)
            self.assertEqual(captured_vals[-1], 80)

            winlib.ddc_set_brightness(999, 0)
            self.assertEqual(captured_vals[-1], 20)

    def test_ddc_set_brightness_maps_255_scale(self):
        """Verify 0..100 logical percentage is scaled to 0..255 range."""
        captured_vals = []

        def fake_set(handle, val):
            captured_vals.append(val.value if hasattr(val, "value") else val)
            return True

        with patch("paperscreen.winlib.ddc_get_raw_brightness", return_value=(0, 100, 255)), \
             patch.object(winlib.dxva2(), "SetMonitorBrightness", side_effect=fake_set):
            
            winlib.ddc_set_brightness(999, 50)
            self.assertEqual(captured_vals[-1], 128)

            winlib.ddc_set_brightness(999, 100)
            self.assertEqual(captured_vals[-1], 255)


class ClearTypeCrossProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.patch_signals = patch.object(signals, "config_dir", return_value=self.tmpdir.name)
        self.patch_signals.start()
        signals.clear()
        cleartype._saved_state.clear()

    def tearDown(self):
        self.patch_signals.stop()
        self.tmpdir.cleanup()

    def test_cleartype_persisted_to_journal_and_restored_across_process(self):
        """Enabling grayscale persists original state so separate process can restore it."""
        with patch("paperscreen.winlib.get_font_smoothing_type", return_value=winlib.FE_FONTSMOOTHINGCLEARTYPE), \
             patch("paperscreen.winlib.set_font_smoothing_type", return_value=True):
            
            res = cleartype.enable_grayscale_smoothing()
            self.assertTrue(res["ok"])
            self.assertEqual(res["previous"], winlib.FE_FONTSMOOTHINGCLEARTYPE)

            # Check journal persisted it
            j = signals.load()
            self.assertEqual(j.get("cleartype_previous"), winlib.FE_FONTSMOOTHINGCLEARTYPE)

            # Simulate process exit by emptying in-memory state
            cleartype._saved_state.clear()

            # Now restore from "new" process
            restored = cleartype.restore_previous()
            self.assertTrue(restored["ok"])
            self.assertTrue(restored["changed"])
            self.assertEqual(restored["restored"], winlib.FE_FONTSMOOTHINGCLEARTYPE)

            # Journal is now cleaned up
            j2 = signals.load()
            self.assertNotIn("cleartype_previous", j2)


class DaemonLifecycleAndTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.patch_config = patch.object(config, "config_dir", return_value=self.tmpdir.name)
        self.patch_signals = patch.object(signals, "config_dir", return_value=self.tmpdir.name)
        self.patch_config.start()
        self.patch_signals.start()
        signals.clear()

    def tearDown(self):
        self.patch_signals.stop()
        self.patch_config.stop()
        self.tmpdir.cleanup()

    def test_daemon_startup_timeout_reported_as_failure(self):
        """If spawned daemon fails to initialize within timeout, apply() returns failed status."""
        with patch("paperscreen.spawn.is_daemon_running", return_value=False), \
             patch("paperscreen.spawn.start_detached", return_value=5555), \
             patch("paperscreen.paper_engine.MAX_DAEMON_WAIT", 0.2):
            
            rep = paper_engine.apply(set_backlight=False)
            self.assertEqual(rep["status"], "failed")
            self.assertIn("timeout", rep["matrix"])

            # Verify journal reflects failed status
            j = signals.load()
            self.assertFalse(j.get("active"))
            self.assertEqual(j.get("status"), "failed")


class StateJournalConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.patch_signals = patch.object(signals, "config_dir", return_value=self.tmpdir.name)
        self.patch_signals.start()
        signals.clear()

    def tearDown(self):
        self.patch_signals.stop()
        self.tmpdir.cleanup()

    def test_concurrent_journal_updates_no_lost_keys(self):
        """Simulate concurrent threads updating distinct fields via update() with mutex locking."""
        errors = []

        def worker(key, val):
            try:
                for _ in range(10):
                    signals.update(**{key: val})
                    time.sleep(0.005)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(f"worker_{i}", i * 10))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        final_state = signals.load()
        for i in range(5):
            self.assertIn(f"worker_{i}", final_state)
            self.assertEqual(final_state[f"worker_{i}"], i * 10)


class ColorMatrixAchromaticAndGamutTests(unittest.TestCase):
    def test_eink_is_strictly_achromatic_across_inputs(self):
        """E-Ink preset must produce identical R, G, B outputs for ANY input color."""
        m = color_matrix.preset("eink")
        self.assertTrue(color_matrix.is_achromatic(m))

        gamut_samples = [
            (1.0, 0.0, 0.0),   # Red
            (0.0, 1.0, 0.0),   # Green
            (0.0, 0.0, 1.0),   # Blue
            (1.0, 1.0, 0.0),   # Yellow
            (0.0, 1.0, 1.0),   # Cyan
            (1.0, 0.0, 1.0),   # Magenta
            (0.2, 0.7, 0.4),   # Arbitrary mixed
            (0.9, 0.9, 0.9),   # Near white
            (0.1, 0.1, 0.1),   # Near black
        ]
        for inp in gamut_samples:
            r, g, b = color_matrix.apply_matrix(m, inp)
            self.assertAlmostEqual(r, g, places=5, msg=f"Channels must match for {inp}")
            self.assertAlmostEqual(g, b, places=5, msg=f"Channels must match for {inp}")

    def test_inverted_paper_matrix_gamut_contrast_and_distinction(self):
        """Inverted paper matrix maps light to dark, dark to light, and maintains chromatic identity."""
        m = color_matrix.preset("inverted_paper")

        # White input -> Dark background
        w_out = color_matrix.apply_matrix(m, (1.0, 1.0, 1.0))
        self.assertLess(max(w_out), 0.20)

        # Black input -> Light parchment text
        b_out = color_matrix.apply_matrix(m, (0.0, 0.0, 0.0))
        self.assertGreater(min(b_out), 0.60)

        # Red retains red dominance over green and blue
        r_out = color_matrix.apply_matrix(m, (1.0, 0.0, 0.0))
        self.assertGreater(r_out[0], r_out[1])
        self.assertGreater(r_out[0], r_out[2])

        # Blue retains blue dominance over red and green
        u_out = color_matrix.apply_matrix(m, (0.0, 0.0, 1.0))
        self.assertGreater(u_out[2], u_out[0])
        self.assertGreater(u_out[2], u_out[1])


class CorruptJournalRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.patch_signals = patch.object(signals, "config_dir", return_value=self.tmpdir.name)
        self.patch_signals.start()
        signals.clear()

    def tearDown(self):
        self.patch_signals.stop()
        self.tmpdir.cleanup()

    def test_corrupt_json_is_backed_up_and_recovered(self):
        """When state.json contains invalid/corrupted bytes, it is moved to .corrupt and returns {}."""
        p = signals.state_path()
        with open(p, "w", encoding="utf-8") as f:
            f.write("{this is not valid json content!!!")

        data = signals.load()
        self.assertEqual(data, {})

        # Verify that state.json.corrupt exists and contains the unparseable content
        corrupt_backup = f"{p}.corrupt"
        import os
        self.assertTrue(os.path.isfile(corrupt_backup))
        with open(corrupt_backup, "r", encoding="utf-8") as f:
            self.assertIn("this is not valid json", f.read())


class WinlibSystemParametersInfoTests(unittest.TestCase):
    def test_set_font_smoothing_type_passes_c_void_p(self):
        """Verify set_font_smoothing_type dispatches pointer-width c_void_p value to SystemParametersInfoW."""
        import ctypes
        from unittest.mock import MagicMock

        mock_user32 = MagicMock()
        mock_user32.SystemParametersInfoW.return_value = 1

        with patch("paperscreen.winlib.user32", return_value=mock_user32):
            ok = winlib.set_font_smoothing_type(winlib.FE_FONTSMOOTHINGCLEARTYPE)
            self.assertTrue(ok)
            mock_user32.SystemParametersInfoW.assert_called_once()
            args = mock_user32.SystemParametersInfoW.call_args[0]
            # args: (SPI_SETFONTSMOOTHINGTYPE, 0, pvParam, flags)
            self.assertEqual(args[0], 0x200B)
            self.assertEqual(args[1], 0)
            self.assertIsInstance(args[2], ctypes.c_void_p)
            self.assertEqual(args[2].value, 2)


class WinlibGammaRampPerMonitorTests(unittest.TestCase):
    def test_gamma_ramp_creates_per_monitor_dc(self):
        """Verify set_gamma_ramp enumerates each monitor and creates isolated DCs via CreateDCW."""
        from unittest.mock import MagicMock

        mock_user32 = MagicMock()
        mock_gdi32 = MagicMock()

        # Simulate 2 monitors
        monitors = [
            (1001, None, None),
            (1002, None, None),
        ]

        def fake_get_mon_info(hmon, mi_ref):
            mi = getattr(mi_ref, "_obj", mi_ref)
            mi.szDevice = "\\\\.\\DISPLAY1" if hmon == 1001 else "\\\\.\\DISPLAY2"
            return True

        mock_user32.GetMonitorInfoW.side_effect = fake_get_mon_info
        mock_gdi32.CreateDCW.side_effect = lambda dev, dev2, drv, init: 9999 + (1 if "1" in dev else 2)
        mock_gdi32.SetDeviceGammaRamp.return_value = True

        with patch("paperscreen.winlib.enum_monitor_handles", return_value=monitors), \
             patch("paperscreen.winlib.user32", return_value=mock_user32), \
             patch("paperscreen.winlib.gdi32", return_value=mock_gdi32):

            ok = winlib.set_gamma_ramp((1.0, 1.0, 1.0))
            self.assertTrue(ok)
            self.assertEqual(mock_gdi32.CreateDCW.call_count, 2)
            self.assertEqual(mock_gdi32.DeleteDC.call_count, 2)


class SessionLockUnlockTests(unittest.TestCase):
    def test_session_lock_unlock_matrix_reversion(self):
        """CMD_SESSION_LOCK reverts matrix to neutral identity; CMD_SESSION_UNLOCK reapplies preset."""
        from paperscreen.daemon import Daemon
        from paperscreen import tray

        d = Daemon()
        d.current_preset = "sepia"
        d.current_night = False

        with patch("paperscreen.winlib.mag_set_color_effect") as mock_set_eff, \
             patch("paperscreen.signals.load", return_value={"active": True, "preset": "sepia"}):

            # Simulate session lock (Win+L)
            d.handle_menu_command(tray.CMD_SESSION_LOCK)
            self.assertTrue(d.session_locked)
            mock_set_eff.assert_called_with(color_matrix.identity())

            # Simulate session unlock
            with patch("paperscreen.daemon._lerp_apply") as mock_lerp:
                d.handle_menu_command(tray.CMD_SESSION_UNLOCK)
                self.assertFalse(d.session_locked)
                mock_lerp.assert_called_once()


class BreakTimerLockMutexTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.patch_config = patch.object(config, "config_dir", return_value=self.tmpdir.name)
        self.patch_config.start()

    def tearDown(self):
        self.patch_config.stop()
        self.tmpdir.cleanup()

    def test_acquire_and_release_lock_lifecycle(self):
        from paperscreen import breaks

        breaks._release_lock()
        acquired = breaks._acquire_lock()
        self.assertTrue(acquired)
        import os
        self.assertTrue(os.path.isfile(breaks._lock_path()))
        breaks._release_lock()
        self.assertFalse(os.path.isfile(breaks._lock_path()))


class BacklightDebounceTests(unittest.TestCase):
    def test_backlight_deduplication(self):
        """Rapid identical set_brightness calls within 150ms are skipped/debounced."""
        with patch("paperscreen.backlight.signals.load", return_value={}), \
             patch("paperscreen.backlight._wmi_get_brightness", return_value=None), \
             patch("paperscreen.winlib.open_physical_monitors") as mock_open:

            mock_open.return_value.__enter__.return_value = []
            mock_open.return_value.__exit__.return_value = None

            report1 = backlight.set_brightness(75)
            # Immediate second call with same level
            report2 = backlight.set_brightness(75)

            self.assertEqual(report2["skipped"], [{"reason": "debounced"}])


class SettingsWindowTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.patch_config = patch.object(config, "config_dir", return_value=self.tmpdir.name)
        self.patch_signals = patch.object(signals, "config_dir", return_value=self.tmpdir.name)
        self.patch_config.start()
        self.patch_signals.start()
        signals.clear()
        cfg = dict(config.DEFAULTS)
        cfg["live_preview"] = False
        config.save(cfg)
        import tkinter as tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = None

    def tearDown(self):
        if self.app:
            try:
                self.app.destroy()
            except Exception:
                pass
            self.app = None
        try:
            self.root.update()
            self.root.destroy()
        except Exception:
            pass
        self.patch_signals.stop()
        self.patch_config.stop()
        self.tmpdir.cleanup()
        import gc
        gc.collect()

    def test_settings_window_initialization_and_matrix_computation(self):
        from paperscreen import settings_gui
        self.app = settings_gui.SettingsWindow(self.root)
        self.assertIsNotNone(self.app.var_preset.get())
        m = self.app._compute_current_matrix()
        self.assertEqual(len(m), 5)
        self.assertEqual(len(m[0]), 5)

        # Changing sliders alters computed matrix
        self.app.var_kelvin.set(2200)
        self.app.var_desat.set(80.0)
        m_warm = self.app._compute_current_matrix()
        self.assertNotEqual(m, m_warm)

    def test_settings_preset_selection_updates_sliders(self):
        from paperscreen import settings_gui
        self.app = settings_gui.SettingsWindow(self.root)
        self.app.var_preset.set("amber_candle")
        self.app._on_preset_selected()
        self.assertEqual(self.app.var_kelvin.get(), 2200)
        self.assertEqual(self.app.var_desat.get(), 75.0)

    @patch("paperscreen.spawn.is_daemon_running", return_value=True)
    @patch("paperscreen.winlib.user32")
    def test_live_preview_ipc_when_daemon_running(self, mock_u32, mock_daemon):
        from paperscreen import settings_gui, tray
        mock_u32().FindWindowW.return_value = 12345
        mock_u32().PostMessageW.return_value = 1

        self.app = settings_gui.SettingsWindow(self.root)
        self.app._apply_live_preview()

        # Signals should contain preview_matrix
        j = signals.load()
        self.assertIn("preview_matrix", j)
        self.assertIsNotNone(j["preview_matrix"])
        mock_u32().PostMessageW.assert_called_with(12345, 0x0111, tray.CMD_LIVE_PREVIEW, 0)

    @patch("paperscreen.spawn.is_daemon_running", return_value=False)
    @patch("paperscreen.winlib.mag_set_color_effect")
    def test_live_preview_in_process_when_daemon_stopped(self, mock_mag_set, mock_daemon):
        from paperscreen import settings_gui
        self.app = settings_gui.SettingsWindow(self.root)
        self.app._apply_live_preview()
        mock_mag_set.assert_called()

    @patch("paperscreen.paper_engine.apply")
    @patch("paperscreen.spawn.is_daemon_running", return_value=False)
    def test_save_and_apply_starts_daemon_when_stopped(self, mock_daemon, mock_apply):
        from paperscreen import settings_gui
        with patch("tkinter.messagebox.showinfo"):
            self.app = settings_gui.SettingsWindow(self.root)
            self.app._save_and_apply()
            mock_apply.assert_called_once()

    def test_inverted_paper_customization_preserves_inverted_matrix(self):
        from paperscreen import settings_gui
        self.app = settings_gui.SettingsWindow(self.root)
        self.app.var_preset.set("inverted_paper")
        self.app._on_preset_selected()
        self.assertTrue(self.app.var_invert.get())

        # Inverted matrix maps white to dark
        m_orig = self.app._compute_current_matrix()
        w_orig = color_matrix.apply_matrix(m_orig, (1.0, 1.0, 1.0))
        self.assertLess(max(w_orig), 0.20)

        # Simulate moving a slider (e.g. changing kelvin or ceiling)
        self.app.var_kelvin.set(3200)
        self.app.var_ceiling.set(85.0)

        # Ensure preset remains inverted_paper and does NOT revert to normal white paper
        self.assertEqual(self.app.var_preset.get(), "inverted_paper")
        m_custom = self.app._compute_current_matrix()
        w_custom = color_matrix.apply_matrix(m_custom, (1.0, 1.0, 1.0))
        self.assertLess(max(w_custom), 0.20)
        self.assertNotEqual(m_orig, m_custom)

    @patch("paperscreen.spawn.is_daemon_running", return_value=True)
    @patch("paperscreen.winlib.user32")
    @patch("paperscreen.winlib.mag_set_color_effect")
    def test_toggle_engine_turns_off_and_reverts_to_identity(self, mock_mag_set, mock_u32, mock_daemon):
        from paperscreen import settings_gui, tray
        signals.update(active=True, preset="paper")
        mock_u32().FindWindowW.return_value = 54321

        self.app = settings_gui.SettingsWindow(self.root)
        self.assertTrue(self.app._is_engine_active())

        # Clicking toggle engine when active should turn OFF and revert matrix to identity
        self.app._toggle_engine()
        mock_mag_set.assert_called_with(color_matrix.identity())
        mock_u32().PostMessageW.assert_called_with(54321, 0x0111, tray.CMD_TOGGLE, 0)


class DaemonReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.patch_config = patch.object(config, "config_dir", return_value=self.tmpdir.name)
        self.patch_signals = patch.object(signals, "config_dir", return_value=self.tmpdir.name)
        self.patch_config.start()
        self.patch_signals.start()
        signals.clear()

    def tearDown(self):
        self.patch_signals.stop()
        self.patch_config.stop()
        self.tmpdir.cleanup()

    def test_state_file_oserror_does_not_quarantine(self):
        """Transient OSError (antivirus/file lock) must not rename valid state.json to .corrupt."""
        signals.save({"backlight_previous": {"Mon #1": 80}, "active": True})
        p = signals.state_path()
        self.assertTrue(os.path.isfile(p))

        with patch("builtins.open", side_effect=OSError("Sharing violation")):
            loaded = signals.load()
            self.assertEqual(loaded, {})

        # File must NOT have been renamed to .corrupt
        self.assertTrue(os.path.isfile(p), "valid state file must be retained on transient OSError")
        self.assertFalse(os.path.isfile(f"{p}.corrupt"))

    def test_state_file_corrupt_json_quarantines(self):
        """Truly corrupt/unparseable JSON is safely quarantined to .corrupt."""
        p = signals.state_path()
        with open(p, "w", encoding="utf-8") as f:
            f.write("{this is not valid json")

        loaded = signals.load()
        self.assertEqual(loaded, {})
        self.assertTrue(os.path.isfile(f"{p}.corrupt"), "corrupt JSON should be quarantined")

    def test_transition_lock_is_reentrant(self):
        """_transition_lock must be an RLock to prevent deadlocks when messages pump re-entrant commands."""
        from paperscreen import daemon
        self.assertIsInstance(daemon._transition_lock, type(threading.RLock()))
        # Verify acquiring twice on same thread succeeds without blocking
        with daemon._transition_lock:
            with daemon._transition_lock:
                pass

    @patch("paperscreen.daemon._lerp_apply")
    @patch("paperscreen.backlight.restore")
    @patch("paperscreen.backlight.set_brightness")
    @patch("paperscreen.cleartype.restore_previous")
    @patch("paperscreen.cleartype.enable_grayscale_smoothing")
    def test_hotkey_toggle_off_restores_state_and_stays_alive(
        self, mock_ct_enable, mock_ct_restore, mock_set_bri, mock_restore_bri, mock_lerp
    ):
        """Toggling OFF via hotkey restores backlight/smoothing, updates journal, and DOES NOT stop the daemon."""
        from paperscreen import daemon
        d = daemon.Daemon()
        signals.update(active=True, preset="paper")

        # 1. Toggle OFF
        d.on_hotkey()
        self.assertFalse(d.stop.is_set(), "daemon must remain alive when hotkey toggles off")
        mock_restore_bri.assert_called_once()
        mock_ct_restore.assert_called_once()
        j = signals.load()
        self.assertFalse(j.get("active"))

        # 2. Toggle back ON
        d.on_hotkey()
        self.assertFalse(d.stop.is_set())
        mock_set_bri.assert_called_once()
        j2 = signals.load()
        self.assertTrue(j2.get("active"))


if __name__ == "__main__":
    unittest.main()

