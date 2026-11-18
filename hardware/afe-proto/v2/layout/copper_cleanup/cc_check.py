"""the electrical margin the cleanup must not spend: every protected net (the nets whose track length an LR row reads or limits) is no longer than it was, compared unrounded.
usage: python3 cc_check.py BEFORE_BOARD AFTER_BOARD   (exit 1 if any net got longer than float noise, 1e-9 mm)"""
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
AFE = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
sys.path[:0] = [AFE, os.path.join(AFE, '..', 'pcbkit')]
import pcbtools                                  # registers pcbkit
from pcbtools import check, rules
from pcbtools.boards import v2_layout as L

TOL = 1e-9
PROTECTED = list(L.INV_LEN_NODES) + list(L.ADC_NETS) + list(L.INV_NODES)


def lengths(path):
    b = check.load(path)
    return {n: rules.length_of(b, n, top_only=False) for n in PROTECTED}


if __name__ == '__main__':
    a, z = lengths(sys.argv[1]), lengths(sys.argv[2])
    bad = []
    for n in PROTECTED:
        print('%-10s before %.12f  after %.12f  %+.3e' % (n, a[n], z[n], z[n] - a[n]))
        if z[n] > a[n] + TOL:
            bad.append(n)
    if bad:
        raise SystemExit('longer than before: %s' % bad)
