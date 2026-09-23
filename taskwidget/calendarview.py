"""Hand-drawn month calendar: colour dots per day + long-term underscores."""

from __future__ import annotations

import calendar as _calendar
import datetime as dt

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, Gtk

from . import i18n, theme
from .gtkutil import draw_text

WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
HEADER_H = 15.0
CELL_H = 42.0
CELL_PAD = 2.0


def month_days(year: int, month: int) -> tuple[list[dt.date], int]:
    """All days shown in the month grid (whole weeks, Mon-first).

    Returns (days, rows).  Rows follow the real calendar (4..6 weeks).
    """
    cal = _calendar.Calendar(firstweekday=0)          # Monday first
    weeks = cal.monthdatescalendar(year, month)
    return [d for w in weeks for d in w], len(weeks)


class CalendarView(Gtk.DrawingArea):
    """Month grid with per-day task dots and spanning long-term bars."""

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = dict(cfg)
        self.col = theme.theme_colors(self.cfg)
        self.scale = theme.scale_of(self.cfg)
        self.today = dt.date.today()
        self.cursor = dt.date(self.today.year, self.today.month, 1)
        self.selected: dt.date | None = None
        self.days: list[dt.date] = []
        self.rows = 5
        self.model: dict = {}
        self.hover: dt.date | None = None
        self.on_day = None                              # callback(date)
        self.on_day_tasks = None                        # callback(date)
        self._marks: set[dt.date] = set()

        self.set_can_focus(False)
        self.set_hexpand(True)
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._press)
        self.connect("motion-notify-event", self._motion)
        self.connect("leave-notify-event", self._leave)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK
                        | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self._recompute()

    # ------------------------------------------------------------- state ----

    def set_config(self, cfg: dict) -> None:
        self.cfg = dict(cfg)
        self.col = theme.theme_colors(self.cfg)
        self.scale = theme.scale_of(self.cfg)
        self.queue_draw()

    def set_today(self, d: dt.date) -> None:
        self.today = d

    def set_selected(self, d: dt.date | None) -> None:
        self.selected = d
        self.queue_draw()

    def set_month(self, year: int, month: int) -> None:
        month = max(1, min(12, month))
        if month == 12:
            year, month = year + 1, 1
        elif month == 0:
            year, month = year - 1, 12
        self.cursor = dt.date(year, month, 1)
        self._recompute()

    def shift_month(self, delta: int) -> None:
        self.set_month(self.cursor.year, self.cursor.month + delta)

    def set_data(self, model: dict, days: list[dt.date], rows: int) -> None:
        self.model = model or {}
        self.days = list(days)
        self.rows = rows
        self._marks = self._compute_marks()
        self.queue_draw()

    def _compute_marks(self) -> set:
        """Days whose dot / underscore band can open the day popover."""
        marks = set()
        for d, cell in (self.model or {}).items():
            if not isinstance(cell, dict):
                continue
            if cell.get("dots"):
                marks.add(d)
        for b in self._all_bars():
            for i in range(int(b.get("from_cell", 0)),
                           int(b.get("to_cell", -1)) + 1):
                if 0 <= i < len(self.days):
                    marks.add(self.days[i])
        return marks

    def _recompute(self) -> None:
        self.days, self.rows = month_days(self.cursor.year, self.cursor.month)
        self.queue_draw()

    def title(self) -> str:
        return i18n.fmt(self.cursor, "%B %Y")

    # ------------------------------------------------------------ geometry --

    def _geom(self) -> tuple[float, float, float, float, float]:
        a = self.get_allocation()
        pad = CELL_PAD * self.scale
        gw = max(10.0, a.width - pad * 2)
        cw = gw / 7.0
        h = HEADER_H * self.scale + self.rows * CELL_H * self.scale
        return pad, HEADER_H * self.scale, cw, CELL_H * self.scale, h

    def required_height(self) -> int:
        return int(HEADER_H * self.scale + self.rows * CELL_H * self.scale)

    def _cell_hit(self, x: float, y: float) -> tuple:
        """-> (date, region) where region is 'date' or 'tasks'."""
        pad, hh, cw, ch, _ = self._geom()
        if y < hh or y >= hh + self.rows * ch:
            return None, None
        col = int((x - pad) // cw)
        row = int((y - hh) // ch)
        if col < 0 or col > 6 or row < 0 or row >= self.rows:
            return None, None
        idx = row * 7 + col
        if idx >= len(self.days):
            return None, None
        day = self.days[idx]
        local = y - (hh + row * ch)
        band = 21.0 * self.scale
        if day in self._marks and local >= band:
            return day, "tasks"
        return day, "date"

    def _cell_at(self, x: float, y: float) -> dt.date | None:
        return self._cell_hit(x, y)[0]

    # ------------------------------------------------------------ events ----

    def _press(self, _w, event) -> bool:
        day, region = self._cell_hit(event.x, event.y)
        if day is None:
            return True
        if day.month != self.cursor.month or day.year != self.cursor.year:
            self.set_month(day.year, day.month)
            return True
        if region == "tasks" and self.on_day_tasks:
            self.selected = day
            self.queue_draw()
            self.on_day_tasks(day, self._cell_rect(day))
            return True
        self.selected = day
        self.queue_draw()
        if self.on_day:
            self.on_day(day)
        return True

    def _cell_rect(self, day: dt.date):
        """Gdk.Rectangle-ish (x, y, w, h) of a day cell, widget coords."""
        from gi.repository import Gdk
        try:
            idx = self.days.index(day)
        except ValueError:
            return None
        pad, hh, cw, ch, _ = self._geom()
        r, c = divmod(idx, 7)
        rect = Gdk.Rectangle()
        rect.x, rect.y = int(pad + c * cw), int(hh + r * ch)
        rect.width, rect.height = int(cw), int(ch)
        return rect

    def _motion(self, _w, event) -> bool:
        day, region = self._cell_hit(event.x, event.y)
        if day != self.hover:
            self.hover = day
            self.queue_draw()
        win = self.get_window()
        if win is not None:
            try:
                if region == "tasks" and day in self._marks:
                    win.set_cursor(Gdk.Cursor.new_from_name(
                        self.get_display(), "pointer"))
                else:
                    win.set_cursor(None)
            except Exception:
                pass
        return False

    def _leave(self, _w, _e) -> bool:
        self.hover = None
        self.queue_draw()
        return False

    # -------------------------------------------------------------- draw ----

    def _draw(self, _w, cr) -> bool:
        c = self.col
        k = self.scale
        pad, hh, cw, ch, _ = self._geom()
        grid_w = cw * 7
        s = self.scale

        # weekday header
        for i, name in enumerate(i18n.weekday_names(True)):
            cx = pad + cw * i + cw / 2
            draw_text(cr, name, cx, hh / 2 + 0.5, 9.5 * s, c["dim"],
                      align="center", bold=True)

        for idx, day in enumerate(self.days):
            r, col = divmod(idx, 7)
            x = pad + col * cw
            y = hh + r * ch
            in_month = (day.month == self.cursor.month and day.year == self.cursor.year)
            self._cell(cr, day, x, y, cw, ch, in_month, s)

        # long-term underscores (drawn on top so they cross cell backgrounds)
        self._bars(cr, pad, hh, cw, ch, s)
        return True

    def _round_rect(self, cr, x, y, w, h, r) -> None:
        r = max(0.0, min(r, w / 2.0, h / 2.0))
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -1.5707963, 0.0)
        cr.arc(x + w - r, y + h - r, r, 0.0, 1.5707963)
        cr.arc(x + r, y + h - r, r, 1.5707963, 3.1415926)
        cr.arc(x + r, y + r, r, 3.1415926, 4.7123889)
        cr.close_path()

    def _cell(self, cr, day: dt.date, x, y, w, h, in_month, s) -> None:
        c = self.col
        cell = self.model.get(day, {}) if self.model else {}
        dots = cell.get("dots", [])
        is_today = day == self.today
        is_sel = self.selected == day
        is_hover = self.hover == day and in_month
        iw, ih = w - 3 * s, h - 3 * s
        ix, iy = x + 1.5 * s, y + 1.5 * s

        if is_today or is_hover or is_sel:
            self._round_rect(cr, ix, iy, iw, ih, 11 * s)
            cr.set_source_rgba(*theme.parse_css_color(
                c["accent_soft"] if is_today else c["surface_h"]))
            cr.fill()

        if is_sel:
            self._round_rect(cr, ix + 0.5, iy + 0.5, iw - 1, ih - 1, 11 * s)
            cr.set_source_rgba(*theme.parse_css_color(c["accent"]))
            cr.set_line_width(1.4 * s)
            cr.stroke()

        num_alpha = 1.0 if in_month else 0.32
        num_color = c["accent"] if is_today else (c["text"] if in_month else c["dim"])
        draw_text(cr, str(day.day), x + w / 2, y + 13.5 * s, 11 * s,
                  num_color, bold=is_today, align="center", alpha=num_alpha)

        # timed-task dots
        if dots:
            r = 2.7 * s
            shown = dots[:3]
            gap = 6.6 * s
            total = (len(shown) - 1) * gap
            cx0 = x + w / 2 - total / 2
            for i, ci in enumerate(shown):
                cr.arc(cx0 + i * gap, y + 24.5 * s, r, 0, 6.2831853)
                cr.set_source_rgba(*theme.hex_rgba(_palette_hex(ci)))
                cr.fill()
            if len(dots) > 3:
                draw_text(cr, f"+{len(dots) - 3}", x + w - 5 * s, y + 24.5 * s,
                          8.5 * s, c["dim"], align="right")

    # ------------------------------------------------------------- bars -----

    def _all_bars(self) -> list[dict]:
        out: list[dict] = []
        seen: set[int] = set()
        for day in self.days:
            cell = self.model.get(day) if self.model else None
            if not cell:
                continue
            for b in cell.get("bars", []):
                k = id(b)
                if k in seen:
                    continue
                seen.add(k)
                out.append(b)
        return out

    def _bars(self, cr, pad, hh, cw, ch, s) -> None:
        """Long-term tasks: a rounded underscore on every day they span."""
        bars = self._all_bars()
        if not bars:
            return
        for i in range(len(self.days)):
            covering = [b for b in bars
                        if b["from_cell"] <= i <= b["to_cell"]]
            if not covering:
                continue
            r, col = divmod(i, 7)
            left = pad + col * cw
            cell_bottom = hh + (r + 1) * ch
            for b in covering:
                first = i == b["from_cell"]
                last = i == b["to_cell"]
                x0 = left + (0 if (not first or b.get("open_left")) else 4 * s)
                x1 = left + cw - (4 * s if (last and not b.get("open_right")) else 0)
                if x1 - x0 < 3:
                    continue
                lane = int(b.get("lane", 0))
                bh = 2.4 * s
                bottom = cell_bottom - 3.0 * s - lane * 3.4 * s
                y = bottom - bh
                alpha = 0.42 if b.get("retro") else 1.0
                self._round_rect(cr, x0, y, x1 - x0, bh, bh / 2.0)
                rr, gg, bb, _a = theme.hex_rgba(_palette_hex(b["color"]))
                cr.set_source_rgba(rr, gg, bb, alpha)
                cr.fill()


def _palette_hex(i: int) -> str:
    from .models import PALETTE
    return PALETTE[int(i) % len(PALETTE)][1]
