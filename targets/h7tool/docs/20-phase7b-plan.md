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
The heartbeat and USB-SOF clock reference, the
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
  counts since connect and returns the queue), and then from VOUT being wired to both inputs. That wiring is not a supported measurement (one source on one input; the owner ruled it out
  on 2026-11-03, the board's internal design may not allow it), so the 17-28 % low reading with both leads is withdrawn, not chased. With one lead
  the output is nominal on either input (CH1 sine +2.1 %, DC +0.8 %, 2026-11-03; CH2 +1.2 %, +0.9 %). The 3 % excess of the old tool on CH1 over
  its recorded 0.599 V is unexplained *(check)*; recorded only, deferred by the owner (2026-11-03): it needs a reference voltage and a hardware look, software alone will not settle it; CH1 reading 1-2 % high on the current tool is the same direction.
  A cycle of the ten failed once in one run (not reproduced in 40 more) and is unexplained *(check)*.
- Bench wiring from 2026-11-02 evening: VOUT to CH2 only (the owner's choice, simpler and more stable); the gate defaults to it and also passes with `H7_GATE_VOUT=1`.
- Image 13 (build 15): no self-timed return to the boot loader by default, and control opcode 0x0044 `BOOT` restarts into it (docs/19).
  The "crash" at 19:33 and the loss of the unit at about 20:35 were the 30-minute window of image12a ending, not faults. The gate names the
  boot-loader state instead of "the daemon did not come up". Proven on the unit: opcode armed and the unit enumerated as 0483:5720; the flash
  wrapper's second flash from a running image13a used the opcode and no sudo; the gate passes on it.

## Phase 7 first close (2026-11-02; reopened by part 2 below)

7a (control function) and 7b (the H7 behind the daemon and the unchanged GUI) are done, and image 13 replaces the boot-loader timer with a host
command. What was checked at the close: board-free suite 1249 passed / 18 skipped / 322 deselected; GUI suites 124 passed; the host-compiled
dispatcher tests 6 passed; the real-Due smoke passes; the H7 gate passes on the real unit with VOUT on CH2 (sine +1.2 %, DC +0.9 % against
nominal, control replies 0.8 ms median under full load, 0 underruns, 0 gaps). The timer is decided by code review, not by a 30-minute wait: the
default `RUN_MS` is 0, the run loop tests only `RUN_WINDOW_OPEN()` (constant 1 then), the old 1,800,000 ms constant is absent from the image,
and `tests/test_h7_image13.py` fails when any of that changes (six mutations tried).
Open, none blocking: the old tool's 3 % excess on CH1, one unexplained failed start/stop cycle, and the pre-existing flaky
`test_the_end_of_a_recording_says_so`. Not done, and now the plan of part 2 below: GUI controls for the H7's gain and coupling, the generator panel, XY, replay of H7 recordings, and the test suite's reach.

## Phase 7b, part 2: what the H7 still lacks (survey 2026-11-02)

Found by driving every GUI feature against the simulated H7 (`MainWindow` offscreen, the real daemon, the real dispatcher) and by listing what no
test tier reaches. Each item is a measured symptom, not a guess; the cause is named where it was read from the code.

### GUI: what does not work for an H7 yet
| # | symptom on the simulated H7 | cause | work |
|---|---|---|---|
| G1 | the preset box offers the Due's rate list (50 kHz ... "max in-spec"), which the H7 start ignores | `PRESETS` in `gui/app.py` | list the device's own rates from its description, or hide the box |
| G2 | the generator panel is "Generator (DAC0 -> A0)"; a 1 Vpp sine at offset 0 is refused by the swing cap ("108800 codes outside 1706..2366") | `gui/awg.py` maps the Due's 0.55-2.75 V window onto 12-bit codes (4095) | an H7 mapping from the description: zero code, 5.975 mV per code, the cap; volts about 0 V |
| G3 | the generator cannot start while capture runs ("already running; stop first") | the H7 refuses a start while running; the Due's flow restarts | the GUI stops and restarts, or the daemon switches mode |
| G4 | the XY view draws 4000 points for CH1 and none for CH2 | `scope._draw_xy` picks the other channel from the Due's tags 7 and 6 | choose the other channel from the format's ids |
| G5 | the spectrum view draws one curve (CH1); CH2's is empty | not read yet *(check whether the Due draws both)* | decide, then fix or document |
| G6 | the Measure panel says "ADVREF 3270 mV, measured", a Due fact | `app.py` footnote | take it from the description |
| G7 | no gain or coupling control; volts are the gain-0 calibration only | the description hardwires `gain_code` 0; docs/12's gain table is not used by the host | per-gain calibration for codes 1-7 (needs a reference voltage; stated gate: +-1 %), the description follows the set gain, then a per-channel panel; Y and trigger ranges follow |
| G8 | a recording of an H7 replays with the Due's format | `FileDevice.describe()` returns kind "file" and drops `sample`, `channels`, `defaults`, `options` from the sidecar (the recording itself works: 60 frames = 245,760 bytes, sidecar carries the H7 description) | pass the sidecar's description through |
| G9 | record and CSV export hang a headless run | both open a file dialog | patch the dialog in tests; no product change |

What works, so it is not re-done: connect and format switch, both channels drawn in volts, time and spectrum views, trigger on either channel with a
level in volts (range follows the device), cursors, the Measure values (Vpp 2.0001 V, 1,000.0 Hz on the 1 V simulated sine), the Health panel,
stop, record.

### Test suite: what no tier reaches
| # | gap | work |
|---|---|---|
| T1 | **done:** `ports.census()`/`h7_state()`, the `due` and `h7` markers, the `h7_unit` fixture, `--require-h7`, a header line and a counted skip summary; `tests/test_devices.py` (11 tests, 5 mutations) and `tests/test_h7_unit.py` (T3, the gate as a test); docs/testing.md. Was: no way to say "run what the attached hardware allows": the Due's tests skip as "no board" and the H7 has no pytest tests at all (its real-unit checks are `measure/h7_daemon_gate.py`) | detect devices without opening a port (Due 2341:003D/003E, H7 1209:0001 with interfaces 0 and 2, boot loader 0483:5720), print one summary line at the start ("Due: track B on ..., H7: absent, boot loader"), mark real-unit tests `due` and `h7`, skip each with a reason that names the missing device and counts them separately, and keep `--require-board` and a new `--require-h7` as failures, so a skip is never read as a pass |
| T2 | **done (first step of part 2):** the eight test files under `targets/h7tool/tools` (55 tests) were collected by no tier. They are `tests/test_h7_*.py` now and under the same guards (encoding, pacing, platform marker); two need numpy and skip in the plain venv like the GUI tests; the board-free tier went from 1249 to 1288 passed | done; docs/testing.md says where H7 tests live |
| T3 | **done** (the gate runs as `test_h7_unit.py`, 8 of 8 passes on the unit). Was: the gate's stages run only by hand | turn them into `h7`-marked tests that skip when the unit is absent or in the boot loader (with that state named) |
| T4 | GUI-on-H7 tests cover three things (format, defaults, restore) | add XY, spectrum, measure labels, generator mapping and refusal, preset, trigger on CH2, cursors, record and export with the dialog patched, replay |
| T5 | record then replay of version-4 frames has no test | round trip through `FileDevice` and the window |
| T6 | `measure.parse_identity` and provenance know tracks A-C only | decide the H7's identity path and test it |
| T7 | `ports.find_h7` is verified on Linux only | tests over faked `list_ports` entries in the Windows and macOS location formats |
| T8 | the simulation cannot show a fault the transport or the firmware causes (the DTR fault and the feeder underruns were found only on the unit) | the simulated stream can start "found running" (done) and refuse writes; add a boot-loader re-enumeration and a ring that underruns when fed slowly |

### Step 2 done (2026-11-03): G1, G4, G6, G8

Each has a test in `tests/test_gui_h7.py` or `tests/test_daemon_api.py` that fails with the source change taken out (checked by reverting `gui/` and `host/`).
- **G1**: for a device whose description is not a Due's the rate box holds the one rate the description starts at ("1 MHz"), disabled; a Due description brings
  the list back. `MainWindow._fill_presets`.
- **G4**: the symptom was not reproduced (setting the format already remaps `CH_A0`/`CH_A1`, so the second channel was found). What the test did find, with CH2 as
  the source, was a defect on every device: the XY axes were labelled only on entering the view, so switching the source channel left them naming the old pair.
  `_draw_xy` relabels when the pair changes.
- **G6**: `Format.reference` carries the line from the description's calibration sources; the Due keeps its ADVREF line (`stream.reference_note`).
- **G8**: `FileDevice.describe()` passes `sample`, `channels`, `defaults` and `options` from the sidecar's device block; a Due's block has none, so nothing changes for it.

### Step 3 done (2026-11-03): G2, G3

- **G2**: the daemon's H7 description carries `generator` (output name VOUT, mV per code, the swing cap). `AwgPanel.set_device` makes the panel plan in volts
  about 0 V (`awg.plan_h7`), refusing and naming the offset that fits when the cap would be exceeded; a Due description restores the DAC0 panel. The waveform
  is still the Due-style 12-bit blob around 2048 that `waveform_to_dac_codes` re-centres, so one builder serves both.
- **G3**: the window stops an H7 before it plays (the H7 refuses a start while running, where the Due restarts).
- Tests in `tests/test_gui_h7.py`, each failing with its change taken out. The real-unit gate has a new check: Play pressed in the window while capturing,
  3 Vpp at 0 V (251 codes), read back through the window's rings on the wired channel: CH1 +2.2 % (1.5328 V against 1.4997), tolerance 4 %.
- **Found on the unit, recorded and not tuned for**: small sines read high by a roughly constant 20-30 mV of amplitude, whatever the rate (1 MS/s and 200 kS/s
  agree) or the path (window and direct client agree). CH1 at gain 0, VOUT on CH1: peak 10 / 20 / 40 / 84 / 150 / 250 codes read +64 / +33 / +10 / +4.4 / +2.1 /
  +2.1 % against nominal; the slope between 84 and 250 codes is 5.95-6.1 mV per code (nominal 5.975), so it is an additive term and not a scale error. Zero
  amplitude reads 0.052 V (`std x sqrt 2`, about 36 mV rms), and a fit at the sine's own frequency removes only part of the excess. Not explained; it is the
  same channel and the same kind of question as the CH1 offset above, deferred as hardware-side. This is why the gate plays 3 Vpp: that is where the known
  error is inside the tolerance, and the panel's mapping is exact (84 codes for 1 Vpp is checked in the unit test).

### Step 4 done (2026-11-03): G7, with the limit stated

- **Daemon**: `H7Device.describe` reads the unit's gains and couplings back, so each channel's `calibration` (zero, codes per volt, `gain_code`) and `range_v`
  are those in force. The `start` reply carries the description the unit now has. Settings are the unit's own and sticky: an option not named keeps what is in
  force (the unit powers up at gain 0, DC); a daemon that described gain 4 and then started at gain 0 was caught by the real-unit gate and is guarded by
  `test_a_start_without_options_keeps_the_settings_the_description_reports`.
- **GUI**: `gui/inputs_panel.py` (per-channel gain and coupling, hidden for a Due) feeds the start's `options`; the start reply replaces the format, keeping the
  selected channel and trigger level; a change while capturing restarts with it (generator included). The simulated unit now follows the gain it was given, and a
  new simulated unit starts at power-up settings.
- **Calibration**: the gain codes 1-7 already had factory scale and measured zeros for both channels (docs/17), and are used as they are. No reference voltage
  was available, so nothing here is calibrated against one. **Stated limit**: every volts figure is good to about +-1 % (docs/17), and the gate's check for gains
  1-4 is that a 100-code sine from VOUT, read through each gain's own scale, agrees with VOUT's nominal 5.975 mV per code to 4 %. CH1, VOUT on CH1: gain 1 +1.9 %,
  2 +1.4 %, 3 +0.9 %, 4 +1.1 %. Gains 5-7 (ranges 0.44 V and below) are not exercised on the unit: a VOUT level that fits them is below the swing the DAC makes
  cleanly.
- **The small-sine excess is input-side**: the same 40-code sine reads +10.2 / +4.4 / +3.0 / +2.3 / +1.6 % at gains 0-4. It falls with gain, as the unit's input
  noise referred to the input does (docs/17), though the size is more than the quadrature sum of the measured noise explains *(check)*. Not tuned for; the gate
  keeps gain 0 to the 3 Vpp check and uses gains 1-4 at 100 codes.

### Order and gates
1. T1 and T2 first: they change what "green" means, so every later step is judged by them.
2. G1, G4, G6, G8 (small, no new measurement), each with a test that fails when the fix is removed.
3. G2 and G3 (the generator on the H7), then the gate on the real unit with a played sine read back through the window.
4. G7 (calibration for gain codes 1-7, then the panel). Gate: a known level read at several gain codes on the real unit, with the reference
   voltage this still needs; without one the gate states the +-1 % limit instead of passing.
5. T4-T8 alongside each step. The phase closes when the board-free suite, the GUI suites, the H7 tier on the real unit and the Due smoke are green
   together, and the plan's open items are either closed or named.

Needs the owner: a reference voltage for G7, and whether H7 and Due tests should ever run in one invocation when both are attached (T1 proposes yes, each
only against its own device).

### Part 2, step 1 done: the H7's tests are managed like the Due's
`tests/test_h7_*.py` (eight files moved from `targets/h7tool/tools`) are collected by the board-free tier and the container's gate, under the same
guards. Board-free: 1289 passed / 20 skipped / 322 deselected in the plain venv (was 1249), the platform tier 18 passed, the Due smoke passes; the moved
tests still catch a broken swing cap (5 failures). **Found by running the whole board-free tier in the GUI venv, which had not been done:**
`test_metrics.py::test_a_legacy_stamp_still_resolves_by_wall_clock` fails there ("latest, unmatched build stamp") and passes alone and in the plain
venv; it fails the same way at `9dd0c5c`, before any of this work, so it is an order-dependent test that predates it *(cause not found)*.

### Part 2, step 2 done: device detection, and the two faults it found on the unit
Detection and the counted skips are in (docs/testing.md). Running the real-unit test repeatedly exposed two faults that single runs hid, and fixing the first exposed a third; all three are traced to
their causes and fixed at their source (docs/19, "Starting and stopping the stream"): the run boundary the host did not make (`H7Device` now reopens the stream
port and drains it before each run, as the Due's device does), an IN-endpoint disable written to an idle endpoint (image 17), and bulk OUT not drained when no
playback owns it (the Due's rule, image 17). Before: 4-7 of 400 stale first frames and 1-15 of 400
starts with no frames per image. After: 0 stale first frames in 2,970 starts and 0 starts with no frames in 1,100 (image 17). The first attempt tolerated the symptoms (the gate judged a run from its second frame) and a firmware
change that reduced one of them without a known cause; both were removed, the gate is strict again, and the images 14-16 that led there are not kept. The test
suite now also guards image 17's procedure by source (step order, one EPDIS behind a second EPENA check, waits against the clock, expiries counted), with ten
mutations.
