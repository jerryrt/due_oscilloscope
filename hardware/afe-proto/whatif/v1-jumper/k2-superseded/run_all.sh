#!/bin/sh
# regenerate every result in results/ (numpy only, about 3 minutes); N= sets the Monte Carlo draws (default 20000)
cd "$(dirname "$0")" && python3 ranges.py > results/ranges.txt && python3 forced.py > results/forced.txt && python3 detect.py > results/detect.txt && python3 precision.py > results/precision.txt 2>/dev/null
