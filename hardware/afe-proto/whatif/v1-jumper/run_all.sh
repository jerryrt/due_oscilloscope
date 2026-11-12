#!/bin/sh
# regenerate every result in results/ (numpy only); N= sets the Monte Carlo draws (default 20000). final_s3.py is the S3 design; ranges.py/precision.py/stack.py are the earlier single-ended passes.
cd "$(dirname "$0")" && python3 ranges.py > results/ranges.txt 2>/dev/null && python3 precision.py > results/precision.txt 2>/dev/null && python3 stack.py > results/stack.txt && python3 scan_s3.py > results/scan_s3.txt 2>/dev/null && python3 final_s3.py > results/final_s3.txt 2>/dev/null && python3 pr3_run.py > results/pr3.txt 2>/dev/null
