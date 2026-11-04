"""Gate for phase 7b-5: the REAL H7 through the real daemon, with the same client the Due uses.

Starts `python -m daemon --device h7` (nothing else may hold the H7's ports), then checks, in this order:
  1. the hello description is the H7's and the rates are the H7's;
  2. a sine and a DC level played on VOUT are read back in volts, through the GUI's own decode, to their nominal values (which input
     carries VOUT is declared with H7_GATE_VOUT, default 1);
  3. ten start/stop cycles: every run delivers gapless version-4 frames and the stream is quiet after each stop;
  4. the control channel polled every 20 ms for CONTROL_S seconds under full playback + capture load: every reply returns,
     the worst latency is reported, and no frame is lost or flagged.
Writes nothing to flash; VOUT goes to the H7's own inputs only (never to the Due); the swing is far inside the host cap.
Needs .venv-gui (numpy for the decode). Exit status is non-zero on any failed check.

    .venv-gui/bin/python targets/h7tool/measure/h7_daemon_gate.py [control_seconds]
"""
import array, os, struct, subprocess, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "host"), ROOT]
from daemon.client import Client, Refused
from gui import stream
import numpy as np

PORT = 45498
HDR = struct.Struct("<4sBBHIIIIII")
CONTROL_S = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
# The sine below is 150 codes at 5.975 mV per code, so 0.896 V peak, and the DC level is 167 codes (0.998 V). Both read their nominal
# value to within a few percent with VOUT on one input (2026-11-02: CH1 0.915 V and +1.005 V; CH2 +1.2 % and +0.9 %). One source on one input is
# the supported wiring: VOUT on both inputs at once is not a measurement this instrument is meant to make. Which input carries VOUT is declared,
# not assumed: H7_GATE_VOUT="1" (default, the bench wiring since 2026-11-04) or "2" (the wiring of 2026-11-02 evening).
WIRED = [int(x) for x in os.environ.get("H7_GATE_VOUT", "1").split(",")]
TOL = 0.04                                     # fraction of nominal: factory scale vs stock calibration, and the known 1-3 % offsets
EXPECT_V = 150 * 5.975e-3


def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg, flush=True)
    if not ok:
        sys.exit(1)


def dc_waveform(dev_codes):
    return array.array("H", [2048 + dev_codes] * 1024).tobytes()


def sine_waveform(peak, n=256):
    import math
    return array.array("H", [2048 + round(peak * math.sin(2 * math.pi * i / n)) for i in range(n)]).tobytes()


class Tap:
    """Frames that arrived since the last take(). Client.wait_frames counts every frame since connect and returns the whole queue,
    so a second call asking for 30 returns at once with frames from the first run - the trap this exists to avoid."""

    def __init__(self, cl):
        self.cl, self.seen = cl, cl.frames_received

    def take(self, n, timeout=20.0):
        """Block until n new frames have arrived and return exactly the newest n of them (n <= the client's queue)."""
        self.cl.wait_frames(self.seen + n, timeout=timeout)
        got = list(self.cl.frames)[-n:]
        self.seen = self.cl.frames_received
        return got

    def new(self):
        """Whatever has arrived since the last call, with the count that fell off the end of the client's queue."""
        n = self.cl.frames_received - self.seen
        keep = min(n, len(self.cl.frames))
        got = list(self.cl.frames)[len(self.cl.frames) - keep:] if keep else []
        self.seen = self.cl.frames_received
        return got, n - keep


def seq_gaps(frames):
    seqs = [HDR.unpack_from(f, 0)[4] for f in frames]
    return sum(1 for a, b in zip(seqs, seqs[1:]) if b != a + 1)


def main():
    import subprocess as sp
    if "0483:5720" in sp.run(["lsusb"], capture_output=True, text=True).stdout and "1209:0001" not in sp.run(["lsusb"], capture_output=True, text=True).stdout:
        check(False, "the unit is in the stock boot loader (0483:5720), not running an image: flash one with tools/h7_flash_wait.sh "
                     "(an image built with a RUN_MS window returns here when the window ends)")
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "host"))
    d = subprocess.Popen([sys.executable, "-m", "daemon", "--device", "h7", "--port", str(PORT)], cwd=os.path.join(ROOT, "host"),
                         env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    cl = None
    try:
        for _ in range(40):
            time.sleep(0.5)
            try:
                cl = Client("127.0.0.1", PORT, timeout=20); cl.connect(); break
            except Exception:
                cl = None
        check(cl is not None, "the daemon came up on the real H7")
        dev = cl.hello("control").get("device", {})
        check(dev.get("kind") == "h7" and dev.get("track") == "h", f"description: kind {dev.get('kind')} track {dev.get('track')}")
        # Settings stay with the unit (and an aborted run leaves its gain behind): state this gate's own, gain 0 and DC, before reading any volts.
        cl.call("start", mode="capture", adc_hz=1_000_000, channels=2, options={"gain": 0, "coupling": "dc"}); cl.call("stop"); time.sleep(0.5)
        dev = cl.hello("control").get("device", {})
        check([c["calibration"]["gain_code"] for c in dev["channels"]] == [0, 0], "the unit is at gain 0 for this gate")
        stream.set_format(stream.format_from_description(dev))
        r = cl.call("rate", adc_hz=1_000_000, channels=2)
        check(abs(r["adc"]["actual_hz"] - 1_000_000) < 1, f"rate snap: {r['adc']}")
        cl.subscribe(True)

        tap = Tap(cl)

        # 2. Levels in volts, through each wired channel's own calibration: a sine, then a DC level (which must hold, not decay).
        cl.send_awg(sine_waveform(150)); cl.wait_event("awg_ok")
        cl.call("start", mode="loop", adc_hz=1_000_000, dac_sps=1_000_000, channels=2)
        tap.seen = cl.frames_received
        frames = tap.take(200)[40:]                                       # the first frames: the DAC and the ADC start together
        cl.call("stop"); time.sleep(0.5)
        for tag in WIRED:
            vs = np.concatenate([stream.codes_to_volts(stream.decode(f).channels[tag], tag=tag) for f in frames])
            amp = float(vs.std() * 2 ** 0.5)                              # sine amplitude from its rms; noise adds in quadrature, ~0.001 V here
            print(f"CH{tag}: sine 150 codes peak reads {amp:.4f} V (nominal {EXPECT_V:.4f})")
            check(abs(amp - EXPECT_V) < TOL * EXPECT_V, f"CH{tag}: the sine's amplitude is within {TOL:.0%} of nominal")
        cl.send_awg(dc_waveform(167)); cl.wait_event("awg_ok")
        t_start = time.time()
        cl.call("start", mode="loop", adc_hz=1_000_000, dac_sps=1_000_000, channels=2)
        check(time.time() - t_start < 3.0, f"a loop start straight after a loop run returned in {time.time() - t_start:.2f} s: the unit drains the bulk OUT the stopped playback left queued")
        tap.seen = cl.frames_received
        frames = tap.take(1000)
        cl.call("stop"); time.sleep(0.5)
        for tag in WIRED:
            vs = np.concatenate([stream.codes_to_volts(stream.decode(f).channels[tag], tag=tag) for f in frames])
            first, last = float(vs[100_000:200_000].mean()), float(vs[-100_000:].mean())
            print(f"CH{tag}: DC +167 codes reads {first:+.3f} V at 0.1-0.2 s and {last:+.3f} V at the end (nominal {167 * 5.975e-3:+.3f})")
            check(abs(last - 167 * 5.975e-3) < TOL * 167 * 5.975e-3 and abs(first - last) < 0.03, f"CH{tag}: a DC level reads its nominal value and holds")

        # 2b. The scale follows the gain (G7). No reference voltage is available, so VOUT's own nominal (5.975 mV per code, itself good to about
        # 1 %, docs/17) is the reference and the claim is only that each gain's scale agrees with it to TOL: a scale that did not follow the gain
        # would be out by the factor between gain codes. Gain 0 is left to the checks above: its input noise inflates a small sine (docs/20).
        for g in (1, 2, 3, 4):
            cl.send_awg(sine_waveform(100)); cl.wait_event("awg_ok")
            r = cl.call("start", mode="loop", adc_hz=1_000_000, dac_sps=1_000_000, channels=2, options={"gain": [g, g]})
            stream.set_format(stream.format_from_description(r["device"]))
            got = {c["id"]: c["calibration"]["gain_code"] for c in r["device"]["channels"]}
            check(got == {1: g, 2: g}, f"gain {g}: the start reply's description names the gain in force ({got})")
            tap.seen = cl.frames_received
            frames = tap.take(100)[20:]
            cl.call("stop"); time.sleep(0.5)
            for tag in WIRED:
                vs = np.concatenate([stream.codes_to_volts(stream.decode(f).channels[tag], tag=tag) for f in frames])
                amp = float(vs.std() * 2 ** 0.5); nominal = 100 * 5.975e-3
                print(f"CH{tag}: gain {g}: 100-code sine reads {amp:.4f} V (nominal {nominal:.4f}, {amp / nominal - 1:+.1%})")
                check(abs(amp - nominal) < TOL * nominal, f"CH{tag}: at gain {g} the sine reads its nominal amplitude within {TOL:.0%}")
        # Settings stay with the unit, so leave it at gain 0, DC, and the format of the description it now gives.
        cl.call("start", mode="capture", adc_hz=1_000_000, channels=2, options={"gain": 0, "coupling": "dc"}); cl.call("stop"); time.sleep(0.5)
        stream.set_format(stream.format_from_description(cl.hello("control").get("device", {})))

        # 3. start/stop cycles. Every run starts at seq 0 and is contiguous, and a start that produces no frames fails. Two faults used to make this flake
        # (docs/19): a run boundary the host did not make (a half frame left in the read path was completed by the next run's first bytes, eating its seq 0)
        # and an IN-endpoint disable that latched on an endpoint whose transfer had already finished (the unit then sent nothing). Both are fixed at the source,
        # so nothing here tolerates either.
        for i in range(10):
            t_start = time.time()
            cl.call("start", mode="capture", adc_hz=1_000_000, channels=2)
            check(time.time() - t_start < 3.0, f"cycle {i + 1}: the start returned in {time.time() - t_start:.2f} s (a start that waits on a port close takes tens of seconds)")
            tap.seen = cl.frames_received
            cl.wait_frames(tap.seen + 32, timeout=20)
            cl.call("stop"); time.sleep(0.3)
            fr, lost_from_queue = tap.new()                              # EVERY frame since the start, not the newest 32: the client runs ahead of this thread
            check(lost_from_queue == 0, f"cycle {i + 1}: the client's queue kept every frame ({lost_from_queue} fell off)")
            before = cl.frames_received; time.sleep(0.3)
            seqs = [HDR.unpack_from(f, 0)[4] for f in fr]
            ok = (seqs[:1] == [0] and len(fr) >= 30 and all(HDR.unpack_from(f, 0)[:2] == (b"DUE0", 4) for f in fr)
                  and seq_gaps(fr) == 0 and cl.frames_received == before)
            check(ok, f"cycle {i + 1}: {len(fr)} version-4 frames from seq 0 with no gap, quiet after the stop" + ("" if ok else f" (first seqs {seqs[:4]})"))

        # 4. control polled under load
        cl.send_awg(sine_waveform(150)); cl.wait_event("awg_ok")
        cl.call("start", mode="loop", adc_hz=1_000_000, dac_sps=2_000_000, channels=2)
        tap.seen = cl.frames_received
        lat, n_frames, gaps, flagged, dropped, last = [], 0, 0, 0, 0, None
        end = time.time() + CONTROL_S
        while time.time() < end:
            t0 = time.perf_counter(); c = cl.call("counters")["counters"]; lat.append(time.perf_counter() - t0)
            got, lost = tap.new(); dropped += lost
            for f in got:
                h = HDR.unpack_from(f, 0); n_frames += 1
                if last is not None and h[4] != last + 1: gaps += 1
                last = h[4]; flagged += (h[2] != 0 or h[7] != 0)
            time.sleep(0.02)
        cl.call("stop")
        lat.sort()
        print(f"counters polled {len(lat)}x under load: median {lat[len(lat) // 2] * 1e3:.2f} ms, max {lat[-1] * 1e3:.2f} ms; "
              f"{n_frames} frames seen, {gaps} sequence gaps, {flagged} flagged, {dropped} not kept by this client's queue; last h7 status {c.get('h7')}")
        check(lat[-1] < 1.0, "every control reply came back inside a second while the unit streamed and played")
        check(flagged == 0, "no frame carried a flag or an overrun count")
        h = c["h7"]
        check(h["play_underruns"] == 0 and h["lost"] == 0 and h["adc_ovr"] == 0 and h["dma_err"] == 0,
              f"the unit's own counters are clean after the load: {h['play_underruns']} playback underruns, {h['lost']} frames lost, "
              f"{h['adc_ovr']} ADC overruns, {h['dma_err']} DMA errors")
        check(n_frames > CONTROL_S * 500, f"frames kept arriving under load ({n_frames})")
        print(f"(stages 1-4 done; sequence gaps seen by this client: {gaps}, dropped from its queue: {dropped})")

        # 5. the unmodified front end, offscreen, on the real unit
        cl.close(); cl = None
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtWidgets
        from gui.app import MainWindow
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        stream.set_format(stream.DUE_FORMAT)                              # the window must take the H7's format itself
        w = MainWindow(host="127.0.0.1", port=PORT)
        try:
            w.connect_to_daemon()
            end = time.time() + 10
            while time.time() < end and stream.current_format().name != "h7":
                app.processEvents(); time.sleep(0.01)
            check(stream.current_format().name == "h7" and [w.channel.itemText(i) for i in range(w.channel.count())] == ["CH1", "CH2"],
                  "the window took the H7's format and channels from the real unit's description")
            w.start_capture()
            end = time.time() + 15
            while time.time() < end and not (w.frames_shown >= 30 and 1 in w.rings and 2 in w.rings):
                app.processEvents(); time.sleep(0.01)
            w.tick()
            check(w.frames_shown >= 30 and w.rings[1].filled > 0 and w.rings[2].filled > 0 and len(w.scope.trace()[0]) > 0,
                  f"the window drew both channels from the real unit ({w.frames_shown} frames shown)")
            # Press Play while it is capturing (G2, G3): 3 Vpp at 0 V in volts (the top of the swing cap; a small sine reads high by a roughly constant 20-30 mV of amplitude on this bench, docs/20), the unit stopped and restarted in loop mode, and the sine read back
            # on the wired channel through the window's own rings.
            w.awg.vpp.setValue(3.0); w.awg.offset.setValue(0.0); w.awg.hz.setValue(1000.0)
            lo, hi, _why = w.awg.code_range(); nominal = (hi - lo) / 2 * 5.975e-3
            w.awg.run_btn.setChecked(True)
            check(w.awg.run_btn.isChecked(), "the generator accepted 3 Vpp at 0 V on the H7 (volts about 0 V, inside the swing cap)")
            time.sleep(1.0)
            w.acq.reset(); w.rings.clear() if hasattr(w.rings, "clear") else None
            end = time.time() + 10
            while time.time() < end and not all(t in w.rings and w.rings[t].filled > 100_000 for t in WIRED):
                app.processEvents(); time.sleep(0.01)
            for tag in WIRED:
                vs = stream.codes_to_volts(w.rings[tag].window(100_000)[0], tag=tag)
                amp = float(vs.std() * 2 ** 0.5)
                print(f"CH{tag}: the window's generator, 3 Vpp at 0 V, reads {amp:.4f} V peak (nominal {nominal:.4f})")
                check(abs(amp - nominal) < TOL * nominal, f"CH{tag}: the sine played from the window reads its nominal amplitude")
            # stop through the window's own control, then confirm the unit is idle
            w.stop_capture() if hasattr(w, "stop_capture") else w.session.call("stop")
        finally:
            w.disconnect_from_daemon(); w.close()
            stream.set_format(stream.DUE_FORMAT)
        print("H7 daemon gate: all checks passed")
    finally:
        try: cl.close()
        except Exception: pass
        d.terminate()
        try: d.wait(10)
        except Exception: d.kill()


if __name__ == "__main__":
    main()
