"""The host path (tools/capped.sh) pins BLAS/OpenMP threads the way docker/pcb/run.sh does in the container."""
import os
import subprocess
import sys

import pytest

from simtools import capped

pytestmark = [pytest.mark.hostcap, pytest.mark.skipif(not capped.available() or capped.in_container(),
                                                      reason="needs capped.sh's systemd scope on a host")]

VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")
LIMITS = ("OMP_THREAD_LIMIT",)


def clean_env(**extra):
    """The caller's environment with every thread variable removed, then `extra`: a test must not inherit what the
    shell that launched it exported (kvm_02's run had OMP_NUM_THREADS=2 and OPENBLAS_NUM_THREADS=2)."""
    env = {k: v for k, v in os.environ.items() if k not in VARS + LIMITS}
    env.update(extra)
    return env
CODE = "import os; print(' '.join(os.environ.get(v, 'unset') for v in %r))" % (VARS,)


@pytest.mark.parametrize("cpus, want", [(2, "2"), (1.5, "1"), (0.5, "1"), (5, "5")])
def test_capped_sh_sets_floor_of_c_threads(cpus, want):
    r = capped.run([sys.executable, "-c", CODE], mem="500M", timeout=60, cpus=cpus, env=clean_env())
    assert r.returncode == 0 and r.stdout.split() == [want] * 4, (cpus, r.stdout, r.stderr[-200:])


def test_capped_sh_defaults_to_nproc_and_overrides_an_inherited_value():
    env = clean_env(OMP_NUM_THREADS="99", OPENBLAS_NUM_THREADS="98")
    r = capped.run([sys.executable, "-c", CODE], mem="500M", timeout=60, env=env)
    # nproc itself honours OMP_NUM_THREADS, so the expected figure is asked with it removed: a test run from a
    # shell that exports OMP_NUM_THREADS=2 (kvm_02's was) must not expect 2
    clean = subprocess.run(["nproc"], capture_output=True, text=True, env=clean_env()).stdout.strip()
    assert r.stdout.split() == [clean] * 4, r.stdout


def test_the_default_does_not_depend_on_the_callers_thread_exports():
    """The same default whatever OMP_NUM_THREADS the caller exported: the value capped.sh picks is nproc's."""
    outs = set()
    for omp in (None, "1", "2", "64"):
        env = clean_env(**({"OMP_NUM_THREADS": omp, "OPENBLAS_NUM_THREADS": omp} if omp else {}))
        outs.add(capped.run([sys.executable, "-c", CODE], mem="500M", timeout=60, env=env).stdout.strip())
    assert len(outs) == 1, outs
