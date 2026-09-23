"""Liquid-glass CSS generation (dark / bright, opacity and scale aware).

Everything here must stay inside the GTK 3.24 CSS dialect: no ``!important``,
no ``background:`` shorthand, no ``font-feature-settings``.  Borders are always
written longhand so unknown-value errors cannot creep in.
"""

from __future__ import annotations

from .models import PALETTE

# ---------------------------------------------------------------- colours ----


def rgba(hex_color: str, a: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    a = max(0.0, min(1.0, float(a)))
    return f"rgba({r},{g},{b},{a:.3f})"


def parse_css_color(s: str) -> tuple[float, float, float, float]:
    """Turn a CSS colour we produced back into cairo floats."""
    s = (s or "").strip()
    if s.startswith("#"):
        h = s.lstrip("#")
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0,
                int(h[4:6], 16) / 255.0, 1.0)
    inner = s[s.find("(") + 1:s.rfind(")")]
    parts = [p.strip() for p in inner.split(",")]
    if len(parts) == 4 and "/" not in inner:
        r, g, b, a = parts
        return (float(r) / 255.0, float(g) / 255.0, float(b) / 255.0, float(a))
    if len(parts) == 3:
        r, g, b = parts
        return (float(r) / 255.0, float(g) / 255.0, float(b) / 255.0, 1.0)
    return (0.0, 0.0, 0.0, 1.0)


def hex_rgba(hex_color: str) -> tuple[float, float, float, float]:
    r, g, b, _ = parse_css_color(hex_color)
    return (r, g, b, 1.0)


def _mix(c1: str, c2: str, t: float) -> str:
    a = c1.lstrip("#")
    b = c2.lstrip("#")
    out = "#"
    for i in (0, 2, 4):
        x = int(a[i:i + 2], 16)
        y = int(b[i:i + 2], 16)
        out += f"{int(x + (y - x) * t):02x}"
    return out


def clamp_alpha(v, default=0.72) -> float:
    try:
        a = float(v)
    except (TypeError, ValueError):
        a = default
    return max(0.40, min(1.0, a))


def clamp_radius(v) -> float:
    """Corner roundness in logical px;0 = square,48 = fully rounded card."""
    try:
        r = float(v)
    except (TypeError, ValueError):
        r = 26.0
    return max(0.0, min(48.0, r))


def scale_of(cfg: dict) -> float:
    try:
        s = float(cfg.get("scale", 1.0))
    except (TypeError, ValueError):
        s = 1.0
    return max(0.85, min(1.10, s))


def theme_colors(cfg: dict) -> dict:
    """Colors for both CSS and the cairo-drawn calendar."""
    bright = cfg.get("theme") == "bright"
    alpha = clamp_alpha(cfg.get("opacity", 0.72))
    if bright:
        return dict(
            bright=True,
            alpha=alpha,
            bg1=rgba("#fdfdff", alpha),
            bg2=rgba("#e9edf6", alpha),
            solid1="#fdfdff",
            solid2="#e9edf6",
            text=rgba("#171a26", 0.93),
            text1="#171a26",
            dim=rgba("#171a26", 0.50),
            line=_mix("#ffffff", "#1d2438", 0.16),
            line_soft=_mix("#ffffff", "#1d2438", 0.10),
            surface=rgba("#1d2438", 0.05),
            surface_h=rgba("#1d2438", 0.09),
            accent="#2f6fed",
            accent_soft=rgba("#2f6fed", 0.16),
            border=rgba("#ffffff", 0.85),
            shadow=rgba("#28324e", 0.35),
            entry_bg=rgba("#ffffff", 0.55),
            done="#12a05a",
            late="#d9480f",
            dot_ring=rgba("#1d2438", 0.18),
        )
    return dict(
        bright=False,
        alpha=alpha,
        bg1=rgba("#212436", alpha),
        bg2=rgba("#0e0f18", alpha),
        solid1="#1b1e2e",
        solid2="#0e0f18",
        text=rgba("#eef1ff", 0.94),
        text1="#eef1ff",
        dim=rgba("#eef1ff", 0.52),
        line=rgba("#ffffff", 0.17),
        line_soft=rgba("#ffffff", 0.10),
        surface=rgba("#ffffff", 0.055),
        surface_h=rgba("#ffffff", 0.10),
        accent="#7aa2ff",
        accent_soft=rgba("#7aa2ff", 0.22),
        border=rgba("#ffffff", 0.16),
        shadow=rgba("#000000", 0.50),
        entry_bg=rgba("#ffffff", 0.06),
        done="#30d158",
        late="#ff9f0a",
        dot_ring=rgba("#ffffff", 0.22),
    )


def border(width: str, style: str, color: str, indent: str = "  ") -> str:
    return (f"{indent}border-width: {width};\n"
            f"{indent}border-style: {style};\n"
            f"{indent}border-color: {color};")


# ------------------------------------------------------------------- css -----


def build_css(cfg: dict) -> str:
    k = scale_of(cfg)
    c = theme_colors(cfg)
    danger = "#d9302f" if c.get("bright") else "#ff453a"
    radius = clamp_radius(cfg.get("radius"))
    rail_radius = min(radius, 20.0)              # the rail is only 48 px wide
    u = lambda v: f"{v * k:.2f}px"           # noqa: E731  (scale-aware unit)
    fs = lambda v: f"{font_px(v, k)}px"      # noqa: E731

    color_classes = "\n".join(
        f"  .tw .c{i} {{ background-color: {h}; }}" for i, (_, h) in enumerate(PALETTE)
    )
    swatch_classes = "\n".join(
        f"  .tw .sw.c{i} {{ background-color: {h}; }}" for i, (_, h) in enumerate(PALETTE)
    )

    css = f"""
/* ================= toplevel: transparent so the glass card floats ========= */
.tw {{
  background-color: transparent;
  font-family: "Adwaita Sans", "Cantarell", sans-serif;
  font-size: {fs(12)};
  color: {c['text']};
}}
.tw button, .tw entry, .tw label {{ text-shadow: none; }}
.tw button {{ background-image: none; box-shadow: none; }}

.glass {{
  background-image: linear-gradient(165deg, {c['bg1']}, {c['bg2']});
{border('1px', 'solid', c['border'], '  ')}
  border-radius: {u(radius)};
  box-shadow: 0 {u(14)} {u(38)} {c['shadow']};
  padding: {u(12)};
}}

/* ---- gentle section dividers: fade out at both ends ---- */
.div {{
  background-image: linear-gradient(to right, transparent, {c['line']} 14%, {c['line']} 86%, transparent);
  min-height: 1px;
  margin: {u(7)} {u(3)};
}}

/* ---- header ---- */
.hdr {{ padding: {u(2)} {u(4)} {u(0)}; }}
.title {{ font-size: {fs(15)}; font-weight: 800; color: {c['text']}; }}
.date  {{ font-size: {fs(11)}; color: {c['dim']}; }}
.iconbtn {{
  background-color: transparent;
  color: {c['dim']};
  border-width: 0;
  border-radius: {u(999)};
  padding: {u(6)};
  min-width: {u(26)};
  min-height: {u(26)};
}}
.iconbtn:hover {{ background-color: {c['surface_h']}; color: {c['text']}; }}
.iconbtn:active {{ background-color: {c['accent_soft']}; }}

/* ---- search / filter row ---- */
.searchrow {{ padding: {u(1)} {u(4)}; }}

/* ---- calendar ---- */
.calnav {{ padding: {u(2)} {u(2)} {u(0)}; }}
.caltitle {{ font-size: {fs(12.5)}; font-weight: 800; color: {c['text']}; }}
.calwrap {{ border-radius: {u(16)}; }}

/* ---- day groups ---- */
.glabel {{
  font-size: {fs(10.5)}; font-weight: 800;
  color: {c['dim']};
  padding: {u(7)} {u(6)} {u(2)};
}}
.gempty {{ font-size: {fs(11)}; color: {c['dim']}; opacity: 0.55; padding: {u(2)} {u(8)} {u(5)}; }}

/* ---- task rows ---- */
.row {{
  border-radius: {u(13)};
  padding: {u(5)} {u(7)};
  background-color: transparent;
}}
.row:hover {{ background-color: {c['surface_h']}; }}
.row.retro {{ opacity: 0.62; }}
.row.done  {{ opacity: 0.55; }}
.ttext {{ font-size: {fs(12.5)}; color: {c['text']}; }}
.ttime {{
  font-size: {fs(11.5)}; color: {c['dim']};
}}
.tick {{ font-size: {fs(11)}; color: {c['done']}; }}
.del {{
  background-color: transparent;
  color: {c['dim']};
  border-width: 0;
  border-radius: {u(999)};
  padding: {u(2)};
  min-width: {u(20)};
  min-height: {u(20)};
  opacity: 0;
}}
.row:hover .del {{ opacity: 0.75; }}
.row:hover .del:hover {{ background-color: {c['surface_h']}; color: {c['late']}; opacity: 1; }}
.check {{
  background-color: transparent;
  color: transparent;
  border-width: 1.5px;
  border-style: solid;
  border-color: {c['line']};
  border-radius: {u(999)};
  padding: {u(1)};
  min-width: {u(16)};
  min-height: {u(16)};
  font-size: {fs(10)};
  font-weight: 800;
}}
.check:hover {{ border-color: {c['text']}; color: {c['dim']}; }}
.check.on {{
  background-color: {c['done']};
  border-color: transparent;
  color: #ffffff;
}}
.badge {{
  font-size: {fs(9.5)}; font-weight: 800;
  padding: {u(2)} {u(7)};
  border-radius: {u(999)};
  background-color: {c['surface']};
  color: {c['dim']};
  border-width: 1px;
  border-style: solid;
  border-color: {c['line_soft']};
}}
.badge.done {{ color: {c['done']}; border-color: {rgba('#30d158', 0.35)}; }}
.badge.late {{ color: {c['late']}; border-color: {rgba('#ff9f0a', 0.35)}; }}

.dot {{ min-width: {u(9)}; min-height: {u(9)}; border-radius: {u(999)}; }}
{color_classes}

/* ---- scrollbars ---- */
.scroll, .scroll > viewport {{ background-color: transparent; box-shadow: none; }}
scrollbar {{ background-color: transparent; }}
scrollbar slider {{
  background-color: {c['line']};
  border-width: 0;
  border-radius: {u(999)};
  min-width: {u(5)};
  min-height: {u(24)};
}}
scrollbar slider:hover {{ background-color: {c['dim']}; }}
scrollbar button {{ background-color: transparent; border-width: 0; color: transparent; }}

/* ---- form controls ---- */
.formlabel {{ font-size: {fs(10.5)}; font-weight: 800; color: {c['dim']}; }}
.hint {{ font-size: {fs(10.5)}; color: {c['dim']}; }}
.hint.warn {{ color: {c['late']}; }}
.entry {{
  background-color: {c['entry_bg']};
  border-width: 1px;
  border-style: solid;
  border-color: {c['line_soft']};
  border-radius: {u(13)};
  padding: {u(7)} {u(11)};
  color: {c['text']};
  font-size: {fs(12.5)};
}}
.entry:focus {{ border-color: {c['accent']}; background-color: {c['surface']}; }}
.entry selection {{ background-color: {c['accent_soft']}; color: {c['text']}; }}
.btn {{
  background-color: {c['surface']};
  border-width: 1px;
  border-style: solid;
  border-color: {c['line_soft']};
  border-radius: {u(13)};
  color: {c['text']};
  padding: {u(6)} {u(12)};
  font-size: {fs(12)};
  box-shadow: none;
}}
.btn:hover {{ background-color: {c['surface_h']}; }}
.btn:active {{ background-color: {c['accent_soft']}; }}
.btn.suggested {{
  background-color: {c['accent']};
  border-color: transparent;
  color: #ffffff;
  font-weight: 800;
}}
.btn.suggested:hover {{ background-color: {c['accent']}; opacity: 0.92; }}
.btn.danger {{
  background-color: transparent;
{border('1px', 'solid', danger, '  ')}
  color: {danger};
  font-weight: 700;
}}
.btn.danger:hover {{ background-color: {rgba(danger, 0.16)}; }}
.btn.danger:disabled {{ opacity: 0.45; }}
.phrase {{
  font-size: {fs(12.5)};
  font-weight: 700;
  color: {c['accent']};
  background-color: {c['surface']};
{border('1px', 'solid', c['line'], '  ')}
  border-radius: {u(9)};
  padding: {u(3)} {u(10)};
}}
.chip {{
  background-color: transparent;
  border-width: 1px;
  border-style: solid;
  border-color: {c['line']};
  border-radius: {u(999)};
  color: {c['dim']};
  padding: {u(5)} {u(11)};
  font-size: {fs(11)};
  box-shadow: none;
}}
.chip:hover {{ background-color: {c['surface_h']}; color: {c['text']}; }}
.chip.on {{
  background-color: {c['accent_soft']};
  border-color: {c['accent']};
  color: {c['text']};
  font-weight: 700;
}}
.calbtn {{
  background-color: {c['surface']};
  border-width: 1px;
  border-style: solid;
  border-color: {c['line_soft']};
  border-radius: {u(13)};
  color: {c['text']};
  padding: {u(6)} {u(10)};
  font-size: {fs(11.5)};
  box-shadow: none;
}}
.calbtn:hover {{ background-color: {c['surface_h']}; }}
.calbtn.on {{ border-color: {c['accent']}; background-color: {c['accent_soft']}; }}
.calnavbtn {{
  background-color: transparent;
  border-width: 0;
  color: {c['dim']};
  border-radius: {u(999)};
  min-width: {u(24)}; min-height: {u(24)};
  padding: {u(3)};
}}
.calnavbtn:hover {{ background-color: {c['surface_h']}; color: {c['text']}; }}
.spinbutton {{
  background-color: {c['surface']};
  border-width: 1px;
  border-style: solid;
  border-color: {c['line_soft']};
  border-radius: {u(13)};
  color: {c['text']};
}}
.spinbutton entry {{ background-color: transparent; border-width: 0; color: {c['text']}; }}
.spinbutton button {{ background-color: transparent; border-width: 0; color: {c['dim']}; box-shadow: none; }}
.spinbutton button:hover {{ color: {c['text']}; }}

/* ---- popover (calendar / filter) ---- */
popover.background {{
  background-color: {c['bg1']};
  background-image: linear-gradient(165deg, {c['bg1']}, {c['bg2']});
  border-width: 1px;
  border-style: solid;
  border-color: {c['border']};
  border-radius: {u(18)};
  box-shadow: 0 {u(10)} {u(28)} {c['shadow']};
  padding: {u(10)};
  color: {c['text']};
}}
popover.background > contents {{ background-color: transparent; padding: 0; }}
popover.background > arrow {{ background-color: {c['bg1']}; border-width: 0; }}

/* ---- gtk calendar inside popovers ---- */
calendar {{
  background-color: transparent;
  color: {c['text']};
  border-width: 0;
}}
calendar header {{ background-color: transparent; border-width: 0; }}
calendar header button {{
  background-color: {c['surface']};
  border-width: 1px;
  border-style: solid;
  border-color: {c['line_soft']};
  border-radius: {u(9)};
  color: {c['dim']};
  box-shadow: none;
}}
calendar header button:hover {{ color: {c['text']}; background-color: {c['surface_h']}; }}
calendar header label {{ color: {c['text']}; font-weight: 800; }}
calendar > grid {{ border-width: 0; }}
calendar > grid > label {{ color: {c['dim']}; border-radius: {u(8)}; }}
calendar > grid > label:selected {{ background-color: {c['accent']}; color: #ffffff; font-weight: 800; }}
calendar:selected {{ background-color: {c['accent']}; color: #ffffff; }}

/* ---- switches and scales (settings app) ---- */
switch {{
  background-color: {c['surface']};
  border-width: 1px;
  border-style: solid;
  border-color: {c['line_soft']};
  border-radius: {u(999)};
  min-width: {u(42)};
  min-height: {u(22)};
  box-shadow: none;
}}
switch:checked {{ background-color: {c['accent']}; border-color: transparent; }}
switch slider {{
  background-color: #ffffff;
  border-width: 0;
  border-radius: {u(999)};
  min-width: {u(17)};
  min-height: {u(17)};
  box-shadow: 0 {u(2)} {u(4)} {rgba('#000000', 0.28)};
}}
scale trough {{
  background-color: {c['surface_h']};
  border-width: 0;
  border-radius: {u(999)};
  min-height: {u(6)};
  min-width: {u(6)};
}}
scale highlight {{ background-color: {c['accent']}; border-width: 0; border-radius: {u(999)}; }}
scale slider {{
  background-color: #ffffff;
  border-width: 1px;
  border-style: solid;
  border-color: {c['line']};
  border-radius: {u(999)};
  min-width: {u(15)};
  min-height: {u(15)};
  box-shadow: 0 {u(2)} {u(5)} {rgba('#000000', 0.30)};
}}
combobox button {{
  background-color: {c['surface']};
  border-width: 1px;
  border-style: solid;
  border-color: {c['line_soft']};
  border-radius: {u(12)};
  color: {c['text']};
  padding: {u(5)} {u(10)};
  box-shadow: none;
}}
combobox button:hover {{ background-color: {c['surface_h']}; }}
check, radio {{
  min-width: {u(16)};
  min-height: {u(16)};
  border-width: 1.5px;
  border-style: solid;
  border-color: {c['line']};
  border-radius: {u(6)};
  background-color: {c['entry_bg']};
  color: #ffffff;
}}
check {{ border-radius: {u(999)}; }}
check:checked, radio:checked {{
  background-color: {c['accent']};
  border-color: transparent;
}}
check:checked {{ border-radius: {u(999)}; }}

/* ---- colour swatches ---- */
.sw {{
  border-radius: {u(999)};
  min-width: {u(13)};
  min-height: {u(13)};
  border-width: 1.5px;
  border-style: solid;
  border-color: {c['dot_ring']};
  padding: 0;
  box-shadow: none;
}}
.sw:hover {{ border-color: {c['text']}; }}
.sw.sel {{
  border-width: 2px;
  border-color: {c['text']};
  box-shadow: 0 0 0 {u(3)} {c['accent_soft']};
}}
{swatch_classes}

/* ---- next-up strip ---- */
.nextup {{
  background-color: {c['surface']};
  border-width: 1px;
  border-style: solid;
  border-color: {c['line_soft']};
  border-radius: {u(13)};
  padding: {u(4)} {u(10)};
  margin: {u(5)} {u(4)} {u(0)};
}}
.nextup:hover {{ background-color: {c['surface_h']}; }}
.nlabel {{ font-size: {fs(9.5)}; font-weight: 800; color: {c['dim']}; }}
.ntitle {{ font-size: {fs(12)}; color: {c['text']}; }}
.ncount {{ font-size: {fs(11.5)}; font-weight: 700; color: {c['accent']}; }}
.nextup.late .ncount {{ color: {c['late']}; }}

/* ---- fold rail ---- */
.rail {{ padding: {u(8)}; border-radius: {u(rail_radius)}; }}
.railbtn {{
  background-color: transparent;
  background-image: none;
  color: {c['dim']};
  border-width: 0;
  border-radius: {u(999)};
  min-width: {u(30)};
  min-height: {u(30)};
  padding: {u(6)};
}}
.railbtn:hover {{ background-color: {c['surface_h']}; color: {c['text']}; }}
.raildrag {{
  border-width: 2px;
  border-style: dashed;
  border-color: {c['accent']};
  border-radius: {u(rail_radius)};
}}

/* ---- focusable task rows ---- */
.row:focus {{ background-color: {c['surface_h']}; }}

/* ---- day / steps popovers ---- */
.dpoptitle {{ font-size: {fs(12.5)}; font-weight: 800; color: {c['text']}; }}
.dpopsub {{ font-size: {fs(10.5)}; color: {c['dim']}; }}
.steprow {{
  border-radius: {u(10)};
  padding: {u(3)} {u(5)};
  background-color: transparent;
}}
.steprow:hover {{ background-color: {c['surface_h']}; }}
.steptext {{ font-size: {fs(12)}; color: {c['text']}; }}
.steptext.done {{ color: {c['dim']}; opacity: 0.6; }}
.stepdel {{
  background-color: transparent;
  background-image: none;
  color: {c['dim']};
  border-width: 0;
  border-radius: {u(999)};
  min-width: {u(18)};
  min-height: {u(18)};
  padding: {u(1)};
  opacity: 0.7;
}}
.stepdel:hover {{ color: {c['late']}; opacity: 1; }}
.dotbtn {{
  background-color: transparent;
  background-image: none;
  border-width: 0;
  border-radius: {u(999)};
  padding: {u(3)};
  min-width: {u(18)};
  min-height: {u(18)};
  box-shadow: none;
}}
.dotbtn:hover {{ background-color: {c['surface_h']}; }}
.hint.accent {{ color: {c['accent']}; }}


.drag {{
  background-color: {rgba('#7aa2ff', 0.12)};
  border-width: 2px;
  border-style: dashed;
  border-color: {c['accent']};
  border-radius: {u(radius)};
}}
.draglabel {{
  color: {c['text']};
  font-size: {fs(13)};
  font-weight: 800;
  background-color: {c['bg1']};
  border-radius: {u(999)};
  padding: {u(7)} {u(16)};
  border-width: 1px;
  border-style: solid;
  border-color: {c['border']};
  box-shadow: 0 {u(6)} {u(18)} {c['shadow']};
}}

/* =================== settings app =================== */
.settings {{
  background-color: {c['solid1']};
  background-image: linear-gradient(165deg, {c['solid1']}, {c['solid2']});
  color: {c['text1']};
  font-size: {fs(12.5)};
}}
.stitle {{ font-size: {fs(17)}; font-weight: 800; color: {c['text']}; }}
.ssub {{ font-size: {fs(11)}; color: {c['dim']}; }}
.sect {{
  font-size: {fs(12)}; font-weight: 800;
  color: {c['text']};
  margin-top: {u(10)};
  margin-bottom: {u(4)};
}}
.help {{ font-size: {fs(11)}; color: {c['dim']}; }}
.card {{
  background-color: {c['surface']};
  border-width: 1px;
  border-style: solid;
  border-color: {c['line_soft']};
  border-radius: {u(16)};
  padding: {u(13)};
}}
.srow {{ padding: {u(4)} {u(2)}; }}
.slabel {{ font-size: {fs(12.5)}; color: {c['text']}; }}
.statusdot {{ min-width: {u(9)}; min-height: {u(9)}; border-radius: {u(999)}; background-color: {c['late']}; }}
.statusdot.on {{ background-color: {c['done']}; }}

notebook {{ background-color: transparent; }}
notebook > header {{
  background-color: transparent;
  border-width: 0;
  min-height: 0;
  padding: {u(2)};
}}
notebook > header tab {{
  background-color: {c['surface']};
  border-width: 1px;
  border-style: solid;
  border-color: {c['line_soft']};
  border-radius: {u(999)};
  color: {c['dim']};
  padding: {u(5)} {u(14)};
  margin: {u(3)} {u(4)};
  box-shadow: none;
}}
notebook > header tab:checked {{
  background-color: {c['accent_soft']};
  border-color: {c['accent']};
  color: {c['text']};
  font-weight: 800;
}}
notebook > page {{ padding: {u(10)}; background-color: transparent;
  background-image: none; border-width: 0; box-shadow: none; }}
notebook > child {{ background-color: transparent; background-image: none;
  border-width: 0; box-shadow: none; }}

/* ---- popups (notifications) ---- */
.pop {{
  background-image: linear-gradient(165deg, {c['bg1']}, {c['bg2']});
  border-width: 1px;
  border-style: solid;
  border-color: {c['border']};
  border-radius: {u(22)};
  box-shadow: 0 {u(12)} {u(34)} {c['shadow']};
  padding: {u(13)};
}}
.ptitle {{ font-size: {fs(13.5)}; font-weight: 800; color: {c['text']}; }}
.psub {{ font-size: {fs(11)}; color: {c['dim']}; }}
"""
    return css


def font_px(base: float, scale: float) -> str:
    return f"{base * scale:.2f}"


def apply_css(cfg: dict) -> None:
    """(Re)install the CSS provider on the default screen."""
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk

    css = build_css(cfg).encode("utf-8")
    provider = getattr(apply_css, "_provider", None)
    if provider is None:
        provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        apply_css._provider = provider
    provider.load_from_data(css)


def validate(cfg: dict) -> str | None:
    """Parse check without touching the screen.  Returns an error or None."""
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    provider = Gtk.CssProvider()
    try:
        provider.load_from_data(build_css(cfg).encode("utf-8"))
    except Exception as exc:                      # GLib.Error
        return str(exc)
    return None
