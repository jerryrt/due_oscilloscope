"""Minimal S-expression reader and writer for KiCad files (symbol libraries, schematics, footprints, boards).

Atoms are Python str; quoted strings are wrapped in `Q` so the writer quotes them again. A list is a Python list.

    e = parse(text)            one top-level form -> the list; several -> a list of them
    dump(e)                    text, short lists on one line
    find(e, key), first(e, key)

The tokenizer is one compiled regular expression (no per-character Python loop) and the reader is iterative (no
recursion limit on deep files). String escapes are symmetrical: the writer escapes backslash, quote and newline, the reader
undoes exactly those, so parse(dump(x)) == x.
"""
import re


class Q(str):
    """A quoted string atom."""


_TOKEN = re.compile(r'[ \t\r\n]*(?:(?P<open>\()|(?P<close>\))|"(?P<str>(?:[^"\\]|\\.)*)"|(?P<atom>[^ \t\r\n()"]+))')
_ESC = re.compile(r'\\(.)', re.S)
_UNESC = {'n': '\n', '\\': '\\', '"': '"'}


def _unescape(s):
    return _ESC.sub(lambda m: _UNESC.get(m.group(1), m.group(0)), s) if '\\' in s else s


def parse(text):
    stack = [[]]
    pos = 0
    n = len(text)
    for m in _TOKEN.finditer(text):
        if m.start() != pos and text[pos:m.start()].strip():
            raise ValueError(f'cannot parse at offset {pos}: {text[pos:pos + 30]!r}')
        pos = m.end()
        kind = m.lastgroup
        if kind == 'open':
            stack.append([])
        elif kind == 'close':
            if len(stack) < 2:
                raise ValueError('unbalanced: extra )')
            e = stack.pop()
            stack[-1].append(e)
        elif kind == 'str':
            stack[-1].append(Q(_unescape(m.group('str'))))
        else:
            stack[-1].append(m.group('atom'))
    if text[pos:n].strip():
        raise ValueError(f'cannot parse at offset {pos}: {text[pos:pos + 30]!r}')
    if len(stack) != 1:
        raise ValueError('unbalanced: missing )')
    return stack[0][0] if len(stack[0]) == 1 else stack[0]


def _q(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def dump(e, ind=0):
    """Serialise; short lists stay on one line."""
    if isinstance(e, Q):
        return _q(e)
    if isinstance(e, str):
        return e
    if isinstance(e, int):
        return str(e)
    if isinstance(e, float):
        s = f'{e:.4f}'.rstrip('0').rstrip('.')
        return '0' if s in ('-0', '') else s
    parts = [dump(x, ind + 1) for x in e]
    one = '(' + ' '.join(parts) + ')'
    if len(one) < 100 and '\n' not in one:
        return one
    pad = '\t' * (ind + 1)
    head = [parts[0]]
    k = 1
    while k < len(parts) and not isinstance(e[k], list):
        head.append(parts[k])
        k += 1
    return '(' + ' '.join(head) + ''.join('\n' + pad + p for p in parts[k:]) + '\n' + '\t' * ind + ')'


def find(e, key):
    return [x for x in e if isinstance(x, list) and x and x[0] == key]


def first(e, key):
    r = find(e, key)
    return r[0] if r else None
