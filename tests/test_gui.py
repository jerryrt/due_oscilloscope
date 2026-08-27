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
