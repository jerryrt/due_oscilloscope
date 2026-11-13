"""pcbtools: shared PCB-checking package for the AFE boards. See ARRAYS.md for the interface.

No import-time side effects here. In particular the package does not touch BLAS/OpenMP threads: numpy/scipy start one thread per CPU
they SEE, and in a container with a CPU quota (docker --cpus 2 on a 12-core host) those threads spin against the quota (measured:
a 15 s sparse solve took 98 s). The container's launcher (docker/pcb/run.sh) exports the thread variables equal to the container's
--cpus; tests/pcbtools/test_threads.py holds that.
"""
