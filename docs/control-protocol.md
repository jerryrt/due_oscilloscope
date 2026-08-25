# Control over the native port

**Status: the transport exists on Track B; nothing speaks over it yet.**

| | |
|---|---|
| Command layer split out of the main loop | done, Track B |
| Second CDC function on the native cable | done, Track B |
| Host discovers the two nodes by interface number | done |
| Frame parser, executor binding, opcodes | not started |
| Heartbeat and asynchronous notifications | not started |
| Track A | not started |

What that means concretely today: the board enumerates two serial nodes
on one cable, `usb_ctl_read()` and `usb_ctl_write()` carry bytes both
ways byte-exact, and the main loop drains the command endpoint and
throws the bytes away. The framing below is still a design and is still
worth arguing with; the numbering above it is now a measured fact.

The rest of this document is written as the proposal it was, because the
reasoning is what makes the parts that are not built yet decidable.

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

**Recommendation: the second CDC interface**, and the reason is not
convenience.

EP0 is testable from code - it needs libusb or pyusb rather than a
terminal, which is a dependency this host does not have today but could
take. The argument against it is architectural: **EP0 is host-initiated
only.** The device can never push on it. This channel exists to export
more state, and on EP0 every piece of state costs a poll; a bulk IN
endpoint lets the device send status, alarms and events as they happen.

Two smaller costs, recorded so they are not rediscovered: a control
transfer's data stage is small and unstreamed, so anything larger than
a register dump arrives in pieces; and EP0 is shared with enumeration,
so a busy poll loop competes with the transfers that keep the device
attached.

One thing to establish before EP0 is dismissed entirely *(check)*: on
macOS the CDC-ACM driver has already matched and claimed this device
(`AppleUSBDevice`, driver matched, in `ioreg`), and whether libusb can
open it for control transfers regardless has not been tested.

**The control endpoints are 512-byte bulk, single-banked.** That is not
what this document first said - it said 64 bytes, on the reasoning that
commands are small and DPRAM is shared - and the reasoning was fine but
the size is not available. USB 2.0 section 5.8.3: *a high-speed bulk
endpoint must have a wMaxPacketSize of 512 bytes.* It is not a maximum
and there is no small-endpoint case; 64-byte bulk is a full-speed size.
A host might well accept a 64-byte high-speed bulk endpoint, but a
device that enumerates out of spec is a defect waiting for a different
host, and this one has already spent a session on a host-side USB
behaviour nothing reported.

The size is forced; the bank count is what buys it back. **The budget is
4096 bytes** - datasheet 40.2, "4096 bytes of Embedded Dual-Port RAM
(DPRAM) for Pipes/Endpoints" - and a bank costs its endpoint's full
size, so 512-byte control endpoints are affordable only single-banked:

| | size x banks | bytes |
|---|---|---|
| EP0 control | 64 x 1 | 64 |
| EP1 ACM notification | 64 x 2 | 128 |
| EP2 bulk OUT (samples) | 512 x 2 | 1024 |
| EP3 bulk IN (frames) | 512 x 2 | 1024 |
| **in use today** | | **2240** |
| EP4 control notification | 64 x 1 | 64 |
| EP5 control bulk OUT | 512 x 1 | 512 |
| EP6 control bulk IN | 512 x 1 | 512 |
| **after this channel** | | **3328** |

768 bytes spare. Double-banking both control endpoints would need 4416
and does not fit, which is the whole reason the bank count is pinned
here rather than left to the implementation:

| layout | cost | total |
|---|---|---|
| 64 B, 2 banks (what this document first pinned) | 384 | 2624 - fits, but out of spec |
| 512 B, 2 banks | 2176 | **4416 - does not fit** |
| 512 B, 1 bank | 1088 | 3328 - fits |

Single-banking costs throughput and nothing else: the endpoint cannot
accept the next packet until the previous one is read out, so back-to-back
512-byte transfers pay a turnaround. Commands are one frame each and
arrive at human or 1 Hz heartbeat rates, so the cost is not measurable
here. It does mean the control channel must never be used to move bulk
data - if something ever wants to, it takes the spare 768 bytes for a
second OUT bank and re-reads this table.

Two constraints from Table 40-1 that the layout has to respect, and does:
endpoints 4, 5 and 6 allow at most **two** banks each (only EP1 and EP2
allow three), so the "512 B, 2 banks" row was never more than one bank
short of illegal anyway; and all three are DMA-capable, so nothing about
the numbering forecloses moving the control channel onto DMA later.

One ordering rule comes with it (40.5.1.6): **pipes and endpoints can
only be allocated in ascending order**, and re-allocating endpoint x
slides x+1's window without moving x+2, which silently corrupts both.
So the control endpoints must be configured after the sample endpoints,
never in between, and none of the existing four may be re-`ALLOC`ed once
the new ones are up. `configure_data_endpoints()` already walks EP1..EP3
in order; the new ones append.

The hardware also checks this for us: `CFGOK` is set only if the
requested size and bank count fit the endpoint's maximum *and* the
DPRAM. `usb_cfg_fail` already counts endpoints that come back without
it, so a budget mistake surfaces as a counter rather than as a
mysteriously dead endpoint.

## Numbering, pinned

Track B hand-writes its descriptors and Track A goes through
PluggableUSB, so the same layout is reached by two routes. Both tracks
must present *identical* descriptors, so the numbering is a contract
rather than an implementation detail, and it lives here.

| | interface | endpoints |
|---|---|---|
| CDC comm (data) | 0 | EP1 interrupt IN |
| CDC data (samples) | 1 | EP2 bulk OUT, EP3 bulk IN |
| CDC comm (control) | 2 | EP4 interrupt IN |
| CDC data (control) | 3 | EP5 bulk OUT, EP6 bulk IN |

Interfaces 0 and 1 keep their present numbers, so an existing host that
opens the first CDC function is unaffected by the second appearing.
Endpoints 4 to 6 are free: the CMSIS header declares
`UOTGHS_DEVEPTCFG[10]`.

Two interface association descriptors, one per function, so the host
groups them correctly and does not present the four interfaces as
unrelated. All four bulk endpoints are 512 bytes because high speed
allows no other size; the control pair is single-banked and the sample
pair double-banked, which is where the difference between them actually
lives. The notification endpoints are 16-byte interrupt.

A host tells the two apart by interface number, not by enumeration
order, and `host/ports.py` now does: `usb_interfaces()` asks IOKit which
USB interface is behind each callout device, and `find_all_ports()`
returns the programming port, the sample node and the command node.

On this machine the three are `/dev/cu.usbmodem141201`,
`/dev/cu.usbmodemB_011` and `/dev/cu.usbmodemB_013`. The two native
names sort the same way the interfaces number, which is why taking the
first of them worked before this was written down - and why it is not
what the code does: that agreement is macOS deriving a node name from an
interface number, not anything the device controls. Name order is the
fallback for a host with no `ioreg`, and it is tested as one.

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

## The command set

### Frame

Request and response share one 16-byte header. `drivers/playstat.h` set
the pattern and this follows it: a magic of its own, a version, a CRC,
and a fixed layout the host mirrors.

```
off sz  field      notes
---------------------------------------------------------------------
 0   4  magic      "DUEC"
 4   1  version    = 1
 5   1  flags      bit0 1 = response, bit1 1 = error
 6   2  req_id     echoed in the response, so a late reply to an
                   abandoned request cannot be read as the answer to
                   the next one
 8   2  opcode     see below; echoed in the response
10   2  length     payload bytes following this header
12   4  crc32      over bytes 0..11 and the payload
---------------------------------------------------------------------
16      payload
```

On error, `flags` bit1 is set and the payload is a `u16` code followed
by ASCII text - the same words the console prints today, because the
device already has to produce them for the UART transport and two sets
of refusal wording would drift.

Every response is sent, including for commands with nothing to say.
Silence is never a valid answer: it is indistinguishable from a wedged
device, which is the failure this project has spent the most time on.

### Opcodes

Grouped so the ranges mean something, and every one of them maps onto a
`cmd_execute()` case that the UART transport reaches too.

| op | name | payload in | payload out |
|---|---|---|---|
| `0x0001` | `PING` | — | `dev_us` u32, `dev_ms` u32, `seq` u32 |
| `0x0002` | `IDENTITY` | — | track, fw id, protocol ver, frame bytes, samples/frame, MCK |
| `0x0003` | `CAPABILITIES` | — | RC limits per direction, channel limits, ring depths |
| `0x0010` | `GET_RATES` | — | dac RC + hz, adc RC + hz, channels |
| `0x0011` | `SET_RATES` | dac_sps u32, adc_hz u32, channels u8 | the *snapped* values actually set |
| `0x0012` | `GET_MODE` | — | mode u8 |
| `0x0013` | `SET_MODE` | mode u8, flags u8 | mode actually entered |
| `0x0020` | `GET_COUNTERS` | — | the `play:` and stream counters, with `dev_us` |
| `0x0021` | `GET_OCCUPANCY` | — | `occ_min`, `endtx`, `run_us`, `consumed`, histogram |
| `0x0022` | `GET_RATE_TRACE` | — | the decimated trace, empty when compiled out |
| `0x0023` | `GET_LINK` | — | endpoint and DMA status, activity counters, cfg failures |
| `0x0024` | `GET_LOAD` | — | `dev_us`, main-loop passes, worst pass, MCK, a 32-bucket log2 histogram of pass duration in cycles |
| `0x0030` | `GET_FAULT` | — | the last HardFault record, or empty |
| `0x0031` | `CLEAR_COUNTERS` | — | — |
| `0x0032` | `RESET` | magic u32 | — (no response; the device is gone) |

`SET_RATES` returning the snapped value rather than an acknowledgement
is deliberate. Every rate here is `39 MHz / RC` for integer RC, the
host already has to know what it actually got, and a protocol that
answers "yes" to a request it silently altered is how a project ends up
quoting rates the hardware never ran at.

`RESET` is the one command with no response, and it takes a magic
argument so a corrupted frame cannot reboot the instrument.

### What stays on the UART

The development-only commands - `measure_printf`, `measure_gpio`,
`trigger_fault`, the sweeps and the crosstalk scan - are not in this
set. They exist to characterise the board on a bench, they print pages
of text, and deployment has no console at all. The rule is not that the
two transports expose the same commands; it is that any command both
expose runs the same code.

### Asynchronous notifications

The device may send an unsolicited response - `flags` bit0 set,
`req_id` zero - on the control IN endpoint. That is the whole reason
this is an endpoint pair rather than EP0. The first users:

- overrun or underrun crossing a threshold, so the host learns without
  polling;
- mode changed by the device itself, which today happens on a refusal
  the host has to go looking for;
- fault captured, so a HardFault reaches the host rather than waiting
  for someone to ask.

### Load, and why it is here

Every other counter in this set reports damage: an underrun, an
overrun, a ring that ran dry. All of them say the main loop was too
slow *somewhere*, and none says when, for how long, or how close to the
edge a run that passed actually came. Objective 0c is diagnosed today by
reading endpoint registers over the programming port - which is exactly
the port a deployed board does not have.

`GET_LOAD` reports how hard the device is working while it is working:
main-loop passes and the distribution of how long each one took. It is
readable while the sample path is blocked, because it is a different
endpoint pair on a different interface.

Cumulative since boot or since a clear, so the host differences two
readings and gets a rate over whatever interval it chose. The worst
pass is the exception - a maximum cannot be differenced - so clearing is
a separate act and never a side effect of reading, or the console and
the control channel would silently steal each other's worst case.

**It is measured with the cycle counter, not with `micros()`.** `micros()`
costs 869 ns on this board, measured by `Q`; the idle pass is about
10 us, so sampling it every pass would tax the loop by more than a
fifth. DWT's cycle counter is one load from a free-running register.
`load_tick()` costs 410 ns - 4% of a pass - and is profiled by `Q`
alongside everything else, so if it ever stops being negligible that is
visible in the same place that condemned `micros()`.

What a healthy board looks like, measured: 103 k passes/s idle and
94 k while capturing at the maximum in-spec rate, with 99.99% of passes
in a single log2 bucket. That tightness is the point - against a
distribution this narrow, one pass several buckets to the right is
unmistakable, and starting a stream (11.8 ms of printf) shows up
immediately.

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

**Both tracks must behave identically.** Not merely
feature-equivalent: the same command on either track produces the same
response bytes, the same refusals, and the same state. The tracks share
no source by invariant 3, so this is a contract enforced by tests
rather than by a shared header - the wire format is the only thing they
are allowed to have in common, and it belongs in this document.

The suite already runs `--track=both`; every command added here needs a
test that runs on both and compares, not two tests that each assert
against the same expectation separately.

**Track A follows.** That looked like it would force Track A to stop
using the Arduino core for enumeration, which would have cost it its
value as an independent oracle. It does not: the SAM core at 1.6.12
defines `PLUGGABLE_USB_ENABLED` and ships `PluggableUSB.{h,cpp}`, so a
second interface is added through the core's own extension mechanism
rather than by patching it *(check: PluggableUSB has not been exercised
on this board yet)*. Track A keeps the core for enumeration exactly as
invariant 3 intends.

## Open questions

Nothing outstanding that blocks starting. The numbering above is the
contract, and the DPRAM budget - the one figure this document opened
without - is now read off the datasheet: 4096 bytes, 2240 in use, 1088
more for this channel.

What remains unverified is not a number but two behaviours, and both are
marked *(check)* where they are stated: whether libusb can open a device
macOS's CDC-ACM driver has already claimed, which only matters if the
EP0 route is ever revisited, and whether PluggableUSB works on this
board, which Track A will answer the first time it is asked to.
