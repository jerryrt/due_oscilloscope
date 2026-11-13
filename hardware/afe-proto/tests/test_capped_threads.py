"""The host path (tools/capped.sh) pins BLAS/OpenMP threads the way docker/pcb/run.sh does in the container."""
import os
import subprocess
import sys

import pytest

from simtools import capped

pytestmark = [pytest.mark.hostcap, pytest.mark.skipif(not capped.available() or capped.in_container(),
                                                      reason="needs capped.sh's systemd scope on a host")]

VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")
CODE = "import os; print(' '.join(os.environ.get(v, 'unset') for v in %r))" % (VARS,)


@pytest.mark.parametrize("cpus, want", [(2, "2"), (1.5, "1"), (0.5, "1"), (5, "5")])
def test_capped_sh_sets_floor_of_c_threads(cpus, want):
    r = capped.run([sys.executable, "-c", CODE], mem="500M", timeout=60, cpus=cpus)
    assert r.returncode == 0 and r.stdout.split() == [want] * 4, (cpus, r.stdout, r.stderr[-200:])


def test_capped_sh_defaults_to_nproc_and_overrides_an_inherited_value():
    env = dict(os.environ, OMP_NUM_THREADS="99")
    r = capped.run([sys.executable, "-c", CODE], mem="500M", timeout=60, env=env)
    assert r.stdout.split() == [subprocess.run(["nproc"], capture_output=True, text=True).stdout.strip()] * 4, r.stdout
