"""Pure-Python color matrix builder for the paper-screen effect.

MAGCOLOREFFECT convention (verified against Microsoft's canonical invert
sample, which places translation 1s in the LAST ROW):

    out(R,G,B,A) = (r, g, b, a, 1) * M      (row vector times matrix)

i.e. input channels index ROWS, output channels index COLUMNS, and
M[4][0..2] are per-channel constant offsets (translation). The identity
matrix (and thus MS's grayscale example) is symmetric, which is why this
is easy to get wrong; the invert sample (1 - x) disambiguates it.
"""

from __future__ import annotations

import math
from typing import Dict, Sequence, Tuple

Matrix = Tuple[Tuple[float, float, float, float, float], ...]

LUMA_WEIGHTS: Dict[str, Sequence[float]] = {
    # sRGB / Rec.709 luma weights
    "paper": (0.34, 0.36, 0.30),
}


def identity() -> Matrix:
    return (
        (1.0, 0.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 0.0, 1.0),
    )


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def kelvin_to_rgb(kelvin: float) -> Tuple[float, float, float]:
    """Approximate blackbody RGB (0..1). Tanner Helland's approximation."""
    k = _clamp(kelvin, 1000.0, 15000.0) / 100.0
    if k <= 66.0:
        r = 255.0
        g = 99.4708025861 * math.log(k) - 161.1195681661
    else:
        r = 329.698727446 * ((k - 60.0) ** -0.1332047592)
        g = 288.1221695283 * ((k - 60.0) ** -0.0755148492)
    if k >= 66.0:
        b = 255.0
    elif k <= 19.0:
        b = 0.0
    else:
        b = 138.5177312231 * math.log(k - 10.0) - 305.0447927307
    return (
        _clamp(r, 0.0, 255.0) / 255.0,
        _clamp(g, 0.0, 255.0) / 255.0,
        _clamp(b, 0.0, 255.0) / 255.0,
    )


def tint_gains(kelvin: float) -> Tuple[float, float, float]:
    """Per-output-channel gains for a white-point shift toward `kelvin`.

    Normalized so the strongest channel is 1.0 (like f.lux): warm points
    keep red full and attenuate blue. Never exceeds 1 => no channel clips.
    Standard sRGB D65 (6500 K) is strictly neutral (1.0, 1.0, 1.0).
    """
    if abs(kelvin - 6500.0) < 1.0:
        return (1.0, 1.0, 1.0)
    r, g, b = kelvin_to_rgb(kelvin)
    top = max(r, g, b)
    if top <= 0.0:
        return (1.0, 1.0, 1.0)
    return (r / top, g / top, b / top)


def paper_matrix(
    kelvin: float = 4600.0,
    desaturation: float = 0.35,
    black_floor: float = 0.10,
    white_ceiling: float = 0.92,
    contrast: float = 1.0,
    luminance: float = 1.0,
) -> Matrix:
    """Build the 5x5 paper-effect matrix in MAGCOLOREFFECT orientation.

    Pixel pipeline (per output channel c, gains g_c from `kelvin`):
      L   = luma(r,g,b)                        # wr·r + wg·g + wb·b
      x   = (1-d)·in_c + d·L                   # desaturate toward luma
      y   = k·x + (1-k)·0.5                    # contrast pivot at mid-gray
      out = g_c·Lm·(floor + (ceiling-floor)·y) # tone map to paper range

    `luminance` (0.2..1.0) scales the whole output range. This is the
    PWM-aware dimming path: reducing pixel luminance via the matrix keeps
    the panel's backlight duty cycle (and thus PWM flicker depth) unchanged
    on monitors that dim by PWM — unlike overlay-style dimmers.
    """
    d = _clamp(desaturation, 0.0, 1.0)
    s = 1.0 - d
    k = _clamp(contrast, 0.2, 2.0)
    wr, wg, wb = LUMA_WEIGHTS["paper"]
    floor = _clamp(black_floor, 0.0, 0.5)
    ceiling = _clamp(white_ceiling, floor + 0.01, 1.0)
    gains = tint_gains(kelvin)
    lm = _clamp(luminance, 0.05, 1.0)

    span = ceiling - floor

    # tone-map scale applied to y, per channel
    tm_c = gains  # (gr, gg, gb)

    # M[in][out]; rows 0..2 are r,g,b inputs; cols 0..2 are r,g,b outputs.
    m = [[0.0] * 5 for _ in range(5)]
    for out_c in range(3):
        for in_c in range(3):
            mix = (s if in_c == out_c else 0.0) + d * (wr, wg, wb)[in_c]
            m[in_c][out_c] = gains[out_c] * lm * span * k * mix

    # translation: floor + (ceiling-floor)·(1-k)/2, per channel
    for out_c in range(3):
        m[4][out_c] = gains[out_c] * lm * (floor + span * (1.0 - k) / 2.0)

    # structural rows/columns
    m[3][3] = 1.0
    m[4][4] = 1.0

    return tuple(tuple(row) for row in m)


def lerp_matrix(a: Matrix, b: Matrix, t: float) -> Matrix:
    """Linear interpolation between two matrices (for smooth transitions)."""
    if t <= 0.0:
        return a
    if t >= 1.0:
        return b
    return tuple(
        tuple(a[r][c] + (b[r][c] - a[r][c]) * t for c in range(5))
        for r in range(5)
    )


def ease(t: float) -> float:
    """Ease-in-out cubic for flicker-free transitions (30+ fps stepping)."""
    t = _clamp(t, 0.0, 1.0)
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0


def apply_matrix(m, rgb: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """Apply matrix per the magnifier convention: (r,g,b,a=1,w=1) * M."""
    r, g, b = rgb
    vec = (r, g, b, 1.0, 1.0)
    out = []
    for out_c in range(3):
        v = sum(vec[i] * m[i][out_c] for i in range(5))
        out.append(_clamp(v, 0.0, 1.0))
    return (out[0], out[1], out[2])


def is_achromatic(matrix: Matrix, tolerance: float = 1e-5) -> bool:
    """Return True if matrix maps every input to strictly equal R, G, B channels (neutral grayscale)."""
    # For a matrix to be strictly achromatic, all columns 0, 1, 2 must be identical
    for row in range(5):
        c0, c1, c2 = matrix[row][0], matrix[row][1], matrix[row][2]
        if abs(c0 - c1) > tolerance or abs(c0 - c2) > tolerance:
            return False
    return True


def inverted_paper_matrix(
    kelvin: float = 4600.0,
    desaturation: float = 0.20,
    black_floor: float = 0.10,
    white_ceiling: float = 0.90,
) -> Matrix:
    """Dark-mode paper matrix with chromatic polarity inversion.

    Rather than naive negative RGB inversion (which turns red to cyan and blue
    to yellow), this transform applies cross-channel coupling designed to invert
    background/foreground luminance while preserving primary chromatic dominance
    (e.g., maintaining red emphasis on diff deletions and blue emphasis on links/syntax).
    Hues are mapped onto warm dark charcoal paper (#1A1816) with parchment text (#EAE2D0).
    Note: Due to channel clipping and cross-weighting, this is an artistic syntax-preserving
    transform rather than a mathematically complete hue-angle invariant color space engine.
    """
    d = _clamp(desaturation, 0.0, 1.0)
    wr, wg, wb = LUMA_WEIGHTS["paper"]
    floor = _clamp(black_floor, 0.0, 0.5)
    ceiling = _clamp(white_ceiling, floor + 0.01, 1.0)
    gains = tint_gains(kelvin)
    span = ceiling - floor

    c_diag = 0.3333333
    c_off = -0.6666667
    luma_w = (wr, wg, wb)

    m = [[0.0] * 5 for _ in range(5)]
    for in_c in range(3):
        for out_c in range(3):
            smart_w = c_diag if in_c == out_c else c_off
            mono_w = -luma_w[in_c]
            w_eff = (1.0 - d) * smart_w + d * mono_w
            m[in_c][out_c] = gains[out_c] * span * w_eff

    for out_c in range(3):
        m[4][out_c] = gains[out_c] * ceiling

    m[3][3] = 1.0
    m[4][4] = 1.0
    return tuple(tuple(row) for row in m)


PRESET_VALUES: Dict[str, dict] = {
    "paper": {"kelvin": 4400, "desaturation": 0.65, "black_floor": 0.10, "white_ceiling": 0.90, "contrast": 1.04},
    "sepia": {"kelvin": 3600, "desaturation": 0.70, "black_floor": 0.12, "white_ceiling": 0.86, "contrast": 1.05},
    "warm_reading": {"kelvin": 3000, "desaturation": 0.55, "black_floor": 0.12, "white_ceiling": 0.84, "contrast": 1.06},
    "eink": {"kelvin": 6500, "desaturation": 1.00, "black_floor": 0.08, "white_ceiling": 0.92, "contrast": 1.04},
    "eink_warm": {"kelvin": 4000, "desaturation": 1.00, "black_floor": 0.08, "white_ceiling": 0.90, "contrast": 1.04},
    "amber_candle": {"kelvin": 2200, "desaturation": 0.75, "black_floor": 0.08, "white_ceiling": 0.82, "contrast": 1.05},
    "nightpaper": {"kelvin": 3200, "desaturation": 0.60, "black_floor": 0.07, "white_ceiling": 0.72, "contrast": 1.05, "luminance": 0.85},
    "inverted_paper": {"kelvin": 4400, "desaturation": 0.20, "black_floor": 0.10, "white_ceiling": 0.90},
}

PRESETS = (
    "paper",
    "sepia",
    "eink",
    "warm_reading",
    "eink_warm",
    "amber_candle",
    "nightpaper",
    "inverted_paper",
    "custom",
    "off",
)


def preset(name: str):
    """Named presets."""
    name = name.lower()
    if name in ("off", "identity", "none"):
        return identity()
    if name == "paper":
        return paper_matrix(**PRESET_VALUES["paper"])
    if name == "sepia":
        return paper_matrix(**PRESET_VALUES["sepia"])
    if name == "eink":
        return paper_matrix(**PRESET_VALUES["eink"])
    if name == "warm_reading":
        return paper_matrix(**PRESET_VALUES["warm_reading"])
    if name == "eink_warm":
        return paper_matrix(**PRESET_VALUES["eink_warm"])
    if name == "amber_candle":
        return paper_matrix(**PRESET_VALUES["amber_candle"])
    if name == "nightpaper":
        return paper_matrix(**PRESET_VALUES["nightpaper"])
    if name == "inverted_paper":
        return inverted_paper_matrix(**PRESET_VALUES["inverted_paper"])
    if name == "custom":
        from . import config
        cfg = config.load()
        return paper_matrix(
            kelvin=cfg.get("kelvin", 4400),
            desaturation=cfg.get("desaturation", 0.65),
            black_floor=cfg.get("black_floor", 0.10),
            white_ceiling=cfg.get("white_ceiling", 0.90),
            contrast=cfg.get("contrast", 1.04),
        )
    raise ValueError(f"unknown preset: {name!r}")


__all__ = [
    "identity",
    "tint_gains",
    "multiply",
    "lerp_matrix",
    "ease",
    "paper_matrix",
    "inverted_paper_matrix",
    "preset",
    "PRESET_VALUES",
]


