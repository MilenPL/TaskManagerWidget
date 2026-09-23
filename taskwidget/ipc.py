"""Tiny line-JSON UNIX socket channel between the settings app and the widget."""

from __future__ import annotations

import json
import os
import socket
import threading

from . import paths


def sock_path() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/task-widget-{paths.uid()}"
    os.makedirs(base, exist_ok=True)
    p = os.path.join(base, "task-widget.sock")
    # stale socket from a crashed run?
    if os.path.exists(p) and not alive(p):
        try:
            os.unlink(p)
        except OSError:
            pass
    return p


def alive(path: str | None = None) -> bool:
    path = path or sock_path()
    if not os.path.exists(path):
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            s.connect(path)
        return True
    except OSError:
        return False


def send(cmd: dict, timeout: float = 1.0) -> dict | None:
    """Send one command; returns the acknowledgement or None if not running."""
    path = sock_path()
    if not os.path.exists(path):
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(path)
            s.sendall((json.dumps(cmd) + "\n").encode("utf-8"))
            s.shutdown(socket.SHUT_WR)
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.decode("utf-8") or "{}")
    except (OSError, ValueError):
        return None


def serve(handler) -> "Server":
    """Start accepting commands in a background thread.

    ``handler(cmd: dict) -> None`` runs on the calling (GTK) thread via
    GLib.idle_add, so it is safe to touch widgets there.
    """
    return Server(handler)


class Server:
    def __init__(self, handler):
        self.handler = handler
        self.path = sock_path()
        self._stop = threading.Event()
        try:
            os.unlink(self.path)
        except OSError:
            pass
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self.path)
        os.chmod(self.path, 0o600)
        self._sock.listen(6)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        from gi.repository import GLib
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            try:
                conn.settimeout(1.5)
                buf = b""
                while b"\n" not in buf:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                cmd = json.loads(buf.decode("utf-8") or "{}")
                GLib.idle_add(self._dispatch, cmd)
                conn.sendall(b'{"ok":true}\n')
            except (OSError, ValueError):
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _dispatch(self, cmd):
        try:
            self.handler(cmd)
        except Exception as exc:            # never let a bad command kill us
            print(f"ipc error: {exc}")
        return False

    def close(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        try:
            os.unlink(self.path)
        except OSError:
            pass
