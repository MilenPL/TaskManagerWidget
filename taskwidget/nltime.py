"""Lightweight natural-language date/time parsing for the task title field.

Understood phrases (case-insensitive, in English **or** the active UI
language)::

    in 20 min | in 2 hours | in 3 days
    today | tonight | tomorrow | day after tomorrow
    friday | next friday | mon..sun
    at 5pm | 5:30 pm | 14:30 | at 14:30

The matched words are removed from the title, so *dentist tomorrow at 14:30*
becomes a task called *dentist*.

Word boundaries are only applied to ASCII words: scripts without spaces
(Chinese, Japanese, Hindi, Arabic …) must be matchable inside a sentence, so
non-ASCII terms are matched plainly.
"""

from __future__ import annotations

import datetime as dt
import re

from . import i18n

_PAT: dict = {}
_PAT_LANG = ""


def _term(word: str) -> str:
    """A matchable alternative: bounded for ASCII, plain otherwise."""
    e = re.escape(word)
    return rf"\b{e}\b" if word.isascii() else e


def _alt(words) -> str:
    items = sorted({str(w) for w in words if w}, key=len, reverse=True)
    return "|".join(_term(w) for w in items) or r"(?!)x"


def _group(words) -> str:
    items = sorted({str(w) for w in words if w}, key=len, reverse=True)
    return "|".join(_term(w) for w in items) or r"(?!)x"


def patterns() -> dict:
    """Compiled matchers for the active language (cached)."""
    global _PAT, _PAT_LANG
    lang = i18n.get_language()
    if _PAT and _PAT_LANG == lang:
        return _PAT

    w = i18n.parser_words()
    at_words = set(w["at"]) | {"at"}
    at_alt = "|".join(sorted((re.escape(x) for x in at_words),
                             key=len, reverse=True))
    rel = re.compile(
        rf"\b(?:{_alt(w['in'] | {'in'})})\s*(\d{{1,3}})\s*"
        r"(minutes?|mins?|hours?|hrs?|days?)\b", re.I)

    day_map: dict[str, int] = {}
    for word in w["day_after"]:
        day_map[word.lower()] = 2
    for word in w["tomorrow"]:
        day_map[word.lower()] = 1
    for word in w["tonight"] | w["today"]:
        day_map[word.lower()] = 0
    dayword = re.compile(
        rf"({_group(w['day_after'] | w['tomorrow'] | w['tonight'] |
                    w['today'])})", re.I)

    nextwd = re.compile(
        rf"\b(?:{_alt(w['next'] | {'next'})})\s*({_group(w['weekdays'])})",
        re.I)
    wd = re.compile(rf"({_group(w['weekdays'])})", re.I)
    ampm = re.compile(
        rf"\b(?:{at_alt}\s*)?(\d{{1,2}})(?::(\d{{2}}))?\s*(am|pm)\b", re.I)
    clock = re.compile(
        rf"\b(?:{at_alt}\s*)?(\d{{1,2}}):([0-5]\d)\b", re.I)

    # only strip a leading word that is long enough (or a classic English
    # one) so short localised words never eat a real title
    lead = {x for x in (at_words | {"on", "by", "@"})
            if len(x) >= 3 or x in ("at", "on", "by", "@")}
    lead_pat = "|".join(sorted((re.escape(x) for x in lead),
                               key=len, reverse=True))
    strip = re.compile(rf"^(?:{lead_pat})\s+", re.I)

    _PAT = dict(rel=rel, dayword=dayword, day_map=day_map, nextwd=nextwd,
                wd=wd, ampm=ampm, clock=clock, strip=strip)
    _PAT_LANG = lang
    return _PAT


class Parsed:
    __slots__ = ("title", "date", "time", "tokens")

    def __init__(self, title, date, time, tokens):
        self.title = title
        self.date = date            # dt.date | None
        self.time = time            # (h, m) | None
        self.tokens = tokens        # matched words, for the live hint

    @property
    def found(self) -> bool:
        return bool(self.tokens)

    def __repr__(self) -> str:      # pragma: no cover - debugging aid
        return f"Parsed({self.title!r}, {self.date}, {self.time}, {self.tokens})"


def _free(span, taken) -> bool:
    a, b = span
    for s, e in taken:
        if a < e and s < b:
            return False
    return True


def parse(text: str, base: dt.date | None = None,
          now: dt.datetime | None = None) -> Parsed:
    """Split ``text`` into a clean title plus an optional date and time."""
    p = patterns()
    base = base or dt.date.today()
    start = now or dt.datetime.now()
    src = text or ""
    taken: list[tuple[int, int]] = []
    tokens: list[str] = []
    date: dt.date | None = None
    time: tuple[int, int] | None = None

    def claim(m) -> bool:
        if m and _free(m.span(), taken):
            taken.append(m.span())
            tokens.append(m.group(0))
            return True
        return False

    # ---- relative --------------------------------------------------------
    m = p["rel"].search(src)
    if claim(m):
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("d"):
            date = start.date() + dt.timedelta(days=n)
        else:
            minutes = n * (60 if unit.startswith("h") else 1)
            when = start + dt.timedelta(minutes=minutes)
            date, time = when.date(), (when.hour, when.minute)

    # ---- explicit day words ---------------------------------------------
    m = p["dayword"].search(src)
    if claim(m):
        offset = p["day_map"].get(m.group(0).lower(), 0)
        date = start.date() + dt.timedelta(days=offset)
        if offset == 0 and time is None and \
                m.group(0).lower() in {w.lower() for w in
                                       i18n.parser_words()["tonight"]}:
            time = (20, 0)

    # ---- next <weekday> ---------------------------------------------------
    m = p["nextwd"].search(src)
    if claim(m):
        idx = i18n.weekday_index(m.group(1))
        if idx >= 0:
            ahead = (idx - start.weekday()) % 7
            date = start.date() + dt.timedelta(days=ahead + 7)

    # ---- plain weekday ----------------------------------------------------
    m = p["wd"].search(src)
    if date is None and claim(m):
        idx = i18n.weekday_index(m.group(1))
        if idx >= 0:
            ahead = (idx - start.weekday()) % 7
            date = start.date() + dt.timedelta(days=ahead)

    # ---- clock times ------------------------------------------------------
    m = p["ampm"].search(src)
    if claim(m):
        h = int(m.group(1)) % 12
        if m.group(3).lower() == "pm":
            h += 12
        time = (h, int(m.group(2) or 0))
    else:
        m = p["clock"].search(src)
        if claim(m):
            h = int(m.group(1))
            if 0 <= h <= 23:
                time = (h, int(m.group(2)))

    if not tokens:
        return Parsed(src.strip(), None, None, [])

    # ---- strip the matched spans (right to left) --------------------------
    out = src
    for a, b in sorted(taken, reverse=True):
        out = out[:a] + " " + out[b:]
    out = re.sub(r"\s+", " ", out).strip()
    out = p["strip"].sub("", out).strip()
    out = re.sub(r"\s+[,;:]+$", "", out).strip()
    if not out:
        out = src.strip()          # never swallow the whole title
    return Parsed(out, date, time, tokens)


def quick(text: str) -> str:
    """Short human hint for the parsed date/time, or '' if nothing matched."""
    return hint_for(parse(text))


def hint_for(p: Parsed) -> str:
    from . import i18n as _i18n
    from .i18n import tr
    if not p.found:
        return ""
    bits = []
    if p.date:
        today = dt.date.today()
        if p.date == today:
            bits.append(tr("today"))
        elif p.date == today + dt.timedelta(days=1):
            bits.append(tr("tomorrow"))
        elif p.date == today - dt.timedelta(days=1):
            bits.append(tr("yesterday"))
        else:
            bits.append(_i18n.fmt(p.date, "%a %d %b"))
    if p.time:
        bits.append(f"{p.time[0]:02d}:{p.time[1]:02d}")
    return " → " + " ".join(bits)
