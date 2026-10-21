"""Standalone executable builder for PaperScreen using PyInstaller.

Produces a zero-dependency, self-contained Windows executable `PaperScreen.exe`.
Usage:
    python build_exe.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def main() -> int:
    print("== Building PaperScreen Standalone Executable ==")

    # Ensure in project root
    root_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root_dir)

    # PyInstaller arguments
    # Builds single executable with console support (can be invoked via CLI or pinned to taskbar)
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name=PaperScreen",
        "--collect-all=paperscreen",
        "--paths=.",
        "paperscreen/__main__.py",
    ]

    print("Running command:", " ".join(cmd))
    res = subprocess.run(cmd)
    if res.returncode != 0:
        print("Build failed with returncode:", res.returncode, file=sys.stderr)
        return res.returncode

    exe_path = os.path.join(root_dir, "dist", "PaperScreen.exe")
    if os.path.isfile(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"\n[SUCCESS] Standalone single-file executable created: {exe_path} ({size_mb:.2f} MB)")
    else:
        # Fallback check for onedir path
        onedir_path = os.path.join(root_dir, "dist", "PaperScreen", "PaperScreen.exe")
        if os.path.isfile(onedir_path):
            exe_path = onedir_path
            print(f"\n[SUCCESS] Executable created: {exe_path}")
        else:
            print("\n[WARNING] Build finished but exe not found at expected path:", exe_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
