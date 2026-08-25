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
| OUT via endpoint DMA | 26.6 MB/s, *byte-perfect withdrawn* | **37.58 MB/s, 0 B deficit** | +41% |
| IN via endpoint DMA | 32.0 MB/s | **34.14 MB/s** | +7% |
| Duplex, aggregate | 8.55 + 8.40 = 16.95 MB/s | **18.94 + 28.41 = 47.35 MB/s** | 2.8x |
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

## What was not measured

- **Track A on Windows.** Only Track B was built and flashed.
- **The second channel pair.** A1 was captured at `nch=2` and did not
  read flat, but DAC1 -> A1 is objective 3 and the loop was validated on
  one channel, which is what the waveform targets.
- **The daemon and the Qt front end.** Both are POSIX-bound through
  `host/`; neither was run.
- **The pytest suite.** `tests/` imports `host/`, so it does not run
  here. Everything above went through `tools/bench.py` and
  `tools/loop.py`, which are pyserial-only.
- **Long soaks.** The longest run was 5 s. Nothing here says anything
  about thermal drift or hour-scale stability.
- One board, one machine, one USB topology.
