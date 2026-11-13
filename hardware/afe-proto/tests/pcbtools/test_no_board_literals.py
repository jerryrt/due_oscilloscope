"""The board-independent modules contain no reference designator and no net name: every ref, pin and net the rules use comes from
the board configuration (pcbtools/CONFIG_FIELDS.md). The scan reads the STRING tokens of each module (docstrings and f-string parts
included, comments not) and fails on
  * a reference-designator token (R/C/U/J/D/Q/L/TP/BR/MH/SW/F followed by digits) in any string, and
  * a string that starts with '/' followed by a name character (a KiCad net name such as '/A0' or '/GND').
There is no allowlist: even the ground net is a config field (`GND`). The test is itself tested: a literal appended to a copy of a
module must fail the scan (test_the_scan_fails_on_a_literal)."""
import io
import os
import re
import tokenize

import pytest

PKG = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pcbtools')
MODULES = ['rules.py', 'check.py', 'drc.py', 'fence.py', 'cap.py', 'geom.py', 'mutate.py', 'boardio.py', 'shapes.py',
           'gate3/__init__.py', 'gate3/__main__.py', 'gate3/engine.py', 'gate3/connectivity.py', 'gate3/table.py']      # the gate-3 tool; its table (boards/gate3_*.py) is a config
REF = re.compile(r'(?<![A-Za-z0-9_])(?:R|C|U|J|D|Q|L|TP|BR|MH|SW|F)\d+(?![A-Za-z0-9_])')
NET = re.compile(r"(?:^|[\s'\"(\[,])/[A-Za-z0-9_+{]")
# a net starts a string or follows a quote/space: 'A0/A1' (two names joined by a slash) is not a net name, and neither is
# a path like 'tests/fixtures'; the check is on the string's own first characters and on quoted names inside a docstring


def strings(text):
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.STRING or tok.type == getattr(tokenize, 'FSTRING_MIDDLE', -1):
            out.append((tok.start[0], tok.string))
    return out


def violations(text):
    bad = []
    for line, s in strings(text):
        body = s
        for m in REF.finditer(body):
            bad.append((line, m.group(0)))
        # a net name: the string (or a quoted word inside it) begins with '/'
        if re.match(r"""^[rbfRBF]*(['"]{1,3})/[A-Za-z0-9_+{]""", body) or re.search(r"""['"]/[A-Za-z0-9_+]""", body):
            bad.append((line, 'net literal ' + body[:20]))
    return bad


@pytest.mark.parametrize('mod', MODULES)
def test_no_reference_or_net_literals(mod):
    text = open(os.path.join(PKG, mod)).read()
    assert strings(text) is not None
    assert violations(text) == []


def test_the_scan_examines_strings_at_all():
    assert sum(len(strings(open(os.path.join(PKG, m)).read())) for m in MODULES) > 500         # a floor: it must have looked


@pytest.mark.parametrize('literal', ["x = 'R101'", "x = '/A0'", 'x = f"{a} not at U101"', "x = '/GND'", '"""doc: pair_caps(b, (\'/CH1_N\', 1))"""',
                                     "x = 'C2'", "x = 'TP301'", "x = 'BR503'"])
def test_the_scan_fails_on_a_literal(literal):
    """break the check on purpose: each of these must be reported (and the neighbours that are fine must not be)"""
    assert violations(literal + '\n')


@pytest.mark.parametrize('fine', ["x = 'A0/A1 top only'", "x = '/'.join(a)", "p = 'tests/fixtures'", "x = 'LR-1'", "x = 'TP'", "x = 'R'",
                                  "x = 'ABC123'", "x = f'{r} not at the output pin'"])
def test_the_scan_leaves_generic_strings_alone(fine):
    assert violations(fine + '\n') == []


def test_a_literal_appended_to_a_real_module_is_found(tmp_path):
    text = open(os.path.join(PKG, 'rules.py')).read()
    assert violations(text) == []
    assert violations(text + "\nBAD = 'R108'\n") and violations(text + "\nBAD = pad_c(b, 'J601', '5')\n")
    assert violations(text + "\nBAD = nid(b, '/GND')\n")
