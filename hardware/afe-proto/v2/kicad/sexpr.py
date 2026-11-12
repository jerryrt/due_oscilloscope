"""Minimal S-expression reader and writer for KiCad files.

Atoms are kept as Python str; quoted strings are wrapped in Q so the writer
can quote them again.  Enough for KiCad 10 symbol libraries and schematics.
"""


class Q(str):
    """A quoted string atom."""


def parse(text):
    tok, i, n = [], 0, len(text)
    stack = [[]]
    while i < n:
        c = text[i]
        if c in ' \t\r\n':
            i += 1
        elif c == '(':
            stack.append([]); i += 1
        elif c == ')':
            e = stack.pop(); stack[-1].append(e); i += 1
        elif c == '"':
            j = i + 1; buf = []
            while text[j] != '"':
                if text[j] == '\\':
                    buf.append(text[j:j + 2]); j += 2
                else:
                    buf.append(text[j]); j += 1
            stack[-1].append(Q(''.join(buf).replace('\\"', '"').replace('\\\\', '\\'))); i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            stack[-1].append(text[i:j]); i = j
    assert len(stack) == 1, 'unbalanced'
    return stack[0][0] if len(stack[0]) == 1 else stack[0]


def _q(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def dump(e, ind=0):
    """Serialise; short lists stay on one line."""
    if isinstance(e, Q):
        return _q(e)
    if isinstance(e, str):
        return e
    if isinstance(e, (int,)):
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
        head.append(parts[k]); k += 1
    return '(' + ' '.join(head) + ''.join('\n' + pad + p for p in parts[k:]) + '\n' + '\t' * ind + ')'


def find(e, key):
    return [x for x in e if isinstance(x, list) and x and x[0] == key]


def first(e, key):
    r = find(e, key)
    return r[0] if r else None
