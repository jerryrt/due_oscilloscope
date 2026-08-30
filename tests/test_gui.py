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

import io
import os
import struct
import sys
import time
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
    assert win.scope.trace()[0] is not None
    assert len(win.scope.trace()[0]) > 0, "nothing was drawn"


def test_volts_come_from_the_measured_reference_not_a_nominal_one():
    """Every volt this window draws came from an ADC code.

    The DAC->ADC loop is ratiometric, so the board cannot measure its
    own reference and 3300 was an assumption. The scope settled it at
    3270, and until the GUI read that the axis, the cursors and the
    trigger level were all 0.91% high.

    Asserted against the calibration record rather than against 3270, so
    the day a better instrument moves the number this follows it instead
    of failing.
    """
    import calibration as cal
    want, source = cal.advref_mv()
    assert source == "measured", "calibration.json is unreadable from here"

    assert stream.ADVREF_MV == want
    assert stream.ADVREF_SOURCE == "measured", (
        "the GUI fell back to the nominal reference; calibration.json is "
        "unreadable from here")
    assert abs(stream.VREF_V - want / 1000.0) < 1e-9

    # Full scale reads as the reference, and the trigger level control
    # round-trips through the same scale factor the trace uses.
    assert abs(float(stream.codes_to_volts(4095)) - want / 1000.0) < 0.001
    mid = stream.volts_to_codes(want / 2000.0)
    assert abs(mid - 2048) <= 1


def test_the_measurements_recover_a_known_tone():
    """A tone whose frequency and amplitude are known by construction."""
    rate, period = 200000, 250              # 800 Hz exactly
    r = stream.ChannelRing(seconds=0.05, rate_hz=rate)
    r.append(_tone(8000, period, amp=800, mid=2048))

    m = stream.measure(stream.select(r, 4000), rate)
    assert m["note"] is None

    assert abs(m["freq_hz"] - rate / period) < 1.0, m["freq_hz"]
    assert abs(m["period_s"] - period / rate) < 1e-7

    # 1600 codes peak-to-peak through the measured reference.
    want_vpp = float(stream.codes_to_volts(1600))
    assert abs(m["vpp_v"] - want_vpp) < 0.01, (m["vpp_v"], want_vpp)

    # A sine's RMS is its mean squared plus half its amplitude squared.
    a = float(stream.codes_to_volts(800))
    dc = float(stream.codes_to_volts(2048))
    assert abs(m["rms_v"] - np.sqrt(dc * dc + a * a / 2)) < 0.01
    assert abs(m["duty"] - 0.5) < 0.02


def test_noise_at_the_midpoint_does_not_multiply_the_frequency():
    """The defect hardware validation found, as a regression test.

    A sine crosses its midpoint once per period in theory. Through an
    ADC it wanders across that level on the way, and every wobble reads
    as another crossing. Three captures of one unchanging 97.66 Hz
    signal read 97.66, 146.41 and 195.31 before hysteresis - the last
    two are spurious edges inflating the count, and the mean-across-the-
    endpoints estimator turned a couple of them into a doubling.

    The noise here is deliberately placed where it does damage: on the
    samples nearest the midpoint, which is where a real converter's is
    least helpful.
    """
    rate, period = 50000, 512
    n = 6000
    t = np.arange(n, dtype=np.float64)
    clean = 2048 + 900 * np.sin(2 * np.pi * t / period)

    rng = np.random.default_rng(11)
    noisy = clean.copy()
    near = np.abs(clean - 2048) < 40           # the midpoint crossings
    noisy[near] += rng.integers(-12, 13, size=int(near.sum()))

    r = stream.ChannelRing(seconds=0.5, rate_hz=rate)
    r.append(noisy.astype(np.uint16))

    m = stream.measure(stream.select(r, n), rate)
    assert m["note"] is None, m["note"]
    want = rate / period
    assert abs(m["freq_hz"] - want) < want * 0.02, (
        f"{m['freq_hz']:.2f} Hz against a true {want:.2f} - noise at the "
        f"midpoint is being counted as crossings")


def test_a_window_holding_one_period_refuses_rather_than_guessing():
    """Two crossings give one interval, and one interval cannot be
    checked against anything. The old estimator reported it anyway."""
    rate, period = 50000, 512
    r = stream.ChannelRing(seconds=0.5, rate_hz=rate)
    r.append(_tone(3000, float(period), amp=900, skew=0.0))

    m = stream.measure(stream.select(r, 700), rate)   # ~1.4 periods
    assert m["freq_hz"] is None
    assert m["note"] == "fewer than two periods in window"


def test_a_discontinuity_in_the_window_measures_nothing():
    """Rather than measuring across it.

    The largest excursion may span two unrelated moments and the
    interval between crossings is not a period. A number carries that
    lie further than a plot does - the plot at least shows the break.
    """
    rate = 200000
    r = stream.ChannelRing(seconds=0.05, rate_hz=rate)
    r.append(_tone(2000, 250))
    r.append(_tone(2000, 250, phase=2000), discontinuous=True)

    m = stream.measure(stream.select(r, 3000), rate)
    assert m["note"] == "discontinuity in window"
    for k in ("vpp_v", "rms_v", "freq_hz", "duty"):
        assert m[k] is None, f"{k} was measured across a splice"


def test_a_flat_channel_refuses_to_report_a_frequency():
    """A quiet channel crosses its own midpoint on noise. Timing that
    would report the noise and call it the signal."""
    rate = 200000
    r = stream.ChannelRing(seconds=0.05, rate_hz=rate)
    rng = np.random.default_rng(7)
    flat = (2048 + rng.integers(-1, 2, size=4000)).astype(np.uint16)
    r.append(flat)

    m = stream.measure(stream.select(r, 3000), rate)
    assert m["freq_hz"] is None and m["duty"] is None
    assert m["note"] == "signal too flat to time"
    # Amplitude is still honest - it is the timing that is unavailable.
    assert m["vpp_v"] is not None


def test_there_is_no_rise_time_because_this_adc_cannot_see_one():
    """Deliberate absence, asserted so it is not added by accident.

    The DAC's step is 789-938 ns measured with a scope (docs/awg.md);
    this ADC's sample interval is 1.1 us at its fastest. A 10-90% time
    from these samples would report the sampling interval and call it
    the converter's edge.
    """
    rate = 200000
    r = stream.ChannelRing(seconds=0.05, rate_hz=rate)
    r.append(_tone(4000, 250))
    m = stream.measure(stream.select(r, 2000), rate)
    assert "rise_s" not in m and "fall_s" not in m


def test_the_spectrum_puts_a_known_tone_at_its_known_level():
    """A tone on an exact bin, so bin resolution is not in the way.

    64 whole cycles in the 16384-point transform: 200000/256 = 781.25 Hz
    exactly. 1000 codes of amplitude against a full scale of 2048 is
    20*log10(1000/2048) = -6.227 dBFS, and the transform should say so
    rather than approximately so.
    """
    rate = 200000
    r = stream.ChannelRing(seconds=0.3, rate_hz=rate)
    r.append(_tone(30000, 256.0, amp=1000, skew=0.0))

    f, db, note = stream.spectrum(stream.select(r, stream.FFT_MAX_POINTS), rate)
    assert note is None
    i = int(np.argmax(db))
    assert abs(f[i] - rate / 256.0) < 0.01, f[i]
    assert abs(db[i] - 20 * np.log10(1000 / 2048)) < 0.05, db[i]


def test_every_window_reports_the_same_amplitude():
    """Only the leakage should change, not the height of the tone.

    Normalising by the window's own sum is what buys this. Without it a
    Blackman spectrum reads several dB below a rectangular one for the
    same signal, and a user comparing two captures taken with different
    windows would read a level change that is not there.
    """
    rate = 200000
    r = stream.ChannelRing(seconds=0.3, rate_hz=rate)
    r.append(_tone(30000, 256.0, amp=1000, skew=0.0))
    sw = stream.select(r, stream.FFT_MAX_POINTS)

    peaks = []
    for w in stream.FFT_WINDOWS:
        _f, db, note = stream.spectrum(sw, rate, window=w)
        assert note is None, (w, note)
        peaks.append(float(db[int(np.argmax(db))]))
    assert max(peaks) - min(peaks) < 0.05, dict(zip(stream.FFT_WINDOWS, peaks))


def test_a_tone_between_bins_loses_only_scalloping():
    """Off-bin, the peak bin under-reads. That is the transform, not a
    defect, and the size of it is bounded and known: Hann's worst case
    is 1.42 dB. Asserted so a real error cannot hide inside it."""
    rate = 200000
    r = stream.ChannelRing(seconds=0.3, rate_hz=rate)
    r.append(_tone(30000, 250.0, amp=1000, skew=0.0))

    _f, db, _n = stream.spectrum(stream.select(r, stream.FFT_MAX_POINTS), rate)
    peak = float(db[int(np.argmax(db))])
    ideal = 20 * np.log10(1000 / 2048)
    assert -1.45 < peak - ideal <= 0.05, peak - ideal


def test_the_spectrum_refuses_across_a_discontinuity():
    """Sharper than the time domain's version of this rule.

    A splice is a step, a step is broadband, and the transform will
    spread that step's energy across every frequency on screen - which
    reads as a noise floor rather than as the missing data it is.
    """
    rate = 200000
    r = stream.ChannelRing(seconds=0.3, rate_hz=rate)
    r.append(_tone(8000, 256.0, skew=0.0))
    r.append(_tone(8000, 256.0, phase=8000, skew=0.0), discontinuous=True)

    f, db, note = stream.spectrum(stream.select(r, 12000), rate)
    assert f is None and db is None
    assert note == "discontinuity in window"


def test_the_transform_is_bounded_so_it_cannot_block_the_feeder():
    """Rule 5. The ring holds two seconds - 1.8 M samples at the full
    rate - and an FFT that size inside a 33 ms redraw would stall the
    display and, behind it, the reader."""
    rate = 907000
    r = stream.ChannelRing(seconds=2.0, rate_hz=rate)
    r.append(_tone(200000, 256.0, skew=0.0))

    sw = stream.select(r, 200000)
    assert sw.samples.size > stream.FFT_MAX_POINTS
    f, db, note = stream.spectrum(sw, rate)
    assert note is None
    assert db.size == stream.FFT_MAX_POINTS // 2 + 1, db.size


def test_the_trigger_controls_describe_the_trigger_that_is_used(win):
    """The controls and the Trigger object must not drift apart."""
    win.trig_mode.setCurrentIndex(0)                      # Off
    assert win.trigger() is None

    win.trig_mode.setCurrentIndex(1)                      # Auto
    win.trig_slope.setCurrentIndex(1)                     # Falling
    win.trig_level.setValue(1.65)
    t = win.trigger()
    assert t is not None and t.mode == "auto" and t.rising is False
    # Volts in, codes out, through the one conversion.
    assert t.level == stream.volts_to_codes(1.65)
    # And that conversion round-trips against the one the trace uses.
    assert abs(float(stream.codes_to_volts(t.level)) - 1.65) < 0.002


def test_the_trigger_line_and_the_spin_box_are_one_control(win):
    """Issue #8's B6: the level has a handle on the plot.

    Two widgets, one number. Moving either must move the other, because
    a line that shows yesterday's level over today's trigger is worse
    than no line - it is a wrong number drawn where the eye is.
    """
    win.trig_mode.setCurrentIndex(1)                      # Auto
    win.view_box.setCurrentIndex(0)                       # Time
    assert win.scope.trigger_line() == pytest.approx(
        win.trig_level.value(), abs=1e-3)

    win.trig_level.setValue(1.0)
    assert win.scope.trigger_line() == pytest.approx(1.0, abs=1e-3)

    # A drag, as the mouse handler delivers it: setPos emits
    # sigPositionChanged, which is the same signal the drag emits.
    win.scope.trig_line.setPos(2.5)
    assert win.trig_level.value() == pytest.approx(2.5, abs=1e-3)
    # And the echo settled rather than ringing: both still agree.
    assert win.scope.trigger_line() == pytest.approx(2.5, abs=1e-3)


def test_the_trigger_line_leaves_when_it_would_lie(win):
    """Off has no level to show; a spectrum's axis is dB and an XY
    plot's is volts-vs-volts, so a volts-at-time level drawn on either
    would be a unit error made visible."""
    win.view_box.setCurrentIndex(0)                       # Time
    win.trig_mode.setCurrentIndex(1)                      # Auto
    assert win.scope.trigger_line() is not None

    win.trig_mode.setCurrentIndex(0)                      # Off
    assert win.scope.trigger_line() is None

    win.trig_mode.setCurrentIndex(1)                      # Auto
    win.view_box.setCurrentIndex(1)                       # Spectrum
    assert win.scope.trigger_line() is None
    win.view_box.setCurrentIndex(2)                       # XY
    assert win.scope.trigger_line() is None

    win.view_box.setCurrentIndex(0)                       # Time again
    assert win.scope.trigger_line() == pytest.approx(
        win.trig_level.value(), abs=1e-3)


def test_the_panel_shows_the_reason_where_a_refused_number_would_be(win):
    """Not a dash, and not the previous value.

    A field that reverts to its last good reading invites a stale number
    being read as a live one, which is the failure docs/status.md
    records more than once - a clean-looking display over data that was
    wrong.
    """
    win.measure.update_from(stream.measure(
        stream.Sweep(np.empty(0, dtype=np.uint16), np.empty(0, dtype=bool)),
        200000))
    assert win.measure.value("vpp_v") == "no data"

    rate, period = 200000, 250
    r = stream.ChannelRing(seconds=0.05, rate_hz=rate)
    r.append(_tone(8000, period))
    win.measure.update_from(stream.measure(stream.select(r, 4000), rate))
    shown = win.measure.value("freq_hz")
    assert shown.startswith("800"), shown

    # And back to a refusal: the good number must not survive.
    r2 = stream.ChannelRing(seconds=0.05, rate_hz=rate)
    r2.append(_tone(2000, period))
    r2.append(_tone(2000, period, phase=2000), discontinuous=True)
    win.measure.update_from(stream.measure(stream.select(r2, 3000), rate))
    assert win.measure.value("freq_hz") == "discontinuity in window"


def test_the_panel_says_which_reference_its_volts_are_in(win):
    """A reading that cannot be attributed is not a measurement.

    The loop is ratiometric, so every volt on screen is scaled by a
    number that came from an instrument this board cannot be.
    """
    text = win.measure.reference.text()
    assert str(stream.ADVREF_MV) in text and stream.ADVREF_SOURCE in text


def test_the_measurements_describe_the_trace_that_was_drawn(win, daemon):
    """Measured over the sweep as drawn, not a second one taken later.

    Two sweeps a frame apart are different data, and a number beside a
    trace that describes a different trace is worse than no number.
    """
    win.connect_to_daemon()
    win.client.call("start", mode="capture", adc_hz=200000, channels=2)
    win.client.wait_frames(10, timeout=15.0)
    win.tick()

    drawn = win.scope.last_sweep
    assert drawn.samples.size > 0
    direct = stream.measure(drawn, win.rate_hz)
    if direct["vpp_v"] is not None:
        assert win.measure.value("vpp_v") == f"{direct['vpp_v']:.4f} V"


def test_switching_to_the_spectrum_relabels_the_axes(win, daemon):
    """A dBFS curve under a Volts axis is a lie a screenshot carries."""
    win.connect_to_daemon()
    win.client.call("start", mode="capture", adc_hz=200000, channels=2)
    win.client.wait_frames(10, timeout=15.0)

    win.view_box.setCurrentIndex(0)
    win.tick()
    assert "Time" in win.scope.plot.getAxis("bottom").labelText

    win.view_box.setCurrentIndex(1)
    win.tick()
    assert "Frequency" in win.scope.plot.getAxis("bottom").labelText
    assert "dBFS" in win.scope.plot.getAxis("left").labelText
    x, y = win.scope.trace()
    assert x is not None and len(x) > 0, "the spectrum drew nothing"


def test_a_dropped_frame_breaks_the_trace_like_an_overrun_does(win):
    """The gap the daemon makes on purpose, not the device's overrun.

    Rule 5 has the daemon drop frames toward a slow client rather than
    block the feeder, so a sequence gap is the *expected* discontinuity
    and not a rare fault. Until this it reached the health panel as a
    counter and reached the ring as nothing at all, so the trace was
    drawn straight across the missing samples and the measurements were
    computed over the join.

    Found by running against the board. The synthetic device never drops
    anything, which is exactly why it could not have found it.
    """
    codes = np.full(64, 2000, dtype=np.uint16)
    win.ingest(stream.decode(make_frame(1, {7: codes, 6: codes})))
    win.ingest(stream.decode(make_frame(2, {7: codes, 6: codes})))
    ring = win.rings[7]
    _s, breaks = ring.window()
    assert not breaks.any(), "consecutive frames must not break the line"

    # seq 4: three is missing.
    win.ingest(stream.decode(make_frame(4, {7: codes, 6: codes})))
    assert win.seq_gaps == 1
    _s, breaks = ring.window()
    assert breaks.any(), (
        "a dropped frame was joined onto the previous one - rule 3 says "
        "never draw across a discontinuity, and rule 5 makes this the "
        "common case rather than a rare one")

    # And the measurements refuse over it rather than measuring the join.
    m = stream.measure(stream.select(ring, ring.filled), 200000)
    assert m["note"] == "discontinuity in window"


def test_both_channels_are_drawn_not_just_the_source(win, daemon):
    """The board captures A0 and A1 in the same frames.

    Drawing one at a time hid the thing they are captured together for:
    docs/frontend.md lists "2ch with DAC1 at mid scale: A1 tone < a few
    codes" as a self-test, and the device's own console prints "A1 must
    read flat, or demux is wrong". Neither is checkable on a display
    that shows one channel.
    """
    win.connect_to_daemon()
    win.client.call("start", mode="capture", adc_hz=200000, channels=2)
    win.client.wait_frames(20, timeout=15.0)
    win.tick()

    assert set(win.rings) >= {stream.CH_A0, stream.CH_A1}
    for tag in (stream.CH_A0, stream.CH_A1):
        x, y = win.scope.trace(tag)
        assert x is not None and len(x) > 0, f"{stream.LABELS[tag]} not drawn"

    # And they are distinguishable, because every trace in this project
    # ends up in a screenshot pasted into a message.
    assert (win.scope.trace_color(stream.CH_A0)
            != win.scope.trace_color(stream.CH_A1))


def test_the_second_channel_shares_the_first_ones_time_axis():
    """Not triggered independently.

    A0 and A1 come from the same frames, so sliding them separately
    would put two moments on one axis and invite reading a phase
    difference the display invented.
    """
    rate = 200000
    a = stream.ChannelRing(seconds=0.05, rate_hz=rate)
    b = stream.ChannelRing(seconds=0.05, rate_hz=rate)
    # Identical content in both, fed in lockstep the way frames arrive.
    for _ in range(4):
        chunk = _tone(1000, 271.0)
        a.append(chunk)
        b.append(chunk)

    sw = stream.select(a, 800, stream.Trigger(level=2048, rising=True))
    assert sw.triggered and sw.end_back > 0, "expected a triggered sub-window"

    other, _breaks = stream.window_like(b, a, sw)
    assert np.array_equal(other, sw.samples), (
        "the second channel was taken from a different offset")


def test_channels_out_of_step_draw_nothing_rather_than_guessing():
    """If the rings hold different amounts, any alignment is a guess."""
    rate = 200000
    a = stream.ChannelRing(seconds=0.05, rate_hz=rate)
    b = stream.ChannelRing(seconds=0.05, rate_hz=rate)
    a.append(_tone(2000, 271.0))
    b.append(_tone(1500, 271.0))          # short by 500

    sw = stream.select(a, 800)
    other, _breaks = stream.window_like(b, a, sw)
    assert other.size == 0


def test_xy_draws_the_path_and_breaks_it_at_a_discontinuity():
    """A chord across a Lissajous figure reads as a real trajectory.

    Worse than the time domain's version: there, a straight segment is
    visibly a join. Here it is a plausible path between two operating
    points, and nothing about it says the data is missing.
    """
    n = 2000
    x = _tone(n, 200.0, amp=900)
    y = _tone(n, 200.0, amp=900, phase=50.0)
    breaks = np.zeros(n, dtype=bool)
    breaks[900] = True

    xs, ys = stream.xy_points(x, y, breaks)
    assert xs.size > 0 and xs.size == ys.size
    assert np.isnan(xs).any() and np.isnan(ys).any(), (
        "the discontinuity did not break the figure")

    # Volts, not codes, through the one conversion.
    finite = xs[np.isfinite(xs)]
    assert 0.0 <= finite.min() and finite.max() <= stream.VREF_V


def test_xy_is_subsampled_not_reduced_to_extremes():
    """min/max per column reduces a function of time. XY is a path, and
    its extremes are not where it went."""
    n = 40000
    x = _tone(n, 2000.0, amp=900)
    y = _tone(n, 2000.0, amp=900, phase=500.0)
    xs, ys = stream.xy_points(x, y, max_points=1000)
    assert 0 < xs.size <= 1000 and xs.size == ys.size


def test_xy_mode_labels_both_axes_with_their_channels(win, daemon):
    win.connect_to_daemon()
    win.client.call("start", mode="capture", adc_hz=200000, channels=2)
    win.client.wait_frames(20, timeout=15.0)

    win.view_box.setCurrentIndex(2)                  # XY
    win.tick()
    assert "A0" in win.scope.plot.getAxis("bottom").labelText
    assert "A1" in win.scope.plot.getAxis("left").labelText
    x, y = win.scope.trace(stream.CH_A0)
    assert x is not None and len(x) > 0, "XY drew nothing"


def test_the_generator_refuses_what_the_dac_cannot_reach():
    """The DAC is not rail-to-rail, and clamping would hide that.

    CLAUDE.md lists "writing zero does not give ground" among the facts
    that are easy to get wrong. A generator that silently clamps an
    over-large request produces a clipped waveform, and a clipped
    waveform on this bench looks exactly like the converter
    misbehaving - a diagnosis this project has paid for more than once.
    """
    from gui import awg

    lo_mv, hi_mv = 578, 2771
    centre = (lo_mv + hi_mv) / 2000.0

    lo, hi, why = awg.plan(1.5, centre, lo_mv, hi_mv)
    assert why is None and lo is not None and hi > lo

    # Wider than the span at any offset.
    _l, _h, why = awg.plan(3.0, centre, lo_mv, hi_mv)
    assert why and "span" in why

    # Fits, but not where it was asked for - and the message names an
    # offset that would work, because that is the number wanted.
    _l, _h, why = awg.plan(1.5, 0.4, lo_mv, hi_mv)
    assert why and "Offset" in why, why

    _l, _h, why = awg.plan(0.0, centre, lo_mv, hi_mv)
    assert why and "above zero" in why


def test_the_generator_maps_volts_onto_the_measured_span():
    """Full-scale request lands on the full code range, and the ends
    correspond to the ends of the measured span."""
    from gui import awg

    lo_mv, hi_mv = 578, 2771
    span_v = (hi_mv - lo_mv) / 1000.0
    lo, hi, why = awg.plan(span_v, (lo_mv + hi_mv) / 2000.0, lo_mv, hi_mv)
    assert why is None
    assert lo == 0 and hi == 4095, (lo, hi)

    # Half amplitude at the centre uses the middle half of the range.
    lo, hi, why = awg.plan(span_v / 2, (lo_mv + hi_mv) / 2000.0, lo_mv, hi_mv)
    assert why is None
    assert abs(lo - 1024) <= 2 and abs(hi - 3071) <= 2, (lo, hi)


def test_the_generator_span_comes_from_the_measurement_not_the_doc():
    """docs/frontend.md still quotes 546-2760, the retired ADC-derived
    pair. The panel must use what the scope measured."""
    from gui import awg
    import calibration as cal

    lo, hi, source = awg.dac_span_mv()
    want = cal.require()["dac_mv"]
    assert source == "measured"
    assert (lo, hi) == (want["span_lo"], want["span_hi"])
    assert (lo, hi) != (want["adc_derived_span_lo"],
                        want["adc_derived_span_hi"])


def test_the_generator_builds_whole_cycles_between_the_codes():
    """A fractional cycle is a step when the buffer repeats, and a step
    the host authored is indistinguishable from one the converter made."""
    import measure as measuremod
    import struct as _struct

    blob, hz = measuremod.build_arb("sine", 1000.0, 200000,
                                    lo_code=1000, hi_code=3000, cycles=3)
    codes = [_struct.unpack("<H", blob[i:i + 2])[0] & 0xFFF
             for i in range(0, len(blob), 2)]
    assert len(codes) % 3 == 0, "not whole cycles"
    assert min(codes) == 1000 and max(codes) == 3000
    assert abs(hz - 1000.0) < 1.0
    # Every sample tagged for DAC0.
    tags = {_struct.unpack("<H", blob[i:i + 2])[0] >> 12
            for i in range(0, len(blob), 2)}
    assert tags == {0}


def test_cursors_measure_the_interval_between_them(win, daemon):
    """dt, its reciprocal, and dV - in the units the axis is in."""
    win.connect_to_daemon()
    win.client.call("start", mode="capture", adc_hz=200000, channels=2)
    win.client.wait_frames(20, timeout=15.0)
    win.timebase.setCurrentIndex(2)                 # 20 ms
    win.tick()

    assert win.cursor_text() is None, "cursors should start off"
    win.act_cursors.setChecked(True)
    win.tick()

    # Place them a known distance apart and check the arithmetic.
    win.scope.set_cursor_positions(0.002, 0.005)      # 2 ms, 5 ms
    r = win.scope.cursor_reading()
    assert abs(r["dx"] - 0.003) < 1e-9
    assert abs(r["inverse"] - 1.0 / 0.003) < 1e-6

    text = win.cursor_text()
    assert "3,000.00 us" in text, text
    assert "333.3 Hz" in text, text

    # The panel is written on redraw, not on drag, so compare after a
    # tick rather than before one.
    win.tick()
    assert win.measure.cursor.text() == win.cursor_text()


def test_cursors_report_the_axis_they_are_on(win, daemon):
    """The same two lines measure seconds in the time view and hertz in
    the spectrum. Labelling a frequency difference "dt" is a small lie
    that a screenshot carries a long way."""
    win.connect_to_daemon()
    win.client.call("start", mode="capture", adc_hz=200000, channels=2)
    win.client.wait_frames(20, timeout=15.0)
    win.act_cursors.setChecked(True)
    win.tick()
    assert "dt" in win.cursor_text()

    win.view_box.setCurrentIndex(1)                   # Spectrum
    win.tick()
    win.scope.set_cursor_positions(1000.0, 4000.0)
    text = win.cursor_text()
    assert "df" in text and "3,000.0 Hz" in text, text
    assert "dt" not in text


def test_a_cursor_on_a_break_reads_nothing_rather_than_a_level():
    """The curve carries NaN where the data is discontinuous, and a
    cursor landing there must not report the number beside it."""
    from gui import scope as scopemod
    xs = np.array([0.0, 1.0, 2.0, 3.0])
    ys = np.array([1.0, np.nan, 2.0, 2.5])

    assert scopemod._sample_at(xs, ys, 0.0) == 1.0
    assert scopemod._sample_at(xs, ys, 1.0) is None      # the break
    assert scopemod._sample_at(xs, ys, 9.0) is None      # off the end


def test_the_export_carries_the_reference_its_volts_are_in(win, daemon, tmp_path):
    """A column of volts is meaningless without the reference.

    ADVREF moved by 0.91% once already in this project, so a file that
    does not say which one it was scaled by cannot be compared with one
    written before or after that. Provenance in the file, not the
    filename.
    """
    win.connect_to_daemon()
    win.client.call("start", mode="capture", adc_hz=200000, channels=2)
    win.client.wait_frames(20, timeout=15.0)
    win.tick()

    out = tmp_path / "sweep.csv"
    n = win._write_csv(str(out), win.scope.last_sweep)
    assert n > 0

    text = out.read_text()
    head = [l for l in text.splitlines() if l.startswith("#")]
    assert any(f"advref_mv={stream.ADVREF_MV}" in l for l in head), head
    assert any(stream.ADVREF_SOURCE in l for l in head), head
    assert any("rate_hz=" in l for l in head), head
    assert any("triggered=" in l for l in head), head

    rows = [l for l in text.splitlines() if l and not l.startswith("#")]
    assert rows[0].startswith("t_s,")
    assert len(rows) == n + 1                      # header plus samples


def test_the_export_marks_discontinuities_as_a_column(win, tmp_path):
    """A join is a column, not a missing row.

    A reader has to be able to see the break rather than infer it from
    a jump in the time step - and the time step does not jump, because
    the samples either side are adjacent in the ring even though they
    are not adjacent in time.
    """
    codes = np.full(64, 2000, dtype=np.uint16)
    win.ingest(stream.decode(make_frame(1, {7: codes, 6: codes})))
    win.ingest(stream.decode(make_frame(3, {7: codes, 6: codes})))   # gap

    ring = win.rings[7]
    sweep = stream.select(ring, ring.filled)
    out = tmp_path / "broken.csv"
    win._write_csv(str(out), sweep)

    rows = [l for l in out.read_text().splitlines()
            if l and not l.startswith("#")]
    header, body = rows[0], rows[1:]
    assert header.endswith("break")
    assert any(r.endswith(",1") for r in body), "the join is not marked"


def test_export_of_an_empty_screen_says_so_rather_than_writing_a_file(win):
    win.export_csv()
    assert "nothing on screen" in win.statusBar().currentMessage()


def test_the_readout_says_whether_it_triggered_not_what_was_asked(win, daemon):
    """Auto free-runs when it finds no edge. The label has to say so.

    This is the whole reason the readout exists: a trace moving because
    the trigger found nothing looks exactly like a trace moving because
    the signal is wrong, and this bench has already spent effort telling
    those apart for a different instrument.
    """
    win.connect_to_daemon()
    win.client.call("start", mode="capture", adc_hz=200000, channels=2)
    win.client.wait_frames(10, timeout=15.0)

    win.trig_mode.setCurrentIndex(0)                      # Off
    win.tick()
    assert win.trigger_state_text() == "free"

    # A level the synthetic device's signal cannot reach, so auto must
    # fall back - and must not claim to have triggered.
    win.trig_mode.setCurrentIndex(1)                      # Auto
    win.trig_level.setValue(stream.VREF_V)                # full scale
    win.tick()
    assert win.trigger_state_text() == "searching", (
        "auto free-ran but the readout claimed a trigger")


def test_the_health_panel_reports_what_it_cost_to_draw(win, daemon):
    win.connect_to_daemon()
    win.client.call("start", mode="capture", adc_hz=200000, channels=2)
    win.client.wait_frames(10, timeout=15.0)
    win.tick()
    win.poll_status()
    assert win.health.value("mode") == "capture"
    assert "/" in win.health.value("frames")
    assert win.health.value("gaps") == "0"
    assert win.health.value("read_gap").endswith("us")
    assert win.health.value("role") == "control"


def test_the_display_shows_the_rate_the_hardware_makes(win, daemon):
    """Rule 1 in docs/frontend.md, at the last place it could be
    broken: what is on screen comes from the frame header."""
    win.connect_to_daemon()
    win.client.call("start", mode="capture", adc_hz=200001, channels=2)
    win.client.wait_frames(5, timeout=15.0)
    win.tick()
    win.poll_status()
    assert win.rate_hz == 201030
    assert "201,030" in win.health.value("rate")


def test_a_sequence_gap_is_counted_and_shown(win, daemon):
    win.connect_to_daemon()
    win.ingest(stream.decode(make_frame(1, {7: [1, 2]})))
    win.ingest(stream.decode(make_frame(5, {7: [3, 4]})))
    win.poll_status()
    assert win.seq_gaps == 1
    assert win.health.value("gaps") == "1"


def test_a_discontinuous_frame_is_counted_for_the_channel_shown(win, daemon):
    win.connect_to_daemon()
    win.ingest(stream.decode(make_frame(1, {7: [1, 2]})))
    win.ingest(stream.decode(
        make_frame(2, {7: [3, 4]}, flags=stream.FLAG_OVERRUN)))
    win.poll_status()
    assert win.rings[7].discontinuities == 1
    assert win.health.value("breaks") == "1"


def test_the_window_survives_the_daemon_going_away(win, daemon):
    """A front end that hangs when the daemon dies is worse than one
    that says so."""
    win.connect_to_daemon()
    daemon.stop()
    win.poll_status()
    assert win.client is None
    assert "stopped answering" in win.statusBar().currentMessage()

# -- replaying a recording --------------------------------------------
#
# The front end does not open the file: the daemon does, and this window
# connects to it like any other source. What is worth asserting here is
# that it says which source it is looking at, and that it stops offering
# the controls a recording cannot answer.


@pytest.fixture
def recording_path(tmp_path):
    """Six frames in the device's own format, with the sidecar the
    recorder writes beside them."""
    import json
    path = str(tmp_path / "bench2.due")
    with open(path, "wb") as f:
        for seq in range(6):
            f.write(make_frame(seq, {7: [2048] * 1016, 6: [2048] * 1016},
                               rate=100000))
    with open(path + ".json", "w") as f:
        json.dump({"device": {"track": "b", "kind": "board"},
                   "mode": "capture", "frame_bytes": devmod.FRAME_BYTES,
                   "rates": {"adc_hz": 100000, "channels": 2},
                   "frames": 6, "dropped": 0, "error": None}, f)
    return path


@pytest.fixture
def replay_daemon(recording_path):
    srv = servermod.Server(devmod.FileDevice(recording_path, pace=False),
                           host="127.0.0.1", port=0).start()
    yield srv
    srv.stop()


@pytest.fixture
def replay_win(qapp, replay_daemon):
    w = MainWindow(host="127.0.0.1", port=replay_daemon.port)
    yield w
    w.disconnect_from_daemon()
    w.close()


def test_the_panel_names_the_recording_it_is_looking_at(replay_win,
                                                        recording_path):
    """The link row has always said which host and port. What it never
    said is what is on the other end, which mattered less when the only
    answers were this board and the synthetic device."""
    replay_win.connect_to_daemon()
    src = replay_win.health.value("source")
    assert os.path.basename(recording_path) in src
    assert "6 frames" in src
    assert "replaying" in replay_win.windowTitle()


def test_a_replay_offers_no_generator_and_no_rate(replay_win):
    """Greyed out because the source cannot answer them, not because
    the features are gone: a recording has no DAC to drive, and its
    samples are at the rate they were taken at."""
    replay_win.connect_to_daemon()
    assert replay_win.replaying is True
    assert not replay_win.awg.isEnabled()
    assert not replay_win.preset.isEnabled()


def test_a_board_still_offers_both(win):
    """The negative, so that the disabling above cannot quietly become
    unconditional."""
    win.connect_to_daemon()
    assert win.replaying is False
    assert win.awg.isEnabled() and win.preset.isEnabled()


def test_disconnecting_from_a_replay_puts_the_controls_back(replay_win):
    replay_win.connect_to_daemon()
    replay_win.disconnect_from_daemon()
    assert replay_win.replaying is False
    assert replay_win.awg.isEnabled() and replay_win.preset.isEnabled()
    assert replay_win.health.value("source") == "-"
    assert replay_win.windowTitle() == "due_oscilloscope"


def test_the_trace_follows_the_rate_in_the_recording(replay_win):
    """The point of replaying through the daemon rather than loading a
    file here: the rate comes out of the frame headers, exactly as it
    does live, so the time axis is the recording's and not this
    window's default."""
    replay_win.connect_to_daemon()
    replay_win.start_capture()
    deadline = time.time() + 10.0
    while replay_win.client.frames_received < 3 and time.time() < deadline:
        time.sleep(0.02)
    replay_win.tick()
    assert replay_win.rate_hz == 100000


def test_starting_the_generator_clears_the_previous_run(win, daemon):
    """Play starts the device, so it must clear what the last run left
    behind - exactly as Start does.

    `docs/frontend.md` rule 2: stale frames from a previous run once
    manufactured a "frozen DAC" that was not happening and cost a full
    session. This window reached that state from a button: Play called
    `start mode=loop` without resetting, so the rings, the sequence-gap
    count and the discontinuity count all carried across, and the old
    samples were drawn as the new run's.
    """
    win.connect_to_daemon()
    win.ingest(stream.decode(make_frame(1, {7: [1000] * 1016,
                                            6: [1000] * 1016})))
    win.ingest(stream.decode(make_frame(5, {7: [1000] * 1016,
                                            6: [1000] * 1016})))
    assert win.rings and win.seq_gaps == 1 and win.frames_shown == 2

    win.awg.vpp.setValue(1.0)
    win.awg.offset.setValue(1.65)
    win.awg_requested("sine", 1000.0, 1.0, 1.65, True)

    assert win.rings == {}, "the previous run's samples survived Play"
    assert win.seq_gaps == 0 and win.frames_shown == 0
    assert win.last_seq is None and win.overruns == 0


def test_a_refused_generator_does_not_clear_anything(win, daemon):
    """The reset belongs after the local checks, not before them. A
    request the panel itself refuses never reaches the device, so there
    is no new run to make room for - and wiping the trace would throw
    away the picture the user was looking at when they mistyped."""
    win.connect_to_daemon()
    win.ingest(stream.decode(make_frame(1, {7: [1000] * 1016,
                                            6: [1000] * 1016})))
    before = dict(win.rings)

    win.awg.vpp.setValue(3.3)          # cannot be centred on this span
    win.awg.offset.setValue(0.1)
    assert win.awg.code_range()[2] is not None, "expected a refusal"
    win.awg_requested("sine", 1000.0, 3.3, 0.1, True)

    assert win.rings == before


# -- the daemon session -----------------------------------------------
#
# Driven without a window at all, which is the whole reason it is a
# separate object: the daemon-facing half is the part a new maintainer
# most needs to touch and was the part most tangled with Qt.


@pytest.fixture
def session(qapp, daemon):
    from gui.session import DaemonSession
    s = DaemonSession("127.0.0.1", daemon.port)
    yield s
    s.close()


def pump(win, seconds=10.0, until=None):
    """Run the window by hand for a while.

    No Qt event loop runs under pytest, so the 30 Hz redraw and the 4 Hz
    poll never fire on their own. Anything that waits for frames to
    arrive has to turn the crank itself.
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        win.tick()
        win.poll_status()
        if until is not None and until():
            return True
        time.sleep(0.02)
    return until is None or until()


def collect(signal):
    """Record what a signal emits, as a list of argument tuples."""
    seen = []
    signal.connect(lambda *args: seen.append(args))
    return seen


def test_the_session_reports_a_refusal_and_keeps_the_link(session):
    """A refusal and a loss are different things, and conflating them is
    what five separate `except` blocks in the window used to do. The
    device saying no leaves the link exactly where it was."""
    refusals = collect(session.refused)
    gone = collect(session.disconnected)
    assert session.open("control")

    assert session.call("start", mode="capture", adc_hz=10_000_000) is None
    assert len(refusals) == 1
    op, message = refusals[0]
    assert op == "start" and message, "the device's own message is empty"
    assert session.is_open and not gone
    # And the link really is usable, not merely marked open.
    assert session.call("ping") is not None


def test_a_dead_daemon_closes_the_session_and_says_why(session, daemon):
    """The other outcome. It is not a refusal, must not read as one, and
    the window has to be told to stop drawing."""
    refusals = collect(session.refused)
    gone = collect(session.disconnected)
    assert session.open("control")
    daemon.stop()

    assert session.call("ping") is None
    assert not session.is_open
    assert len(gone) == 1 and "stopped answering" in gone[0][0]
    assert not refusals, "a dead daemon was reported as a refusal"
    # Every later call is a no-op rather than a second failure.
    assert session.call("ping") is None
    assert len(gone) == 1


def test_a_connect_that_never_lands_reports_and_leaves_no_link(qapp):
    from gui.session import DaemonSession
    s = DaemonSession("127.0.0.1", 1)              # nothing listens on 1
    failed = collect(s.connect_failed)
    assert s.open("control") is False
    assert not s.is_open
    assert len(failed) == 1
    # The message has to carry the way out, not just the fact.
    assert "python3 -m daemon --fake" in failed[0][0]


def test_the_poll_path_does_not_shout_about_a_refusal(session):
    """`counters` costs the board a console round trip and may refuse
    while playback runs. A refusal there is a dash on a panel, not
    something to say out loud four times a second - but a lost link
    still is."""
    refusals = collect(session.refused)
    assert session.open("observer")

    # An observer may not drive the device, so this is a real refusal.
    assert session.call_quiet("start", mode="capture") is None
    assert not refusals
    assert session.is_open


def test_closing_twice_emits_once(session):
    gone = collect(session.disconnected)
    session.open("control")
    session.close()
    session.close()
    assert len(gone) == 1 and gone[0][0] == ""


# -- the run state ----------------------------------------------------


def test_reset_clears_everything_a_new_run_must_not_inherit():
    """The shape test, and the reason the state is one object.

    Compared field by field against a state that has never seen a frame,
    so an eighth number added to `AcquisitionState` and forgotten in
    `reset()` fails here rather than by drawing the previous run's
    samples as this one's - which is what the two-places version did.
    """
    fresh = vars(stream.AcquisitionState())

    acq = stream.AcquisitionState()
    for seq in (1, 2, 7):                      # 7 makes a gap
        acq.ingest(stream.decode(make_frame(seq, {7: [1000] * 1016,
                                                  6: [3000] * 1016})))
    assert acq.rings and acq.seq_gaps == 1 and acq.frames_shown == 3
    acq.reset()

    assert vars(acq) == fresh


def test_the_rate_survives_a_reset_because_it_is_not_the_runs():
    """It describes how the device is configured, not what this run did,
    and the first frame of the next run corrects it either way.
    Re-defaulting it would put 200 kHz on the panel for a bench that is
    not running at 200 kHz."""
    acq = stream.AcquisitionState()
    acq.ingest(stream.decode(make_frame(1, {7: [2048] * 1016},
                                        rate=100000)))
    assert acq.rate_hz == 100000
    acq.reset()
    assert acq.rate_hz == 100000


def test_a_sequence_gap_breaks_the_ring_without_a_widget():
    """The rule that needed a board to find - frames dropped between the
    daemon and the window were counted and then drawn straight across -
    asserted where it lives, rather than through a window."""
    acq = stream.AcquisitionState()
    def feed(seq):
        return acq.ingest(stream.decode(make_frame(seq, {7: [1000] * 1016})))

    assert feed(1) is False
    assert feed(2) is False
    assert feed(9) is True
    assert acq.seq_gaps == 1
    assert acq.discontinuities(7) == 1
    assert acq.discontinuities(6) == 0, "a channel with no ring is not a break"


# -- the layer rule ---------------------------------------------------


def test_the_compute_layer_has_no_qt():
    """`gui/stream.py` is what makes 60-odd headless tests possible, and
    it stays that way only if something checks. A stray `from PySide6
    import QtCore` for one convenience is how a module like this stops
    being importable without a display, and nothing else would notice
    until the suite needed one."""
    import subprocess
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys, os; sys.path.insert(0, os.getcwd()); "
         "import gui.stream; "
         "print(any(m.startswith('PySide6') for m in sys.modules))"],
        cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False", "Qt reached gui/stream.py"


# -- menus, toolbar and shortcuts --------------------------------------


def test_a_verb_is_one_object_in_every_place_it_appears():
    """Menu item, toolbar button and shortcut are one `QAction`.

    Three objects would have to be enabled three times, and the one that
    got forgotten would be a button that still looks pressable while the
    window is not connected.
    """
    from PySide6 import QtGui
    win = MainWindow()
    try:
        device = [m for m in win.menuBar().findChildren(QtWidgets.QMenu)
                  if m.title() == "&Device"][0]
        assert win.act_start in device.actions()
        assert win.act_start in win.toolbar.actions()

        win.act_start.setEnabled(True)
        button = win.toolbar.widgetForAction(win.act_start)
        assert button.isEnabled()
        win.act_start.setEnabled(False)
        assert not button.isEnabled(), "the toolbar kept its own copy"
        assert isinstance(win.act_start, QtGui.QAction)
    finally:
        win.close()


def test_every_shortcut_carries_a_modifier():
    """A bare key belongs to whichever widget has focus.

    Space opens a focused combo box and a digit types into the trigger
    level, so a bare-key shortcut works right up until someone clicks a
    control - which is worse than one that reads as slightly formal.
    This is the kind of rule that only holds if something checks.
    """
    from PySide6 import QtCore, QtGui
    win = MainWindow()
    try:
        bare = []
        for act in win.findChildren(QtGui.QAction):
            for seq in act.shortcuts():
                if not seq.count():
                    continue
                if seq[0].keyboardModifiers() == QtCore.Qt.NoModifier:
                    bare.append((act.text(), seq.toString()))
        assert not bare, f"bare-key shortcuts: {bare}"
    finally:
        win.close()


def test_run_stop_follows_the_device_and_not_the_last_button(win, daemon):
    """A replay that reaches the end of its file stops without anyone
    asking. A Run key that tracked which button was pressed last would
    then be asking the daemon to start something already started."""
    win.connect_to_daemon()
    win.start_capture()
    win.poll_status()
    assert win.device_running is True

    win.toggle_run()                       # running -> stop
    win.poll_status()
    assert win.device_running is False

    win.toggle_run()                       # idle -> start
    win.poll_status()
    assert win.device_running is True


def test_the_view_menu_and_the_view_box_cannot_disagree(win):
    """The menu sets the combo rather than holding a second copy of the
    setting, so there is nothing to keep in step."""
    win.set_view("xy")
    assert win.view_box.currentData() == "xy"
    win.set_view("time")
    assert win.view_box.currentData() == "time"
    win.set_view("not a view")             # ignored, not an exception
    assert win.view_box.currentData() == "time"


def test_the_timebase_steps_and_stops_at_the_ends(win):
    """Wrapping would take 1 ms to 2 s on one keypress, which on a
    rolling display looks like the signal changed."""
    win.timebase.setCurrentIndex(0)
    win.step_timebase(-1)
    assert win.timebase.currentIndex() == 0
    win.step_timebase(+1)
    assert win.timebase.currentIndex() == 1

    win.timebase.setCurrentIndex(win.timebase.count() - 1)
    win.step_timebase(+1)
    assert win.timebase.currentIndex() == win.timebase.count() - 1


# -- opening a recording from the window -------------------------------


def test_opening_a_recording_starts_a_daemon_and_connects(win,
                                                          recording_path):
    """The window starts a daemon and connects to it; it does not read
    the file. Same rule as "the daemon writes the file, not the GUI" -
    what this adds is only that you no longer have to leave the program
    to do it."""
    win.connect_to_daemon()
    home_port = win.port

    win.replay(recording_path)

    assert win.client is not None, "never connected to the replay daemon"
    assert win.replaying is True
    assert win.port != home_port, "still pointed at the daemon it started on"
    assert win.replay_child is not None and win.replay_child.poll() is None
    assert os.path.basename(recording_path) in win.windowTitle()

    child = win.replay_child
    win.connect_home()
    assert child.poll() is not None, "the replay daemon was left running"
    assert win.port == home_port
    assert win.replay_child is None


def test_a_recording_the_daemon_refuses_never_becomes_a_connection(
        win, tmp_path):
    """The daemon checks the file before it binds a port, so a child
    that has exited is carrying the useful message - and "could not
    reach a daemon" would bury it under the symptom."""
    bad = str(tmp_path / "notaframe.due")
    with open(bad, "wb") as f:
        f.write(b"nowhere near a frame")

    win.replay(bad)

    assert win.client is None
    assert win.replay_child is None, "a refused replay left a process behind"
    assert win.notice.showing
    assert "no whole frames" in win.notice.text, win.notice.text


# -- a refusal that stays ----------------------------------------------


def test_a_refusal_outlives_the_next_status_poll(win, daemon):
    """The defect this fixes, stated as the test.

    `showMessage` was the only error channel and the 4 Hz status poll
    writes to it too, so the device's own refusal - the one message rule
    4 says to show - could be gone in 250 ms.
    """
    win.connect_to_daemon()
    win.session.call("start", mode="capture", adc_hz=10_000_000)
    assert win.notice.showing
    first = win.notice.text
    assert "start refused" in first

    for _ in range(4):
        win.poll_status()
    assert win.notice.text == first, "the poll overwrote the refusal"


def test_a_refusal_is_not_a_dialog(win, daemon, monkeypatch):
    """A modal is the one presentation a refusal cannot survive: it names
    a limit worth reading twice, and a dialog is gone the moment it is
    acknowledged. This used to raise one for `start` and not for the
    same refusal of the same op from the generator panel."""
    def boom(*a, **k):
        raise AssertionError("a refusal opened a dialog")

    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", boom)
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", boom)
    win.connect_to_daemon()
    win.session.call("start", mode="capture", adc_hz=10_000_000)
    assert win.notice.showing


def test_a_new_run_clears_the_last_refusal(win, daemon):
    """A notice that outlived the thing it was about would be the same
    defect as a counter that did."""
    win.connect_to_daemon()
    win.session.call("start", mode="capture", adc_hz=10_000_000)
    assert win.notice.showing
    win.start_capture()
    assert not win.notice.showing


def test_a_notice_can_be_dismissed(win):
    win.notice.error("something")
    assert win.notice.showing
    win.notice.dismiss.click()
    assert not win.notice.showing
    assert win.notice.text == ""


# -- replay transport --------------------------------------------------


def test_the_replay_bar_is_only_up_for_a_recording(win, replay_win):
    """A board has no position, and a progress bar against one would be
    inventing a number."""
    win.connect_to_daemon()
    assert win.replay_bar.isHidden()

    replay_win.connect_to_daemon()
    assert not replay_win.replay_bar.isHidden()
    replay_win.disconnect_from_daemon()
    assert replay_win.replay_bar.isHidden()


def test_the_replay_bar_counts_frames_not_percent(replay_win):
    """Frames, because that is the unit the sidecar, the daemon's
    `frames_read` and the health panel all quote, and a percentage would
    be the one number here that does not join up with the rest."""
    replay_win.connect_to_daemon()
    replay_win.start_capture()
    pump(replay_win, until=lambda: replay_win.replay_bar.bar.maximum() > 1)

    assert replay_win.replay_bar.bar.maximum() == 6      # the fixture's frames
    assert "frames" in replay_win.replay_bar.bar.format()


def test_the_position_is_where_in_the_file_and_not_how_many_were_sent():
    """The replayed count runs on across a loop while the file starts
    again, so where in the file that is has to come out of how many
    times it wrapped. Asserted on the widget rather than through a
    daemon, because the arithmetic is the thing that can be wrong."""
    from gui.replay_bar import ReplayBar
    bar = ReplayBar()
    bar.set_position({"frames": 14, "frames_total": 6, "loops": 2,
                      "at_end": False})
    assert bar.bar.maximum() == 6
    assert bar.bar.value() == 2                    # 14 - 2*6
    assert bar.state.text() == "pass 3"

    bar.set_position({"frames": 6, "frames_total": 6, "loops": 0,
                      "at_end": True})
    assert bar.bar.value() == 6 and bar.state.text() == "at the end"

    # A board's counters carry no frames_total, and must leave it alone
    # rather than reset it to a position of zero.
    bar.set_position({"frames": 900, "underruns": 0})
    assert bar.bar.value() == 6


def test_the_end_of_a_recording_says_so(replay_win):
    """A recording ends on its own, which on a board only ever happens
    because something went wrong. A trace that stopped for the ordinary
    reason should not read as a fault."""
    replay_win.connect_to_daemon()
    replay_win.start_capture()
    assert pump(replay_win, until=lambda: replay_win.notice.showing)

    assert replay_win.device_running is False
    assert "End of the recording" in replay_win.notice.text


def test_restart_plays_the_recording_again(replay_win):
    """`start` on a device that is already running is refused, by the
    fake and by the board alike, so Restart has to stop first."""
    replay_win.connect_to_daemon()
    replay_win.start_capture()
    # Both, and not just the notice: `at_end` can arrive on the poll
    # before the tick that drains the last frames, and this test is
    # about what a second pass does to the first pass's numbers.
    assert pump(replay_win, until=lambda: (replay_win.notice.showing
                                           and replay_win.frames_shown == 6))

    replay_win.replay_bar.restart_btn.click()
    assert not replay_win.notice.showing, "the end-of-file notice survived"
    assert replay_win.frames_shown == 0, "the last pass was not cleared"

    played_again = pump(replay_win,
                       until=lambda: replay_win.frames_shown == 6)
    assert played_again, "the recording did not play again"


# ------------------------------------------------------------------
# The four functions issue #8's A3 moved out of the window.
#
# The point of these is not coverage - three of them were already
# exercised through a MainWindow. It is that they can now be exercised
# *without* one, which is what "compute in stream.py, draw in a widget"
# buys and the only way to tell whether the move actually happened. If
# any of these grows a widget again, these tests stop compiling before
# the rule stops being true.
# ------------------------------------------------------------------


def test_cursor_text_labels_the_axis_it_is_reading():
    """Seconds in the time view, hertz in the spectrum, volts in XY.

    Labelling a frequency difference "dt" is the small lie the docstring
    warns about, and it is the kind a screenshot carries a long way.
    """
    assert stream.cursor_text(None) is None

    t = stream.cursor_text({"view": "time", "dx": 1.5e-6,
                            "inverse": 666666.7, "dy": 0.25})
    assert t.startswith("dt 1.50 us"), t
    assert "1/dt 666,666.7 Hz" in t
    assert "dV +0.2500 V" in t

    f = stream.cursor_text({"view": "spectrum", "dx": 12345.6,
                            "inverse": None, "dy": -3.5})
    assert "df 12,345.6 Hz" in f and "dA -3.50 dB" in f
    assert "dt" not in f, "a frequency difference must not be called dt"

    xy = stream.cursor_text({"view": "xy", "dx": 0.5,
                             "inverse": None, "dy": -0.25})
    assert "dX 0.5000 V" in xy and "dY -0.2500 V" in xy


def test_cursor_text_omits_the_second_line_when_there_is_no_dy():
    """A missing reading is absent, not zero - the two mean different
    things and a cursor pair on one axis has no dy at all."""
    t = stream.cursor_text({"view": "time", "dx": 1e-6,
                            "inverse": None, "dy": None})
    assert "dV" not in t and "1/dt" not in t
    assert t == "dt 1.00 us"


def test_trigger_state_text_separates_asked_for_from_happened():
    """The distinction the label exists for: auto that found no edge is
    free-running, and a trace moving for that reason looks exactly like
    a trace moving because the signal is wrong."""
    assert stream.trigger_state_text("off", False) == "free"
    assert stream.trigger_state_text("off", True) == "free"
    assert stream.trigger_state_text("auto", True) == "TRIG"
    assert stream.trigger_state_text("auto", False) == "searching"


def test_describe_source_names_a_replay_by_its_path():
    """Replay is the answer that needed this function - "a board" and
    "the synthetic device" were distinguishable without it."""
    s = stream.describe_source({"kind": "file", "path": "cap.due",
                                "frames": 1234,
                                "recorded": {"track": "b"}})
    assert "cap.due" in s and "1,234 frames" in s and "track b" in s

    # `fake` is not a track anyone should be told about.
    s = stream.describe_source({"kind": "file", "path": "x.due",
                                "frames": 2, "recorded": {"track": "fake"}})
    assert "track" not in s

    assert stream.describe_source({"kind": "board", "track": "a"}) \
        == "board (track a)"
    assert stream.describe_source({"kind": "synthetic"}) == "synthetic"


def test_write_csv_carries_the_reference_it_scaled_by(tmp_path):
    """Provenance in the file, not the filename.

    A column of volts is meaningless without ADVREF, and this project
    has had ADVREF move by 0.91% under figures already written down.
    """
    import numpy as np

    n = 8
    sweep = stream.Sweep(samples=np.full(n, 2048, dtype=np.uint16),
                         breaks=np.zeros(n, dtype=bool),
                         triggered=True)
    path = tmp_path / "out.csv"
    written = stream.write_csv(str(path), sweep, source=stream.CH_A0,
                               rings={}, rate_hz=453488)
    assert written == n

    text = path.read_text()
    head = [l for l in text.splitlines() if l.startswith("#")]
    assert any("advref_mv={}".format(stream.ADVREF_MV) in l for l in head), head
    assert any(stream.ADVREF_SOURCE in l for l in head), head
    assert any("rate_hz=453488" in l for l in head), head
    assert any("triggered=True" in l for l in head), head

    rows = [l for l in text.splitlines() if l and not l.startswith("#")]
    assert rows[0].startswith("t_s,"), rows[0]
    assert rows[0].endswith(",break"), rows[0]
    assert len(rows) == n + 1


def test_write_csv_marks_a_discontinuity_as_a_column(tmp_path):
    """A break is a column and not a missing row: the reader has to see
    the join rather than infer it from a time step."""
    import numpy as np

    n = 4
    breaks = np.zeros(n, dtype=bool)
    breaks[2] = True
    sweep = stream.Sweep(samples=np.full(n, 1000, dtype=np.uint16),
                         breaks=breaks, triggered=False)
    path = tmp_path / "b.csv"
    stream.write_csv(str(path), sweep, source=stream.CH_A0,
                     rings={}, rate_hz=1000)

    rows = [l for l in path.read_text().splitlines()
            if l and not l.startswith("#")][1:]
    assert len(rows) == n
    assert [r.split(",")[-1] for r in rows] == ["0", "0", "1", "0"]


# ------------------------------------------------------------------
# Issue #8's C1: the panels' read APIs, and the rule that keeps them
# the only way in.
#
# Moving 24 assertions off `_labels[...]` is only half of it. Without
# something asserting the boundary, the next test written reaches
# through the private name again - which is how the debt accumulated in
# the first place, one reasonable-looking test at a time.
# ------------------------------------------------------------------


def test_no_gui_test_reaches_past_a_panel_read_api():
    """The boundary, asserted on this file.

    The panels' private label dictionary was load-bearing: every reader
    of a label indexed straight into it and called `.text()`, so
    renaming a private broke the tests of a project that does not
    otherwise care how a panel stores its widgets. That is the wrong way
    round, and it is why `NoticeBar` and `ReplayBar` were built with
    read properties from the start.

    Note that this docstring cannot spell the forbidden forms either -
    the check reads the whole file, so naming them here would make the
    explanation the offender. They are in `banned` below, assembled from
    fragments.

    Checked textually rather than by import, because what is being
    protected is how the *tests* are written.
    """
    import re
    with io.open(__file__, encoding="utf-8") as fh:
        text = fh.read()

    # Assembled from fragments so this file does not itself contain the
    # strings it forbids. Spelling them out here made the test its own
    # first offender, which is funny once and then just a false alarm
    # everyone learns to ignore.
    labels = "." + "_labels" + "["
    banned = {
        labels: "panel.value(key)",
        ".scope." + "curve.getData(": "scope.trace()",
        ".scope." + "curves[": "scope.trace(tag) / scope.trace_color(tag)",
        ".scope." + "cursors[": "scope.set_cursor_positions(a, b)",
    }
    offenders = []
    for frag, instead in banned.items():
        start = 0
        while True:
            i = text.find(frag, start)
            if i < 0:
                break
            offenders.append("line %d: %s -> use %s"
                             % (text.count("\n", 0, i) + 1, frag, instead))
            start = i + 1
    assert not offenders, (
        "GUI tests reaching past a panel's read API:\n  "
        + "\n  ".join(offenders))


def test_the_read_apis_answer_for_every_field_the_panel_has(win):
    """A read API that silently returns None for a real field is worse
    than the private access it replaced, because a test asserting
    `value(key) is None` would pass on a typo."""
    for key in win.health.keys():
        assert win.health.value(key) is not None, (
            "health.value(%r) is None but %r is one of the panel's own "
            "fields" % (key, key))
    for key in win.measure.keys():
        assert win.measure.value(key) is not None, (
            "measure.value(%r) is None but %r is one of the panel's own "
            "fields" % (key, key))

    # And an unknown key answers None rather than raising, so a test
    # that asks the wrong question gets a clear failure.
    assert win.health.value("no_such_field") is None
    assert win.measure.value("no_such_field") is None


def test_scope_trace_returns_what_is_drawn(win, daemon):
    """`trace()` is the active channel and `trace(tag)` is a named one,
    and they agree when the named one is active."""
    win.connect_to_daemon()
    win.start_capture()
    assert pump(win, until=lambda: win.frames_shown > 0)

    x, y = win.scope.trace()
    assert x is not None and len(x) > 0, "nothing was drawn"

    xa, ya = win.scope.trace(stream.CH_A0)
    assert len(xa) == len(x)

    assert win.scope.trace("not a channel") == (None, None)
    assert win.scope.trace_color("not a channel") is None


# ------------------------------------------------ the daemon's pushed events

def test_a_pushed_device_error_reaches_the_notice_bar(win, daemon):
    """The event stream had no reader in the window at all.

    `client.events` was drained only by `wait_event()`, which lives in
    `tests/test_daemon_api.py`, so every event the daemon pushed to the
    front end accumulated in a 1024-entry deque and expired when it
    wrapped. `device_error` is the one message `docs/frontend.md` rule 4
    says to show, and it was reaching the client object and stopping
    there.
    """
    win.connect_to_daemon()
    assert win.client is not None
    daemon.broadcast_event("device_error", message="the converter stopped")

    for _ in range(50):
        win.poll_status()
        if win.notice.showing:
            break
        time.sleep(0.02)

    assert win.notice.showing, (
        "a device_error the daemon pushed never reached the notice bar")
    assert "the converter stopped" in win.notice.text


def test_a_waveform_refusal_surfaces_rather_than_expiring(win, daemon):
    """The case `Session.send_awg`'s docstring already claimed.

    It says a waveform refusal "surfaces through the daemon's event
    stream and not here". The daemon does push it - `_handle_awg`
    answers with `error/refused` and no `id`, so the client files it
    under events rather than replies - and before the drain existed it
    surfaced nowhere. The docstring was the only place the behaviour
    was.
    """
    win.connect_to_daemon()
    daemon.broadcast_event("error", code="refused",
                           message="this build has no generator")

    for _ in range(50):
        win.poll_status()
        if win.notice.showing:
            break
        time.sleep(0.02)

    assert "this build has no generator" in win.notice.text


def test_an_error_reply_is_not_rendered_twice(win, daemon):
    """An `error` carrying an `id` is a reply, and has its own path.

    `host/daemon/client.py` files anything with an `id` under replies,
    where `Session._call` turns it into the `refused` signal. Only
    unsolicited events reach `_on_event`, so the two renderers cannot
    both fire for one refusal.
    """
    win.connect_to_daemon()
    c = win.client
    before = len(c.events)
    # An op the daemon will refuse, sent as a call so the refusal
    # carries our id.
    try:
        c.call("nonsense_op")
    except Exception:
        pass
    assert len(c.events) == before, (
        "a refusal answering a call landed in the event stream; it would "
        "now be rendered by both _on_refused and _on_event")


def test_state_events_do_not_reach_the_notice_bar(win, daemon):
    """`started`/`stopped`/`recording` are already on the health panel.

    Repeating them in the notice bar is the noise that made
    `statusBar().showMessage()` useless, which is why `gui/notice.py`
    exists at all.
    """
    win.connect_to_daemon()
    win.notice.clear()
    for name in ("started", "stopped", "recording", "recorded", "awg_ok"):
        daemon.broadcast_event(name)
    for _ in range(5):
        win.poll_status()
        time.sleep(0.02)
    assert not win.notice.showing, (
        f"a state event was rendered as a notice: {win.notice.text!r}")


# -- the window must not state a device state that is not the device's --
#
# Two faults found by photographing the front end for the wiki, which
# turns out to be a good way to catch them: a screenshot puts two panels
# side by side and they either agree or they do not. Both were the same
# shape - a control asserting something the hardware was not doing.

def test_a_refused_generator_request_does_not_leave_the_button_reading_stop(
        qapp):
    """Issue #37.

    `_validate` unchecks Play when the settings become impossible, but
    the button's text is written only in `_emit` - so it kept reading
    "Stop" while the panel showed refused values and the *previous*
    waveform went on playing. Three statements about the generator, two
    of them wrong, and the button was the loudest of the three.

    The panel alone, with nothing connected to `requested`: attaching a
    window means the request round-trips to a device that cannot play
    it, which unchecks the button for a different reason and hides the
    thing under test.
    """
    from gui import awg

    panel = awg.AwgPanel()
    mid = (panel.lo_mv + panel.hi_mv) / 2000.0
    panel.vpp.setValue(0.5)
    panel.offset.setValue(mid)
    qapp.processEvents()
    assert panel.code_range()[2] is None, "precondition: settings are legal"

    panel.run_btn.setChecked(True)
    qapp.processEvents()
    assert panel.run_btn.text() == "Stop", "precondition: it reads as running"

    # More swing than the DAC has. The panel refuses locally, before
    # anything reaches a device.
    panel.vpp.setValue(3.0)
    qapp.processEvents()

    assert panel.run_btn.isChecked() is False
    assert panel.run_btn.isEnabled() is False
    assert panel.run_btn.text() == "Play", (
        "a refused request left the button claiming the generator is "
        "running")
    assert "span" in panel.note.text(), "the refusal should name the limit"


def test_the_rate_control_is_disabled_while_the_generator_owns_the_rate(
        win, daemon, qapp):
    """Issue #36.

    `start_capture` sends the Rate preset, but the generator runs the
    device in loop mode where the preset is ignored and the rate comes
    from the generator. The combo went on displaying the user's pick:
    one screenshot had `Rate 50 kHz` in the toolbar against
    `Rate (actual) 200,000 Hz` in Health, a factor of four apart.
    """
    win.connect_to_daemon()
    assert win.preset.isEnabled(), "precondition: selectable when idle"

    win._rate_control_follows_generator(True)
    assert not win.preset.isEnabled(), (
        "the Rate control still offers a rate the generator has "
        "overridden")
    assert "Health" in win.preset.toolTip(), (
        "a disabled control should say where the real rate is")

    win._rate_control_follows_generator(False)
    assert win.preset.isEnabled()
    assert win.preset.toolTip() == ""


def test_a_replay_still_owns_the_rate_control(win, qapp):
    """The generator fix must not undo the replay one.

    `setEnabled(not replay)` disabled this for recordings first, and a
    recording has exactly one rate - it is in the frames. Re-enabling it
    when the generator stops would hand back a control the file does not
    honour.
    """
    win.replaying = True
    win.preset.setEnabled(False)
    win._rate_control_follows_generator(False)
    assert not win.preset.isEnabled(), (
        "stopping the generator re-enabled a control a recording owns")


def test_starting_a_capture_replaces_the_previous_run_s_message(
        win, daemon, qapp):
    """Issue #39.

    `start_capture` clears the refusal notice and then said nothing, so
    the status bar kept whatever the last run had put there. The gallery
    caught the plainest form of it: stop the generator, start a plain
    capture, and a live run at 50,000 Hz sits underneath the words
    "generator stopped".

    Same family as #36 and #37 - a widget stating a device state that is
    not the device's - and the argument is already written three lines
    above the omission, about `self.notice`.
    """
    win.connect_to_daemon()
    win.statusBar().showMessage("generator stopped")

    win.start_capture()
    qapp.processEvents()
    said = win.statusBar().currentMessage()
    assert "generator" not in said, (
        f"a capture is running under a sentence about the generator: "
        f"{said!r}")
    assert "capturing" in said, said

    win.stop_capture()
    qapp.processEvents()
    assert win.statusBar().currentMessage() == "stopped", (
        "stopping left the running message on screen")


def test_the_call_timeout_outlives_the_daemon_s_own_worst_case():
    """Issue #42.

    `BoardDevice.start` drains the console with `cap=5.0` before issuing
    the run command, and the first start after a connect pays close to
    the whole cap - the programming port was just opened, which asserts
    NRSTB, so the board is resetting and printing its banner. Measured
    on windows-desk: first start 5.53 s, every later one 0.93 s.

    The client timeout was also 5.0, so the first Start lost the race
    every time and the window reported "daemon stopped answering" about
    a board whose correct reply arrived half a second later.

    The two numbers are not independent, and this test is here to say so
    out loud: one of them is a bound on the other.
    """
    from gui import session as sessionmod
    drain_cap = 5.0                      # devmod's own constant
    assert sessionmod.CALL_TIMEOUT > drain_cap, (
        f"a call timeout of {sessionmod.CALL_TIMEOUT} cannot outlast a "
        f"daemon that is allowed to spend {drain_cap} draining before it "
        f"even sends the command")


def test_noise_on_an_undriven_pin_is_not_a_signal_to_be_timed():
    """Issue #43, as a target rather than as a description.

    Nothing in the suite fails while the swing floor is wrong, so
    whoever sets the constant has nothing to check against. This is that
    check, and it deliberately encodes the *requirement* rather than
    this bench's number: noise of a realistic amplitude must not be
    reported as a waveform, whatever the reference or the gain.

    The amplitude is taken from a measurement, not invented. On
    `windows-desk`, 1240 consecutive 20 ms windows of an undriven DAC
    output pin - A1 while the host feeds DAC0 only - spanned 45 to 52
    codes peak-to-peak, and the whole distribution fits inside seven
    codes. `records/issue43-quiet-window-windows.jsonl`. The floor is
    10, so every one of those windows clears it by a factor of four and
    the panel will happily time them: measured on the board, an
    undriven pin read 9,523.8 Hz at 1.2 % duty, to five figures, with
    nothing on screen marking it as different from a real reading.

    Uniform noise rather than a captured window on purpose - a
    board-free test should not carry one bench's samples, and the
    property under test is not specific to this bench's noise shape.

    Marked strict, so that fixing #43 fails this test until the xfail is
    removed with it. A silently-passing xfail is how a fixed defect
    keeps a test that no longer tests anything.
    """
    rng = np.random.default_rng(20260830)
    rate = 200000
    # 52 codes peak-to-peak about mid-scale: the worst quiet window
    # measured, and still four times the floor.
    codes = rng.integers(2048 - 26, 2048 + 27, size=4000, dtype=np.uint16)

    r = stream.ChannelRing(seconds=0.05, rate_hz=rate)
    r.append(codes)
    m = stream.measure(stream.select(r, 4000), rate)

    assert m["freq_hz"] is None, (
        f"timed an undriven pin at {m['freq_hz']} Hz from "
        f"{int(codes.max() - codes.min())} codes of noise")
    assert m["period_s"] is None
    assert m["duty"] is None
    assert m["note"], "a refusal has to say why"


def test_the_noise_guard_is_a_ratio_not_an_amplitude():
    """Issue #43: why the fix is a shape statistic and not a constant.

    The old guard was `MEASURE_MIN_SWING_CODES`, an absolute number of
    codes, and `windows-desk` failed three times to choose a defensible
    value because the quantity it gates is not stable: several discrete
    levels within a session, drifting between sessions, and not selected
    by capture rate, by prior DAC activity or by source amplitude.

    An amplitude constant has to track all of that. A ratio does not, and
    this pins the property: white noise reads the same peakedness across
    a 250x range of amplitude, so no bench's noise level can put it on
    the wrong side of the threshold.
    """
    rng = np.random.default_rng(43)
    seen = []
    for pk in (8, 52, 200, 800, 2000):
        codes = rng.integers(2048 - pk // 2, 2048 + pk // 2 + 1,
                             size=4000, dtype=np.uint16)
        seen.append(stream._spectral_peakedness(codes.astype(np.int32)))
    assert max(seen) < stream.MEASURE_MIN_PEAKEDNESS, (
        f"noise peakedness {max(seen):.1f} reaches the threshold "
        f"{stream.MEASURE_MIN_PEAKEDNESS}")
    assert max(seen) / min(seen) < 2.0, (
        f"peakedness moved from {min(seen):.2f} to {max(seen):.2f} across "
        f"a 250x amplitude range; it is not scale-free after all, which "
        f"is the whole reason it replaced an absolute floor")


def test_a_real_waveform_still_gets_timed():
    """The guard must not cost the measurements it protects.

    Including a narrow pulse train, which the duty-cycle check proposed
    on #43 would have rejected - a 2 % duty signal is a legitimate
    waveform with a real period, and its midpoint-referenced duty is
    genuinely 2 %.
    """
    rate = 200000
    n = 4000
    t = np.arange(n)
    rng = np.random.default_rng(44)
    p = n / 20.0
    cases = {
        "sine": 2048 + 800 * np.sin(2 * np.pi * t / p),
        "square": 2048 + 800 * np.sign(np.sin(2 * np.pi * t / p)),
        "ramp": 1248 + 1600 * ((t % p) / p),
        "narrow pulse 2% duty": np.where((t % p) < 0.02 * p, 2848, 1248),
    }
    for name, wave in cases.items():
        codes = np.clip(wave + rng.normal(0, 3, n), 0, 4095)
        codes = codes.round().astype(np.uint16)
        r = stream.ChannelRing(seconds=0.05, rate_hz=rate)
        r.append(codes)
        m = stream.measure(stream.select(r, n), rate)
        assert m["freq_hz"] is not None, (
            f"{name} was refused a frequency: note={m['note']!r}, "
            f"peakedness="
            f"{stream._spectral_peakedness(codes.astype(np.int32)):.1f}")
        assert abs(m["freq_hz"] - rate / p) / (rate / p) < 0.05, (
            f"{name} timed at {m['freq_hz']:.1f} Hz, expected "
            f"{rate / p:.1f}")


def test_a_small_but_real_signal_survives_the_guard():
    """The threshold has to leave room below anything worth timing.

    12 codes peak-to-peak is under 10 mV and well inside the noise of
    the benches measured on #43, and it is still unmistakably periodic.
    A guard that rejected this would have traded one wrong answer for
    another.
    """
    rate, n = 200000, 4000
    t = np.arange(n)
    rng = np.random.default_rng(45)
    codes = (2048 + 6 * np.sin(2 * np.pi * t / (n / 20.0))
             + rng.normal(0, 0.5, n))
    codes = np.clip(codes, 0, 4095).round().astype(np.uint16)
    assert stream._spectral_peakedness(codes.astype(np.int32)) > \
        stream.MEASURE_MIN_PEAKEDNESS
