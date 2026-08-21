# USB Transport

Measured on this host, MCK 78 MHz. All rates are **host-timed**; the
device reports byte counts only, for reasons in the last section.

## Ceilings

| Direction | Track A (Arduino CDC) | Track B (bare metal) |
|---|---|---|
| IN, device to host | **7.81 MB/s** | 3.86 MB/s |
| OUT, host to device | **0.126 MB/s** | **3.02 MB/s** |
| Duplex, equal budgets | not measured | 1.93 in + 1.65 out = **3.58 MB/s** |

For scale, the ADC's full output at this clock is 906,738 sps x 2 bytes =
**1.813 MB/s**.

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

## Duplex is limited by the service loop, not the link

Duplex total (3.58 MB/s) lands close to IN alone (3.86), rather than
adding to it. Separate endpoints in opposite directions can overlap on
the bus, so a link-limited system would have shown roughly twice the
one-way figure. What is shared is the processor: both directions copy
through the same FIFO loop from the same main loop.

That also means the headroom is a firmware question. Track A demonstrates
7.81 MB/s of write throughput from the same silicon by keeping the banks
fed; combining that technique with block reads should lift duplex well
above the 3.63 MB/s a symmetric full-rate instrument needs.

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
