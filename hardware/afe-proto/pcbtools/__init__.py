"""pcbtools: shared PCB-checking package for the AFE boards. See ARRAYS.md for the interface.

No import-time side effects here. In particular the package does not touch BLAS/OpenMP threads: numpy/scipy start one thread per CPU
they SEE, and in a container with a CPU quota (docker --cpus 2 on a 12-core host) those threads spin against the quota (measured:
a 15 s sparse solve took 98 s). The container's launcher (docker/pcb/run.sh) exports the thread variables equal to the container's
--cpus; tests/pcbtools/test_threads.py holds that.
"""

# pcbkit (hardware/pcbkit/pcbkit) is the general half of this package's tools. It is found beside this tree (or at PCBKIT_ROOT) and
# registered as the module `pcbkit` without touching sys.path: a board config must leave sys.path as it found it (test_board_isolation).
import importlib.util as _ilu
import os as _os
import sys as _sys

if 'pcbkit' not in _sys.modules and _ilu.find_spec('pcbkit') is None:
    _kit = _os.path.join(_os.environ.get('PCBKIT_ROOT') or _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), 'pcbkit'), 'pcbkit')
    if _os.path.isfile(_os.path.join(_kit, '__init__.py')):
        _spec = _ilu.spec_from_file_location('pcbkit', _os.path.join(_kit, '__init__.py'), submodule_search_locations=[_kit])
        _mod = _ilu.module_from_spec(_spec)
        _sys.modules['pcbkit'] = _mod
        _spec.loader.exec_module(_mod)
