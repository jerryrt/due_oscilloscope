# USB Transport

Measured on this host, MCK 78 MHz. All rates are **host-timed**; the
device reports byte counts only, for reasons in a later section.

## Ceilings

Current figures via **endpoint DMA** (`usbbench.py in-dma/out-dma/
duplex-dma`), with the CPU-FIFO figures kept for comparison. Host side
runs one real-time thread per direction (see `host/rt.py`):

| Direction | Endpoint DMA | CPU FIFO copies |
|---|---|---|
| IN, device to host | **32.0 MB/s** | 5.20 MB/s |
| OUT, host to device | **26.6 MB/s, byte-perfect** | 5.03 MB/s, byte-perfect |
| Duplex, equal contention | 8.55 + 8.40 = **16.95 MB/s** | 2.77 + 2.47 = 5.25 MB/s |

Getting DMA to work took three findings, recorded in the `usb_cdc.c`
history: AUTOSW is required (manual FIFOCON and automatic bank
switching cannot share an endpoint), a `DEVEPTCFG` write while EPEN is
clear is silently ignored on this part, and the mode must be reapplied
whenever endpoint configuration is rebuilt (every bus reset and
SET_CONFIGURATION), or an enumeration quietly reverts it.

For scale, the ADC's full in-spec output at this clock is about
**1.81 MB/s**, and the full-rate loop moves 3.7 MB/s combined - which
is why it only became viable once the playback ring was DMA-fed.

Earlier figures from the single-threaded benchmark - 3.86 IN, 3.02 OUT,
3.58 duplex - were partly measuring the host's own polling loop: one
thread interleaved both directions behind a select() timeout, so each
direction stalled while the other's syscall ran. The device-side
counter for the IN flood is disregarded entirely: it reads far above
the wire rate, which means `usb_cdc_write` clobbers banks when
producing faster than the host drains (recorded as an open issue in
`docs/status.md`; the streaming path never outruns the wire and its
frames verify byte-perfect).

## macOS drops OUT bytes when the tty queue is pressured

The costliest host-side discovery in the project: **writing into a
macOS CDC-ACM output queue that is under pressure silently loses
~128-byte chunks that `write()` has already counted.** Nothing errors.
Free-running blocking writes produced ~75 clean phase jumps per second
on the DAC while every counter on both sides stayed green; the loss was
proven by byte conservation (host-written minus device-received matched
jumps x 128 B) and by the jumps landing exactly on DAC ring-buffer
boundaries. Clock-paced writes at the exact consumption rate still
dropped at every tested queue depth.

Two policies have measured clean, and which applies depends on the
device side:

- **Manual-FIFO device** (small ring, drains the queue only at DAC
  consumption rate): the only safe write lands in a *truly empty*
  queue - a real-time thread polling `TIOCOUTQ` and bursting only at
  zero. That gate caps near 1.7 MB/s once IN traffic competes.
- **DMA-fed device** (current: 32 KB ring ingested by endpoint DMA at
  wire speed): the tty queue stays shallow as long as the host's lead
  is smaller than the ring, so the pressure condition cannot form and
  **clock-paced blocking writes at the DAC byte rate with a ~20 KB
  lead are safe** - and reach full rate in duplex. Writes must be
  whole 512-byte packets so no short packet fragments the device's
  stream DMA span.

`host/loopback.py` implements the second. Any future host software
that feeds the DAC must keep whichever policy matches the device it
talks to, and must never free-run writes into saturation.

**It has not gone away, it is now measurable, and it is far worse than
"rare".** `play_bytes_in` follows the OUT DMA's `BUFF_COUNT`
continuously, so the device's byte count is exact and the question is
answerable directly: stop feeding, let the pipeline drain, and compare.
The quantum is the fingerprint - every such loss is a whole multiple of
128 bytes, where the device-side defect this was confused with for a
fortnight lost arbitrary amounts (12 to 370 bytes, no common factor).
`test_host_fed_ramp_loses_no_samples` and
`test_device_receives_every_byte_the_host_sent` separate them on
exactly that basis.

What that measurement shows, two runs per rate on a quiet machine,
agreeing run to run within 1%:

| DAC rate | lost per 3 s | share of what was written |
|---|---|---|
| 200,000 sps | 0 B | **exact** |
| 397,959 | ~11 kB | 0.45% |
| 600,000 | ~24 kB | 0.67% |
| 886,363 | ~79 kB | 1.48% |
| 1,000,000 | ~136 kB | 2.25% |
| 1,218,750 | ~50 kB | 0.67% |
| 1,392,857 | ~72 kB | 0.85% |

So the earlier figure - one 3 s run in eight under load, none in 22 on
a quiet machine - was measured at 200 ksps, the one rate that loses
nothing. Above it the drop is **continuous, reproducible, and present
on an idle machine**. It is not an event that occasionally happens to a
run; it is the normal behaviour of this path.

**The drain is not optional to the measurement.** Counters read
straight after the feeder stops show a deficit that is mostly pipeline:
55 to 450 kB sits in the CDC driver beneath the tty layer. That the
remainder is genuinely lost was established by reading the device once
a second for six seconds after the feed stopped - `play_bytes_in` and
`play_consumed` both freeze while `play_underruns` climbs, so the
device is sitting starved with an empty ring and the bytes never
arrive. It also cannot be the wire: bulk OUT is CRC-checked with
retries and NAK backpressure, so whatever reaches the host controller
is delivered. The loss is above the controller.

**This is the cause of the playback starvation**, not a separate
defect. The ring drains at exactly the rate bytes go missing: 600,000
sps loses 0.67% and its ring decays at 0.73% per second; 1,218,750 sps
loses 0.67% and decays at 0.79%. Every underrun attributed to host
scheduling, feed policy, lead size or device arming was this.

**It also means over-feeding is not a fix**, though it looks like one.
Feeding 1-2% surplus stops the ring draining and takes the underrun
count to zero at every failing rate - while the dropped samples are
still missing from the waveform. The counter goes green and the data
stays wrong, which is the precise failure mode invariant 5 exists to
prevent. The device cannot flag it: it counts and reports what *it*
drops, and these bytes never reached it.

**The fix: write a constant size.** Writing a constant 512 bytes per
`write()` is lossless where writing "whatever is due" is not - same
sizes on the wire, same pacing, same rate, different result. Measured
with the pipeline drained, interleaved so a drifting machine cannot
favour one arm:

| DAC rate | due-sized writes | constant 512 B |
|---|---|---|
| 200,000 sps | 0.000% | 0.000% |
| 397,959 | 0.45% | **0.000%** |
| 600,000 | 0.67% | **0.000%** |
| 1,218,750 | 0.67% | **0.000%** (residual, below) |
| 1,392,857 | 0.85% | **0.000%** |

With it the AWG ladder runs clean at every rate over repeated passes,
and the three rates that used to starve - 600,000, 1,218,750 and
1,392,857 - report `under=0` with the ring sitting at 21 to 30 slots
instead of 5. `Feeder.WRITE_SIZE` is where this lives.

**Size alone is not the mechanism**, and this is the part that is still
not understood. Capping the due-sized path at 1024 bytes leaves
0.47-0.84% - with or without a finer idle sleep - even though every
write it then issues is 512 or 1024, the same sizes the constant-size
path uses. Something about *how* the writes are issued matters and it
is not their size. What is established is which policy is clean.

**A residual survives at the top of the ladder.** 1,218,750 sps is
exact in most runs, and occasionally loses a little (384 B) or a lot
(336,768 B). That is the intermittency the earlier "one run in eight"
figure described, now confined to the fastest rates instead of spread
across all of them. Held by `RESIDUAL` in the test, by outcome rather
than by mark, so it turns green by itself.

**What the loss is not.** Two mechanisms were tested and neither
explains the floor:

- *Not write size alone.* At 1,000,000 sps the deficit is 2.04-2.25%
  at every forced size from 512 B to 16384 B - but that rate is one of
  the oversupplied ones below, which no write policy fixes, so it was
  the wrong rate to test the idea at. At 200,000 sps, which loses
  nothing by default, forcing the size shows the threshold plainly:
  0.000% at 512 B and 1024 B, 0.28-0.39% at 2048 B, 0.56-0.76% at
  4096 B and above.
- *Not queue pressure, for the floor.* Feeding deliberately **under**
  the device's rate, so the ring drains hard and the tty queue is
  certainly empty, does not reduce it. At 600,000 sps the deficit is
  0.62-0.78% at every feed scale from 0.96 through 1.00 - flat. Only
  the part **above** the device's rate is pressure-related, and that
  part is large: scale 1.01 loses 1.02-1.10% and scale 1.02 loses
  1.82-1.90%.

So the loss has two components: a rate-dependent floor that happens
with an empty queue and cannot be fed around, and a surplus-shedding
term on top of it that punishes over-feeding. The floor is the open
question.

**The whole OUT path loses bytes, not just the playback feed, and
"OUT byte-perfect" was never true.** `out-dma` at ~28.5 MB/s, with the
pipeline given 0.3 s, 1.0 s, 3.0 s and 6.0 s to drain and no flush on
any run:

| drain | host wrote | device received | short | |
|---|---|---|---|---|
| 0.3 s | 113,836,032 | 111,392,768 | 2,443,264 | 2.15% |
| 1.0 s | 113,393,664 | 110,940,160 | 2,453,504 | 2.16% |
| 3.0 s | 112,852,992 | 110,309,376 | 2,543,616 | 2.25% |
| 6.0 s | 113,311,744 | 110,796,800 | 2,514,944 | 2.22% |

Flat against drain length, so none of it is in flight, and every
deficit is a whole multiple of 128. This is the same defect the
playback feed suffers, reproduced with **no DAC, no ring, no pacing
and no real-time thread** - just a writer thread pushing 16 KB blocks
at a device that sinks them by DMA. That makes the bench the simplest
reproduction available and the right place to attack this.

It also means the throughput figures this project quotes for OUT
describe bytes *offered*, not bytes *delivered*, and the "byte-perfect"
qualifier attached to them is withdrawn.

**Still unseparated: host-side drop, or device-side under-count.** The
128-byte granularity points at the host - a device-side DMA counter
would be granular in packets (512 B) or in span size - and bulk OUT
cannot lose data on the wire, since it is CRC-checked with retries and
NAK backpressure. But the device's own counting has not been audited
against an independent measure, and it should be before the host is
blamed.

**And the clean rates are not clean.** 886,363 and 1,000,000 sps lose
the most (1.48% and 2.25%) and report `under=0`, because the device's
own timing shows its converter running slow there by almost the same
fraction (-1.58% and -2.35%). Supply and demand cancel. Judge this path
by byte conservation, never by the underrun counter.

## close() hangs unless the device always drains OUT

macOS's `close()` on a tty waits for in-flight write URBs to complete.
`tcflush` cannot recall a URB already handed to the controller, so if
the device stops reading bulk OUT - as it used to after a stop command
- the host process hangs in `close()` forever, holding the port and
leaving the board streaming for the next run to trip over. Two rules
came out of this, both implemented:

- The firmware's main loop **drains and discards bulk OUT whenever no
  consumer owns it** (correct CDC behaviour anyway).
- Host tools still `tcflush` before closing the native port, as a
  belt-and-braces against queued-but-not-submitted bytes.

**It happened again on 2026-08-22 and is not fully explained.** The
test suite hung 50 minutes in `close()` after the duplex DMA
benchmark, board heartbeat still flashing and both USB activity LEDs
dark. It did not reproduce in eight further benches. The candidate is
`usb_cdc_dma_mode()`, which stops both DMA channels and flips AUTOSW
but never issues `EPRST` - a DMA stopped mid-bank leaves a bank
nothing frees, and the endpoint NAKs for good. Track A does reset the
endpoint (`ep_reset_fifo()`); Track B has no `EPRST` anywhere. See
objective 0c in `docs/HANDOFF.md` before changing it: `EPRST` also
clears the data toggle.

Diagnosing it from the outside: a host tool making no progress while
the board's heartbeat still flashes and both activity LEDs stay dark
is this and not a dead board. `sample <pid> 2 -mayDie | grep close`
confirms it in one line. `tcflush` will not help and neither will
waiting; kill the process.

## Track A's bulk path now bypasses the core

The asymmetry described below was the state of things while Track A used
`SerialUSB` for bulk data. It no longer does: the two bulk endpoints are
taken away from the core and driven by UOTGHS DMA
(`sketches/bringup/usbdma.cpp`), with enumeration and control transfers
left where they were. Measured host-side on the same board:

| Direction | Via the core | Via endpoint DMA |
|---|---|---|
| OUT | 0.126 MB/s | **19.72 MB/s**, byte-perfect |
| IN | 7.81 MB/s | **31.10 MB/s** |
| Duplex | - | **15.58 MB/s** (7.90 in + 7.68 out) |

The section below stays because it explains *why* that was necessary,
and because the per-byte `accept()` cost is a live trap for anyone who
reaches for `Serial_::read()` on a data path.

## The 62x asymmetry was a firmware path, not USB

Track A reads at 0.126 MB/s because `Serial_::read()` calls `accept()`
**once per byte**, and each call refills the entire 512-byte receive
ring:

```c
buffer->tail = (tail + 1) % CDC_SERIAL_BUFFER_SIZE;
if (USBD_Available(CDC_RX))
        accept();          /* whole-ring refill, per byte */
```

That works out at roughly 620 cycles per byte at 78 MHz, which matches
the measured rate. Reading whole 512-byte banks instead, as
`usb_cdc_read()` does, gives 3.02 MB/s on identical hardware: **24 times
faster**, same endpoints, same host driver.

Conversely Track A *writes* faster than Track B (7.81 against 3.86)
because the core blocks on `TXINI` and keeps the endpoint banks full,
while the bare-metal writer returns as soon as a bank is busy and waits
for the next pass of the main loop. Non-blocking cost throughput.

**Neither direction is limited by USB.** The hub chain makes no
difference: moving the native port from behind two chained hubs to a
root port changed IN from 7.855 to 7.811 MB/s and left OUT unchanged.

## Duplex is limited by the service loops, not the link

This held on both ends, and both fixes were measured. Device-side, both
directions copy through the same FIFO loop from the same main loop, so
duplex lands near the better single direction rather than their sum.
Host-side, the original single-threaded benchmark had the same shape,
and splitting it into one real-time thread per direction lifted the
measured duplex from 3.58 to 5.25 MB/s combined - the earlier "ceiling"
was partly the measuring loop itself. The remaining device-side
headroom is the endpoint-DMA work: 5.25 MB/s already clears the
~3.9 MB/s a symmetric full-rate instrument needs, while the
DAC-at-ceiling case (~5.0 MB/s biased toward OUT) is the tight one.

### Measuring duplex fairly

The first duplex measurement gave 2.85 in against 0.85 out and looked
like a hardware asymmetry. It was not: the service loop gave IN a budget
of 8 frames and OUT a budget of 16 banks, a 4:1 ratio in bytes, and the
result reproduced that ratio almost exactly. With equal byte budgets and
alternating order the same test gives 1.93 and 1.65.

**An asymmetry produced by the scheduler is not a property of the
transport.** Budgets on the host matter too, for the same reason.

## The board resets when the programming port is opened

This is normal, and it invalidated several device-side measurements
before it was understood.

Opening the programming port produces a General Reset: `RSTTYP = 0`, and
the backup domain is cleared, so the boot counter in GPBR starts over.
It happens on open, never on write, with or without DTR asserted, and
identically whether the port is behind hubs or on a root port.

Datasheet section 14.4.4.1 lists four causes of a General Reset:
power-on, **asynchronous master reset via the NRSTB pin**, brownout, and
voltage regulation loss. Section 6.4 notes that the ordinary `NRST` pin
resets everything "except the Backup region", which is why a cleared
backup domain does **not** imply a supply problem: `NRSTB` goes through
the Supply Controller and does clear it.

So the signature does not distinguish a brownout from the Due's designed
auto-reset circuit, and the determinism settles it. A marginal supply is
load-dependent and erratic; this is clockwork, identical uptime every
time, unchanged by topology.

**Consequence for measurement**: the device cannot time its own
benchmark, because its window begins at a boot the host knows nothing
about. It reports byte counts; the host keeps the clock.

## Instrumentation rules earned here

- **Never infer firmware state the firmware can report.** A boot counter
  in a backup register and the reset cause from RSTC would have explained
  in one run what took many rounds of guesswork about clocks and timers.
- **Validate the instrument before trusting it.** The boot counter was
  only believable once a software reset was shown to increment it while
  preserving the backup domain.
- **Discover ports, never hardcode them.** Node names come from USB
  location and move with the cable. A stale path once aimed the
  1200-baud erase-and-reset touch at the wrong port, wiping the flash
  without writing anything. `host/ports.py` identifies the control port
  by the only reliable means available: it answers.
