"""The old v1 tools' goldens of record (taken in the PCB image, see STAMP.json) say what the new tools must reproduce. This
test reads the golden text only (no KiCad): it pins the facts the equivalence tests rely on, so a golden cannot change silently."""
import json
import pathlib
import re

G = pathlib.Path(__file__).resolve().parents[1] / 'golden' / 'v1-34b2e51-image'


def text(name):
    return (G / f'{name}.out').read_text()


def test_stamp_names_the_image_and_every_tool():
    s = json.loads((G / 'STAMP.json').read_text())
    assert s['image'].startswith('sha256:') and len(s['installed']) == 64 and set(s['tools']) == {
        'build_pcb', 'check_pcb', 'lr_check', 'lr_check_mutate', 'fence_check'}
    for t, r in s['tools'].items():
        assert r['cap'] == '3G' and r['peak_rss_kb'] > 0


def test_build_pcb_golden():
    t = text('build_pcb')
    assert '119 footprints, 107 packed, 128 nets' in t and t.strip().endswith('exit=0')
    assert "('C105', 'R112')" in t                          # the one courtyard overlap the old legaliser could not clear


def test_check_pcb_golden_rows():
    t = text('check_pcb')
    for row in ('PASS S1', 'PASS S2', 'PASS S3', 'PASS S4', 'PASS P1:', 'PASS P3:', 'PASS MP1', 'PASS MP2', 'PASS MP3'):
        assert row in t, row
    assert 'FAIL P2' in t and t.strip().endswith('exit=1')   # the baseline has unrouted nets, so P2 fails


def test_lr_check_golden_rows():
    t = text('lr_check')
    for ok in ('LR-3', 'LR-5', 'LR-7', 'LR-9'):
        assert f'[PASS] {ok}' in t, ok
    assert 'FAIL: LR-1, LR-2, LR-4, LR-6, LR-8, LR-10, LR-11' in t and t.strip().endswith('exit=1')


def test_lr_check_mutate_golden_all_arms_fail_as_required():
    t = text('lr_check_mutate')
    assert 'every arm behaved' in t and 'NOT CAUGHT' not in t and t.strip().endswith('exit=0')
    assert len(re.findall(r'\[FAILED AS REQUIRED\]', t)) >= 45


def test_fence_check_golden():
    assert text('fence_check').strip().splitlines()[0] == 'POWER: clean'
