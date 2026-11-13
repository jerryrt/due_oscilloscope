"""Gate-3 tables: the v2 table is complete, the v1 template loads with every field present and its TODO fields are reported by name, and
the engine refuses an incomplete table or config by naming the field rather than crashing. No pcbnew: the checks run before any board is read."""
import os
import pathlib
import types

import pytest

from pcbtools.gate3 import REQUIRED, check_config, check_table
from pcbtools.gate3 import __main__ as cli
from pcbtools.gate3.table import TODO_MARK, config_fields
from pcbtools.boards import gate3_v1 as V1
from pcbtools.boards import gate3_v2 as V2

AFE = pathlib.Path(__file__).resolve().parents[2]


def clone(mod, **over):
    ns = types.SimpleNamespace(**{k: v for k, v in vars(mod).items() if not k.startswith('_')})
    for k, v in over.items():
        setattr(ns, k, v)
    return ns


def test_v2_table_is_complete():
    assert check_table(V2) == []
    assert len(REQUIRED) > 80                                        # a floor: the field list was read, not an empty tuple


def test_every_field_is_required_or_named_optional():
    """a field the table defines that the engine never reads would be a second home for a fact: only these are not in REQUIRED"""
    extra = {k for k in vars(V2) if k.isupper() and k not in REQUIRED}
    assert extra == {'AFE', 'EVIDENCE_DERIVED'}


def test_v1_template_has_every_field_and_reports_its_todos_by_name():
    problems = check_table(V1)
    assert [p for p in problems if p.startswith('missing field')] == []              # every field present
    todo = [p for p in problems if p.startswith('TODO in ')]
    assert todo and all(p.split(':')[0][len('TODO in '):].split('[')[0] in REQUIRED for p in todo)       # each names a real field
    names = {p.split(':')[0][len('TODO in '):].split('[')[0] for p in todo}
    assert {'BRIDGE_REF_PATTERN', 'BRIDGES_SOURCE', 'PROOF', 'EVIDENCE_DATA', 'BOM_DATA_DIR'} <= names       # the fields only kvm_01 knows
    assert 'BOARD' not in names and 'BRIDGE_PART' not in names                                              # filled from the repo


def test_v1_template_board_and_project_exist():
    root = AFE.parents[1]
    assert (root / V1.BOARD).is_file() and (root / V1.PROJECT).is_file()


def test_a_missing_field_is_named_and_a_complete_table_is_not_flagged():
    gone = clone(V2)
    del gone.GAPS
    assert check_table(gone) == ['missing field GAPS']
    assert check_table(clone(V2)) == []                                                # the control: the clone alone is clean


def test_a_todo_inside_a_nested_value_is_found_with_its_path():
    t = clone(V2, PROOF=dict(V2.PROOF, source=TODO_MARK + 'kvm_01): the source pad'))
    assert check_table(t) == ["TODO in PROOF['source']: TODO(kvm_01): the source pad"]


def test_none_is_a_legal_value_for_an_optional_row():
    assert check_table(clone(V2, DEV_FOREIGN=None)) == []


def test_cli_refuses_an_incomplete_table_naming_the_fields(capsys):
    rc = cli.main(['--config', 'v2_layout', '--table', 'gate3_v1', '--out', os.devnull])
    err = capsys.readouterr().err
    assert rc == 2 and 'TODO in BRIDGE_REF_PATTERN' in err and 'TODO in PROOF' in err


def test_cli_check_table_accepts_the_v2_table(capsys):
    assert cli.main(['--config', 'v2_layout', '--table', 'gate3_v2', '--out', os.devnull, '--check-table']) == 0
    assert 'no TODO markers' in capsys.readouterr().out


def test_cli_names_a_config_field_the_table_makes_it_read(capsys, monkeypatch):
    """a config without OVERHANG is reported before any board is read"""
    import pcbtools.boards.v2_layout as cfg
    short = types.SimpleNamespace(**{k: v for k, v in vars(cfg).items() if k != 'OVERHANG'})
    assert check_config(cfg, V2) == [] and check_config(short, V2) == ['config lacks OVERHANG']
    monkeypatch.setattr('pcbtools.gate3.table.load_module', lambda spec, package='pcbtools.boards': V2 if spec == 'gate3_v2' else short)
    rc = cli.main(['--config', 'x', '--table', 'gate3_v2', '--out', os.devnull])
    assert rc == 2 and 'config lacks OVERHANG' in capsys.readouterr().err


def test_config_fields_follow_the_table():
    assert {'GND', 'KEEPOUT', 'HOP_MAX', 'DECOUP_MAX', 'CHANNELS', 'VREF_NET', 'DESIGNATOR_GAP_MIN'} <= set(config_fields(V2))
    assert 'DESIGNATOR_GAP_MIN' not in config_fields(V1)                              # v1's table quotes only the hop limits
