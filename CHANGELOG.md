# Changelog

## v2.29-gnome — 2026-09-23

First release, built for the **GNOME desktop environment**.

First public release. Built for, and tested on, the **GNOME desktop
environment** (Wayland through XWayland, or X11).

### Added
- **A first-run introduction.** The first time the widget starts it opens a
  modal tour — *using it* (8 tips: calendar dots, step rings, search,
  creating a task, natural-language times, the next-up strip, keyboard
  shortcuts, why it hides from alt-tab) and *making it yours* (glass,
  position, features, notifications, language/title/backup). **got it**
  dismisses it and it never returns on its own; **open settings** jumps
  straight to the settings app. It is localised in all15 languages and can
  be reopened any time from *show the introduction again* in the settings
  footer. Guarded by a new `onboarding_seen` config flag.
- **`clear all tasks` in *settings → data & startup*** — a destructive button
  that opens a modal dialog which stays locked until you literally type
  `clear all tasks` (case- and space-insensitive). It shows how many tasks
  will go, offers **cancel**, and only then wipes them; the widget empties
  within a second. The button is greyed out when there is nothing to clear.
  The confirmation phrase is deliberately never translated — it is a safety
  token, not UI copy — while the surrounding dialog is fully localised.

### Fixed
- **The widget opened in the middle of the screen after a login.** The
  placement was only ever corrected when it landed *outside* the workarea —
  a window the window manager had just centred is still inside it, so the
  wrong place stuck. `_settle()` now compares against the position the widget
  itself asked for (never a possibly-stale server read), re-applies it and
  retries a few times; `apply_preset()` also schedules that check. Every
  change (preset, fold, drag, correction) still writes `state.json`, so the
  next login restores the last place you left it.
- **Changing the language did not refresh the widget.** Only the strings
  built by `refresh()` were re-translated, so the header date changed but the
  search box, the task-title box, the `next up` tag, the *new task* label,
  the add button and every tooltip kept the old language until a restart. A
  new `_retext()` pushes the current language through every widget that is
  created only once, and runs after every config reload — switching language
  now takes effect immediately, no restart.
- Icon-button and button **tooltips** were never passed through the
  translator at all (the wrapper did not know about those helpers); the
  wrapper now covers them, and the 15 newly reachable strings are in every
  catalogue.
- **The settings window went black when switching language.** The content was
  rebuilt but never `show()`n — only the very first build was made visible by
  `show()`, so a language switch produced an empty toplevel. The rebuilt tree
  is now shown explicitly, and the rebuild happens on the next idle pass
  because the combo was destroying itself inside its own `changed` emission,
  which segfaulted GTK.
- The tree is attached to the window *before* it is filled, matching what
  GTK expects; attaching it afterwards left a hierarchy that crashed in
  `gtk_widget_show_all()`.
- The settings poll timer is now removed on close, and quitting only stops a
  main loop that actually exists.

### Added
- **15 languages, English (US) by default** — a *language* selector at the top
  of *settings → appearance* switches instantly: the settings window rebuilds
  itself and the widget follows within a second.
  `en_US` (default), `pl`, `es`, `fr`, `de`, `it`, `pt`, `ru`, `zh`, `ja`,
  `ar`, `hi`, `ko`, `tr`, `id`.
  - catalogues live in `taskwidget/locales/*.json`, UTF-8, one line per entry,
    no indentation and no duplicated English (the English text *is* the key),
    so a whole language is ~6 KB;
  - month/weekday names and date order are localised too — Chinese, Japanese,
    Korean, Hindi, Arabic, Turkish and Indonesian reorder the date via an
    `@pattern` override, Russian and Polish get both month forms;
  - the natural-language parser understands the active language's words
    (`dentysta jutro o14:30`, `歯医者 明日14:30`, …) while English always works;
  - **a deleted, truncated or corrupt file never surfaces an error**: the
    language drops out of the list and everything falls back to English.
- **Side padding and word-wrap in the settings app** — prose no longer runs
  into the edge of the window or the tab block.
- **Four independent day filters**, so the month calendar and the five-day
  (weekly) view can differ:
  - *five-day view: show yesterday* (on) — drop the previous day's group
  - *month calendar: only not-done tasks* (off) — dots/bars of undone tasks
  - *five-day view: only not-done tasks* (off) — hides finished tasks from
    every day group
  - *today: only not-done tasks* (off) — today's group and the
    `today · times` panel only
- **Custom widget title** — the word at the top of the card is an editable
  field in *settings → appearance*, applied as you type (empty falls back to
  `tasks`).

## 0.2.0 — 2026-09-22

### Added
- **Fold to the side** — a small header button (and `Ctrl+F`) collapses the
  widget into a slim 48 px glass rail showing only an unfold arrow. The edge
  the card already hugged is preserved and the state survives a restart.
- **Calendar day popover (#3)** — click a day's dots to open that day and
  tick its tasks off without leaving the calendar.
- **Steps and progress rings (#4)** — click a task's colour dot to add
  subtasks; the dot turns into a progress ring and the row shows `2/4`.
- **Next-up strip (#5)** — a slim line under the header with the next task
  and a live countdown (`in 12 min` / `now` / `overdue 30 min`).
- **Do not disturb (#6)** — a quiet window (default `22:00 → 07:00`,
  overnight-safe) that queues pop-ups and sounds and shows them when it ends.
- **Keyboard shortcuts (#9)** — `Ctrl+N`, `/`, `Ctrl+F`, `Enter`, `Delete`,
  `Esc`; rows are focusable and highlight on focus.
- **Natural-language times (#10)** — `dentist tomorrow at 14:30` becomes a
  title plus a date and time, with a live hint while typing.
- A **features** tab in the settings app: one switch per item above, plus the
  quiet-window times and a counter of queued alerts.
- Console entry points (`task-widget`, `task-widget-settings`),
  `pyproject.toml`, tests, icon, MIT licence.

### Fixed
- `!important`, `background:` shorthands and `font-feature-settings` are not
  valid GTK 3 CSS — the stylesheet is now entirely inside the dialect.
- Every cairo string was painted at the layout origin
  (`PangoCairo.show_layout()` takes no x/y).
- `set_no_show_all()` makes `show_all()` skip the whole subtree, so the drag
  curtain label never appeared.
- `Gtk.Entry` has no `set_xalign()`; the settings app crashed building the
  features tab.
- Popovers were shown with `show()` before `popup()` and could exceed the
  screen; they are now constrained to the screen and the day list scrolls.
- Unfolding never re-showed the card.
- A position read right after a resize could be `(0, 0)`; clamping it wrote a
  bogus saved position. Untrusted reads are now ignored.

## 0.1.0 — 2026-09-22

Initial version: liquid-glass widget with month calendar (colour dots and
spanning long-term bars), five-day window, today-with-times, create-task form
with 16 colours, search and colour filter, glass notifications with snooze,
nine position presets, drag mode gated by the settings app, per-user storage,
autostart and launchers.
