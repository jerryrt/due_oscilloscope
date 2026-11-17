import os
import pathlib
import sys

import pytest

# hardware/pcbkit: `import pcbkit`
sys.path.insert(0, os.environ.get('PCBKIT_ROOT') or str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.append('/usr/lib/python3/dist-packages')       # the image's pcbnew


def _pcbnew():
    try:
        import pcbnew
        return pcbnew
    except ImportError as e:
        if os.environ.get('PCBKIT_REQUIRE_PCBNEW') == '1':
            pytest.fail(f'PCBKIT_REQUIRE_PCBNEW=1 but pcbnew does not import: {e}')
        pytest.skip('pcbnew is not importable here')


@pytest.fixture(scope='session')
def pcbnew_mod():
    return _pcbnew()
