# Daemon API

The daemon owns the board and serves clients over a socket. This is the
reference for that socket: framing, the command catalogue, and the
rules a client can rely on. `docs/frontend.md` says why the daemon is a
separate process at all; this says how to talk to it.

**Status: implemented, and tested without hardware.** `host/daemon/`
plus `tests/test_daemon_protocol.py`, `tests/test_daemon_api.py` and one
hardware case in `tests/test_daemon_hardware.py`.

```sh
python3 -m daemon --fake         # synthetic frames, no board
python3 -m daemon --file cap.due # replay a recording; see "Replay"
python3 -m daemon                # the real thing
```

**Run it on a free-threaded interpreter.** With four busy Python
threads in the process, the GIL build underran playback 13 times and
read 132 frames where a quiet run reads ~890; the free-threaded build
of the same version underran zero times and read 891. The daemon is
stdlib only, so it needs no free-threaded wheels - `python3.14t -m venv
.venv-ft` is the whole setup. Measured in `docs/status.md`.

## Transport

TCP. The default bind is **all interfaces with no authentication**, on
the stated assumption of a trusted network - the decision and its
consequences are in `docs/frontend.md`. `--host` narrows it.

Both directions carry the same framing:

```
off sz  field
-------------------------------------------------
 0   2  magic  "DU"
 2   1  type
 3   1  flags   reserved, 0
 4   4  body length, little endian
 8   -  body
```

| Type | Value | Direction | Body |
|---|---|---|---|
| `CMD` | 1 | client to daemon | JSON object |
| `EVT` | 2 | daemon to client | JSON object |
| `FRAME` | 3 | daemon to client | one device frame, **verbatim** |
| `AWG` | 4 | client to daemon | waveform bytes |

A body may not exceed 4 MB. A bad magic, an unknown type or an oversize
declared length ends the connection: a stream that has lost its framing
has already produced an unknown amount of garbage, and hunting for the
next plausible magic invents structure that may not be there.

### Frames cross verbatim

A `FRAME` body is exactly what the device produced - 32-byte header and
4064 bytes of payload, sequence number, timestamp, overrun flag and CRC
untouched. So a client proves continuity from the bytes rather than
trusting the daemon, `host/measure.py` parses a socket and a serial
port identically, and a future browser head gets the same bytes.

## Commands

Every `CMD` carries `op` and may carry `id`. The reply is an `EVT` with
the same `id`; unsolicited events carry none. An error is
`{"event":"error","code":...,"message":...}` and the message names the
limit rather than saying no.

| op | Needs control | Does |
|---|---|---|
| `hello` | no | `{role: "control"\|"observer"}`. Returns the role granted, `granted`, the protocol version and the device |
| `ping` | no | `pong` |
| `status` | no | Everything below under [Status](#status). Host-side only; safe to poll |
| `counters` | no | The device's own counters. Control channel only - never the console |
| `trace` | no | Playback occupancy and the converter's own rate trace. Control channel only |
| `load` | no | The device's main-loop load. Control channel only - never the console |
| `caps` | no | Rate limits, modes, device description |
| `rate` | no | Snap `adc_hz`/`dac_sps` without touching the device |
| `subscribe` | no | `{frames: bool}` - start or stop receiving `FRAME` |
| `start` | yes | `{mode, adc_hz, dac_sps, channels, preset}` |
| `stop` | yes | Stop the device |
| `record.start` | yes | `{path}` - capture frames to disk |
| `record.stop` | yes | Close the file, return the sidecar |
| `console` | yes | `{text}` - raw device console, board only |

Modes are `capture`, `play` and `loop`. Capture-only runs from a
console preset (`preset`, default `"1"`), because `=<dac>,<adc>` applies
to `L` and `P` only; `play` and `loop` take the rates.

### Rates come back as the hardware makes them

Every rate is `39 MHz / RC` for an integer RC, and `rate` returns the RC
and the rate that RC produces:

```json
{"op":"rate","adc_hz":200001,"channels":2}
{"event":"rate","adc":{"requested":200001,"rc":194,"actual_hz":201030}}
```

RC truncates, so the answer is the nearest rate **at or above** the
request - one hertz more than 200,000 asks for a rate 1,030 Hz higher.
A client displays what comes back, never what it asked for. A header
that once declared the requested rate rather than the produced one was
a defect, and this is the same mistake at the other end of the wire.

**And `actual_hz` is still what the timer was programmed for, not what
the converter delivers.** Between roughly **750,000 and 1,300,000 sps**
the DACC converts below its programmed rate - by 0.4% to 3.1% depending
on the rate, and *which* deficit a run gets is chosen when playback
starts, so two runs at one rate can differ. Issue #48 has the map and
`docs/awg.md` the detail; `DACC_MR_REFRESH` is the register and the
effect is the silicon's, on both tracks and both hosts.

So the chain a client sees is:

    requested   ->   actual_hz (RC truncation, reported here)
                ->   what the DAC actually converts (NOT reported)

The daemon does not measure the third and does not refuse rates in that
band - a refusal would be wrong, since the rates work and most
applications will not care about 1.6%. **A client that must know the
delivered rate has to read the playback counters** (`consumed` and
`run_us` from `trace`) and compute it, which is what
`tools/issue47_ratio.py` does.

The front end is unaffected: it pins loop mode at 200,000 sps, which is
RC 195 and measured clean - median ratio 0.99947 over eight runs. This
is reachable from the API and not from the GUI, which is the same
division the duplex-cost note in CLAUDE.md draws.

**Capture has no equivalent gap, and that is measured rather than
assumed.** The capture side reports its rate the same computed way -
`(SystemCoreClock/2) / acq_configured_rc()` - so the question applies to
it just as much, and a reader who has got this far will ask. On
`windows-desk`, all five presets deliver exactly what they declare:
50,000 / 100,000 / 200,000 / 402,061 / 453,488 sps all at ratio
**1.00000**, in thirty runs, including both rates adjacent to the
playback band. So the warning above is about playback and only
playback, and `rate_hz` in a frame header can be taken at face value.

The check is the sample count over the span between the first and last
frame's own `timestamp_us`, which is `micros()` - a free-running MCK
timer, not derived from the sample count, so a missed conversion shows
as fewer samples per microsecond exactly as the DACC's does.
`PortStats.measured_rate_hz()`. It cannot see a wrong MCK, since the
trigger and `micros()` share it; that is a different question from this
one. `records/issue48-adc-rate-windows.jsonl`.

Rates past a limit are refused with the limit named: the trigger floor
(RC 86 for two channels, RC 44 for one - measured, not derived, and not
halvable) and the DACC ceiling at RC 28. The board's own refusals are
forwarded verbatim - `# loop: ADC 906976 Hz x2 ch refused (max 453488)`
reaches the client as an error carrying that text. The **capability
report** in `docs/frontend.md` is what ends the duplication.

An asymmetry found while testing this has since been closed in
firmware: the capture path had refused past its floor since bring-up,
while a DAC rate past the DACC ceiling was acknowledged rather than
refused. Both tracks now refuse below RC 28 and name the limit, so the
host table is a courtesy again rather than the only thing standing
between a console user and a rate the converter cannot make.

## Events

| event | When |
|---|---|
| `hello`, `pong`, `status`, `caps`, `rate`, `subscribed`, `ok` | replies |
| `started`, `stopped` | broadcast when the device starts or stops |
| `recording`, `recorded` | broadcast when a recording starts or ends |
| `awg_ok` | a waveform upload was accepted |
| `error` | with `code`: `unknown_op`, `bad_json`, `bad_type`, `not_control`, `refused`, `internal`, `protocol` |
| `device_error` | the device raised while being read |

## Ownership

One client holds control; the rest may attach and watch. Control goes
to the first client that asks for it in `hello`, is released when that
client disconnects, and a client that asked and did not get it is told
so (`granted: false`) rather than silently demoted - that is how two
front ends end up both believing they own the board.

## Backpressure

Each client has a bounded queue and its own sender thread. When it
fills, the **oldest frames** are dropped and counted, and the count
appears in `status`. A client that stops reading loses frames; it does
not slow the device, the recorder, or anybody else.

Dropping the oldest rather than the newest is deliberate: a client that
fell behind wants what is happening now, not a replay of what it
missed. Nothing is ever spliced, and the drop count is the client's
proof that a gap exists - the display rule and the device's own
invariant 5 are the same rule.

### That isolation needs a core, and this is its bound

**Accepted limit, ruled 2026-09-01.** The promise above holds on a host
with a core to spare. It does not hold under CPU contention, and the
reading client can lose a frame too - about half the time once the
lever is pulled.

| host | what pulls it |
|---|---|
| Linux | ~2x CPU oversubscription |
| macOS | contention, and it is **more sensitive** - it breaks around 1x where Linux needs 2x |
| Windows | not contention. It appears inside a full suite run with load held constant |

**The bound is two-sided, and the second half is why this is a limit
rather than a fragility.** Measured on two hosts with two different
levers: **one** of the seven daemon multi-client tests fails, and it is
the same one each time. Everything else the daemon does is untouched by
the same load.

**No mechanism is identified**, on either route. One thing is known and
untried: the daemon's reader thread never calls `host/rt.py`, which
exists for time-sensitive I/O threads and which `measure.py` does use.
A promoted reader may remove the contention route; nobody has run that
arm at a load that fires the lever.

Do not read a clean run as proof this is fixed. **A null taken with the
wrong lever for your host reads exactly like a pass** - the two benches
that found these levers each spent an afternoon proving the other's
lever did nothing.

The device is drained whether or not anyone is listening. A CDC device
that stops draining bulk OUT hangs the host in `close()` waiting on
write URBs that never complete.

## Recording

`record.start` writes frames to disk **verbatim**, and the daemon does
it, not the client - a capture has to survive a front end that crashes
or is closed. A `.json` sidecar beside the file carries what the frames
cannot: rates, mode, device, frame size, start and stop times, and the
counts.

The writer sits behind a bounded queue of its own. If the disk stalls -
an fsync, an indexer - frames are dropped from the record and counted
in `dropped`, in the sidecar and in `status`. A recording with a hole
says so. Sustained write rate on this host is **unmeasured**; ~1.81
MB/s is about 6.5 GB per hour, which is arithmetic on a measured figure
and not itself a measurement.

## Replay

`--file` serves a recording in place of a board. It is the other half of
the section above, and until 2026-08-27 it did not exist: `record.start`
wrote a format nothing in the repository read back.

```sh
python3 -m daemon --file cap.due                 # paced as recorded
python3 -m daemon --file cap.due --replay-loop   # start again at the end
python3 -m daemon --file cap.due --replay-speed 4
python3 -m daemon --file cap.due --replay-fast   # as fast as it is read
```

**The frames a client receives are the bytes in the file**, headers and
CRCs included. That is the property the whole thing rests on: everything
above the daemon - the frame splitter, the trigger, the measurements,
the FFT, the export - then runs over a recording through exactly the
code that runs over a board, rather than a second decoding of the same
format. `tests/test_daemon_api.py` asserts the byte identity directly.

It is a source and not a mode, so the client-facing protocol is
unchanged: `hello`, `subscribe`, `start` and `stop` mean what they
always did, and `start` rewinds to the beginning of the file.

What it refuses, and what it will not pretend:

| | |
|---|---|
| `describe().kind` | `"file"`, with the sidecar's own device block beside it as `recorded`. Two fields, because a capture read as a live bench of that track is exactly the confusion **two differently-wired benches** make easy |
| `status.rates` | the recording's, with `source: "recording"`. Never the rate the caller asked to start at - a file cannot be asked to convert, and answering as though it could would put a number in a reply that nothing measured |
| `start mode=play` | refused. A recording has samples to replay, not a generator |
| a waveform upload | refused, and the session survives the refusal |
| a differing `frame_bytes` in the sidecar | refused at open, naming both sizes. The 4096-byte frame is compiled in and `frame.h` calls the geometry load-bearing; reading across it would misalign every sample and still decode to plausible numbers |
| a trailing part-frame | reported as `truncated_bytes`, not trimmed in silence. A recorder killed mid-write leaves a file whose end is unknown, and that is worth knowing before a measurement is taken off it |

Pacing comes from the frames' own `timestamp_us`, so a stall on the
bench replays as a stall rather than being smoothed to the nominal rate.
One exception, and it is counted: a gap longer than `REPLAY_MAX_GAP_S`
(1.0 s) is truncated and added to `gaps_shortened` in `counters`,
because a front end that looks hung is worse than a distortion that
reports itself. `--replay-loop` wraps, and the sequence numbers jump
backwards at the seam: the daemon counts a gap there and a display draws
a break, because the two passes were never continuous.

`counters` on a replay carries `frames`, `frames_total`, `loops`,
`at_end`, `seq_gaps`, `gaps_shortened`, and `recorded_dropped` - what
the recorder itself lost to the disk, carried through from the sidecar
so a hole in the source is never read as a fault of the replay.

## Status

```json
{"protocol":1,"uptime_s":12.5,"device":{...},"running":true,
 "mode":"capture","rates":{...},"frames_read":812,"discarded_bytes":0,
 "controller":"127.0.0.1:52344","clients":[{"addr":"...","role":"control",
 "subscribed":true,"dropped":0,"frames_sent":812}],
 "recording":null,"waveform_bytes":0,"counters":{...}}
```

`discarded_bytes` counts bytes thrown away while looking for a frame
magic. Anything beyond one frame's worth means framing is not locking
on, which reads downstream as data corruption.

### Status carries the latency histograms

`status.jitter` holds three log-2 microsecond histograms: `read_gap`,
the interval between device reads that returned data; `fanout`, what
one frame costs to hand to every client and the recorder; and `feed`,
the interval between the feeder's writes, present while playback runs.
Each reports `n`, `mean_us`, `max_us` and percentile upper bounds.

Read `max_us` first. A mean hides the one late wakeup that empties a
buffer, which is the only kind of failure this system has ever had.

### Status asks the device nothing

Poll it as often as you like. That is a property worth stating because
it was not free: the description used to be fetched per call, which
meant asking the board for its banner, and a banner print stalls the
main loop long enough for the DAC to drain its ring - **eleven
underruns per call, measured, every run**. The description is now asked
for once and cached, the track being unable to change without a
reflash.

`counters` is the op that does touch the device, which is why it is
separate. `B` is a short report and measures clean mid-stream, but a
client that wants numbers during playback should still prefer taking
them after the stop.

### `trace` reports the rate the converter actually held

`counters` says what went wrong; `trace` says what the DAC was actually
doing. It returns the playback ring's occupancy histogram and, more
usefully, `rate_us` - absolute device microseconds sampled every
`rate_decim`-th *consumed* buffer - with `window_rates` differenced from
them and `traced_byte_rate` spanning the whole trace.

Its own op rather than part of `counters` because it is a different
device command (`O`) and a reply two orders of magnitude longer: two
lines of up to 256 values. Like `counters`, `status` never drags it in.

Why per-window and not a whole-run average: at 886,363 sps the converter
holds one of two discrete rates, -1.56% or -2.34% of nominal, chosen at
`play_start` and held for the entire run. An average across a rate that
changes is a number the hardware never produced. The trace is keyed on
consumed buffers rather than on ENDTX, so a window is exactly
`rate_decim` buffers of data whatever the underruns, and a run that ends
starved - a drained run, deliberately - writes no misleading samples.

### `load` asks whether the main loop is keeping up

`counters` asks what went wrong on the sample path and `trace` asks what
rate the converter held. `load` asks the third question, and it is the
one no host-side figure can answer: is the device's main loop keeping
up at all. It returns `passes`, `dev_us`, the per-pass cycle histogram
and `max_us`.

**A rate comes from differencing two of these.** `passes` and `dev_us`
are cumulative since boot or the last clear, so the caller picks its own
interval. `max_us` is the exception and it is a trap worth naming: a
maximum cannot be differenced, so it is the worst pass since the last
clear and it persists. A board that was deliberately stalled once with
`=<ms>S` reports that stall in `max_us` for the rest of its uptime -
measured on `windows-desk`, where a 1.5 s stall run for a screenshot was
still the reported maximum hours later. Read it as a high-water mark,
never as a live figure.

**No console fallback - and since #51 q3 neither has `counters` or
`trace`.** `CLAUDE.md`'s
rule is that printf is a debug method and not an instrument: one console
status command blocks the main loop for 13-20 ms, where twenty GET_LOAD
queries cost 0.29 ms in total. A load figure taken by a method that
blocks the loop for 15 ms would be measuring the instrument rather than
the device, so a board without a control channel gets an error instead
of a misleading number. That argument was always general; it now
governs all three.

Like `counters` and `trace`, `status` never drags it in.

**What it cannot see.** Invariant 1 is that the CPU never touches sample
data - PDC writes the buffer, USB DMA reads the same buffer - so a loop
that is not perturbed is *not* evidence that the sample path is healthy.
Measured on `windows-desk` against issue #44: across twelve loop runs
losing between 0 and 259 inbound frames, `passes` moved by one per
second and the mean pass time was identical to the hundredth of a
microsecond. Everything that goes through the processor reads clean
while the DMA path loses data, which is the design working as intended
and a reason not to read a healthy load as an all-clear.

## Versioning

`protocol` is an integer, reported in `hello` and `status`, and declared
in exactly one place (`daemon/protocol.py`). A client checks it and
refuses what it does not understand rather than guessing.

## What is deliberately absent

- **No authentication.** See the trusted-network decision.
- **No DSP.** The daemon moves bytes and owns timing. Analysis belongs
  to the client, which has numpy; the daemon is stdlib.
- **No firmware flashing.** Out of scope; `tools/flash.sh` keeps it.
- **No signal generation.** A client uploads a waveform; the daemon
  loops it through `measure.Feeder`, whose clock-paced policy is
  measured and is not to be reinvented.
