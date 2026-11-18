cd /work
O=hardware/afe-proto/whatif/fill-keepouts/img/final2
C=hardware/afe-proto/whatif/fill-keepouts/crop.py
run() { n=$1; shift; python3 $C hardware/afe-proto/kicad/_main_f0845ddf.kicad_pcb $O/$n-before.png "$@"; python3 $C hardware/afe-proto/kicad/afe-proto.kicad_pcb $O/$n-after.png "$@"; }
run lm-c1n 32.5 10.5 38.5 14 200
run vneg-o 41.5 2 50 6.5 150
run bnc-keyhole 104 -1.8 112 3 200
