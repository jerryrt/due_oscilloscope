"""Guard: when the environment claims pcbnew, the pcbnew-marked group must really have run (not skipped, not deselected
to nothing). Runs last (conftest orders `guard_last` items at the end)."""
import pytest

pytestmark = [pytest.mark.pcbnew, pytest.mark.guard_last]


def test_pcbnew_group_actually_ran(pcbnew_required, request):
    RAN = request.config._pcbtools_ran
    assert RAN['pcbnew_selected'] > 0, 'no pcbnew-marked test was collected: the marker group is empty'
    assert RAN['pcbnew_passed'] == RAN['pcbnew_selected'], (
        f"{RAN['pcbnew_passed']} of {RAN['pcbnew_selected']} pcbnew-marked tests passed: the rest were skipped, "
        'deselected after collection, or failed')
