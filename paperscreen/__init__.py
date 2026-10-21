"""PaperScreen: make your Windows monitor feel like paper."""

__version__ = "1.0.4"

from . import backlight, circadian, cleartype, color_matrix, config, signals, winlib  # noqa: F401

__all__ = [
    "__version__",
    "color_matrix",
    "config",
    "backlight",
    "cleartype",
    "circadian",
    "signals",
    "winlib",
]
