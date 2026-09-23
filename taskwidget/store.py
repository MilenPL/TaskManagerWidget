"""Per-user task persistence and the display rules (which task shows where)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from . import paths
from .models import (RETENTION_LONGTERM, RETENTION_TIMED, Task, today)

FILE_VERSION = 1


@dataclass
class Entry:
    task: Task
    day: dt.date
    occ: dt.datetime | None      # None for long-term tasks
    badge: str | None            # "done" | "time's up"
    retro: bool                  # listed the day after it finished
    done: bool
    is_lt: bool
    sort_t: int                  # seconds-of-day for ordering


class Store:
    def __init__(self):
        self.path = paths.tasks_path()
        self.tasks: list[Task] = []
        self.load()

    # ---------- persistence ----------

    def load(self) -> None:
        doc = paths.read_json(self.path, None)
        # Never fall back to another user's data: if the file belongs to a
        # different uid we simply start empty.
        if doc is None or not paths.owner_ok(doc):
            self.tasks = []
            return
        self.tasks = [t for t in (Task.from_dict(d) for d in doc.get("tasks", [])) if t]
        self.prune()

    def save(self) -> None:
        paths.write_json(
            self.path,
            {
                "owner_uid": paths.uid(),
                "version": FILE_VERSION,
                "tasks": [t.to_dict() for t in self.tasks],
            },
        )

    def prune(self, day: dt.date | None = None) -> bool:
        """Drop tasks that fell out of their retention window."""
        day = day or today()
        keep: list[Task] = []
        changed = False
        for t in self.tasks:
            if t.is_longterm:
                start, last, _, _ = t.longterm_span(day)
                # None => open ended, keep.  Otherwise keep while listed.
                if last is None or last >= day - dt.timedelta(days=1) or start > day:
                    keep.append(t)
                else:
                    changed = True
            else:
                last_occ = max(
                    (o.date() for o in t.occurrences(
                        day - dt.timedelta(days=400), day)),
                    default=t.when_dt().date(),
                )
                if last_occ + dt.timedelta(days=RETENTION_TIMED) >= day:
                    keep.append(t)
                else:
                    changed = True
        if changed:
            self.tasks = keep
        return changed

    # ---------- mutations ----------

    def add(self, task: Task) -> None:
        self.tasks.append(task)
        self.save()

    def remove(self, task_id: str) -> None:
        self.tasks = [t for t in self.tasks if t.id != task_id]
        self.save()

    def get(self, task_id: str) -> Task | None:
        for t in self.tasks:
            if t.id == task_id:
                return t
        return None

    def clear_finished(self) -> int:
        """Remove done / expired tasks (used by the settings app)."""
        day = today()
        keep = []
        for t in self.tasks:
            if t.is_longterm:
                _, last, badge, _ = t.longterm_span(day)
                if badge is None:
                    keep.append(t)
                elif last is None or last >= day:
                    keep.append(t)
            elif t.done:
                pass  # drop
            else:
                keep.append(t)
        n = len(self.tasks) - len(keep)
        self.tasks = keep
        if n:
            self.save()
        return n

    # ---------- queries ----------

    def day_entries(self, day: dt.date, now: dt.datetime | None = None) -> list[Entry]:
        now = now or dt.datetime.now()
        out: list[Entry] = []
        prev = day - dt.timedelta(days=1)
        for t in self.tasks:
            if t.is_longterm:
                start, last, badge, end = t.longterm_span(day)
                if day < start:
                    continue
                if last is not None and day > last:
                    continue
                shown = None
                if badge and end is not None and day >= end:
                    shown = badge
                out.append(Entry(
                    task=t, day=day, occ=None, badge=shown, retro=False,
                    done=(shown == "done"), is_lt=True, sort_t=0,
                ))
            else:
                for occ in t.occurrences(prev, day):
                    if occ.date() == day:
                        retro = False
                    elif occ.date() == prev:
                        retro = True          # shown one day after finishing
                    else:
                        continue
                    done = t.is_done_at(occ)
                    out.append(Entry(
                        task=t, day=day, occ=occ, badge=None, retro=retro,
                        done=done, is_lt=False, sort_t=occ.hour * 3600 + occ.minute * 60,
                    ))
        out.sort(key=lambda e: (0 if e.is_lt else 1, e.sort_t, e.task.title.lower()))
        return out

    def calendar_model(self, days: list[dt.date], now: dt.datetime | None = None,
                       only_undone: bool = False) -> dict:
        """Per day: dots for timed tasks + long-term underline segments.

        ``only_undone`` hides anything already finished, so the month grid can
        be filtered independently of the five-day list below it.
        """
        now = now or dt.datetime.now()
        model: dict[dt.date, dict] = {d: {"dots": [], "bars": []} for d in days}
        if not days:
            return model
        w0, w1 = days[0], days[-1]

        # timed dots
        for t in self.tasks:
            if t.is_longterm:
                continue
            for occ in t.occurrences(w0, w1):
                if only_undone and t.is_done_at(occ):
                    continue
                cell = model.get(occ.date())
                if cell is not None:
                    cell["dots"].append(t.color)

        # long-term underlines: one segment per task, lane-assigned
        lanes_end: list[dt.date | None] = []
        for t in self.tasks:
            if not t.is_longterm:
                continue
            if only_undone and t.done:
                continue
            start, last, _, end = t.longterm_span(now.date())
            if last is not None and last < w0:
                continue
            if start > w1:
                continue
            lane = 0
            while lane < len(lanes_end) and lanes_end[lane] is not None and lanes_end[lane] >= start - dt.timedelta(days=1):
                lane += 1
            if lane >= 3:
                lane = 2
            if lane >= len(lanes_end):
                lanes_end.extend([None] * (lane + 1 - len(lanes_end)))
            active_end = end if end is not None else w1
            lanes_end[lane] = max(active_end, start)
            seg_start = max(start, w0)
            seg_end = min(max(active_end, start), w1)
            if seg_start <= seg_end:
                model[seg_start]["bars"].append(dict(
                    color=t.color, lane=lane, from_cell=days.index(seg_start),
                    to_cell=days.index(seg_end), open_left=start < w0,
                    open_right=(last is None) or (active_end >= w1 and last >= w1),
                    retro=False,
                ))
            # the 2 retro days are drawn faded
            if end is not None and last is not None and last > active_end:
                r_start = max(active_end + dt.timedelta(days=1), w0)
                r_end = min(last, w1)
                if r_start <= r_end:
                    model[r_start]["bars"].append(dict(
                        color=t.color, lane=lane, from_cell=days.index(r_start),
                        to_cell=days.index(r_end), open_left=False,
                        open_right=last > w1, retro=True,
                    ))
        return model
