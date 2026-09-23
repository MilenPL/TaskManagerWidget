"""First-run introduction: what the widget does and what can be customised.

Shown once, automatically, the first time the widget starts; it can be opened
again any time from the footer of the settings app.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")

from gi.repository import GLib, Gtk

from . import config, gtkutil as G
from .i18n import tr
from .launcher import launch_settings

R_SETTINGS = Gtk.ResponseType.HELP
R_DONE = Gtk.ResponseType.OK

#: English keys — translated at render time, never at import time
USING_IT = [
    "tap a day's dots to open that day and tick its tasks off",
    "click a task's colour dot to add subtasks — the dot turns into a ring",
    "type in the search box on the widget to filter every list",
    "build a task at the bottom: pick a colour, type a title, choose a date "
    "and time",
    "type \"dentist tomorrow at 14:30\" — the words become the date",
    "slim line under the header with the next task and its countdown",
    "Ctrl+N new · / search · Ctrl+F fold · Enter ticks a task off · "
    "Delete removes it",
    "it stays under every window and never shows up in alt-tab — that is "
    "on purpose",
]

MAKING_IT_YOURS = [
    "dark or bright glass, opacity and size — settings → appearance",
    "move it with one of the nine presets, or press change position and drag it",
    "turn the optional features on or off — settings → features",
    "sounds, snooze and a quiet window — settings → notifications",
    "language, widget title, backup and clear all tasks — settings → "
    "data & startup",
]

_current: Gtk.Dialog | None = None


def current() -> Gtk.Dialog | None:
    return _current


def _mark_seen() -> None:
    try:
        config.update(lambda c: c.__setitem__("onboarding_seen", True))
    except Exception:
        pass


def _bullets(keys, colour_base: int) -> Gtk.Box:
    box = G.vbox(6)
    for i, key in enumerate(keys):
        row = G.hbox(9)
        row.pack_start(G.dot((colour_base + i * 3) % 16, 7), False, False, 0)
        lab = G.label(tr(key), "slabel")
        lab.set_xalign(0.0)
        row.pack_start(lab, True, True, 0)
        box.pack_start(row, False, False, 0)
    return box


def _on_response(dlg, response) -> None:
    want_settings = response == R_SETTINGS
    dlg.destroy()
    if want_settings:
        launch_settings()


def _on_destroy(dlg) -> None:
    global _current
    _current = None
    if getattr(dlg, "_tw_mark", False):
        _mark_seen()


def show(parent=None, mark_seen: bool = True) -> Gtk.Dialog | None:
    """Open the introduction. Returns the dialog (or the one already open)."""
    global _current
    if _current is not None:
        try:
            _current.present()
        except Exception:
            pass
        return _current

    dlg = Gtk.Dialog(title=tr("welcome — how this widget works"),
                     transient_for=parent, flags=Gtk.DialogFlags.MODAL)
    dlg._tw_mark = bool(mark_seen)
    _current = dlg
    dlg.set_destroy_with_parent(True)
    dlg.set_default_response(R_DONE)

    box = G.vbox(10)
    G.cls(box, "tw", "settings")
    box.set_margin_top(16)
    box.set_margin_bottom(14)
    box.set_margin_start(18)
    box.set_margin_end(18)
    box.set_size_request(560, -1)

    head = G.vbox(2)
    head.pack_start(G.label(tr("welcome — how this widget works"), "stitle"),
                    False, False, 0)
    head.pack_start(G.label(
        tr("a short tour of what it does and what you can change"), "ssub"),
        False, False, 0)
    box.pack_start(head, False, False, 0)
    box.pack_start(G.divider(), False, False, 0)

    body = G.vbox(6)
    body.pack_start(G.label(tr("using it"), "sect"), False, False, 0)
    body.pack_start(_bullets(USING_IT, 0), False, False, 0)
    body.pack_start(G.divider(), False, False, 0)
    body.pack_start(G.label(tr("making it yours"), "sect"), False, False, 0)
    body.pack_start(_bullets(MAKING_IT_YOURS, 5), False, False, 0)

    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_propagate_natural_height(True)
    scroll.set_max_content_height(560)
    scroll.set_shadow_type(Gtk.ShadowType.NONE)
    G.cls(scroll, "scroll")
    scroll.add(body)
    box.pack_start(scroll, True, True, 0)

    settings_btn = dlg.add_button(tr("open settings"), R_SETTINGS)
    G.cls(settings_btn, "btn")
    done_btn = dlg.add_button(tr("got it"), R_DONE)
    G.cls(done_btn, "btn", "suggested")

    dlg.connect("response", _on_response)
    dlg.connect("destroy", _on_destroy)
    dlg.get_content_area().add(box)
    dlg.show_all()
    GLib.timeout_add(60, lambda: _focus(done_btn) )
    return dlg


def _focus(widget) -> bool:
    try:
        widget.grab_focus()
    except Exception:
        pass
    return False
