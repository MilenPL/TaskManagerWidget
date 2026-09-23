#!/bin/bash
#
# Regenerates everything in docs/screenshots/ for the README.
#   ./tools/make-screenshots.sh
#
# It forces English for the duration (the README is English) and puts your
# language, intro flag and settings back afterwards.
#
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
OUT="$ROOT/docs/screenshots"
TMP="$(mktemp -d /tmp/tw-shots.XXXXXX)"
mkdir -p "$OUT"
WALL="$ROOT/tools/wallpaper.png"

kill_all () {
  pkill -f 'task-widget$' 2>/dev/null
  pkill -f 'bin/task-widget-settings' 2>/dev/null
  sleep 1
  pkill -9 -f 'task-widget$' 2>/dev/null
  pkill -9 -f 'bin/task-widget-settings' 2>/dev/null
  sleep 0.6
}
widget_id () { xwininfo -root -tree 2>/dev/null | grep -i '"task manager widget"' | head -1 | awk '{print $1}'; }
settings_id () { xwininfo -root -tree 2>/dev/null | grep -i 'task manager widget settings' | head -1 | awk '{print $1}'; }
grab () { [ -n "${1:-}" ] || { echo "  ! no window for $2"; return 1; }
          import -window "$1" "$2" 2>/dev/null && echo "  $(basename "$2")"; }
py () { python3 -c "$1"; }

# ---- remember the user's own settings so we can put them back -------------
ORIG_LANG=$(py "import sys; sys.path.insert(0,'.'); from taskwidget import config; print(config.load().get('language','en_US'))")
ORIG_SEEN=$(py "import sys; sys.path.insert(0,'.'); from taskwidget import config; print(config.load().get('onboarding_seen'))")
echo "your language/intro flag: $ORIG_LANG / $ORIG_SEEN (restored at the end)"

kill_all
py "
import sys; sys.path.insert(0, '.')
from taskwidget import config
config.update(lambda c: (c.__setitem__('language', 'en_US'),
                         c.__setitem__('opacity', 0.72)))"

[ -s "$WALL" ] || magick -size 800x1300 gradient:'#1d2745'-'#07080f' \
    -fill '#2f6fed' -draw 'circle 650,220 650,500' \
    -fill '#9d5cff' -draw 'circle 120,980 120,1230' \
    -fill '#00c7be' -draw 'circle 720,1130 720,1290' \
    -blur 0x60 -resize 1200x2000! -depth 8 -strip "$WALL" 2>/dev/null

# ---- demo data: the long-term task (with steps) comes first ---------------
py "
import sys, datetime as dt
sys.path.insert(0, '.')
from taskwidget import store as store_mod
from taskwidget.models import Task
s = store_mod.Store()
s.tasks = [t for t in s.tasks if 'ALARM TEST' not in t.title]
day = dt.date.today()
order = ['write the quarterly report']
s.tasks.sort(key=lambda t: order.index(t.title) if t.title in order else 1)
rep = next((t for t in s.tasks if t.title == 'write the quarterly report'), None)
if rep is not None:
    if len(rep.steps) != 4:
        rep.clear_steps()
        for st in ('gather the numbers', 'draft each section',
                   'review with the team', 'send it out'):
            rep.add_step(st)
    for i, st in enumerate(rep.steps):
        st['done'] = i < 2
s.save()"

# ---- widget (dark / bright / folded) -------------------------------------
start_widget () {   # $1 = TASKWIDGET_DEBUG_POPOVER
  kill_all
  TASKWIDGET_DEBUG_POPOVER="${1:-}" python3 -u bin/task-widget >"$TMP/w-$2.log" 2>&1 &
  sleep "${3:-7}"
}
start_widget "" dark 7
grab "$(widget_id)" "$TMP/widget-dark.png"
py "import sys; sys.path.insert(0,'.')
from taskwidget import config
config.update(lambda c: c.__setitem__('theme','bright'))"
sleep 3; grab "$(widget_id)" "$TMP/widget-bright.png"
py "import sys; sys.path.insert(0,'.')
from taskwidget import config
config.update(lambda c: c.__setitem__('theme','dark'))"
sleep 3
py "import sys, time; sys.path.insert(0,'.')
from taskwidget import ipc; ipc.send({'fold': True})"
sleep 3; grab "$(widget_id)" "$TMP/folded.png"
py "import sys; sys.path.insert(0,'.')
from taskwidget import ipc; ipc.send({'fold': False})"
sleep 2

# ---- popovers -------------------------------------------------------------
start_widget day day 9
grab "$(grep -o 'POPOVER_XID day [0-9]*' "$TMP/w-day.log" | awk '{print $3}')" "$TMP/day-popover.png"

start_widget steps steps 9
grab "$(grep -o 'POPOVER_XID steps [0-9]*' "$TMP/w-steps.log" | awk '{print $3}')" "$TMP/steps-popover.png"

start_widget drag drag 7
grab "$(widget_id)" "$TMP/drag-mode.png"

# ---- notification popup ---------------------------------------------------
start_widget "" notif 5
py "
import sys, datetime as dt
sys.path.insert(0, '.')
from taskwidget import store as store_mod, config
from taskwidget.models import Task
config.update(lambda c: c['notifications'].__setitem__('sounds', False))
s = store_mod.Store()
s.tasks = [t for t in s.tasks if 'ALARM TEST' not in t.title]
s.tasks.append(Task.new('send the report', 0, 'timed',
                        when=dt.datetime.now() - dt.timedelta(seconds=30)))
s.save()"
sleep 6
grab "$(xwininfo -root -tree 2>/dev/null | grep -i '"task reminder"' | head -1 | awk '{print $1}')" "$TMP/notification.png"
kill_all
py "
import sys; sys.path.insert(0, '.')
from taskwidget import store as store_mod, config
config.update(lambda c: c['notifications'].__setitem__('sounds', True))
s = store_mod.Store()
s.tasks = [t for t in s.tasks if 'ALARM TEST' not in t.title and t.title != 'send the report']
s.save()"

# ---- first-run introduction ----------------------------------------------
echo "== intro"
py "import sys; sys.path.insert(0,'.')
from taskwidget import config
config.update(lambda c: c.__setitem__('onboarding_seen', False))"
setsid nohup python3 -u bin/task-widget >"$TMP/intro.log" 2>&1 </dev/null &
sleep 9
TITLE=$(py "import sys; sys.path.insert(0,'.')
from taskwidget import config, i18n
i18n.set_language(config.load().get('language'))
sys.stdout.write(i18n.tr('welcome — how this widget works'))")
grab "$(xwininfo -root -tree 2>/dev/null | grep -F "\"$TITLE\"" | head -1 | awk '{print $1}')" "$TMP/intro.png"
kill_all

# ---- confirmation dialog ---------------------------------------------------
echo "== clear-all dialog"
setsid nohup python3 - "$ROOT" >"$TMP/dialog.log" 2>&1 <<'PY' &
import os, sys, time
os.environ.setdefault("GDK_BACKEND", "x11")
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk
import taskwidget.gtkutil as G
G.init(x11=True)
from taskwidget import config, theme
import taskwidget.settingsapp as SA
theme.apply_css(config.load())
app = SA.SettingsApp(); app.show()
def open_it():
    app._clear_all_dialog()
    if app._clear_entry is not None:
        app._clear_entry.set_text(SA.CLEAR_PHRASE)
    return False
GLib.timeout_add(1500, open_it)
Gtk.main()
PY
sleep 7
grab "$(xwininfo -root -tree 2>/dev/null | grep -i 'clear all tasks' | head -1 | awk '{print $1}')" "$TMP/clear-dialog.png"
kill_all

# ---- settings, all five tabs ---------------------------------------------
setsid nohup python3 -u bin/task-widget >"$TMP/live.log" 2>&1 </dev/null &
sleep 5
for page in 0 1 2 3 4; do
  python3 bin/task-widget-settings --page "$page" >"$TMP/set-$page.log" 2>&1 &
  pid=$!
  sleep 7
  grab "$(settings_id)" "$TMP/set-$page.png"
  kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
  sleep 1
done

# ---- put everything on the wallpaper --------------------------------------
echo "== compositing"
compose () {
  local src="$1" out="$2" pad="${3:-70}" w h cw ch
  [ -s "$src" ] || { echo "  ! missing $src"; return 1; }
  read -r w h < <(identify -format '%w %h' "$src")
  cw=$((w + 2 * pad)); ch=$((h + 2 * pad))
  magick "$WALL" -resize "${cw}x${ch}!" "$src" -geometry "+${pad}+${pad}" \
         -composite -depth 8 -strip -define png:compression-level=9 "$out"
  echo "  -> $(basename "$out") $(identify -format '%wx%h' "$out")"
}
shrink () {   # cap width so the README stays readable
  local w; w=$(identify -format '%w' "$1")
  if [ "$w" -gt 1150 ]; then magick "$1" -resize 1150x "$2"; else cp "$1" "$2"; fi
}

compose "$TMP/widget-dark.png"     "$OUT/widget-dark.png"
compose "$TMP/widget-bright.png"   "$OUT/widget-bright.png"
compose "$TMP/day-popover.png"     "$OUT/day-popover.png"
compose "$TMP/steps-popover.png"   "$OUT/steps-popover.png"
compose "$TMP/notification.png"    "$OUT/notification.png"
compose "$TMP/drag-mode.png"       "$OUT/drag-mode.png"
compose "$TMP/intro.png"           "$OUT/intro.png" 60
compose "$TMP/clear-dialog.png"    "$OUT/clear-dialog.png" 60
for p in 0 1 2 3 4; do
  [ -s "$TMP/set-$p.png" ] || continue
  shrink "$TMP/set-$p.png" "$TMP/set-$p-s.png"
  compose "$TMP/set-$p-s.png" "$OUT/settings-$p.png" 55
done
mv -f "$OUT/settings-0.png" "$OUT/settings-appearance.png" 2>/dev/null
mv -f "$OUT/settings-1.png" "$OUT/settings-position.png" 2>/dev/null
mv -f "$OUT/settings-2.png" "$OUT/settings-notifications.png" 2>/dev/null
mv -f "$OUT/settings-3.png" "$OUT/settings-features.png" 2>/dev/null
mv -f "$OUT/settings-4.png" "$OUT/settings-data.png" 2>/dev/null

# folded rail next to the full card
if [ -s "$TMP/folded.png" ] && [ -s "$TMP/widget-dark.png" ]; then
  magick "$TMP/widget-dark.png" -resize 50% "$TMP/u.png"
  magick "$TMP/folded.png" -resize 50% "$TMP/f.png"
  read -r uw uh < <(identify -format '%w %h' "$TMP/u.png")
  read -r fw fh < <(identify -format '%w %h' "$TMP/f.png")
  gw=90; pad=70
  cw=$((uw + fw + gw + 2 * pad)); ch=$((uh + 2 * pad))
  magick "$WALL" -resize "${cw}x${ch}!" \
         "$TMP/u.png" -geometry "+${pad}+${pad}" -composite \
         "$TMP/f.png" -geometry "+$((pad + uw + gw))+${pad}" -composite \
         -depth 8 -strip "$OUT/fold-unfold.png"
  echo "  -> fold-unfold.png $(identify -format '%wx%h' "$OUT/fold-unfold.png")"
fi

# ---- put the user's settings back ----------------------------------------
py "
import sys; sys.path.insert(0, '.')
from taskwidget import config
config.update(lambda c: (c.__setitem__('language', '$ORIG_LANG'),
                         c.__setitem__('onboarding_seen', '$ORIG_SEEN' == 'True'),
                         c.__setitem__('theme', 'dark'),
                         c.__setitem__('opacity', 0.72)))"
echo "restored language=$ORIG_LANG onboarding_seen=$ORIG_SEEN"
kill_all
setsid nohup python3 -u bin/task-widget >/tmp/tw-live.log 2>&1 </dev/null &
sleep 3
echo "== done -> $OUT"
ls -1 "$OUT" | sed 's/^/  /'
du -sh "$OUT" | sed 's/^/  /'
rm -rf "$TMP"
