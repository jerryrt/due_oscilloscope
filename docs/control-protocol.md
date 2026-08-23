# Control over the native port — design proposal

**Status: proposal, nothing implemented.** Written to be argued with
before any of it is built.

## Why

The deployed board is used with **one USB cable, the native port**.
Making an end user plug in two cables to use it is not acceptable. The
programming port and everything built on it stay for development and
validation, but nothing in the shipped design may depend on them.

Today that means the deployed board has **no control path at all**:

- Commands are read only from `uart_getc()`
  (`apps/baremetal_bringup/main.c`), which is the UART on the
  programming port.
- The native port's descriptor (`drivers/usb_cdc.c`) exposes one
  CDC-ACM function: a comm interface with an interrupt endpoint, and a
  data interface with bulk OUT (playback) and bulk IN (frames). Nothing
  parses commands from either.
- Bulk OUT is drained and discarded when nothing consumes it.

A second motivation, and the one that decides the shape: the protocol
should export **more device state and finer-grained control** than the
current single-letter console commands can carry.

## What must not be done

**Do not multiplex commands in-band on bulk OUT.** Two independent
reasons, both measured rather than argued:

1. It forces the CPU to scan the sample stream looking for command
   markers, which is exactly what invariant 1 forbids.
2. `Feeder.WRITE_SIZE` is 512 because macOS's CDC-ACM output path
   silently discards 0.45–0.85% at every rate above 200 ksps unless
   every `write()` is the same size. Injecting a differently-sized
   command into that stream risks reintroducing a loss that no counter
   on either side reports.

**Do not put the heartbeat on the console.** Polling `B` at 20 Hz took
RC 65 from 6 underruns to 30 when the ring was short, because a printf
holds the main loop for milliseconds against a 0.95 µs conversion.
Where you most want to observe, observing is what breaks it.

## Transport: a second interface

Endpoints are not scarce. The CMSIS header declares
`UOTGHS_DEVEPTCFG[10]` and DMA channels 1..7; the native port uses
0 (control), 1 (ACM notification), 2 (bulk OUT), 3 (bulk IN). Four and
up are free.

Two candidates:

| | Second CDC interface | EP0 vendor requests |
|---|---|---|
| Enumerates as | a second `/dev/cu.*` on the same cable | no serial node |
| Host code | opens a second port; `termios` as today | `libusb`, new dependency |
| Talk to it by hand | yes, a terminal works | no |
| Endpoint cost | 1 interrupt + 2 bulk | none |
| Interferes with the sample path | no — separate endpoints | no |

**Recommendation: the second CDC interface.** It keeps the "you can
poke it from a terminal" property that this project has leaned on
throughout bring-up, and it costs endpoints we have.

Size the control endpoints at 64 bytes, not 512. Commands are small,
and endpoint FIFO memory is shared DPRAM that the two 512-byte
double-banked data endpoints already draw on *(check: total DPRAM
budget not verified)*.

## Firmware structure: one executor, two transports

**The command execution layer must be shared.** Whether a command
arrives on the programming port or the native port, it runs the same
code. The transports may differ freely — the UART side stays
line-oriented ASCII (`h`, `P`, `=..L`), the native side is binary and
framed — but each transport only *parses into a common command
representation* and hands it to one executor.

Today `main.c` tangles parsing and execution in a `switch` over
`uart_getc()`, so this means extracting a command layer **before**
adding the second transport, not after:

```
uart_getc() ──► ascii_parse ──┐
                              ├──► cmd_t ──► cmd_execute() ──► drivers
usb ctrl EP ──► frame_parse ──┘
```

`cmd_execute()` returns a result the transport renders: the UART prints
it as the text a human reads today, the native port packs it into a
response frame. That is what keeps the two from drifting.

## Framing

`drivers/playstat.h` is the working precedent and should set the
pattern: a magic distinct from `FRAME_MAGIC`, a version byte, a CRC,
and a fixed layout the host mirrors. A parser that meets one of these
in a stream it did not expect must reject it rather than half-read it.

Request and response both framed; every request carries an id the
response echoes, so a reply cannot be mistaken for the answer to a
different question.

## The heartbeat

A host-initiated ping/pong at a fixed interval, carrying the device's
own clock. What it is good for, and what it is not:

**Good for — liveness.** Objective 0c wedges the *host* in `close()`
with the board still healthy; a stalled main loop would be a different
failure with the same outward silence. A heartbeat separates them in
one interval instead of by reading LEDs and running `sample`.

**Good for — clock offset.** Round-trip timing is the only way to
estimate phase between host and device clocks. Nothing in the project
does this today.

**Not good for — frequency.** A rate estimated from RTT inherits the
CDC pipeline delay, which varies with load: 55–450 KB sits in the
driver below the tty layer. The rate loop already solves this the right
way, with a long baseline of one-way device timestamps
(`measure.playstat_rate`), and agrees with an independent device-side
measurement to 0.001–0.018 pp. **Keep taking frequency from the
one-way timestamps; use the ping only for offset and liveness.**

Interval: ~1 Hz. It must never printf, and it must never touch the
sample path.

## State worth exporting

Beyond what `B` and `O` print today, and driven by what this session
kept needing and not having:

- `play_consumed`, `play_underruns`, `play_bytes_in` with a device
  timestamp — already the `playstat` record's payload; the control
  channel makes it available without a stream running.
- Occupancy histogram and `play_occ_min`, currently only via `O`.
- Overrun counters, currently only in the frame header.
- Build identity: firmware version and track, so a host can refuse a
  mismatched pairing rather than misparse.
- Whatever the rate loop needs to be closed in *capture-only* mode,
  which has no carrier at all today.

## Settled

Three questions this document opened have been answered by the project
owner, and they simplify it.

**Reset in deployment is the cable.** The native port is also the power
source, so unplugging it power-cycles the board. Losing NRSTB with the
programming port costs nothing that matters, and no software reset
command is required.

**printf diagnostics are development-only.** They are not intended to
be available in deployment at all, so nothing has to replace the UART
channel `docs/debugging.md` is built around. This also removes the last
reason for the console to exist on the shipped path.

**Track A follows.** That looked like it would force Track A to stop
using the Arduino core for enumeration, which would have cost it its
value as an independent oracle. It does not: the SAM core at 1.6.12
defines `PLUGGABLE_USB_ENABLED` and ships `PluggableUSB.{h,cpp}`, so a
second interface is added through the core's own extension mechanism
rather than by patching it *(check: PluggableUSB has not been exercised
on this board yet)*. Track A keeps the core for enumeration exactly as
invariant 3 intends.

## Open questions

- Total endpoint DPRAM budget on this part, and whether two more
  64-byte double-banked endpoints fit alongside the existing 512-byte
  pair *(check)*.
- Track B hand-writes its descriptors and Track A will go through
  PluggableUSB, so the two arrive at the same wire layout by different
  routes. The interface and endpoint numbering has to be pinned in this
  document, or they will drift and the host will need to tell them
  apart.
