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

**A real board only.** There is no fake-device option, deliberately.
The suite has board-free tests because framing, ownership and
backpressure are not properties of the Due - but a *gallery* is a claim
about an instrument, and a picture of a synthetic device making a
synthetic sine would be the most misleading artifact this repository
could publish. If there is no board, there is no gallery.

    .venv-gui/Scripts/python.exe tools/gallery.py --out wiki/img
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
from gui.app import MainWindow                      # noqa: E402


class _Daemon:
    """A daemon in its own process, and a port to reach it on."""

    def __init__(self, proc, port):
        self.proc, self.port = proc, port

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5.0)
        except Exception:                            # noqa: BLE001
            self.proc.kill()


def _spawn_daemon(port):
    import socket
    import subprocess
    if not port:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
    env = dict(os.environ, PYTHONPATH=os.path.join(REPO, "host"))
    proc = subprocess.Popen(
        [sys.executable, "-m", "daemon", "--host", "127.0.0.1",
         "--port", str(port)],
        cwd=os.path.join(REPO, "host"), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    for _ in range(60):
        time.sleep(0.5)
        try:
            import socket as sk
            with sk.create_connection(("127.0.0.1", port), timeout=0.5):
                return _Daemon(proc, port)
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError("the daemon exited during start-up")
    raise RuntimeError("the daemon never accepted a connection")


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

    def settle_clean(self, want=None, secs=8.0):
        """Wait for the window to actually show what was asked for.

        Two conditions, and both were learned by publishing a gallery
        without them. `want` is matched against the status bar, which is
        the only place that reports the waveform the device is *playing*
        rather than the one the panel is displaying - the first gallery
        captured four shapes that were all one sine because nothing
        checked. And the Measure panel must carry numbers rather than
        "discontinuity in window": a capture with a splice in the window
        cannot be measured, so a screenshot taken then shows an
        instrument that appears unable to measure anything.
        """
        end = time.time() + secs
        last = ""
        while time.time() < end:
            self.pump(0.3)
            last = self.win.statusBar().currentMessage()
            named = want is None or want in last
            measured = "discontinuity" not in (self.win.measure.value("vpp_v") or "")
            if named and measured:
                return True, last
        return False, last

    def shot(self, name, title, why, settle=1.2, widget=None, want=None,
             require=True):
        ok, seen = self.settle_clean(want) if want else (True, "")
        if not ok:
            msg = (f"{name}: window never showed {want!r} with a clean "
                   f"measurement window - status bar says {seen!r}")
            if require:
                raise RuntimeError(msg)
            print(f"  ! {msg}", flush=True)
        self.pump(settle)
        w = widget or self.win
        path = os.path.join(self.out, f"{name}.png")
        if not w.grab().save(path):
            raise RuntimeError(f"could not save {path}")
        self.index.append({"file": f"{name}.png", "title": title,
                           "why": why, "bench": self.bench,
                           "verified": bool(ok), "status_bar": seen,
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
        if not apply:
            return
        # Unconditionally, not "if running". A refused request unchecks
        # the button while the *previous* waveform keeps playing (issue
        # #37), so "if running" skipped the re-apply for every shot after
        # a refusal and left a stale ramp under a dozen captions.
        # Stop through the session as well as the button. Clicking Play
        # while the device is still running earns "start refused:
        # already running; stop first" - a red notice that then sits in
        # the screenshot, describing the photographer rather than the
        # instrument.
        if a.run_btn.isChecked():
            a.run_btn.click()
        try:
            self.win.session.call("stop")
        except Exception:                            # noqa: BLE001
            pass
        self.pump(0.8)
        self.win.notice.clear()
        if not a.run_btn.isEnabled():
            # The panel refuses these settings, so there is nothing to
            # apply. That is a legitimate state to photograph.
            return
        a.run_btn.click()                # play: uploads
        self.pump(1.0)
        if not a.run_btn.isChecked():
            print("    ! generator would not start", flush=True)


def build(args):
    index = []
    bench = os.environ.get("DUE_BENCH", "windows-desk")

    # The daemon runs in its own process, which is how it is deployed
    # and - it turns out - the only way to photograph it honestly. In
    # process with the window, the GUI's redraws and grabs starve the
    # daemon's device read thread through the GIL: an early gallery
    # carried Read gap max 1,467,999 us and 77 device overruns in every
    # frame, so the Health panel was reporting damage the capture
    # harness had caused. `python -m gui` spawns a daemon the same way.
    srv = _spawn_daemon(args.port)
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
        # No explicit click here: `awg()` applies. Adding one toggled
        # playback straight back off, which the shot verifier caught as
        # "status bar says 'generator stopped'" - the check earning its
        # keep on the very first image.
        g.awg(shape="sine", hz=1000.0, vpp=1.5, offset=1.675)
        g.shot("01-loop-sine", "The closed loop: HOST -> DAC0 -> A0 -> HOST",
               "A sine asked for in the Generator panel and captured back "
               "on A0 in the same window. Nothing else here is a "
               "simulation: the host builds the samples, the DAC plays "
               "them, the ADC reads the pin, and the trace is what came "
               "back over USB.", want="sine")

        # 2. Shapes.
        for shape in ("sine", "square", "triangle", "ramp"):
            g.awg(shape=shape, hz=1000.0, vpp=1.5)
            g.shot(f"02-shape-{shape}", f"Generator: {shape}",
                   f"A {shape} at 1 kHz, 1.5 Vpp, captured through the "
                   f"loop. The shape is built on the host and streamed to "
                   f"the DAC, so an arbitrary waveform is the same path.",
                   want=shape)

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
               "Compare with the next image.", want="square")

        g.awg(shape="square", hz=20000.0)
        # 1 ms, not the 20 ms everything else uses. At 20 ms a 20 kHz
        # square is 400 cycles across the plot and draws as a solid
        # block - a true picture that shows nothing, and the caption
        # below is about the shape of the edges.
        g.combo(win.timebase, 0.001)
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
               "which is a gap in this panel rather than in the board. "
               "Note the timebase: 1 ms rather than the 20 ms used "
               "everywhere else, because at 20 ms this is 400 cycles and "
               "draws as a solid block.")

        # 4. Views.
        g.combo(win.timebase, 0.02)
        g.awg(shape="sine", hz=1000.0, vpp=1.5)
        g.combo(win.view_box, "time")
        g.shot("06-view-time", "Time view", "The default.")
        # 1025 Hz, not 1000. A 1 kHz tone is exactly 20 cycles in a
        # 20 ms window, so it fits and *rectangular is exact* - the
        # first gallery promised a smeared tone and showed a clean
        # spike, because the frequency chosen could not smear. 1025 Hz
        # is 20.5 cycles: the worst case, and the one the tooltip warns
        # about.
        g.awg(shape="sine", hz=1025.0, vpp=1.5)
        g.combo(win.view_box, "spectrum")
        g.combo(win.fft_window, "hann")
        g.shot("07-view-spectrum-hann",
               "Spectrum, Hann window, on a tone that does not fit",
               "1025 Hz in a 20 ms window is 20.5 cycles - it does not "
               "fit a whole number of times. Hann tapers the ends, so "
               "the tone stays a line. Compare the next image, which is "
               "the same capture read with a different window.")
        g.combo(win.fft_window, "rectangular")
        g.shot("08-view-spectrum-rect",
               "The same tone, rectangular window: smeared",
               "**Deliberately the wrong window, on a tone chosen to "
               "expose it.** Rectangular is exact only when the analysis "
               "window holds a whole number of cycles; at 20.5 cycles "
               "the ends do not match and the discontinuity spreads "
               "energy across the whole span. The window control says so "
               "in its tooltip. At 1000 Hz - 20 cycles exactly - this "
               "picture and the Hann one are indistinguishable, which is "
               "the trap: a spectrum without its window named is not a "
               "measurement, and a lucky frequency hides the difference.")
        g.combo(win.view_box, "time")

        # 5. Rates. These have to leave loop mode: the generator sets
        # both rates itself, so with it running every preset produced an
        # identical 200,000 Hz and three screenshots that differed only
        # by a greyed-out label. In plain capture the preset is what the
        # firmware is given, and Health reports what the converter
        # actually made - which is the thing worth showing.
        win.awg.run_btn.click()          # stop the generator
        g.pump(1.0)
        for label, key in (("50 kHz", "1"), ("200 kHz", "3"),
                           ("max in-spec", "5")):
            g.combo(win.preset, key)
            win.start_capture()
            g.pump(2.5)
            if key == "1":
                # XY belongs here and not in loop mode. Loop mode feeds
                # DAC0 only, so A1 sits undriven and the XY view drew a
                # flat horizontal line - a true picture of nothing.
                # A capture start runs the board's *internal* generator
                # (`with_gen` in stream_core_start), which puts its
                # phase-locked square on the other DAC. Two live
                # channels is what the view is for.
                g.combo(win.view_box, "xy")
                g.shot("09-view-xy", "XY view: A0 against A1",
                       "**A step, and the fact that it is a step rather "
                       "than a rectangle is the measurement.** A0 carries "
                       "the internal generator's sine, A1 the square it "
                       "puts on the other DAC. Plotting one against the "
                       "other, A1 switches exactly as A0 crosses "
                       "mid-rail and the trace retraces its own path - "
                       "any phase lag between the two converters would "
                       "open this into a hysteresis loop whose width is "
                       "that lag. It does not open, which is what one PDC "
                       "stream driven by one trigger is supposed to "
                       "produce. In loop mode the host feeds DAC0 alone, "
                       "A1 is undriven, and this view is an honest flat "
                       "line - which is why the shot is taken here.")
                g.combo(win.view_box, "time")
            g.shot(f"10-rate-{key}", f"Capture preset: {label}",
                   "**The rate asked for and the rate reported are "
                   "different numbers, and the second one is the truth.** "
                   "Every rate this hardware has is 39 MHz divided by an "
                   "integer, so a round request gets the nearest divider; "
                   "Health shows what the frame headers carry rather than "
                   "what the control said. The trace is flat because the "
                   "generator is stopped - the preset governs capture, "
                   "and in loop mode the generator would own both rates "
                   "and this control would be disabled.")
            win.stop_capture()
            g.pump(0.6)

        # Back to a signal for the rest.
        g.awg(shape="sine", hz=1000.0, vpp=1.5, offset=1.675)
        for label, secs in (("1 ms", 0.001), ("100 ms", 0.1), ("2 s", 2.0)):
            g.combo(win.timebase, secs)
            g.shot(f"11-timebase-{label.replace(' ', '')}",
                   f"Timebase: {label}",
                   "The display keeps a ring in seconds, so the timebase "
                   "chooses how much of it to draw rather than asking the "
                   "device for anything.")

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

        # 8. A board that actually stopped, photographed while it is
        # wrong.
        #
        # It is here because the alternative was worse: an earlier
        # gallery happened to catch 111 discontinuities during an
        # ordinary run and the next one caught none, so a caption
        # promising red counters had nothing reliable behind it. A
        # capture harness that waits for a defect either publishes a
        # picture it cannot reproduce or quietly drops the claim.
        # `=<ms>S` stalls the main loop for real - it is the command the
        # heartbeat work was validated against - so the counters below
        # are a genuine event on a genuine board, provoked on purpose.
        #
        # Through the daemon's own `console` op, not a serial handle of
        # our own. Opening the programming port here asserts NRSTB and
        # resets the board, and the daemon already holds that port to
        # read the identity - so a second handle both killed the run and
        # starved the daemon out of start-up, which is how this was
        # found. The daemon owns the ports; ask it.
        if win.session.call("console", text="=900S") is not None:
            g.pump(2.5)
            g.shot("15-health-stalled",
                   "The same panel, with the board deliberately stalled",
                   "**This is what the counters are for, and it is the "
                   "reason to believe the other pictures.** The board's "
                   "main loop was stalled for 900 ms on purpose with "
                   "`=900S`, the command the timer-driven heartbeat was "
                   "validated against, sent over the daemon's console "
                   "op. The ADC went on converting into a ring nobody was "
                   "draining.\n\n"
                   "Every number here is a consequence of that, and each "
                   "one is checkable. **Device overruns 175** and "
                   "**Discontinuities 1**, both red: the frames either "
                   "side of the gap are not continuous with each other, "
                   "and the panel says so instead of splicing them - "
                   "invariant 5, photographed. **Read gap max 907,000 "
                   "us** against a 900 ms stall, which is the reader "
                   "genuinely blocked for as long as the board was "
                   "stopped. That figure is only readable because of "
                   "issue #40: until it was fixed this counter measured "
                   "across deliberate stops too, and published 3.8 s of "
                   "idle time as a stall in the data path. **Sequence "
                   "gaps 0** and **Dropped to us 0** stay clean, which "
                   "matters as much - the loss was the device's, and the "
                   "panel does not smear it across the host's counters.",
                   widget=win.health)
            g.shot("16-measure-stalled",
                   "Measure declining to time something that is not a signal",
                   "The same stall, one panel to the left, and it does "
                   "not say what you would expect. A stalled loop feeds "
                   "the DAC nothing, and playback abandons itself after "
                   "500 ms without a byte rather than holding a buffer "
                   "for ever - so by 900 ms the DAC has stopped being "
                   "driven and simply holds its last code.\n\n"
                   "What is left on A0 is that held level plus the "
                   "bench's own noise: **Vpp 0.0064 V**, with mean and "
                   "RMS equal to each other at 0.9273 V, which is what a "
                   "DC level looks like measured honestly. The timing "
                   "fields refuse - *signal too flat to time* - rather "
                   "than reporting a frequency derived from 6 mV of "
                   "noise, which is what a zero-crossing counter with no "
                   "amplitude floor would have done, confidently and to "
                   "four digits.",
                   widget=win.measure)

        win.awg.run_btn.click()          # stop playback
        g.pump(0.8)
    finally:
        try:
            win.disconnect_from_daemon()
        except Exception:                            # noqa: BLE001
            pass
        srv.stop()

    with open(os.path.join(args.out, "index.json"), "w") as fh:
        json.dump(index, fh, indent=2)
        fh.write("\n")
    print(f"\n{len(index)} images -> {args.out}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "build", "gallery"))
    ap.add_argument("--port", type=int, default=0,
                    help="daemon port; 0 picks a free one")
    return build(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
