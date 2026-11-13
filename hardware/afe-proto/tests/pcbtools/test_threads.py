"""Inside the pinned image the BLAS/OpenMP thread variables equal the container's CPU allowance (docker/pcb/run.sh exports them): a
12-thread pool under a 2-CPU quota took 98 s on a solve that needs 15 s on one thread. pcbtools itself sets nothing (no import-time
side effects); these tests read the environment the container gives every process.

Outside the image the container's facts do not exist and the tests skip with that reason; the gate runs them inside."""
import math
import os
import pathlib

import pytest

VARS = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS')
IN_IMAGE = bool(os.environ.get('DUE_PCB_IMAGE_CONTENT'))


def _cpus():
    """the container's CPU allowance from the cgroup (cpu.max: '<quota> <period>' or 'max <period>'), or None when unlimited"""
    p = pathlib.Path('/sys/fs/cgroup/cpu.max')
    if not p.exists():
        return None
    quota, period = p.read_text().split()[:2]
    return None if quota == 'max' else math.ceil(int(quota) / int(period))


needs_image = pytest.mark.skipif(not IN_IMAGE, reason='the thread allowance is a property of the container: runs in the image (docker/pcb/run.sh)')


@needs_image
def test_the_thread_variables_are_set_in_the_image():
    missing = [v for v in VARS if not os.environ.get(v)]
    assert not missing, f'{missing} unset: docker/pcb/run.sh must export them equal to the container --cpus'


@needs_image
def test_the_thread_variables_equal_the_container_cpu_allowance():
    cpus = _cpus()
    if cpus is None:
        pytest.skip('this container has no cpu quota (cgroup cpu.max is max)')
    got = {v: os.environ.get(v) for v in VARS}
    assert all(x == str(cpus) for x in got.values()), f'cgroup allows {cpus} CPUs, environment says {got}'


def test_the_package_sets_no_environment_on_import():
    """the control for the above and the rule that replaced the import-time pin: importing pcbtools changes nothing"""
    import subprocess
    import sys
    root = pathlib.Path(__file__).resolve().parents[2]
    env = {k: v for k, v in os.environ.items() if k not in VARS + ('MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')}
    code = "import pcbtools, os; print([os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')])"
    out = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True, env=env, cwd=str(root)).stdout.strip()
    assert out == "[None, None, None]", out
