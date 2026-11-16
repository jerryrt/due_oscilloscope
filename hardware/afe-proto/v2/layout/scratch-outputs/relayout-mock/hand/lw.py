import sys
sys.path.insert(0,'/work/hardware/afe-proto/v2/layout')
import relayout_place as RP
w=RP.LAB_W*4
print('LAB_W', RP.LAB_W, 'LAB_H', RP.LAB_H, 'ZONE', RP.ZONE)
print('west label x span', 71.125-w/2, 71.125+w/2, 'zone margin 0.06 ->', 71.125-w/2-0.06, 'A0 lane right edge 69.3')
