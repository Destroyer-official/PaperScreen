# PaperScreen — Research Summary & Implementation Plan

Make an ordinary Windows monitor behave like paper for long-form coding/reading.
Python, zero-dependency core, optional GUI later.

---

## 1. What the latest research actually says (2021–2026)

| Claim | Verdict | Source |
|---|---|---|
| Blue-light-blocking glasses reduce eye strain | **No evidence** (Cochrane 2023, 17 trials); questionnaire follow-up (PMID 41322997) finds adherence, not optics, drives improvement | Singh et al., Cochrane DBSR; AAO |
| Blue light from screens damages eyes | No scientific evidence; sun >> screens | AAO (reviewed by Rahul Khurana, MD, 2021) |
| Blue-light filters: any value at all? | Yes — **sleep hygiene** (melanopsin/ipRGC circadian phase), not strain | 2026 narrative review PMID 42524168; AAO night-mode page |
| Primary causes of digital eye strain | Reduced blink **rate and completeness**, uncorrected refractive/binocular issues, task cognitive demand, brightness/glare mismatch | **TFOS Lifestyle 2023 (PMID 37062428)** — the ocular-surface consensus report |
| Best-evidenced mitigation | Full refractive correction (see optometrist!), improved blinking, optimized environment, **regular breaks** | TFOS Lifestyle 2023 |
| 20-20-20 rule | Small RCT support; adherence is the practical bottleneck | Tal et al. Clin Optom 2023; PMID 41322997 identifies adherence predictor |
| Dark mode vs light mode | **No significant visual-fatigue difference** in RCT (n=30 tablet); dark mode slightly better on dry-eye/CFF metrics | PMID 40283833 (2025) |
| Blink rate while reading screens | Significantly reduced vs baseline; measurable via eye tracking | PMID 39491645 (2024) |
| PWM flicker (OLED) | Real; characterized by SVM; software cannot fix hardware flicker | PMID 41411543 (2025) |
| Brightness guidance | Match screen brightness to surroundings; avoid screen brighter than room | AAO guidance |
| Matte filters | Recommended by AAO to cut specular glare | AAO computer-usage page |

**Product design consequences (what we build vs what we don't):**

1. Marketing stays honest: "reduces strain risk factors", never "eliminates strain".
2. Core value = luminance matching (DDC) + rendering quality (matrix, grayscale
   smoothing) + **behavioral: automatic, gentle, non-annoying break reminders**
   (adherence is the bottleneck — so they must be toast-based, escalating
   politely, never blocking).
3. Warm tint is a **sleep feature** (evening), not a strain claim.
4. We avoid software-induced flicker: matrix animations step at ~30 Hz with
   eased interpolation; DDC writes are debounced (DDC is slow, ~50-200 ms/op).
5. Recommend (README): optometrist check, matte protector, bias lighting,
   flicker-free/DC-dim monitor — things software can't do.

---

## 2. Technical verification notes (errors found in the original draft)

1. **Matrix convention.** `MAGCOLOREFFECT` is a GDI+-style color matrix.
   Microsoft's own grayscale example (MagSetFullscreenColorEffect docs) shows the
   input-vector convention: `out = M · (r, g, b, 1)` with offsets in the **last row**
   (translation row). Several community snippets transpose it. We verify empirically
   in `tools/verify_matrix.py` and assert the correct orientation at runtime.
2. **`MagSetFullscreenColorEffect` requires the magnifier running state**: it only has
   effect while the full-screen magnifier API is active (`MagInitialize` +
   in Win 8+ it affects the whole desktop directly, but **the effect does not persist
   across reboot** and is cleared when the last Mag client exits). Needs a resident
   process (service/tray) → architecture decision below.
3. **DDC/CI is not universally available.** Works over HDMI/DP (if "DDC/CI" enabled in
   the monitor's OSD), usually not over adapters/docks/VGA. Windows 11 also exposes
   some internal panels via WMI. `SetMonitorBrightness` can fail or behave oddly on
   some models (Twinkle Tray's known-issues list). → Must implement fallback chain
   and per-monitor caps/quirks.
4. **The grain overlay idea is dubious.** A topmost transparent window costs
   compositing and can break exclusive-fullscreen apps/games and screen capture.
   The Magnification API is the right channel; grain adds marginal value → demoted to
   optional, default-off experiment (Phase 3), never in the core path.
5. **ClearType registry toggling (`FontSmoothingType`) requires logoff/logon** to fully
   apply and SystemParametersInfo(SPI_SETFONTSMOOTHINGTYPE) does not reliably
   broadcast. → Optional, opt-in, reversible, documented.
6. **Claimed "70–80% strain reduction" from software is not defensible.** We will not
   ship that number; no RCT supports it.

---

## 3. Architecture

```
paperscreen/                (package)
├── __init__.py
├── __main__.py             CLI entry: python -m paperscreen ...
├── cli.py                  argparse; commands: on/off/status/monitors/break/doctor
├── config.py               JSON config in %APPDATA%\PaperScreen\config.json
├── winlib.py               ALL raw ctypes bindings (mag, dxva2, user32, gdi32, SPI)
├── color_matrix.py         pure-python matrix builder (testable, no win32)
├── paper_engine.py         orchestration: apply/release, atomic, idempotent
├── backlight.py           DDC/CI chain: dxva2 → WMI fallback → no-op
├── cleartype.py            SPI_GET/SETFONTSMOOTHINGTYPE (optional feature)
├── breaks.py               20-20-20 timer (single instance, config-driven)
├── signals.py              safe-restore watchdog: SIGINT, atexit, session lock file
└── daemon/                 (Phase 2) tray resident process
tools/
├── verify_matrix.py        live empirical matrix-orientation check (developer)
tests/
└── test_matrix.py          unit tests, stdlib unittest
PLAN.md  README.md  LICENSE
```

Key decisions:
- **Zero dependencies** for core (ctypes + stdlib). GUI (Phase 2) may use tkinter
  (stdlib) to stay dependency-free; PyQt only if tkinter proves insufficient.
- **Correctness first**: every effect applied is journaled (state file) so a crash
  cannot leave the user's display stuck in paper mode (release-on-next-start +
  explicit `off` + `doctor` to force-clean).
- **Matrix math is pure** and unit-tested; win32 only in `winlib.py`/`paper_engine.py`.

## 4. Paper color science (concrete defaults)

- Target background: unbleached paper `#F3EBDD` (≈ parchment) at daytime; charcoal ink
  `#2E2A26`. Achieved via: warm white-point shift (~4500–5000 K day, ~3400 K night),
  gentle global desaturation (35%), and soft contrast compression via the matrix
  translation row (black floor ≈ 0.10, white ceiling ≈ 0.92 in output space).
- Night phase additionally lowers target backlight (25–35%) via DDC when available.
- All numbers user-tunable in config; presets: `paper`, `sepia`, `eink`, `off`.

## 5. Phased roadmap

**Phase 1 (done in this repo, CLI):** matrix engine + DDC backlight + config +
on/off/status/doctor + 20-20-20 break timer + safe restore + unit tests + live
verification tooling.

**Phase 2:** resident tray daemon (tkinter), hotkeys, smooth transitions
(interpolated matrix over ~1 s), auto-on by app (fullscreen detection skip),
per-display profiles, autostart.

**Phase 3:** webcam ambient-lux loop (opt-in; OpenCV optional dep), grain overlay
experiment (default off), ambient-light history graph, MSI installer + code signing.

## 6. Verification plan (per run)

1. `python -m unittest` (matrix math, config round-trip).
2. `python -m paperscreen doctor` — verifies APIs available, DDC reachable, matrix
   round-trip set→get (MagGetFullscreenColorEffect) identity vs paper, then restores.
3. Manual: `on` → observe, `off` → identical pixels (screenshot diff optional).
