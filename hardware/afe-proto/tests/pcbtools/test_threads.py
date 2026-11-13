"""pcbtools pins BLAS/OpenMP threads to one (see pcbtools/__init__.py) so a container CPU quota cannot turn a 15 s solve into 98 s."""
import os
import subprocess
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _env_after_import(extra_env, first):
    code = f"import {first}; import os; print([os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')])"
    env = {k: v for k, v in os.environ.items() if k not in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')}
    env.update(extra_env)
    env['PYTHONPATH'] = str(ROOT)
    return subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True, env=env, cwd=str(ROOT)).stdout.strip()


def test_importing_the_package_pins_one_thread():
    assert _env_after_import({}, 'pcbtools') == "['1', '1', '1']"


def test_a_caller_choice_is_respected():
    assert _env_after_import({'OPENBLAS_NUM_THREADS': '3'}, 'pcbtools') == "['3', '1', '1']"


def test_the_control_without_the_package_leaves_them_unset():
    """the arm that can fail: if the package stopped pinning, test 1 would see None (and this one proves the probe reads unset as None)"""
    assert _env_after_import({}, 'os') == "[None, None, None]"
