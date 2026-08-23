# Next Hardware: options for a more powerful instrument

**Status: an options paper. Nothing is chosen and nothing is built.**
It exists so the question "what if we want a faster one?" is answered
from what this project has measured rather than from a catalogue.

Read `docs/architecture.md` for the invariants a successor must keep,
`docs/frontend.md` for the host software that would move with it, and
`docs/usb.md` for the transport ceilings measured here.

## What carries over, and what does not

The software is the part that took the time, and most of it survives a
board change.

**The host survives almost entirely.** The wire format is already
device-agnostic: magic, version, sequence, per-channel rate, channel
mask, device timestamp and a header CRC, with `bits_per_sample` and
`packing` fields that a 14- or 16-bit converter needs no change to use.
The daemon reaches hardware through one `Device` interface with two
implementations today (`BoardDevice`, `FakeDevice`); a new instrument is
a third. Everything above that seam - the socket protocol, ownership,
backpressure, recording, the client, the GUI plan - does not know what
it is talking to.

**The tests split the same way.** The 95 board-free tests survive
verbatim, because framing, ownership, refusals and recording are not
properties of any particular converter. The hardware tests get a new
file per device.

**The firmware does not survive.** PDC, DACC, TC and UOTGHS are SAM3X.
What survives is the *structure* - ping-pong DMA, a ring the CPU never
reads, underruns counted rather than concealed, frames that are never
spliced - and the recorded facts in `CLAUDE.md`, which are worth more
than the code they describe.

## The fork that decides everything

**Continuous streaming, or burst capture into deep memory?** They are
different machines and mixing them is where scope projects go wrong.

This instrument streams continuously and is bounded by the host link.
A bench DSO does the opposite: it captures a burst into memory far
faster than any link could carry, then reads it out slowly, and its
"sample rate" is a memory bandwidth rather than a transport one.

Only this choice changes the software architecture. Channel count,
analog bandwidth and resolution change the board.

If streaming is kept, the arithmetic is short. USB High Speed measured
**32 MB/s IN** on this part, which at two bytes a sample is about
**16 Msps aggregate** - sixteen times today's rate with no change to
the model at all. USB 3 through a bridge is a few hundred MB/s *(check
the figure for the part and the transfer size actually used; do not
size a design against a headline)*, so roughly 100 Msps aggregate.
Past that, deep memory and burst mode are not optional.

## The options, in order of how much survives

### 1. This board, with an analog front end

The weakest part of this instrument is not its digital path: it is that
there is no front end at all. Nothing is 5 V tolerant, there are no
clamps, no attenuator, no bias and no anti-alias filtering, so the only
safe input is the DAC on the far end of a jumper.

Protection, a switchable attenuator, mid-rail bias, a buffer amplifier
and a filter per channel change **no software whatsoever** and turn a
loopback demonstration into something usable on real signals. If
"powerful" means "connectable", this is the answer, and it is Phase 3
in `docs/scope.md` already.

### 2. A faster Cortex-M in the same idiom

SAM E70/V71 keeps the vendor's peripheral idioms and USB HS lineage, so
the DMA-fed endpoint work transfers conceptually. STM32H7 is the
stronger mainstream choice - much faster core, far more SRAM, several
ADCs at higher rate and resolution *(check the exact part; the family
spans a wide range)*.

Both are Cortex-M7, which invalidates a fact this project currently
records as a certainty: **M7 has a data cache, so DMA buffers need
cache maintenance.** `CLAUDE.md` says the opposite, correctly, about
the M3. That line becomes a trap the day the successor arrives.

Streaming stays inside USB High Speed here, so the ceiling is the
~32 MB/s already measured.

### 3. USB 3, which implies an FPGA

Almost no microcontroller has a USB 3 device controller. In practice
USB 3 means a bridge chip, and a bridge wants a 16- or 32-bit parallel
bus clocked around 100 MHz. Nothing on a Cortex-M can feed that
continuously, so the FPGA is not a luxury in this design - it is the
only part fast enough to be on that bus.

The shape is:

```
ADC -> FPGA (capture, trigger, packing, optionally DDR) -> USB 3 bridge -> HOST
```

Two bridges are worth considering:

| Bridge | What you write | Notes |
|---|---|---|
| FTDI FT600/FT601 | a FIFO master in HDL | the USB stack is inside the chip; simplest path by a distance |
| Infineon EZ-USB FX3 | a GPIF II state machine, plus firmware | more flexible, more work; what most commercial analysers and cameras use |

Both land in the same throughput class, a few hundred MB/s *(check)*.

### 4. FPGA with deep memory - the real instrument

The same front end as (3) with DDR behind the capture path: hardware
triggering, pre-trigger depth, and a sample rate decoupled from the
link. Firmware becomes HDL plus a small control processor, and the host
software still survives complete. Largest jump in capability, and in
effort.

### 5. Merge host and device

An SBC with a converter attached, or a Pi driving a satellite MCU. The
daemon runs on the SBC and its socket becomes local or stays remote,
unchanged either way.

Convenient, and it puts Linux scheduling on the sampling path. After
what was measured here - a feeder starved by four busy threads in its
own process, and the same load invisible once the GIL was gone - that
arrangement deserves the same instrumentation before it is trusted.

## What USB 3 costs in software

Less than it looks, but not nothing.

**The tty layer disappears**, and with it macOS's silent 128-byte chunk
drop (`docs/usb.md`, objective 0b). libusb with several transfers
queued replaces it, which is the change already wanted for jitter
reasons: the kernel keeps shipping while the process is descheduled.

**Frames must grow.** Fan-out costs a measured mean of 45 us per frame
and never exceeded 127 us, which is invisible at 442 frames a second
and impossible at 50,000 - what 4 KB frames would mean at 200 MB/s.
Frames need to be tens or hundreds of kilobytes, the header keeps its
shape, and the daemon must hand out `memoryview` slices rather than
copies. The wire format already permits it: any multiple of 512 with a
whole number of samples is valid.

**Recording becomes a storage decision.** ~1.81 MB/s is about 6.5 GB
per hour; 200 MB/s is roughly 700 GB per hour. Continuous logging stops
being a checkbox.

**The display was never going to see every sample.** The min/max
decimation in `docs/frontend.md` is what makes any of these rates
drawable, and it does not change.

## What must be reimplemented, not inherited

The discipline is the reason this project can tell a device fault from
a host fault, and in an FPGA design it has to be built again in HDL:

- overruns **counted and flagged in the frame header**, never a silent
  splice
- monotonic sequence numbers, so continuity is provable from the bytes
- a header CRC, so a resync is detectable rather than plausible
- device timestamps, so freshness can be proved and a host window
  compared against device time
- byte-exact accounting on any host-fed path, which is what allowed
  "the host dropped 128 bytes" to be separated from "the device lost
  data"

Every one of those was added after a defect that had already been
misattributed once. An implementation that omits them will lie in
exactly the documented ways.

Two invariants also need editing rather than copying: **"the CPU never
touches sample data"** becomes a statement about the FPGA's datapath,
and **"Cortex-M3 has no data cache"** stops being true the moment an M7
or an SoC is in the chain.

## The four questions that pick the option

1. How many channels?
2. What analog bandwidth - which sets the sample rate, not the other
   way round?
3. What resolution, and is it real resolution or marketing bits?
4. Continuous streaming, or burst capture into deep memory?

Only the fourth changes the software architecture. The first three
change the board.

## A migration that keeps the work

1. Implement the new device behind the existing `Device` interface, in
   the daemon, with the same frame format and a bumped `version`.
2. Keep the board-free test suite as the contract it already is.
3. Add one hardware test file for the new instrument, starting with the
   same three cases the current one has: whole frames out of real
   bytes, no sequence gaps, and a port the next run can open.
4. Run both instruments through the same GUI. If the front end can tell
   them apart, something has leaked through the seam that should not
   have.
