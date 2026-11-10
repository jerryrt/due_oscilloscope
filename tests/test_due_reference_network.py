"""The Due V03 reference network, read from the KiCad PCB. Board-free.

hardware/reference/arduino-due/v03/README.md describes how ADVREF is fed, and what
a shield would have to do to drive it. That description is only worth having while it
is true of the board file, so this reads the file.
"""
import os
import re

import pytest

pytestmark = pytest.mark.smoke

PCB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "hardware", "reference", "arduino-due", "v03", "Arduino-DUE-V03.kicad_pcb")

EXPECTED = {
    "AREF": {("BR1", "1"), ("PWMH0", "8")},
    "AVREFL": {("BR1", "2"), ("C34", "2"), ("JR1", "2"), ("L3", "1")},
    "AVREF": {("C19", "2"), ("L3", "2"), ("U1", "75")},
}
ON_3V3 = {("BR1", "3"), ("JR1", "1")}


def pads_by_net(text):
    """{net: {(reference, pad)}} for every pad of every footprint."""
    out = {}
    starts = [m.start() for m in re.finditer(r'\n\t\(footprint "', text)] + [len(text)]
    for a, b in zip(starts, starts[1:]):
        blk = text[a:b]
        ref = re.search(r'\(property "Reference" "([^"]+)"', blk)
        if not ref:
            continue
        for pm in re.finditer(r'\(pad "([^"]+)" (\w+) (\w+)(.*?)\n\t\t\)', blk, re.S):
            net = re.search(r'\(net "([^"]*)"\)', pm.group(4))
            if net:
                out.setdefault(net.group(1), set()).add((ref.group(1), pm.group(1)))
    return out


def problems(text):
    nets = pads_by_net(text)
    bad = ["%s is %s" % (n, sorted(nets.get(n, set()))) for n, want in EXPECTED.items() if nets.get(n) != want]
    bad += ["+3V3 lacks %s" % sorted(ON_3V3 - nets.get("+3V3", set()))] if ON_3V3 - nets.get("+3V3", set()) else []
    return bad


def test_the_pcb_has_the_reference_network_the_readme_describes():
    text = open(PCB, encoding="utf-8").read()
    assert len(text) > 1_000_000, "the board file is missing or truncated"
    assert problems(text) == []


def test_the_check_can_fail():
    """Move BR1's first pad onto the 3.3 V rail and the check must say so."""
    text = open(PCB, encoding="utf-8").read()
    start = text.index('(property "Reference" "BR1"')
    pad = re.compile(r'(\(pad "1" .*?\(net ")AREF("\))', re.S)
    m = pad.search(text, start)
    tampered = text[:m.start()] + m.group(1) + "+3V3" + m.group(2) + text[m.end():]
    assert problems(tampered) != []
