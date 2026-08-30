#!/usr/bin/env python3
"""Capture the wiki's screenshot gallery, reproducibly, from a live board.

Every image the wiki shows is produced by this script against a real
device, so the gallery can be re-taken when the UI changes rather than
being a set of hand-curated pictures that quietly go stale. That matters
here more than in most projects: a screenshot is a figure, and this
project's rule is that a figure carries its bench and its date.

**Native Qt, not offscreen.** The offscreen platform has no fonts and
renders every label as tofu - structurally correct and completely
unreadable, which is worse than no screenshot because it looks like a
rendering bug in the application. Checked, not assumed.

**The broken shots are the point, not an embarrassment.** A gallery of
clean traces demonstrates a UI; a gallery that also shows the DAC
clipping at a rail it cannot cross, a square that is a trapezoid because
it is past the amplitude ceiling, a rectangular FFT window smearing a
tone that does not fit it, and a stalled main loop being reported by a
heartbeat - that demonstrates an instrument whose limits are known and
displayed. Each of those is captioned with why it looks that way, so a
reader learns the limit rather than mistaking it for a defect.

    .venv-gui/Scripts/python.exe tools/gallery.py --out wiki/img
    .venv-gui/Scripts/python.exe tools/gallery.py --fake      # no board
"""
import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "host"))

# Before any Qt import. An inherited QT_QPA_PLATFORM=offscreen - which
# the test suite sets - would silently produce a gallery of tofu.
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6 import QtWidgets                       # noqa: E402
from daemon import device as devmod                 # noqa: E402
from daemon import server as srvmod                 # noqa: E402
from gui.app import MainWindow                      # noqa: E402


class Gallery:
    def __init__(self, win, app, outdir, bench, index):
        self.win, self.app, self.out = win, app, outdir
        self.bench = bench
        self.index = index

    def pump(self, seconds):
        """Turn the crank. No Qt event loop runs here, so the 30 Hz
        redraw and the 4 Hz poll have to be driven by hand - the same
        reason `tests/test_gui.py` has a `pump`."""
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()
            self.win.tick()
            time.sleep(0.02)

    def shot(self, name, title, why, settle=1.2, widget=None):
        self.pump(settle)
        w = widget or self.win
        path = os.path.join(self.out, f"{name}.png")
        if not w.grab().save(path):
            raise RuntimeError(f"could not save {path}")
        self.index.append({"file": f"{name}.png", "title": title,
                           "why": why, "bench": self.bench,
                           "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        print(f"  {name}.png  {title}", flush=True)

    # -- helpers over the window's own controls ----------------------
    def combo(self, box, data):
        i = box.findData(data)
        if i < 0:
            raise RuntimeError(f"no such option {data!r}")
        box.setCurrentIndex(i)
        self.app.processEvents()

    def awg(self, shape=None, hz=None, vpp=None, offset=None, apply=True):
        """Set the generator, and actually send it.

        **Changing a control does not re-upload the waveform.** The panel
        emits `requested` only when the Play button toggles, so setting
        Shape to Triangle while a sine is playing leaves the sine on the
        wire and the word "Triangle" on the screen. The first run of this
        script captured exactly that - four shapes, one sine, four
        confident captions - which is a figure saying something the data
        does not. Toggling off and on re-sends.
        """
        a = self.win.awg
        if shape is not None:
            self.combo(a.shape, shape)
        if hz is not None:
            a.hz.setValue(hz)
            if a.hz.value() != hz:
                print(f"    ! frequency clamped to {a.hz.value()} "
                      f"(asked {hz})", flush=True)
        if vpp is not None:
            a.vpp.setValue(vpp)
        if offset is not None:
            a.offset.setValue(offset)
        self.app.processEvents()
        if apply and a.run_btn.isChecked():
            a.run_btn.click()            # stop
            self.pump(0.4)
            a.run_btn.click()            # play: re-uploads
            self.pump(0.6)


def build(args):
    index = []
    if args.fake:
        dev = devmod.FakeDevice(pace=True)
        bench = "fake device (no board)"
    else:
        import measure
        board = measure.Board(settle=3.0)
        dev = devmod.BoardDevice(board)
        bench = os.environ.get("DUE_BENCH", "windows-desk")

    srv = srvmod.Server(dev, host="127.0.0.1", port=0).start()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    win = MainWindow(host="127.0.0.1", port=srv.port)
    win.resize(1600, 950)
    win.show()
    g = Gallery(win, app, args.out, bench, index)
    os.makedirs(args.out, exist_ok=True)

    try:
        win.connect_to_daemon()
        g.pump(1.0)

        # 1. The loop, which is what this instrument *is*.
        g.awg(shape="sine", hz=1000.0, vpp=1.5, offset=1.675)
        win.awg.run_btn.click()
        g.pump(2.0)
        g.shot("01-loop-sine", "The closed loop: HOST -> DAC0 -> A0 -> HOST",
               "A sine asked for in the Generator panel and captured back "
               "on A0 in the same window. Nothing else here is a "
               "simulation: the host builds the samples, the DAC plays "
               "them, the ADC reads the pin, and the trace is what came "
               "back over USB.")

        # 2. Shapes.
        for shape in ("sine", "square", "triangle", "ramp"):
            g.awg(shape=shape, hz=1000.0, vpp=1.5)
            g.shot(f"02-shape-{shape}", f"Generator: {shape}",
                   f"A {shape} at 1 kHz, 1.5 Vpp, captured through the "
                   f"loop. The shape is built on the host and streamed to "
                   f"the DAC, so an arbitrary waveform is the same path.")

        # 3. The limits, which is where the broken shots start.
        g.awg(shape="sine", hz=1000.0, vpp=3.0, offset=1.675)
        g.shot("03-clip-rail",
               "Asking for more swing than the DAC has: refused, with the number",
               "**Deliberately impossible, and the front end says so rather "
               "than clipping.** The Due's DAC is not rail-to-rail - it "
               "spans 578-2771 mV, measured on this bench and printed in "
               "the panel - so 3.0 Vpp cannot be produced. The generator "
               "refuses in red, naming the limit it would have broken: "
               "*3.000 V peak-to-peak is more than the DAC's 2.193 V "
               "span*, and the previous trace stays on screen untouched. "
               "A silently clipped sine would have looked like a signal.")

        g.awg(shape="square", hz=1000.0, vpp=1.5)
        g.shot("04-square-clean", "Square at 1 kHz: a square",
               "Well inside the DAC's step rate, so the edges are edges. "
               "Compare with the next image.")

        g.awg(shape="square", hz=20000.0)
        g.shot("05-square-fast",
               "Square at 20 kHz, which is as fast as this panel will ask",
               "**The front end clamps before the hardware does.** The "
               "frequency box stops at 20 kHz, so the interesting "
               "ceilings are not reachable from here at all: docs/awg.md "
               "records four of them and they disagree - full amplitude "
               "survives to ~400-450 kHz while a *recognisable* square "
               "only reaches ~100-200 kHz, and at 407 kHz Vpp is still "
               "100% with no flat top left. 'Amplitude fell to 68%' and "
               "'the square became a triangle' are the same number and "
               "different findings. Reaching them needs the console, "
               "which is a gap in this panel rather than in the board.")

        # 4. Views.
        g.awg(shape="sine", hz=1000.0, vpp=1.5)
        g.combo(win.view_box, "time")
        g.shot("06-view-time", "Time view", "The default.")
        g.combo(win.view_box, "spectrum")
        g.combo(win.fft_window, "hann")
        g.shot("07-view-spectrum-hann", "Spectrum, Hann window",
               "The same tone as a spectrum. Hann is the safe default.")
        g.combo(win.fft_window, "rectangular")
        g.shot("08-view-spectrum-rect",
               "Spectrum, rectangular window: the tone smeared",
               "**Deliberately the wrong window.** Rectangular is exact "
               "only when the analysis window holds a whole number of "
               "cycles and smears the tone everywhere else. The window "
               "control has that in its tooltip; this is what it looks "
               "like when ignored, and why a spectrum without its window "
               "named is not a measurement.")
        g.combo(win.view_box, "xy")
        g.shot("09-view-xy", "XY view",
               "A0 against A1. With DAC1 carrying the bench sync, this "
               "draws the loop rather than plotting it against time.")
        g.combo(win.view_box, "time")

        # 5. Rates and timebases.
        for label, key in (("50 kHz", "1"), ("200 kHz", "3"),
                           ("max in-spec", "5")):
            g.combo(win.preset, key)
            g.pump(1.5)
            g.shot(f"10-rate-{key}", f"Capture preset: {label}",
                   "The rate shown in Health is the one the frame header "
                   "reports, not the one that was asked for. Every rate "
                   "this hardware has is 39 MHz divided by an integer, so "
                   "asking for a round number gets the nearest divider.")
        for label, secs in (("1 ms", 0.001), ("100 ms", 0.1), ("2 s", 2.0)):
            g.combo(win.timebase, secs)
            g.shot(f"11-timebase-{label.replace(' ', '')}",
                   f"Timebase: {label}",
                   "The display keeps a ring in seconds, so the timebase "
                   "chooses how much of it to draw.")

        # 6. Trigger.
        g.combo(win.timebase, 0.005)
        for mode, why in (
                ("off", "Free-runs. The trace holds still only when the "
                        "rate divides evenly into the frame - which is a "
                        "missing front-end feature, not a signal defect."),
                ("auto", "Triggers when it can and free-runs when it "
                         "cannot. The usable default."),
                ("normal", "Holds the last trace rather than drawing an "
                           "untriggered one, so a lost trigger is visible "
                           "as a frozen screen instead of a rolling mess.")):
            g.combo(win.trig_mode, mode)
            g.shot(f"12-trigger-{mode}", f"Trigger mode: {mode}", why)
        g.combo(win.trig_mode, "auto")

        # 7. Integrity - the panel most instruments do not show at all.
        g.shot("13-health", "Health: every counter that can contradict the trace",
               "Built first, not last. Sequence gaps, discontinuities, "
               "device overruns, frames dropped to this client, and the "
               "read/feed/fan-out gap maxima. Every one exists because "
               "something once looked right on screen while the data was "
               "wrong - a clean `seq_gaps=0 crc_bad=0 under=0` has "
               "coexisted with a badly degraded signal more than once "
               "here. Invariant 5: overruns are counted and flagged, "
               "never silently spliced.",
               widget=win.health)

        g.shot("14-measure", "Measure, with its reference stated",
               "Vpp, mean, RMS, frequency, period and duty. The panel "
               "prints 'ADVREF 3270 mV, measured' because every volt on "
               "screen came from an ADC code and the reference was "
               "measured rather than assumed - 3300 was an assumption "
               "until a scope settled it.",
               widget=win.measure)

        win.awg.run_btn.click()          # stop playback
        g.pump(0.8)
    finally:
        try:
            win.disconnect_from_daemon()
        except Exception:                            # noqa: BLE001
            pass
        srv.stop()
        try:
            dev.close()
        except Exception:                            # noqa: BLE001
            pass

    with open(os.path.join(args.out, "index.json"), "w") as fh:
        json.dump(index, fh, indent=2)
        fh.write("\n")
    print(f"\n{len(index)} images -> {args.out}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "build", "gallery"))
    ap.add_argument("--fake", action="store_true",
                    help="synthetic device, for checking the script "
                         "without occupying a bench")
    return build(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
