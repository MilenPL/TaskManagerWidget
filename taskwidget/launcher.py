"""Console entry points.

The X11 backend **must** be chosen before ``gi.repository.Gtk`` is imported,
otherwise GTK silently binds to Wayland and the window loses its
"always below / hidden from alt-tab" hints.  Nothing in this module touches
GTK, so it is safe to import first.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def setup_backend() -> None:
    """Force the XWayland backend unless the user picks one explicitly.

    ``TASKWIDGET_BACKEND`` exists so the widget can be experimented with on a
    pure Wayland session (stacking and taskbar hints will not work there).
    """
    override = os.environ.get("TASKWIDGET_BACKEND")
    os.environ["GDK_BACKEND"] = override if override else "x11"


def root() -> str:
    """The checkout root, or site-packages' parent when pip-installed."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(module: str) -> int:
    setup_backend()
    mod = __import__(f"taskwidget.{module}", fromlist=["main"])
    return int(mod.main() or 0)


def widget() -> None:
    """``task-widget`` — start the widget."""
    raise SystemExit(run("widget"))


def settings() -> None:
    """``task-widget-settings`` — start 'task manager widget settings'."""
    raise SystemExit(run("settingsapp"))


# --------------------------------------------------------------- launching --

def _command(console: str, script: str) -> list[str]:
    """How to start one of the two programs on this machine.

    Installed console script > script in this checkout > in-process import,
    so a widget installed with pip can still be relaunched from its settings
    app.
    """
    exe = shutil.which(console)
    if exe:
        return [exe]
    path = os.path.join(root(), "bin", script)
    if os.path.exists(path):
        return [sys.executable, path]
    return [sys.executable, "-c",
            f"from taskwidget.launcher import "
            f"{'widget' if console == 'task-widget' else 'settings'}; "
            f"{'widget' if console == 'task-widget' else 'settings'}()"]


def widget_command() -> list[str]:
    return _command("task-widget", "task-widget")


def settings_command() -> list[str]:
    return _command("task-widget-settings", "task-widget-settings")


def _spawn(cmd: list[str]) -> bool:
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def launch_widget() -> bool:
    return _spawn(widget_command())


def launch_settings() -> bool:
    return _spawn(settings_command())


if __name__ == "__main__":                       # pragma: no cover
    target = (sys_argv := __import__("sys").argv)[1] if len(sys_argv) > 1 else "widget"
    raise SystemExit(run("settingsapp" if target.startswith("set") else "widget"))
