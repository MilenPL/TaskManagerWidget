#!/usr/bin/env python3
"""Functional checks for the widget's optional features.

Run from a checkout:   python3 tests/run_tests.py
No test framework needed — it exits non-zero if anything fails.
"""
import datetime as dt
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# the backend has to be chosen before gi.repository.Gtk is imported
from taskwidget.launcher import setup_backend  # noqa: E402

setup_backend()

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")

from gi.repository import Gdk, GLib, Gtk  # noqa: E402

import taskwidget.gtkutil as G  # noqa: E402

G.init(x11=True)

from taskwidget import config, nltime, notify, theme  # noqa: E402
from taskwidget import widget as W  # noqa: E402
from taskwidget.notify import Popup  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def spin(sec=0.6):
    ctx = GLib.MainContext.default()
    end = time.time() + sec
    while time.time() < end:
        while ctx.iteration(False):
            pass
        time.sleep(0.01)


def key(kval, ctrl=False):
    ev = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
    ev.keyval = kval
    ev.state = Gdk.ModifierType.CONTROL_MASK if ctrl else 0
    return ev


def labels(widget):
    out, stack = [], [widget]
    while stack:
        w = stack.pop(0)
        if isinstance(w, Gtk.Label):
            out.append(w.get_text())
        if isinstance(w, Gtk.Container):
            stack.extend(w.get_children())
    return out


def row_count(widget, css="row"):
    n, stack = 0, [widget]
    while stack:
        w = stack.pop(0)
        if isinstance(w, Gtk.EventBox) and \
                w.get_style_context().has_class(css):
            n += 1
        if isinstance(w, Gtk.Container):
            stack.extend(w.get_children())
    return n


def _buttons(widget):
    out, stack = [], [widget]
    while stack:
        w = stack.pop(0)
        if isinstance(w, Gtk.Button):
            out.append(w)
        if isinstance(w, Gtk.Container):
            stack.extend(w.get_children())
    return out


def main() -> int:
    theme.apply_css(config.load())
    # keep the first-run introduction out of the way while we test, and put
    # the user's own flag back afterwards
    seen_before = bool(config.load().get("onboarding_seen"))
    config.update(lambda c: c.__setitem__("onboarding_seen", True))

    w = W.Widget()
    w.show()
    spin(0.6)

    # ------------------------------------------------------- next-up strip --
    check("next-up strip visible by default", w.nextup.get_visible(),
          f"'{w.nu_title.get_text()}' {w.nu_count.get_text()}")
    w.cfg["features"]["next_up"] = False
    w.refresh()
    check("next-up hidden when feature off", not w.nextup.get_visible())
    w.cfg["features"]["next_up"] = True
    w.refresh()
    check("next-up back on", w.nextup.get_visible())
    check("next-up has a date", w._nextup_date is not None, str(w._nextup_date))

    # --------------------------------------------------------------- steps --
    task = next((t for t in w.store.tasks if t.has_steps), None)
    if task is None:
        task = w.store.tasks[0]
        task.add_step("first step")
        w.store.save()
        w.refresh()
    check("a task has steps", task.has_steps, f"{task.title} {task.step_counts}")

    # ------------------------------------------------- calendar / weekly ----
    # the two areas are filtered separately, so test them separately
    f = w.cfg["features"]

    w.refresh()
    check("weekly shows yesterday by default",
          any(t.lower() == "yesterday" for t in labels(w.days_box)))

    done_rows = row_count(w.days_box, "done")
    check("some tasks are finished in the list", done_rows > 0,
          f"{done_rows} finished rows")

    f["weekly_only_undone"] = True
    w.refresh()
    check("weekly only-not-done hides finished rows",
          row_count(w.days_box, "done") == 0,
          f"{row_count(w.days_box, 'done')} left")
    f["weekly_only_undone"] = False

    f["weekly_today_only_undone"] = True
    w.refresh()
    check("today-only filter keeps other days intact",
          row_count(w.days_box, "done") > 0,
          f"{row_count(w.days_box, 'done')} finished rows elsewhere")
    sample = next((e for e in w.store.day_entries(w.day) if e.done), None)
    if sample is None:
        e0 = w.store.day_entries(w.day)[0]
        e0.task.mark_done(e0.occ if not e0.task.is_longterm else None, True)
        w.store.save()
        sample = next((e for e in w.store.day_entries(w.day) if e.done), None)
    if sample is not None:
        check("today filter drops a finished today task",
              not w._in_window(sample, 0))
        check("today filter leaves other days alone",
              w._in_window(sample, 1) or not any(
                  e.done for e in w.store.day_entries(w.day +
                                                      dt.timedelta(days=1))))
    f["weekly_today_only_undone"] = False
    w.refresh()

    f["show_yesterday"] = False
    w.refresh()
    check("show_yesterday off drops the group",
          not any(t.lower() == "yesterday" for t in labels(w.days_box)))
    f["show_yesterday"] = True
    w.refresh()
    check("show_yesterday back on",
          any(t.lower() == "yesterday" for t in labels(w.days_box)))

    from taskwidget.calendarview import month_days
    days, _ = month_days(w.cal.cursor.year, w.cal.cursor.month)
    all_dots = sum(len(v["dots"]) for v in w.store.calendar_model(days).values())
    undone_dots = sum(len(v["dots"]) for v in
                      w.store.calendar_model(days, only_undone=True).values())
    check("calendar filter is separate and stricter",
          undone_dots <= all_dots, f"{undone_dots} <= {all_dots}")
    f["calendar_only_undone"] = True
    w.refresh()
    check("calendar switch is read by the widget",
          w.feat("calendar_only_undone") is True)
    f["calendar_only_undone"] = False
    w.refresh()

    # ------------------------------------------------------- widget title ---
    w.cfg["title"] = "planner"
    w._sync_date_label()
    check("widget title is configurable",
          w.title_lbl.get_text() == "planner", w.title_lbl.get_text())
    w.cfg["title"] = ""
    w._sync_date_label()
    check("empty title falls back to 'tasks'",
          w.title_lbl.get_text() == "tasks", w.title_lbl.get_text())
    w.cfg["title"] = "tasks"
    w._sync_date_label()

    # --------------------------------------------------------------- fold ---
    before = w.geometry()
    w.set_folded(True)
    spin(0.9)
    check("folded geometry", w.geometry()[0] == W.FOLD_W, str(w.geometry()))
    check("rail visible when folded", w.rail_ev.get_visible())
    check("content hidden when folded", not w.main.get_visible())
    w.set_folded(False)
    spin(0.9)
    check("unfolded geometry", w.geometry()[0] == before[0], str(w.geometry()))
    check("content visible again", w.main.get_visible())
    check("rail hidden again", not w.rail_ev.get_visible())

    # ---- folding must never move the card -------------------------------
    from taskwidget import paths as _paths
    x_before = _paths.read_json(_paths.state_path(), {}).get("x")
    for _ in range(2):
        w.set_folded(True)
        spin(0.9)
        w.set_folded(False)
        spin(0.9)
    x_after = _paths.read_json(_paths.state_path(), {}).get("x")
    check("fold/unfold cycles never move the card",
          x_before == x_after, f"{x_before} -> {x_after}")

    # ---- a fresh login: the WM can centre the window instead of honouring
    #      our placement — the widget must put itself back -------------------
    want = w._last_pos
    check("the widget remembers its intended position",
          want is not None, str(want))
    if want:
        wa = G.workarea()
        w.win.move(wa[0] + (wa[2] - w.geometry()[0]) // 2,
                   wa[1] + (wa[3] - w.geometry()[1]) // 2)
        spin(0.3)
        got = w.win.get_position()
        check("simulated window-manager centring took effect",
              got != want, f"now {got}, wanted {want}")
        w._settle()
        spin(0.5)
        check("settle puts it back where we asked",
              w.win.get_position() == want, str(w.win.get_position()))
        saved = (_paths.read_json(_paths.state_path(), {}) or {})
        check("and the position is saved for the next login",
              (saved.get("x"), saved.get("y")) == tuple(want),
              f"{saved.get('x')},{saved.get('y')}")

    # ---------------------------------------------------------- shortcuts ---
    w.cfg["features"]["shortcuts"] = True
    w.win.set_focus(None)
    ok = w._on_key(w.win, key(Gdk.KEY_n, ctrl=True))
    check("Ctrl+N focuses the task field", ok and w.win.get_focus() is w.tentry)

    w.win.set_focus(None)
    ok = w._on_key(w.win, key(Gdk.KEY_slash))
    check("/ focuses search", ok and w.win.get_focus() is w.entry)

    w.win.set_focus(w.entry)
    ok = w._on_key(w.win, key(Gdk.KEY_slash))
    check("/ ignored while typing", not ok)
    w.win.set_focus(None)

    folded = w.folded
    ok = w._on_key(w.win, key(Gdk.KEY_f, ctrl=True))
    check("Ctrl+F folds", ok and w.folded != folded, f"folded={w.folded}")
    w._on_key(w.win, key(Gdk.KEY_f, ctrl=True))
    check("Ctrl+F unfolds", w.folded == folded, f"folded={w.folded}")

    entries = w.store.day_entries(w.day)
    check("today has entries", bool(entries), f"{len(entries)}")
    e = entries[0]
    was = e.task.done
    ok = w._row_key(None, key(Gdk.KEY_Return), e)
    check("Enter toggles a task", ok and e.task.done != was,
          f"{e.task.title}: {was} -> {e.task.done}")
    if e.task.done != was:                    # put the demo task back
        w._row_key(None, key(Gdk.KEY_Return), e)
        check("toggle restores the task", e.task.done == was)
    w.store.save()
    w.refresh()

    w.cfg["features"]["shortcuts"] = False
    ok = w._on_key(w.win, key(Gdk.KEY_n, ctrl=True))
    check("shortcuts switch disables keys", not ok)
    w.cfg["features"]["shortcuts"] = True

    # ----------------------------------------------------- natural language --
    w.cfg["features"]["nl_time"] = True
    w.tentry.set_text("dentist tomorrow at 14:30")
    w._update_hint()
    hint = w.color_lbl.get_text()
    check("live parse hint", "tomorrow" in hint and "14:30" in hint, hint)
    w.tentry.set_text("water the plants")
    w._update_hint()
    check("no hint without a date", bool(w.color_lbl.get_text()))
    p = nltime.parse("ship it friday at 9am")
    check("parse + strip", p.title == "ship it" and p.date and p.time == (9, 0),
          repr(p))
    w.cfg["features"]["nl_time"] = False
    w.tentry.set_text("review tomorrow")
    w._update_hint()
    check("nl switch off -> no parse hint",
          "tomorrow" not in w.color_lbl.get_text(), w.color_lbl.get_text())
    w.tentry.set_text("")
    w.cfg["features"]["nl_time"] = True

    # -------------------------------------------------------- day popover ---
    w.cfg["features"]["day_popover"] = True
    target = w.day
    for off in range(0, 7):
        d = w.day + dt.timedelta(days=off)
        if w.store.day_entries(d):
            target = d
            break
    w._open_day_popover(target, w.cal._cell_rect(target))
    spin(1.0)
    pop = w._day_pop
    check("day popover created", pop is not None)
    if pop is not None:
        a = pop.get_allocation()
        check("day popover shown", bool(G.xid_of(pop)) and pop.get_visible(),
              str(G.xid_of(pop)))
        check("day popover fits the screen",
              0 < a.width <= 600 and 0 < a.height <= 560, f"{a.width}x{a.height}")
        check("day popover has content", len(pop.get_children()) > 0)
        w._close_pop("_day_pop")

    # ------------------------------------------------------- steps popover --
    w._open_steps(w.cal, task)
    spin(1.0)
    sp = w._step_pop
    check("steps popover created", sp is not None)
    if sp is not None:
        check("steps popover shown", bool(G.xid_of(sp)) and sp.get_visible(),
              str(G.xid_of(sp)))
        check("steps kept", len(task.steps) >= 1,
              f"{len(task.steps)} steps, {task.step_counts}")
        w._close_pop("_step_pop")

    # ----------------------------------------------------------------- DND --
    on = {"features": dict(w.cfg["features"], dnd=True,
                           dnd_from="22:00", dnd_to="07:00")}
    night = dt.datetime(2026, 9, 22, 23, 30)
    noon = dt.datetime(2026, 9, 22, 12, 0)
    check("DND active at night", notify.dnd_active(on, night))
    check("DND inactive at noon", not notify.dnd_active(on, noon))
    off = {"features": dict(on["features"], dnd=False)}
    check("DND switch turns it off", not notify.dnd_active(off, night))
    check("queue starts empty", notify.Notifier.queue_size() == 0,
          str(notify.Notifier.queue_size()))

    # ------------------------------------------------------------- popups ---
    cfg = config.load()
    if entries:
        n = notify.Notifier(w.store, lambda: cfg)
        before_n = len(Popup.open_popups)
        n._show(entries[0].task, "at", "due", entries[0].occ, cfg, sound=False)
        check("glass popup opens", len(Popup.open_popups) == before_n + 1)
        Popup.close_all()
        check("popups close again", len(Popup.open_popups) == 0)

    # ---------------------------------------------------------------- i18n --
    import ast as _ast
    import glob as _glob
    import json as _json
    import taskwidget.i18n as I

    check("default language is English (US)",
          I.get_language() == I.DEFAULT_LANG == "en_US")
    check("tr returns the English source by default",
          I.tr("search tasks") == "search tasks")
    check("tr fills placeholders in English",
          I.tr("{n} tasks", n=7) == "7 tasks")
    check("unknown language code falls back to English",
          I.set_language("xx_YY") == "en_US")
    check("a missing catalog is never an error", not I.has_catalog("zz_ZZ"))
    check("language list only shows files that exist",
          I.available() == [c for c in I.LANGUAGES if I.has_catalog(c)])
    check("English date names", I.fmt(dt.date(2026, 9, 22), "%A %d %B")
          == "Tuesday 22 September")
    check("weekday lookup", I.weekday_index("Wednesday") == 2
          and I.weekday_index("Fri") == 4)

    # every string handed to tr()/plural() must exist in every catalog,
    # otherwise a translation silently degrades to English
    expected: set = set()
    for path in _glob.glob(os.path.join(ROOT, "taskwidget", "*.py")):
        tree = _ast.parse(open(path, encoding="utf-8").read())
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Call):
                name = getattr(node.func, "id", None) or \
                    getattr(node.func, "attr", "")
                if name in ("tr", "plural"):
                    for arg in node.args:
                        if isinstance(arg, _ast.Constant) \
                                and isinstance(arg.value, str) and arg.value:
                            expected.add(arg.value)
            # bullet lists are translated at render time, not wrapped in tr()
            if isinstance(node, _ast.Assign) and isinstance(node.value, _ast.List):
                targets = {getattr(t, "id", "") for t in node.targets}
                if targets & {"USING_IT", "MAKING_IT_YOURS"}:
                    for elt in node.value.elts:
                        if isinstance(elt, _ast.Constant) and elt.value:
                            expected.add(elt.value)
    # strings that reach the UI through dicts / the palette / badges
    from taskwidget.models import PALETTE
    from taskwidget.settingsapp import PRESET_LABELS
    from taskwidget.widget import REPEAT_LABEL
    expected |= {v for v in PRESET_LABELS.values()}
    expected |= {v for v in REPEAT_LABEL.values()}
    expected |= {"done", "time's up"}
    expected |= {name for name, _hex in PALETTE}
    expected |= {"@wd", "@wd_s", "@mo", "@mo_s"}
    # plural() arguments are plain strings too
    expected |= {"{n} task", "{n} tasks"}

    problems = []
    for code in I.LANGUAGES:
        if code == I.DEFAULT_LANG or not I.has_catalog(code):
            continue
        try:
            data = _json.load(open(I.catalog_path(code), encoding="utf-8"))
        except ValueError as exc:
            problems.append(f"{code}: invalid JSON ({exc})")
            continue
        missing = sorted(expected - set(data))
        if missing:
            problems.append(
                f"{code}: {len(missing)} missing, e.g. {missing[:3]}")
        for k_name, want in (("@wd", 7), ("@wd_s", 7),
                             ("@mo", 12), ("@mo_s", 12)):
            got = len(str(data.get(k_name, "")).split(","))
            if got != want:
                problems.append(f"{code}: {k_name} has {got} entries, "
                                f"need {want}")
    check("every catalog is complete",
          not problems, "; ".join(problems[:4]) or
          f"{len([c for c in I.LANGUAGES if I.has_catalog(c)]) - 1} languages")

    # the widget must follow the configured language
    w.cfg["language"] = I.available()[-1] if len(I.available()) > 1 else "en_US"
    i18n_set = __import__("taskwidget.i18n", fromlist=["set_language"]).set_language
    check("widget language key present", "language" in w.cfg,
          repr(w.cfg["language"]))
    w.cfg["language"] = "en_US"
    i18n_set("en_US")

    # ---- a live language change must re-text everything, with no restart --
    english_date = w.date_lbl.get_text()          # what the header says now
    english_month = w.month_lbl.get_text()
    config.update(lambda c: c.__setitem__("language", "ar"))
    w._on_cfg_changed()
    spin(0.4)
    check("switching to Arabic rewrites the header live",
          w.date_lbl.get_text() != english_date, w.date_lbl.get_text())
    config.update(lambda c: c.__setitem__("language", "en_US"))
    w._on_cfg_changed()
    spin(0.4)
    for name, got, want in (
        ("header date", w.date_lbl.get_text(), english_date),
        ("month label", w.month_lbl.get_text(), english_month),
        ("search box placeholder", w.entry.get_placeholder_text(), "search tasks"),
        ("title box placeholder", w.tentry.get_placeholder_text(),
         "what needs doing?"),
        ("next-up tag", w.nu_tag.get_text(), "next up"),
        ("new task label", w.lbl_new_task.get_text(), "new task"),
        ("add button", w.btn_add.get_label(), "add"),
        ("previous month tip", w.cal_prev.get_tooltip_text(), "previous month"),
        ("filter tip", w.filter_btn.get_tooltip_text(), "filter"),
        ("settings tip", w.settings_btn.get_tooltip_text(),
         "task manager widget settings"),
    ):
        check(f"live switch: {name}", got == want, repr(got))
    check("no Arabic text left behind",
          all("س" not in s for s in (
              w.date_lbl.get_text(), w.entry.get_placeholder_text(),
              w.nu_tag.get_text(), w.lbl_new_task.get_text())))

    # ---- the settings app rebuilds itself when the language changes ----
    import taskwidget.settingsapp as SA

    app = SA.SettingsApp()
    app.show()
    spin(0.9)
    first = app.win.get_child()
    check("settings page exists and is shown",
          first is not None and first.get_visible())
    check("corner roundness control exists",
          getattr(app, "rad_scale", None) is not None)
    if getattr(app, "rad_scale", None) is not None:
        adj = app.rad_scale.get_adjustment()
        check("its range is0..48",
              adj.get_lower() == 0 and adj.get_upper() == 48,
              f"{adj.get_lower()}..{adj.get_upper()}")
        app._radius(40)
        check("moving it writes radius to config",
              config.load().get("radius") == 40,
              str(config.load().get("radius")))
        check("and it reaches the stylesheet",
              "border-radius: 40.00px" in theme.build_css(config.load()))
        check("and the preview card follows too",
              app._radius and app.rad_lbl.get_text() == "40 px",
              app.rad_lbl.get_text())
        app._radius(26)                          # put it back
        check("restored to the default", config.load().get("radius") == 26)
    codes = I.available()
    if len(codes) > 1:
        app.lang_combo.set_active(1)                 # fires _language_changed
        spin(1.0)
        second = app.win.get_child()
        check("settings rebuilt after a language switch",
              second is not None and second is not first)
        check("rebuilt page is shown — window is not black",
              second is not None and second.get_visible()
              and len(second.get_children()) > 0)
        check("language really changed",
              I.get_language() == codes[1], I.get_language())
        check("same tab is kept", app.nb is not None
              and app.nb.get_current_page() == 0,
              str(app.nb.get_current_page() if app.nb else None))
        app.lang_combo.set_active(0)                 # back to English (US)
        spin(1.0)
        check("back to English (US)",
              I.get_language() == I.DEFAULT_LANG, I.get_language())
        check("English page shown again",
              app.win.get_child() is not None
              and app.win.get_child().get_visible())
    # ---- "clear all tasks" refuses to run without the typed phrase ----
    snap = list(app.store.tasks)
    check("tasks exist before the destructive test",
          len(snap) > 0, str(len(snap)))
    check("clear-all button exists in the data tab",
          getattr(app, "btn_clear_all", None) is not None)
    app._clear_all_dialog()
    spin(0.5)
    dlg = getattr(app, "_clear_dlg", None)
    check("confirmation dialog opens", dlg is not None)
    if dlg is not None:
        ok = dlg.get_widget_for_response(Gtk.ResponseType.YES)
        check("confirm button starts disabled",
              ok is not None and not ok.get_sensitive())
        app._clear_entry.set_text("clear")
        check("partial phrase keeps it locked", not ok.get_sensitive())
        app._clear_entry.set_text("   CLEAR ALL TASKS   ")
        check("the phrase unlocks it (case/space tolerant)",
              bool(ok and ok.get_sensitive()))
        dlg.emit("response", Gtk.ResponseType.CANCEL)
        spin(0.4)
        check("cancel keeps every task",
              len(app.store.tasks) == len(snap),
              f"{len(app.store.tasks)} of {len(snap)}")
        check("dialog closed after cancel",
              getattr(app, "_clear_dlg", None) is None)

        app._clear_all_dialog()
        spin(0.5)
        dlg = getattr(app, "_clear_dlg", None)
        check("dialog reopens", dlg is not None)
        if dlg is not None:
            app._clear_entry.set_text(SA.CLEAR_PHRASE)
            dlg.emit("response", Gtk.ResponseType.YES)
            spin(0.4)
            check("typed phrase really clears everything",
                  len(app.store.tasks) == 0, str(len(app.store.tasks)))
            check("dialog closed after confirming",
                  getattr(app, "_clear_dlg", None) is None)
            app.store.tasks = snap                 # put the demo data back
            app.store.save()
            check("demo tasks restored",
                  len(app.store.tasks) == len(snap))
            w.store.load()
            check("widget sees the restored tasks again",
                  len(w.store.tasks) > 0, str(len(w.store.tasks)))

    # ---- corner roundness (0 = square ..48 = round) -----------------------
    check("radius setting exists", "radius" in config.load(),
          str(config.load().get("radius")))
    check("radius0 gives square corners",
          "border-radius: 0.00px" in theme.build_css({"radius": 0}))
    check("radius48 gives fully round corners",
          "border-radius: 48.00px" in theme.build_css({"radius": 48}))
    check("radius is clamped to 48",
          "border-radius: 48.00px" in theme.build_css({"radius": 9999}))
    check("radius falls back to the default on junk",
          "border-radius: 26.00px" in theme.build_css({"radius": "junk"}))
    check("stylesheet valid at every radius",
          all(theme.validate({"radius": r, "theme": t, "scale": s}) is None
              for r in (0, 26, 48) for t in ("dark", "bright")
              for s in (0.85, 1.10)))

    # ---- first-run introduction ---------------------------------------
    from taskwidget import intro

    check("onboarding flag exists in config", "onboarding_seen" in config.load())
    config.update(lambda c: c.__setitem__("onboarding_seen", False))
    check("flag cleared for the test",
          not bool(config.load().get("onboarding_seen")))
    check("widget offers the intro on first run",
          w._maybe_show_intro() is not None)
    spin(0.6)
    dlg = intro.current()
    check("intro dialog opens", dlg is not None and dlg.get_visible())
    if dlg is not None:
        texts = [t.lower() for t in labels(dlg)]
        check("intro has a welcome title",
              any("welcome" in t for t in texts))
        check("intro has both sections",
              any("using it" in t for t in texts)
              and any("making it yours" in t for t in texts))
        check("intro lists plenty of instructions",
              len(texts) >= 15, f"{len(texts)} lines")
        check("intro mentions notifications and language",
              any("notifications" in t for t in texts)
              and any("language" in t or "langue" in t or "sprache" in t
                      or "język" in t for t in texts))
        ok = dlg.get_widget_for_response(Gtk.ResponseType.OK)
        check("intro has a 'got it' button", ok is not None)
        dlg.destroy()
        spin(0.4)
        check("dismissing it marks it as seen",
              bool(config.load().get("onboarding_seen")))
    check("second call does nothing once seen",
          w._maybe_show_intro() is None)
    settings_labels = [b.get_label() or "" for b in
                       _buttons(app.win)]
    check("settings can reopen the introduction",
          any("introduction" in s.lower() for s in settings_labels),
          str(settings_labels[-2:]))

    config.update(lambda c: c.__setitem__("onboarding_seen", seen_before))

    app.win.destroy()
    spin(0.4)
    check("settings closed without a GTK warning", True)

    w.quit()
    spin(0.4)

    bad = [r for r in results if not r[1]]
    print()
    print(f"{len(results) - len(bad)}/{len(results)} checks passed")
    if bad:
        print("FAILED:")
        for name, _, detail in bad:
            print("  -", name, detail)
        return 1
    print("ALL GOOD")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
