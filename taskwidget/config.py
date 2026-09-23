"""Widget configuration (owned by the settings app, watched by the widget)."""

from __future__ import annotations

import copy

from . import paths

SOUNDS = "/usr/share/sounds/freedesktop/stereo"

DEFAULTS = {
    "owner_uid": 0,
    "theme": "dark",           # "dark" | "bright"
    "opacity": 0.72,           # glass alpha 0.40 .. 1.0
    "scale": 1.0,              # widget size 0.85 .. 1.12
    "autostart": True,
    "language": "en_US",      # see taskwidget/i18n.py (English US is default)
    "onboarding_seen": False,  # show the introduction once, on first run
    "radius": 26,             # corner roundness,0 (square) .. 48 (rounded)
    "title": "tasks",          # the word drawn at the top of the widget
    # settings -> widget commands
    "drag_mode": False,
    "position_preset": "bottom_right",
    "preset_seq": 0,
    "cmd": None,               # "quit" | "refresh" | None
    "cmd_seq": 0,
    # optional features, each individually switchable in the settings app
    "features": {
        "day_popover": True,   # tap a day's dots -> quick-complete popover
        "steps": True,         # subtasks + progress ring instead of a dot
        "next_up": True,       # slim "next up" strip with a countdown
        "shortcuts": True,     # Ctrl+N, /, Ctrl+F, Enter/Del on a task
        "nl_time": True,       # natural-language dates in the title field
        # calendar and the five-day (weekly) view are filtered separately, so
        # you can show only undone tasks in one of them and everything in the
        # other.
        "show_yesterday": True,             # weekly view keeps yesterday
        "calendar_only_undone": False,      # month grid: undone dots only
        "weekly_only_undone": False,        # weekly view: undone tasks only
        "weekly_today_only_undone": False,  # today's group: undone only
        "dnd": True,           # queue alerts inside the quiet window
        "dnd_from": "22:00",
        "dnd_to": "07:00",
    },
    "notifications": {
        "enabled": True,
        "popups": True,
        "sounds": True,
        "volume": 0.7,
        "remind_min": 10,      # 0 disables advance reminders
        "snooze_min": 10,      # how long a snoozed alert sleeps
        "at_time": True,       # popup when a task comes due
        "deadline": True,      # "time's up" for long-term tasks
        "alarm_repeat": True,  # keep re-playing while the alarm popup lives
        "popup_timeout": 8,    # seconds, 0 = stay until dismissed
        "sound_remind": f"{SOUNDS}/message-new-instant.oga",
        "sound_due": f"{SOUNDS}/complete.oga",
        "sound_alarm": f"{SOUNDS}/alarm-clock-elapsed.oga",
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    doc = paths.read_json(paths.config_path(), {}) or {}
    if not paths.owner_ok(doc):
        doc = {}
    cfg = _merge(DEFAULTS, doc)
    cfg["owner_uid"] = paths.uid()
    return cfg


def save(cfg: dict) -> None:
    cfg = copy.deepcopy(cfg)
    cfg["owner_uid"] = paths.uid()
    paths.write_json(paths.config_path(), cfg)


def update(mutate) -> dict:
    cfg = load()
    mutate(cfg)
    save(cfg)
    return cfg


def write_state(doc: dict) -> None:
    doc = dict(doc)
    doc["owner_uid"] = paths.uid()
    paths.write_json(paths.state_path(), doc)


def read_state() -> dict:
    doc = paths.read_json(paths.state_path(), {}) or {}
    if not paths.owner_ok(doc):
        return {}
    return doc
