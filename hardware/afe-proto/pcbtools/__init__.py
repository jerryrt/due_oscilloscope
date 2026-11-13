"""pcbtools: shared PCB-checking package for the AFE boards. See ARRAYS.md for the interface.

Thread pinning. numpy/scipy start one BLAS/OpenMP thread per CPU they SEE, not per CPU they are ALLOWED: in a container with a CPU
quota (docker --cpus 2 on a 12-core host) the 12 threads spin against the quota and a sparse solve that takes 15 s on one thread
takes 98 s (measured in the pinned image on the v2 integrated board, tools/cap). Nothing in pcbtools gains from BLAS threads (the
kernels are sparse matrix-vector products, element-wise numpy and chunked reductions), so importing the package pins them to one,
unless the caller already chose. This works only if pcbtools is imported BEFORE numpy; a program that imports numpy first must set
the variables itself (docker/pcb/run.sh should export them for the image).
"""
import os

for _v in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(_v, '1')
