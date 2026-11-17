"""The Due's own pin names, printed on the shield's overhang bands (LR-11, owner 2026-11-13).

The shield covers the Due's silkscreen, so a user adding a jumper wire to a socket cannot read which pin it is. Each socket of the
board's edge rows gets the label the Due prints for that pin, on top silk, in the overhang band on its side of the board.

Built once and driven by the board config (see boards/v2_layout.py), so another board reuses it::

    python3 -m pcbtools.pinlabels BOARD.kicad_pcb --config v2_layout [--write [OUT]] [--check] [--list]

    pinlabels.parse_header_table(path, refs)  -> {header: {pin: Label(text, check)}}     the Due's names, parsed from the table
    pinlabels.plan_labels(b, cfg)             -> [Planned]                               where each label goes (BoardArrays + config)
    pinlabels.apply_labels(text, planned, cfg) -> text                                   the board text with the labels spliced in
    pinlabels.findings(b, cfg)                -> [str]                                   what is wrong with the board's labels (LR-11)

Config fields (all read from `cfg`, none is typed here): EDGE_SOCKETS {socket ref: Due header ref in the table}, PIN_TABLE (repo
relative path of docs/due-header-table.md), BOARD_RECT, KEEPOUTS (the bands), PIN_LABEL_H / _W / _THICK /
_EDGE_MARGIN / _PAD_GAP / _ALIASES / _POS_TOL / _FUNCTION_HEADERS, DESIGNATOR_GAP_ONE_LABEL (the gap two labels must keep), DESIGNATOR_ADVANCE and
DESIGNATOR_INK_H (the designators' boxes, which labels keep clear of), PIN_LABEL_INK {name: ink length} and PIN_LABEL_INK_H (from
INK_FILE), OVERHANG (derived from them by required_overhang).

The names are the table's "Arduino" or "Due label" column: the cell without its `*(check)*` mark and its parenthesis, mapped through
PIN_LABEL_ALIASES when the whole cell is a key ("3.3 V" -> "3V3"), else its first word; for a header in PIN_LABEL_FUNCTION_HEADERS the
word that is not the Dnn number ("D14 TX3" -> "TX3"), and a cell with no such word keeps the number, marked (check). A cell the table marks
`*(check)*` (or whose column header is marked) keeps the mark in `Label.check`, and the plan, the CLI listing and the board's data
comment carry it: the name is the table's inference, not a read-off from the Due.

Placement. Every label is turned 90 degrees (reading bottom to top, on both bands), exactly PIN_LABEL_H (1.0 mm, the board house's minimum)
high and PIN_LABEL_W wide (the stroke font's default width at that height), one size for every name. A label starts at the band's outer
edge (PIN_LABEL_EDGE_MARGIN in) and runs inward, so it may enter the copper-free strip between the band and the socket pads, never closer
than PIN_LABEL_PAD_GAP to a pad. Nothing is narrowed or shrunk: the overhang is what is sized, to fit the longest name
(required_overhang()), from lengths measured in KiCad's stroke font (measure(), stored in pinlabel_ink.json, which a test re-measures).
"""
from __future__ import annotations

# The implementation is pcbkit.pinlabels (hardware/pcbkit/pcbkit/pinlabels.py), driven by the configuration. This module is the AFE's binding of it: the Due's frame, the repository
# root for the pin table, the ink file beside this package, and the label uuid namespace the boards' existing labels were made with. Names and results are unchanged.
import importlib
import os
import sys

from pcbkit import pinlabels as _kit
from pcbkit.pinlabels import (Label, Planned, clean, parse_header_table, label_names, measure, required_overhang, planned_boxes,   # noqa: F401
                              _cells, _box, _convex_gap, _gap, _label_boxes, _fmt)

SHEET_X, SHEET_Y = 50.0, 150.0                       # Due mm -> KiCad sheet mm: x + 50, 150 - y
REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
INK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pinlabel_ink.json')
NAMESPACE = 'afe-pinlabel'


class _Cfg:
    """a board configuration with the AFE's defaults for the names the kit reads (FRAME, PIN_TABLE_ROOT, PIN_LABEL_UUID_NAMESPACE)"""
    _DEFAULTS = {'FRAME': (SHEET_X, SHEET_Y), 'PIN_TABLE_ROOT': REPO, 'PIN_LABEL_UUID_NAMESPACE': NAMESPACE}

    def __init__(self, cfg):
        object.__setattr__(self, '_cfg', cfg)

    def __getattr__(self, k):
        c = object.__getattribute__(self, '_cfg')
        if hasattr(c, k):
            return getattr(c, k)
        if k in _Cfg._DEFAULTS:
            return _Cfg._DEFAULTS[k]
        raise AttributeError(k)


def socket_pads(b, cfg):
    return _kit.socket_pads(b, _Cfg(cfg))


def label_table(cfg):
    return _kit.label_table(_Cfg(cfg))


def plan_labels(b, cfg):
    return _kit.plan_labels(b, _Cfg(cfg))


def pad_edge(b, cfg):
    return _kit.pad_edge(b, _Cfg(cfg))


def load_ink(path=INK_FILE):
    return _kit.load_ink(path)


def file_texts(text):
    return _kit.file_texts(text, (SHEET_X, SHEET_Y))


def findings(b, cfg):
    return _kit.findings(b, _Cfg(cfg))


def _sheet(x, y):
    return _kit._sheet(x, y, (SHEET_X, SHEET_Y))


def label_uuid(ref, pin):
    return _kit.label_uuid(ref, pin, NAMESPACE)


def label_block(p):
    return _kit.label_block(p, (SHEET_X, SHEET_Y), NAMESPACE)


def apply_labels(text, plan, cfg, all_ids=None):
    return _kit.apply_labels(text, plan, _Cfg(cfg), all_ids)


def main(argv):
    from . import boardio
    return _kit.main(argv, read_board=lambda p, c: boardio.read_board_retry(p),
                     load_config=lambda n: _Cfg(importlib.import_module('pcbtools.boards.' + n)), ink_file=INK_FILE)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
