# Debugging Without a Probe

No JTAG/SWD probe is in use. Diagnostics are built from three independent
mechanisms, chosen because they fail for different reasons.

| Mechanism | Cost *(measured)* | Works when |
|---|---|---|
| Direct PIO write | **~36-69 ns** (track-dependent) | Always, including pre-init and in fault handlers |
| UART printf | **3600 us** per 40-char line at 115200 | After clock and UART init, outside real-time paths |
| Host-side counters | zero on target | Whenever frames are flowing |

### Measured on this board

Figures from `sketches/bringup` at 84 MHz, not estimates.

Both tracks run the same measurements, from `sketches/bringup` and
`apps/baremetal_bringup`.

| Operation | Track A (Arduino, gcc 4.8.3) | Track B (bare metal, gcc 15.2.1) |
|---|---|---|
| printf, 40-char line, on the wire | **3600 us** | **3600 us** |
| Direct PIO set + clear pair | 138.3 ns | **71.5 ns** |
| Same via an abstraction | 4328 ns (`digitalWrite`) | 536 ns (`led_on`/`led_off`) |
| Flash used | 15868 B | 7256 B text + 100 B data |

printf is identical because it is wire-bound: at 115200 baud a 40-char
line takes 3.6 ms regardless of who formats it. Everything else differs,
and the gap is the eleven-year compiler difference plus the absence of
the Arduino abstraction layer.

Three conclusions follow, and all three are load-bearing:

- **printf costs ~26000x a PIO toggle pair.** That ratio, not the
  absolute numbers, is why acquisition instrumentation uses GPIO.
- **`digitalWrite()` costs ~31x a direct register write.** Never use it
  for instrumentation; go straight to `PIO_SODR` / `PIO_CODR`.
- An earlier estimate here put a GPIO write at 12-24 ns (1-2 cycles).
  Measured, a set+clear pair costs 71.5 ns bare metal and 138.3 ns under
  the Arduino toolchain, so a single write is roughly 36-69 ns depending
  on track. The APB bridge and loop overhead dominate the store itself.
  Either figure is negligible against a 950 ns conversion interval, and
  utterly negligible against a buffer-completion ISR firing every few
  thousand conversions. **Quote the per-track number, not a single
  figure**: it is toolchain-dependent.

The three are layers, not alternatives. Build all of them before writing
any ADC code.

---

## 1. UART printf

Debug output goes out the **programming port**, which on the SAM3X8E side
is a plain **UART peripheral** — the 16U2 merely bridges it to USB. So
bare-metal printf needs roughly a 50-line UART driver and **no USB stack
at all**.

This is why the probeless approach works cleanly here: debug output and
the USB sample path are entirely independent problems, and the debug path
is the trivial one.

### Retargeting newlib

Implement `_write()`, plus stubs for `_sbrk`, `_close`, `_fstat`,
`_isatty`, `_lseek`, `_read` — the linker complains otherwise. Build with
`-specs=nano.specs`. Add `-u _printf_float` only if `%f` is genuinely
needed; it pulls in a large amount of code.

### The trap

**printf is slow and blocking.** At 115200 baud a 40-character line takes
about 3.5 ms. An ADC conversion takes 0.95 us. A single printf inside the
PDC interrupt handler destroys the timing being measured — and worse, it
presents as a hardware problem.

Rules:

- **Never printf from an ISR.** Write to a ring buffer; drain it in the
  main loop or a low-priority task.
- Raise the baud rate. The SAM3X UART goes far beyond 115200.
- Prefix machine-ignorable output with `#` (see `docs/protocol.md`).

---

## 2. LED and GPIO

Pin 13 = **PB27**. No SPI conflict on the Due, unlike the Uno.

A GPIO write costs one to two cycles. That is cheap enough to place
**inside the ADC ISR** without perturbing the timing under measurement —
something printf can never do. This is the key structural advantage, not
merely a fallback.

It also works when printf cannot: before UART init, during early boot,
with interrupts disabled, inside the HardFault handler, or when the UART
path is itself the broken thing. It is the "is the CPU alive at all"
channel and it has no dependencies.

### Patterns

**Heartbeat.** Slow blink from the main loop or idle task. If it stops,
the system hung or faulted. The single most useful signal available.

**Blink codes for fatal errors.** N blinks, long pause, repeat. Placed in
the HardFault handler *alongside* the register dump — if the UART is what
broke, the blink code is the only thing that survives. The two fail
independently, which is the entire point.

**ISR timing.** Toggle high on ISR entry, low on exit. ISR duration and
jitter then become externally measurable with real precision.

**Idle-hook blink (RTOS).** Blink from the FreeRTOS idle hook and LED
brightness becomes a crude CPU-load meter. A dim or dark LED means the
idle task is starving. A continuous system-health readout for free, and
hard to obtain any other way without a probe.

**Debug bus.** The Due has plenty of spare pins. Four GPIOs give sixteen
states readable on a logic analyser: the LED serves humans, the extra
pins serve instruments.

### Limits

Human-readable bandwidth is a few bits per second, and above ~20 Hz the
eye integrates it into "on" or "dim". It conveys *states*, never values.

---

## 3. HardFault handler

**Build this first — before any driver code.**

Without a probe, a hard fault is a silent lockup. A handler that dumps
the stacked exception frame recovers most of what a debugger would give
for crash diagnosis, in roughly 80 lines.

Dump:

```
stacked frame   r0, r1, r2, r3, r12, LR, PC, xPSR
fault status    CFSR, HFSR, MMFAR, BFAR
```

`PC` alone usually identifies the faulting instruction; `CFSR` says why.
Cross-reference against the `.map` file, which the link flags already
emit.

The handler must also **blink a fault code**, so it still reports when
the UART is unavailable.

Under FreeRTOS, add `configCHECK_FOR_STACK_OVERFLOW = 2` and a hook that
prints the offending task name. Stack overflow is the most common RTOS
failure and is otherwise invisible.

---

## 4. Host-side counters

Zero cost on target, because the numbers are already being collected for
other reasons:

- `overrun_count` (RXBUFF + GOVRE) in every frame header
- `seq` continuity checked by the host
- ISR duration measured externally via GPIO toggle

This gives dropped-sample detection with **no printf anywhere near the
real-time path**, which is the whole objective.

---

## Track A as an oracle

When bare-metal code misbehaves, flash the equivalent Arduino sketch and
compare. It answers "hardware or my code?" in one step, which is worth a
great deal without a debugger. See `docs/toolchain.md`.

---

## If a probe is added later

The JTAG header is populated and nothing in this design forecloses it. A
CMSIS-DAP probe would add breakpoints, memory inspection and thread-aware
RTOS views. The mechanisms above remain useful regardless — particularly
GPIO timing, which stays more accurate than any halt-based measurement.

## An overrun count is a stopwatch

Issue #41 is worth keeping as a method rather than as one bug. Capture
lost exactly 3 frames at the start of every run above 200 kHz, nine
times of nine, and the count turned out to be a *measurement of a
duration* rather than a symptom.

Each lost frame is one ring slot the main loop failed to service, so

    blocking = runway + lost / frames_per_second

with `runway = STREAM_NBUF * STREAM_BUF_SAMPLES / (channels * rate)`.
At 453,488 Hz over two channels that runway is 8.96 ms, and 4 lost
frames implies about 18 ms of blocked loop. The same arithmetic run
backwards predicts the rate at which losses start.

**The cause was `cmd_stream` printing its banner AFTER `stream_start`.**
Invariant 8 costs 13-20 ms of blocked main loop for a console line, and
the ring is already filling while it prints. Moving the two prints
before the start took the count to zero at every rate, nine runs of
nine - mechanism demonstrated by intervention, not inference.

**The model, measured on two independent code paths:**

    T = about 6 ms of formatting and uart_flush
      + the UART time of whatever that path prints

`cmd_stream` prints ~160 characters after starting and blocks
[17.9, 20.2] ms; `h_loop` prints ~102 and blocks [14.5, 15.2]. The
difference matches the extra characters at 115200 8N1 (5.0 ms) and the
two paths agree on the fixed part to within 0.6 ms. That is CLAUDE.md's
console cost arrived at from the capture ring instead of the load
monitor - two instruments sharing nothing landing on one number.

### The class, not the instance

Every site that starts a converter and then prints, with margin = runway
minus predicted blocking:

| site | rate | runway | banner | margin |
|---|---|---|---|---|
| `cmd_stream` | 453,488 | 8.96 ms | ~160 ch | **-10.93 ms** |
| `h_loop` / `ha_loop` | 453,488 | 8.96 ms | ~102 ch | **-5.89 ms** — **fixed, see below** |
| `cmd_dac_crosscheck` | 200,000 | 20.32 ms | ~110 ch | +4.77 ms |
| `cmd_stream_uart` | 2,000 | 2032 ms | ~74 ch | +2019 ms |

`cmd_dac_crosscheck` survives on margin alone - about one added banner
line from biting - and only because it starts capture at a fixed
200,000 Hz where the runway is largest.

**`h_loop` was priced here and then left unfixed for a day**, because
`67d3990` only moved `cmd_stream`'s banner - the audit had already
identified the class and the fix went to the instance. Measured before
touching it, four runs at each of two rates:

| | `first_overrun` before | after |
|---|---|---|
| ADC 453,488 Hz | **2, 2, 2, 2** | 0, 0, 0, 0 |
| ADC 402,061 Hz | **1, 1, 1, 1** | 0, 0, 0, 0 |

8 of 8 against 0 of 8, Fisher p = 7.8e-5. The counts also match what the
margin predicts - -5.89 ms is 2.6 frames of a 2.24 ms frame at 453,488,
and the larger runway at 402,061 gives 1.8 - so the model priced a site
it had not measured and was right at both rates.

`max_overrun` is unchanged by the reorder, which is the point: that is
issue #44's separate, later loss, and moving a banner does not touch it.
`first` and `max` really do locate a loss in time.

**Two sites are NOT hazards and should not be "fixed".** `h_play` prints
after a successful `play_start`, but playback is *host*-driven: nothing
flows until the host feeds, which happens after the command returns.
Capture is *device*-driven and fills the moment the timer runs. That
asymmetry is the whole mechanism. And `h_mimic` already prints before
starting, with a comment recording that ~7 ms of banner was once found
lying over the first samples of every capture on that preset - which is
why preset M reads zero at every rate, and is what localised #41.

### The class is closed, and here is the enumeration

The table above was written from the sites someone thought of. Grepping
every capture start on both tracks gives five each, and they account for
all of them:

| call site | status |
|---|---|
| `cmd_stream` | **fixed** - `67d3990` |
| `h_loop` / `ha_loop` | **fixed** - `0978e7f` |
| `h_mimic` / `ha_mimic` | already prints before starting |
| `cmd_dac_crosscheck` | +4.77 ms, survives on margin |
| `cmd_stream_uart` | +2019 ms |

plus `h_play` / `ha_play`, which starts playback rather than capture and
is not in this class at all.

`cmd_dac_crosscheck` is the one left running on margin, and the audit's
own words are "about one added banner line from biting". That margin is
now known to be trustworthy - the -5.89 ms prediction for `h_loop` was
right at two rates before anyone measured it - so +4.77 ms is a real
cushion rather than a hopeful one. It is also a debug-only command. Add
a line to its banner and it becomes a defect.

### first, max, and where a loss actually sits

`first_overrun` and `max_overrun` cannot locate a loss in time, and two
issues turn on the difference. #41 loses its frames *before the first
frame ships*, so first equals max. #44 loses them later, so first is 0
and max is not.

`ParsedStream.overrun_steps` records `(frame index, device timestamp,
new count)` at each change - a handful of tuples per run, because the
counter moves rarely. Read it rather than the aggregates whenever the
question is *when*.

Two cautions paid for on #44 within one hour of writing that trace.
`first == max` does **not** separate a single stall from spread
contention: at 200 kHz the first frame reaches the host at 5.08 ms while
the playback priming window closes at 61.4 ms, so `first` is sampled
long before the window of interest opens. And a distribution cannot be
read off one draw - one traced cycle put every loss after 2 seconds, and
twenty-four more found onsets from 15 ms to 752 ms with the heavy cycles
losing steadily throughout the run.
