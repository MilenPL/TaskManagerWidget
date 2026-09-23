"""Custom glass notifications: popups with sound, reminders, snooze, alarms."""

from __future__ import annotations

import datetime as dt
import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, GLib, Gtk

from . import config, gtkutil as G, paths
from .i18n import tr
from .models import Task, iso, parse_dt

SOUNDS_DIR = config.SOUNDS

BUNDLED_SOUNDS = [
    ("Message", f"{SOUNDS_DIR}/message-new-instant.oga"),
    ("Complete", f"{SOUNDS_DIR}/complete.oga"),
    ("Alarm", f"{SOUNDS_DIR}/alarm-clock-elapsed.oga"),
    ("Bell", f"{SOUNDS_DIR}/bell.oga"),
    ("Bark", f"{SOUNDS_DIR}/bark.oga"),
    ("Drip", f"{SOUNDS_DIR}/drip.oga"),
    ("Glass", f"{SOUNDS_DIR}/glass.oga"),
    ("Sonar", f"{SOUNDS_DIR}/sonar.oga"),
]

MAX_POPUPS = 4
MAX_FLUSH = 3


# --------------------------------------------------------- do-not-disturb ---

def hm(value, default=(0, 0)) -> tuple[int, int]:
    """Parse ``HH:MM`` (lenient) into (hour, minute)."""
    if isinstance(value, (tuple, list)) and len(value) == 2:
        try:
            return max(0, min(23, int(value[0]))), max(0, min(59, int(value[1])))
        except (TypeError, ValueError):
            return default
    try:
        text = str(value or "").strip()
        if ":" not in text:
            return default
        h, m = text.split(":", 1)
        return max(0, min(23, int(h))), max(0, min(59, int(m)))
    except (TypeError, ValueError):
        return default


def dnd_active(cfg: dict, now: dt.datetime | None = None) -> bool:
    """True inside the quiet window (handles windows that cross midnight)."""
    f = (cfg or {}).get("features") or {}
    if not f.get("dnd"):
        return False
    now = now or dt.datetime.now()
    start = hm(f.get("dnd_from", "22:00"))
    end = hm(f.get("dnd_to", "07:00"))
    if start == end:
        return False
    minute = now.hour * 60 + now.minute
    s, e = start[0] * 60 + start[1], end[0] * 60 + end[1]
    if s < e:
        return s <= minute < e
    return minute >= s or minute < e


def dnd_minutes_left(cfg: dict, now: dt.datetime | None = None) -> int:
    """Minutes until the quiet window ends (0 when it is not running)."""
    if not dnd_active(cfg, now):
        return 0
    now = now or dt.datetime.now()
    end = hm((cfg.get("features") or {}).get("dnd_to", "07:00"))
    target = now.replace(hour=end[0], minute=end[1], second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return max(1, int((target - now).total_seconds() // 60))


# ------------------------------------------------------------------ sound ----

def play(path: str | None, volume: float = 0.7) -> bool:
    if not path or not os.path.exists(path):
        return False
    v = int(max(0.0, min(1.0, float(volume))) * 65536)
    try:
        subprocess.Popen(
            ["paplay", "--volume", str(v), path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except OSError:
        return False


# ----------------------------------------------------------------- popup -----


class Popup(Gtk.Window):
    """A small rounded-glass alert that stacks at the top of the screen."""

    open_popups: list["Popup"] = []

    def __init__(self, kind: str, title: str, sub: str, color: int,
                 on_done=None, on_snooze=None, snooze_label: str = "snooze",
                 timeout: int = 8, repeat_sound=None):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.kind = kind
        self._repeat_sound = repeat_sound
        self._repeat_src = None
        self._close_src = None

        self.set_title(tr("task reminder"))
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_accept_focus(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
        try:
            self.stick()
        except Exception:
            pass
        G.glass_visual(self)
        self.get_style_context().add_class("tw")

        root = G.vbox(8)
        root.get_style_context().add_class("pop")

        head = G.hbox(8)
        head.pack_start(G.dot(color, 11), False, False, 0)
        txt = G.vbox(1)
        txt.pack_start(G.label(title, "ptitle"), False, False, 0)
        txt.pack_start(G.label(sub, "psub"), False, False, 0)
        head.pack_start(txt, True, True, 0)
        close = G.icon_button("window-close-symbolic", "iconbtn", tr("dismiss"))
        close.connect("clicked", lambda _w: self.destroy())
        head.pack_end(close, False, False, 0)
        root.pack_start(head, False, False, 0)

        btns = G.hbox(6)
        if on_done:
            b = G.button(tr("done"), "btn suggested")
            b.connect("clicked", lambda _w: (on_done(), self.destroy()))
            btns.pack_start(b, True, True, 0)
        if on_snooze:
            b = G.button(snooze_label, "btn")
            b.connect("clicked", lambda _w: (on_snooze(), self.destroy()))
            btns.pack_start(b, True, True, 0)
        root.pack_start(btns, False, False, 0)

        root.show_all()
        self.add(root)
        self.set_size_request(300, -1)
        self.connect("destroy", self._on_destroy)

        Popup.open_popups.append(self)
        self._reposition()
        self.show_all()

        if timeout and timeout > 0:
            self._close_src = GLib.timeout_add_seconds(int(timeout), self._auto_close)
        if repeat_sound:
            self._repeat_src = GLib.timeout_add_seconds(12, self._repeat)

    # --------------------------------------------------------------- guts ---

    def _repeat(self) -> bool:
        if self._repeat_sound:
            self._repeat_sound()
        return True

    def _auto_close(self) -> bool:
        self._close_src = None
        self.destroy()
        return False

    def _on_destroy(self, *_a) -> None:
        if self in Popup.open_popups:
            Popup.open_popups.remove(self)
        for src in (self._close_src, self._repeat_src):
            if src:
                try:
                    GLib.source_remove(src)
                except Exception:
                    pass
        self._close_src = self._repeat_src = None
        Popup.reposition_all()

    @staticmethod
    def reposition_all() -> None:
        for p in list(Popup.open_popups):
            p._reposition()

    def _reposition(self) -> None:
        x, y, w, h = G.workarea()
        pw = self.get_allocated_width() or 300
        ph = self.get_allocated_height() or 90
        right = x + w - pw - 18
        top = y + 16
        idx = Popup.open_popups.index(self) if self in Popup.open_popups else 0
        top += idx * (ph + 10)
        self.move(max(x + 8, right), top)

    @staticmethod
    def close_all() -> None:
        for p in list(Popup.open_popups):
            try:
                p.destroy()
            except Exception:
                pass


# -------------------------------------------------------------- notifier -----

class Notifier:
    """Watches the store and raises popups / sounds at the right moments."""

    def __init__(self, store, get_cfg):
        self.store = store
        self.get_cfg = get_cfg
        self._last_day = dt.date.today()

    # -- helpers ------------------------------------------------------------

    def _sound_for(self, kind: str, n: dict) -> str | None:
        if kind == "remind":
            return n.get("sound_remind")
        if kind == "deadline":
            return n.get("sound_alarm")
        return n.get("sound_due")

    def _text_for(self, task: Task, kind: str, occ, n: dict) -> tuple[str, str]:
        if kind == "remind":
            mins = int(n.get("remind_min", 10))
            clock = occ.strftime("%H:%M") if occ else ""
            return (tr("coming up"),
                    tr("in {n} min · {t}", n=mins, t=clock))
        if kind == "deadline":
            return tr("time's up"), tr("the deadline has passed")
        if kind == "snoozed" and task.is_longterm:
            return tr("time's up"), tr("snoozed reminder")
        return tr("due now"), (occ.strftime("%H:%M") if occ else "")

    def _actions(self, task: Task, key: str, kind: str, occ):
        n = self.get_cfg().get("notifications", {})
        snooze_min = int(n.get("snooze_min", 10) or 10)

        def on_done():
            task.mark_done(occ if not task.is_longterm else None, True)
            self.store.save()
            Popup.close_all()

        def on_snooze():
            task.snoozed[key] = iso(dt.datetime.now() + dt.timedelta(minutes=snooze_min))
            task.notified.setdefault(key, {})["last"] = kind
            self.store.save()

        return on_done, on_snooze, tr("snooze {n}m", n=snooze_min)

    def _fire(self, task: Task, key: str, kind: str, occ, cfg: dict) -> None:
        n = cfg.get("notifications", {})
        task.notified.setdefault(key, {})
        task.notified[key][kind] = iso(dt.datetime.now())
        task.notified[key]["last"] = kind
        self.store.save()

        if dnd_active(cfg):
            # inside the quiet window: hold it back and show it later
            self._enqueue(task, key, kind, occ)
            return
        self._show(task, key, kind, occ, cfg, sound=True)

    # -- do-not-disturb queue -------------------------------------------

    @staticmethod
    def _queue_read() -> list:
        doc = paths.read_json(paths.queue_path(), None)
        if not isinstance(doc, dict) or not paths.owner_ok(doc):
            return []
        items = doc.get("items")
        if not isinstance(items, list):
            return []
        return [e for e in items if isinstance(e, dict) and e.get("task_id")]

    @staticmethod
    def _queue_write(entries: list) -> None:
        try:
            paths.write_json(paths.queue_path(),
                             {"owner_uid": paths.uid(), "items": entries})
        except OSError:
            pass

    @classmethod
    def queue_size(cls) -> int:
        doc = paths.read_json(paths.queue_path(), None)
        items = doc.get("items") if isinstance(doc, dict) else None
        return len(items) if isinstance(items, list) else 0

    def _enqueue(self, task: Task, key: str, kind: str, occ) -> None:
        items = self._queue_read()
        items = [e for e in items
                 if not (e.get("task_id") == task.id and e.get("key") == key)]
        items.append({"task_id": task.id, "key": key, "kind": kind,
                      "occ": iso(occ) if occ else None,
                      "at": iso(dt.datetime.now())})
        self._queue_write(items[-24:])

    def flush(self, cfg: dict) -> int:
        """Show whatever the quiet window held back.  Returns how many."""
        doc = paths.read_json(paths.queue_path(), None)
        items = doc.get("items") if isinstance(doc, dict) else None
        if not isinstance(items, list) or not items:
            return 0
        self._queue_write([])
        shown = 0
        for i, entry in enumerate(items[:MAX_FLUSH]):
            task = self.store.get(entry.get("task_id"))
            if task is None:
                continue
            key = entry.get("key") or "at"
            kind = entry.get("kind") or "due"
            occ = parse_dt(entry.get("occ"))
            sound = bool(shown == 0)
            delay = i * 700
            GLib.timeout_add(delay, self._show_later,
                             task, key, kind, occ, cfg, sound)
            shown += 1
        return shown

    def _show_later(self, task, key, kind, occ, cfg, sound) -> bool:
        self._show(task, key, kind, occ, cfg, sound=sound)
        return False

    def _show(self, task: Task, key: str, kind: str, occ, cfg: dict,
              sound: bool = True) -> None:
        n = cfg.get("notifications", {})

        if sound and n.get("sounds", True):
            if n.get("alarm_repeat") and kind in ("due", "deadline"):
                snd = self._sound_for(kind, n)
                vol = n.get("volume", 0.7)
                rep = lambda s=snd, v=vol: play(s, v)      # noqa: E731
            else:
                rep = None
            play(self._sound_for(kind, n), n.get("volume", 0.7))
        else:
            rep = None

        if not n.get("popups", True):
            return

        head, sub = self._text_for(task, kind, occ, n)
        on_done, on_snooze, snooze_lbl = self._actions(task, key, kind, occ)
        if occ and not task.is_longterm and kind == "due":
            sub = tr("{h} · {t}", h=head, t=occ.strftime("%H:%M"))

        Popup(
            kind=kind, title=task.title, sub=sub, color=task.color,
            on_done=on_done, on_snooze=on_snooze, snooze_label=snooze_lbl,
            timeout=int(n.get("popup_timeout", 8) or 0),
            repeat_sound=rep,
        )
        while len(Popup.open_popups) > MAX_POPUPS:
            old = Popup.open_popups[0]
            try:
                old.destroy()
            except Exception:
                pass

    # -- main scan ----------------------------------------------------------

    def tick(self) -> None:
        cfg = self.get_cfg()
        n = cfg.get("notifications", {})
        if not n.get("enabled", True):
            Popup.close_all()
            return
        now = dt.datetime.now()
        day = now.date()

        if not dnd_active(cfg, now):
            try:
                self.flush(cfg)
            except Exception as exc:
                print(f"flush error: {exc}")

        for t in list(self.store.tasks):
            if t.is_longterm:
                self._scan_longterm(t, now, n, cfg)
            else:
                self._scan_timed(t, now, day, n, cfg)

    def _scan_longterm(self, t, now, n, cfg) -> None:
        if not n.get("deadline", True):
            return
        dl = t.deadline_dt()
        if dl is None or t.done:
            return
        key = "dl"
        sn = t.snoozed.get(key)
        if sn:
            until = parse_dt(sn)
            if until is None or now < until:
                return
            t.snoozed.pop(key, None)
            kind = t.notified.get(key, {}).get("last", "deadline")
            self._fire(t, key, kind, None, cfg)
            return
        if now < dl or now > dl + dt.timedelta(minutes=10):
            return
        if t.notified.get(key, {}).get("deadline"):
            return
        self._fire(t, key, "deadline", None, cfg)

    def _scan_timed(self, t, now, day, n, cfg) -> None:
        w0 = day - dt.timedelta(days=1)
        w1 = day + dt.timedelta(days=45)
        for occ in t.occurrences(w0, w1):
            if t.is_done_at(occ):
                continue
            key = iso(occ)

            sn = t.snoozed.get(key)
            if sn:
                until = parse_dt(sn)
                if until is None or now < until:
                    continue
                t.snoozed.pop(key, None)
                kind = t.notified.get(key, {}).get("last", "due")
                self._fire(t, key, kind, occ, cfg)
                continue

            noted = t.notified.get(key, {})

            remind_min = int(n.get("remind_min", 0) or 0)
            if remind_min > 0:
                rt = occ - dt.timedelta(minutes=remind_min)
                if rt <= now < occ - dt.timedelta(seconds=25):
                    if not noted.get("remind"):
                        self._fire(t, key, "remind", occ, cfg)
                        continue

            if n.get("at_time", True):
                if occ <= now < occ + dt.timedelta(minutes=10):
                    if not noted.get("due"):
                        self._fire(t, key, "due", occ, cfg)
                        continue
