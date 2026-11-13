"""Loading and checking a gate-3 table (`pcbtools/boards/gate3_<board>.py`): a module of named fields and no logic.

`check_table(T)` returns the problems as text, naming the field: a required field the table does not define, and any field whose value
(searched through lists, tuples and dicts) carries a `TODO(` marker, which a table writer leaves on what only another person can fill.
The CLI refuses to run while there are problems and prints them; nothing here raises on a bad table.
"""
from __future__ import annotations

import datetime
import importlib
import importlib.util
import json
import os

TODO_MARK = 'TODO('

# every field the engine reads, grouped as README.md groups them
REQUIRED = (
    # identity and files
    'TITLE', 'GENERATED_BY', 'BOARD', 'PROJECT', 'RENDER_DIR', 'RENDERS', 'RENDER_LINK_PREFIX', 'RENDER_HINT', 'DUE_ORIGIN', 'RULE_DOC',
    'SECTION_SOURCES',
    # LR table
    'LR_HEADING', 'LR_INTRO', 'LR_DOC_ROWS', 'LR_RENAMES', 'LR_SUBCHECKS', 'DRC_ROW',
    # DRC
    'DRC_DOCUMENTED', 'DRC_DOCUMENTED_LABEL', 'DRC_DOCUMENTED_NOTE', 'RULE_DIFF_TEXT',
    # bridges
    'BRIDGE_REF_PATTERN', 'BRIDGES_SOURCE', 'NET_CLASS_FIELDS', 'D24_ROW_PATTERN', 'D24_QUOTE_PATTERN', 'D24_FOUND', 'D24_MISSING', 'BRIDGE_ACCEPT',
    # deviations
    'POWER_CAPS', 'POWER_CAPS_CAPTION', 'CFG_QUOTED', 'CFG_FOREIGN_WAIVED', 'CFG_GAP_WAIVED', 'CFG_GAP_MIN', 'CFG_GAP_ONE_LABEL',
    'DEV_COURT', 'DEV_POWER', 'DEV_FOREIGN', 'DEV_FOREIGN_EMPTY', 'DEV_GAP', 'DEV_OUTLINE', 'DEV_EDGE', 'DEV_PROOF', 'DEV_PROOF_JOINED', 'DEV_PROOF_NOT',
    'MC1_COMMIT', 'MC1_PATTERN', 'MC1_FOUND', 'MC1_MISSING', 'MARGINS',
    # connectivity proof
    'PROOF', 'PROOF_PATH_ORDER', 'PROOF_HEADING', 'PROOF_INTRO', 'PROOF_COPPER', 'PROOF_RESULT', 'PROOF_PATH_HEAD', 'PROOF_HISTORY', 'PROOF_UPSTREAM',
    'PROOF_UPSTREAM_NONE', 'PROOF_DRC', 'PROOF_RULE',
    # evidence rows
    'EVIDENCE_HEADING', 'EVIDENCE_DATA', 'EVIDENCE', 
    # BOM
    'BOM_ENGINE', 'BOM_DATA_DIR', 'BOM_EXTRA_CSV', 'BOARD_COUNTS', 'REPORT_BOARDS', 'TARGET_BOARDS', 'OWNER_FITTED_LCSC', 'BRIDGE_PART', 'WATCH_PACKAGES',
    'BOM_INTRO', 'BOM_UNIT_NOTE', 'BOM_RECONCILE_NOTE', 'BRIDGE_PART_TEXT', 'BOM_PCB_NOTE', 'COST_TARGET', 'COST_TARGET_RESULT', 'GAPS',
)


def _todo_paths(name, v, out):
    if isinstance(v, str):
        if TODO_MARK in v:
            out.append(f'{name}: {v[:100]}')
    elif isinstance(v, dict):
        for k, x in v.items():
            _todo_paths(f'{name}[{k!r}]', x, out)
        for k in v:
            if isinstance(k, str) and TODO_MARK in k:
                out.append(f'{name}: key {k[:60]}')
    elif isinstance(v, (list, tuple)):
        for i, x in enumerate(v):
            _todo_paths(f'{name}[{i}]', x, out)


def check_table(T):
    """problems of a table, each naming its field: ['missing field NAME', 'NAME: TODO(...) text', ...]; empty when the table is complete"""
    out = []
    for name in REQUIRED:
        if not hasattr(T, name):
            out.append(f'missing field {name}')
        else:
            todo = []
            _todo_paths(name, getattr(T, name), todo)
            out.extend('TODO in ' + t for t in todo)
    return out


def load_module(spec, package='pcbtools.boards'):
    """a board config or table by name (`gate3_v2` -> pcbtools.boards.gate3_v2) or by path to a .py file"""
    if spec.endswith('.py') or os.sep in spec:
        sp = importlib.util.spec_from_file_location('gate3_table_' + os.path.basename(spec)[:-3], spec)
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        return m
    return importlib.import_module(f'{package}.{spec}')


# config fields the engine reads whatever the table says (the rest follow from the table: margin limits, renamed rows, classes, quoted fields)
CONFIG_FIXED = ('GND', 'BOARD_SETUP', 'OVERHANG', 'BOARD_MAX_MM', 'BAND_NAME', 'KEEPOUTS')


def config_fields(T):
    """the board-config field names a table makes the engine read"""
    need = list(CONFIG_FIXED)
    need += [m['limit'] for m in getattr(T, 'MARGINS', ())]
    need += [f for _, _, f in getattr(T, 'LR_RENAMES', ())]
    need += list(getattr(T, 'CFG_QUOTED', ()))
    spec = getattr(T, 'NET_CLASS_FIELDS', None) or {}
    for v in spec.values():
        need += [x.split('.')[0] for x in ([v] if isinstance(v, str) else v)]
    return list(dict.fromkeys(need))


def check_config(cfg, T):
    """['config lacks NAME', ...]: the fields the engine would read from `cfg` that it does not define; empty when complete"""
    return [f'config lacks {n}' for n in config_fields(T) if not hasattr(cfg, n)]
