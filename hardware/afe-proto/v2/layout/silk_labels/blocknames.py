import sys
sys.path.insert(0, '/work/hardware/afe-proto'); sys.path.append('/usr/lib/python3/dist-packages')
from pcbtools import boardio, silkread as S
from pcbtools.boards import v2_layout as C
b = boardio.read_board(sys.argv[1])
names = {'AWG': 'AWG', 'POWER': 'POWER', 'REF / CAL': 'REFCAL', 'CH1': 'CH1', 'CH2': 'CH2'}
for t, x, y, h in zip(b.t_text, b.t_x, b.t_y, b.t_h):
    t = t.decode() if isinstance(t, bytes) else t
    if t in names:
        blk = names[t]; rs = C.OUTLINE[blk]
        box = S.text_box(t, x, y, h, h)
        hit = [r for r in rs if r[0] <= x <= r[2] and r[1] <= y <= r[3]]
        r = hit[0] if hit else None
        where = 'outside every rectangle of its outline'
        if r:
            ew = 'west' if abs(box[0] - r[0]) < abs(box[2] - r[2]) else 'east'; ns = 'south' if abs(box[1] - r[1]) < abs(box[3] - r[3]) else 'north'
            where = 'inside rect %s, nearest corner %s-%s, edge gaps W %.2f E %.2f S %.2f N %.2f' % (tuple(round(v, 2) for v in r), ns, ew, box[0] - r[0], r[2] - box[2], box[1] - r[1], r[3] - box[3])
        print('%-10s at (%.2f, %.2f) size %.1f: %s' % (t, x, y, h, where))
