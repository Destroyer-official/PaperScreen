"""Persistent state journal so separate CLI processes can restore each
other's changes (e.g. `paperscreen on` then later `paperscreen off`).

Lives beside config.json in %APPDATA%/PaperScreen/state.json.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from .config import config_dir

STATE_NAME = "state.json"


def state_path() -> str:
    return os.path.join(config_dir(), STATE_NAME)


def load() -> dict:
    try:
        with open(state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def update(**fields) -> dict:
    data = load()
    for k, v in fields.items():
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    save(data)
    return data


def save(data: dict) -> None:
    os.makedirs(config_dir(), exist_ok=True)
    target = state_path()
    tmp = target + f".{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, target)
    except Exception:
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def clear() -> None:
    try:
        os.remove(state_path())
    except OSError:
        pass
