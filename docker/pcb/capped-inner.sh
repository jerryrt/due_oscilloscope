#!/bin/bash
# Runs INSIDE the container, as run.sh's entry point: the command under
# `timeout`, then one summary line on stderr in capped.sh's format.
#
#   capped: peak_rss_kb=<n> wall_s=<s> exit=<n> cap=<MEM> limit_s=<T> image=<content-hash>
#
# The peak is the container cgroup's memory.peak (the whole job and its
# children, unlike capped.sh's largest-single-process figure), in KB.
# Fields after limit_s are this runner's own; the host parser ignores them.
# The OOM kill is the kernel's, and it may take this script with the job; then
# run.sh prints the line from outside.
set -uo pipefail
limit=$1; shift
t0=$(date +%s.%N)
timeout -k 5 "$limit" "$@"
rc=$?
wall=$(python3 -c "import sys,time;print('%.2f' % (time.time()-float(sys.argv[1])))" "$t0")
peak=?
if [ -r /sys/fs/cgroup/memory.peak ]; then peak=$(( $(cat /sys/fs/cgroup/memory.peak) / 1024 )); fi
if grep -qE '^oom_kill [1-9]' /sys/fs/cgroup/memory.events 2>/dev/null; then rc=137; fi
echo "capped: peak_rss_kb=$peak wall_s=$wall exit=$rc cap=${DUE_PCB_CAP:-?} limit_s=$limit image=${DUE_PCB_IMAGE_CONTENT:-?}" >&2
exit $rc
