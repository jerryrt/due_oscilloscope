# Bare Metal and RTOS

Both variants are built from the **same drivers**. `drivers/` is
RTOS-agnostic; only `main()` differs. That is what makes the comparison
meaningful rather than two unrelated projects.

```
apps/baremetal_bringup/main.c     superloop + ISRs (exists, working)
apps/rtos_bringup/main.c          FreeRTOS tasks + the same ISRs (not started)
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
