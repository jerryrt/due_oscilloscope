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
    assert win.scope.curve.getData()[0] is not None
    assert len(win.scope.curve.getData()[0]) > 0, "nothing was drawn"


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
    assert win.measure._labels["vpp_v"].text() == "no data"

    rate, period = 200000, 250
    r = stream.ChannelRing(seconds=0.05, rate_hz=rate)
    r.append(_tone(8000, period))
    win.measure.update_from(stream.measure(stream.select(r, 4000), rate))
    shown = win.measure._labels["freq_hz"].text()
    assert shown.startswith("800"), shown

    # And back to a refusal: the good number must not survive.
    r2 = stream.ChannelRing(seconds=0.05, rate_hz=rate)
    r2.append(_tone(2000, period))
    r2.append(_tone(2000, period, phase=2000), discontinuous=True)
    win.measure.update_from(stream.measure(stream.select(r2, 3000), rate))
    assert win.measure._labels["freq_hz"].text() == "discontinuity in window"


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
        assert win.measure._labels["vpp_v"].text() == f"{direct['vpp_v']:.4f} V"


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
    x, y = win.scope.curve.getData()
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
        x, y = win.scope.curves[tag].getData()
        assert x is not None and len(x) > 0, f"{stream.LABELS[tag]} not drawn"

    # And they are distinguishable, because every trace in this project
    # ends up in a screenshot pasted into a message.
    assert (win.scope.curves[stream.CH_A0].opts["pen"].color().name()
            != win.scope.curves[stream.CH_A1].opts["pen"].color().name())


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
    x, y = win.scope.curves[stream.CH_A0].getData()
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
    win.scope.cursors[0].setPos(0.002)                # 2 ms
    win.scope.cursors[1].setPos(0.005)                # 5 ms
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
    win.scope.cursors[0].setPos(1000.0)
    win.scope.cursors[1].setPos(4000.0)
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
    src = replay_win.health._labels["source"].text()
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
    assert replay_win.health._labels["source"].text() == "-"
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
        win, tmp_path, monkeypatch):
    """The daemon checks the file before it binds a port, so a child
    that has exited is carrying the useful message - and "could not
    reach a daemon" would bury it under the symptom."""
    said = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning",
                        lambda *a, **k: said.append(a[2]))
    bad = str(tmp_path / "notaframe.due")
    with open(bad, "wb") as f:
        f.write(b"nowhere near a frame")

    win.replay(bad)

    assert win.client is None
    assert win.replay_child is None, "a refused replay left a process behind"
    assert said and "no whole frames" in said[0], said
