"""One-shot helper: wrap UI string literals in tr(...).

Uses the AST so multi-line and concatenated literals are wrapped whole, and
skips anything already wrapped, empty, or built at run time.

    python3 tools/i18n_wrap.py taskwidget/widget.py ...

Note: CPython reports ``col_offset`` in UTF-8 *bytes*, so all editing here is
done on bytes — mixing in character offsets corrupts any line containing a
non-ASCII character.
"""

from __future__ import annotations

import ast
import re
import sys

METHODS = {
    "label", "button", "set_placeholder_text", "set_tooltip_text",
    "set_label", "set_text", "set_title",
}
#: method name -> argument indexes that carry user-visible text
EXTRA = {
    "_row": (0, 2),                       # (label, control, hint)
    "icon_button": (2,),                  # (icon, css, tooltip)
    "button": (0, 2),                     # (text, css, tooltip)
    "new": (0, 3, 4),                     # FileChooserNative(title,…,ok,cancel)
}
SKIP = re.compile(rb"^\s*$|[{}]")


def wrap(path: str) -> tuple[int, list[str]]:
    raw = open(path, "rb").read()
    text = raw.decode("utf-8")
    tree = ast.parse(text)

    line_starts = [0]
    for line in raw.splitlines(keepends=True):
        line_starts.append(line_starts[-1] + len(line))

    wanted = []
    notes: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func, args = node.func, node.args
        name = None
        if isinstance(func, ast.Attribute) and func.attr in METHODS:
            name = func.attr
        elif isinstance(func, ast.Attribute) and func.attr in EXTRA:
            if isinstance(func.value, ast.Attribute) and \
                    func.value.attr == "FileChooserNative":
                name = func.attr
            elif func.attr in ("_row", "icon_button"):
                name = func.attr
        elif isinstance(func, ast.Name) and func.id in ("label", "button"):
            name = func.id
        if name is None or not args:
            continue
        indexes = EXTRA.get(name, (0,))
        for idx in indexes:
            if idx >= len(args):
                continue
            arg = args[idx]
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                continue
            if arg.end_lineno is None:
                continue
            seg = raw[line_starts[arg.lineno - 1] + arg.col_offset:
                      line_starts[arg.end_lineno - 1] + arg.end_col_offset]
            if SKIP.search(seg) or seg[:2] in (b'f"', b"f'", b'b"', b"r'",
                                               b"rb", b"fr") or \
                    seg.startswith(b"tr("):
                if b"{" in seg:
                    notes.append(f"  placeholder: {seg[:70]!r}")
                continue
            wanted.append((seg,
                           line_starts[arg.lineno - 1] + arg.col_offset,
                           line_starts[arg.end_lineno - 1] + arg.end_col_offset))
            if b"{" in seg:
                notes.append(f"  placeholder (skipped): {seg[:70]!r}")

    # de-duplicate identical spans, edit from the back
    seen = set()
    count = 0
    for seg, start, end in sorted(wanted, key=lambda t: t[1], reverse=True):
        if (start, end) in seen:
            continue
        seen.add((start, end))
        if raw[start:end] != seg:
            continue
        raw = raw[:start] + b"tr(" + seg + b")" + raw[end:]
        count += 1

    if count and b"from .i18n import tr" not in raw:
        m = re.search(rb"\n(from \.[^\n]*import [^\n]*\n)", raw)
        if m:
            raw = raw[:m.end(1)] + b"from .i18n import tr\n" + raw[m.end(1):]

    open(path, "wb").write(raw)
    return count, notes


if __name__ == "__main__":
    for p in sys.argv[1:]:
        n, notes = wrap(p)
        print(f"{p}: wrapped {n}")
        for note in notes:
            print(note)
