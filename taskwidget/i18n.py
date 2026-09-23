"""Tiny JSON i18n — English (en_US) is the source language and the default.

Design notes
------------
* **English text is the key.** ``tr("search tasks")`` needs no catalogue at
  all: with the default language it returns the key itself. Only translated
  languages ship a file, so there is no duplicated English anywhere.
* **Optimised files.** UTF-8 raw (no ``\\uXXXX`` escaping, which would roughly
  double the CJK/Arabic/Hindi files), one ``"key":"value"`` per line, no
  indentation, no trailing whitespace. Calendar names are stored as one
  comma-separated string each instead of four JSON arrays.
* **Never fails.** A deleted, unreadable or truncated file, an unknown
  language code, a missing key or a bad format placeholder all fall back to
  English silently — the UI can never show an error message.
"""

from __future__ import annotations

import datetime as dt
import json
import os

DEFAULT_LANG = "en_US"

#: code -> name shown in the settings list (first entry is the default)
LANGUAGES: dict[str, str] = {
    "en_US": "English (US)",
    "pl": "Polski · Polish",
    "es": "Español · Spanish",
    "fr": "Français · French",
    "de": "Deutsch · German",
    "it": "Italiano · Italian",
    "pt": "Português · Portuguese",
    "ru": "Русский · Russian",
    "zh": "中文 · Chinese (Simplified)",
    "ja": "日本語 · Japanese",
    "ar": "العربية · Arabic",
    "hi": "हिन्दी · Hindi",
    "ko": "한국어 · Korean",
    "tr": "Türkçe · Turkish",
    "id": "Bahasa Indonesia",
}

RTL_LANGS = {"ar"}

_EN_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                "Saturday", "Sunday"]
_EN_WEEKDAYS_S = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
_EN_MONTHS_S = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug",
                "Sep", "Oct", "Nov", "Dec"]

_lang = DEFAULT_LANG
_cat: dict[str, str] = {}
_words_cache: tuple | None = None


def _locales_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")


def catalog_path(code: str) -> str:
    return os.path.join(_locales_dir(), f"{code}.json")


def has_catalog(code: str) -> bool:
    """True when a usable file exists — used to build the settings list."""
    if code == DEFAULT_LANG:
        return True
    try:
        with open(catalog_path(code), encoding="utf-8") as fh:
            data = json.load(fh)
        return isinstance(data, dict) and bool(data)
    except (OSError, ValueError):
        return False


def set_language(code: str | None) -> str:
    """Activate a language. Returns the language actually in effect."""
    global _lang, _cat, _words_cache
    code = code if code in LANGUAGES else DEFAULT_LANG
    _lang = code
    _cat = {}
    if code != DEFAULT_LANG:
        try:
            with open(catalog_path(code), encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            pass                                   # deleted file -> English
        except (OSError, ValueError):
            pass                                   # unreadable -> English
        else:
            if isinstance(data, dict):
                _cat = {str(k): str(v) for k, v in data.items()
                        if isinstance(k, str) and isinstance(v, str) and v}
    _words_cache = None
    return _lang


def get_language() -> str:
    return _lang


def language_name(code: str | None = None) -> str:
    return LANGUAGES.get(code or _lang, LANGUAGES[DEFAULT_LANG])


def is_rtl() -> bool:
    return _lang in RTL_LANGS


#: common spellings of English weekdays that are not in the standard list
_WEEKDAY_ALIASES = {"tues": "tuesday", "thur": "thursday",
                    "thurs": "thursday", "tu": "tuesday",
                    "thu": "thursday", "sa": "saturday", "su": "sunday",
                    "mo": "monday", "we": "wednesday", "fr": "friday"}


def weekday_index(name: str) -> int:
    """0..6 for Monday..Sunday, in English *or* the active language."""
    n = (name or "").strip().lower()
    if not n:
        return -1
    n = _WEEKDAY_ALIASES.get(n, n)
    for table in (_EN_WEEKDAYS, _EN_WEEKDAYS_S, weekday_names(),
                  weekday_names(True)):
        for i, w in enumerate(table):
            if w.lower() == n:
                return i
    return -1


def available() -> list[str]:
    """Codes with a usable file, English always first."""
    return [c for c in LANGUAGES if has_catalog(c)]


def tr(key: str, **kw) -> str:
    """Translate ``key`` (the English text) and fill in ``{placeholders}``."""
    s = _cat.get(key) or key
    if kw:
        try:
            s = s.format(**kw)
        except (KeyError, IndexError, ValueError, TypeError):
            try:
                s = key.format(**kw)
            except (KeyError, IndexError, ValueError, TypeError):
                pass
    return s


# --------------------------------------------------------------- calendar ---

def _csv(key: str, english: list[str]) -> list[str]:
    raw = _cat.get(key)
    if not raw:
        return english
    parts = [p for p in raw.split(",") if p.strip()]
    if len(parts) != len(english):
        return english                              # truncated -> English
    return parts


def weekday_names(short: bool = False) -> list[str]:
    if short:
        return _csv("@wd_s", _EN_WEEKDAYS_S)
    return _csv("@wd", _EN_WEEKDAYS)


def month_names(short: bool = False, title: bool = False) -> list[str]:
    """Month names.

    ``title`` selects the standalone form (``September 2026``) for languages
    where the name changes after a day number (``22 September``) — Polish and
    Russian need both.
    """
    if short:
        return _csv("@mo_s", _EN_MONTHS_S)
    date_form = _csv("@mo", _EN_MONTHS)
    if title:
        return _csv("@mo_t", date_form)
    return date_form


def fmt(d, pattern: str = "%A %d %B") -> str:
    """``strftime`` that uses *our* language, not the machine locale.

    A catalog may override any pattern by using it as a key prefixed with
    ``@`` — Chinese, Japanese, Korean, Hindi, Arabic, Turkish and Indonesian
    put the day/month in a different order than English.
    """
    if not isinstance(d, (dt.date, dt.datetime)):
        return str(d)
    if _lang == DEFAULT_LANG:
        return d.strftime(pattern)
    pattern = _cat.get("@" + pattern) or pattern
    wd, wds = weekday_names(), weekday_names(True)
    mo = month_names(title="%d" not in pattern)
    mos = month_names(short=True)
    out = (pattern
           .replace("%A", wd[d.weekday()])
           .replace("%a", wds[d.weekday()])
           .replace("%B", mo[d.month - 1])
           .replace("%b", mos[d.month - 1]))
    return d.strftime(out)


def plural(n: int, one: str, many: str) -> str:
    """Crude but predictable pluralisation for the languages we ship."""
    if _lang in ("pl", "ru", "uk", "sr"):
        if n % 10 not in (0, 1, 2, 3, 4) or n % 100 in (12, 13, 14):
            return tr(many, n=n)
        if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            return tr(one, n=n)
        return tr(many, n=n)
    if _lang in ("ar"):
        return tr(many, n=n)
    return tr(one, n=n) if n == 1 else tr(many, n=n)


# -------------------------------------------------------- parser (nltime) ---

def parser_words() -> dict:
    """Day words the natural-language parser should understand.

    English always works; the active language's words are accepted too.
    """
    global _words_cache
    if _words_cache is not None and _words_cache[0] == _lang:
        return _words_cache[1]
    out = {
        "today": {"today", tr("today")},
        "tonight": {"tonight", tr("tonight")},
        "tomorrow": {"tomorrow", tr("tomorrow")},
        "day_after": {"day after tomorrow", tr("day after tomorrow")},
        "next": {"next", tr("next")},
        "in": {"in", tr("in")},
        "at": {"at", tr("at")},
        "weekdays": set(_EN_WEEKDAYS + _EN_WEEKDAYS_S) | set(weekday_names()) |
                    set(weekday_names(True)),
    }
    for k in list(out):
        out[k] = {w for w in out[k] if w}
    _words_cache = (_lang, out)
    return out
