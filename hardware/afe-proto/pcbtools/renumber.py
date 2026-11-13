"""renumber.py: number reference designators by functional block (LR-11) from a generated map, and rewrite text with it.

Nothing here names a board: a board passes its parts as (ref, block) pairs and the digit each block takes.

    mp = build_map(parts, hundreds={'ch1': 1, ...}, override={'R98': 'cal'})
    new_text = rewrite(text, mp)

Within a block the parts keep their old order (by prefix letters, then number), so the numbers inside a hundred follow
the old ones. The map is a pure function of its inputs; applying it to files is the caller's one-off step.
"""
import re


def split_ref(ref):
    m = re.fullmatch(r'([A-Za-z]+)(\d+)', ref)
    if not m:
        raise ValueError(f'not a designator: {ref!r}')
    return m.group(1), int(m.group(2))


def build_map(parts, hundreds, override=None, width=2):
    """parts: iterable of (ref, block); hundreds: block -> digit (1..9); override: ref -> block.
    Returns {old_ref: new_ref}; raises ValueError on a block with no digit, a duplicate part or a collision."""
    override = override or {}
    blk = {}
    for ref, block in parts:
        if ref in blk:
            raise ValueError(f'duplicate part {ref}')
        blk[ref] = override.get(ref, block)
    for ref, b in blk.items():
        if b not in hundreds:
            raise ValueError(f'{ref}: block {b!r} has no hundreds digit')
    used, new = {}, {}
    for ref in sorted(blk, key=split_ref):
        pre, _ = split_ref(ref)
        h = hundreds[blk[ref]]
        k = used.get((pre, h), 0) + 1
        if k >= 10 ** width:
            raise ValueError(f'block {blk[ref]!r} has too many {pre} parts for {width} digits')
        used[(pre, h)] = k
        new[ref] = f'{pre}{h}{k:0{width}d}'
    if len(set(new.values())) != len(new):
        raise ValueError('duplicate new designators')
    return new


_BOUND = r'(?<![A-Za-z0-9_])(%s)(?![A-Za-z0-9_])'


def rewrite(text, mapping):
    """replace every whole-word designator in `text` by its new one in ONE pass (so no name is rewritten twice).
    R10 never eats R100: the word boundaries make each name match whole (alternation order does not matter)."""
    if not mapping:
        return text
    names = sorted(mapping)
    pat = re.compile(_BOUND % '|'.join(re.escape(n) for n in names))
    return pat.sub(lambda m: mapping[m.group(1)], text)


def unmapped(text, mapping):
    """designator-looking words in `text` that are not keys of `mapping` (to spot a part the map missed)"""
    pat = re.compile(r'(?<![A-Za-z0-9_])([A-Z]{1,2}\d{1,3})(?![A-Za-z0-9_])')
    return sorted({w for w in pat.findall(text) if w not in mapping})
