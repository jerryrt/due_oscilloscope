cd /work
O=hardware/afe-proto/whatif/fill-keepouts/img/final2
C=hardware/afe-proto/whatif/fill-keepouts/crop.py
run() { n=$1; shift; python3 $C hardware/afe-proto/kicad/_main_f0845ddf.kicad_pcb $O/$n-before.png "$@"; python3 $C hardware/afe-proto/kicad/afe-proto.kicad_pcb $O/$n-after.png "$@"; }
run power 18 4 44.5 23 60
run refcal 44.5 4.5 64.8 31.5 60
run scope-ch1 64 33.5 92.3 46.7 60
run scope-ch2 75 22 92.3 32.3 60
run awg 69.5 3.8 92.3 19.7 60
run bnc-scope-a 98.2 17.5 116.4 35.8 60
run bnc-scope-b 98.2 35.3 116.4 53.6 60
run bnc-awg 98.2 -1.8 116.4 16.6 60
run u502-pin3 56 13 63 19.5 160
run header-j606 20 46 33 53.5 100
run header-j601 112 46 117 54 100
