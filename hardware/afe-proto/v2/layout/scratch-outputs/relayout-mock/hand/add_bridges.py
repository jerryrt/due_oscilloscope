"""python3 add_bridges.py IN.kicad_pcb OUT.kicad_pcb BRIDGES.py
BRIDGES.py: BRIDGES = [dict(ref='BR201', x=73.8, y=27.3, rot=90, a='+3V3A_P', b='+3V3A', move={'D201.2': '+3V3A_P'})]   (Due mm; pad 1 = net a, pad 2 = net b;
move: pads whose net is renamed to a). Scratch only: inserts a 0603 0R footprint (copied from main's BR102 block) and renames pad nets by text splice."""
import re, sys, uuid, hashlib
inp, out, spec = sys.argv[1:4]
ns = {}; exec(open(spec).read(), ns)
t = open(inp).read()
TPL = open('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/hand/br_template.txt').read()
def U(tag):
    h = hashlib.sha1(tag.encode()).hexdigest()
    return f'{h[:8]}-{h[8:12]}-5{h[13:16]}-a{h[17:20]}-{h[20:32]}'
blocks = ''
for b in ns['BRIDGES']:
    blk = TPL.replace('BR102', b['ref']).replace('(at 112.8 114.3)', '(at %.4f %.4f %g)' % (b['x'] + 50, 150 - b['y'], b['rot']) if b['rot'] else '(at %.4f %.4f)' % (b['x'] + 50, 150 - b['y']))
    blk = blk.replace('"/+3V3A_K"', '"/%s"' % b['a']).replace('"/+3V3A_S"', '"/%s"' % b['b'])
    blk = re.sub(r'\(uuid "[0-9a-f-]+"\)', lambda m: '(uuid "%s")' % U(b['ref'] + m.group(0)), blk)
    blk = re.sub(r'\(path "[^"]*"\)\n', '', blk)
    blocks += blk
    for pin, net in b.get('move', {}).items():
        ref, p = pin.split('.')
        i = t.index('(property "Reference" "%s"' % ref); s = t.rfind('\n\t(footprint ', 0, i); e = t.index('\n\t(footprint ', i + 1) if '\n\t(footprint ' in t[i + 1:] else len(t)
        fp = t[s:e]
        fp2 = re.sub(r'(\(pad "%s"[^\n]*\n(?:(?!\n\t\t\(pad ).)*?\(net ")[^"]*(")' % re.escape(p), lambda m: m.group(1) + '/' + net + m.group(2), fp, count=1, flags=re.S)
        assert fp2 != fp, pin
        t = t[:s] + fp2 + t[e:]
anchor = '\n\t(gr_circle\n\t\t(center 140.17 99.2)'
i = t.index('\n\t(segment') if '\n\t(segment' in t else t.index(anchor)
t = t[:i] + blocks.rstrip('\n') + t[i:]
open(out, 'w').write(t)
print('bridges', len(ns['BRIDGES']))
