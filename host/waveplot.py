"""Draw a captured waveform ourselves, from the samples.

The instrument's own screenshot is worth having - it carries the
graticule, the trigger marker and the scale factors, and it is what a
person actually saw. What it is not is the data: a DS1102E screen is
320x234 pixels rendered from a **600-point** screen record, while the
acquisition memory behind it holds **1,048,576** points at 10 ns. Three
orders of magnitude of the record never reach the picture.

So this draws the other one. Same acquisition, every sample, and the
same numbers that produce the measurement produce the image - which
means a feature in a table can be pointed at in a plot without anyone
having to trust that the two came from the same moment.

SVG rather than a raster, because it stays sharp at any zoom and because
a scope trace is lines: the whole file is one polyline plus a graticule.

**Min/max per column, never subsampling.** A million points cannot be
drawn into a thousand pixels one-to-one, and taking every thousandth
sample would step straight over exactly the brief excursion this project
keeps hunting. Each column instead carries the minimum and maximum of
the samples that fall in it, so a one-sample spike is a full-height
line rather than a sample nobody picked.
"""
from __future__ import annotations

import html


def minmax(v, columns):
    """(col, lo, hi) per pixel column, covering every sample."""
    n = len(v)
    if n == 0:
        return []
    columns = max(1, min(columns, n))
    out = []
    for c in range(columns):
        a = c * n // columns
        b = max(a + 1, (c + 1) * n // columns)
        chunk = v[a:b]
        out.append((c, min(chunk), max(chunk)))
    return out


def render_svg(v, dt, *, width=1200, height=420, title="",
               subtitle="", volts_per_code=None, pad_frac=0.08,
               marks=()):
    """One capture as an SVG string.

    `marks` are (seconds, label) pairs drawn as vertical rules - for
    saying "the reload is here" on the picture rather than only in a
    table.
    """
    if not v:
        return "<svg xmlns='http://www.w3.org/2000/svg'/>"
    n = len(v)
    span_s = n * dt
    lo, hi = min(v), max(v)
    if hi - lo < 1e-9:
        lo, hi = lo - 5e-4, hi + 5e-4
    pad = (hi - lo) * pad_frac
    lo, hi = lo - pad, hi + pad

    left, right, top, bottom = 74, 16, 34, 40
    pw = width - left - right
    ph = height - top - bottom

    def y_of(val):
        return top + ph * (hi - val) / (hi - lo)

    cols = minmax(v, pw)
    # One polyline down the column minima and back along the maxima
    # closes the envelope, so a spike shows as height rather than as a
    # sample that happened to be sampled.
    down = " ".join(f"{left + c},{y_of(mn):.2f}" for c, mn, _ in cols)
    up = " ".join(f"{left + c},{y_of(mx):.2f}"
                  for c, _, mx in reversed(cols))

    grid = []
    for i in range(11):
        x = left + pw * i / 10.0
        grid.append(f"<line x1='{x:.1f}' y1='{top}' x2='{x:.1f}' "
                    f"y2='{top + ph}' class='g'/>")
        t = span_s * i / 10.0
        grid.append(f"<text x='{x:.1f}' y='{top + ph + 15}' "
                    f"class='ax' text-anchor='middle'>"
                    f"{_time(t)}</text>")
    for i in range(9):
        y = top + ph * i / 8.0
        grid.append(f"<line x1='{left}' y1='{y:.1f}' x2='{left + pw}' "
                    f"y2='{y:.1f}' class='g'/>")
        val = hi - (hi - lo) * i / 8.0
        lbl = f"{val * 1000:.1f} mV"
        if volts_per_code:
            lbl = f"{val * 1000:.1f} mV"
        grid.append(f"<text x='{left - 8}' y='{y + 4:.1f}' class='ax' "
                    f"text-anchor='end'>{lbl}</text>")

    rules = []
    for at_s, label in marks:
        if not 0 <= at_s <= span_s:
            continue
        x = left + pw * at_s / span_s
        rules.append(f"<line x1='{x:.1f}' y1='{top}' x2='{x:.1f}' "
                     f"y2='{top + ph}' class='mk'/>")
        rules.append(f"<text x='{x + 4:.1f}' y='{top + 12}' "
                     f"class='mkl'>{html.escape(label)}</text>")

    code_note = ""
    if volts_per_code:
        code_note = (f" &middot; {(hi - lo) / volts_per_code:,.0f} DAC codes "
                     f"across")
    sub = (f"{n:,} samples &middot; {dt * 1e9:.0f} ns/sample &middot; "
           f"{_time(span_s)} span{code_note}"
           + (f" &middot; {html.escape(subtitle)}" if subtitle else ""))

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img">
<style>
.bg{{fill:#0B0F0E}} .g{{stroke:#25302C;stroke-width:1}}
.tr{{fill:#D9A400;fill-opacity:.9;stroke:#F0BC1A;stroke-width:.6}}
.ax{{fill:#8D9A96;font:11px ui-monospace,Menlo,monospace}}
.ti{{fill:#E4EAE7;font:600 13px Archivo,Helvetica,sans-serif}}
.su{{fill:#8D9A96;font:11px ui-monospace,Menlo,monospace}}
.mk{{stroke:#5FA8DE;stroke-width:1;stroke-dasharray:4 3}}
.mkl{{fill:#5FA8DE;font:10px ui-monospace,Menlo,monospace}}
</style>
<rect class="bg" x="0" y="0" width="{width}" height="{height}"/>
{''.join(grid)}
<polygon class="tr" points="{down} {up}"/>
{''.join(rules)}
<text class="ti" x="{left}" y="16">{html.escape(title)}</text>
<text class="su" x="{left}" y="{height - 10}">{sub}</text>
</svg>"""


def _time(t):
    a = abs(t)
    if a >= 1e-3:
        return f"{t * 1e3:.3g} ms"
    if a >= 1e-6:
        return f"{t * 1e6:.3g} us"
    return f"{t * 1e9:.3g} ns"
