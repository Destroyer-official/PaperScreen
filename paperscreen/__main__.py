"""python -m paperscreen ..."""

import sys

try:
    from .cli import main
except ImportError:
    from paperscreen.cli import main

sys.exit(main())
