# Bare Metal and RTOS

Both variants are built from the **same drivers**. `drivers/` is
RTOS-agnostic; only `main()` differs. That is what makes the comparison
meaningful rather than two unrelated projects.

```
apps/baremetal_bringup/main.c     superloop + ISRs (exists, working)
apps/rtos_bringup/main.c          FreeRTOS tasks + the same ISRs (exists, working)
```

## Order of work

**Bare metal first, always.** Get the acquisition loop provably correct,
then layer FreeRTOS on top. Debugging DMA setup and a scheduler
simultaneously is how a weekend disappears, especially with the SysTick
ownership question below.

## FreeRTOS integration

FreeRTOS is well suited to a CMake project because it is just source
files, with no build system of its own to fight:

```
FreeRTOS/Source/*.c
FreeRTOS/Source/portable/GCC/ARM_CM3/port.c    <- Cortex-M3, correct for SAM3X
FreeRTOS/Source/portable/MemMang/heap_4.c
```

Add as a CMake target pointing at the project's `FreeRTOSConfig.h`.

Cortex-M3 implements `BASEPRI`, so the **full** FreeRTOS port applies;
the restricted CM0 variant is not needed.

## The two settings that decide whether it works

### 1. Vector table aliasing

The startup file must route:

```
SVC_Handler      -> vPortSVCHandler
PendSV_Handler   -> xPortPendSVHandler
SysTick_Handler  -> xPortSysTickHandler
```

Miss these and `vTaskStartScheduler()` hard-faults immediately.

This is the bare-metal form of the SysTick conflict that afflicts
FreeRTOS under the Arduino core, where `millis()` already owns SysTick.
Here it is cleaner: nothing else claims the timer, so ownership is simply
a matter of pointing the vector at the right handler. In the bare-metal
build, SysTick belongs to the BSP; in the RTOS build, it belongs to the
kernel.

### 2. Interrupt priorities

SAM3X8E implements **4 priority bits** (16 levels), so:

```c
#define configPRIO_BITS   4
```

Then set `configMAX_SYSCALL_INTERRUPT_PRIORITY` accounting for ARM's
shifted priority encoding — priorities occupy the *high* bits of the
8-bit register. Getting this wrong is the single most common source of
mysterious `configASSERT` failures on Cortex-M, and the symptom rarely
points at the cause.

## Acquisition must stay out of the scheduler path

```
ADC ENDRX ISR    priority ABOVE configMAX_SYSCALL_INTERRUPT_PRIORITY
                 (numerically lower value)
```

Placing it above the syscall ceiling means the kernel can never mask or
delay it. The cost is absolute: **that handler may not call any FreeRTOS
API** — no `xQueueSendFromISR`, no notifications, nothing. It touches
only a lock-free ring buffer. A lower-priority task collects the data and
may use kernel primitives freely.

This is not a compromise made for FreeRTOS. It is the correct
architecture in the bare-metal build too, where the same ISR writes the
same ring. The RTOS build merely makes the constraint explicit and
enforceable.

An RTOS tick landing mid-acquisition is a real source of sample jitter,
and jitter smears FFT bins. Keeping the acquisition ISR above the kernel
removes the possibility entirely.

## Configuration worth setting

| Setting | Value | Why |
|---|---|---|
| `configCHECK_FOR_STACK_OVERFLOW` | 2 | Most common RTOS failure; otherwise invisible without a probe |
| `configUSE_IDLE_HOOK` | 1 | Idle-hook LED blink doubles as a CPU-load meter |
| `configASSERT` | defined | Routes to the fault reporter; silent asserts are worthless here |
| `configTOTAL_HEAP_SIZE` | sized against 96 KB | SRAM is shared with DMA buffers — budget both together |

`heap_4.c` is the sensible default: coalescing, and adequate when
allocation happens at startup only.

**Memory budgeting is tighter than usual.** The FreeRTOS heap, task
stacks and the DMA capture ring all come out of the same 96 KB. Size the
capture ring first — it has a hard throughput deadline — and give
FreeRTOS what remains.

## Stage C1, built and measured (2026-08-30)

Track C exists. `apps/rtos_bringup`, `cmake/freertos.cmake`, built by
`cmake --build build-c --target firmware_rtos` after configuring with
`-DBUILD_TRACK_C=ON`. FreeRTOS V11.1.0, pinned by 40-character commit
rather than by tag, fetched at configure time (issue #45 decision 3).

    # id: track=C fw=0.2.0 ctlver=4 framever=3 mck=78000000 ...

    text 11,596   data 8   bss 4,468     Track B: 38,372 / 32 / 72,904

It answers a **typed** `v`, `h` and `T`, which is the claim worth
making: the identity printed from `main()` would prove only that
`main()` ran, while a reply to a keystroke proves `console_task` is
being scheduled.

**No allocator in the image**, by the same `nm --defined-only` check
`tests/test_no_heap.py` applies to Track B. Static allocation, no
MemMang file compiled at all.

**Vector aliasing needed no change to `startup_sam3x8e.c`.** This note
predicted "a one-line change here"; in the event the handlers were
already declared as *weak* aliases of `Default_Handler`, so defining
`vPortSVCHandler`/`xPortPendSVHandler`/`xPortSysTickHandler` to the
CMSIS names in `FreeRTOSConfig.h` is enough - `port.c` then emits strong
definitions that win. Verified in the link map, where `SysTick_Handler`
resolves to `port.c.obj`, rather than from the symbol name alone.

### The time source, and why it may not call FreeRTOS

`bsp/systick.c` cannot be linked: it defines `SysTick_Handler` strongly
and two strong definitions are a duplicate symbol, not an override.
`millis()` and `micros()` live in that file and almost everything calls
them - `drivers/adc.c` alone has ten sites. So the application provides
them (`apps/rtos_bringup/time_rtos.c`), which is invariant 4's shape.

**The obvious implementation is `xTaskGetTickCount()` and it is wrong.**
`drivers/acq.c` calls `micros()` from inside `ADC_Handler()`, behind
`#if ACQ_RATE_TRACE_ENABLED` which defaults to 0. That ISR sits *above*
`configMAX_SYSCALL_INTERRUPT_PRIORITY` and may call no FreeRTOS API at
all. A kernel-calling `micros()` would put an API call in that ISR the
day someone set the flag, and the failure would be corrupted kernel
state rather than a compile error.

The counter is therefore a plain volatile advanced from
`vApplicationTickHook()`, readable from any context at any priority.
The interpolation is byte-for-byte `bsp/systick.c`'s, valid because
FreeRTOS programmes `SysTick->LOAD` as
`configCPU_CLOCK_HZ / configTICK_RATE_HZ - 1` - 77,999 at 78 MHz and
1000 Hz, the identical value `systick_init()` writes.

Measured on the board, because a time source that returns 0 or ticks at
the wrong rate neither fails to link nor fails to run:

    # time millis=9776 micros=9776008 d_ms=100 d_us=99998 (asked 100 ms)

`d_us` of 99,998 rather than a round 100,000 is the evidence that
matters - the microsecond interpolation is live, not `millis()` times a
thousand.

**One genuine behavioural difference between the tracks.** Time does not
advance until the scheduler starts. Bare metal calls `systick_init()`
early in `main()`; here `xTaskIncrementTick()` only runs after
`vTaskStartScheduler()`, so anything timed during initialisation reads 0
and a duration measured across the scheduler start is wrong rather than
merely coarse.

### What C2 has left, at the symbol level

Invariant 4 says bare-metal and RTOS builds "link identical driver code
and differ only in `main()`". That is now checked rather than asserted.
Comparing what the kernel defines against what `bsp/`, `drivers/` and
`lib/due_shared` define:

    symbols defined by the FreeRTOS objects        148
    symbols defined by bsp/ + drivers/             277
    defined by BOTH                                  1   SysTick_Handler

**One collision, and it is the one already handled.** Nothing else in
the BSP or the drivers competes with the kernel for a name.

And taking everything `bsp/`, `drivers/` and `lib/` *reference*, minus
everything they, the kernel and Track C's application define, sixteen
symbols remain and every one is the toolchain's or the linker script's:

    __aeabi_ldivmod  __aeabi_uldivmod  __libc_init_array  errno
    memcpy  memset  strlen
    _sdata _edata _sbss _ebss _etext _estack _heap_start _heap_end

**None is a Track C problem.** So with `millis()`/`micros()` provided
there is no remaining symbol-level obstacle to linking the whole driver
set under the kernel, and C2 is a question of task decomposition and
priorities rather than of missing pieces.

Stated as what it is: a symbol-level analysis, not a link test. The
link test is `apps/rtos_bringup/main.c`, whose tasks call the stream,
playback and generator drivers and run the same suite the other tracks
do.

## What the comparison should measure

The point of building both is data, not preference:

- **ISR latency and jitter** — GPIO toggle at ENDRX entry, measured
  externally. Expect the RTOS build to be no worse, since the ISR sits
  above the kernel ceiling.
- **Achievable sustained throughput** — should be identical if the
  architecture holds. A difference means something is touching the data
  path that should not be.
- **CPU headroom** — idle-hook duty cycle.
- **Code size and RAM cost** of the kernel against the superloop.

If the RTOS build shows worse jitter, the cause is almost certainly a
priority misconfiguration rather than the kernel itself.

## Other RTOS options

Considered and set aside, recorded so the reasoning is not relitigated:

- **ChibiOS** — capable, but more opinionated about its own build system,
  which fits a CMake project less comfortably.
- **Zephyr** — brings `west`, CMake, Kconfig and devicetree. The
  `arduino_due` board target exists but is thin, and USB device support
  on SAM3X is doubtful. Would mean learning Kconfig as much as RTOS
  concepts.
- **NuttX** — has SAM3X support including a USB device framework, but
  adopting it is a wholesale commitment rather than an experiment.

FreeRTOS is chosen because it drops into an existing CMake build as plain
source and leaves the bare-metal architecture intact underneath.

## Track D: RTEMS — queued, not started

**Decision recorded 2026-08-30. Nothing is being built, scoped or
designed for it yet, and this section is deliberately the only place it
appears.**

A fourth track will be an **RTEMS** build of the same firmware. The
reason is that RTEMS is space-qualified and used on flight hardware,
which makes it a different *kind* of comparison from Track C: FreeRTOS
answers "does the architecture survive a scheduler", RTEMS asks what the
same drivers look like under a kernel with that pedigree.

It is **not** in the "Other RTOS options" list above. Those were
considered and set aside; this is queued.

**The precondition is explicit: Track D is picked up only when A, B and
C are all stable.** Anyone reaching for this before then is reading it
wrong — the value of a fourth track is a comparison against three that
already hold, and three moving targets would produce a fourth.

**Where Track C actually is lives in the stage sections above and on
issue #45, not here.** This entry originally said "Track C is at C1 and
C2 is unfinished", which was true when it was written on 2026-08-30 and
was being overtaken within the day - `057f60b` split the application
into two tasks, which is the decomposition C2 was defined as. A queued
entry that pins itself to another track's stage number has to be
re-verified every time that track moves, and the person who wrote it is
not usually the person who moves it. So it points at the owner's own
sections instead.

Nothing follows from this entry: no issue, no scoping document, no
directory, no build target. It exists so the intent is written down
where the tracks are defined rather than carried in someone's head.
