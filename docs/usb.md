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
