"""One time budget per marker group, and a run is judged against the sum.

A single 300 s ceiling over the board-free tier was red on two of three
benches with zero failing tests - it judged one number over a mixed set,
and a budget that fires on hardware is a budget everyone reads past.
The owner's ruling (issue #86) is three budgets, one per group, each set
at the slowest bench's reproducible figure with a margin, and a run
judged against the sum of the budgets of the groups it selected.

The numbers are pinned here so that a change is an edit to this file
and not a drift - the failure section 8 of docs/testing.md had, where a
five-minute intention became fifteen with nothing noticing.
"""

import os
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))


def _conftest():
    """conftest.py compiled from its SOURCE, never from bytecode.

    An importlib file loader trusts a cached .pyc whose recorded mtime
    and size match the file, and a mutation that keeps the size - 360 to
    300, sum to max - restored within the same second matches both. The
    first break-check of this file passed a mutation and failed a
    restore for exactly that reason. Reading the text and compiling it
    cannot be fooled that way.
    """
    path = os.path.join(HERE, "conftest.py")
    mod = types.ModuleType("due_conftest")
    mod.__file__ = path
    with open(path, encoding="utf-8") as fh:
        code = compile(fh.read(), path, "exec")
    exec(code, mod.__dict__)                                  # noqa: S102
    return mod


class _Item:
    def __init__(self, *marks):
        self._marks = set(marks)

    def get_closest_marker(self, name):
        return object() if name in self._marks else None


class _Session:
    """Just enough of a pytest session for pytest_sessionfinish."""

    def __init__(self, items, t0, no_ceiling=False):
        class _Opt:
            pass
        class _PM:
            def get_plugin(self, _name):
                return None
        class _Cfg:
            pass
        self.config = _Cfg()
        self.config.option = _Opt()
        self.config.option.no_ceiling = no_ceiling
        self.config.pluginmanager = _PM()
        self.items = items
        self.testscollected = len(items)
        self._due_t0 = t0
        self.exitstatus = 0


def test_the_three_numbers_are_the_owners_ruling():
    """Change them deliberately: this fails until the test agrees."""
    c = _conftest()
    assert c.BUDGET_S == {"gate": 360.0, "platform": 30.0, "board": None}


def test_a_board_item_is_board_even_when_platform_marked_too():
    c = _conftest()
    assert c.group_of(_Item("board", "platform")) == "board"
    assert c.group_of(_Item("platform")) == "platform"
    assert c.group_of(_Item()) == "gate"


@pytest.mark.parametrize("groups, budget", [
    ({"gate"}, 360.0),
    ({"platform"}, 30.0),
    ({"gate", "platform"}, 390.0),
    ({"board"}, None),
    ({"board", "gate"}, 360.0),
    (set(), None),
])
def test_a_run_is_judged_against_the_sum_of_what_it_selected(groups,
                                                              budget):
    c = _conftest()
    assert c.budget_for(groups) == budget


def test_over_budget_fails_the_session_and_under_does_not(monkeypatch):
    c = _conftest()
    now = 1_000_000.0
    monkeypatch.setattr(c.time, "time", lambda: now)
    monkeypatch.setattr(c, "_check_one_instrument", lambda s: None)

    over = _Session([_Item("platform")], t0=now - 31.0)
    c.pytest_sessionfinish(over, 0)
    assert over.exitstatus == 1, "31 s against a 30 s platform budget"

    under = _Session([_Item("platform")], t0=now - 29.0)
    c.pytest_sessionfinish(under, 0)
    assert under.exitstatus == 0

    # A mixed run gets the sum: 200 s is over the platform budget alone
    # and under gate + platform.
    mixed = _Session([_Item("platform"), _Item()], t0=now - 200.0)
    c.pytest_sessionfinish(mixed, 0)
    assert mixed.exitstatus == 0

    # No budget at all - board only - never fails on time.
    board = _Session([_Item("board")], t0=now - 10_000.0)
    c.pytest_sessionfinish(board, 0)
    assert board.exitstatus == 0

    # --no-ceiling is the deliberate, visible escape.
    escaped = _Session([_Item("platform")], t0=now - 31.0, no_ceiling=True)
    c.pytest_sessionfinish(escaped, 0)
    assert escaped.exitstatus == 0
