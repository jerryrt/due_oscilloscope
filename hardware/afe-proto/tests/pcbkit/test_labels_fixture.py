"""Both approved boards against pcbkit.labels: every label passes validate except the findings the owner accepted, and the placer's own plan passes. Needs pcbnew (the PCB image)."""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path[:0] = [ROOT, os.path.join(ROOT, '..', 'pcbkit'), os.path.join(ROOT, 'pcbkit_regress')]
import pytest
pytest.importorskip('pcbnew')
import labels as F


@pytest.mark.parametrize('which', ['v1', 'v2'])
def test_the_approved_board_passes_and_the_plan_passes(which):
    assert F.validate_fixture(which)


def test_the_fixture_fails_when_an_accepted_finding_goes_missing_or_a_new_one_appears(monkeypatch):
    monkeypatch.setitem(F.ACCEPTED, 'v2', {})                       # J605 is no longer accepted: the fixture must fail
    assert not F.validate_fixture('v2')
    monkeypatch.setitem(F.ACCEPTED, 'v1', {'J101': 'x'})            # an accepted finding that does not occur: the fixture must fail
    assert not F.validate_fixture('v1')
