"""The vectorised labelling against the pure-Python reference, exactly. No board.

Skipped where numpy is absent.
"""
import pytest

np = pytest.importorskip("numpy")

import dsp  # noqa: E402
import etspam  # noqa: E402
import etsperiod  # noqa: E402
from test_etspam import _synth  # noqa: E402

pytestmark = pytest.mark.smoke


def _both(pam, monkeypatch, n=300_000, chunk=None, sigma=1.3):
    pat, vals = _synth(pam, n=n, sigma=sigma)
    trk = etsperiod.track_clock_ratio(vals, 46, pat.symbols, 29, levels=pat.pam)
    monkeypatch.setenv("DUE_DSP", "numpy")
    if chunk:
        monkeypatch.setattr(etspam, "CHUNK", chunk)
    out = {}
    for which, fn in (("ref", etspam.label_samples_ref), ("np", etspam.label_samples)):
        cells = {}
        centre, by_t = fn(vals, 46, trk["model"], pat, 29, 3.0, cells, 0)
        out[which] = (centre, by_t, cells)
    return out


def _same(a, b):
    ca, ba, xa = a
    cb, bb, xb = b
    assert [list(h) for h in ca] == [list(h) for h in cb]
    assert [[None if h is None else list(h) for h in row] for row in ba] == \
           [[None if h is None else list(h) for h in row] for row in bb]
    assert xa == xb


@pytest.mark.parametrize("pam", [4, 16])
def test_the_labels_are_identical(pam, monkeypatch):
    got = _both(pam, monkeypatch)
    _same(got["ref"], got["np"])


def test_the_labels_do_not_depend_on_the_chunk(monkeypatch):
    got = _both(4, monkeypatch, chunk=2048 * 3)
    _same(got["ref"], got["np"])


def test_the_comparison_can_fail(monkeypatch):
    """Shift the vectorised labelling's boundary: the comparison must see it."""
    got = _both(4, monkeypatch)
    pat, vals = _synth(4, n=300_000)
    trk = etsperiod.track_clock_ratio(vals, 46, pat.symbols, 29, levels=4)
    monkeypatch.setenv("DUE_DSP", "numpy")
    c, b = etspam.label_samples(vals, 46, trk["model"], pat, 29, 3.0 + 29, None, 0)
    assert [list(h) for h in c] != [list(h) for h in got["ref"][0]]
