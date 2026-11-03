# Phase 7b plan: the H7 behind the daemon and GUI (revised after the survey)

## Principle
**The device class hides every H7 detail; the daemon and the GUI see a device-neutral description and nothing else.** An
`H7Device` (a new module, `host/daemon/h7device.py`) owns discovery, the two USB functions, start and stop, configuration,
the swing cap, the feeding of playback samples and the counters. Where the daemon or GUI must change at all, the change is a
*general* seam that the Due keeps using unchanged, never an `if h7` branch.

## What the survey found (host/daemon, gui/, host/ports.py; checked against the files)
- `server.py` applies the Due's rate model (`ratemod.check_capture(adc_hz, channels)`, `check_dac`, `describe`) in exactly three
  places: `_op_rate`, `_op_start` and the `caps` reply. The model is a timer clock over an integer RC with Due floors and `channels` in {1, 2}.
- The server forwards frames verbatim: it runs `FrameSplitter` (magic `DUE0`, 4096 bytes) over `device.read()`. Version-4 frames have the same
  magic and size, so the splitter needs no change; only the final consumer, `gui/stream.py decode()`, takes the channel tag from bits 15-12
  of every sample and the code from the low 12 bits, which corrupts 16-bit samples.
- A device needs: `describe()`, `start(mode, *, dac_sps, adc_hz, channels, waveform, preset)`, `stop()`, `read(timeout)`, `stats()`, `counters()`,
  `trace()`, `load()`, `heartbeat(...)`, `close()`, optional `write_awg()` and `feeder`; `BoardDevice` also drives a console (`v`, `=...P/L`)
  that the H7 does not have.
- Discovery is Arduino VID 0x2341 with PIDs 0x003D (console) and 0x003E (a native pair ordered by interface number).

## The device-neutral contract (the only shared-code changes)
1. **`describe()` carries the sample format and the channels**, so the GUI is generic. The Due's description is unchanged and a missing
   `sample` key means "the Due default". The H7 adds `sample: {bits: 16, layout: "planar", full_scale_codes: 65535}`, `frame_version: 4`, and
   `channels: [{id, label: "CH1", calibration: {zero_code, codes_per_volt, gain_code}}, ...]` (from `h7_cal`, measured zero, docs/17), plus the
   gain and coupling choices it offers.
2. **A rate policy is the device's.** `server.py` asks `getattr(device, "rate_policy", ratemod)`: the module `rates.py` already has the
   needed interface, so the Due is untouched. `H7Device.rate_policy` snaps to integer periods of the 200 MHz base (ADC period >= 80
   ticks, DAC period >= 40), answers `describe()` in its own terms, and refuses what the unit refuses.
3. **Channel selection** keeps `channels` as a count (1 means CH1, 2 means both) and accepts an optional `channel_mask` from the client;
   the Due ignores it. Gain and coupling travel as optional `options` passed only to a device that declares `accepts_options`.
4. **Not-implemented stays not-implemented**: `trace()`, `load()` and `heartbeat()` on the H7 raise the daemon's device error; no zeros.

## What `H7Device` does
- **Open:** finds the unit by VID 0x1209 / PID 0x0001 (new `ports.find_h7()`, Due discovery untouched), the stream node on interface 0 and the
  control node on interface 2; refuses a unit whose IDENTITY is not track `h`, control version 4, frame version 4.
- **start:** `capture` = CONFIG then RUN; `play` = CONFIG then PLAY and the feeder; `loop` = both. Opens the stream port, never relies on DTR.
- **Playback feed:** converts the daemon's uploaded waveform (12-bit tagged samples) to DAC codes, **enforces the swing cap**
  (`h7_awg.check_codes`: refuse, never clamp), writes whole 2048-byte units from its own thread.
- **read/stats/counters:** frames from the stream port; counters via the control COUNTERS record (docs/19).
- **describe:** from IDENTITY and `h7_cal`, as above.

## Order, with a gate at each step
Each step that touches shared code first runs the whole board-free suite and compares with the baseline below.
- **7b-0 Baseline (done).** 1227 passed, 16 skipped, 322 deselected (`.venv`, `-m "not board and not platform"`, 141 s) and 113 passed in
  the GUI suite (`.venv-gui`). Nothing the H7 work touches may change these.
- **7b-1 Seams (done: server hook and options in 6489e20, GUI data layer: format, decode by version, per-channel volts; widgets follow in 7b-3).** The rate-policy hook, the `describe()` sample/channels keys, `channel_mask` and `options` pass-through in `server.py`;
  `gui/stream.py` decodes by header version (3: unchanged tag-in-sample path; 4: planar 16-bit, channels from the mask) and takes volts from
  the channel calibration when the description gives it. Gate: baseline numbers identical; new tests for each seam, mutation-checked.
- **7b-2 `H7Device` against a simulated unit (done: host/daemon/h7device.py, h7sim.py, tests/test_h7device.py).** A simulated transport that runs the *compiled firmware dispatcher* (`ctl_h7.c`, the same code
  as on the unit) behind the device class and emits synthetic version-4 frames, so daemon API tests, the start/stop/rate paths and the
  swing-cap refusal run board-free through the real control code. Extends `FakeDevice`'s style; no `if h7` in the server.
- **7b-3 GUI with the simulated unit (done: gui/app.py, scope.py, stream.py; daemon --fake-h7, gui --spawn-fake-h7; tests/test_gui_h7.py).** `python -m gui` on the simulated H7 draws CH1 and CH2 with volts, labels and rates correct.
- **7b-4 Discovery and the daemon entry.** `--device auto|due|h7` in `daemon/__main__.py`; `auto` tries the Due board then the H7.
- **7b-5 (done: targets/h7tool/measure/h7_daemon_gate.py) Board gate (the Phase 7 gate).** `python -m daemon` on the real unit, an unmodified client and the GUI get a trace; a DC level
  from VOUT reads right in volts (host plays the code, the daemon captures it on the other channel); stop/start and restart cycles clean;
  the control channel polled while playback and capture run at full rate (never yet tested).

## Riskiest assumptions, and how each is checked
1. Hidden 12-bit assumptions elsewhere in `gui/` (awg 4095, trigger levels in codes): the grep list is part of 7b-1 and each hit gets a test.
2. `host/provenance.py` and `measure.py` identity paths need a console; they stay unused by the H7 path. If a daemon feature calls them
   (recording metadata is a candidate), the H7 description supplies the same fields instead of `v`.
3. Recording (`record.start`) writes frames plus a sidecar with `frame_bytes`/geometry: v4 frames are 4096 bytes so replay's geometry check
   passes, but replay would then be decoded by the GUI as v4, which must also work from a file.
4. The daemon holds the Due's ports for `python -m daemon` today; it must not try to open them when `--device h7`.
5. The firmware control function has only been exercised by one client at low rate: 7b-5 tests it under load before the phase is called done.
6. The swing cap is host-enforced by design; the daemon path is a second writer of playback codes, so the cap check lives in `H7Device`,
   not in a client.

## Not in 7b
GUI controls for gain, coupling and the swing cap (the daemon accepts them; a panel is later), the heartbeat and USB-SOF clock reference, the
Due's `trace`/`load` equivalents, the 250M module, and any change to the Due firmware or its wire contract.

## Status log
- 7b-0: baseline 1227 passed / 16 skipped / 322 deselected; GUI 113.
- 7b-1a: after the server seams 1230 passed (the three new tests), skips and deselections unchanged. A repo guard (no bare-number timeouts in tests)
  failed on my first test and was obeyed, not waived.
- 7b-1b: after the GUI data layer GUI 118 (five new tests), board-free 1230 passed / 17 skipped (the new GUI test file skips in the numpy-less
  venv; a skip is not a pass and the file runs in `.venv-gui`), 322 deselected. The real Due through the daemon and the changed `gui.stream.decode`
  (`measure/due_daemon_smoke.py`, run with `.venv-gui`) passes before and after.
- 7b-2: `H7Device`, its rate policy, `ports.find_h7()`, and a simulated unit (`h7sim.py`: the real firmware dispatcher compiled for the host,
  driven through host/control.py's own codec, plus a synthetic version-4 frame source). Nine daemon-API tests; breaking the swing cap, the
  channel mapping or the stop each fails tests. Board-free suite 1239 passed (1230 + 9) / 17 skipped / 322 deselected; the real Due smoke passes.
  Three faults found on the way, all in the simulation or my tests, none in the device class: a sleep loop in my simulated stream that took
  the control lock on every read and starved the start request (a real stream read never touches the control channel); an over-strict "no
  frame after stop" assertion (frames already in flight legitimately arrive; the property is that the stream stops within a bound and stays
  stopped); and bare-number sleeps that the repo's pacing guard rejected.
- 7b-3: the window takes the device's format, channels and defaults from its description on connect (`_apply_format`): channel selector,
  trigger range, plot spans and curves are rebuilt from it, a Due's description (no `sample` key) leaves everything as it was, and the start
  sends the device's own defaults and no Due preset. Three GUI tests on a simulated H7 (CH1 and CH2 drawn, volts recovered to 4 mV through
  each channel's own calibration, the Due format restored); breaking the per-channel calibration or the format application fails them.
  GUI suite 118 -> 121 passed; board-free 1239 passed / 18 skipped (the new GUI-H7 file needs numpy and skips in that venv) / 322 deselected;
  the real Due smoke passes.
  **A pre-existing flaky test**, found by the guard and measured rather than assumed: `tests/test_gui.py::test_the_end_of_a_recording_says_so`
  failed once in a combined GUI run. Run alone it fails 6 times in 40 at `bd9c558`, a checkout with none of the H7 host or GUI changes, 2 in 30
  at `6489e20`, and 0 in 30 on the current tree: roughly 5-15 % per run on every tree, so not caused by this work and not fixed by it
  (`device_running` is still true when it checks). Until it is understood, a lone failure of that test in a GUI-suite run is rerun, never
  counted as a regression or waved through.
- 7b-4: `daemon --device auto|due|h7` (`open_hardware`). auto takes an attached H7 (found by USB id, which opens nothing) and otherwise the
  Due; due and h7 open exactly what they name, and h7 with none attached is a refusal, never a fallback. Four tests; four mutations (auto never
  picks the H7, no Due fallback, due ignored, h7 falls back) each fail one. Board-free 1243 passed. **Behaviour change to know about:** with an
  H7 on the bench a bare `python -m daemon` now opens the H7, so the real-Due smoke names `--device due`.
- 7b-5: the board gate, `measure/h7_daemon_gate.py`, runs the real daemon (`--device h7`) on the real unit with the unmodified client and
  GUI: description and rates, a sine and a DC level in volts through each channel's calibration (VOUT's input declared with
  `H7_GATE_VOUT`), ten start/stop cycles, the control channel polled every 20 ms under full playback and capture, the unit's own counters,
  and the offscreen window. Passes on CH1-only and on CH2-only wiring (sine 0.915 / 0.907 V against 0.896 nominal, DC +1.005 / +1.007 V
  held; control reply 0.8 ms median, 1.3 ms max under load; 9,800 frames, 0 gaps).
  Found on the real unit, not in the simulation, and fixed: opening a tty raises DTR and the transport never lowers it (no HUPCL), so a
  stale line ran the image on its own and CONFIG answered busy - `transport.drop_dtr()` and a stop of a run the device did not start;
  `SerialStream` used the port object as a file descriptor; a SIGTERMed daemon left the unit running; the feeder slept 10 ms on a refused
  write against an 8 ms ring and underran 965 times in 10 s at 2 MS/s (now 0; the old feeder fails the gate with 970).
  Retracted on the way: an early "0.8 V" reading and a "DC decays" finding came from reading frames of earlier runs (`Client.wait_frames`
  counts since connect and returns the queue), and then from VOUT being wired to both inputs: with leads on both CH1 and CH2 the output read
  17-28 % low and DC decayed to zero, on the pre-daemon tool as well; with either lead alone it is nominal. At 17:00 the double wiring read
  nominal and nothing is known to have changed *(cause not found; check the two-lead junction)*. The 3 % excess of the old tool on CH1 over
  its recorded 0.599 V is unexplained *(check)*.
  A cycle of the ten failed once in one run (not reproduced in 40 more) and is unexplained *(check)*.
- Bench wiring from 2026-11-02 evening: VOUT to CH2 only (the owner's choice, simpler and more stable); the gate defaults to it. The two-lead
  loading above was not bisected: the last good two-lead data (17:00) is firmware build 13 (image11m) and every low reading is build 14
  (image12a, committed 17:13), so if both leads are used again the first test is image11m against image12a on the same wiring *(check)*.
- Image 13 (build 15): no self-timed return to the boot loader by default, and control opcode 0x0044 `BOOT` restarts into it (docs/19).
  The "crash" at 19:33 and the loss of the unit at about 20:35 were the 30-minute window of image12a ending, not faults. The gate names the
  boot-loader state instead of "the daemon did not come up". Proven on the unit: opcode armed and the unit enumerated as 0483:5720; the flash
  wrapper's second flash from a running image13a used the opcode and no sudo; the gate passes on it.
