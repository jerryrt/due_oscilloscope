# Daemon API

The daemon owns the board and serves clients over a socket. This is the
reference for that socket: framing, the command catalogue, and the
rules a client can rely on. `docs/frontend.md` says why the daemon is a
separate process at all; this says how to talk to it.

**Status: implemented, and tested without hardware.** `host/daemon/`
plus `tests/test_daemon_protocol.py`, `tests/test_daemon_api.py` and one
hardware case in `tests/test_daemon_hardware.py`.

```sh
python3 -m daemon --fake        # synthetic frames, no board
python3 -m daemon               # the real thing
```

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
| `status` | no | Everything below under [Status](#status) |
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

Rates past a limit are refused with the limit named: the trigger floor
(RC 86 for two channels, RC 44 for one - measured, not derived, and not
halvable) and the DACC ceiling at RC 28. The board remains the
authority and its refusals are forwarded verbatim; these checks only
catch what can be caught early. The **capability report** in
`docs/frontend.md` is what ends the duplication.

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
