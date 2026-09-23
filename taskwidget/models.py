"""Task model: timed tasks, long-term tasks, recurrence and status rules."""

from __future__ import annotations

import calendar
import datetime as dt
import uuid
from dataclasses import dataclass, field, fields

# 16 predefined colours (name, hex)
PALETTE = [
    ("Red", "#ff453a"),
    ("Orange", "#ff9f0a"),
    ("Yellow", "#ffd60a"),
    ("Lime", "#a8e05f"),
    ("Green", "#30d158"),
    ("Teal", "#00c7be"),
    ("Cyan", "#32d5e8"),
    ("Sky", "#4cc2ff"),
    ("Blue", "#0a84ff"),
    ("Indigo", "#5e5ce6"),
    ("Violet", "#9d5cff"),
    ("Purple", "#bf5af2"),
    ("Pink", "#ff6fb5"),
    ("Rose", "#ff375f"),
    ("Brown", "#a2845e"),
    ("Gray", "#8e8e93"),
]

REPEATS = ("none", "daily", "weekly", "monthly")
KINDS = ("timed", "longterm")

RETENTION_TIMED = 1      # days a timed task stays listed after its day
RETENTION_LONGTERM = 2   # days a long-term task stays listed after finishing


def now_dt() -> dt.datetime:
    return dt.datetime.now()


def today() -> dt.date:
    return dt.date.today()


def parse_dt(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        return None


def iso(d) -> str | None:
    if d is None:
        return None
    if isinstance(d, dt.datetime):
        return d.isoformat(timespec="minutes")
    return d.isoformat()


def add_interval(d: dt.datetime, rep: str) -> dt.datetime:
    if rep == "daily":
        return d + dt.timedelta(days=1)
    if rep == "weekly":
        return d + dt.timedelta(days=7)
    if rep == "monthly":
        y, m = d.year, d.month + 1
        if m > 12:
            m = 1
            y += 1
        day = min(d.day, calendar.monthrange(y, m)[1])
        return d.replace(year=y, month=m, day=day)
    return d


@dataclass
class Task:
    id: str
    title: str
    color: int = 0
    kind: str = "timed"            # timed | longterm
    when: str = ""                 # timed: first occurrence; longterm: start
    deadline: str | None = None    # longterm only, optional (23:59 of that day)
    repeat: str = "none"
    done: bool = False
    done_at: str | None = None
    completed: dict = field(default_factory=dict)   # recurring occ iso -> iso
    notified: dict = field(default_factory=dict)    # occ key -> {kind: iso}
    snoozed: dict = field(default_factory=dict)     # occ key -> iso snooze-until
    steps: list = field(default_factory=list)       # [{id, title, done}]
    created: str = ""

    # ---------- helpers ----------

    @staticmethod
    def new(title: str, color: int, kind: str, when: dt.datetime | None = None,
            deadline: dt.datetime | None = None, repeat: str = "none") -> "Task":
        return Task(
            id=uuid.uuid4().hex[:12],
            title=title,
            color=color % len(PALETTE),
            kind=kind if kind in KINDS else "timed",
            when=iso(when or now_dt()),
            deadline=iso(deadline) if deadline else None,
            repeat=repeat if (kind == "timed" and repeat in REPEATS) else "none",
            created=iso(now_dt()),
        )

    def when_dt(self) -> dt.datetime:
        return parse_dt(self.when) or now_dt()

    def deadline_dt(self) -> dt.datetime | None:
        return parse_dt(self.deadline)

    @property
    def is_longterm(self) -> bool:
        return self.kind == "longterm"

    def occ_key(self, occ: dt.datetime | None) -> str:
        if self.is_longterm:
            return "dl"
        return iso(occ) if occ else "at"

    def is_done_at(self, occ: dt.datetime | None) -> bool:
        if self.is_longterm or self.repeat == "none":
            return self.done
        return iso(occ) in self.completed

    def mark_done(self, occ: dt.datetime | None, on: bool = True) -> None:
        if self.is_longterm or self.repeat == "none":
            self.done = bool(on)
            self.done_at = iso(now_dt()) if on else None
        else:
            k = iso(occ)
            if on:
                self.completed[k] = iso(now_dt())
            else:
                self.completed.pop(k, None)

    # ---------- steps / subtasks ----------

    def add_step(self, title: str) -> None:
        title = (title or "").strip()
        if not title:
            return
        self.steps.append({"id": uuid.uuid4().hex[:8],
                           "title": title, "done": False})

    def remove_step(self, step_id: str) -> None:
        self.steps = [s for s in self.steps if s.get("id") != step_id]

    def toggle_step(self, step_id: str) -> None:
        for s in self.steps:
            if s.get("id") == step_id:
                s["done"] = not bool(s.get("done"))
                return

    def clear_steps(self) -> None:
        self.steps = []

    @property
    def step_counts(self) -> tuple[int, int]:
        total = len(self.steps)
        done = sum(1 for s in self.steps if s.get("done"))
        return done, total

    @property
    def has_steps(self) -> bool:
        return bool(self.steps)

    # ---------- status ----------

    def longterm_span(self, day: dt.date):
        """(first_day, last_listed_day|None, badge, underline_end|None)

        last_listed_day None means "keeps going" (open-ended, not finished).
        underline_end   None means the underscore reaches the window edge.
        """
        start = self.when_dt().date()
        dl = self.deadline_dt()
        if self.done:
            fin = parse_dt(self.done_at).date() if self.done_at else day
            return start, fin + dt.timedelta(days=RETENTION_LONGTERM), "done", fin
        if dl:
            if now_dt() > dl:
                return start, dl.date() + dt.timedelta(days=RETENTION_LONGTERM), "time's up", dl.date()
            return start, dl.date(), None, dl.date()
        return start, None, None, None

    def occurrences(self, w0: dt.date, w1: dt.date) -> list[dt.datetime]:
        """Timed-task occurrences whose day lies inside [w0, w1]."""
        if self.is_longterm:
            return []
        a = self.when_dt()
        if self.repeat == "none":
            return [a] if w0 <= a.date() <= w1 else []
        out: list[dt.datetime] = []
        cur = a
        guard = 0
        while cur.date() < w0 and guard < 5000:
            cur = add_interval(cur, self.repeat)
            guard += 1
        while cur.date() <= w1 and len(out) < 60:
            if cur.date() >= w0:
                out.append(cur)
            cur = add_interval(cur, self.repeat)
            guard += 1
            if guard > 5000:
                break
        return out

    # ---------- serialisation ----------

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @staticmethod
    def from_dict(d: dict) -> "Task | None":
        if not isinstance(d, dict) or not d.get("id") or not d.get("title"):
            return None
        known = {f.name for f in fields(Task)}
        clean = {k: v for k, v in d.items() if k in known}
        try:
            t = Task(**clean)
        except TypeError:
            return None
        if t.kind not in KINDS:
            t.kind = "timed"
        if t.repeat not in REPEATS:
            t.repeat = "none"
        t.color = int(t.color) % len(PALETTE)
        # steps may come from a newer/older file: normalise them
        clean_steps = []
        for s in (t.steps if isinstance(t.steps, list) else []):
            if not isinstance(s, dict):
                continue
            title = str(s.get("title") or "").strip()
            if not title:
                continue
            clean_steps.append({"id": str(s.get("id") or uuid.uuid4().hex[:8]),
                                "title": title,
                                "done": bool(s.get("done"))})
        t.steps = clean_steps
        return t
