"""Filesystem locations, per-user isolation and small JSON helpers."""

from __future__ import annotations

import json
import os
import tempfile

APP = "task-widget"


def uid() -> int:
    return os.getuid()


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    p = os.path.join(base, APP)
    os.makedirs(p, exist_ok=True)
    return p


def data_dir() -> str:
    """Per-user task storage. The uid segment guarantees each logged-in
    user only ever sees their own tasks, even on a shared home."""
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    p = os.path.join(base, APP, f"u{uid()}")
    os.makedirs(p, exist_ok=True)
    return p


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def state_path() -> str:
    return os.path.join(config_dir(), "state.json")


def tasks_path() -> str:
    return os.path.join(data_dir(), "tasks.json")


def queue_path() -> str:
    """Notifications held back by the do-not-disturb window."""
    return os.path.join(data_dir(), "queue.json")


def autostart_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    p = os.path.join(base, "autostart")
    os.makedirs(p, exist_ok=True)
    return os.path.join(p, "task-widget.desktop")


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_json(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path: str, obj) -> None:
    """Atomic write so watchers never see a half-written file."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def owner_ok(doc) -> bool:
    """A data file belongs to the current user unless it says otherwise."""
    if not isinstance(doc, dict):
        return False
    return doc.get("owner_uid") in (None, uid())
