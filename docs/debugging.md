# Debugging Without a Probe

No JTAG/SWD probe is in use. Diagnostics are built from three independent
mechanisms, chosen because they fail for different reasons.

| Mechanism | Cost | Works when |
|---|---|---|
| LED / GPIO | ~1–2 cycles (12–24 ns) | Always, including pre-init and in fault handlers |
| UART printf | ~3.5 ms per 40-char line at 115200 | After clock and UART init, outside real-time paths |
| Host-side counters | zero on target | Whenever frames are flowing |

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
