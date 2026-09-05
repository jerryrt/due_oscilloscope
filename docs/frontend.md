# Front End: design

**Status: proposal. Nothing here is built.** This document settles the
architecture so that the work can start from a decision rather than a
preference. Read `docs/scope.md` for where this sits in the plan and
`docs/protocol.md` for the wire format it consumes.

A terminology warning, because this repository uses the phrase both
ways: *front end* here means the **software** front end, the GUI. The
**analog** front end - clamps, attenuator, bias, buffer op-amp - is
Phase 3 in `docs/scope.md` and is a different thing entirely. Where
this document says "front end" unqualified, it means the GUI.

The goal is a full instrument: a two-channel scope and an arbitrary
waveform generator, with self-test and parameter setting, running on
Windows, Linux and macOS.

## The decision

**Two processes: a stdlib daemon and a Qt GUI, over a loopback TCP
socket.** This is what `docs/scope.md` already anticipated - "a
streaming daemon owning the ports and real-time threads, a GUI as a
separate process over a local socket" - and it is confirmed here rather
than reopened.

| | Owns | Dependencies |
|---|---|---|
| Daemon | both serial ports, the real-time feeder thread, the device console | stdlib, plus a serial backend on Windows |
| GUI | display, DSP, user interaction | PySide6, pyqtgraph, numpy, scipy |

### Why the split is load-bearing

It is not tidiness. Three things break if the GUI and the acquisition
share a process.

The feeder thread's pacing is what keeps the host from silently losing
bytes. `host/rt.py` puts it on a QoS class and the Mach time-constraint
band precisely so the scheduler does not defer it, and macOS's CDC-ACM
output path drops ~128-byte chunks from a pressured queue with
`write()` having counted them (`docs/usb.md`). A Qt event loop in the
same process adds repaint stalls and garbage-collection pauses to that
thread's jitter budget, and the failure it produces is silent data
loss, not a dropped frame.

The socket is a crash boundary. If the GUI dies, the daemon keeps
draining bulk OUT. A device that stops draining while the host has
writes in flight hangs the host process in `close()` holding the port -
that is the hazard in `docs/usb.md` and it is objective 0c (#71), seen
once in the wild.

The two halves want different interpreters, and that is not a
hypothetical: PySide6 6.9.3 declares `>=3.9,<3.14` while the test venv
here runs 3.14.6. A process boundary makes that a non-issue - two
venvs, two Pythons, one socket between them - where a single process
would force the whole project onto whichever interpreter Qt supports
this year.

### The two alternatives, and why not

**Single process, Qt with a worker thread.** Less plumbing, and Python
does release the GIL inside `os.read`/`os.write`. But it puts the
real-time thread back in a process with a stop-the-world collector and
a UI thread that can block on a repaint, which is re-running the
timing hazards this project has already paid to learn.

**Browser front end over WebSocket.** The most portable option -
nothing to install on the viewing machine, works remotely, works on a
tablet - and the DSP is the problem: either it runs in the browser, or
it moves into the daemon and drags numpy in behind it. Worth adding
later as a second head on the same daemon, which the protocol below
allows for. Not the first one.

## Running it

Build the venv first - one pinned declaration, committed, and the venv
itself never is:

```sh
python -m venv .venv-gui
.venv-gui/bin/python -m pip install -r requirements-gui.txt
```

```sh
.venv-gui/bin/python -m gui --spawn-fake        # no hardware at all
.venv-gui/bin/python -m gui --spawn-file cap.due  # replay a recording
.venv-gui/bin/python -m gui                     # a daemon already running
```

On Windows the paths are `.venv-gui/Scripts/python.exe`, and the
declaration carries `pyserial` for a reason that is not about the GUI:
`tests/conftest.py` reaches `host/transport.py`, whose Windows backend
imports `serial` where the POSIX one imports `termios`. Without it the
whole GUI test file fails to *collect*, which reads as a broken test
file rather than a missing wheel.

The daemon is stdlib only, so `--spawn-fake` starts one on the same
interpreter - there is no second environment to install for a demo. The
front end's own tests run headlessly in the same venv:

```sh
.venv-gui/bin/python -m pytest tests/test_gui.py -q
```

They skip in the test venv rather than failing, because that one
deliberately has neither Qt nor numpy.

## Toolkit

**PySide6 (Qt 6) with pyqtgraph.**

PySide6 is Qt's own binding, LGPL where PyQt6 is GPL-or-commercial, and
one codebase covers all three platforms with a real widget set -
dockable panels, native menus, HiDPI - which a full instrument UI
needs. pyqtgraph is the only mature Python plotting library that
sustains interactive redraw at these rates; `docs/toolchain.md` already
chose it and ruled out matplotlib for exactly that reason.

Rejected: Tkinter (stdlib, but cannot redraw fast enough), Dear PyGui
(fast GPU plots, thin widget set), wxPython and Kivy (no advantage
here), Electron (a second runtime for nothing).

### The rendering budget shapes the UI

The aggregate rate is ~907 ksps, about 1.81 MB/s. A plot two thousand
pixels wide cannot show 907,000 points per second, so the GUI never
draws raw samples: it reduces each pixel column to a min/max pair and
draws the envelope. That is what a real DSO does, and it is why numpy
lives in the GUI process while the daemon stays stdlib.

## Wire protocol between daemon and GUI

**Implemented; the reference is `docs/daemon-api.md`.** What follows is
the design it was built from.

One TCP connection on the loopback interface. An 8-byte header - magic,
type, length - then the body.

| Type | Direction | Body |
|---|---|---|
| `CMD` | GUI to daemon | JSON: a command or a parameter change |
| `EVT` | daemon to GUI | JSON: replies, counters, refusals, console text |
| `FRAME` | daemon to GUI | one device frame, **verbatim** |
| `AWG` | GUI to daemon | waveform bytes for playback |

`FRAME` carries the device's 4096-byte frame untouched, header and all,
so both sides parse it with `measure.parse_frames`. One parser, one
definition of the format, and no second place for it to drift. It also
means a future browser head gets the same bytes.

**Backpressure**: if the GUI cannot keep up, the daemon drops whole
frames from the oldest end and counts them, and the GUI displays that
count. It never splices. Invariant 5 in `CLAUDE.md` is that
discontinuous data is never presented as continuous, and it applies to
the display exactly as it applies to the device.

### Network exposure

**Decided: the daemon listens on all interfaces with no
authentication.** It is to be used on a trusted network only, and that
assumption is the security model - written down here so it is revisited
deliberately rather than forgotten.

What it means in practice, stated plainly rather than as a warning:
anyone who can reach the port can drive the DAC, start and stop
captures, and read the sample stream. Nothing on the far side of the
socket is authenticated, so the network is doing the authenticating.
The board itself cannot be damaged through it - the DAC drives its own
pin into a jumper - but the instrument can be taken over mid-measurement
by anything that can open a socket.

Two consequences to build in rather than discover:

- **Make the bind address a setting, defaulting to all interfaces.**
  One line now, and the day this runs somewhere less trusted it is a
  config change instead of a rewrite.
- **One control owner at a time.** Additional clients may attach and
  watch, but only one may command the board. Two front ends issuing
  rate changes into the same device console is a class of confusion
  worth designing out at the start.

## Portability: the work is not in the GUI

Every line of `host/` is POSIX-only. `host/ports.py` opens with
`os.open`, configures with `termios`, asserts DTR through
`fcntl`/`TIOCM_DTR`, discovers by globbing `/dev/cu.usbmodem*`, and
waits with `select` on raw descriptors. None of that exists on Windows.
`host/rt.py` is explicit about the same thing - it returns "no
promotion (not macOS)" everywhere else.

So the daemon needs a backend split:

- **macOS**: today's code, unchanged.
- **Linux**: the same POSIX code with a different glob (`/dev/ttyACM*`,
  and `/dev/serial/by-id` for stable names) and no `cu`/`tty`
  distinction. Small.
- **Windows**: real work. Either pyserial, or ctypes over
  `CreateFile`/`ReadFile` with overlapped I/O; COM ports enumerate
  through SetupAPI or the registry. Whether the daemon may take
  pyserial as a dependency on Windows is an open question below.

Port *identification* stays as it is and is already portable: the
control port is the one that answers `h` with the banner. Nothing about
that depends on the operating system, and it has already prevented two
classes of bug that hardcoded paths caused.

Real-time promotion needs a per-OS implementation - SCHED_FIFO through
`os.sched_setscheduler` on Linux, `timeBeginPeriod` plus a
time-critical thread priority on Windows - under the rule `host/rt.py`
already follows: report what actually stuck, never raise, so the
promotion cannot become an unmeasured variable.

The macOS 128-byte drop is a macOS defect. Linux and Windows will have
their own, and the defence is already built: the device's byte
accounting is exact, so `play_bytes_in` is compared against the host's
`write()` count on every platform. That is how the next one gets found
instead of argued about.

## Features

### Available against today's firmware

**Self-test.** Most of this exists already in `tests/` and
`host/measure.py`; the front end runs it and reports it.

- port discovery and identity, which track is flashed, firmware banner
- DAC0 to A0 and DAC1 to A1 loopback integrity, per channel
- ADC linearity sweep and multiplexer crosstalk
- the ramp test - every sample encodes its own position, so it proves
  byte-exactness rather than plausibility. This is the instrument that
  found the lost-sample defect.
- trigger-rate sweep, including the silent decimation cliff
- transport benchmarks, CPU-FIFO and DMA, IN, OUT and duplex
- counter health: sequence gaps, overruns, underruns, spans, partial,
  and Track A's endpoint rebuilds
- the tone-amplitude oracle, per 50 ms window, against the theoretical
  maximum for a full-scale sine
- a pass/fail report carrying the measured numbers, not just ticks

**Scope.** Timebase and volts per division, software trigger (edge,
level, pulse; auto, normal, single), cursors, automatic measurements
(Vpp, RMS, frequency, duty, rise and fall), math including A-B, FFT
with a choice of window, spectrogram, XY mode, persistence, roll mode,
record and export.

**AWG.** Waveform library and arbitrary upload from file or drawn by
hand, amplitude and offset entered in volts and mapped through the
DAC's real **578-2771 mV** span - the scope-measured pair in
`calibration.json`, not the 546-2760 this line used to quote, which
was ADC-derived and low by about the ADC's own offset - per-channel
DAC0 and DAC1 via tag
interleaving, sweep, burst, one-shot, and a visible underrun count.

**Parameters already settable**: sample rate on both sides, channel
count, capture presets.

### Requiring firmware work, in priority order

1. **A machine-readable capability report.** Without it the GUI
   hardcodes the device's limits - the `ACQ_MIN_RC` table, the DACC
   ceiling, the channel map, MCK, the frame layout - and lies the
   moment firmware changes. A command that returns them as data makes
   the GUI's refusals *be* the device's refusals rather than a copy
   that drifts. Cheapest item here and everything else is safer behind
   it.
2. **Per-channel analog gain and offset.** `ADC_CGR` carries a gain
   field per channel and `ADC_COR` an offset (both present in the
   device header). That is a hardware volts-per-division and vertical
   position control without waiting for the Phase 3 analog front end.
3. **Hardware trigger.** `ADC_EMR` provides a window comparator -
   `CMPMODE`, `CMPSEL`, `CMPFILTER` - and `ADC_MR`'s `TRGSEL` can
   select the external `ADTRG` pin. Level, window and external
   triggering, filtered against noise. Today's trigger is software and
   after the fact.
4. **Burst capture with pre-trigger depth.** The frame flags already
   reserve "first of burst" and "last of burst", so the format
   anticipated this; the firmware needs a rolling pre-trigger buffer
   armed by item 3. Single-shot capture of a one-off event is the
   feature continuous streaming cannot provide.
5. **Resolution and tracking time.** `ADC_MR` carries `LOWRES` and the
   tracking, settling and startup fields. Ten-bit mode buys rate;
   longer tracking buys accuracy from higher-impedance sources.
6. **Sync output.** A GPIO pulse at waveform start so an external
   instrument, or the second channel, can lock to the generator.
7. **Track B's missing DAC update-rate sweep.** Track A has `d` and
   `j`/`k` and Track B has never had them; `CLAUDE.md` requires the
   tracks stay feature-equivalent, so this is owed regardless.
8. **Calibration constants in device flash.** Decided: they live on
   the board, not in a host file, so calibration follows the board
   between machines and a front end on a fresh install is correct
   immediately. The device reports them through item 1's capability
   report, which means the GUI never carries a second copy.

   The SAM3X has no EEPROM, so this is an EEFC page write, and two
   things need checking before it is designed: whether a page can be
   written while code executes from the same flash bank on this part
   *(check the datasheet and errata)*, and where the page sits so a
   firmware update does not erase it. It must also never be written
   while streaming - an erase-write stalls the real-time path, and the
   one thing the sample stream cannot absorb is the CPU disappearing.

   Saved *setups* are a separate matter and stay host-side: they are
   the user's workspace, not a property of the board.

Every firmware item costs double. The tracks share no source by design
and must stay feature-equivalent, so each lands twice with the same
command letter and output format. Item 1 is the partial exception: a
capability report lets the GUI tolerate one track being behind the
other.

### Explicitly out of scope

**Firmware flashing.** The front end does not program the board.
`tools/flash.sh` keeps that job.

## Record and logging

There are two modes and they answer the "does the GUI keep every
sample" question differently, which is why it cannot be settled once.

**Live mode** keeps a rolling window in memory - a ring sized in
*seconds*, not bytes, so it does not silently shrink to a fraction of a
screen when the rate goes up. It holds what the display and the
measurements need and discards behind that. Nothing is written to disk.

**Logging mode** captures to disk continuously, and the recording is
complete whether or not the display keeps up.

### The daemon writes the file, not the GUI

Recording must survive the GUI, and it must not depend on it. If the
front end crashes, blocks on a repaint, or is closed by accident, the
capture continues. Sending the stream across the socket only for a Qt
process to write it back to disk would add a second process's
scheduling to the write path and a second place for it to fail, for no
gain: the daemon already holds every frame.

So the GUI sends start and stop, and displays progress, byte count and
counters. The file is the daemon's.

### Format: the frames, verbatim

Frames are appended to the file exactly as they arrived, headers
included. That keeps sequence numbers, device timestamps and overrun
flags in the record, which is what makes continuity provable after the
fact rather than assumed - and it means the same `measure.parse_frames`
reads a file and a live stream. A sidecar records what the frames do
not carry: rate, channel map, track, device banner, host wall-clock at
start.

Appending fixed 4096-byte frames is also the cheapest write available,
which matters at these rates.

### What has to be true, and what is not yet known

The aggregate stream is ~1.81 MB/s, so a continuous log costs about
**6.5 GB per hour** (arithmetic on a measured figure, not a measured
figure itself). Whether this host sustains that write rate *while*
streaming USB is **unmeasured** - the hazard is not average bandwidth
but a stall, from an fsync, an indexer, or a sleeping disk.

Two rules follow, and they are the same ones the display already obeys:

- **Disk backpressure never stalls the USB drain.** The writer runs
  behind a bounded queue. If the queue fills, frames are dropped from
  the record and counted, and the count is surfaced. A recording with a
  hole in it says so.
- **A dropped frame is never spliced over.** The gap is recorded, so
  the file cannot later be read as continuous data. This is invariant 5
  applied to storage.

Measure the sustained write rate before trusting a long capture, and
record the figure in `docs/status.md` rather than assuming a modern
disk copes.

### Playing a recording back

**Built, 2026-08-27.** `python3 -m daemon --file cap.due` serves a
recording in place of a board, and the front end connects to it exactly
as it connects to one:

```sh
python3 -m daemon --file cap.due                 # a source, not a mode
.venv-gui/bin/python -m gui --spawn-file cap.due # both, in one command
```

Or **File > Open recording...** (`Ctrl+O`), which does the same thing
from inside the window: it starts a daemon with `--file` on a free port
and connects to it. **Device > Connect to ...** comes back to wherever
the window was pointed when it started, and the replay daemon it
started is ended with it. The window still does not read the file - the
daemon does - for the same reason it does not write one.

**The daemon opens the file, not the GUI**, and that is the same
decision as "the daemon writes the file, not the GUI" two sections up.
The daemon owns the device; a front end that could swap the source
underneath a running recorder would be exactly the confusion the split
exists to prevent. Replaying a capture is therefore a daemon you start,
the way a board is.

The property that makes it worth having: **the frames the client
receives are the bytes in the file**, headers and CRCs included, so the
frame splitter, the trigger, the measurements, the FFT, the cursors and
the CSV export all run over a recording through the code that runs over
the board. Not a second decoding that agrees with the first until it
does not. `tests/test_daemon_api.py` asserts the byte identity directly.

What a replay will not do is pass for a board:

- `describe()` says `kind="file"`, and carries the sidecar's own device
  block beside it as `recorded`. Two fields, because conflating them is
  how somebody else's capture gets read as a live bench of that track -
  and **this project has two benches, wired differently**.
- The rates in `status` are the recording's, never the ones the caller
  asked to start at. A file cannot be asked to convert at another rate,
  and answering as though it could would put a number in a reply that
  nothing measured.
- `write_awg` refuses. A recording has no generator, and the front end
  greys the generator panel and the rate preset out rather than
  offering controls the source cannot answer.
- Frames are paced from the frames' own `timestamp_us`, so a stall on
  the bench replays as a stall. A gap longer than `REPLAY_MAX_GAP_S` is
  truncated and *counted* as `gaps_shortened`, because a front end that
  looks hung is worse than a distortion that is reported.
- `--replay-loop` starts the file again at its end. The sequence
  numbers jump backwards at the seam, the daemon counts a gap there and
  the display draws a break: the two passes were never continuous.

The window shows where it has got to: a **Replay** bar under the plot
with the position in frames, the pass number when it is looping, and a
**Restart**. It is counted in frames rather than as a percentage
because frames are the unit the sidecar, the daemon's `frames_read` and
the health panel all quote, and a percentage would be the one number
here that did not join up with the rest. The position is
`frames - loops * frames_total`: the daemon counts what it has sent,
which runs on across a loop while the file starts again.

The end of a recording is announced rather than left to be inferred. A
recording stops on its own, which on a board only ever happens because
something went wrong, and a trace that stopped for the ordinary reason
should not read as a fault. It comes off the daemon's own `at_end`
rather than off watching `running` go false: a short recording can be
over before the first status poll, and an edge nobody was there to see
is an end that never gets announced.

Still not built: **scrubbing**. A replay runs forwards from wherever
Restart put it, and `--replay-speed` is the only other handle on it.
Seeking would need the daemon to be able to start at an offset, which
is a change to `FileDevice` rather than to the window.

## Where a change goes

`gui/` is worked by more than one person now, which is why this section
exists at all. Issue #8 has the full survey; this is the part a
contributor needs before touching anything.

| Module | What belongs in it | What must never be in it |
|---|---|---|
| `gui/stream.py` | Frames to something drawable: decoding, the rings, the trigger, measurements, the FFT, the min/max reduction, `AcquisitionState` | **Any Qt import.** A test asserts it |
| `gui/session.py` | The daemon connection and every way it can fail. Signals out, plain calls in | A widget, a layout, a message string aimed at a user |
| `gui/scope.py` | Drawing the reduced data pyqtgraph is handed | Deciding *what* to draw - that is `stream.select` |
| `gui/awg.py`, `gui/health.py`, `gui/measure_panel.py`, `gui/notice.py`, `gui/replay_bar.py` | One panel each, with its own local validation | Talking to the daemon |
| `gui/app.py` | Wiring. Which widget is connected to which slot, and what a signal renders as | Arithmetic, unit conversion, and `daemon.client` |

Two objects carry most of the weight, and both were pulled out of the
window in 2026-08-27 rather than designed in:

**`DaemonSession` owns the socket.** The window had thirteen `try:`
blocks, five of them catching bare `Exception`, and each ended in its
own hand-written status message - so rule 4 below, "refusals come from
the device", was implemented five times and the five did not agree. The
distinction the session exists to keep is between three outcomes rather
than one: a **reply**, a **refusal** (the device said no and its own
message names the limit; the link is fine), and a **loss** (the daemon
is gone, which is not a refusal and must not read as one). Calls return
the reply or `None`; what went wrong arrives as a signal that exactly
one method renders. A caller still repairs its own widget - a checkable
button that asked for something and did not get it has to come back up -
and it learns that from the `None`, not by catching.

**`AcquisitionState` owns what a run accumulates.** Seven numbers that
used to be flat attributes on the window, reset from two places that
were not the same two: `reset_counters()` had exactly one caller, Start,
while Play starts the device too. So Play carried the previous run's
rings, sequence-gap count and discontinuity count into the next run and
drew the old samples as the new one's - rule 2's own failure mode,
reached from a button. Nothing was wrong with any line of it; the defect
was that there were two places to remember and no way to see they had
diverged. `reset()` is now the whole answer to "what does a new run
clear?", and a test compares the state field by field against one that
has never seen a frame, so an eighth number added and forgotten fails
there rather than on screen.

The window keeps read-only properties (`rings`, `rate_hz`,
`frames_shown`, `seq_gaps`, `last_seq`, `overruns`) forwarding onto it.
That is deliberately its read surface - what the health panel, the
export header and the headless tests ask it - and read-only is the
point: there is one writer.

## Menus, toolbar and keys

Added 2026-08-27, with the survey in issue #8. The five verbs - Connect,
Start, Stop, Record, Export - used to sit in the control row under the
plot, where fifteen widgets competed for the window's width. They are
now a menu bar and a toolbar, and what is left under the plot is
grouped by function with separators rather than running flat: **source,
timebase and rate**, then **trigger**, then **view**. Measured in the
same font, the strip went from 2094 px of preferred width to 1564, and
the window's own minimum from 2616 to 2086.

Each verb is one `QAction` appearing in the menu, on the toolbar and on
a shortcut. Three objects would have to be enabled three times, and the
one that got forgotten would be a button that still looks pressable
while nothing is connected.

| | |
|---|---|
| `Ctrl+K` | Connect / Disconnect |
| `Ctrl+Return` / `Ctrl+.` | Start / Stop |
| `Ctrl+Space` | Run/Stop - whatever the device is doing, do the other thing |
| `Ctrl+R` | Record |
| `Ctrl+E` | Export CSV |
| `Ctrl+O` | Open recording |
| `Ctrl+U` | Cursors |
| `Ctrl+1` `Ctrl+2` `Ctrl+3` | Time, spectrum, XY |
| `Ctrl+[` `Ctrl+]` | Shorter, longer timebase |

**Every shortcut carries `Ctrl`, including the ones a bench scope would
give a bare key.** A bare `Space` or `[` belongs to whichever widget has
focus - `Space` opens a focused combo box, a digit types into the
trigger-level spin box - so a bare-key binding works right up until
someone clicks a control. A test walks every action and fails on a
shortcut with no modifier, because that is the kind of rule that only
holds if something checks.

## Where a message goes

`statusBar().showMessage()` was the window's only error channel, and
every message overwrote the last - including the ones the 4 Hz status
poll writes. The device's own refusal, which rule 4 below says is the
one message that must be shown, could be gone in 250 ms.

`gui/notice.py` is a bar under the plot that keeps it until something
replaces it or it is dismissed. The pattern is not new: `gui/awg.py`
already kept a persistent wrapped red label for the generator's own
local refusals, and reserved the height a wrapped one needs because "a
truncated explanation is worse than a bare no - it reads as the whole
answer". This is that label generalised, so there is one answer to
"where does a message go" rather than two.

**A refusal is not a dialog.** It names a limit worth reading twice -
the rate the hardware will actually make, the offset that would fit -
and a modal is the one presentation that cannot be read twice. `start`
used to raise one while the same refusal of the same op from the
generator panel went to the status bar; now everything renders in
`_on_refused`, and the status bar keeps a copy that it is free to lose.
A new run clears the notice, because a notice that outlived the thing
it was about would be the same defect as a counter that did.

Run/Stop follows the device's own `running`, not which button was
pressed last. A replay that reaches the end of its file stops without
anyone asking, and a Run key that tracked the last button would then be
asking the daemon to start something already started.

## Rules the UI must obey

Each of these is a defect this project has already paid for once.

1. **Never drain a queue with an unbounded loop.** When the producer is
   faster than the display it never returns — it hung this GUI's first
   test run for ten minutes. The daemon is built to drop toward a slow
   client and count it, so **leaving frames queued is the designed
   behaviour**, not a backlog to clear.
2. **Do not derive a ring's write position from a running total.** It
   is correct until one append is larger than the ring, and then the
   window silently returns samples that are not the newest — no error,
   no gap, just a stale view that looks live.
3. **Rate controls snap to an integer RC and display `hz_for(RC)`, not
   what was typed.** The hardware's entire set of rates is 39 MHz / RC.
   A frame header once declared the requested rate instead of the real
   one, and that was a defect the suite caught.
4. **Prove freshness before drawing.** Stale kernel-buffered frames
   from a previous run once manufactured a "frozen DAC" that was not
   happening and cost a full session. Sequence numbers near zero and
   device timestamps spanning the host window are the proof, and
   `host/loopback.py` already enforces both.
5. **Draw a visible break at a discontinuity.** Overrun-flagged frames
   are not continuous with the previous frame. Never join across one.
6. **Refusals come from the device.** When a rate is refused, show the
   device's own message naming the limit.
7. **The GUI never blocks the feeder.** Drop frames toward the display
   instead, and count what was dropped.

## Safety

Everything above is loopback only: DAC0 to A0, DAC1 to A1, over a
jumper. Nothing on this board is 5 V tolerant, and there are no clamps,
no series resistors and no protection of any kind.

An external trigger input and anything that reads as "connect your
signal here" are precisely the features that invite wiring a real
signal to an unprotected pin. Those panels stay disabled until the
Phase 3 analog front end exists. A warning label is not sufficient.

## Phasing

- **G0** - **done.** The daemon, the wire protocol and the client exist
  and are tested; see `docs/daemon-api.md`. The Windows serial backend
  this line used to except is landed - `host/transport.py` is the seam
  and both backends are behind it.
- **G1** - **done**: Qt shell, live trace with min/max decimation, roll
  mode, health panel. `gui/`, 14 headless tests. Logging mode is
  daemon-side and already available through the API; wiring a button to
  it is G2 work.
- **G2** - **done**: trigger, measurements, FFT. 38 headless tests, up
  from 14. See "The trigger" and "Measurements and the spectrum" below.
- **G3** - **panel done**: shape, frequency, amplitude and offset in
  volts, mapped through the measured DAC span, with a refusal instead of
  a clamp. Arbitrary upload from file or drawn by hand is still open.
- **G4** - **dual channel, XY, cursors, recording, file playback and
  CSV export done**; calibration open, and scrubbing a replay with it.

G0 carries the real risk, and it is the Windows serial backend rather
than anything about the GUI. G1 to G4 are ordinary UI work.

### The trigger

**The defect it fixes, and why it is not cosmetic.** `CLAUDE.md`: the
GUI "draws the most recent N samples every 33 ms with no trigger at all,
so a trace holds still only when `rate/tone` divides the frame's
samples-per-channel. That is a missing front-end feature, not a signal
defect." The bench has since spent real effort proving that a *different*
shake is the DSO's trigger rather than the board (`docs/awg.md`), so a
GUI that shakes for a third reason is a standing source of
misattribution.

**Measured, not eyeballed.** A tone whose period deliberately does not
divide the window, fed in ragged chunks the way frames arrive: the
free-running window moves by up to **1598 codes** between redraws, the
triggered one by **1**. That is the assertion - displacement in codes -
because bit-equality is the wrong test: the same phase computed at a
different absolute sample index differs by 1 LSB of float rounding, and
calling that "moved" fails for the wrong reason.

**Where it lives.** `gui/stream.select()` returns a `Sweep`, and
`ScopeView.draw` renders whatever it is handed. The decision is Qt-free
so a headless test can reach it without a display; that is the whole
reason the extraction came first.

Four decisions a later session should not have to rediscover:

- **`Sweep.triggered` is not bookkeeping.** A free-running sweep and a
  triggered one are identical as arrays. Auto falls back to free-running
  when it finds no edge, and a scope that does that *silently* is how a
  moving trace gets blamed on the signal. The toolbar readout shows what
  the sweep did, never what the mode box says.
- **A crossing at a discontinuity is rejected.** The step across a
  frame the device flagged is not a transition the signal made.
  Triggering on it would hold the trace still and make a splice look
  like a signal - worse than drawing it moving. Invariant 5 at the one
  place it would be believed.
- **An edge trigger at sample resolution is one sample unstable** when a
  sample lands exactly on the level: that sample reads at the level on
  some periods and below it on others - through truncation in a
  synthetic tone, through noise on a real input. 5 us at 200 ksps.
  Sub-sample interpolation is the fix and is deliberately not built,
  because it changes what is *drawn* rather than only where the sweep
  starts. A test holds it as a known number and says to rewrite rather
  than delete it when interpolation lands.
- **No holdoff knob.** The search takes the most recent qualifying edge,
  so a minimum spacing has nothing to reject. A knob that is programmed
  is not a knob that does anything.

**Still software only.** Nothing here reaches a pin - see Safety above,
which keeps an external trigger *input* disabled until the Phase 3
analog front end exists.

### Measurements and the spectrum

**Every value is a number or a reason, never a plausible-looking
figure.** The panel shows the reason where the number would be - not a
dash, and not the previous reading, because a field that reverts to its
last good value invites a stale number being read as a live one. That is
the failure `docs/status.md` records more than once.

Three refusals, each earned:

- **A window containing a discontinuity measures nothing.** The largest
  excursion may span two unrelated moments and the interval between
  crossings is not a period. In the spectrum it is sharper still: a
  splice is a step, a step is broadband, and the transform spreads that
  energy across every frequency on screen, which reads as a noise floor
  rather than as missing data.
- **A channel swinging under ten codes reports amplitude but not
  timing.** A quiet channel crosses its own midpoint on noise.
- **There is no rise or fall time, deliberately.** The DAC's step is
  789-938 ns measured with a scope (`docs/awg.md`); this ADC's sample
  interval is 1.1 us at its fastest and 5 us at 200 ksps. A 10-90% time
  from these samples would report the sampling interval and call it the
  converter's edge. A test asserts the absence so it is not added by
  accident.

**The spectrum's dB is absolute**, referenced to a full-scale sine
rather than to the largest bin, so two captures compare. Normalising by
the window's own sum keeps a tone's reported height the same whichever
window is chosen - measured, all four agree within 0.05 dB - so only the
leakage changes, which is the whole reason for choosing one. Scalloping
is bounded rather than hidden: a tone between bins under-reads by up to
Hann's 1.42 dB, and a test holds the loss inside that so a real error
cannot hide there.

**The transform is capped at 16384 points.** The ring holds two seconds,
1.8 M samples at the full rate, and an FFT that size inside a 33 ms
redraw would block the feeder.

**Two defects that only the board could find.** Both were invisible
against `FakeDevice`, which produces a clean tone and never drops a
frame - which is the argument for validating a display against hardware
even when its logic is testable without one.

- **A sequence gap reached the health panel and reached the ring as
  nothing.** Only the device's own overrun flag marked a break, so
  frames dropped *between the daemon and the window* were counted and
  then drawn straight across. Rule 5 has the daemon drop toward a slow
  client by design, so this was the common case, not a rare fault:
  61 gaps in a six-second run, every one joined.
- **Noise at the midpoint was counted as crossings.** A sine crosses its
  midpoint once per period in theory; through an ADC it wanders across
  it on the way. Three captures of one unchanging signal read 97.66,
  146.41 and 195.31 Hz. Hysteresis of a tenth of the signal's own
  peak-to-peak fixed the crossings; the *median* interval rather than
  the mean across the endpoints fixed the estimator, which turned one
  spurious edge in a three-crossing window into a doubling.

**The frame header's rate is per channel**, and it says so. Reading it
as an aggregate is how 195.31 Hz looked like it "exactly matched
50000/256" when the signal was 50000/512.

**The generator refuses rather than clamps.** The DAC is not
rail-to-rail - `CLAUDE.md` lists that among the facts that are easy to
get wrong, because writing zero does not give ground - so "1.5 Vpp at
0.4 V" is not producible. A panel that silently clamped it would emit a
clipped waveform, and a clipped waveform on this bench looks exactly
like the converter misbehaving, which is a diagnosis this project has
paid for more than once. The refusal names the offsets that *would*
work, because that is the number the user is actually after.

**Cursors, recording and export.** Three notes worth keeping:

- **The cursors' y values are read off the drawn curve, not
  re-derived**, so the number agrees with the pixels beside it. And the
  sample is the nearest one, never interpolated: the curve is already a
  min/max envelope with two points per column, so interpolating would
  invent a value between a column's minimum and its maximum, which is
  not a value the signal took. A cursor on a NaN reads nothing.
- **Recording is the daemon's.** This section already said "the daemon
  writes the file, not the GUI"; the button only asks. Frames go to disk
  exactly as the device sent them, header and CRC included, so a
  recording replays through the same parser that read it live - which
  it now does: `--file` is the reader, and "Playing a recording back"
  above is what it is for. Until 2026-08-27 that sentence described a
  property nothing exercised, and the Record button wrote a format with
  no reader anywhere in the repository.
- **Export is the sweep on screen and says so in its header**, along
  with the rate, the source channel, whether it was triggered, and the
  ADVREF its volts were scaled by. That last one is not decoration:
  ADVREF moved 0.91% in this project once already, and a column of volts
  without its reference cannot be compared across that. A discontinuity
  is a `break` column rather than a missing row, because the time step
  does not jump across a join - the samples are adjacent in the ring
  and not in time - so a reader could not otherwise see it.

**The generator, end to end on the board.** Volts in, volts back:
1.500 Vpp requested at 1.675 V, and the loop returns 1.5248 Vpp at a
mean of 1.6390 V, 500.0 Hz, zero underruns. Both errors are accounted
for rather than mysterious - the **-36 mV** offset is the ADC's own,
which `baseline.json` records deliberately uncorrected (its ADC-derived
span sits 32 mV below the scope's for the same reason), and the
**+1.65%** amplitude is inside the DAC span's stated
`span_tolerance_mv` of 40, which is +/-1.8% of 2193 mV.

Worth knowing what that bounds: the front end agrees with the bench
scope to about the tolerance the scope's own span carries, and no
better. It is not a calibration.

**Volts come from the measured reference.** `ADVREF` is 3270 mV, not the
nominal 3300, and the panel footers which it used. The loop is
ratiometric - the DAC's reference *is* the ADC's - so the board cannot
measure its own reference and every volt on screen is scaled by a number
that came from an instrument this board cannot be. A reading that cannot
be attributed is not a measurement.

## Dependencies and environments

Settled, and it revises what `CLAUDE.md` used to say. Everything with
dependencies runs from a venv: the test suite already does, the GUI
will, and a Windows serial backend may. `host/` stays stdlib, but as a
property preserved rather than a rule extended - it buys a diagnostic
that needs no install step on the bring-up machine, and it already
holds, so keeping it is free.

The distinction that resolves the apparent conflict: `python3 -m venv`
works offline and `pip install` does not. The venv was never the
hazard. Tools in `host/` may be run from one; being import-clean only
means they also run when the venv is the broken thing.

The daemon therefore stays stdlib on macOS and Linux because it already
is, and takes a venv on Windows if its backend needs pyserial. Neither
weakens anything, because bring-up does not happen on Windows.

What is self-contained is the **lockfile**, not the venv. A venv holds
absolute paths and platform-specific wheels; it does not travel between
operating systems, architectures, or Python versions. So: one pinned
declaration committed, one venv per machine created from it, none of
them committed. Extras keep it to a single declaration:

```sh
pip install -e .            # daemon: stdlib, nothing pulled
pip install -e .[gui]       # PySide6, pyqtgraph, numpy, scipy
pip install -e .[dev]       # pytest
```

**Which interpreter, settled by installing it.** The GUI venv is
`.venv-gui` on Python 3.13.14, carrying PySide6 6.9.3 (Qt 6.9.3),
pyqtgraph 0.14.0, numpy 2.5.2 and scipy 1.18.1 - installed on this
machine and imported, not inferred from metadata. PySide6 is
`cp39-abi3` and declares `>=3.9,<3.14`, so 3.14 is out for the GUI
while the test venv is happy there; its wheel is
`macosx_12_0_universal2`, which this host satisfies. The front end can
be developed here.

Providing the interpreter is the OS user's job - the project declares
what it needs and does not work around an old one.

For a machine with no package manager, vendor the wheels and install
with `--no-index --find-links`. That is a better offline story than
having no dependencies, because it covers the GUI too.

## Open questions

