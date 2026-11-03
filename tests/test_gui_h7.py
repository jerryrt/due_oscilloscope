"""The front end on a simulated H7 (docs/20): the window takes the device's sample format, channels and defaults from its description,
draws CH1 and CH2 in volts through their own calibration, and puts the Due's format back afterwards. The format is global state, so the
fixture restores it. Needs the GUI venv (PySide6, numpy) and a host C compiler for the simulated unit; without them it SKIPS, which is not a pass."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
np = pytest.importorskip("numpy", reason="needs the GUI venv: this skip is NOT a pass")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", reason="needs PySide6: this skip is NOT a pass")

import pacing                                            # noqa: E402
from daemon import h7sim                                 # noqa: E402
from daemon import server as servermod                   # noqa: E402
from gui import stream                                   # noqa: E402
from gui.app import MainWindow, PRESETS                           # noqa: E402

pytestmark = pytest.mark.skipif(not h7sim.available(), reason="no host C compiler for the simulated H7: this skip is NOT a pass")


@pytest.fixture(scope="session")
def qapp():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def h7win(qapp):
    srv = servermod.Server(h7sim.make_sim_device(pace=True), host="127.0.0.1", port=0).start()
    w = MainWindow(host="127.0.0.1", port=srv.port)
    yield w, srv
    w.disconnect_from_daemon(); w.close(); srv.stop()
    stream.set_format(stream.DUE_FORMAT)                  # never leak another device's format into the next test


def pump(qapp, cond, timeout=pacing.QUICK):
    import time
    end = time.time() + timeout
    while time.time() < end:
        qapp.processEvents()
        if cond():
            return True
        pacing.pause(pacing.POLL)
    return False


def connect(qapp, w):
    w.connect_to_daemon()
    assert w.client is not None
    assert pump(qapp, lambda: stream.current_format().name == "h7"), "the window never took the device's format"


def test_the_window_becomes_an_h7_window_and_draws_both_channels_in_volts(qapp, h7win):
    w, srv = h7win
    connect(qapp, w)
    assert stream.LABELS == {1: "CH1", 2: "CH2"}
    assert [w.channel.itemText(i) for i in range(w.channel.count())] == ["CH1", "CH2"]
    lo, hi = stream.y_range(); assert lo < -14 and hi > 14                                # bipolar, +-14 V at gain 0
    assert w.trig_level.minimum() < -14 and abs(w.trig_level.value()) < 1e-9              # centred on 0 V, not on VREF/2
    w.start_capture()
    frames = w.client.wait_frames(10, timeout=pacing.NORMAL)
    w.tick()
    assert w.frames_shown >= 10 and set(w.scope.curves) == {1, 2}
    assert 1 in w.rings and 2 in w.rings and w.rings[1].filled > 0 and w.rings[2].filled > 0, "a channel never reached the display"
    assert len(w.scope.trace()[0]) > 0, "nothing was drawn"
    # the synthetic unit sends a 1 V and a 0.5 V sine, in each channel's own calibration: the GUI's volts must recover them
    f = stream.decode(frames[0])
    v1 = stream.codes_to_volts(f.channels[1], tag=1); v2 = stream.codes_to_volts(f.channels[2], tag=2)
    assert abs(float(np.max(np.abs(v1))) - 1.0) < 0.004 and abs(float(np.max(np.abs(v2))) - 0.5) < 0.004      # tight enough to see CH2's own zero (9 mV from CH1's)


def test_a_start_from_the_window_sends_the_devices_own_defaults_and_no_due_preset(qapp, h7win):
    w, srv = h7win
    connect(qapp, w)
    sent = {}
    real = w.session.call
    w.session.call = lambda op, **kw: (sent.update({op: kw}), real(op, **kw))[1]
    w.start_capture()
    assert sent["start"]["adc_hz"] == 1_000_000 and sent["start"]["channels"] == 2 and sent["start"]["preset"] is None


def test_a_dues_description_puts_the_due_format_back(qapp, h7win):
    w, srv = h7win
    connect(qapp, w)
    w._apply_format({"kind": "board", "track": "b"})          # what a Due's description looks like
    assert stream.current_format() is stream.DUE_FORMAT and stream.LABELS == {7: "A0", 6: "A1"}
    assert [w.channel.itemText(i) for i in range(w.channel.count())] == ["A0", "A1"]
    assert stream.y_range() == (0.0, stream.VREF_V) and set(w.scope.curves) == {7, 6}


def test_the_rate_box_offers_the_h7_its_one_rate_and_the_due_its_list_again(qapp, h7win):
    """G1: the Due's presets are firmware commands the H7's start ignores, so the box must not offer them for an H7 - it names the
    rate the description starts at, disabled - and a Due description must bring the whole list back, enabled."""
    w, srv = h7win
    connect(qapp, w)
    assert [w.preset.itemText(i) for i in range(w.preset.count())] == ["1 MHz"]
    assert not w.preset.isEnabled()
    w._apply_format({"kind": "board"})                              # a Due's description has no sample format
    assert [w.preset.itemText(i) for i in range(w.preset.count())] == [label for label, _ in PRESETS]
    assert w.preset.isEnabled()


def test_xy_on_an_h7_plots_ch1_against_ch2_and_names_both_axes(qapp, h7win):
    """G4: the XY view found its second channel from the Due's tags 7 and 6, so on an H7 (tags 1 and 2) it drew nothing."""
    w, srv = h7win
    connect(qapp, w)
    w.start_capture()
    w.client.wait_frames(20, timeout=pacing.NORMAL)
    w.view_box.setCurrentIndex(2)                                   # XY
    w.channel.setCurrentIndex(0)                                    # CH1 is the source
    w.tick()
    assert "CH1" in w.scope.plot.getAxis("bottom").labelText and "CH2" in w.scope.plot.getAxis("left").labelText
    x, y = w.scope.trace(1)
    assert x is not None and len(x) > 0, "XY drew nothing on an H7"
    w.channel.setCurrentIndex(1)                                    # and CH2 as the source
    w.tick()
    assert "CH2" in w.scope.plot.getAxis("bottom").labelText and "CH1" in w.scope.plot.getAxis("left").labelText
    x, y = w.scope.trace(2)
    assert x is not None and len(x) > 0, "XY drew nothing with CH2 as the source"


def test_the_measure_panel_names_the_h7s_calibration_not_the_dues_adc_reference(qapp, h7win):
    """G6: 'ADVREF 3270 mV, measured' is a Due fact; the H7's volts come from its own calibration, which the description states."""
    w, srv = h7win
    assert "ADVREF" in w.measure.reference.text()                   # a Due until a device says otherwise
    connect(qapp, w)
    text = w.measure.reference.text()
    assert "ADVREF" not in text and "factory scale" in text
