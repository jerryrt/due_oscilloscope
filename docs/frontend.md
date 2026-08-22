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
that is the hazard in `docs/usb.md` and it is objective 0c in
`docs/HANDOFF.md`, seen once in the wild.

The dependency rule stays satisfiable. `CLAUDE.md` requires `host/` to
be stdlib only and to run from the system interpreter, because
bring-up must not need a package manager. The GUI needs numpy and Qt.
The process boundary is what lets both be true at once, without either
rule being weakened.

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
DAC's real 546-2760 mV span, per-channel DAC0 and DAC1 via tag
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
8. **Saved setups and stored calibration.** A host-side file is enough
   to start. A device-side flash page only if calibration should follow
   the board rather than the machine.

Every firmware item costs double. The tracks share no source by design
and must stay feature-equivalent, so each lands twice with the same
command letter and output format. Item 1 is the partial exception: a
capability report lets the GUI tolerate one track being behind the
other.

### Explicitly out of scope

**Firmware flashing.** The front end does not program the board.
`tools/flash.sh` keeps that job.

## Rules the UI must obey

Each of these is a defect this project has already paid for once.

1. **Rate controls snap to an integer RC and display `hz_for(RC)`, not
   what was typed.** The hardware's entire set of rates is 39 MHz / RC.
   A frame header once declared the requested rate instead of the real
   one, and that was a defect the suite caught.
2. **Prove freshness before drawing.** Stale kernel-buffered frames
   from a previous run once manufactured a "frozen DAC" that was not
   happening and cost a full session. Sequence numbers near zero and
   device timestamps spanning the host window are the proof, and
   `host/loopback.py` already enforces both.
3. **Draw a visible break at a discontinuity.** Overrun-flagged frames
   are not continuous with the previous frame. Never join across one.
4. **Refusals come from the device.** When a rate is refused, show the
   device's own message naming the limit.
5. **The GUI never blocks the feeder.** Drop frames toward the display
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

- **G0** - serial backend abstraction, headless daemon, wire protocol.
  Verifiable by the existing pytest suite with no GUI at all.
- **G1** - Qt shell, live single-channel view, roll mode.
- **G2** - trigger, measurements, FFT.
- **G3** - AWG panel with arbitrary upload.
- **G4** - dual channel, XY, record and export, calibration.

G0 carries the real risk, and it is the Windows serial backend rather
than anything about the GUI. G1 to G4 are ordinary UI work.

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

For a machine with no package manager, vendor the wheels and install
with `--no-index --find-links`. That is a better offline story than
having no dependencies, because it covers the GUI too.

## Open questions

- Whether the GUI can run on this machine at all. The system
  interpreter is Python 3.9.6 and recent numpy and PySide6 releases
  have moved past 3.9 *(check the current wheels)*. If they have, the
  GUI venv needs an interpreter this machine does not have, and with no
  package manager that means a python.org installer. Worth settling
  early: it decides whether the front end is developed here or only on
  the other two platforms.
- Record buffer size and whether the GUI keeps every sample or only
  what it displays.
- Whether the daemon binds loopback only, or offers remote operation -
  and if remote, what authenticates the connection.
- Where calibration constants live: host file, or device flash.
