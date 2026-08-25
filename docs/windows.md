# Windows validation

First validation of this project on a host other than macOS, run
2026-08-25 on Windows 11 Pro 26200 against a second, previously unused
Due. Everything below was measured on that machine; nothing is carried
over from the macOS figures.

Two things came out of it. The board behaves the same everywhere, and
**macOS's CDC driver is the cause of two separate open objectives** -
the `close()` wedge and the playback byte loss are one behaviour seen
twice.

## The headline

| Claim | macOS (design) | Windows | |
|---|---|---|---|
| Playback byte conservation, 200 k - 1.39 M sps | loses 0.45% - 2.25% | **0 B at every rate** | conserved |
| Playback underruns, up to 1,218,750 sps | `under=0` | **`under=0`** | matches |
| Capture continuity, 453,488 sps | gapless, 1.83 MB/s | **gapless, 1.82 MB/s** | matches |
| Loop tone amplitude | 1371 +/- 2 codes | **1370.8** | matches |
| OUT via endpoint DMA | 26.6 MB/s, *byte-perfect withdrawn* | **37.6-37.8 MB/s, 0 B deficit** | higher, and conserved |
| IN via endpoint DMA | 32.0 MB/s (single run) | **29 median, 26.4-34.0 over 9 runs** | no difference worth claiming |
| Duplex, aggregate | 8.55 + 8.40 = 16.95 MB/s | **47.7-48.5 MB/s** | ~2.8x |
| Objective 0c close wedge | ~1 cycle in 3 | **0 in 52 cycles** | does not occur |

## Objective 0c does not reproduce here

The prediction on record was: *if this is macOS's CDC-ACM close path,
the same firmware and the same soak should not wedge on Linux or
Windows.* It held.

| Run | Cycles | Wedges | Worst close |
|---|---|---|---|
| `tools/soak0c_portable.py`, close while playing | 40 | **0** | 0.002 s |
| Close with a write actively in flight | 12 | **0** | 0.002 s |

macOS, same firmware: 9 wedges in 30 cycles with the POSIX reproducer,
6 in 25 with the portable one.

**The clean soak on its own would have been a false pass, and this is
the part worth keeping.** Windows does not survive the backlog - it
never builds one. Measured rather than assumed:

- A 256 KB write returns in **0.193 s**. The DAC drains 256 KB in
  0.218 s at that rate, so `usbser.sys` is pacing the writer at the
  device's consumption rate rather than buffering.
- The device reports `in=261120` of 262,144 written when the call
  returns - about **1 KB outstanding**, against the 55-450 KB macOS
  leaves sitting below the tty layer.
- `close()` then takes **0.000 s**, because there is nothing to dispose
  of.

That is a different condition, not a passing grade on the same one. So
the condition was built deliberately: a slow DAC rate, a 4 MB write from
a writer thread, and `close()` from another thread one second in, while
the write was still blocked. The device counted **`in=430080`** during
that second - 430 KB against 400 KB/s expected, so the write was moving
data at full rate when the close hit it. Twelve cycles, no wedge.

**The mechanism is the same one that prevents the byte loss.** macOS
buffers and then loses; Windows applies backpressure and cannot. 0c and
objectives 0a/0b/0i/0k are two symptoms of one driver behaviour, not two
faults.

## Playback byte conservation

`tools/bench.py --only play --policy design`, using the design's own
feed policy from `host/measure.py` `Feeder`: whole 512-byte packets,
clock-paced against a 20 KB lead. 4 MB per rate.

| RC | sps | deficit | under |
|---|---|---|---|
| 195 | 200,000 | 0 B | 0 |
| 130 | 300,000 | 0 B | 0 |
| 98 | 397,959 | 0 B | 0 |
| 65 | 600,000 | 0 B | 0 |
| 44 | 886,363 | 0 B | 0 |
| 39 | 1,000,000 | 0 B | 0 |
| 32 | 1,218,750 | 0 B | 0 |
| 28 | 1,392,857 | 0 B | 15 (0.4%) |

Only RC 28 underruns, and it is past the 1.383 Msps DACC limit the
design itself states.

**This confirms the mechanism proposed for objective 0i.** RC 44 and
RC 39 run **1.6% slow** here too, by the device's own `runus` - so the
slow converter is real and is a property of the device. But no bytes are
lost at those rates, because Windows never oversupplies. Oversupply plus
shedding is the right diagnosis, and closing the loop on the device's
own consumption is the right fix; Windows simply does it in the driver.
(HANDOFF records 1.58% and 2.35% for these two. The first agrees, the
second does not, and is worth re-deriving.)

## A correction to the IN figure, wrong in two ways

This document first reported IN at **34.14 MB/s** against the design's
32.0, as "+7%". Both halves of that were unsound; the macOS review
caught the first.

**The clock started late.** `t0` was taken after `board.cmd()` had slept
0.4 s and read the console, during which the device was already
streaming into a host buffer megabytes deep. Those bytes counted toward
`total` while their time did not count toward `elapsed`.

The fix is a bounded discard window before the clock starts - and the
first attempt at it is worth recording as a mistake in its own right:
"drain until nothing has arrived for 200 ms" **never terminates during a
flood**, because the device never goes quiet. It hung. A fixed settle
window both empties the backlog and skips the startup transient, and it
terminates whatever the device is doing.

**And one run was never a figure.** With the clock fixed, nine runs give
26.36, 27.46, 27.82, 27.88, 28.96, 28.98, 28.99, 31.79, 34.02 - median
**28.96**, spread **26.4 to 34.0**. The original 34.14 sits at the top of
that distribution. `docs/status.md` already records this counter's
run-to-run spread as 35-59% on macOS, and the same caution simply was
not applied here.

So **IN is not measurably different between the two hosts**, and the +7%
should never have been written. OUT and duplex survive the correction:
OUT is 37.6-37.8 MB/s across runs with 0 B deficit, duplex 47.7-48.5
MB/s aggregate, and both sit far outside the spread.

Same failure as the underrun rate in issue #5 - a number quoted before
the sample was big enough to separate a difference from noise.

## Objective 0h: WRITE_SIZE is a macOS workaround

`Feeder.WRITE_SIZE = 512` is the fix for the macOS byte loss - "whatever
is due, capped at 16 KB" lost 0.45-0.85% above 200 ksps and a constant
512 lost nothing. Whether that is a property of the device, of the
protocol, or of one host's driver was never established. It is the
driver's.

Swept with the project's own `Feeder` through `run_play(drain_s=1.5)`,
four write policies against six rates:

| write policy | deficit, all six rates |
|---|---|
| 512 (current policy) | **0 B** |
| due-sized, capped at 16 KB (the legacy path) | **0 B** |
| 1536 (the size that loses most on macOS) | **0 B** |
| 16384 | **0 B** |

24 runs, not one byte lost. Confirmed at volume on the worst rate on
record: **23.48 MB through the legacy path at RC 39, deficit 0 B.** The
same run loses about 516 KB on macOS.

**The policy still earns its place, for a different reason.** Underruns
depend on write size here even though bytes do not - 16384 B roughly
doubles them against 512 B at every rate:

| RC | sps | under @ 512 | under @ 16384 |
|---|---|---|---|
| 195 | 200,000 | 0 | 3 |
| 98 | 397,959 | 0 | 9 |
| 65 | 600,000 | 0 | 15 |
| 44 | 886,363 | 6 | 20 |
| 39 | 1,000,000 | 10 | 23 |
| 28 | 1,392,857 | 21 | 37 |

Constant 512 remains the right default. The reason written beside it -
byte loss - is a macOS reason; off macOS the reason is ring stability,
and the two should not be confused, because a future host that pages the
first will not necessarily page the second.

## Capture and the full loop

`tools/loop.py`. Capture at 453,488 sps/ch, two channels, 5 s:

```
frames 2240  seq 0..2239 (expected 2240)
seq_gaps 0  dropped 0  bad_crc 0  resyncs 0  inconsistent 0
declared rate 453488 Hz/ch  payload 9.10 MB (1.82 MB/s)
```

Full loop, HOST -> DAC -> jumper -> ADC -> HOST, one channel, three
consecutive runs:

| sps | aggregate amplitude | per-window (40 ms) | spread | outside +/-2 | seq_gaps | under |
|---|---|---|---|---|---|---|
| 453,488 | **1371.2** | 1371.2 - 1371.3 | **0.1 codes** | 0 of 19 | 0 | 0 |
| 200,000 | 1370.7 | 1370.6 - 1370.8 | 0.1 codes | 0 | 0 | 0 |

The design's 1371 +/- 2 in every 40 ms window, met at both rates.

### Two measurement traps this run fell into

Recorded because both produced a confident wrong answer first.

**Underruns must be measured with a prompt stop.** Leaving playback
running while the counters drain adds a tail: the device empties the
ring and then repeats buffers until told to stop, which is a fixed
**~0.46 s** at every rate. That reads as 4% of transitions at 200 ksps
and 24% at 1.39 Msps and is entirely the harness. The tell was that
`under` scaled as 177:570:1339 against rates of 1:3:7 - a constant time,
not a rate-dependent fault. Byte conservation needs the opposite (a
drain, since a prompt stop discards what is in flight), so the two
questions need two runs. `tools/bench.py` now does both.

**Goertzel windows must hold a whole number of tone cycles.** 8192
samples at 453,488 Hz is 18.08 cycles of a 1001 Hz tone; the leftover
fraction leaks differently in every window and produced a +/-5 code
ripple that was the measurement, not the signal.

**And the window must use the tone actually emitted, not the one
requested.** Fixing the window length left a residue - the per-window
level sat ~4 codes under the whole-run aggregate at 453,488 sps while
agreeing exactly at 200,000 - and this document previously recorded that
as possibly ADC track-and-hold settling, open and undemonstrated. It was
neither. `build_waveform` picks a whole-sample period, so the DAC emits
`sps / round(sps / tone)`: exactly 1000.000 Hz at 200,000 sps, but
1001.077 Hz at 453,488, because 453.488 rounds to 453. `run_loop`
computed that correctly and then returned only the stream, so `main()`
analysed at the requested 1000.0 and reintroduced the very leakage the
whole-cycle fix had removed.

Checked against a mathematically perfect 1371-code sine, before touching
the board:

| sps | per_cycle | real tone | at real tone | at requested tone |
|---|---|---|---|---|
| 200,000 | 200 | 1000.000 Hz | 1371.00, 0 of 40 outside +/-2 | same |
| 453,488 | 453 | 1001.077 Hz | 1370.95, 0 of 17 outside | **1366.00-1367.53, 17 of 17 outside** |

On the board after the fix: aggregate 1371.2, windows 1371.2-1371.3,
spread 0.1 codes, none outside +/-2. `host/loopback.py` never had this
because it passes the tone `build_waveform` handed back.

Found by the macOS team reviewing PR #3, and findable only because the
number it was supposed to be had been written down.

## Platform notes

**The native port presents both CDC functions.** Objective 8's transport
enumerates correctly here: `COM11` at interface `.0` (samples) and
`COM12` at `.2` (commands), both reporting `SER=B-01`. This is the first
time that has been seen anywhere but macOS.

**pyserial does not surface `MI_00` on Windows.** Win32's `DeviceID`
carries it, but pyserial's `hwid` reads
`USB VID:PID=2341:003E SER=B-01 LOCATION=1-5:x.0`. The `is_sample()`
check in `tools/soak0c_portable.py` therefore matches nothing and falls
through to the location sort, which happens to order `.0` before `.2`.
Correct by luck. `tools/bench.py` sorts on `LOCATION` deliberately.

**With blank flash, SAM-BA appears on the native port.** The programming
port is the wrong place to look after an erase: the SAM3X boots ROM
SAM-BA, which enumerates as `03EB:6124` on native USB rather than
through the 16U2, and `bossac --port=COM7` reports "No device found" on a
board sitting in the bootloader waiting. `tools/flash.py` now detects
SAM-BA first and flashes it with `-U true`.

**Real-time promotion changes nothing.** `host/rt.py` is Mach-specific,
so every figure here was measured on an ordinary thread. Raising the
process to `HIGH_PRIORITY_CLASS`, the thread to
`THREAD_PRIORITY_TIME_CRITICAL` and the timer to 1 ms leaves the
underrun counts unchanged within noise. Worth stating carefully: the
first attempt at this experiment used ctypes without `argtypes`, the
calls silently failed, and it read as "priority made no difference" -
the same conclusion, reached invalidly. `restype`/`argtypes` on
`GetCurrentProcess`/`SetPriorityClass` are not optional; a 64-bit HANDLE
truncates to `c_int` without them.

## Porting host/ to the seam, and the two bugs it exposed

`host/` was POSIX-only: raw termios, `os.read`/`os.write` on a bare fd,
and `select.select` to wait on the sample and console ports together.
All of that now sits behind `host/transport.py`, so `measure.py`, the
daemon, the front end and `tests/` are written once and run everywhere.
`host/rt.py` gained the Windows and Linux promotions beside the Mach
one.

The POSIX backend is the original code **moved, not rewritten**. This
project's measured history depends on exact write semantics - "a
constant 512 bytes per write()" is the macOS byte-loss fix, and "one
blocking write" is part of objective 0c's condition - so a rewrite that
merely looked equivalent would invalidate every figure taken there.

Porting it found two real defects. Neither is Windows-specific; macOS
was hiding both.

### The settle window overran the device's ADC ring

`run_loop()` issued the `L` command and then **slept 0.2 s without
reading**. The device starts capturing the moment it takes the command,
and its ADC ring is four 4 KB buffers - 16 KB, or 20 ms at 800 KB/s. So
the host spent ten ring-fulls not reading, and the device dropped frames
it had already numbered.

Measured before: `overrun_count` 33-35 per run and a lost frame in three
runs out of four. After draining during the settle instead of sleeping
blind: **0 lost frames in four runs, overrun 0-10**, and playback still
byte-exact.

macOS never showed it because its CDC driver buffers 55-450 KB below the
tty layer and absorbed the burst. **The device was overrunning there
too** - the host just never saw the consequence. This is a real fix for
both platforms.

The settle itself has to stay. Removing it entirely starts the feed
before the device has armed playback, and the device then receives 6-20
KB less than the host sent - a byte-conservation failure, and far worse
than the overrun it was meant to cure. Measured, not assumed.

Frames read during the settle are deliberately discarded, so a run's
first analysed sequence number is no longer zero. `settle_frames`
records how many, because "starts near zero" is how a stale capture is
caught and that check has to tell the two apart.

### Windows gives a COM port 4 KB of receive buffer

At the full in-spec capture rate of 1.82 MB/s, 4096 bytes is **2.2 ms**
of headroom; the measured worst case between reads is 5.4-7.6 ms. The
port now asks for 4 MB.

And `wait_any` **drains as it polls** rather than asking `in_waiting`
and sleeping. Polling does not empty the driver buffer; only reading
does. Asking while a writer thread holds the GIL lets the buffer back
up, the device's bulk IN stops being consumed, and the ADC ring overruns
on the board - a host-side stall that arrives looking like a device
fault, with the device's own overrun counter as the only clue. That
change alone took `overrun_count` from 33-204 to a steady 33-35 before
the settle fix took it to 0-10.

### A test that pinned one OS's naming

`test_native_port_offers_both_functions` asserted the two CDC functions
report interfaces `(1, 3)`. On Windows they report `(0, 2)`, and both
are right: a CDC-ACM function spans **two** interfaces, a Communications
one carrying the notification endpoint and a Data one carrying bulk.
macOS's IOKit names the data interface because the BSD callout node
hangs off it; Windows' `usbser` names the comm interface because it
binds the function there. The test now asserts the structure the
contract actually specifies - samples first, commands one whole function
later - instead of one host's choice of which half to name.

## Toolchain

Everything Track B needs was already on the machine; nothing was
downloaded. Locations resolve from `toolchains.json` with no
`toolchains.local.json` - see `docs/toolchain.md`.

| Component | Version |
|---|---|
| `arm-none-eabi-gcc` | 14.3.Rel1 (ARM, mingw-w64) |
| `cmake` / `ninja` | 3.31.6, bundled with Visual Studio 2022 |
| `bossac` | 1.6.1-arduino |
| `arduino-cli` | bundled in Arduino IDE 2.x |

Track B builds clean: 19/19 objects, no warnings under `-Wall -Wextra`,
27,868 B text / 116 B data / 73,020 B bss.

## What runs here now

After the transport port, the project's own tooling runs on Windows -
not just the pyserial harnesses written for the first pass.

| | Result |
|---|---|
| `host/ports.py` | control COM7, native COM11, command COM12, ordered by interface |
| `host/receive.py` | 1783 frames, 0 CRC bad, 0 seq gaps, 1.825 MB/s; A1 flat at 2053-2062 |
| `host/loopback.py` | A0 1371.9 codes, A1 0.7 codes |
| `host/daemon`, `--fake` and against the board | runs; the socket is TCP, so nothing there was POSIX-bound |
| `tests/`, no hardware | 96 passed |
| `tests/ --track=b -m smoke` | 108 passed, 2 skipped |

`loopback.py`'s own per-window series oscillates 1364.3 <-> 1376.9 in a
regular beat, which is objective 0f's sampling beat and not a property
of this host - the project's own tool shows it too.

## Track A on Windows

First run of the oracle on this platform. It builds (63,612 bytes),
flashes, and reports itself:

```
# id: track=A fw=0.1.0 ctlver=0 framever=3 mck=78000000 adcclk=19500000 ...
```

`ctlver=0` is correct - Track A has no control channel yet - and the
native port presents one CDC function, so `find_all_ports()` returns no
command node. Both are the contract behaving as documented.

| Suite | Result |
|---|---|
| `--track=a -m smoke` | **89 passed, 21 skipped, 0 failed** |
| `--track=a` (full) | **198 passed, 19 failed, 24 skipped** (10m51) |

The 19 failures are the same three classes as Track B's 11, and nothing
new:

- **~10 assert a byte deficit exists** (`assert 0 > 0`, `assert 0 > 20`,
  "the loop never retuned"). Track A conserves bytes on Windows too, so
  the closed-loop tests have no oversupply to correct.
- **~6 are missing instrumentation** (`assert None`) - the carrier and
  rate-trace tests need what objective 1c says Track A does not have.
- **The rest are underrun thresholds** at the top rates.

**`arduino-cli upload` cannot flash a Due on Windows.** The sam core's
recipe does the 1200-baud touch and then points bossac at the
programming port with `-U false`. That works on macOS, where ROM SAM-BA
answers through the 16U2's UART; here the erased chip brings SAM-BA up
on the *native* port as `03EB:6124`, so bossac reports "No device found
on COM7" **having already erased the board**. Measured: it wiped Track B
and left nothing behind. `tools/sketch.py upload` now hands the binary
arduino-cli built to `tools/flash.py`, which knows where SAM-BA is and
which board it belongs to.

One test was skipped rather than fixed:
`test_playback_counters_describe_one_run_not_several` reads its identity
off the `O` occupancy line, and Track A has no `O`. That is objective 1c
and not a defect, so it skips with that reason - the same way the
control-channel and load-monitor tests already do.

## Linux: the software path, not the hardware

Run under WSL2 Ubuntu 24.04, Python 3.12.3. **No hardware**: `usbipd` is
not installed, so no USB passthrough, and nothing below touched a board.
This moves Linux from "declared tier 1 on zero evidence" to "the code
paths are exercised"; it does not make it validated.

What ran:

| | Result |
|---|---|
| `transport` backend selection | `_PosixPort`, `WINDOWS=False` |
| `rt.promote()` | reached `SCHED_FIFO`, refused for want of privilege, degraded correctly |
| `ports.usb_interfaces()` / `native_nodes()` | `{}` / `[]` with no devices - no crash |
| `toolchains.json` on Linux | resolved `cmake` at `/usr/bin`; the rest absent, as expected |
| no-hardware suite | **99 passed, 1 failed** |

The `rt.py` result is the one worth having: that is the exact
degradation branch where I had found - by inspection, not by running -
a `NameError` from Python unbinding the `except ... as` variable. It now
takes that branch for real and returns the right message. The privileged
success path still has not run; it needs `CAP_SYS_NICE` or an rtprio
limit.

**The one failure is pre-existing and not the transport port's.**
`test_the_server_leaves_no_threads_behind` times out waiting 10 s for
daemon threads to exit. Controlled by running the **pre-transport**
`host/` - which is POSIX-only and needs no port to run on Linux - from
the same venv: it fails **two** tests there, against one here. Both
versions take ~180 s wall for ~15 s of CPU, so something in the daemon
tests blocks on Linux regardless of this branch. Worth its own
investigation; it is not this PR.

## What was not measured

- **Linux.** Nothing here has run on Linux. `host/transport.py` uses the
  POSIX backend there and `host/rt.py` has a SCHED_FIFO path, both
  written against documented interfaces and **neither executed**. Treat
  the first Linux run as bring-up, not regression - it is tier 1 and has
  not earned that yet.
- **macOS after the port.** The POSIX backend is the original code
  moved, not rewritten, but no Mac has run it since. That is the one
  thing the review of this branch most needs.
- **Track A on Windows.** Only Track B was built and flashed.
- **The second channel pair.** DAC1 -> A1 is objective 3; the loop was
  validated on one channel, which is what the waveform targets.
- **The Qt front end.** Needs its own venv and PySide6; not installed
  here. `tests/test_gui.py` skips for that reason, not a platform one.
- **Long soaks.** The longest run was 5 s. Nothing here says anything
  about thermal drift or hour-scale stability.
- One board, one machine, one USB topology.
