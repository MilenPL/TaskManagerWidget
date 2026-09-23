#!/usr/bin/env bash
#
# Installs the task manager widget for the current user.
#
#   ./install.sh                 launchers, icon and autostart entry
#   ./install.sh --no-autostart  launchers and icon only
#   ./install.sh --uninstall     remove everything this script created
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
AUTO_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
WANT_AUTOSTART=1
ACTION=install

for arg in "$@"; do
  case "$arg" in
    --no-autostart) WANT_AUTOSTART=0 ;;
    --autostart)    WANT_AUTOSTART=1 ;;
    --uninstall)    ACTION=uninstall ;;
    -h|--help)
      sed -n '2,7p' "$0"
      exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

# Prefer the console scripts if the package is installed (pipx/pip);
# otherwise run straight from this checkout.
resolve () {   # $1 = console name, $2 = script inside this repo
  local installed
  installed="$(command -v "$1" 2>/dev/null || true)"
  if [ -n "$installed" ]; then
    printf '%s' "$installed"
  else
    printf '%s' "$ROOT/bin/$2"
  fi
}

WIDGET_CMD="$(resolve task-widget task-widget)"
SETTINGS_CMD="$(resolve task-widget-settings task-widget-settings)"

write_entry () {   # path name comment exec extra
  cat >"$1" <<EOF
[Desktop Entry]
Type=Application
Name=$2
Comment=$3
Exec=$4
Icon=task-widget
Terminal=false
Categories=Utility;Office;
StartupNotify=false
$5
EOF
  chmod 744 "$1"
}

if [ "$ACTION" = "uninstall" ]; then
  rm -f "$APP_DIR/task-widget.desktop" \
        "$APP_DIR/task-widget-settings.desktop" \
        "$AUTO_DIR/task-widget.desktop" \
        "$ICON_DIR/task-widget.svg"
  command -v update-desktop-database >/dev/null 2>&1 \
    && update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
  echo "removed launchers, autostart entry and icon"
  echo "your tasks and settings were left untouched:"
  echo "  ${XDG_DATA_HOME:-$HOME/.local/share}/task-widget/"
  echo "  ${XDG_CONFIG_HOME:-$HOME/.config}/task-widget/"
  exit 0
fi

mkdir -p "$APP_DIR" "$ICON_DIR" "$AUTO_DIR"
[ -d "$(dirname "$WIDGET_CMD")" ] || chmod +x "$ROOT/bin/task-widget" \
                                       "$ROOT/bin/task-widget-settings"

cp -f "$ROOT/data/task-widget.svg" "$ICON_DIR/task-widget.svg"
chmod 644 "$ICON_DIR/task-widget.svg"

write_entry "$APP_DIR/task-widget-settings.desktop" \
  "task manager widget settings" \
  "Configure the liquid glass task widget" \
  "$SETTINGS_CMD" \
  "Keywords=tasks;todo;widget;glass;"

write_entry "$APP_DIR/task-widget.desktop" \
  "task manager widget" \
  "Always-on-bottom liquid glass task widget" \
  "$WIDGET_CMD" \
  "NoDisplay=true"

if [ "$WANT_AUTOSTART" = "1" ]; then
  write_entry "$AUTO_DIR/task-widget.desktop" \
    "task manager widget" \
    "Always-on-bottom liquid glass task widget" \
    "$WIDGET_CMD" \
    "X-GNOME-Autostart-enabled=true
NoDisplay=true"
  echo "autostart: enabled"
else
  rm -f "$AUTO_DIR/task-widget.desktop"
  echo "autostart: disabled"
fi

command -v update-desktop-database >/dev/null 2>&1 \
  && update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 \
  && gtk-update-icon-cache -q -t "$ICON_DIR/.." >/dev/null 2>&1 || true

echo "widget:    $WIDGET_CMD"
echo "settings:  $SETTINGS_CMD"
echo "launchers: $APP_DIR"
echo
echo "start it now with:  $WIDGET_CMD"
