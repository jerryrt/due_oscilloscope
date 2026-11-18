"""make the board bytes reproducible: pcbnew gives the vias and rule areas that fill_clean creates random uuids and orders items by them. Every via and zone whose uuid is not one of the
input board's gets a uuid5 of its own content, and the vias (and the zones) are put back in uuid order, in the slots they already occupy.
usage: python3 cc_normalize.py INPUT_BOARD BOARD"""
import re
import sys
import uuid


def top_blocks(t):
    """[(start, end)] of the top-level children of the file's one form"""
    out, depth, start = [], 0, None
    for m in re.finditer(r'\(|\)|"(?:[^"\\]|\\.)*"', t):
        s = m.group(0)
        if s == '(':
            depth += 1
            if depth == 2:
                start = m.start()
        elif s == ')':
            if depth == 2:
                out.append((start, m.end()))
            depth -= 1
    return out


UUID = re.compile(r'\(uuid "([^"]+)"\)')


def normalize(text, known):
    blocks = top_blocks(text)
    slots = {'via': [], 'zone': []}
    for (a, b) in blocks:
        kind = text[a + 1:b].split(None, 1)[0].split('\n')[0]
        if kind in slots:
            slots[kind].append((a, b))
    repl = {}
    for kind, sl in slots.items():
        items = []
        for (a, b) in sl:
            blk = text[a:b]
            m = UUID.search(blk)
            if m and m.group(1) not in known:
                body = UUID.sub('', blk)
                blk = blk[:m.start()] + '(uuid "%s")' % uuid.uuid5(uuid.NAMESPACE_URL, 'afe2-cc/' + kind + '/' + re.sub(r'\s+', ' ', body)) + blk[m.end():]
            items.append(blk)
        order = sorted(range(len(items)), key=lambda i: UUID.search(items[i]).group(1))
        for slot, i in zip(sl, order):
            repl[slot] = items[i]
    out, last = [], 0
    for (a, b) in sorted(repl):
        out.append(text[last:a]); out.append(repl[(a, b)]); last = b
    out.append(text[last:])
    return ''.join(out)


COPPER = ('segment', 'via', 'zone')


def splice(original, built):
    """everything but the copper (tracks, vias, zones and rule areas) stays byte for byte as the original board has it, in its order; pcbnew's re-save moves the graphics, labels and
    fonts about, and the tests that regenerate those sections compare bytes. The copper region of the built board replaces the original's, which is one contiguous run in both."""
    def span(t):
        bl = top_blocks(t)
        idx = [k for k, (a, b) in enumerate(bl) if t[a + 1:b].split(None, 1)[0].split('\n')[0] in COPPER]
        assert idx == list(range(idx[0], idx[-1] + 1)), 'the copper is not one run'
        return bl[idx[0]][0], bl[idx[-1]][1]
    (a, b), (c, d) = span(original), span(built)
    return original[:a] + built[c:d] + original[b:]


if __name__ == '__main__':
    known = set(UUID.findall(open(sys.argv[1]).read()))
    t = normalize(open(sys.argv[2]).read(), known)
    t = splice(open(sys.argv[1]).read(), t)
    open(sys.argv[2], 'w').write(t)
    print('normalised', sys.argv[2])
