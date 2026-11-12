"""Speed and memory budgets for pcbtools steps, through x1's runner (simtools.budget.run_step). Marked slow: they run in the bench
and the gate, not in a quick run. A budget is {"peak_rss_kb": N, "wall_s": S} = the median of the measurements taken IN THE IMAGE
times a stated margin, kept in tests/golden/budgets.json under "pcbtools". No budget recorded yet = an explicit skip with the
reason (nothing is measured on a host)."""
import json
import os
import pathlib
import sys

import pytest

from simtools import budget as bg

pytestmark = pytest.mark.slow
HERE = pathlib.Path(__file__).resolve().parent
BUDGETS = pathlib.Path(os.environ.get('PCBTOOLS_BUDGETS', HERE.parents[0] / 'golden' / 'budgets.json'))


def _budget(step):
    if not BUDGETS.exists():
        pytest.skip(f'{BUDGETS.name} does not exist yet: budgets are measured in the image')
    b = json.loads(BUDGETS.read_text()).get('pcbtools', {}).get(step)
    if b is None:
        pytest.skip(f'no budget recorded for pcbtools/{step} yet: it is measured in the image')
    return b


def test_sexpr_parse_of_the_v1_board_stays_inside_its_budget():
    b = _budget('sexpr_parse')
    out = bg.run_step('sexpr_parse', [sys.executable, str(HERE / 'bench_sexpr.py'), '7'], budget=b, mem='1G', cwd=str(HERE.parents[1]))
    bg.assert_ok(out)
    assert json.loads(out.result.stdout.strip().splitlines()[-1])['step'] == 'sexpr_parse'


def test_an_impossible_budget_is_reported_as_over_budget(tmp_path):
    """the check can fail: a 1 KB / 0.001 s budget makes the same step OVER_BUDGET (and not a crash or an OOM)"""
    out = bg.run_step('sexpr_parse', [sys.executable, str(HERE / 'bench_sexpr.py'), '1'], budget={'peak_rss_kb': 1, 'wall_s': 0.001},
                      mem='1G', timeout=60, cwd=str(HERE.parents[1]))
    assert out.kind == 'OVER_BUDGET', out
