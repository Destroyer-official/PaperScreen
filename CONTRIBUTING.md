# Contributing to PaperScreen

Thank you for your interest in contributing to **PaperScreen**! We welcome bug reports, documentation improvements, and pull requests that adhere to our zero-dependency, evidence-aligned philosophy.

---

## Zero-Dependency Philosophy

PaperScreen core runs on **pure Python standard library + ctypes on Windows**. We do not add external third-party dependencies (like PyQt, Pillow, WMI, or PyWin32) to the core runtime package. Any Windows API interaction must be achieved through ctypes bindings in `paperscreen/winlib.py`.

---

## Development Setup

1. **Clone the repository**:
   ```powershell
   git clone https://github.com/Destroyer-official/PaperScreen.git
   cd PaperScreen
   ```

2. **Verify environment**:
   Make sure you are on Windows 8, 10, or 11 with Python 3.10+ installed:
   ```powershell
   python --version
   ```

3. **Run the test suite**:
   ```powershell
   python -m unittest discover -s tests -v
   ```

---

## Submitting Pull Requests

1. Create a feature branch:
   ```powershell
   git checkout -b feature/my-enhancement
   ```
2. Write clean, readable Python code adhering to PEP 8 standards with type annotations.
3. Add corresponding unit tests in `tests/test_production.py` or new test files in `tests/`.
4. Ensure all tests pass:
   ```powershell
   python -m unittest discover -s tests
   ```
5. Commit your changes with clear, descriptive commit messages:
   ```powershell
   git commit -m "feat(presets): add warm drafting color preset"
   ```
6. Push to your branch and open a Pull Request against `main`.

---

## Scientific Rigor & Medical Honesty

When proposing features related to eye health, visual comfort, or circadian biology:
- Cite peer-reviewed literature (e.g. TFOS DEWS II/Lifestyle, Cochrane, CIE standards).
- Do not make exaggerated claims (e.g. "completely eliminates eye strain").
- Maintain our commitment to evidence-based interventions: luminance matching, regular micro-breaks, and rendering quality over blue-light marketing claims.
