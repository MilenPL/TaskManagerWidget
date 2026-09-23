"""The always-on-bottom liquid-glass widget window."""

from __future__ import annotations

import datetime as dt
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")

from gi.repository import Gdk, GLib, Gtk, Pango

from . import config, gtkutil as G, ipc, nltime, paths, theme
from . import i18n
from .i18n import tr
from . import store as store_mod
from .calendarview import CalendarView, month_days
from .models import PALETTE, REPEATS, Task, today
from .notify import Notifier, Popup

BASE_W, BASE_H = 378, 756
FOLD_W = 48                      # width of the folded side rail
MARGIN = 14

PRESETS = [
    "bottom_right", "bottom_left", "bottom_center",
    "top_right", "top_left", "top_center",
    "right", "left", "center",
]

REPEAT_LABEL = {
    "none": "no repeat", "daily": "daily",
    "weekly": "weekly", "monthly": "monthly",
}


def mtime(path: str) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return 0


def clear(box: Gtk.Container) -> None:
    box.foreach(lambda w: w.destroy())


# ============================================================== widget =======


class Widget:
    def __init__(self):
        self.cfg = config.load()
        i18n.set_language(self.cfg.get("language"))
        self.k = theme.scale_of(self.cfg)
        self.store = store_mod.Store()
        self.day = today()
        st = config.read_state()
        self.folded = bool(st.get("folded", False))
        self._cfg_m = mtime(paths.config_path())
        self._store_m = mtime(self.store.path)
        self._last_pos = None          # our own record of where the card is
        self._preset_seq = int(self.cfg.get("preset_seq", 0) or 0)
        self._cmd_seq = int(self.cfg.get("cmd_seq", 0) or 0)
        self._minute = dt.datetime.now().strftime("%H:%M")
        self._nu_counter = 0
        self._nextup_live = False

        # list filters
        self.search = ""
        self.filter_colors: set[int] = set()
        self.hide_done = False
        self.hide_empty = False

        # create-task form state
        self.f_color = 7
        self.f_date = self.day
        nxt = dt.datetime.now() + dt.timedelta(minutes=60 - dt.datetime.now().minute % 60)
        self.f_time = (nxt.hour, 0)
        self.f_long = False
        self.f_repeat = "none"
        self.f_deadline = True

        self.drag_mode = bool(self.cfg.get("drag_mode"))
        self.dragging = False
        self._drag_win = (0, 0)
        self._drag_ptr = (0, 0)
        self._when_pop = None
        self._warn_src = None
        self._nl_src = None
        self._day_pop = None
        self._step_pop = None

        self._build()
        self.refresh()

    # ------------------------------------------------------------ geometry --

    def feat(self, name: str, default=True):
        f = self.cfg.get("features")
        if not isinstance(f, dict):
            return default
        return f.get(name, default)

    def widget_title(self) -> str:
        """The word at the top of the card — settable in the settings app."""
        return (str(self.cfg.get("title") or "").strip() or "tasks")

    def geometry(self) -> tuple[int, int]:
        k = theme.scale_of(self.cfg)
        w = FOLD_W if self.folded else BASE_W
        return int(w * k), int(BASE_H * k)

    def _build(self) -> None:
        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.win = win
        win.set_title(tr("task manager widget"))
        win.set_decorated(False)
        win.set_resizable(False)
        win.set_deletable(True)
        # --- the stacking recipe that keeps it under every app -------------
        win.set_type_hint(Gdk.WindowTypeHint.DOCK)
        win.set_keep_below(True)
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        try:
            win.stick()
        except Exception:
            pass
        G.glass_visual(win)
        win.get_style_context().add_class("tw")

        w, h = self.geometry()
        win.set_size_request(w, h)

        overlay = Gtk.Overlay()
        win.add(overlay)

        main = G.vbox(0)
        G.cls(main, "glass")
        overlay.add(main)

        # drag curtain (only visible while the settings app says so)
        ev = Gtk.EventBox()
        ev.set_visible_window(True)
        ev.set_can_focus(False)
        ev.set_hexpand(True)
        ev.set_vexpand(True)
        ev.set_valign(Gtk.Align.FILL)
        ev.set_halign(Gtk.Align.FILL)
        G.cls(ev, "drag", "tw")
        ev.set_no_show_all(True)
        ev.add_events(Gdk.EventMask.BUTTON_PRESS_MASK
                      | Gdk.EventMask.BUTTON_RELEASE_MASK
                      | Gdk.EventMask.POINTER_MOTION_MASK
                      | Gdk.EventMask.BUTTON_MOTION_MASK)
        ev.connect("button-press-event", self._drag_press)
        ev.connect("button-release-event", self._drag_release)
        ev.connect("motion-notify-event", self._drag_motion)
        tip = G.vbox(0)
        tip.set_halign(Gtk.Align.CENTER)
        tip.set_valign(Gtk.Align.CENTER)
        lab = G.label(tr("drag to move the widget"), "draglabel")
        lab.set_halign(Gtk.Align.CENTER)
        tip.pack_start(lab, False, False, 0)
        ev.add(tip)
        self.drag_label = lab
        self.drag_tip = tip
        overlay.add_overlay(ev)
        self.drag_ev = ev
        ev.set_visible(self.drag_mode)
        self.main = main

        # ---- folded side rail -------------------------------------------
        rail = Gtk.EventBox()
        rail.set_visible_window(True)
        rail.set_can_focus(False)
        rail.set_hexpand(True)
        rail.set_vexpand(True)
        rail.set_valign(Gtk.Align.FILL)
        rail.set_halign(Gtk.Align.FILL)
        G.cls(rail, "glass", "rail", "tw")
        rail.set_no_show_all(True)
        rbox = G.vbox(0)
        rbox.set_halign(Gtk.Align.CENTER)
        rbox.set_valign(Gtk.Align.CENTER)
        self.rail_btn = G.icon_button("pan-start-symbolic", "railbtn",
                                      tr("unfold the widget (Ctrl+F)"))
        self.rail_btn.connect("clicked", lambda _w: self.set_folded(False))
        rbox.pack_start(self.rail_btn, False, False, 0)
        rail.add(rbox)
        rail.add_events(Gdk.EventMask.BUTTON_PRESS_MASK
                        | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK
                        | Gdk.EventMask.BUTTON_MOTION_MASK)
        rail.connect("button-press-event", self._drag_press)
        rail.connect("button-release-event", self._drag_release)
        rail.connect("motion-notify-event", self._drag_motion)
        overlay.add_overlay(rail)
        self.rail_ev = rail
        rail.set_visible(self.folded)
        # ---- header ------------------------------------------------------
        head = G.hbox(6)
        G.cls(head, "hdr")
        left = G.vbox(0)
        self.title_lbl = G.label(self.widget_title(), "title")
        left.pack_start(self.title_lbl, False, False, 0)
        self.date_lbl = G.label(tr(""), "date")
        left.pack_start(self.date_lbl, False, False, 0)
        head.pack_start(left, True, True, 0)
        b = G.icon_button("preferences-system-symbolic", "iconbtn",
                          tr("task manager widget settings"))
        b.connect("clicked", lambda _w: launch_settings())
        head.pack_end(b, False, False, 0)
        self.settings_btn = b
        self.fold_btn = G.icon_button("pan-end-symbolic", "iconbtn",
                                      tr("fold the widget to the side (Ctrl+F)"))
        self.fold_btn.connect("clicked", lambda _w: self.set_folded(True))
        head.pack_end(self.fold_btn, False, False, 0)
        main.pack_start(head, False, False, 0)

        # ---- next-up strip -----------------------------------------------
        nu = Gtk.EventBox()
        nu.set_visible_window(True)
        nu.set_can_focus(False)
        G.cls(nu, "nextup")
        inner = G.hbox(8)
        self.nu_tag = G.label(tr("next up"), "nlabel")
        inner.pack_start(self.nu_tag, False, False, 0)
        self.nu_dot = G.dot(8, 9)
        inner.pack_start(self.nu_dot, False, False, 0)
        self.nu_title = G.label(tr(""), "ntitle")
        self.nu_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.nu_title.set_max_width_chars(22)
        inner.pack_start(self.nu_title, True, True, 0)
        self.nu_count = G.label(tr(""), "ncount")
        inner.pack_end(self.nu_count, False, False, 0)
        nu.add(inner)
        nu.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        nu.connect("button-press-event", self._nextup_click)
        nu.set_tooltip_text(tr("the next task coming up — click to open its day"))
        self.nextup = nu
        self._nextup_date = None
        main.pack_start(nu, False, False, 0)
        main.pack_start(G.divider(), False, False, 0)

        # ---- search + filter --------------------------------------------
        srow = G.hbox(6)
        G.cls(srow, "searchrow")
        self.entry = Gtk.Entry()
        G.cls(self.entry, "entry")
        self.entry.set_placeholder_text(tr("search tasks"))
        self.entry.set_hexpand(True)
        self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY,
                                           "system-search-symbolic")
        self.entry.connect("changed", self._on_search)
        srow.pack_start(self.entry, True, True, 0)
        fb = G.icon_button("view-filter-symbolic", "iconbtn", tr("filter"))
        fb.connect("clicked", self._open_filter)
        self.filter_btn = fb
        srow.pack_end(fb, False, False, 0)
        main.pack_start(srow, False, False, 0)
        main.pack_start(G.divider(), False, False, 0)

        # ---- scrolling body ---------------------------------------------
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(False)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)
        scroll.set_shadow_type(Gtk.ShadowType.NONE)
        G.cls(scroll, "scroll")
        self.scroll = scroll
        body = G.vbox(0)
        self.body = body
        scroll.add(body)
        main.pack_start(scroll, True, True, 0)

        # month navigation
        nav = G.hbox(4)
        G.cls(nav, "calnav")
        prev = G.icon_button("go-previous-symbolic", "calnavbtn", tr("previous month"))
        prev.connect("clicked", lambda _w: self._shift_month(-1))
        nxt = G.icon_button("go-next-symbolic", "calnavbtn", tr("next month"))
        nxt.connect("clicked", lambda _w: self._shift_month(1))
        self.cal_prev, self.cal_next = prev, nxt
        nav.pack_start(prev, False, False, 0)
        self.month_lbl = G.label(tr(""), "caltitle")
        self.month_lbl.set_xalign(0.5)
        self.month_lbl.set_hexpand(True)
        nav.pack_start(self.month_lbl, True, True, 0)
        nav.pack_start(nxt, False, False, 0)
        body.pack_start(nav, False, False, 0)

        self.cal = CalendarView(self.cfg)
        self.cal.on_day = self._pick_day
        self.cal.on_day_tasks = self._open_day_popover
        self.cal.set_selected(self.f_date)
        self.cal.set_tooltip_text(
            tr("click a day number to set the date · click a day's dots to "
            "open it and tick tasks off"))
        body.pack_start(self.cal, False, False, 0)

        body.pack_start(G.divider(), False, False, 0)
        self.days_box = G.vbox(0)
        body.pack_start(self.days_box, False, False, 0)
        body.pack_start(G.divider(), False, False, 0)
        self.today_box = G.vbox(0)
        body.pack_start(self.today_box, False, False, 0)

        main.pack_start(G.divider(), False, False, 0)

        # ---- create-task form -------------------------------------------
        main.pack_end(self._build_form(), False, False, 0)

        win.connect("destroy", self._on_destroy)
        win.connect("key-press-event", self._on_key)
        self._retext()

    # ------------------------------------------------------------- form -----

    def _build_form(self) -> Gtk.Box:
        f = G.vbox(7)

        r0 = G.hbox(6)
        self.lbl_new_task = G.label(tr("new task"), "formlabel")
        r0.pack_start(self.lbl_new_task, False, False, 0)
        self.color_lbl = G.label(tr(""), "hint")
        self.color_lbl.set_xalign(1.0)
        r0.pack_end(self.color_lbl, True, True, 0)
        f.pack_start(r0, False, False, 0)

        sw = G.hbox(3)
        self.sw_btns = []
        for i in range(len(PALETTE)):
            b = G.swatch_button(i, self._pick_color)
            self.sw_btns.append(b)
            sw.pack_start(b, False, False, 0)
        f.pack_start(sw, False, False, 0)

        r1 = G.hbox(6)
        self.tentry = Gtk.Entry()
        G.cls(self.tentry, "entry")
        self.tentry.set_placeholder_text(tr("what needs doing?"))
        self.tentry.set_hexpand(True)
        self.tentry.connect("activate", lambda _w: self._add_task())
        self.tentry.connect("changed", self._on_title_changed)
        r1.pack_start(self.tentry, True, True, 0)
        self.btn_add = G.button(tr("add"), "btn suggested", tr("create the task"))
        self.btn_add.connect("clicked", lambda _w: self._add_task())
        r1.pack_start(self.btn_add, False, False, 0)
        f.pack_start(r1, False, False, 0)

        r2 = G.hbox(6)
        self.chip_long = G.button(tr("long-term"), "chip",
                                  tr("no fixed time — runs until you finish it"))
        self.chip_long.connect("clicked", lambda _w: self._toggle_long())
        r2.pack_start(self.chip_long, False, False, 0)
        self.chip_rep = G.button(tr("no repeat"), "chip", tr("recurring"))
        self.chip_rep.connect("clicked", lambda _w: self._cycle_repeat())
        self.chip_rep.set_no_show_all(True)
        r2.pack_start(self.chip_rep, False, False, 0)
        self.btn_when = G.button(tr(""), "calbtn", tr("date and time"))
        self.btn_when.connect("clicked", self._open_when)
        r2.pack_start(self.btn_when, True, True, 0)
        f.pack_start(r2, False, False, 0)

        return f

    # -------------------------------------------------------- form sync -----

    def _warn(self, text: str) -> None:
        if self._warn_src:
            GLib.source_remove(self._warn_src)
            self._warn_src = None
        if not text:
            self.color_lbl.get_style_context().remove_class("warn")
            self._update_hint()
            return
        self.color_lbl.set_text(text)
        self.color_lbl.get_style_context().add_class("warn")
        self._warn_src = GLib.timeout_add_seconds(3, self._expire_warn)

    def _expire_warn(self) -> bool:
        self._warn_src = None
        self.color_lbl.get_style_context().remove_class("warn")
        self._update_hint()
        return False

    def _sync_form(self) -> None:
        for i, b in enumerate(self.sw_btns):
            G.toggle_cls(b, "sel", i == self.f_color)
        self._update_hint()

        G.toggle_cls(self.chip_long, "on", self.f_long)
        self.chip_long.set_label(tr("long-term ✓") if self.f_long
                                 else tr("long-term"))

        self.chip_rep.set_visible(not self.f_long)
        self.chip_rep.set_label(tr(REPEAT_LABEL.get(self.f_repeat, "no repeat")))
        G.toggle_cls(self.chip_rep, "on", self.f_long is False and self.f_repeat != "none")

        if self.f_long:
            if self.f_deadline:
                self.btn_when.set_label(
                    tr("by {d}", d=self._day_label(self.f_date)))
            else:
                self.btn_when.set_label(tr("no deadline"))
            G.toggle_cls(self.btn_when, "on", self.f_deadline)
        else:
            hh, mm = self.f_time
            self.btn_when.set_label(
                f"{self._day_label(self.f_date)} {hh:02d}:{mm:02d}")
            G.toggle_cls(self.btn_when, "on", self.f_date != self.day)

        if self._when_pop is not None and hasattr(self, "_when_pop_dl"):
            self._when_pop_time.set_visible(not self.f_long)
            self._when_pop_dl.set_visible(self.f_long)
            self._sp_h.set_value(self.f_time[0])
            self._sp_m.set_value(self.f_time[1])
            self._chk_dl.set_active(self.f_deadline)
            self._f_cal.set_selected(self.f_date)
            self._f_cal.set_month(self.f_date.year, self.f_date.month)

    def _day_label(self, d: dt.date) -> str:
        if d == self.day:
            return tr("today")
        if d == self.day + dt.timedelta(days=1):
            return tr("tomorrow")
        if d == self.day - dt.timedelta(days=1):
            return tr("yesterday")
        return i18n.fmt(d, "%a %d %b")

    def _pick_color(self, i: int) -> None:
        self.f_color = i % len(PALETTE)
        self._sync_form()
        self._warn("")

    def _toggle_long(self) -> None:
        self.f_long = not self.f_long
        if self.f_long:
            self.f_repeat = "none"
        self._sync_form()

    def _cycle_repeat(self) -> None:
        i = REPEATS.index(self.f_repeat) if self.f_repeat in REPEATS else 0
        self.f_repeat = REPEATS[(i + 1) % len(REPEATS)]
        self._sync_form()

    def _pick_day(self, d: dt.date) -> None:
        """Clicking a day in the top calendar sets the task's date."""
        self.f_date = d
        self.cal.set_selected(d)
        self._sync_form()
        if self._when_pop is not None and hasattr(self, "_when_pop_dl"):
            self._when_pop_time.set_visible(not self.f_long)
            self._when_pop_dl.set_visible(self.f_long)

    def _open_when(self, _btn) -> None:
        if self._when_pop is None:
            self._build_when()
        p = self._when_pop
        p.set_relative_to(self.btn_when)
        self._sync_form()
        p.show_all()
        self._when_pop_time.set_visible(not self.f_long)
        self._when_pop_dl.set_visible(self.f_long)
        p.popup()

    def _build_when(self) -> None:
        p = G.popover_for(self.btn_when)
        self._when_pop = p
        self._constrain(p)
        box = G.vbox(8)

        self._f_cal = CalendarView(self.cfg)
        self._f_cal.on_day = self._pick_day
        d, rows = month_days(self.f_date.year, self.f_date.month)
        self._f_cal.set_data({}, d, rows)
        self._f_cal.set_selected(self.f_date)
        self._f_cal.set_size_request(-1, self._f_cal.required_height())
        box.pack_start(self._f_cal, False, False, 0)

        self._when_pop_time = G.hbox(6)
        self._when_pop_time.pack_start(G.label(tr("time"), "formlabel"), False, False, 0)
        self._sp_h = Gtk.SpinButton.new_with_range(0, 23, 1)
        self._sp_m = Gtk.SpinButton.new_with_range(0, 59, 1)
        for sp in (self._sp_h, self._sp_m):
            sp.set_digits(0)
            sp.set_numeric(True)
            sp.set_width_chars(2)
            sp.connect("value-changed", self._time_changed)
        self._sp_h.set_value(self.f_time[0])
        self._sp_m.set_value(self.f_time[1])
        self._when_pop_time.pack_start(self._sp_h, False, False, 0)
        self._when_pop_time.pack_start(G.label(tr(":"), "formlabel"), False, False, 0)
        self._when_pop_time.pack_start(self._sp_m, False, False, 0)
        box.pack_start(self._when_pop_time, False, False, 0)

        self._when_pop_dl = G.hbox(6)
        self._chk_dl = Gtk.CheckButton.new_with_label("set a deadline")
        self._chk_dl.set_active(self.f_deadline)
        self._chk_dl.connect("toggled", self._deadline_toggled)
        G.cls(self._chk_dl, "hint")
        self._when_pop_dl.pack_start(self._chk_dl, False, False, 0)
        box.pack_start(self._when_pop_dl, False, False, 0)

        done = G.button(tr("done"), "btn suggested")
        done.connect("clicked", lambda _w: self._when_pop.popdown())
        box.pack_end(done, False, False, 0)

        box.show_all()
        p.add(box)
    def _time_changed(self, _w) -> None:
        self.f_time = (int(self._sp_h.get_value()), int(self._sp_m.get_value()))
        self._sync_form()

    def _deadline_toggled(self, w) -> None:
        self.f_deadline = w.get_active()
        self._sync_form()

    def _add_task(self) -> None:
        raw = self.tentry.get_text().strip()
        if not raw:
            self._warn("a title is needed")
            self.tentry.grab_focus()
            return
        title = raw
        if self.feat("nl_time"):
            parsed = nltime.parse(raw)
            if parsed.found:
                if parsed.date is not None:
                    self.f_date = parsed.date
                if parsed.time is not None and not self.f_long:
                    self.f_time = parsed.time
                if parsed.title.strip():
                    title = parsed.title.strip()
                self.tentry.handler_block_by_func(self._on_title_changed)
                try:
                    self.tentry.set_text(title)
                finally:
                    self.tentry.handler_unblock_by_func(self._on_title_changed)
        if self.f_long:
            start = self.day if self.f_date >= self.day else self.f_date
            when = dt.datetime.combine(start, dt.time(0, 0))
            dl = (dt.datetime.combine(self.f_date, dt.time(23, 59))
                  if self.f_deadline else None)
            t = Task.new(title, self.f_color, "longterm", when=when, deadline=dl)
        else:
            when = dt.datetime.combine(self.f_date, dt.time(*self.f_time))
            t = Task.new(title, self.f_color, "timed", when=when,
                         repeat=self.f_repeat)
        self.store.add(t)
        self.tentry.set_text(tr(""))
        self.tentry.grab_focus()
        self._warn("")
        self.cal.set_month(t.when_dt().year, t.when_dt().month)
        self.refresh()

    # ---------------------------------------------------------- filtering ---

    def _on_search(self, entry) -> None:
        self.search = entry.get_text()
        self._rebuild_lists()

    def _open_filter(self, _b) -> None:
        if getattr(self, "_filter_pop", None) is not None:
            try:
                self._filter_pop.destroy()
            except Exception:
                pass
            self._filter_pop = None
        p = G.popover_for(self.filter_btn)
        self._filter_pop = p
        self._constrain(p)
        box = G.vbox(8)
        box.pack_start(G.label(tr("show only these colours"), "formlabel"), False, False, 0)
        sw = G.hbox(3)
        self._filter_sw = []
        for i in range(len(PALETTE)):
            b = G.swatch_button(i, self._toggle_filter)
            G.toggle_cls(b, "sel", i in self.filter_colors)
            self._filter_sw.append(b)
            sw.pack_start(b, False, False, 0)
        box.pack_start(sw, False, False, 0)

        r1 = G.hbox(8)
        r1.pack_start(G.label(tr("hide finished tasks"), "slabel"), True, True, 0)
        r1.pack_end(G.switch(self.hide_done, self._set_hide_done), False, False, 0)
        box.pack_start(r1, False, False, 0)

        r2 = G.hbox(8)
        r2.pack_start(G.label(tr("hide days with nothing"), "slabel"), True, True, 0)
        r2.pack_end(G.switch(self.hide_empty, self._set_hide_empty), False, False, 0)
        box.pack_start(r2, False, False, 0)

        clr = G.button(tr("clear colour filter"), "btn")
        clr.connect("clicked", lambda _w: self._clear_colors())
        box.pack_start(clr, False, False, 0)

        box.show_all()
        p.add(box)
        p.popup()

    def _clear_colors(self) -> None:
        self.filter_colors.clear()
        for i, b in enumerate(getattr(self, "_filter_sw", [])):
            G.toggle_cls(b, "sel", False)
        self._filter_changed()

    def _toggle_filter(self, i: int) -> None:
        if i in self.filter_colors:
            self.filter_colors.discard(i)
        else:
            self.filter_colors.add(i)
        for idx, b in enumerate(getattr(self, "_filter_sw", [])):
            G.toggle_cls(b, "sel", idx in self.filter_colors)
        self._filter_changed()

    def _filter_changed(self) -> None:
        G.toggle_cls(self.filter_btn, "on", bool(self.filter_colors)
                     or self.hide_done or self.hide_empty)
        self._rebuild_lists()

    def _set_hide_done(self, v: bool) -> None:
        self.hide_done = v
        self._filter_changed()

    def _set_hide_empty(self, v: bool) -> None:
        self.hide_empty = v
        self._filter_changed()

    def _match(self, e) -> bool:
        if self.filter_colors and e.task.color not in self.filter_colors:
            return False
        if self.hide_done and e.done:
            return False
        q = self.search.strip().lower()
        if q and q not in e.task.title.lower():
            return False
        return True

    # ------------------------------------------------------------ rows ------

    def _row(self, e, show_time: bool) -> Gtk.Widget:
        t = e.task
        ev = Gtk.EventBox()
        ev.set_visible_window(True)
        ev.set_can_focus(self.feat("shortcuts"))
        ev.set_hexpand(True)
        G.cls(ev, "row")
        if e.retro:
            G.cls(ev, "retro")
        if e.done:
            G.cls(ev, "done")

        row = G.hbox(7)

        # colour marker — becomes a progress ring once the task has steps
        if self.feat("steps"):
            holder = Gtk.Button()
            holder.set_relief(Gtk.ReliefStyle.NONE)
            holder.set_can_focus(False)
            G.cls(holder, "dotbtn")
            if t.has_steps:
                col = theme.theme_colors(self.cfg)
                ring = G.StepRing(
                    theme.hex_rgba(PALETTE[t.color % len(PALETTE)][1]),
                    size=14, track=theme.parse_css_color(col["line"]))
                ring.set_progress(*t.step_counts)
                holder.add(ring)
                done, total = t.step_counts
                holder.set_tooltip_text(
                    tr("{d} of {t} steps done — click to edit",
                       d=done, t=total))
            else:
                holder.add(G.dot(t.color, 9))
                holder.set_tooltip_text(tr("steps / subtasks — click to add some"))
            holder.connect("clicked", lambda _w, tk=t: self._open_steps(holder, tk))
            row.pack_start(holder, False, False, 0)
        else:
            row.pack_start(G.dot(t.color, 9), False, False, 0)

        lab = G.label(t.title, "ttext")
        lab.set_ellipsize(Pango.EllipsizeMode.END)
        lab.set_max_width_chars(24)
        lab.set_hexpand(True)
        row.pack_start(lab, True, True, 0)

        if show_time:
            if t.is_longterm:
                dl = t.deadline_dt()
                txt = dl.strftime("%H:%M") if dl else "—"
            else:
                txt = e.occ.strftime("%H:%M") if e.occ else ""
            row.pack_start(G.label(txt, "ttime"), False, False, 0)

        if e.badge:
            css = "badge " + ("done" if e.badge == "done" else "late")
            row.pack_start(G.label(tr(e.badge), css), False, False, 0)

        if t.has_steps and self.feat("steps"):
            d, tot = t.step_counts
            row.pack_start(G.label(f"{d}/{tot}", "ttime"), False, False, 0)

        chk = Gtk.Button()
        chk.set_relief(Gtk.ReliefStyle.NONE)
        chk.set_can_focus(False)
        chk.set_always_show_image(True)
        chk.set_image(Gtk.Image.new_from_icon_name("object-select-symbolic",
                                                   Gtk.IconSize.MENU))
        G.cls(chk, "check")
        if e.done:
            G.cls(chk, "on")
        chk.set_tooltip_text(tr("mark as done") if not e.done
                             else tr("mark as not done"))
        chk.connect("clicked", lambda _w: self._toggle_done(e))
        row.pack_start(chk, False, False, 0)

        delb = G.icon_button("edit-delete-symbolic", "del", tr("delete this task"))
        delb.connect("clicked", lambda _w: self._delete(t.id))
        row.pack_end(delb, False, False, 0)

        if self.feat("shortcuts"):
            ev.connect("key-press-event", self._row_key, e)
            ev.set_tooltip_text(tr("Enter toggles done · Delete removes it"))

        ev.add(row)
        ev.show_all()
        return ev

    def _row_key(self, widget, event, e) -> bool:
        k = event.keyval
        if k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self._toggle_done(e)
            return True
        if k in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            self._delete(e.task.id)
            return True
        return False

    # --------------------------------------------------- day / steps popups -

    def _close_pop(self, attr: str) -> None:
        pop = getattr(self, attr, None)
        if pop is not None:
            try:
                pop.destroy()
            except Exception:
                pass
            setattr(self, attr, None)

    def _open_day_popover(self, day: dt.date, rect=None) -> None:
        """Quick-complete: tap a day's dots to see and tick off its tasks."""
        if not self.feat("day_popover"):
            self._pick_day(day)
            return
        self._close_pop("_day_pop")
        p = G.popover_for(self.cal)
        self._day_pop = p
        self._constrain(p)
        if rect is not None:
            p.set_pointing_to(rect)

        box = G.vbox(6)
        head = G.hbox(8)
        head.pack_start(G.label(i18n.fmt(day, "%A %d %B"), "dpoptitle"),
                        True, True, 0)
        close = G.icon_button("window-close-symbolic", "iconbtn", tr("close"))
        close.connect("clicked", lambda _w: p.popdown())
        head.pack_end(close, False, False, 0)
        box.pack_start(head, False, False, 0)

        sub_lbl = G.label(tr(""), "dpopsub")
        box.pack_start(sub_lbl, False, False, 0)
        box.pack_start(G.divider(), False, False, 0)

        rows = G.vbox(4)
        holder = Gtk.ScrolledWindow()
        holder.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        holder.set_propagate_natural_height(True)
        holder.set_max_content_height(250)
        holder.set_shadow_type(Gtk.ShadowType.NONE)
        G.cls(holder, "scroll")
        holder.add(rows)
        box.pack_start(holder, False, False, 0)

        use_date = G.button(tr("use as date"), "btn")
        use_date.connect("clicked",
                         lambda _w: (self._pick_day(day), p.popdown()))
        box.pack_start(use_date, False, False, 0)

        def rebuild() -> None:
            clear(rows)
            entries = [e for e in self.store.day_entries(day)
                       if self._match(e)]
            sub = i18n.plural(len(entries), "{n} task", "{n} tasks")
            if day == self.day:
                sub = tr("today") + " · " + sub
            sub_lbl.set_text(sub)
            if entries:
                for e in entries:
                    rows.pack_start(self._day_row(e, rebuild), False, False, 0)
            else:
                rows.pack_start(G.label(tr("nothing planned"), "gempty"),
                                False, False, 0)
            rows.show_all()

        rebuild()
        box.show_all()
        p.add(box)
        p.popup()

    @staticmethod
    def _constrain(p) -> None:
        """Keep popovers fully on screen (they can be wide and tall)."""
        try:
            p.set_constrain_to(Gtk.PopoverConstraint.SCREEN)
        except (AttributeError, TypeError):
            pass

    def _day_row(self, e, rebuild) -> Gtk.Widget:
        t = e.task
        row = G.hbox(7)
        G.cls(row, "steprow")
        row.pack_start(G.dot(t.color, 9), False, False, 0)
        lab = G.label(t.title, "steptext")
        lab.set_ellipsize(Pango.EllipsizeMode.END)
        lab.set_max_width_chars(26)
        lab.set_hexpand(True)
        if e.done:
            G.cls(lab, "done")
        row.pack_start(lab, True, True, 0)
        if not e.is_lt and e.occ:
            row.pack_start(G.label(e.occ.strftime("%H:%M"), "ttime"),
                           False, False, 0)
        if e.badge:
            css = "badge " + ("done" if e.badge == "done" else "late")
            row.pack_start(G.label(tr(e.badge), css), False, False, 0)

        chk = Gtk.Button()
        chk.set_relief(Gtk.ReliefStyle.NONE)
        chk.set_can_focus(False)
        chk.set_always_show_image(True)
        chk.set_image(Gtk.Image.new_from_icon_name("object-select-symbolic",
                                                   Gtk.IconSize.MENU))
        G.cls(chk, "check")
        if e.done:
            G.cls(chk, "on")
        chk.set_tooltip_text(tr("mark as done") if not e.done
                             else tr("mark as not done"))

        def toggle(_w, ent=e) -> None:
            self._toggle_done(ent)
            rebuild()

        chk.connect("clicked", toggle)
        row.pack_start(chk, False, False, 0)
        return row

    def _open_steps(self, anchor, task: Task) -> None:
        if not self.feat("steps"):
            return
        self._close_pop("_step_pop")
        p = G.popover_for(anchor)
        self._step_pop = p
        self._constrain(p)
        box = G.vbox(6)

        head = G.hbox(8)
        head.pack_start(G.label(tr("steps"), "dpoptitle"), True, True, 0)
        count_lbl = G.label(tr(""), "dpopsub")
        head.pack_end(count_lbl, False, False, 0)
        box.pack_start(head, False, False, 0)
        box.pack_start(G.label(task.title, "dpopsub"), False, False, 0)

        holder = G.vbox(0)
        holder.set_size_request(-1, 10)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        scroll.set_max_content_height(180)
        scroll.set_shadow_type(Gtk.ShadowType.NONE)
        G.cls(scroll, "scroll")
        listbox = G.vbox(2)
        scroll.add(listbox)
        holder.pack_start(scroll, True, True, 0)
        box.pack_start(holder, False, False, 0)

        def rebuild() -> None:
            clear(listbox)
            for s in task.steps:
                r = G.hbox(7)
                G.cls(r, "steprow")
                b = Gtk.Button()
                b.set_relief(Gtk.ReliefStyle.NONE)
                b.set_can_focus(False)
                b.set_always_show_image(True)
                b.set_image(Gtk.Image.new_from_icon_name("object-select-symbolic",
                                                         Gtk.IconSize.MENU))
                G.cls(b, "check")
                if s.get("done"):
                    G.cls(b, "on")
                sid = s.get("id")
                b.connect("clicked", lambda _w, i=sid:
                          (task.toggle_step(i), self._save_steps(task), rebuild()))
                r.pack_start(b, False, False, 0)
                txt = G.label(s.get("title", ""), "steptext")
                txt.set_ellipsize(Pango.EllipsizeMode.END)
                txt.set_max_width_chars(28)
                txt.set_hexpand(True)
                if s.get("done"):
                    G.cls(txt, "done")
                r.pack_start(txt, True, True, 0)
                d = G.icon_button("window-close-symbolic", "stepdel", tr("remove"))
                d.connect("clicked", lambda _w, i=sid:
                          (task.remove_step(i), self._save_steps(task), rebuild()))
                r.pack_end(d, False, False, 0)
                listbox.pack_start(r, False, False, 0)
            if not task.steps:
                listbox.pack_start(
                    G.label(tr("no steps yet — add the first one below"), "gempty"),
                    False, False, 0)
            d_count, t_count = task.step_counts
            count_lbl.set_text(f"{d_count}/{t_count}")
            listbox.show_all()

        rebuild()

        add_row = G.hbox(6)
        add = Gtk.Entry()
        G.cls(add, "entry")
        add.set_placeholder_text(tr("add a step…"))
        add.set_hexpand(True)
        add.set_width_chars(18)

        def add_step(_w=None) -> None:
            task.add_step(add.get_text())
            add.set_text(tr(""))
            self._save_steps(task)
            rebuild()

        add.connect("activate", add_step)
        btn = G.button(tr("add"), "btn")
        btn.connect("clicked", add_step)
        add_row.pack_start(add, True, True, 0)
        add_row.pack_start(btn, False, False, 0)
        box.pack_start(add_row, False, False, 0)

        foot = G.hbox(6)
        clr = G.button(tr("clear all"), "btn")
        clr.connect("clicked", lambda _w: (task.clear_steps(),
                                           self._save_steps(task), rebuild()))
        foot.pack_start(clr, False, False, 0)
        use = G.button(tr("done"), "btn suggested")
        use.connect("clicked", lambda _w: p.popdown())
        foot.pack_end(use, False, False, 0)
        box.pack_start(foot, False, False, 0)

        box.show_all()
        p.add(box)
        p.popup()
        GLib.timeout_add(150, lambda: self._focus_widget(add))

    @staticmethod
    def _focus_widget(w) -> bool:
        try:
            w.grab_focus()
        except Exception:
            pass
        return False

    def _save_steps(self, task: Task) -> None:
        self.store.save()
        self._touch_store()
        self.refresh()

    def _toggle_done(self, e) -> None:
        t = e.task
        # read the live state: the Entry snapshot goes stale as soon as the
        # task changes, which would make a second toggle a no-op
        now_done = t.is_done_at(e.occ)
        t.mark_done(e.occ, not now_done)
        self.store.save()
        self._touch_store()
        self.refresh()

    def _delete(self, task_id: str) -> None:
        self.store.remove(task_id)
        self._touch_store()
        self.refresh()

    # ------------------------------------------------------- next-up strip --

    @staticmethod
    def _countdown(when: dt.datetime, now: dt.datetime) -> tuple[str, bool]:
        secs = (when - now).total_seconds()
        late = secs < -60
        if secs < 60 and not late:
            return tr("now"), False
        m = int(abs(secs) // 60)
        if m < 60:
            body = tr("{n} min", n=m)
        else:
            h, m = divmod(m, 60)
            if h < 24:
                body = (tr("{h} h {m} min", h=h, m=m) if m
                        else tr("{h} h", h=h))
            else:
                d, h = divmod(h, 24)
                body = tr("{d} d {h} h", d=d, h=h) if h else tr("{d} d", d=d)
        return (tr("overdue {body}", body=body) if late
                else tr("in {body}", body=body)), late

    def _next_candidate(self, now: dt.datetime):
        grace = now - dt.timedelta(hours=2)
        horizon = self.day + dt.timedelta(days=45)
        best = None
        for t in self.store.tasks:
            if t.is_longterm:
                if t.done:
                    continue
                dl = t.deadline_dt()
                if dl is None:
                    continue
                when, occ = dl, None
            else:
                when, occ = None, None
                for o in t.occurrences(self.day, horizon):
                    if t.is_done_at(o):
                        continue
                    if o < grace:
                        continue
                    when, occ = o, o
                    break
                if when is None:
                    continue
            if when < grace:
                continue
            if best is None or when < best[0]:
                best = (when, t, occ)
        return best

    def _update_nextup(self) -> None:
        now = dt.datetime.now()
        best = self._next_candidate(now) if self.feat("next_up") else None
        if not best:
            self._nextup_live = False
            self._nextup_date = None
            self.nextup.hide()
            return
        when, task, _occ = best
        for i in range(len(PALETTE)):
            self.nu_dot.get_style_context().remove_class(f"c{i}")
        G.cls(self.nu_dot, f"c{task.color % len(PALETTE)}")
        self.nu_title.set_text(task.title)
        text, late = self._countdown(when, now)
        self.nu_count.set_text(text)
        G.toggle_cls(self.nextup, "late", late)
        self._nextup_date = when.date()
        self._nextup_live = True
        self.nextup.show()

    def _nextup_click(self, _w, _event) -> bool:
        if not self._nextup_live or self._nextup_date is None:
            return False
        if not self.feat("day_popover"):
            return False
        day = self._nextup_date
        self._open_day_popover(day, self.cal._cell_rect(day))
        return True

    # ------------------------------------------------------------- folding --

    def _fold_side(self) -> str:
        wx, wy, ww, wh = G.workarea()
        x, y = self.win.get_position()
        w, h = self._win_size()
        return "right" if x + w / 2.0 > wx + ww / 2.0 else "left"

    @staticmethod
    def _set_icon(btn: Gtk.Button, name: str) -> None:
        img = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.BUTTON)
        btn.set_always_show_image(True)
        btn.set_image(img)

    def _update_fold_icons(self) -> None:
        side = self._fold_side()
        if side == "right":
            self._set_icon(self.fold_btn, "pan-end-symbolic")
            self._set_icon(self.rail_btn, "pan-start-symbolic")
        else:
            self._set_icon(self.fold_btn, "pan-start-symbolic")
            self._set_icon(self.rail_btn, "pan-end-symbolic")

    def _apply_fold_visuals(self) -> None:
        if self.folded:
            self.main.hide()
            self.rail_ev.set_no_show_all(False)
            self.rail_ev.show_all()
            self.rail_ev.set_no_show_all(True)
            G.set_cursor(self.rail_ev, "fleur" if self.drag_mode else "pointer")
        else:
            self.rail_ev.hide()
            self.main.show()
        self._update_fold_icons()

    def set_folded(self, on: bool, persist: bool = True) -> None:
        on = bool(on)
        if on == self.folded:
            self._update_fold_icons()
            return
        # use geometry() (derived from cfg + folded), never a live allocation:
        # reading the allocation mid-resize is what caused position drift.
        wx, wy, ww, wh = G.workarea()
        old_w, old_h = self.geometry()
        x, y = self._pos()
        self.folded = on
        nw, nh = self.geometry()
        self.win.set_size_request(nw, nh)
        try:
            self.win.resize(nw, nh)
        except Exception:
            pass
        # keep whichever edge already hugs the screen edge
        nx = x + old_w - nw if x + old_w / 2.0 > wx + ww / 2.0 else x
        nx, ny = self._clamp_xy(nx, y, nw, nh)
        self._move(nx, ny)
        self._apply_fold_visuals()
        if not on:
            self._sync_form()
            self._update_nextup()
        if persist:
            self._save_state(nx, ny)
        GLib.timeout_add(600, self._settle)

    # ------------------------------------------------------- keyboard (⌘) ---

    def _on_key(self, _w, event) -> bool:
        if not self.feat("shortcuts"):
            return False
        key = event.keyval
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        focused = self.win.get_focus()
        editable = isinstance(focused, Gtk.Entry)

        if ctrl and key in (Gdk.KEY_n, Gdk.KEY_N):
            self.tentry.grab_focus()
            self.tentry.select_region(0, -1)
            return True
        if ctrl and key in (Gdk.KEY_f, Gdk.KEY_F):
            self.set_folded(not self.folded)
            return True
        if ctrl and key in (Gdk.KEY_slash, Gdk.KEY_question):
            self.entry.grab_focus()
            self.entry.select_region(0, -1)
            return True
        if key == Gdk.KEY_slash and not editable:
            self.entry.grab_focus()
            self.entry.select_region(0, -1)
            return True
        if key == Gdk.KEY_Escape:
            if editable:
                self.win.set_focus(None)
                return True
            return False
        return False

    # --------------------------------------------------- natural language ---

    def _on_title_changed(self, _e) -> None:
        if self._nl_src:
            GLib.source_remove(self._nl_src)
            self._nl_src = None
        if not self.feat("nl_time"):
            self._update_hint()
            return
        self._nl_src = GLib.timeout_add(320, self._nl_tick)

    def _nl_tick(self) -> bool:
        self._nl_src = None
        self._update_hint()
        return False

    def _update_hint(self) -> None:
        """Right-hand label: warning > parsed date/time > colour name."""
        if self._warn_src:
            return
        lbl = self.color_lbl
        sc = lbl.get_style_context()
        sc.remove_class("warn")
        text = tr(PALETTE[self.f_color][0])
        accent = False
        if self.feat("nl_time") and self.tentry is not None:
            raw = self.tentry.get_text().strip()
            if raw:
                hint = nltime.hint_for(nltime.parse(raw)).strip()
                if hint:
                    text, accent = hint, True
        sc.remove_class("accent")
        if accent:
            sc.add_class("accent")
        lbl.set_text(text)

    # --------------------------------------------------------- rendering ----

    def refresh(self) -> None:
        self._rebuild_cal()
        self._rebuild_lists()
        self._update_nextup()
        d = dt.date.today()
        if d != self.day:
            self.day = d
            self.cal.set_today(d)
            self.f_date = d
        self._sync_date_label()
        self._sync_form()

    def _retext(self) -> None:
        """Strings that were assigned once at build time do not follow a
        language change on their own — push the current language through
        every static widget.  Called after building and on every config load.
        """
        try:
            self.entry.set_placeholder_text(tr("search tasks"))
            self.tentry.set_placeholder_text(tr("what needs doing?"))
            self.nu_tag.set_text(tr("next up"))
            self.nextup.set_tooltip_text(
                tr("the next task coming up — click to open its day"))
            self.cal.set_tooltip_text(
                tr("click a day number to set the date · click a day's dots "
                   "to open it and tick tasks off"))
            self.lbl_new_task.set_text(tr("new task"))
            self.btn_add.set_label(tr("add"))
            self.btn_add.set_tooltip_text(tr("create the task"))
            self.filter_btn.set_tooltip_text(tr("filter"))
            self.settings_btn.set_tooltip_text(tr("task manager widget settings"))
            self.fold_btn.set_tooltip_text(tr("fold the widget to the side (Ctrl+F)"))
            self.rail_btn.set_tooltip_text(tr("unfold the widget (Ctrl+F)"))
            self.cal_prev.set_tooltip_text(tr("previous month"))
            self.cal_next.set_tooltip_text(tr("next month"))
            for i, b in enumerate(self.sw_btns):
                b.set_tooltip_text(tr(PALETTE[i % len(PALETTE)][0]))
        except Exception as exc:                # never break the config reload
            print(f"retext: {exc}")
        self._sync_form()
        self._update_nextup()
        self.cal.queue_draw()

    def _sync_date_label(self) -> None:
        self.title_lbl.set_text(self.widget_title())
        self.date_lbl.set_text(i18n.fmt(self.day, "%A %d %B"))
        self.month_lbl.set_text(self.cal.title())

    def _rebuild_cal(self) -> None:
        days, rows = month_days(self.cal.cursor.year, self.cal.cursor.month)
        model = self.store.calendar_model(
            days, only_undone=self.feat("calendar_only_undone", False))
        self.cal.set_data(model, days, rows)
        self.cal.set_size_request(-1, self.cal.required_height())
        self.cal.set_today(self.day)

    def _in_window(self, e, day_offset: int) -> bool:
        """Config-driven filters for the five-day (weekly) view.

        Kept separate from the month calendar on purpose.
        """
        if not self._match(e):
            return False
        if self.feat("weekly_only_undone", False) and e.done:
            return False
        if day_offset == 0 and self.feat("weekly_today_only_undone", False) \
                and e.done:
            return False
        return True

    def _rebuild_lists(self) -> None:
        clear(self.days_box)
        clear(self.today_box)

        show_yesterday = self.feat("show_yesterday", True)
        names = {0: tr("today"), -1: tr("yesterday"), 1: tr("tomorrow")}
        for i in (-1, 0, 1, 2, 3):
            if i == -1 and not show_yesterday:
                continue
            d = self.day + dt.timedelta(days=i)
            entries = [e for e in self.store.day_entries(d)
                       if self._in_window(e, i)]
            if not entries and self.hide_empty:
                continue
            name = names.get(i, i18n.fmt(d, "%A"))
            head = G.hbox(6)
            lab = G.label(name, "glabel")
            lab.set_xalign(0.0)
            head.pack_start(lab, True, True, 0)
            head.pack_end(G.label(i18n.fmt(d, "%d %b"), "glabel"),
                          False, False, 0)
            self.days_box.pack_start(head, False, False, 0)
            if entries:
                for e in entries:
                    self.days_box.pack_start(self._row(e, False), False, False, 0)
            else:
                self.days_box.pack_start(
                    G.label(tr("nothing planned"), "gempty"), False, False, 0)

        head = G.label(tr("today · times"), "glabel")
        self.today_box.pack_start(head, False, False, 0)
        entries = [e for e in self.store.day_entries(self.day)
                   if not e.retro and self._in_window(e, 0)]
        if entries:
            for e in entries:
                self.today_box.pack_start(self._row(e, True), False, False, 0)
        else:
            self.today_box.pack_start(
                G.label(tr("nothing scheduled"), "gempty"), False, False, 0)

        self.days_box.show_all()
        self.today_box.show_all()

    def _shift_month(self, delta: int) -> None:
        self.cal.shift_month(delta)
        self.month_lbl.set_text(self.cal.title())

    def _touch_store(self) -> None:
        self._store_m = mtime(self.store.path)

    # ------------------------------------------------------------- drag -----

    def set_drag_mode(self, on: bool) -> None:
        on = bool(on)
        self.drag_mode = on
        # no_show_all would make GTK skip the whole subtree, so lift it
        # briefly whenever we reveal a curtain.
        if on:
            self.drag_ev.set_no_show_all(False)
            self.drag_ev.show_all()
            self.drag_ev.set_no_show_all(True)
            G.set_cursor(self.drag_ev, "fleur")
            G.toggle_cls(self.rail_ev, "raildrag", True)
            G.set_cursor(self.rail_ev, "fleur")
            self.win.set_keep_below(False)
            self.win.set_keep_below(True)
        else:
            self.drag_ev.hide()
            G.toggle_cls(self.rail_ev, "raildrag", False)
            G.set_cursor(self.rail_ev, "pointer" if self.folded else "")
            self.dragging = False

    def _drag_press(self, _w, event) -> bool:
        if not self.drag_mode or event.button != 1:
            return False
        self._drag_win = self._pos()
        self._drag_ptr = (event.x_root, event.y_root)
        self.dragging = True
        return True

    def _drag_motion(self, _w, event) -> bool:
        if not self.dragging:
            return False
        dx = event.x_root - self._drag_ptr[0]
        dy = event.y_root - self._drag_ptr[1]
        self._move(self._drag_win[0] + dx, self._drag_win[1] + dy)
        return True

    def _drag_release(self, _w, _event) -> bool:
        if not self.dragging:
            return False
        self.dragging = False
        self._clamp_and_save()
        return True

    def _win_size(self) -> tuple[int, int]:
        """Current size, but never a transient or absurd allocation.

        Right after a resize/map GTK can still report the previous (or the
        natural) size; trusting that is what let a preset land off-target.
        """
        gw, gh = self.geometry()
        w = self.win.get_allocated_width()
        h = self.win.get_allocated_height()
        if w < 50 or h < 50 or abs(w - gw) > 80 or abs(h - gh) > 40:
            return gw, gh
        return int(w), int(h)

    def _inside(self, x: int, y: int, w: int, h: int) -> bool:
        wx, wy, ww, wh = G.workarea()
        return (wx <= x <= wx + max(4, ww - w)
                and wy <= y <= wy + max(4, wh - h))

    def _move(self, x: int, y: int) -> None:
        """Move and remember where we asked to be.

        ``get_position()`` can still answer with the *previous* place right
        after a resize (that is how a fold/unfold cycle landed the card at
        x=878), so our own record is the one we trust.
        """
        x, y = int(x), int(y)
        self.win.move(x, y)
        self._last_pos = (x, y)

    def _pos(self) -> tuple[int, int]:
        """Where the window should be — never an unplaced or stale read."""
        w, h = self.geometry()
        if self._last_pos:
            x, y = self._last_pos
            if self._inside(x, y, w, h):
                return int(x), int(y)
        x, y = self.win.get_position()
        if self._inside(int(x), int(y), w, h):
            return int(x), int(y)
        st = config.read_state()
        if "x" in st and "y" in st:
            return int(st["x"]), int(st["y"])
        wx, wy, ww, wh = G.workarea()
        return self._clamp_xy(wx + ww - w - MARGIN, wy + wh - h - MARGIN, w, h)

    def _clamp_xy(self, x: int, y: int, w: int | None = None,
                  h: int | None = None) -> tuple[int, int]:
        wx, wy, ww, wh = G.workarea()
        if w is None or h is None:
            w, h = self._win_size()
        x = max(wx + 4, min(int(x), wx + max(4, ww - int(w) - 4)))
        y = max(wy + 4, min(int(y), wy + max(4, wh - int(h) - 4)))
        return int(x), int(y)

    def _save_state(self, x: int, y: int) -> None:
        config.write_state({"x": int(x), "y": int(y),
                            "preset": self.cfg.get("position_preset",
                                                   "bottom_right"),
                            "folded": bool(self.folded)})

    def _clamp_and_save(self) -> None:
        """After a drag: keep the card inside the workarea and remember it."""
        x, y = self.win.get_position()
        w, h = self._win_size()
        if not self._inside(int(x), int(y), w, h):
            x, y = self._pos()
        x, y = self._clamp_xy(x, y, w, h)
        self._move(x, y)
        self._save_state(x, y)

    def _settle(self, attempt: int = 0) -> bool:
        """Make sure we really ended up where we asked to be.

        On a fresh login the move can be issued before the window manager has
        mapped the window, so mutter falls back to centring it.  A centred
        window is still *inside* the workarea, so the old "only fix if
        outside" rule never corrected it.  Now we compare against our own
        intended position (never a possibly-stale server read) and retry a
        few times.
        """
        if self.dragging:
            return False
        want = self._last_pos
        if not want:
            return False
        w, h = self.geometry()
        x, y = self.win.get_position()
        aligned = abs(int(x) - want[0]) <= 6 and abs(int(y) - want[1]) <= 6
        if aligned and self._inside(int(x), int(y), w, h):
            return False                       # exactly where we asked
        nx, ny = self._clamp_xy(want[0], want[1], w, h)
        self._move(nx, ny)
        self._save_state(nx, ny)
        if attempt < 5:
            GLib.timeout_add(1200,
                             lambda a=attempt + 1: self._settle(a) or False)
        return False

    def apply_preset(self, name: str) -> None:
        if name not in PRESETS:
            name = "bottom_right"
        wx, wy, ww, wh = G.workarea()
        w, h = self.geometry()               # deterministic: presets must not
        x0, y0 = wx + MARGIN, wy + MARGIN    # depend on a live allocation
        x1 = wx + max(x0 - wx, ww - w - MARGIN)
        y1 = wy + max(y0 - wy, wh - h - MARGIN)
        xm = wx + max(0, (ww - w) // 2)
        ym = wy + max(0, (wh - h) // 2)
        table = {
            "bottom_right": (x1, y1), "bottom_left": (x0, y1),
            "bottom_center": (xm, y1),
            "top_right": (x1, y0), "top_left": (x0, y0), "top_center": (xm, y0),
            "right": (x1, ym), "left": (x0, ym), "center": (xm, ym),
        }
        x, y = table.get(name, (x1, y1))
        x, y = self._clamp_xy(int(x), int(y), w, h)
        self._move(x, y)
        self.cfg["position_preset"] = name
        self._save_state(x, y)
        GLib.timeout_add(700, self._settle)     # confirm the WM honoured it

    def restore_position(self) -> None:
        st = config.read_state()
        want = self.cfg.get("position_preset", "bottom_right")
        if st.get("preset") != want:
            # the preset changed while we were not running
            self.apply_preset(want)
            return
        if "x" in st and "y" in st:
            x, y = self._clamp_xy(int(st["x"]), int(st["y"]))
            self._move(x, y)
            GLib.timeout_add(800, self._settle)
        else:
            self.apply_preset(want)

    # ------------------------------------------------------ config / ipc ----

    def _on_cfg_changed(self) -> None:
        old_scale = theme.scale_of(self.cfg)
        cfg = config.load()
        self.cfg = cfg
        i18n.set_language(cfg.get("language"))
        theme.apply_css(cfg)
        self.cal.set_config(cfg)
        if self._when_pop is not None:
            self._f_cal.set_config(cfg)
        k = theme.scale_of(cfg)
        if abs(k - old_scale) > 1e-6:
            w, h = self.geometry()
            self.win.set_size_request(w, h)
            GLib.timeout_add(600, self._settle)

        if bool(cfg.get("drag_mode")) != self.drag_mode:
            self.set_drag_mode(bool(cfg.get("drag_mode")))

        seq = int(cfg.get("preset_seq", 0) or 0)
        if seq != self._preset_seq:
            self._preset_seq = seq
            self.apply_preset(cfg.get("position_preset", "bottom_right"))

        cmd_seq = int(cfg.get("cmd_seq", 0) or 0)
        if cmd_seq != self._cmd_seq:
            self._cmd_seq = cmd_seq
            self._run_cmd(cfg.get("cmd"))

        self.refresh()
        self._retext()

    def _run_cmd(self, cmd) -> None:
        if cmd == "quit":
            self.quit()
        elif cmd == "refresh":
            self.refresh()

    def on_ipc(self, cmd: dict) -> None:
        if not isinstance(cmd, dict):
            return
        if "drag_mode" in cmd:
            config.update(lambda c: c.__setitem__("drag_mode", bool(cmd["drag_mode"])))
            self.set_drag_mode(bool(cmd["drag_mode"]))
        if cmd.get("preset"):
            self.apply_preset(str(cmd["preset"]))
            config.update(lambda c: (c.__setitem__("position_preset", str(cmd["preset"])),
                                     c.__setitem__("preset_seq",
                                                   int(c.get("preset_seq", 0)) + 1)))
        if "fold" in cmd:
            self.set_folded(bool(cmd["fold"]))
        if cmd.get("cmd"):
            self._run_cmd(str(cmd["cmd"]))

    # ------------------------------------------------------------ timers ----

    def _poll(self) -> bool:
        try:
            cm = mtime(paths.config_path())
            sm = mtime(self.store.path)
        except Exception:
            return True
        if cm != self._cfg_m:
            self._cfg_m = cm
            self._on_cfg_changed()
        if sm != self._store_m:
            self._store_m = sm
            self.store.load()
            self.store.prune()
            self.refresh()
        now = dt.datetime.now()
        if now.strftime("%H:%M") != self._minute:
            self._minute = now.strftime("%H:%M")
            if now.date() != self.day:
                self.refresh()
            else:
                self._sync_date_label()
                self._update_nextup()
        self._nu_counter += 1
        if self._nu_counter >= 10:
            self._nu_counter = 0
            self._update_nextup()
        return True

    def _tick_notify(self) -> bool:
        try:
            self.notifier.tick()
        except Exception as exc:                  # never die on a bad task
            print(f"notify error: {exc}")
        return True

    def _on_destroy(self, *_a) -> None:
        Popup.close_all()
        if Gtk.main_level() > 0:
            Gtk.main_quit()

    def quit(self) -> None:
        Popup.close_all()
        self.win.destroy()

    # ------------------------------------------------------------- start ----

    def show(self) -> None:
        self.win.show_all()
        if self.drag_mode:
            self.set_drag_mode(True)
        else:
            self.drag_ev.hide()
        if self.folded:
            self._apply_fold_visuals()
        else:
            self.rail_ev.hide()
        self.restore_position()
        self.win.present()
        # keep it at the very bottom of the stacking order
        self.win.set_keep_below(True)
        self.win.set_focus(self.tentry)
        # show_all() can reveal things a feature toggle had hidden
        self._sync_form()
        self._update_nextup()

        self.notifier = Notifier(self.store, lambda: self.cfg)
        GLib.timeout_add_seconds(1, self._poll)
        GLib.timeout_add_seconds(5, self._tick_notify)
        self._tick_notify()
        GLib.timeout_add_seconds(2, self._maybe_show_intro)
        # On a fresh login the window manager can centre the window after we
        # asked for a place — re-assert it a few seconds in (and _settle keeps
        # retrying while it is wrong).
        GLib.timeout_add(6000, self._settle)

        dbg = os.environ.get("TASKWIDGET_DEBUG_POPOVER", "")
        if dbg:
            print(f"DBG popover={dbg}", flush=True)
            GLib.timeout_add_seconds(1, lambda: self._debug_popover(dbg) or False)

    def _maybe_show_intro(self):
        """First run only: explain the widget once."""
        try:
            if bool(config.load().get("onboarding_seen")):
                return None
        except Exception:
            return None
        from . import intro
        return intro.show(self.win, mark_seen=True)

    def _debug_popover(self, which: str) -> None:
        print(f"DBG enter {which}", flush=True)
        pop = None
        try:
            if which == "when":
                self._open_when(self.btn_when)
                pop = self._when_pop
            elif which == "filter":
                self._open_filter(self.filter_btn)
                pop = self._filter_pop
                GLib.timeout_add(900, lambda: self._print_xid(which, pop) or False)
                return
            elif which == "drag":
                self.set_drag_mode(True)
                lab, tip, ev = self.drag_label, self.drag_tip, self.drag_ev
                GLib.timeout_add(900,
                                 lambda: self._print_drag(lab, tip, ev) or False)
                return
            elif which == "day":
                target = self.day
                for off in range(0, 7):
                    d = self.day + dt.timedelta(days=off)
                    if self.store.day_entries(d):
                        target = d
                        break
                self._open_day_popover(target, self.cal._cell_rect(target))
                pop = self._day_pop
            elif which == "steps":
                task = next((t for t in self.store.tasks), None)
                if task is not None:
                    if not task.steps:
                        for s in ("draft the outline", "write section one",
                                  "get feedback", "polish and ship"):
                            task.add_step(s)
                        task.steps[1]["done"] = True
                        task.steps[3]["done"] = True
                        self.store.save()
                        self._touch_store()
                        self.refresh()
                    self._open_steps(self.cal, task)
                    pop = self._step_pop
        except Exception as exc:
            print(f"debug popover: {exc}", flush=True)
            return
        if pop is not None:
            GLib.timeout_add(900, lambda: self._print_xid(which, pop) or False)

    @staticmethod
    def _print_xid(which: str, pop) -> None:
        from .gtkutil import xid_of
        print(f"POPOVER_XID {which} {xid_of(pop)}", flush=True)
        return False

    @staticmethod
    def _print_drag(lab, tip, ev) -> None:
        def geo(w):
            a = w.get_allocation()
            return (a.x, a.y, a.width, a.height, w.get_visible(), w.get_mapped())
        print("DRAG", "children", len(ev.get_children()),
              "lab_parent", lab.get_parent(),
              "ev", geo(ev), "tip", geo(tip), "lab", geo(lab),
              repr(lab.get_text()), flush=True)
        return False


# ============================================================ entry point ===


def launch_settings() -> None:
    from . import launcher
    launcher.launch_settings()


def main() -> int:
    G.init(x11=True)
    cfg = config.load()
    theme.apply_css(cfg)
    if ipc.alive():
        print("task widget is already running")
        return 1
    w = Widget()
    server = ipc.serve(w.on_ipc)
    try:
        w.show()
        Gtk.main()
    finally:
        server.close()
        Popup.close_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
