"""The front end, driven headlessly against a synthetic daemon.

Runs in the GUI venv, which is the only one with Qt and numpy:

    .venv-gui/bin/python -m pytest tests/test_gui.py -q

It skips everywhere else rather than failing, because the test venv
deliberately has neither.

What is worth testing without a person looking at it: that frames
become a trace, that a discontinuity breaks the line instead of being
drawn across, that the reduction shows an excursion rather than a
sample that happened to land on a pixel, and that the health panel
reports what it cost to draw.
"""

import os
import struct
import sys
import zlib

import pytest

# The skip reason is an instruction, not a diagnosis. "could not import
# numpy" is true and useless: it reads as a broken environment when it
# means "you are in the wrong venv", and a skip nobody knows how to turn
# into a run is a test that silently stops existing. Four of these were
# failing against a stale frame header for as long as nobody happened to
# remember the other interpreter.
_WRONG_VENV = ("needs the GUI venv - run "
               ".venv-gui/bin/python -m pytest tests/test_gui.py")

numpy = pytest.importorskip("numpy", reason=_WRONG_VENV)
pytest.importorskip("PySide6", reason=_WRONG_VENV)
pytest.importorskip("pyqtgraph", reason=_WRONG_VENV)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np                                      # noqa: E402
from PySide6 import QtWidgets                           # noqa: E402

from daemon import device as devmod                     # noqa: E402
from daemon import server as servermod                  # noqa: E402
from gui import stream                                  # noqa: E402
from gui.app import MainWindow                          # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def daemon():
    # Paced, so the synthetic device produces frames at the rate its
    # own header claims rather than as fast as a core allows. An
    # unpaced one is useful for backpressure tests and useless here.
    srv = servermod.Server(devmod.FakeDevice(pace=True), host="127.0.0.1",
                           port=0).start()
    yield srv
    srv.stop()


@pytest.fixture
def win(qapp, daemon):
    w = MainWindow(host="127.0.0.1", port=daemon.port)
    yield w
    w.disconnect_from_daemon()
    w.close()


def make_frame(seq, codes_by_tag, rate=200000, flags=0, overrun=0):
    """A frame in the device's own format, so the GUI decodes real
    bytes rather than a convenient object.

    Header v3, which is ten fields and not twelve: bits_per_sample,
    packing and n_samples were spent on play_consumed because they never
    varied, and the sample count now comes from the frame's length. See
    lib/due_shared/src/frame.h - this helper has to track it, because a fixture
    that builds a frame the device would never send tests nothing.
    """
    mask = 0
    for t in codes_by_tag:
        mask |= 1 << t
    hdr = struct.pack(stream.HDR_FMT, b"DUE0", 1, flags, mask, seq, rate,
                      seq * 1000, overrun, 0, 0)
    hdr = hdr[:28] + struct.pack("<I", zlib.crc32(hdr[:28]) & 0xFFFFFFFF)
    tags = sorted(codes_by_tag, reverse=True)
    body = bytearray()
    for i in range(len(codes_by_tag[tags[0]])):
        for t in tags:
            body += struct.pack("<H", (t << 12) | (int(codes_by_tag[t][i])
                                                   & 0xFFF))
    return bytes(hdr) + bytes(body)


# -- decoding ---------------------------------------------------------

def test_a_device_frame_decodes_into_channels_by_tag():
    """The tag rides in the top nibble of every sample, which is what
    makes demultiplexing a mask rather than an assumption about the
    order conversions happen in."""
    f = stream.decode(make_frame(3, {7: [100, 300], 6: [200, 400]}))
    assert f.seq == 3 and f.rate_hz == 200000
    assert list(f.channels[7]) == [100, 300]
    assert list(f.channels[6]) == [200, 400]
    assert not f.discontinuous


def test_an_overrun_flag_marks_the_frame_discontinuous():
    f = stream.decode(make_frame(4, {7: [1, 2]}, flags=stream.FLAG_OVERRUN))
    assert f.discontinuous


def test_anything_that_is_not_a_frame_decodes_to_nothing():
    assert stream.decode(b"") is None
    assert stream.decode(b"NOPE" + b"\x00" * 60) is None


# -- the reduction ----------------------------------------------------

def test_the_reduction_shows_the_excursion_not_a_sampled_point():
    """A spike one sample wide must survive being drawn on a plot a
    thousand times narrower than the data. Drawing every Nth sample
    would hide exactly the glitch this project exists to find."""
    samples = np.full(10000, 2048, dtype=np.uint16)
    samples[5000] = 4000
    x, y = stream.minmax(samples, 100)
    assert y.max() == 4000, "the spike was averaged or skipped away"
    assert len(x) == 200, "one min and one max per column"


def test_a_discontinuity_breaks_the_line_rather_than_being_drawn_across():
    """Invariant 5, on screen. A plot is exactly where a splice would
    be believed."""
    samples = np.arange(1000, dtype=np.uint16)
    breaks = np.zeros(1000, dtype=bool)
    breaks[500] = True
    x, y = stream.minmax(samples, 50, breaks)
    assert np.isnan(y).any(), "the gap was drawn as if it were signal"


def test_an_empty_window_draws_nothing_rather_than_raising():
    x, y = stream.minmax(np.empty(0, dtype=np.uint16), 100)
    assert x.size == 0 and y.size == 0


# -- the ring ---------------------------------------------------------

def test_the_window_is_seconds_so_it_does_not_shrink_with_the_rate():
    """Sized in samples, a window silently becomes a fraction of a
    screen when the rate goes up."""
    r = stream.ChannelRing(seconds=0.5, rate_hz=200000)
    assert r.filled == 0
    r.append(np.arange(1000, dtype=np.uint16))
    assert r.filled == 1000
    r.set_rate(453488)
    assert r.filled == 0, "a rate change resizes rather than mixing rates"
    r.append(np.arange(10, dtype=np.uint16))
    assert r.filled == 10


def test_the_ring_keeps_the_newest_samples_when_it_wraps():
    r = stream.ChannelRing(seconds=0.001, rate_hz=200000)   # 1024 minimum
    r.append(np.arange(3000, dtype=np.uint16))
    w, _ = r.window()
    assert w[-1] == 2999, "the newest sample must survive a wrap"
    assert len(w) == 1024


# -- end to end -------------------------------------------------------

def test_a_free_running_sweep_says_that_it_is_free_running():
    """A free-running sweep and a triggered one are the same array.

    The only thing that can tell them apart is the sweep saying so, and
    a scope that silently free-runs when it cannot find an edge is how a
    shaking trace gets blamed on the signal.
    """
    r = stream.ChannelRing(seconds=0.001, rate_hz=200000)
    r.append(np.arange(2000, dtype=np.uint16))

    sw = stream.select(r, 500)
    assert not sw.triggered
    assert sw.trigger_index is None
    assert sw.samples.size == 500
    # The most recent 500, which is what the widget used to ask for
    # directly - the extraction must not have moved the window.
    want, _ = r.window(500)
    assert np.array_equal(sw.samples, want)


def test_an_empty_ring_gives_an_empty_sweep_rather_than_raising():
    r = stream.ChannelRing(seconds=0.001, rate_hz=200000)
    sw = stream.select(r, 500)
    assert sw.empty and not sw.triggered


#: A half-sample skew so the waveform crosses `mid` *between* samples
#: rather than landing on one. Without it the crossing sample computes
#: to mid +/- 1 ULP and truncates to 2047 or 2048 depending on the last
#: bit, which moves the detected edge by one sample - see
#: test_a_sample_sitting_exactly_on_the_level_is_one_sample_unstable.
_SKEW = 0.5


def _tone(n, period, amp=800, mid=2048, phase=0.0, skew=_SKEW):
    t = np.arange(n, dtype=np.float64) + skew
    return (mid + amp * np.sin(2 * np.pi * (t + phase) / period)).astype(np.uint16)


def _displacement(a, b):
    """How far one drawn window moved against the previous one, in codes."""
    n = min(a.size, b.size)
    if n == 0:
        return 0
    return int(np.abs(a[:n].astype(np.int32) - b[:n].astype(np.int32)).max())


def test_the_trigger_holds_a_tone_still_that_free_running_does_not():
    """The defect this exists for, as a number rather than an eye.

    CLAUDE.md: the GUI "draws the most recent N samples every 33 ms with
    no trigger at all, so a trace holds still only when rate/tone
    divides the frame's samples-per-channel".

    So pick a period that deliberately does not divide the window, feed
    it in ragged chunks the way frames arrive, and compare the drawn
    window against the previous one each time. Free-running, consecutive
    sweeps differ; triggered, they are identical.
    """
    period, win = 271, 1000                  # 1000 % 271 != 0, on purpose
    r = stream.ChannelRing(seconds=0.05, rate_hz=200000)
    trig = stream.Trigger(level=2048, rising=True)

    # One continuous tone, appended in ragged chunks the way frames
    # arrive. `pos` is the absolute sample index so the phase carries
    # across the joins - get that wrong and the ring holds a tone with
    # steps in it, which no trigger can or should hold still.
    pos = 0
    n0 = 6000
    r.append(_tone(n0, period, phase=pos)); pos += n0

    free_moved = trig_moved = 0
    prev_free = prev_trig = None
    for k in range(1, 9):
        chunk = 137 * k
        r.append(_tone(chunk, period, phase=pos)); pos += chunk

        f = stream.select(r, win)
        t = stream.select(r, win, trig)
        assert t.triggered, "a clean tone should always find an edge"

        # How far the drawn trace moved, in codes, rather than whether
        # it moved at all. Bit-equality is the wrong test: the same
        # phase computed at a different absolute sample index differs by
        # 1 LSB of float rounding, which is not the trace moving.
        if prev_free is not None:
            free_moved = max(free_moved, _displacement(f.samples, prev_free))
            trig_moved = max(trig_moved, _displacement(t.samples, prev_trig))
        prev_free, prev_trig = f.samples, t.samples

    # Measured: free-running swings by up to ~1600 codes between
    # redraws, triggered by 1. The gap is three orders of magnitude, so
    # the thresholds are nowhere near either number.
    assert free_moved > 50, (
        f"free-running moved only {free_moved} codes - this tone was "
        f"chosen so its period does not divide the window, so if it is "
        f"holding still the test has stopped testing anything")
    assert trig_moved <= 2, (
        f"the triggered sweep moved {trig_moved} codes between redraws; "
        f"anything above a couple of LSB means it is not anchored")


def test_a_sample_sitting_exactly_on_the_level_is_one_sample_unstable():
    """A property of edge triggering at sample resolution, recorded
    rather than papered over.

    When the signal passes through the trigger level *at* a sample, that
    sample is at the level on some periods and just below it on others -
    here because the sine computes to mid +/- 1 ULP and truncates, and
    on a real input because of noise. The detected edge then moves by one
    sample, and the trace jitters by one sample period: 5 us at
    200 ksps, which is 0.1% of a 5 ms window.

    Sub-sample interpolation is the fix and is deliberately not built
    yet - it changes what is drawn, not just where the sweep starts.
    This test exists so the limitation is a known number rather than a
    surprise, and it should be *changed* when interpolation lands, not
    deleted.
    """
    period, win = 271, 1000
    r = stream.ChannelRing(seconds=0.05, rate_hz=200000)
    trig = stream.Trigger(level=2048, rising=True)

    pos, first = 0, None
    shifts = 0
    r.append(_tone(6000, period, phase=pos, skew=0.0)); pos += 6000
    for k in range(1, 6):
        chunk = 137 * k
        r.append(_tone(chunk, period, phase=pos, skew=0.0)); pos += chunk
        sw = stream.select(r, win, trig)
        if first is None:
            first = sw.samples
        elif not np.array_equal(sw.samples, first):
            shifts += 1

    assert shifts > 0, (
        "the knife-edge case stopped reproducing - if interpolation "
        "landed, rewrite this test rather than deleting it")


def test_the_trigger_puts_the_edge_where_it_says_it_does():
    r = stream.ChannelRing(seconds=0.05, rate_hz=200000)
    r.append(_tone(6000, 300))
    sw = stream.select(r, 1000, stream.Trigger(level=2048, rising=True))

    assert sw.triggered and sw.trigger_index == 500      # pretrigger 0.5
    i = sw.trigger_index
    assert sw.samples[i - 1] < 2048 <= sw.samples[i], (
        "the sample at trigger_index should be the first at or past the "
        "level, with its predecessor below it")


def test_a_falling_trigger_finds_the_other_slope():
    r = stream.ChannelRing(seconds=0.05, rate_hz=200000)
    r.append(_tone(6000, 300))
    sw = stream.select(r, 1000, stream.Trigger(level=2048, rising=False))
    i = sw.trigger_index
    assert sw.triggered
    assert sw.samples[i - 1] > 2048 >= sw.samples[i]


def test_auto_free_runs_when_there_is_no_edge_and_admits_it():
    """A flat line has no crossing. Auto must still draw something, and
    must not claim it triggered."""
    r = stream.ChannelRing(seconds=0.05, rate_hz=200000)
    r.append(np.full(4000, 1000, dtype=np.uint16))

    auto = stream.select(r, 1000, stream.Trigger(level=2048, mode="auto"))
    assert not auto.empty and not auto.triggered

    normal = stream.select(r, 1000, stream.Trigger(level=2048, mode="normal"))
    assert normal.empty, "normal mode draws nothing rather than free-running"


def test_the_trigger_does_not_fire_on_a_splice():
    """Invariant 5, at the one place it would be believed.

    A frame flagged discontinuous is not continuous with the one before
    it, so the step across that boundary is not a transition the signal
    made. Triggering on it would hold the trace still and make a splice
    look like a signal, which is worse than drawing it moving.
    """
    r = stream.ChannelRing(seconds=0.05, rate_hz=200000)
    r.append(np.full(2000, 1000, dtype=np.uint16))
    # A jump from below the level to above it, at a frame the device
    # flagged: the only "crossing" anywhere in this ring.
    r.append(np.full(2000, 3000, dtype=np.uint16), discontinuous=True)

    samples, breaks = r.window()
    edges = stream.find_edges(samples, 2048, rising=True, breaks=breaks)
    assert edges.size == 0, "the splice was accepted as an edge"

    sw = stream.select(r, 1000, stream.Trigger(level=2048, mode="normal"))
    assert sw.empty, "normal mode triggered on a discontinuity"


def test_frames_from_a_real_daemon_become_a_trace(win, daemon):
    win.connect_to_daemon()
    assert win.client is not None
    win.client.call("start", mode="capture", adc_hz=200000, channels=2)
    win.client.wait_frames(10, timeout=15.0)
    win.tick()
    assert win.frames_shown >= 10
    assert 7 in win.rings, "A0 never reached the display"
    assert win.rings[7].filled > 0
    assert win.scope.curve.getData()[0] is not None
    assert len(win.scope.curve.getData()[0]) > 0, "nothing was drawn"


def test_the_health_panel_reports_what_it_cost_to_draw(win, daemon):
    win.connect_to_daemon()
    win.client.call("start", mode="capture", adc_hz=200000, channels=2)
    win.client.wait_frames(10, timeout=15.0)
    win.tick()
    win.poll_status()
    labels = win.health._labels
    assert labels["mode"].text() == "capture"
    assert "/" in labels["frames"].text()
    assert labels["gaps"].text() == "0"
    assert labels["read_gap"].text().endswith("us")
    assert labels["role"].text() == "control"


def test_the_display_shows_the_rate_the_hardware_makes(win, daemon):
    """Rule 1 in docs/frontend.md, at the last place it could be
    broken: what is on screen comes from the frame header."""
    win.connect_to_daemon()
    win.client.call("start", mode="capture", adc_hz=200001, channels=2)
    win.client.wait_frames(5, timeout=15.0)
    win.tick()
    win.poll_status()
    assert win.rate_hz == 201030
    assert "201,030" in win.health._labels["rate"].text()


def test_a_sequence_gap_is_counted_and_shown(win, daemon):
    win.connect_to_daemon()
    win.ingest(stream.decode(make_frame(1, {7: [1, 2]})))
    win.ingest(stream.decode(make_frame(5, {7: [3, 4]})))
    win.poll_status()
    assert win.seq_gaps == 1
    assert win.health._labels["gaps"].text() == "1"


def test_a_discontinuous_frame_is_counted_for_the_channel_shown(win, daemon):
    win.connect_to_daemon()
    win.ingest(stream.decode(make_frame(1, {7: [1, 2]})))
    win.ingest(stream.decode(
        make_frame(2, {7: [3, 4]}, flags=stream.FLAG_OVERRUN)))
    win.poll_status()
    assert win.rings[7].discontinuities == 1
    assert win.health._labels["breaks"].text() == "1"


def test_the_window_survives_the_daemon_going_away(win, daemon):
    """A front end that hangs when the daemon dies is worse than one
    that says so."""
    win.connect_to_daemon()
    daemon.stop()
    win.poll_status()
    assert win.client is None
    assert "stopped answering" in win.statusBar().currentMessage()
