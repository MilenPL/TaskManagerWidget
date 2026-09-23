"""Shared GTK 3 plumbing: init, glass visuals, styling and text helpers."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")

import cairo                                            # noqa: E402
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from . import theme                                     # noqa: E402


def init(x11: bool = True) -> None:
    """Force the X11 backend before GTK realises anything.

    Wayland cannot express "keep below + skip taskbar + sticky", so the whole
    app runs on XWayland.
    """
    if x11:
        os.environ["GDK_BACKEND"] = "x11"
        os.environ.setdefault("GDK_BACKEND", "x11")
    Gtk.init(None)


def cls(widget, *names: str):
    sc = widget.get_style_context()
    for n in names:
        if n:
            sc.add_class(n)
    return widget


def uncls(widget, *names: str) -> None:
    sc = widget.get_style_context()
    for n in names:
        sc.remove_class(n)


def toggle_cls(widget, name: str, on: bool) -> None:
    (cls if on else uncls)(widget, name)


def set_margins(widget, top=0, bottom=0, left=0, right=0) -> None:
    widget.set_margin_top(top)
    widget.set_margin_bottom(bottom)
    widget.set_margin_start(left)
    widget.set_margin_end(right)


def glass_visual(window: Gtk.Window) -> None:
    """RGBA visual + transparent draw handler: lets CSS corners float."""
    screen = window.get_screen()
    if screen.is_composited() and screen.get_rgba_visual():
        window.set_visual(screen.get_rgba_visual())
    window.set_app_paintable(True)

    def on_draw(_w, cr):
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.0)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        return False

    window.connect("draw", on_draw)


def set_cursor(widget: Gtk.Widget, name: str) -> None:
    win = widget.get_window()
    if win is None:
        widget.connect("realize", lambda w: set_cursor(w, name))
        return
    try:
        if not name:
            win.set_cursor(None)
        else:
            win.set_cursor(Gdk.Cursor.new_from_name(widget.get_display(), name))
    except TypeError:
        pass


def xid_of(widget) -> int | None:
    """X11 window id of a widget's GdkWindow (used only for screenshots)."""
    try:
        import gi
        gi.require_version("GdkX11", "3.0")
        from gi.repository import GdkX11
        w = widget if isinstance(widget, Gdk.Window) else widget.get_window()
        if w is None:
            return None
        return int(GdkX11.X11Window.get_xid(w))
    except Exception:
        return None


def px(v: int) -> int:
    """Logical px (GTK already scales for HiDPI)."""
    return int(v)


# ------------------------------------------------------------------- text ----


def layout_for(cr, text: str, size: float, bold=False, color="#ffffff",
               alpha=1.0, align="left", max_w: float | None = None,
               ellipsize=True) -> tuple:
    """Create a Pango layout, optionally ellipsised, ready to paint."""
    lay = PangoCairo.create_layout(cr)
    desc = Pango.FontDescription()
    desc.set_family("Adwaita Sans, Cantarell, Sans")
    desc.set_size(int(size * Pango.SCALE))
    desc.set_weight(Pango.Weight.BOLD if bold else Pango.Weight.NORMAL)
    lay.set_font_description(desc)
    lay.set_text(str(text), -1)
    if max_w and max_w > 0:
        lay.set_ellipsize(Pango.EllipsizeMode.END if ellipsize else Pango.EllipsizeMode.NONE)
        lay.set_width(int(max_w * Pango.SCALE))
        lay.set_ellipsize(Pango.EllipsizeMode.END)
    lay.set_alignment(
        {"left": Pango.Alignment.LEFT, "center": Pango.Alignment.CENTER,
         "right": Pango.Alignment.RIGHT}[align]
    )
    return lay


def show_layout(cr, lay, x: float, y: float, color: str, alpha: float = 1.0) -> None:
    r, g, b, a = theme.parse_css_color(color)
    cr.set_source_rgba(r, g, b, a * alpha)
    cr.move_to(x, y)
    PangoCairo.show_layout(cr, lay)


def text_size(cr, text: str, size: float, bold=False, max_w: float | None = None):
    lay = layout_for(cr, text, size, bold=bold, max_w=max_w)
    w, h = lay.get_pixel_size()
    return w, h, lay


def draw_text(cr, text, x, y, size, color, bold=False, align="left",
              max_w=None, alpha=1.0, valign="center") -> tuple:
    """Draw one line of text.  ``(x, y)`` is the anchor point.

    align: left|center|right (horizontal), valign: center|top|baseline
    Returns (w, h).
    """
    w, h, lay = text_size(cr, text, size, bold=bold, max_w=max_w)
    px_ = x
    if align == "center":
        px_ = x - w / 2.0
    elif align == "right":
        px_ = x - w
    py = y
    if valign == "center":
        py = y - h / 2.0
    elif valign == "baseline":
        py = y
    show_layout(cr, lay, px_, py, color, alpha)
    return w, h


# ------------------------------------------------------------------ layout ---


def hbox(spacing=6, start=None, end=None) -> Gtk.Box:
    b = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
    for w in start or []:
        b.pack_start(w, False, False, 0)
    for w in end or []:
        b.pack_end(w, False, False, 0)
    return b


def vbox(spacing=6) -> Gtk.Box:
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


# labels whose text is prose: they wrap instead of running into the edge
WRAP_CSS = {"help", "slabel", "sect", "ssub", "hint", "formlabel", "gempty"}


def label(text: str, css: str = "", xalign: float = 0.0, yalign: float = 0.5) -> Gtk.Label:
    l = Gtk.Label(label=text)
    l.set_xalign(xalign)
    l.set_yalign(yalign)
    if css:
        cls(l, *css.split())
    if set(css.split()) & WRAP_CSS:
        l.set_line_wrap(True)
        l.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    return l


def divider() -> Gtk.Widget:
    b = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    b.set_size_request(-1, 1)
    cls(b, "div")
    return b


def icon_button(icon: str, css: str = "iconbtn", tooltip: str = "") -> Gtk.Button:
    b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
    b.set_relief(Gtk.ReliefStyle.NONE)
    b.set_can_focus(False)
    cls(b, *css.split())
    if tooltip:
        b.set_tooltip_text(tooltip)
    return b


def button(text: str, css: str = "btn", tooltip: str = "") -> Gtk.Button:
    b = Gtk.Button.new_with_label(text)
    b.set_relief(Gtk.ReliefStyle.NONE)
    cls(b, *css.split())
    if tooltip:
        b.set_tooltip_text(tooltip)
    return b


def dot(color_index: int, size: int = 9) -> Gtk.Box:
    from .models import PALETTE
    d = Gtk.Box()
    d.set_size_request(size, size)
    cls(d, "dot", f"c{color_index % len(PALETTE)}")
    return d


def swatch_button(color_index: int, on_picked) -> Gtk.Button:
    from .models import PALETTE
    name, hexv = PALETTE[color_index % len(PALETTE)]
    b = Gtk.Button()
    b.set_relief(Gtk.ReliefStyle.NONE)
    b.set_can_focus(False)
    b.set_size_request(15, 15)
    cls(b, "sw", f"c{color_index % len(PALETTE)}")
    b.set_tooltip_text(name)
    b.connect("clicked", lambda _w: on_picked(color_index))
    return b


def switch(on: bool, on_changed) -> Gtk.Switch:
    s = Gtk.Switch()
    s.set_active(bool(on))
    s.set_valign(Gtk.Align.CENTER)
    s.connect("state-set", lambda _w, state: (on_changed(bool(state)), False)[1])
    return s


def scale(lo, hi, step, value, on_changed, draw_value=False) -> Gtk.Scale:
    s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
    s.set_value(value)
    s.set_draw_value(bool(draw_value))
    s.set_value_pos(Gtk.PositionType.RIGHT)
    s.set_digits(2 if step < 0.05 else 0)
    s.set_hexpand(True)
    s.connect("value-changed", lambda w: on_changed(w.get_value()))
    return s


def popover_for(widget: Gtk.Widget) -> Gtk.Popover:
    p = Gtk.Popover.new(widget)
    p.set_modal(True)
    cls(p, "tw")
    return p


def combobox(items, active, on_changed) -> Gtk.ComboBoxText:
    c = Gtk.ComboBoxText()
    for it in items:
        c.append_text(it)
    if 0 <= active < len(items):
        c.set_active(active)
    c.connect("changed", lambda w: on_changed(w.get_active()))
    return c


class StepRing(Gtk.DrawingArea):
    """A small circular progress ring shown instead of a plain colour dot."""

    def __init__(self, color: tuple, size: int = 14,
                 track: tuple = (1.0, 1.0, 1.0, 0.18)):
        super().__init__()
        self.color = color
        self.track = track
        self.size = int(size)
        self.done = 0
        self.total = 0
        self.set_can_focus(False)
        self.set_size_request(self.size, self.size)
        self.connect("draw", self._draw)

    def set_progress(self, done: int, total: int) -> None:
        self.done = int(done)
        self.total = int(total)
        self.queue_draw()

    def _draw(self, _w, cr) -> bool:
        s = float(self.size)
        lw = max(1.6, s * 0.17)
        r = (s - lw) / 2.0 - 0.5
        cx = cy = s / 2.0
        cr.set_line_width(lw)
        try:
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
        except AttributeError:
            pass
        cr.arc(cx, cy, r, 0, 6.2831853)
        cr.set_source_rgba(*self.track)
        cr.stroke()
        if self.total > 0:
            frac = max(0.0, min(1.0, self.done / float(self.total)))
            if frac > 0.001:
                end = -1.5707963 + 6.2831853 * frac
                cr.arc(cx, cy, r, -1.5707963, end)
                cr.set_source_rgba(*self.color)
                cr.stroke()
        return True


def workarea() -> tuple[int, int, int, int]:
    """(x, y, w, h) of the primary monitor's workarea, logical px.

    Prefers ``_NET_WORKAREA`` from the X root window because that is the only
    source which already excludes the shell's top bar.
    """
    screen = Gdk.Screen.get_default()
    if screen is not None:
        try:
            root = screen.get_root_window()
            res = root.property_get(Gdk.Atom.intern("_NET_WORKAREA", False))
            if res and res[3]:
                data = list(res[3])
                if len(data) >= 4:
                    return int(data[0]), int(data[1]), int(data[2]), int(data[3])
        except Exception:
            pass
        try:
            n = screen.get_primary_monitor() or 0
            wa = screen.get_monitor_workarea(n)
            return int(wa.x), int(wa.y), int(wa.width), int(wa.height)
        except Exception:
            pass
    return 0, 0, 1600, 900


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


__all__ = [
    "init", "cls", "uncls", "toggle_cls", "set_margins", "glass_visual",
    "set_cursor", "px", "draw_text", "text_size", "layout_for", "show_layout",
    "hbox", "vbox", "label", "divider", "icon_button", "button", "dot",
    "swatch_button", "switch", "scale", "popover_for", "combobox", "workarea",
    "clamp", "Gtk", "Gdk", "GLib", "Pango", "PangoCairo", "cairo", "theme",
]
