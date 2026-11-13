#!/usr/bin/env python3
"""Put a Specctra DSN into a canonical order, so the same board always gives the same design file.

    dsn_canon.py IN.dsn OUT.dsn

pcbnew's ExportSpecctraDSN lists things in an order that changes from one export of the same board to the next:
the `place` lines of a component, the `net` blocks of the network, the pins inside a net, and the file's own
path on the first line. Freerouting routes in input order, so an unstable order is unstable routing, and routed
results cannot be reproduced or compared. This sorts exactly those and nothing else:

    * the `(place ...)` children of each `(component ...)` in `(placement ...)`, by reference designator;
    * the `(net ...)` children of `(network ...)`, by net name, and the pin list of each net;
    * the first line, `(pcb <path>`, to the file's base name.

Everything else (structure, library, layer order, padstacks, wiring) is copied byte for byte: its order carries
meaning or is already stable. The scanner is quote-aware and works on the text, so the exporter's formatting
survives. A DSN with no placement or no network is refused, not copied through: a silent no-op would leave the
unreproducibility it exists to remove.
"""
import os
import re
import sys


def _scan(text, i):
    """Index just past the parenthesised expression that starts at text[i] == '('. Quotes (") hide parentheses."""
    depth, inq = 0, False
    n = len(text)
    while i < n:
        c = text[i]
        if inq:
            if c == '"':
                inq = False
        elif c == '"':
            inq = True
        elif c == "(":
            if text.startswith("(string_quote", i):          # `(string_quote ")` declares the quote character
                j = text.index(")", i)
                if depth == 0:
                    return j + 1
                i = j + 1
                continue
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced parentheses in the DSN")


def _children(text, start, end):
    """(span start, span end) of each direct child expression of the list whose body is text[start:end]."""
    out, i = [], start
    while i < end:
        if text[i] == "(":
            j = _scan(text, i)
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def _sort_run(text, body_start, body_end, key, only):
    """Reorder the child expressions of a list body that satisfy `only`, in place among themselves, keeping the
    text between them (indentation, newlines) where it is. Returns the new text for [body_start:body_end]."""
    kids = _children(text, body_start, body_end)
    picked = [(a, b) for a, b in kids if only(text[a:b])]
    if len(picked) < 2:
        return text[body_start:body_end]
    items = sorted((text[a:b] for a, b in picked), key=key)
    out, pos, k = [], body_start, 0
    for a, b in kids:
        if (a, b) in picked:
            out += [text[pos:a], items[k]]
            k += 1
            pos = b
    out.append(text[pos:body_end])
    return "".join(out)


def _head(expr):
    m = re.match(r"\(\s*([^\s()]+)\s*([^\s()]*)", expr)
    return m.group(1), m.group(2)


def _sort_pins(expr):
    m = re.match(r"(\(\s*pins\s*)(.*?)(\s*\))\Z", expr, re.S)
    if not m:
        return expr
    return m.group(1) + " ".join(sorted(m.group(2).split())) + m.group(3)


def _sort_net(expr):
    """The pin list inside one (net ...) block, sorted."""
    inner_start = expr.index("(", 1) if "(" in expr[1:] else None
    if inner_start is None:
        return expr
    out, pos = [], 0
    for a, b in _children(expr, 1, len(expr) - 1):
        if _head(expr[a:b])[0] == "pins":
            out += [expr[pos:a], _sort_pins(expr[a:b])]
            pos = b
    out.append(expr[pos:])
    return "".join(out)


def _block(text, name):
    """(start, end) of the first top-level-under-(pcb) child named `name`."""
    top = _scan(text, text.index("("))
    for a, b in _children(text, text.index("(") + 1, top - 1):
        if _head(text[a:b])[0] == name:
            return a, b
    return None


def _rewrite_children(text, start, end, wanted, fn):
    """Apply fn to every direct child expression whose head is in `wanted`, inside the list body text[start:end]."""
    out, pos = [], start
    for a, b in _children(text, start, end):
        if _head(text[a:b])[0] in wanted:
            out += [text[pos:a], fn(text[a:b])]
            pos = b
    out.append(text[pos:end])
    return "".join(out)


def _in_block(text, name, fn):
    """Replace the (name ...) block under (pcb ...) by fn(block text)."""
    blk = _block(text, name)
    if blk is None:
        raise ValueError(f"the DSN has no {name} block: nothing to canonicalise")
    a, b = blk
    return text[:a] + fn(text[a:b]) + text[b:]


def _canon_network(blk):
    body_a, body_b = len("(network"), len(blk) - 1
    sorted_nets = _sort_run(blk, body_a, body_b, lambda e: _head(e)[1], lambda e: _head(e)[0] == "net")
    blk = blk[:body_a] + sorted_nets + blk[body_b:]
    return blk[:body_a] + _rewrite_children(blk, body_a, len(blk) - 1, {"net"}, _sort_net) + blk[-1]


def _canon_component(comp):
    kw = "(component"
    name = _head(comp)[1]
    body_a = comp.index(name, len(kw)) + len(name)
    return comp[:body_a] + _sort_run(comp, body_a, len(comp) - 1, lambda e: _head(e)[1],
                                     lambda e: _head(e)[0] == "place") + comp[-1]


def _canon_placement(blk):
    body_a = len("(placement")
    return blk[:body_a] + _rewrite_children(blk, body_a, len(blk) - 1, {"component"}, _canon_component) + blk[-1]


def canonicalise(text, name="design.dsn"):
    """The DSN text in canonical order (see the module docstring)."""
    text = _in_block(text, "network", _canon_network)
    text = _in_block(text, "placement", _canon_placement)
    return re.sub(r"\A\(pcb [^\n]*", f"(pcb {name}", text, count=1)


def main(argv):
    if len(argv) != 2:
        print("usage: dsn_canon.py IN.dsn OUT.dsn", file=sys.stderr)
        return 2
    src, dst = argv
    with open(src, encoding="utf-8") as f:
        text = f.read()
    try:
        out = canonicalise(text, os.path.basename(src))
    except ValueError as e:
        print(f"dsn_canon.py: {e}", file=sys.stderr)
        return 3
    with open(dst, "w", encoding="utf-8") as f:
        f.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
