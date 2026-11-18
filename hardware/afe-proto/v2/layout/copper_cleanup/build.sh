#!/bin/bash
# build.sh: rebuild v2/layout/integrated/afe-v2-integrated.kicad_pcb from the board of record (afe-v2-integrated.before.kicad_pcb) in the pinned PCB image, from the repository root:
#   docker/pcb/run.sh -m 4G -t 1800 bash hardware/afe-proto/v2/layout/copper_cleanup/build.sh
# The passes, in order: the automatic track pass (cc_reroute), the hand edits as data (cc_edits), a via of its own for the GND pads the edits left without one (cc_gndvias),
# the second round of hand edits (cc_fix_data: what the detour, dangling, T spur and width checks found), the automatic pass on the detours, and pcbtools.fill_clean LAST (keep-outs, thermal reliefs, minimum widths, stitching). The result replaces the board; the same input always gives the same bytes, and everything but the copper is the board of record's own text.
set -e
A=hardware/afe-proto
W=$A/v2/layout/copper_cleanup
B=$A/v2/layout/integrated/afe-v2-integrated.kicad_pcb
T=$(mktemp -d)
cp $W/afe-v2-integrated.before.kicad_pcb $B
python3 $W/cc_reroute.py $B $T/1.kicad_pcb --max-legs 4 --narrow --skip-nets /GND > $T/1.log
python3 $W/cc_edits.py $T/1.kicad_pcb $T/2.kicad_pcb > $T/2.log
cp $T/2.kicad_pcb $T/3.kicad_pcb
python3 $W/cc_edits.py $T/3.kicad_pcb $T/4.kicad_pcb cc_fix_data > $T/4.log
python3 $W/cc_reroute.py $T/4.kicad_pcb $T/5.kicad_pcb --kinds detour --max-legs 4 --skip-nets /GND --grid > $T/5.log
python3 $W/cc_edits.py $T/5.kicad_pcb $T/5b.kicad_pcb cc_fix2_data > $T/5b.log
python3 $W/cc_gndedge.py $T/5b.kicad_pcb $T/6.kicad_pcb > $T/6.log
if [ -n "$CC_NO_POURKEEP" ]; then cp $T/6.kicad_pcb $T/7.kicad_pcb; else python3 $W/cc_keepouts.py $T/6.kicad_pcb $T/7.kicad_pcb > $T/7.log; fi          # CC_NO_POURKEEP=1 skips our own pour keep-out: the pour guard must then refuse (the proof that it is needed)
cp $T/7.kicad_pcb $B
# the pour guard compares the fill with the pour gaps of the REFERENCE: main's board at f0845ddf (afe-v2-integrated.reference.kicad_pcb, the last accepted pour, CH1_OUT 2.078 mm), not the
# board of record, whose stored fill is the pre-cleanup one (CH1_OUT 0.171 mm: any fill would pass), and not the pre-fill input, which carries that stale fill
(cd $A && python3 -m pcbtools.fill_clean v2/layout/integrated/afe-v2-integrated.kicad_pcb v2/layout/integrated/.fillclean.out.kicad_pcb --config v2_layout --reference v2/layout/copper_cleanup/afe-v2-integrated.reference.kicad_pcb > $T/fc.log 2>&1) || { rc=$?; grep -i "refus" $T/fc.log; echo "fill_clean exit code $rc"; exit $rc; }
echo "fill_clean exit code 0"

mv $A/v2/layout/integrated/.fillclean.out.kicad_pcb $B
rm -f $A/v2/layout/integrated/*.tmp.kicad_pro $A/v2/layout/integrated/.fillclean.out.kicad_pro
python3 $W/cc_normalize.py $W/afe-v2-integrated.before.kicad_pcb $B
python3 $W/cc_check.py $W/afe-v2-integrated.before.kicad_pcb $B
sha256sum $B
