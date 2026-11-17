#!/bin/bash
cd /work/hardware/afe-proto
for x in 76.4 77.2 78.0; do for y in 20.9 21.6 22.5 23.4; do
  dx=$(python3 -c "print(round($x-80.2,3))"); dy=$(python3 -c "print(round($y-22.5,3))")
  n=$(bash kicad/relayout/quick.sh t "R515:-1.0:2.9:-;R516:-3.8:0:-;R201:$dx:$dy:180;TP201:0:9.5:-" 2>&1 | grep -c "designator\|overlap")
  echo "R201 ($x,$y): findings $n"
done; done
