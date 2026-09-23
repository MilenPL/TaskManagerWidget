"""'task manager widget settings' — the companion settings application."""

from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import GLib, Gtk

from . import VERSION, config, gtkutil as G, ipc, paths, theme
from . import i18n
from . import launcher as _launcher_mod
from .i18n import tr
from . import store as store_mod
from .launcher import launch_widget as _launch_widget
from .launcher import settings_command as _settings_command
from .launcher import widget_command as _widget_command
from .notify import BUNDLED_SOUNDS, Notifier, play
from .widget import PRESETS

ROOT = paths.project_root()

#: the confirmation phrase for "clear all tasks" — deliberately NEVER
#: translated: it is a safety token you have to type, like a delete-all
#: phrase in a banking app, not UI copy.
CLEAR_PHRASE = "clear all tasks"

PRESET_LABELS = {
    "bottom_right": "bottom right", "bottom_left": "bottom left",
    "bottom_center": "bottom centre",
    "top_right": "top right", "top_left": "top left",
    "top_center": "top centre",
    "right": "right edge, centred", "left": "left edge, centred",
    "center": "centre of the screen",
}


def mtime(p: str) -> int:
    try:
        return os.stat(p).st_mtime_ns
    except OSError:
        return 0


def widget_command() -> list[str]:
    return _widget_command()


def settings_command() -> list[str]:
    return _settings_command()


def launch_widget() -> bool:
    return _launch_widget()


# ---------------------------------------------------------------- desktop ----

def write_desktop(path: str, name: str, comment: str, exec_cmd: str,
                  extra: str = "") -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    data = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={name}\n"
        f"Comment={comment}\n"
        f"Exec={' '.join(exec_cmd)}\n"
        "Terminal=false\n"
        "Categories=Utility;Office;\n"
        "StartupNotify=false\n"
        f"{extra}"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(data)
    try:
        os.chmod(path, 0o744)
    except OSError:
        pass


def autostart_on() -> bool:
    return os.path.exists(paths.autostart_path())


def set_autostart(on: bool) -> None:
    p = paths.autostart_path()
    if on:
        write_desktop(
            p, "task manager widget",
            "Always-on-bottom liquid glass task widget",
            widget_command(), "X-GNOME-Autostart-enabled=true\nNoDisplay=true\n")
    else:
        try:
            os.unlink(p)
        except OSError:
            pass


def menu_dir() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    p = os.path.join(base, "applications")
    os.makedirs(p, exist_ok=True)
    return p


def menu_installed() -> bool:
    return os.path.exists(os.path.join(menu_dir(), "task-widget-settings.desktop"))


def set_menu(on: bool) -> None:
    d = menu_dir()
    s = os.path.join(d, "task-widget-settings.desktop")
    w = os.path.join(d, "task-widget.desktop")
    if on:
        write_desktop(s, "task manager widget settings",
                      "Configure the liquid glass task widget",
                      settings_command(),
                      "Icon=preferences-system\n")
        write_desktop(w, "task manager widget",
                      "Always-on-bottom liquid glass task widget",
                      widget_command(), "Icon=office-calendar\n")
    else:
        for p in (s, w):
            try:
                os.unlink(p)
            except OSError:
                pass
    if on:
        try:
            subprocess.run(["update-desktop-database", d],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10)
        except Exception:
            pass


# =============================================================== the app =====


class SettingsApp:
    def __init__(self):
        self.cfg = config.load()
        i18n.set_language(self.cfg.get("language"))
        self.k = None
        self.store = store_mod.Store()
        self._mtime = mtime(paths.config_path())
        self._syncing = False
        self._build()
        self.sync()

    # ---------------------------------------------------------- config I/O --

    def get(self, dotted: str):
        node = self.cfg
        for p in dotted.split("."):
            node = node.get(p) if isinstance(node, dict) else None
        return node

    def set(self, dotted: str, value) -> None:
        if self._syncing:
            return
        parts = dotted.split(".")

        def mut(c):
            node = c
            for p in parts[:-1]:
                node = node.setdefault(p, {})
            node[parts[-1]] = value

        config.update(mut)
        self.cfg = config.load()
        self._mtime = mtime(paths.config_path())

    def bump(self, key: str) -> None:
        def mut(c):
            c[key] = int(c.get(key, 0) or 0) + 1
        config.update(mut)
        self.cfg = config.load()
        self._mtime = mtime(paths.config_path())

    # ------------------------------------------------------------- widgets --

    def _row(self, text: str, control, hint: str = "") -> Gtk.Box:
        b = G.hbox(10)
        vb = G.vbox(1)
        vb.pack_start(G.label(text, "slabel"), False, False, 0)
        if hint:
            vb.pack_start(G.label(hint, "help"), False, False, 0)
        b.pack_start(vb, True, True, 0)
        b.pack_end(control, False, False, 0)
        return b

    def _sw(self, dotted: str):
        s = G.switch(bool(self.get(dotted)), lambda v: self.set(dotted, v))
        self._widgets.append((dotted, s))
        return s

    def _build(self) -> None:
        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.win = win
        win.set_title(tr("task manager widget settings"))
        win.set_default_size(600, 660)
        win.set_resizable(True)
        win.set_position(Gtk.WindowPosition.CENTER)
        win.connect("destroy", self._on_destroy)
        self._populate()

    def _on_destroy(self, *_a) -> None:
        src = getattr(self, "_poll_src", None)
        if src:
            try:
                GLib.source_remove(src)
            except Exception:
                pass
            self._poll_src = None
        if Gtk.main_level() > 0:            # only quit a loop we actually started
            Gtk.main_quit()

    def _populate(self) -> None:
        """Build the window contents; re-run it to switch language live.

        The new tree is built first and only swapped in at the very end, so a
        failure half-way through leaves the previous page on screen instead of
        a black window — and the result is always explicitly shown.
        """
        win = self.win
        page = None
        if getattr(self, "nb", None) is not None:
            try:
                page = self.nb.get_current_page()
            except Exception:
                page = None
        self.nb = None
        self._widgets = []

        # the window's child is replaced up-front: GtkWindow must receive its
        # root before the tree is built, otherwise the toplevel ends up with a
        # hierarchy GTK cannot size and show_all() crashes
        old = win.get_child()
        if old is not None:
            win.remove(old)
            old.destroy()

        root = G.vbox(0)
        G.cls(root, "tw", "settings")
        win.add(root)
        inner = G.vbox(10)
        inner.set_margin_top(16)
        inner.set_margin_bottom(16)
        inner.set_margin_start(18)
        inner.set_margin_end(18)
        root.pack_start(inner, True, True, 0)
        root = inner

        # ---- header -------------------------------------------------------
        head = G.hbox(10)
        vb = G.vbox(1)
        vb.pack_start(G.label(tr("task manager widget settings"), "stitle"), False, False, 0)
        vb.pack_start(G.label(tr("liquid glass · always at the bottom of the stack"),
                              "ssub"), False, False, 0)
        head.pack_start(vb, True, True, 0)
        self.status_dot = Gtk.Box()
        self.status_dot.set_size_request(10, 10)
        self.status_dot.set_valign(Gtk.Align.CENTER)
        G.cls(self.status_dot, "statusdot")
        head.pack_start(self.status_dot, False, False, 0)
        self.status_lbl = G.label(tr("widget not running"), "help")
        head.pack_start(self.status_lbl, False, False, 0)
        root.pack_start(head, False, False, 0)
        root.pack_start(G.divider(), False, False, 0)

        # ---- notebook -----------------------------------------------------
        nb = Gtk.Notebook()
        nb.set_scrollable(False)
        nb.set_hexpand(True)
        nb.set_vexpand(True)
        G.cls(nb, "tabs")
        self.nb = nb
        root.pack_start(nb, True, True, 0)

        nb.append_page(self._tab_appearance(), G.label(tr("appearance"), ""))
        nb.append_page(self._tab_position(), G.label(tr("position"), ""))
        nb.append_page(self._tab_notify(), G.label(tr("notifications"), ""))
        nb.append_page(self._tab_features(), G.label(tr("features"), ""))
        nb.append_page(self._tab_data(), G.label(tr("data & startup"), ""))

        # ---- footer -------------------------------------------------------
        foot = G.hbox(8)
        quitb = G.button(tr("close"), "btn")
        quitb.connect("clicked", lambda _w: win.destroy())
        foot.pack_end(quitb, False, False, 0)
        intro_b = G.button(tr("show the introduction again"), "btn")
        intro_b.connect("clicked", lambda _w: self._show_intro())
        foot.pack_end(intro_b, False, False, 0)
        foot.pack_start(G.label(tr("version {v}", v=VERSION), "help"),
                        False, False, 0)
        root.pack_start(foot, False, False, 0)

        # The tree has to be shown explicitly: on a language switch nothing
        # else calls show_all(), and an unshown child leaves a black window.
        root.show_all()
        if self.nb is not None and page is not None:
            self.nb.set_current_page(max(0, min(page, self.nb.get_n_pages() - 1)))
        win.queue_draw()

    # ------------------------------------------------------------- tabs -----

    def _tab_appearance(self) -> Gtk.Widget:
        box = G.vbox(8)
        box.set_margin_top(6)

        # ---- language ------------------------------------------------------
        box.pack_start(G.label(tr("language"), "sect"), False, False, 0)
        codes = i18n.available()
        combo = Gtk.ComboBoxText()
        for code in codes:
            combo.append_text(i18n.language_name(code))
        current = self.get("language") or i18n.DEFAULT_LANG
        combo.set_active(codes.index(current) if current in codes else 0)
        combo.connect("changed", self._language_changed)
        self.lang_combo = combo
        box.pack_start(self._row(tr("interface language"), combo,
                                 tr("the widget follows this within a second")),
                       False, False, 0)

        # ---- widget title -------------------------------------------------
        box.pack_start(G.label(tr("widget"), "sect"), False, False, 0)
        self.title_entry = Gtk.Entry()
        G.cls(self.title_entry, "entry")
        self.title_entry.set_width_chars(14)
        self.title_entry.set_max_width_chars(20)
        self.title_entry.set_text(str(self.get("title") or ""))
        self.title_entry.set_halign(Gtk.Align.END)

        def on_title(w) -> None:
            if self._syncing:
                return
            self.set("title", w.get_text())

        self.title_entry.connect("changed", on_title)
        box.pack_start(self._row(
            tr("title"), self.title_entry,
            tr("the word at the very top of the widget — applies as you type")),
            False, False, 0)

        # theme
        row = G.hbox(6)
        row.pack_start(G.label(tr("theme"), "sect"), True, True, 0)
        self.btn_dark = G.button(tr("dark"), "chip")
        self.btn_dark.connect("clicked", lambda _w: self._theme("dark"))
        self.btn_bright = G.button(tr("bright"), "chip")
        self.btn_bright.connect("clicked", lambda _w: self._theme("bright"))
        row.pack_end(self.btn_bright, False, False, 0)
        row.pack_end(self.btn_dark, False, False, 0)
        box.pack_start(row, False, False, 0)
        box.pack_start(G.label(tr("both variants use the same soft, rounded liquid-glass "
                               "surfaces and gentle dividers."), "help"), False, False, 0)

        # opacity
        box.pack_start(G.label(tr("glass"), "sect"), False, False, 0)
        self.op_lbl = G.label(tr(""), "help")
        self.op_lbl.set_xalign(1.0)
        row = G.hbox(10)
        vb = G.vbox(1)
        vb.pack_start(G.label(tr("opacity"), "slabel"), False, False, 0)
        vb.pack_start(G.label(tr("how see-through the widget's glass is"), "help"),
                      False, False, 0)
        row.pack_start(vb, False, False, 0)
        self.op_scale = G.scale(0.40, 1.0, 0.01, float(self.get("opacity")),
                                self._opacity)
        row.pack_start(self.op_scale, True, True, 0)
        row.pack_end(self.op_lbl, False, False, 0)
        box.pack_start(row, False, False, 0)

        self.sc_lbl = G.label(tr(""), "help")
        self.sc_lbl.set_xalign(1.0)
        row = G.hbox(10)
        vb = G.vbox(1)
        vb.pack_start(G.label(tr("size"), "slabel"), False, False, 0)
        vb.pack_start(G.label(tr("scales the whole widget"), "help"), False, False, 0)
        row.pack_start(vb, False, False, 0)
        self.sc_scale = G.scale(0.85, 1.10, 0.01, float(self.get("scale")),
                                self._scale)
        row.pack_start(self.sc_scale, True, True, 0)
        row.pack_end(self.sc_lbl, False, False, 0)
        box.pack_start(row, False, False, 0)

        # live preview
        r_lbl = G.label("", "help")
        r_lbl.set_xalign(1.0)
        self.rad_lbl = r_lbl
        rrow = G.hbox(10)
        rvb = G.vbox(1)
        rvb.pack_start(G.label(tr("corner roundness"), "slabel"), False, False, 0)
        rvb.pack_start(G.label(tr("0 is square, higher is rounder"), "help"),
                       False, False, 0)
        rrow.pack_start(rvb, False, False, 0)
        rrow.pack_end(r_lbl, False, False, 0)
        self.rad_scale = G.scale(0, 48, 1, float(self.get("radius") or 26),
                                 self._radius)
        rrow.pack_start(self.rad_scale, True, True, 0)
        box.pack_start(rrow, False, False, 0)

        box.pack_start(G.label(tr("preview"), "sect"), False, False, 0)
        prev = G.vbox(6)
        G.cls(prev, "glass")
        prev.set_size_request(-1, 118)
        pv_head = G.hbox(6)
        pv_head.pack_start(G.label(tr("tasks"), "title"), True, True, 0)
        pv_head.pack_start(G.label(tr("sample"), "date"), False, False, 0)
        box.pack_start(prev, False, False, 0)
        prev.pack_start(pv_head, False, False, 0)
        prev.pack_start(G.divider(), False, False, 0)
        pv_row = G.hbox(7)
        pv_row.get_style_context().add_class("row")
        pv_row.pack_start(G.dot(8, 9), False, False, 0)
        pv_row.pack_start(G.label(tr("review pull request"), "ttext"), True, True, 0)
        pv_row.pack_start(G.label(tr("14:30"), "ttime"), False, False, 0)
        prev.pack_start(pv_row, False, False, 0)
        pv_row2 = G.hbox(7)
        pv_row2.get_style_context().add_class("row")
        pv_row2.pack_start(G.dot(4, 9), False, False, 0)
        pv_row2.pack_start(G.label(tr("water the plants"), "ttext"), True, True, 0)
        pv_row2.pack_start(G.label(tr("done"), "badge done"), False, False, 0)
        prev.pack_start(pv_row2, False, False, 0)

        return self._scrolled(box)

    def _tab_position(self) -> Gtk.Widget:
        box = G.vbox(8)
        box.set_margin_top(6)

        box.pack_start(G.label(tr("where the widget sits"), "sect"), False, False, 0)
        row = G.hbox(10)
        row.pack_start(G.label(tr("place at"), "slabel"), False, False, 0)
        self.preset_cb = G.combobox(
            [tr(PRESET_LABELS[p]) for p in PRESETS],
            max(0, PRESETS.index(self.cfg.get("position_preset", "bottom_right"))
                if self.cfg.get("position_preset", "bottom_right") in PRESETS else 0),
            self._preset_changed)
        row.pack_start(self.preset_cb, True, True, 0)
        applyb = G.button(tr("apply"), "btn suggested")
        applyb.connect("clicked", lambda _w: self._apply_preset())
        row.pack_start(applyb, False, False, 0)
        box.pack_start(row, False, False, 0)
        box.pack_start(G.label(tr("Pick a spot and hit apply, or drag it yourself."),
                               "help"), False, False, 0)

        box.pack_start(G.label(tr("move it by hand"), "sect"), False, False, 0)
        card = G.vbox(6)
        G.cls(card, "card")
        self.drag_lbl = G.label(
            tr("Dragging is off. The widget stays exactly where it is until you "
            "say otherwise."), "help")
        self.drag_lbl.set_line_wrap(True)
        card.pack_start(self.drag_lbl, True, True, 0)
        btns = G.hbox(8)
        self.btn_drag = G.button(tr("change position"), "btn suggested",
                                 tr("unlock the widget so you can drag it"))
        self.btn_drag.connect("clicked", lambda _w: self._set_drag(True))
        self.btn_confirm = G.button(tr("confirm position"), "btn",
                                    tr("lock the widget again"))
        self.btn_confirm.connect("clicked", lambda _w: self._set_drag(False))
        btns.pack_start(self.btn_drag, False, False, 0)
        btns.pack_start(self.btn_confirm, False, False, 0)
        card.pack_start(btns, False, False, 0)
        box.pack_start(card, False, False, 0)

        box.pack_start(G.label(tr("the widget itself"), "sect"), False, False, 0)
        card2 = G.vbox(6)
        G.cls(card2, "card")
        self.run_lbl = G.label(tr(""), "help")
        self.run_lbl.set_line_wrap(True)
        card2.pack_start(self.run_lbl, True, True, 0)
        btns2 = G.hbox(8)
        b = G.button(tr("start widget"), "btn suggested")
        b.connect("clicked", lambda _w: launch_widget())
        self.btn_start = b
        btns2.pack_start(b, False, False, 0)
        b2 = G.button(tr("stop widget"), "btn")
        b2.connect("clicked", lambda _w: ipc.send({"cmd": "quit"}))
        btns2.pack_start(b2, False, False, 0)
        card2.pack_start(btns2, False, False, 0)
        box.pack_start(card2, False, False, 0)

        box.pack_start(G.label(
            tr("It is pinned below every other window and hidden from alt-tab and "
            "the workspace switcher — that is by design."), "help"),
            False, False, 0)

        return self._scrolled(box)

    def _tab_notify(self) -> Gtk.Widget:
        box = G.vbox(4)
        box.set_margin_top(6)

        box.pack_start(G.label(tr("alerts"), "sect"), False, False, 0)
        box.pack_start(self._row(tr("notifications"),
                                 self._sw("notifications.enabled"),
                                 tr("turn everything below off in one go")), False, False, 0)
        box.pack_start(self._row(tr("show glass pop-ups"),
                                 self._sw("notifications.popups"),
                                 tr("sound can stay on even with pop-ups off")), False, False, 0)
        box.pack_start(self._row(tr("play sounds"),
                                 self._sw("notifications.sounds")), False, False, 0)

        # volume
        row = G.hbox(10)
        vb = G.vbox(1)
        vb.pack_start(G.label(tr("volume"), "slabel"), False, False, 0)
        vb.pack_start(G.label(tr("alert loudness"), "help"), False, False, 0)
        row.pack_start(vb, False, False, 0)
        self.vol_lbl = G.label(tr(""), "help")
        self.vol_lbl.set_xalign(1.0)
        row.pack_end(self.vol_lbl, False, False, 0)
        self.vol_scale = G.scale(0.0, 1.0, 0.05,
                                 float(self.get("notifications.volume")),
                                 self._volume)
        row.pack_start(self.vol_scale, True, True, 0)
        box.pack_start(row, False, False, 0)

        box.pack_start(G.label(tr("when"), "sect"), False, False, 0)

        # remind lead time
        row = G.hbox(10)
        vb = G.vbox(1)
        vb.pack_start(G.label(tr("remind me before a task"), "slabel"), False, False, 0)
        vb.pack_start(G.label(tr("0 turns advance reminders off"), "help"), False, False, 0)
        row.pack_start(vb, False, False, 0)
        self.rem_sp = Gtk.SpinButton.new_with_range(0, 240, 5)
        self.rem_sp.set_value(float(self.get("notifications.remind_min")))
        self.rem_sp.connect("value-changed",
                            lambda w: self.set("notifications.remind_min",
                                               int(w.get_value())))
        row.pack_end(self.rem_sp, False, False, 0)
        box.pack_start(row, False, False, 0)

        row = G.hbox(10)
        vb = G.vbox(1)
        vb.pack_start(G.label(tr("snooze length"), "slabel"), False, False, 0)
        vb.pack_start(G.label(tr("how long a snoozed alert sleeps"), "help"),
                      False, False, 0)
        row.pack_start(vb, False, False, 0)
        self.sn_sp = Gtk.SpinButton.new_with_range(1, 240, 1)
        self.sn_sp.set_value(float(self.get("notifications.snooze_min")))
        self.sn_sp.connect("value-changed",
                           lambda w: self.set("notifications.snooze_min",
                                              int(w.get_value())))
        row.pack_end(self.sn_sp, False, False, 0)
        box.pack_start(row, False, False, 0)

        box.pack_start(self._row(tr("when a task comes due"),
                                 self._sw("notifications.at_time")), False, False, 0)
        box.pack_start(self._row(tr("when a long-term deadline passes"),
                                 self._sw("notifications.deadline")), False, False, 0)
        box.pack_start(self._row(tr("keep ringing while the pop-up is open"),
                                 self._sw("notifications.alarm_repeat"),
                                 tr("replays the alarm every few seconds")),
                       False, False, 0)

        row = G.hbox(10)
        vb = G.vbox(1)
        vb.pack_start(G.label(tr("pop-up closes after"), "slabel"), False, False, 0)
        vb.pack_start(G.label(tr("0 keeps it until you dismiss it"), "help"),
                      False, False, 0)
        row.pack_start(vb, False, False, 0)
        self.to_sp = Gtk.SpinButton.new_with_range(0, 300, 1)
        self.to_sp.set_value(float(self.get("notifications.popup_timeout")))
        self.to_sp.connect("value-changed",
                           lambda w: self.set("notifications.popup_timeout",
                                              int(w.get_value())))
        row.pack_end(self.to_sp, False, False, 0)
        box.pack_start(row, False, False, 0)

        box.pack_start(G.label(tr("sounds"), "sect"), False, False, 0)
        names = [n for n, _ in BUNDLED_SOUNDS]
        paths_ = [p for _, p in BUNDLED_SOUNDS]
        for key, text in (("sound_remind", "reminder"),
                          ("sound_due", "task due"),
                          ("sound_alarm", "alarm / time's up")):
            row = G.hbox(8)
            row.pack_start(G.label(text, "slabel"), False, False, 0)
            cur = self.get(f"notifications.{key}")
            active = paths_.index(cur) if cur in paths_ else 0
            cb = G.combobox(names, active,
                            lambda i, k=key, ps=paths_:
                            self.set(f"notifications.{k}",
                                     ps[i] if 0 <= i < len(ps) else ps[0]))
            row.pack_end(cb, True, True, 0)
            b = G.button(tr("test"), "btn")
            b.connect("clicked", lambda _w, k=key:
                      play(self.get(f"notifications.{k}"),
                           float(self.get("notifications.volume"))))
            row.pack_end(b, False, False, 0)
            box.pack_start(row, False, False, 0)

        return self._scrolled(box)

    # ---------------------------------------------------------- features ----

    @staticmethod
    def _norm_hhmm(text: str) -> str:
        m = re.match(r"^\s*(\d{1,2})\s*[:.]\s*(\d{1,2})\s*$", text or "")
        if not m:
            return ""
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            return ""
        return f"{h:02d}:{mi:02d}"

    def _time_entry(self, dotted: str) -> Gtk.Entry:
        e = Gtk.Entry()
        G.cls(e, "entry")
        e.set_width_chars(5)
        e.set_max_width_chars(6)
        e.set_text(str(self.get(dotted) or "00:00"))
        e.set_halign(Gtk.Align.START)

        def on_changed(w) -> None:
            norm = self._norm_hhmm(w.get_text())
            sc = w.get_style_context()
            if norm:
                sc.remove_class("warn")
                if not self._syncing:
                    self.set(dotted, norm)
            else:
                sc.add_class("warn")

        e.connect("changed", on_changed)
        return e

    def _tab_features(self) -> Gtk.Widget:
        box = G.vbox(8)
        box.set_margin_top(6)

        box.pack_start(G.label(tr("on the widget"), "sect"), False, False, 0)
        box.pack_start(self._row(
            tr("calendar day popover"),
            self._sw("features.day_popover"),
            tr("tap a day's dots to open that day and tick its tasks off")),
            False, False, 0)
        box.pack_start(self._row(
            tr("steps and progress rings"),
            self._sw("features.steps"),
            tr("click a task's colour dot to add subtasks — the dot turns into a ring")),
            False, False, 0)
        box.pack_start(self._row(
            tr("next-up strip"),
            self._sw("features.next_up"),
            tr("slim line under the header with the next task and its countdown")),
            False, False, 0)
        box.pack_start(self._row(
            tr("natural-language times"),
            self._sw("features.nl_time"),
            tr('type "dentist tomorrow at 14:30" — the words become the date')),
            False, False, 0)
        box.pack_start(self._row(
            tr("keyboard shortcuts"),
            self._sw("features.shortcuts"),
            tr("Ctrl+N new · / search · Ctrl+F fold · Enter ticks a task off · "
            "Delete removes it")),
            False, False, 0)

        box.pack_start(G.label(tr("calendar and lists"), "sect"), False, False, 0)
        box.pack_start(self._row(
            tr("month calendar: only not-done tasks"),
            self._sw("features.calendar_only_undone"),
            tr("drops the colour dot of anything finished — the five-day list "
            "below keeps whatever its own switches say")),
            False, False, 0)
        box.pack_start(self._row(
            tr("five-day view: show yesterday"),
            self._sw("features.show_yesterday"),
            tr("the group above today; switch it off for today plus three days "
            "only")),
            False, False, 0)
        box.pack_start(self._row(
            tr("five-day view: only not-done tasks"),
            self._sw("features.weekly_only_undone"),
            tr("hide finished tasks from every day group")),
            False, False, 0)
        box.pack_start(self._row(
            tr("today: only not-done tasks"),
            self._sw("features.weekly_today_only_undone"),
            tr("just today — its group and the today · times panel, leaving the "
            "other days untouched")),
            False, False, 0)

        box.pack_start(G.label(tr("do not disturb"), "sect"), False, False, 0)
        box.pack_start(self._row(
            tr("queue alerts inside the quiet window"),
            self._sw("features.dnd"),
            tr("pop-ups and sounds are held back instead of firing, then shown "
            "when the window ends")),
            False, False, 0)

        row = G.hbox(10)
        row.pack_start(G.label(tr("from"), "slabel"), False, False, 0)
        self.dnd_from = self._time_entry("features.dnd_from")
        row.pack_start(self.dnd_from, False, False, 0)
        row.pack_start(G.label(tr("to"), "slabel"), False, False, 0)
        self.dnd_to = self._time_entry("features.dnd_to")
        row.pack_start(self.dnd_to, False, False, 0)
        self.dnd_q_lbl = G.label(tr(""), "help")
        self.dnd_q_lbl.set_xalign(1.0)
        row.pack_end(self.dnd_q_lbl, True, True, 0)
        box.pack_start(row, False, False, 0)
        box.pack_start(G.label(
            tr("Overnight windows are fine — 22:00 → 07:00 queues the whole "
            "night. Anything waiting is shown as soon as it ends."), "help"),
            False, False, 0)

        card = G.vbox(6)
        G.cls(card, "card")
        card.pack_start(G.label(tr("what the toggles do not change"), "slabel"),
                        False, False, 0)
        card.pack_start(G.label(
            tr("Turning a feature off only hides it. Tasks, steps and settings "
            "you already made are kept, so switching it back on brings "
            "everything straight back."), "help"), False, False, 0)
        box.pack_start(card, False, False, 0)

        return self._scrolled(box)

    def _tab_data(self) -> Gtk.Widget:
        box = G.vbox(8)
        box.set_margin_top(6)

        box.pack_start(G.label(tr("startup"), "sect"), False, False, 0)
        box.pack_start(self._row(tr("open the widget when I log in"),
                                 self._autostart_switch(),
                                 tr("writes a GNOME autostart entry")), False, False, 0)
        box.pack_start(self._row(tr("show it in the applications menu"),
                                 self._menu_switch(),
                                 tr("adds both launchers to your app grid")),
                       False, False, 0)

        box.pack_start(G.label(tr("your tasks live in"), "sect"), False, False, 0)
        p = G.label(paths.tasks_path(), "help")
        p.set_selectable(True)
        p.set_line_wrap(True)
        box.pack_start(p, False, False, 0)
        box.pack_start(G.label(
            tr("Only your own account's tasks are ever read or written — nothing "
            "is shared between users on this machine."), "help"), False, False, 0)

        box.pack_start(G.label(tr("backup"), "sect"), False, False, 0)
        self.task_lbl = G.label(tr(""), "slabel")
        box.pack_start(self.task_lbl, False, False, 0)
        row = G.hbox(8)
        b = G.button(tr("export tasks…"), "btn")
        b.connect("clicked", lambda _w: self._export())
        row.pack_start(b, False, False, 0)
        b = G.button(tr("import tasks…"), "btn")
        b.connect("clicked", lambda _w: self._import())
        row.pack_start(b, False, False, 0)
        b = G.button(tr("remove finished"), "btn")
        b.connect("clicked", lambda _w: self._clear_finished())
        row.pack_start(b, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.data_lbl = G.label(tr(""), "help")
        self.data_lbl.set_line_wrap(True)
        box.pack_start(self.data_lbl, False, False, 0)

        # ---- destructive: needs a typed confirmation ----------------------
        drow = G.hbox(10)
        self.btn_clear_all = G.button(tr("clear all tasks"), "btn danger",
                                      tr("delete every task on this account"))
        self.btn_clear_all.connect("clicked", lambda _w: self._clear_all_dialog())
        drow.pack_start(self.btn_clear_all, False, False, 0)
        drow.pack_end(G.label(tr("this cannot be undone"), "help"),
                      False, False, 0)
        box.pack_start(drow, False, False, 0)

        box.pack_start(G.label(tr("a few ideas"), "sect"), False, False, 0)
        box.pack_start(G.label(
            tr("· type in the search box on the widget to filter every list\n"
            "· the filter button narrows by colour, hides finished tasks and "
            "empty days\n"
            "· tick 'long-term' when a task has a deadline instead of a time\n"
            "· repeating tasks: click 'no repeat' to cycle daily → weekly → "
            "monthly\n"
            "· click a day's dots in the calendar to tick its tasks off fast\n"
            "· click a task's colour dot to give it steps — it becomes a ring\n"
            "· the small arrow in the header folds the widget to a slim rail"),
            "help"), False, False, 0)

        return self._scrolled(box)

    def _scrolled(self, child: Gtk.Widget) -> Gtk.Widget:
        if isinstance(child, Gtk.Box):
            # side padding so prose never touches the edge of the block
            child.set_margin_start(12)
            child.set_margin_end(12)
        s = Gtk.ScrolledWindow()
        s.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        s.set_shadow_type(Gtk.ShadowType.NONE)
        G.cls(s, "scroll")
        s.add(child)
        return s

    # ------------------------------------------------------ control wiring --

    def _show_intro(self) -> None:
        from . import intro
        intro.show(self.win, mark_seen=True)

    def _language_changed(self, combo) -> None:
        if self._syncing:
            return
        codes = i18n.available()
        idx = combo.get_active()
        if not (0 <= idx < len(codes)):
            return
        code = codes[idx]
        if code == i18n.get_language():
            return
        self.set("language", code)
        i18n.set_language(code)
        # rebuild on the next idle pass: this handler runs *inside* the combo's
        # "changed" emission, and destroying that combo mid-signal crashes GTK
        GLib.idle_add(self._rebuild_for_language)

    def _rebuild_for_language(self) -> bool:
        try:
            self._populate()                  # rebuild the tree, new language
            self.sync()
        except Exception:                     # never leave a black window: at
            import traceback                  # least show what did get built
            traceback.print_exc()
            try:
                self.win.show_all()
                self.win.queue_draw()
            except Exception:
                pass
            return False
        self.win.set_title(tr("task manager widget settings"))
        self.win.queue_draw()
        self.win.show_all()
        return False                          # one-shot idle

    def _theme(self, name: str) -> None:
        self.set("theme", name)
        theme.apply_css(self.cfg)
        self.sync()

    def _opacity(self, v: float) -> None:
        self.set("opacity", round(float(v), 3))
        theme.apply_css(self.cfg)
        self.op_lbl.set_text(f"{int(round(v * 100))}%")

    def _scale(self, v: float) -> None:
        self.set("scale", round(float(v), 3))
        theme.apply_css(self.cfg)
        self.sc_lbl.set_text(f"{v:.2f} ×")
        self.bump("preset_seq")

    def _radius(self, v: float) -> None:
        """Corner roundness — applies to the preview and the widget live."""
        r = int(round(v))
        self.set("radius", r)
        theme.apply_css(self.cfg)
        self.rad_lbl.set_text(f"{r} px")

    def _volume(self, v: float) -> None:
        self.set("notifications.volume", round(float(v), 2))
        self.vol_lbl.set_text(f"{int(round(v * 100))}%")

    def _preset_changed(self, idx: int) -> None:
        if 0 <= idx < len(PRESETS):
            self.set("position_preset", PRESETS[idx])

    def _apply_preset(self) -> None:
        name = self.cfg.get("position_preset", "bottom_right")
        self.bump("preset_seq")
        ipc.send({"preset": name})
        self.data_lbl.set_text(tr(""))

    def _set_drag(self, on: bool) -> None:
        self.set("drag_mode", bool(on))
        ipc.send({"drag_mode": bool(on)})
        self.sync()

    def _autostart_switch(self) -> Gtk.Widget:
        s = G.switch(autostart_on(), lambda v: set_autostart(v))
        self._auto_sw = s
        return s

    def _menu_switch(self) -> Gtk.Widget:
        s = G.switch(menu_installed(), lambda v: set_menu(v))
        self._menu_sw = s
        return s

    # --------------------------------------------------------------- data ---

    def _export(self) -> None:
        d = Gtk.FileChooserNative.new(
            tr("Export tasks"), self.win, Gtk.FileChooserAction.SAVE,
            tr("_Save"), tr("_Cancel"))
        d.set_do_overwrite_confirmation(True)
        d.set_current_name(f"task-widget-tasks-{dt.date.today().isoformat()}.json")
        if d.run() == Gtk.ResponseType.ACCEPT:
            path = d.get_filename()
            try:
                paths.write_json(path, {
                    "owner_uid": paths.uid(), "version": 1,
                    "tasks": [t.to_dict() for t in self.store.tasks]})
                self.data_lbl.set_text(
                    tr("exported {n} tasks to {path}",
                       n=len(self.store.tasks), path=path))
            except OSError as exc:
                self.data_lbl.set_text(tr("export failed: {e}", e=exc))
        d.destroy()

    def _import(self) -> None:
        d = Gtk.FileChooserNative.new(
            tr("Import tasks"), self.win, Gtk.FileChooserAction.OPEN,
            tr("_Open"), tr("_Cancel"))
        d.add_filter(self._json_filter())
        if d.run() == Gtk.ResponseType.ACCEPT:
            path = d.get_filename()
            doc = paths.read_json(path, None)
            if not isinstance(doc, dict) or not paths.owner_ok(doc):
                self.data_lbl.set_text(
                    tr("that file is not a task widget backup for this user"))
            else:
                from .models import Task
                tasks = [t for t in (Task.from_dict(x)
                                     for x in doc.get("tasks", [])) if t]
                self.store.tasks = tasks
                self.store.save()
                self._touch_store()
                self.data_lbl.set_text(
                    tr("imported {n} tasks", n=len(tasks)))
                self._poll_status()
        d.destroy()

    @staticmethod
    def _json_filter() -> Gtk.FileFilter:
        f = Gtk.FileFilter()
        f.set_name(tr("task widget backups (*.json)"))
        f.add_pattern("*.json")
        return f

    def _clear_finished(self) -> None:
        n = self.store.clear_finished()
        self._touch_store()
        self.data_lbl.set_text(
            i18n.plural(n, "removed {n} finished task",
                        "removed {n} finished tasks")
            if n else tr("nothing to remove"))

    # ------------------------------------------------- clear everything ----

    def _clear_all_dialog(self) -> None:
        """Ask for the typed phrase before wiping every task."""
        count = len(self.store.tasks)
        if count <= 0:
            self.data_lbl.set_text(tr("there are no tasks to clear"))
            return
        if getattr(self, "_clear_dlg", None) is not None:
            return                                    # already asking

        dlg = Gtk.Dialog(title=tr("clear all tasks"), transient_for=self.win,
                         flags=Gtk.DialogFlags.MODAL)
        self._clear_dlg = dlg
        dlg.set_destroy_with_parent(True)
        dlg.set_default_response(Gtk.ResponseType.YES)

        box = G.vbox(9)
        G.cls(box, "tw", "settings")
        box.set_margin_top(14)
        box.set_margin_bottom(14)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_size_request(430, -1)

        box.pack_start(G.label(tr("this cannot be undone"), "help"),
                       False, False, 0)
        box.pack_start(G.label(i18n.plural(count, "{n} task", "{n} tasks"),
                               "slabel"), False, False, 0)
        box.pack_start(G.divider(), False, False, 0)
        box.pack_start(G.label(tr("type the phrase below to confirm"), "help"),
                       False, False, 0)
        # shown verbatim, never translated — it is what has to be typed
        box.pack_start(G.label(CLEAR_PHRASE, "phrase"), False, False, 0)

        entry = Gtk.Entry()
        G.cls(entry, "entry")
        entry.set_placeholder_text(CLEAR_PHRASE)
        entry.set_activates_default(True)
        self._clear_entry = entry
        box.pack_start(entry, False, False, 0)

        cancel = dlg.add_button(tr("cancel"), Gtk.ResponseType.CANCEL)
        G.cls(cancel, "btn")
        ok = dlg.add_button(tr("clear all tasks"), Gtk.ResponseType.YES)
        G.cls(ok, "btn", "danger")
        ok.set_sensitive(False)                       # locked until typed
        self._clear_ok = ok

        entry.connect("changed", self._clear_entry_changed)
        dlg.connect("response", self._on_clear_response)

        dlg.get_content_area().add(box)
        dlg.show_all()
        GLib.timeout_add(60, self._focus_clear_entry)

    def _focus_clear_entry(self) -> bool:
        try:
            self._clear_entry.grab_focus()
        except Exception:
            pass
        return False

    def _clear_entry_changed(self, entry) -> None:
        if self._clear_ok is None:
            return
        typed = entry.get_text().strip().casefold()
        self._clear_ok.set_sensitive(typed == CLEAR_PHRASE.casefold())

    def _on_clear_response(self, dlg, response) -> None:
        confirmed = response == Gtk.ResponseType.YES
        dlg.destroy()
        self._clear_dlg = None
        self._clear_entry = None
        self._clear_ok = None
        if confirmed:
            self._do_clear_all()

    def _do_clear_all(self) -> None:
        removed = len(self.store.tasks)
        self.store.tasks = []
        self.store.save()
        self._touch_store()
        if getattr(self, "btn_clear_all", None) is not None:
            self.btn_clear_all.set_sensitive(False)
        self.task_lbl.set_text(self._task_count_text())
        self.data_lbl.set_text(
            tr("all tasks cleared") if removed else tr("nothing to remove"))

    def _touch_store(self) -> None:
        pass  # the widget watches the file itself

    # --------------------------------------------------------------- sync ---

    def sync(self) -> None:
        """Push config values into the widgets without firing their handlers."""
        self._syncing = True
        try:
            self.cfg = config.load()
            if getattr(self, "lang_combo", None) is not None:
                codes = i18n.available()
                cur = self.get("language") or i18n.DEFAULT_LANG
                idx = codes.index(cur) if cur in codes else 0
                if self.lang_combo.get_active() != idx:
                    self.lang_combo.set_active(idx)
            G.toggle_cls(self.btn_dark, "on", self.get("theme") != "bright")
            G.toggle_cls(self.btn_bright, "on", self.get("theme") == "bright")
            if getattr(self, "title_entry", None) is not None:
                self.title_entry.set_text(str(self.get("title") or ""))
            self.op_scale.set_value(float(self.get("opacity")))
            self.op_lbl.set_text(f"{int(round(float(self.get('opacity')) * 100))}%")
            self.sc_scale.set_value(float(self.get("scale")))
            self.sc_lbl.set_text(f"{float(self.get('scale')):.2f} ×")
            if getattr(self, "rad_scale", None) is not None:
                rad = int(round(float(self.get("radius") or 26)))
                self.rad_scale.set_value(rad)
                self.rad_lbl.set_text(f"{rad} px")
            self.vol_scale.set_value(float(self.get("notifications.volume")))
            self.vol_lbl.set_text(
                f"{int(round(float(self.get('notifications.volume')) * 100))}%")
            for dotted, w in self._widgets:
                w.set_active(bool(self.get(dotted)))
            drag = bool(self.get("drag_mode"))
            G.toggle_cls(self.btn_drag, "on", drag)
            G.toggle_cls(self.btn_confirm, "on", not drag)
            self.drag_lbl.set_text(
                tr("Drag mode is ON — grab the widget and move it where you "
                   "want it, then come back and press 'confirm position'.")
                if drag else
                tr("Dragging is off. The widget stays exactly where it is "
                   "until you say otherwise."))
            self.task_lbl.set_text(self._task_count_text())
        finally:
            self._syncing = False

    @property
    def _task_count(self) -> int:
        return len(self.store.tasks)

    def _task_count_text(self) -> str:
        n = self._task_count
        return i18n.plural(n, "{n} task stored", "{n} tasks stored")

    def _poll_status(self) -> bool:
        running = ipc.alive()
        G.toggle_cls(self.status_dot, "on", running)
        self.status_lbl.set_text(tr("widget running") if running
                                 else tr("widget not running"))
        self.run_lbl.set_text(
            tr("The widget is running. Its window is pinned below every other "
               "window and does not appear in alt-tab.")
            if running else
            tr("The widget is not running — press 'start widget' to bring "
               "it back."))
        waiting = Notifier.queue_size()
        if getattr(self, "dnd_q_lbl", None) is not None:
            if waiting:
                self.dnd_q_lbl.set_text(
                    i18n.plural(waiting,
                                "{n} alert waiting for the quiet window to end",
                                "{n} alerts waiting for the quiet window to end"))
            else:
                self.dnd_q_lbl.set_text(
                    tr("quiet {a} → {b}",
                       a=self.get("features.dnd_from"),
                       b=self.get("features.dnd_to"))
                    if self.get("features.dnd") else tr("quiet window off"))
        if mtime(paths.config_path()) != self._mtime:
            self._mtime = mtime(paths.config_path())
            self.sync()
        if self.store.path:
            self.store.load()
            self.task_lbl.set_text(self._task_count_text())
        if getattr(self, "btn_clear_all", None) is not None:
            self.btn_clear_all.set_sensitive(bool(self.store.tasks))
        return True

    # --------------------------------------------------------------- main ---

    def show(self) -> None:
        self.win.show_all()
        self.sync()
        self._poll_src = GLib.timeout_add_seconds(2, self._poll_status)
        self._poll_status()


def main() -> int:
    G.init(x11=True)
    theme.apply_css(config.load())
    app = SettingsApp()
    app.show()
    page = 0
    if "--page" in sys.argv:
        try:
            page = int(sys.argv[sys.argv.index("--page") + 1])
        except (ValueError, IndexError):
            page = 0

    def find_notebook(w):
        if isinstance(w, Gtk.Notebook):
            return w
        if isinstance(w, Gtk.Container):
            for c in w.get_children():
                got = find_notebook(c)
                if got is not None:
                    return got
        return None

    nb = find_notebook(app.win)
    if nb is not None and 0 <= page < nb.get_n_pages():
        nb.set_current_page(page)
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
