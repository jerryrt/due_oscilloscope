#!/bin/bash
# capped.sh [-m MEM] [-t SECONDS] [-c CPUS] command ...
#
# Run ONE heavy job under a hard memory cap and a wall-clock limit, and print its peak memory.
#   -m MEM      memory cap (systemd size: 512M, 2G ...), default 2G; swap is off (MemorySwapMax=0), so the kernel kills the job
#               at the cap instead of the machine swapping or invoking the global OOM killer
#   -t SECONDS  wall-clock limit, default 300 (timeout -k 5)
#   -c CPUS     thread count for BLAS/OpenMP (OMP/OPENBLAS/MKL/NUMEXPR_NUM_THREADS = floor(CPUS), min 1), default nproc
# Exit status: the command's own; 137 = killed (by the memory cap or after -k); 124 = the time limit.
# One summary line goes to stderr when the job ends:  capped: peak_rss_kb=<n> wall_s=<s> exit=<n> cap=<MEM> limit_s=<T>
# (peak RSS is the largest resident set of the job's processes as /usr/bin/time reports it).
# House rules (docs of the pcbtools work): at most two heavy jobs at once, never a process pool, every loop bounded.
M=2G; T=300; C=
while getopts "m:t:c:" o; do
  case $o in m) M=$OPTARG;; t) T=$OPTARG;; c) C=$OPTARG;; *) echo "usage: capped.sh [-m MEM] [-t SECONDS] [-c CPUS] cmd..." >&2; exit 2;; esac
done
shift $((OPTIND-1))
# BLAS/OpenMP threads = floor(-c, or nproc), minimum 1, exactly as docker/pcb/run.sh sets them in the container.
# numpy and scipy otherwise start one thread per visible CPU, and the host path would behave unlike the image's.
# -c only sets the thread count (the memory cap and the timeout are this script's limits, not a CPU quota).
# nproc itself honours OMP_NUM_THREADS, hence the env -u: an inherited value must not become the default.
threads=$(awk -v c="${C:-$(env -u OMP_NUM_THREADS -u OMP_THREAD_LIMIT nproc)}" 'BEGIN { t = int(c); if (t < 1) t = 1; print t }')
export OMP_NUM_THREADS=$threads OPENBLAS_NUM_THREADS=$threads MKL_NUM_THREADS=$threads NUMEXPR_NUM_THREADS=$threads
[ $# -ge 1 ] || { echo "usage: capped.sh [-m MEM] [-t SECONDS] cmd..." >&2; exit 2; }
LOG=$(mktemp)
systemd-run --user --scope -q -p MemoryMax="$M" -p MemorySwapMax=0 \
    /usr/bin/time -f "%M %e" -o "$LOG" timeout -k 5 "$T" "$@"
rc=$?
# /usr/bin/time writes "Command exited with non-zero status N" first when the job failed: the numbers are the last line.
# No numbers at all means time(1) itself was killed with its job: that is the memory cap (the kernel's kill), reported as 137.
read -r peak wall < <(tail -n 1 "$LOG" 2>/dev/null | grep -E '^[0-9]+ [0-9.]+$')
if [ -z "$peak" ] && [ "$rc" -eq 143 ]; then rc=137; fi
echo "capped: peak_rss_kb=${peak:-?} wall_s=${wall:-?} exit=$rc cap=$M limit_s=$T" >&2
rm -f "$LOG"
exit $rc
