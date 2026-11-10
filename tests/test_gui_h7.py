"""The front end on a simulated H7 (docs/20): the window takes the device's sample format, channels and defaults from its description,
draws CH1 and CH2 in volts through their own calibration, and puts the Due's format back afterwards. The format is global state, so the
fixture restores it. Needs the GUI venv (PySide6, numpy) and a host C compiler for the simulated unit; without them it SKIPS, which is not a pass."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
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


def test_the_generator_panel_works_in_volts_about_zero_inside_the_swing_cap_on_an_h7(qapp, h7win):
    """G2: the panel mapped the Due's 0.55-2.75 V window onto 12-bit codes, so an H7 sine of 1 Vpp at 0 V was refused with "108800 codes
    outside 1706..2366". On an H7 it plans in volts about 0 V against the cap in the description, still refuses (never clamps), and a Due
    description gives the old panel back."""
    from gui import awg
    w, srv = h7win
    assert "DAC0" in w.awg.title()
    connect(qapp, w)
    assert "VOUT" in w.awg.title() and w.awg.offset.value() == 0.0 and w.awg.offset.minimum() < 0
    w.awg.vpp.setValue(1.0); w.awg.offset.setValue(0.0)
    lo, hi, why = w.awg.code_range()
    assert why is None and (lo, hi) == (2048 - 84, 2048 + 84), (lo, hi, why)           # 0.5 V / 5.983 mV per code, about 84 codes
    assert w.awg.run_btn.isEnabled()
    w.awg.vpp.setValue(3.9); w.awg.offset.setValue(0.2)                                  # +-1.95 V about 0.2 V: 2.15 V is past the cap
    why = w.awg.code_range()[2]
    assert why and "Offset" in why and not w.awg.run_btn.isEnabled() and "Offset" in w.awg.note.text()
    assert "swing cap" in (awg.plan_h7(4.0, 0.0, 5.983, 330)[2] or "")                    # more than the cap at any offset
    assert awg.plan_h7(1.0, 0.0, 5.983, 330)[:2] == (lo, hi)
    w._apply_format({"kind": "board"})
    assert "DAC0" in w.awg.title() and w.awg.offset.minimum() == 0.0


def test_playing_the_generator_while_the_h7_captures_stops_and_restarts_it_in_loop_mode(qapp, h7win):
    """G3: the H7 refuses a start while it runs ("already running; stop first"), where the Due restarts, so the generator button did
    nothing during capture. The window stops first and the unit ends in loop mode (the played sine itself is read on the real unit)."""
    w, srv = h7win
    connect(qapp, w)
    w.start_capture()
    w.client.wait_frames(5, timeout=pacing.NORMAL)
    assert pump(qapp, lambda: w.device_running)
    w.awg.vpp.setValue(1.0); w.awg.offset.setValue(0.0); w.awg.hz.setValue(1000.0)
    w.awg.run_btn.setChecked(True)                                                       # the user presses Play while capturing
    assert w.awg.run_btn.isChecked(), "the generator was refused"
    assert pump(qapp, lambda: srv.device.mode == "loop", timeout=pacing.NORMAL), "the unit never went to loop mode"


def test_the_inputs_panel_sets_gain_and_coupling_and_the_volts_follow_the_gain_in_force(qapp, h7win):
    """G7: no gain or coupling control, and volts were the gain-0 calibration only. The panel offers each channel's gain and coupling, a
    start sends them, the start reply's description replaces the format, and the unit's 1 V sine still reads 1 V at another gain."""
    w, srv = h7win
    assert not w.inputs.isVisibleTo(w)                                   # a Due (the default) has none
    connect(qapp, w)
    assert w.inputs.isVisibleTo(w) and sorted(w.inputs.gain) == [1, 2]
    lo0, hi0 = stream.y_range()
    w.inputs.gain[1].setCurrentIndex(w.inputs.gain[1].findData(2)); w.inputs.coupling[2].setCurrentIndex(w.inputs.coupling[2].findData("ac"))
    w.channel.setCurrentIndex(1)                                          # CH2 stays selected across the format change
    w.start_capture()
    assert pump(qapp, lambda: srv.device.running)
    cfg = srv.device._config()
    assert (cfg[3], cfg[4], cfg[5]) == (2, 0, 1), cfg                     # CH1 gain 2, CH2 gain 0, CH1 dc / CH2 ac
    assert w.channel.currentData() == 2
    frames = w.client.wait_frames(5, timeout=pacing.NORMAL)
    f = stream.decode(frames[-1])
    v1 = stream.codes_to_volts(f.channels[1], tag=1)
    assert abs(float(np.max(np.abs(v1))) - 1.0) < 0.01, "CH1's 1 V sine does not read 1 V at gain 2: the scale did not follow the gain"
    assert stream.y_range() == (lo0, hi0)                                 # CH2 is still at gain 0: the plot spans the largest range in force
    assert pump(qapp, lambda: w.device_running)                           # the window knows it is running (its poll)
    w.inputs.gain[2].setCurrentIndex(w.inputs.gain[2].findData(4))        # changing a gain while capturing restarts with it
    assert pump(qapp, lambda: srv.device.running and srv.device._config()[4] == 4, timeout=pacing.NORMAL)
    assert pump(qapp, lambda: stream.y_range()[1] < 4.0), "the plot range did not shrink to the gains in force (2 and 4)"
    w._apply_format({"kind": "board"})
    assert not w.inputs.isVisibleTo(w) and w.inputs.options() == {}


def test_the_spectrum_view_shows_the_selected_channel_only_and_nothing_stale_from_the_time_view(qapp, h7win):
    """G5: the spectrum is of the selected channel on a Due too (one source, one curve). On an H7 the other channel's curve still held its
    time-domain trace, drawn on the frequency axis, and `self.curve` stayed on whatever channel was last the source."""
    w, srv = h7win
    connect(qapp, w)
    w.start_capture()
    w.client.wait_frames(20, timeout=pacing.NORMAL)
    w.tick()
    assert len(w.scope.trace(1)[0]) > 0 and len(w.scope.trace(2)[0]) > 0          # the time view drew both
    w.channel.setCurrentIndex(1)                                                  # CH2 is the source
    w.view_box.setCurrentIndex(1)                                                 # Spectrum
    w.tick()
    f2, db2 = w.scope.trace(2)
    assert f2 is not None and len(f2) > 0 and float(np.max(f2)) > 1000.0, "CH2's spectrum was not drawn on CH2's own curve"
    f1 = w.scope.trace(1)[0]
    assert f1 is None or len(f1) == 0, "CH1 still holds its time-domain trace on the frequency axis"


def test_record_export_and_replay_of_an_h7_stream_keep_its_format_with_the_file_dialogs_patched(qapp, h7win, tmp_path, monkeypatch):
    """G9, T5: record and CSV export open a native file dialog, which hangs a headless run; the dialogs are patched to return a path. The
    recording of version-4 frames then replays through the daemon's FileDevice and the window comes up as an H7 again, volts and all."""
    w, srv = h7win
    rec, csv = str(tmp_path / "h7.due"), str(tmp_path / "sweep.csv")
    dialogs = iter([(rec, ""), (csv, "")])
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: next(dialogs))
    connect(qapp, w)
    w.start_capture()
    assert pump(qapp, lambda: w.act_record.isEnabled())
    w.act_record.setChecked(True)                                           # the action's toggled signal calls toggle_record
    w.client.wait_frames(30, timeout=pacing.NORMAL)
    w.act_record.setChecked(False)
    assert os.path.getsize(rec) > 0, "the recording is empty"
    w.tick(); w.export_csv()
    lines = open(csv, encoding="utf-8").read().splitlines()
    assert len(lines) > 10 and any("CH1" in l for l in lines[:12]), lines[:6]
    stream.set_format(stream.DUE_FORMAT)                                    # a fresh window state: the replay must bring the H7 back itself
    w._apply_format({"kind": "board"})
    w.replay(rec)
    # a replay's description says kind "file", so the format is recognised by what it carries: two labelled 16-bit channels in volts
    assert pump(qapp, lambda: stream.LABELS == {1: "CH1", 2: "CH2"}, timeout=pacing.NORMAL), "the replay of an H7 recording did not bring back the H7's channels"
    assert stream.FULL_SCALE_CODES == 65535 and stream.y_range()[1] > 14
    w.start_capture()
    assert w.client.wait_frames(5, timeout=pacing.NORMAL), "the replay served no frames"
    w.tick()
    assert set(w.scope.curves) == {1, 2} and w.rings[1].filled > 0
    w._stop_replay_child()


def test_the_trigger_level_is_converted_with_the_source_channels_own_calibration(qapp, h7win):
    """T4: `trigger()` turned the level in volts into codes with the lowest channel's zero and scale, whatever the source. CH2's zero is 26
    codes from CH1's, and at different gains the scales differ by the gain ratio, so a CH2 trigger at 0.5 V fired at another voltage."""
    w, srv = h7win
    connect(qapp, w)
    w.inputs.gain[1].setCurrentIndex(w.inputs.gain[1].findData(2))                # CH1 gain 2, CH2 stays at gain 0
    w.start_capture()
    assert pump(qapp, lambda: srv.device.running and srv.device._config()[3] == 2)
    w.trig_level.setValue(0.5)
    for tag in (1, 2):
        w.channel.setCurrentIndex(w.channel.findData(tag))
        volts = float(stream.codes_to_volts([w.trigger().level], tag=tag)[0])
        assert abs(volts - 0.5) < 0.001, f"CH{tag}: a 0.5 V trigger level sits at {volts:.4f} V in that channel's own calibration"


def test_the_cursors_read_the_selected_channel_in_every_view(qapp, h7win):
    """T4: the cursor's y values come from `scope.curve`, which only XY and the spectrum set. In the time view with CH2 selected they read
    whichever curve was last used (CH1, a 1 V sine, against CH2's 0.5 V)."""
    w, srv = h7win
    connect(qapp, w)
    w.start_capture()
    w.client.wait_frames(20, timeout=pacing.NORMAL)
    w.view_box.setCurrentIndex(0)
    w.trig_mode.setCurrentIndex(w.trig_mode.findData("off"))
    w.timebase.setCurrentIndex(0)
    for idx, amp in ((0, 1.0), (1, 0.5)):
        w.channel.setCurrentIndex(idx)
        w.tick()
        w.scope.set_cursors(True)
        xs, ys = w.scope.curves[idx + 1].getData()
        peak = int(np.argmax(ys))
        w.scope.set_cursor_positions(float(xs[peak]), float(xs[peak]) + 1e-4)
        r = w.scope.cursor_reading()
        assert r["y1"] is not None and abs(r["y1"] - amp) < 0.05 * amp + 0.02, f"CH{idx + 1}: the cursor read {r['y1']} V, the channel peaks at {amp} V"
        w.scope.set_cursors(False)
