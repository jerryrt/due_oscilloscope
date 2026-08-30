# Native Linux: bring-up on `linux-x1`

`CLAUDE.md` carried native Linux as **tier 1, deferred** - "No host,
nothing measured. Not a claim until a Linux machine has a board on it" -
for the whole project. This is that machine. Everything here is
first-time-on-Linux unless it says otherwise, and it is written as
bring-up rather than as validation: a figure counts once it is taken,
not because the platform is nominally tier 1.

| | |
|---|---|
| Bench | `linux-x1` |
| Host | Ubuntu 26.04 LTS, kernel 7.0.0-30-generic, i5-8265U, 15 GiB |
| Python | 3.14.4 (suite), 3.13.13 via brew (GUI) |
| Toolchain | apt `arm-none-eabi-gcc` **14.2.1**, cmake 4.2.3, ninja 1.13.2 |
| Track A | arduino-cli 1.5.1, `arduino:sam` 1.6.12 |
| Wiring | `DAC0->A0, DAC1->A1, A2 bare` - **measured with `s`**, below |
| Board | Track B, `Due Scope B` / `B-01`, three nodes |

The wiring is the same cabling as `macos` and `windows-desk`, and is
**not** the DSO bench's. Declared in `bench.json`, which is gitignored
per `host/provenance.py`.

## `flash.py` left every board erased here, and the cause is its own last line

This took two wrong diagnoses to reach, and both are kept because the
route matters more than the answer.

**The symptom.** `tools/flash.py` writes, verifies, resets, watches the
native port come up, reports success - and the board is in SAM-BA with
`Boot Flash: false` moments later. Every tool that then opens the console
finds silence and no native port, which reads exactly like firmware that
will not boot.

**Wrong diagnosis 1: "opening the programming port erases the board."**
Committed, documented and pushed before it was tested. The claim was that
Linux has no callout node, that the tty layer raises DTR and RTS in
`tty_port_open()`, and that on the Due those are the 16U2's RESET and
ERASE. Measured afterwards, **all four arms survive**: DTR alone, RTS
alone, both, neither - the board answers `v` every time, and six
consecutive pyserial opens at library defaults answer six times. The
`transport.py` branch it produced was reverted.

**Wrong diagnosis 2: "`-R` in the same bossac invocation races the GPNVM
write."** Tested before writing this time: `-e -w -v -b file -R` against
`-e -w -v -b file` then a separate `-R`, three reps each. **Both set the
bit, 6 of 6.** bossac's arguments were never the problem.

**What it actually is.** `touch_1200()` leaves `/dev/ttyACM0` configured
at 1200 baud, and `restore_115200()` - the function written specifically
to stop the next open re-triggering the 16U2 - is on Linux the open that
triggers it. `os.open()` applies the tty's stored termios, still 1200,
and the kernel drives the modem lines before pyserial can set the speed.
It runs *after* `wait_for_boot()`, so the boot check passes, flash.py
prints success, and the erase lands on the way out.

Measured, with a control:

| arm | after bossac | after the one open |
|---|---|---|
| `restore_115200()` | running (3/3) | **SAM-BA (3/3)** |
| same wait, no open | running (2/2) | **running (2/2)** |

**The fix is at the source**: `touch_1200()` sets the speed back to
115200 on the fd it already holds, so the stored termios is never left at
1200 and the next open is ordinary. Three full `tools/flash.sh` runs end
with the board **running** where they previously ended dead every time.
It is not a platform branch - leaving sane line coding behind is right
everywhere, and it is what `restore_115200`'s own docstring always asked
for.

**What is *not* true**, and was asserted here in an earlier version of
this file: there is no erase-on-open in general. An ordinary console open
is harmless. What is dangerous is exactly one open - the first one after
a 1200-baud touch - and the precise trigger condition inside the 16U2 was
not isolated here.

**The lesson.** `restore_115200`'s docstring already described this
symptom in one sentence - *"presents as the board mysteriously restarting
whenever a tool attaches"* - and it was read only after two mechanisms
had been invented, one of them committed. The cheap readings that would
have ended it: `bossac -i` prints `Boot Flash:` in one line, and the
function's own docstring names the failure. *Ask what state the board was
left in before blaming the transport.*

### Other things that are true and useful

- **Linux has no callout node.** `/dev/ttyACM0` is the only node; there
  is no `cu.*` to prefer. Opening it resets the board over NRSTB, which
  is documented and harmless.
- **A clear GPNVM boot bit imitates dead firmware exactly** - silent
  console, native port that will not enumerate, SAM-BA on every reset.
  Read `bossac -p <native> -i` before diagnosing anything else.
- **`bossac -b 1` is not the spelling.** `-b` takes an optional
  *attached* value, so `-b 1` parses `1` as a stray positional and exits
  "extra arguments found". Use `--boot=1`.
- **`find_all_ports()` returns as soon as the programming port is
  found** and does not wait for the native pair, so a call inside the
  ~1 s re-enumeration window returns `(ttyACM0, None, None)`.

## Byte conservation: Linux is Windows, not macOS

`tools/writepolicy.py`, same design and same arms as the 2026-08-29
macOS and windows-desk runs - four runs per arm per rate, ABBA within
each rate. `records/writepolicy-linux.jsonl`,
`records/writepolicy-linux-rc44-39.jsonl`.

| rate | const | due-sized |
|---|---|---|
| 200,000 sps | 0 B | 0 B |
| 397,959 sps | 0 B | 0 B |
| 600,000 sps | 0 B | 0 B |
| 886,363 sps | 0 B | 0 B |
| 1,000,000 sps | 0 B | 0 B |

**0 B in all 40 runs, both arms, every rate, `under=0` throughout.**

macOS loses 0.605-0.633% at 397,959 and 0.763-0.915% at 600,000 on the
due-sized arm. Linux loses nothing on either arm, which is the Windows
result. So `Feeder.WRITE_SIZE` is confirmed a **macOS-only** workaround
on a third platform, and `tests/helpers.py`'s
`BUFFERING_HOST = sys.platform == "darwin"` is now *measured* for Linux
rather than inferred from `not darwin`. The five tests it skips here are
correctly skipped.

## The WSL2 ambiguity is resolved, and the tunnel was innocent

`CLAUDE.md` flagged this explicitly and said only a native host could
settle it:

> "Linux buffers ahead without discarding" and "usbip supplies the
> elasticity" predict the same numbers, and only a native host separates
> them.

The WSL2 run had **lower** underruns than native Windows at the top of
the ladder - median 0 against 6 at RC 44, 0 against 8 at RC 39 - and that
was read as the tunnel's queue flattering the device, "optimistic, not
pessimistic, which is the worse trap".

Native Linux, no tunnel:

| | RC 44 | RC 39 |
|---|---|---|
| native Windows | 6 | 8 |
| WSL2 via usbip | 0 | 0 |
| **native Linux** | **0** | **0** |

The elasticity is **Linux's own**, not usbip's. The WSL2 underrun
figures were not optimistic after all.

Stated carefully, because this is one bench: it does not prove usbip
contributes nothing, and the kernels differ (7.0.0 native against WSL2's
5.15). What it removes is the *reason to suspect* the tunnel - native
Linux reaches 0 unaided, so no tunnel is needed to explain 0.

Note also that Linux beats native Windows here: Windows conserves bytes
but still underruns 6-8 times at these rates, and Linux does not.

## Suites

| suite | result |
|---|---|
| Track B, board attached | **505 passed, 1 failed, 16 skipped, 1 xfailed** (8:47) |
| GUI (`.venv-gui`, offscreen) | **100 passed** (23 s) |
| Track A, board attached | **502 passed, 5 failed, 17 skipped, 1 xfailed** (8:55), twice - all five are issue #33 downstream, and pass in isolation |

The failure is
`test_control.py::test_stream_stats_says_what_the_console_says[b]` -
`ring_overflow` 292 from the control channel against 332 from the
console. It **passes 3/3 standalone**, so it is context-only, the same
class as the `test_the_fanout_cost_is_recorded_per_frame` failure
documented on macOS. Not a Linux defect.

The xfail is issue #5's gate, drawing +13.5 codes at phase 156, inside
the recorded range.

### Track A's five failures were #33, and there is no separate Linux defect

Recorded here first as five reproducible Linux-only failures, and
separately as a wedge that "did not reproduce". They are one thing.

**All five pass in isolation on a healthy board** - `test_contract`
3 of 3, `test_channels` 11 of 11 - and the earlier "reproduces in
isolation" reading was taken while the board was already wedged, which
made it worthless. In the full suite they fail because the board has
wedged earlier in the run and everything main-loop-served is dark from
that point: the refusal text the harness looks for, the sweep rows, the
stream window.

windows-desk settled the attribution by running all five **by name** on
their bench and passing 7 of 7, which is what made this falsifiable
rather than a suspicion about `drain_console`.

So the entry is: **issue #33**, Track A stops servicing under sustained
host-fed playback.

### #33 characterised from this bench

Feeder self-limits (pyserial blocking writes with a `write_timeout`) and
liveness is PING on the **command** node, which resets nothing - the
console lives on the programming port and closing that drops DTR, which
is NRSTB and looks exactly like a recovery.

**It is a hang, not starvation.**

| step | PING |
|---|---|
| armed, before feed | alive |
| immediately after the flood | dead |
| +10 s, +20 s, +30 s, +60 s idle, console untouched | dead, dead, dead, dead |
| after NRSTB | alive |

Two minutes of complete idle does not clear it. Only a reset does.

**Duration-governed, which confirms windows-desk's bisect on a second
host.**

| dac_hz | bytes at stall | time |
|---|---|---|
| 200,000 | 1,317,888 (2574 x 512) | 5.2 s |
| 397,959 | 2,590,720 (5060 x 512) | 5.2 s |
| 600,000 | 3,890,176 (7598 x 512) | 5.2 s |

Time constant over a 3x rate span, bytes linear in rate, and the byte
count repeats **to the byte** across runs. An earlier version of this
file said "it is not duration alone" on the strength of `--mb` values
read as durations; that is withdrawn.

**The threshold is feed-policy-dependent, and that is probably why the
two benches disagree.** `bench.py`'s paced `design` feeder wedges at
about 2.6 s of data on this host while the unpaced blocking feeder
survives to 5.2 s - same board, same rate, same machine. windows-desk
reads 6.4/8.6 s with the paced feeder. So "the threshold" is a property
of the feeder as much as of the device, and a single number should not
be quoted without saying which feeder produced it.

**The clock starts at the first byte, not at arm.** Arm, wait 3 s, then
feed: stalls after 5.2 s *of feeding*, byte-identical to the no-delay
run.

**It is not a HardFault.** The console was held open *through* the stall
- every earlier read here was taken after an open that resets the board,
so a dump could never have been seen. Zero console bytes across 25 s
spanning the stall, and `fault.cpp` prints `*** HARD FAULT ***` with a
register dump over polled UART before `blink_forever()`.

**Root cause, found and fixed (`a7ef102`).** The playback-status block
writes a record on bulk IN once per `PLAYSTAT_MS` while `play_active()`,
and its comment claimed the write was bounded - "SerialUSB.write returns
short rather than spinning when no bank is free". It is not. On this
core `Serial_::write()` reaches `UDD_Send()`, whose first statement is

    while (TXINI != (UOTGHS->UOTGHS_DEVEPTISR[ep] & TXINI)) {}

an unbounded spin, which `docs/hardware.md` already records from the
same source. `availableForWrite()` cannot serve as the guard either - it
returns the constant `EPX_SIZE - 1` whatever the banks are doing. So a
host that feeds bulk OUT and stops draining bulk **IN** fills both banks
and the main loop spins there until the board is reset. Testing TXINI
first makes it bounded; a dropped record is something the host already
tolerates, because it differences whichever records arrive.

Before: hangs at 1,317,888 B / 5.2 s, 3 of 3. After: 8,030,720 B over
20 s, no stall, 2 of 2, and windows-desk's own reproducer lands on their
Track B control's figures. Track A suite goes from 502 passed / 5 failed
to **506 passed / 1 failed**, the remainder being the documented
`test_awg_ladder_play_only[a-32]`.

### Track B already knew, which is invariant 3 working

`drivers/usb_cdc.c`'s `ep_fifo_write()` carries the guard this bug
needed, written first, on the oracle track:

    /*
     * No spinning. If no bank is free the host is not draining,
     * and blocking here is precisely the failure that wedges the
     * Arduino CDC path.
     */
    if (!(UOTGHS->UOTGHS_DEVEPTISR[ep] & UOTGHS_DEVEPTISR_TXINI))
            break;

Byte for byte what Track A now does, **with the failure mode named in
the comment**. Track B's own playback-status block then says
"usb_cdc_write never spins - it gives up when no bank is free", and
unlike Track A's version of that sentence it is true of its own code.

So the two tracks carried opposite claims about one hazard: Track B's
correct and demonstrated, Track A's asserted and false. The oracle was
right and had been for as long as the file existed - nobody was
comparing the two lines. That is invariant 3 delivering exactly what it
promises, and it is worth knowing that the *comments* diverge as well as
the register programming.

### Why it looked platform-specific, and mostly was not

Worth writing down, because the framing cost time.

**It is not a Linux bug.** windows-desk opened #33 from Windows. This
bench found the *cause*, not the defect.

What genuinely differs between hosts is the **threshold**, and it is set
host-side by how deep the IN direction buffers before the host stops
draining it, plus how the feeder is paced:

- `host/transport.py` requests `RX_BUFFER` of 4 MB on Windows and
  nothing on POSIX, which takes the kernel tty default. A deeper buffer
  stalls later.
- Feed pacing moves it on one host: `bench.py`'s paced feeder wedges at
  about 2.6 s here where an unpaced blocking feeder survives to 5.2 s.

That gives Linux 5.2 s against Windows' 6.4-8.6 s - the same order,
which is what one firmware defect modulated by buffer depth should look
like. **Scheduler differences are not implicated.**

**Why it went undiagnosed everywhere is not platform at all: the failure
destroys its own evidence.** Console, control channel and `GET_LOAD` are
all main-loop-served and die with the loop, so the device goes dark
while still enumerating; and the natural next move - kill the process,
or open the console to look - resets the board and erases the state.
Diagnosis needed an observer that outlives the loop it watches, which is
what the TC-interrupt stall watchdog was: it caught the loop in this
stage with `CFSR` clean. **The missing instrument was the whole problem,
and the platform was incidental.**

**One hypothesis killed, recorded so it is not re-run.** The DPRAM
re-allocation hazard - `usbdma_keepalive()` rewriting EP2/EP3 while the
control channel's EP4-6 sit above them - is **already handled**.
`ep_apply_autosw()` calls `ctlusb_realloc_endpoints()` after its
`DEVEPTCFG` write, and the other two calls in that path (`ep_take`,
`ep_reset_fifo`) write `DEVEPTIDR`/`DEVIDR` and `EPRST` only. The file
knows about the hazard and says so.

Idle endpoint telemetry, for whoever reads this state next:

    # usbdma mode in=0 out=0 rebuilds=0 dtr=0
    # ep2(OUT) CFG=00003066 AUTOSW=0  ep3(IN) CFG=00003166 DEVIMR=00005008

`DEVIMR` bit 14 is `PEP_2`, so the core's interrupt on the sample OUT
endpoint is live at idle - which is what `usbdma_keepalive()` takes away
once playback arms. Whether the core wins it back under flood is the
open measurement.

**The blind spot, and the instrument it wants.** Everything observable
here is main-loop-served, so PING, `GET_LOAD` and the console all go dark
together and nothing can say *why* the loop stopped. The cheap fix is
timer-interrupt telemetry that survives the stall: a TC ISR increments a
counter, `bsp/load.c` already counts main-loop passes, and the ratio read
after recovery proves the loop stopped while interrupts did not - no
live transmission and no printf from an ISR, so invariant 6 holds.
Proposed on #33; not built, because it is a change to both tracks and
both benches are mid-diagnosis elsewhere.

`rt.py`'s `SCHED_FIFO` path works natively - `sched=fifo:10`, policy
confirmed with `sched_getscheduler`. It had only ever run under WSL2
before. Without an `rtprio` limit it declines cleanly with an accurate
message rather than pretending.

## Two documented figures reproduce independently

From `s` on a third board-and-host, which is worth more than either
existing bench re-running it:

| Quantity | Recorded | `linux-x1` |
|---|---|---|
| DAC output span | 546-2760 mV | **547-2766 mV** |
| ADC linearity | 171-172 codes / 256 DAC codes | **~172.3** |

## Setting up the next Linux box

`toolchains.json` needs **no new entry** - all five tools resolve
unmodified, with apt's cross compiler found at `/usr/bin`. What is not in
the docs and was needed here:

1. **`dialout` group.** `/dev/ttyACM*` is `root:dialout 0660`; without it
   every open is `EACCES`. Takes effect at next login (`sg dialout -c`
   bridges the current one).
2. **ModemManager** probes every new `ttyACM` and sends AT commands at
   the board. Ignore ours by VID/PID with `ID_MM_DEVICE_IGNORE=1` on
   2341:003d, 2341:003e and 03eb:6124, rather than disabling the service.
3. **`rtprio` is 0 by default**, so `rt.py` cannot promote. A
   `limits.d` entry fixes it, at next login.
4. **The GUI needs a second interpreter.** PySide6 6.9.3 is
   `>=3.9,<3.14` and Ubuntu 26.04 ships only 3.14, which is not in the
   archive as a lower version; brew's `python@3.13` is what this bench
   uses. `requirements-gui.txt` then installs **unchanged** - the pins
   resolve on Linux/3.13 as they do on macOS/3.13 and Windows/3.12.

### flash.py's boot-bit failures are explained

All three `Boot Flash: false` boards here came from `tools/flash.py` or
`tools/sketch.sh`, and none from a direct bossac run. That is not a
coincidence and not bossac: it is `restore_115200()` erasing the board
after the boot check, as measured above. The fix in `touch_1200()`
removes it.
