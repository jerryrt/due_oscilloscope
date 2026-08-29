# Status and Known Issues

> **2026-08-23: read `docs/HANDOFF.md` objective 0h before quoting
> anything below that was measured above 200 ksps.** The host's USB
> stack was silently discarding 0.45-0.85% of what `write()` counted on
> the playback path, and the underrun counter - which most figures here
> were judged by - stays at zero through exactly that kind of loss. The
> feed is fixed (a constant 512-byte write, `Feeder.WRITE_SIZE`), two
> narrower losses remain, and the figures here have not yet been
> re-read against byte conservation. Some will hold; 886,363 and
> 1,000,000 sps will not.
>
> **2026-08-25: that loss is macOS's, not the device's.** The same
> firmware on Windows 11 conserves every byte at every rate from 200,000
> to 1,392,857 sps, including the two above. Windows' `usbser.sys` paces
> the writer at the device's consumption rate instead of buffering, so
> it has nothing to discard - and for the same reason it never wedges in
> `close()` either. `docs/windows.md`.


## Provenance audit: which figures here predate which fix

**2026-08-27.** Every figure below is dated by `git blame` - the newest
figure-bearing line in its section - and compared against the changes
that alter what a measurement of that kind *means*. **20 of 31
figure-bearing sections are postdated by at least one of them.**

Two distinctions this table keeps, because collapsing them is how an
audit becomes noise:

- **"Postdated by" is mechanical and certain.** It is a date comparison
  out of git, nothing more.
- **"Invalidated" is a judgement and is not claimed here.** A DAC fix
  does not touch a throughput figure; the classification below is by
  keyword and deliberately over-flags. A flagged figure is one to
  re-take before quoting, not one known to be wrong.

The reason to do this at all is that firmware age was invisible and
turned out to matter: reflashing this bench across `623d4dc` moved the
noise floor by a **whole bit** and collapsed a spread that had been
published as repeatability. Nothing warned anyone - both benches
reported `fw 0.2.0` four hours and three DAC commits apart. See
`docs/noise.md`.

### The changes that redefine a measurement

| commit | when | what it changes about a figure |
|---|---|---|
| `15d08f7` | 08-23 02:00 | constant-size writes. Byte conservation on the playback path; objective 0h's gate |
| `3cf34fe` | 08-25 15:38 | `PLAY_PRIME_BUFS` 4 -> 24. Takes underruns to **zero at every rate on the ladder** |
| `c6415fc` | 08-27 07:09 | the sync default. A1 peak-to-peak goes 18-20 -> 2753, so every A1-referenced arm means something else |
| `2e74fbb`, `f38523b`, `623d4dc` | 08-27 08:09-11:39 | the DAC and its sync. `623d4dc` clears a disturbance worth a bit of ADC noise |

### What is flagged

| section | newest figure | postdated by |
|---|---|---|
| Status and Known Issues | 08-25 | `3cf34fe` prime |
| The bulk path no longer goes through the core | 08-22 | `15d08f7` bytes, `3cf34fe` prime |
| The loop, measured per window | 08-22 | `623d4dc` DAC |
| The single-channel floor is measured, not scaled | 08-22 | `15d08f7` bytes, `3cf34fe` prime, `623d4dc` DAC |
| Headline result: both tracks reach the full ADC rate | 08-21 | `15d08f7` bytes, `3cf34fe` prime |
| A conclusion that was wrong twice | 08-21 | `15d08f7` bytes, `3cf34fe` prime |
| What survives about the DMA plan | 08-22 | `15d08f7` bytes, `3cf34fe` prime |
| The full loop works; the "frozen DAC" was the receiver's own bug | 08-21 | `15d08f7` bytes, `3cf34fe` prime, `623d4dc` DAC, `c6415fc` A1 |
| Two host-side bugs that looked like firmware bugs | 08-21 | `15d08f7` bytes, `3cf34fe` prime |
| Found by the test suite: host-fed playback lost samples | 08-22 | `15d08f7` bytes, `3cf34fe` prime |
| What is left is the host's, and it has a different fingerprint | 08-22 | `15d08f7` bytes, `3cf34fe` prime |
| Playback still starves at RC 65, 32 and 28 | 08-22 | `15d08f7` bytes, `3cf34fe` prime |
| The slew alarm that was the sampling beat | 08-22 | `623d4dc` DAC |
| And then the widened margin caught something real | 08-22 | `15d08f7` bytes, `3cf34fe` prime, `623d4dc` DAC |
| The daemon runs free-threaded, and it matters under load | 08-22 | `15d08f7` bytes, `3cf34fe` prime |
| Objective 0a: a hypothesis disproved, and better evidence than it | 08-22 | `15d08f7` bytes, `3cf34fe` prime, `623d4dc` DAC |
| Capture over endpoint DMA, and what it cost to get right | 08-22 | `15d08f7` bytes, `3cf34fe` prime |
| The objective's premise was wrong | 08-22 | `15d08f7` bytes, `3cf34fe` prime |
| Measured figures | 08-23 | `3cf34fe` prime, `623d4dc` DAC |
| Windows 11, second board, 2026-08-25 | 08-25 | `3cf34fe` prime, `623d4dc` DAC |

<!-- 20 of 31 figure-bearing sections -->

### Two things the audit found that are not merely stale

**1. The DAC output range in "Measured figures" is the retired pair.**
It reads 546-2760 mV. `calibration.json` records the scope-measured span
as **578-2771** and keeps 546-2760 under `adc_derived_*` precisely
because it folds the ADC's own offset into the DAC's span and reads
about 32 mV low at the bottom. `docs/hardware.md` carries the same
retired pair as current. Both now point at the calibration record
instead of restating it - one home for the number, which is the rule
`host/calibration.py` exists to enforce.

**2. "Playback still starves at RC 65, 32 and 28" documents starvation
that has since been fixed.** It was measured 08-22; `3cf34fe` landed
08-25 and took underruns to zero at every rate on the ladder. That table
is not un-revalidated, it is very likely *wrong now*, and it is marked
where it sits.

### Both halves executed, 2026-08-27

**The analog half, this bench, current firmware.** The whole hardware
suite: **499 passed, 5 skipped, 4 xfailed, no failures**, 14 minutes.
The four xfails are the known documented defects - issue #5's wrap
displacement, and the macOS byte loss at RC 44, 39 and 28, now
quantified at 1.41%, 2.21% and a 57,856 B residual. Every rate,
amplitude, channel, integrity, load and daemon assertion in
`tests/baseline.json` holds on the post-`623d4dc` build.

Two documented figures moved and both are corrected above: the loop's
"tone 1371 +/- 2 in every window" is 99.3% of windows rather than all of
them, and the playback starvation ladder is gone.

**The host half is not all mine to run.** Transport MB/s was re-taken on
Windows on 08-27 and is current. What this bench can say about the rest
is that the byte deficits reproduce here and are macOS's - which is not
a re-validation of the Windows figures, it is a confirmation that the
macOS ones are still what they were. The 0-series re-take at tier 1
remains open and remains the other bench's.

### What this does not do

It dates sections, not individual numbers, and it dates when a figure
was **written** rather than when it was measured - usually the same
session, but not guaranteed. It also cannot see a figure that was
correct when taken and is still correct: absence from this table is not
a warrant, and presence in it is not a retraction.


Updated after the host-fed playback loss was root-caused and fixed on
both tracks: `play_service()` read the OUT DMA's status register twice
where it needed one read. See "Found by the test suite: host-fed
playback lost samples".

## Recorded figures, generated

Everything in this section is **generated from the recorded measurements
by `tools/report.py`** and nothing in it is hand-written. That is the
point of it: the audit above catalogues figures that went stale because
they were copied into prose and outlived their measurement, and these
cannot, because `tools/report.py --check` fails when the document and
`tests/baseline.json` disagree.

The boundary is deliberate. Numbers live here; the argument for a number,
its caveats and its retractions stay in prose, because those are what a
generator cannot check and what carries the meaning. Do not hand-edit
between the markers - regeneration discards it.

### Trigger rates

<!-- generated: rates -->
| what | RC | sps |
|---|---|---|
| two channels, per channel | 86 | 453,488 |
| two channels, aggregate | 86 | 906,976 |
| one channel | 44 | 886,363 |
| DAC top | 28 | 1,392,857 |

TC clock 39,000,000 Hz, MCK 78,000,000 Hz, ADC clock 19,500,000 Hz.
<!-- end generated -->

### Frame geometry and amplitude

<!-- generated: frame -->
| field | value |
|---|---|
| frame header | 32 bytes |
| samples per frame | 2032 |
| frame size | 4096 bytes |
| full scale | 1370.5 codes |
| window floor | 1340.0 codes |
| window fraction | 0.9 |
<!-- end generated -->

### Transport

<!-- generated: transport -->
| direction | measured MB/s | floor MB/s | worst-case margin |
|---|---|---|---|
| duplex | - | 3.0 | - |
| duplex-dma | 8.19-20.03 | 5.0 | 1.64x |
| in | - | 3.0 | - |
| in-dma | 19.84-30.45 | 12.0 | 1.65x |
| out | - | 3.0 | - |
| out-dma | 17.94-28.23 | 12.0 | 1.50x |
<!-- end generated -->

The margin column is taken from the **low** end of each observed range,
because a floor answers "did the worst run clear it" - see issue #6,
where a single IN reading looked quotable against a ~40% spread.

### Calibration

<!-- generated: calibration -->
| group | key | value |
|---|---|---|
| adc_transfer | advref_mv | 3270 |
| adc_transfer | advref_mv_assumed_previously | 3300 |
| adc_transfer | advref_tolerance_mv | 40 |
| adc_transfer | loop_slope_adc_per_dac_code | 0.67053 |
| adc_transfer | worst_dev_codes_over_measured_range | 4.4 |
| dac_mv | adc_derived_span_hi | 2760 |
| dac_mv | adc_derived_span_lo | 546 |
| dac_mv | span_hi | 2771 |
| dac_mv | span_lo | 578 |
| dac_mv | span_tolerance_mv | 40 |
| dac_mv | uv_per_code | 535.5 |

From `calibration.json`, via `host/calibration.py`. The `_comment` blocks there record how each figure was arrived at and are deliberately not reproduced: they are the argument, not the number.
<!-- end generated -->


## Working

| Capability | Track A | Track B |
|---|---|---|
| UART printf, LED, HardFault report | yes | yes |
| DAC/ADC loopback, sweep, crosstalk | yes | yes |
| TC-triggered ADC + PDC ping-pong | yes | yes |
| Trigger-rate verification | yes, plus refusal past the ceiling | yes, plus refusal past the ceiling |
| TC-triggered DAC playback (TAG mode) | yes | yes |
| USB CDC device | Arduino core, bulk endpoints on own DMA | **own bare-metal stack** |
| Framed binary streaming | yes, resumable | yes, resumable |
| Host deframe / demux / tone check | yes | yes, same receiver |
| Host-fed DAC playback over bulk OUT | yes, by endpoint DMA | yes, by endpoint DMA |
| Full loop: host waveform out, capture back, simultaneously | **yes, to the full-rate pair** | **yes, to the full-rate pair** |
| Transport benchmarks via endpoint DMA | yes | yes |

## Track A parity

The oracle answers every key Track B does, with the same letters and the
same output format: rate arguments, the full loop, playback alone, the
ring dump, the snapshot diagnostic, the USB-free mimic loop, the duplex
bench, the UART transport, the register dump and the three DMA
benchmarks.

### The bulk path no longer goes through the core

Track A used to starve above roughly 62 ksps of host-fed playback, and
the reason was on the record: `Serial_::read()` calls `accept()` once
per byte and each call refills the whole 512-byte receive ring, which
the OUT benchmark had independently clocked at 0.126 MB/s (see
`docs/usb.md`).

The fix keeps the Arduino core for enumeration, descriptors, control
transfers and the 1200-baud erase, and takes only the two bulk endpoints
away from it, programming the UOTGHS DMA channels directly. See
`sketches/bringup/usbdma.cpp`. Two hazards, both already recorded from
Track B's own DMA work, apply here with an extra twist:

- **AUTOSW must be written with the endpoint enabled.** A `DEVEPTCFG`
  write while `EPEN` is clear is silently ignored on this part. Before
  the host opens the port the endpoint is not enabled at all, so the
  mode cannot be applied yet and the keepalive deliberately does
  nothing there.
- **The core rebuilds endpoint configuration** on every bus reset and
  `SET_CONFIGURATION`, clearing AUTOSW and re-enabling its own receive
  interrupt. A sketch gets no hook into either event, so the mode is
  re-asserted by polling. `B` reports the rebuild count; it is zero
  through a normal run, and climbing means the link is resetting
  underneath rather than the data being wrong.

### Transport, measured host-side

**Re-taken on Windows 2026-08-27**, which is the 0-series debt this
file's header opens with. The macOS table is kept below it: it is still
the record for macOS, and this project's rule is to re-take a figure
before disbelieving it rather than to delete it.

Three interleaved rounds per track, a reflash between every arm, plus
one run each from the per-file calibration sweep - so four points per
cell rather than one.

| Direction | Track A | Track B | macOS A | macOS B |
|---|---|---|---|---|
| OUT | **32.38-32.62** | **32.19-32.41** | 27.33 | 26.92 |
| IN | **22.21-30.54** | **27.46-35.65** | 31.02 | 32.12 |
| Duplex | **46.41-46.76** | **46.14-46.98** | 15.19 | 16.25 |

**Duplex is the headline: about 2.9x.** 46-47 MB/s combined is 78% of
USB 2.0 high speed's 60 MB/s against macOS's 28%, and it is the same
firmware and the same cable - which is what a host that paces the writer
instead of buffering and discarding buys. OUT gains about 20%.

**IN cannot be quoted as a single number and the old one should not
have been.** It spans 22.2 to 35.7 MB/s here, and the two tracks are
indistinguishable inside that: Track A's 30.54 sits above Track B's
27.46. The apparent 42% track gap in the first single-run pair - 25.06
against 35.65 - did not survive interleaving, which is the second time
in one day that a clean-looking separation on this bench died that way.

**So the "run-to-run spread is about 5%" above is wrong for IN**, and
that sentence is what made a single IN reading look quotable. OUT and
duplex do hold to about 1% across every round, which is why the gap that
matters shows up in them and not in IN.

**OUT has since moved, on both tracks, and the table above is the old
value.** Re-taken across the shared-framer move - Track B at `ed62111`
on #25, Track A on windows-desk 2026-08-29 - both read **37.3-37.5
MB/s** against the 32.2-32.6 recorded here:

| arm | Track A, 08-29 | Track B, #25 | this table |
|---|---|---|---|
| OUT | **37.28** | **37.51** | 32.38-32.62 (A) |
| IN | 26.22 | 29.69 | 22.21-30.54 (A) |
| duplex | **48.20** | **48.25** | 46.41-46.76 (A) |

A 15% shift in the one arm this section documents as stable to 1%,
reproduced on two tracks that share no hardware source and agreeing to
0.6%, is not run spread. #29 carried Track B's figure as "n=1 against a
documented 35-59% spread, quote nothing until re-taken" - but that
spread is **IN's**, not OUT's, and a second track is the re-take. What
moved it is untested; the framer move is the obvious candidate only
because it is what these were re-taken across.

**IN is unchanged and must not be read from those two numbers.** 26.22
against 29.69 is 11.7% and looks like a track gap; it is inside the
range already above, and this is one un-interleaved run per track, which
the paragraph above says is not a measurement of IN at all. Duplex is up
about 3% - larger than the 1% claimed for it, smaller than OUT's shift,
and wanting an interleaved re-take rather than a claim.

Both benched with `tools/bench.py`, whose play arm was reporting an
unread counter as a 100% deficit on Track A until `412935d`; the
transport arms above were never affected by it.

The macOS figures, for reference:

| Direction | Track A | Track B |
|---|---|---|
| OUT | 27.33 MB/s | 26.92 MB/s |
| IN | 31.02 MB/s | 32.12 MB/s |
| Duplex | 15.19 MB/s | 16.25 MB/s |

Getting there took one fix that applied to both, and it was not where it
looked. Track A's OUT read 19.7 against Track B's 24.0, which invited
the conclusion that the Arduino stack was the problem. It was not:

- **Per-call costs are near identical** between the tracks -
  `stream_service()` 1690 ns on A against 1731 on B. Both are -Os with
  no LTO. The `Q` command on either track prints the whole table.
- **The decisive number was bytes per DMA arm: 347 against a 2048-byte
  buffer, the same on both.** The sink bench armed OUT with `END_TR_EN`,
  which ends a transfer on any short packet, and host pacing produces
  those constantly. What the OUT number measured was re-arm latency;
  Track A was slower only because its loop is 1.43x slower.
- Removing `END_TR_EN` took each arm to the full 2048 bytes and both
  tracks to ~27 MB/s. The playback ring had known this since the
  multi-slot span work; the bench had not.
- An 8192-byte buffer changed nothing (28.03 against 28.16), so the wire
  is now the limit and the 12 KB stays free.
- Two frames per IN transfer was tried and measured **worse** on Track A
  (28.7-29.7 against 30.2-31.2): a second header costs more per arm than
  the re-arm gap it removes. `DMA_FRAMES_PER_XFER` is kept at 1.

Two traps for whoever measures next. Loop rate must be measured with the
bench armed and **no traffic** - under load the arming path is skipped
whenever a channel is busy, and the loop reads far faster than it is.
And the IN flood counters read far above the wire on both tracks, which
is the bank overcommit standing as objective 6 in `docs/HANDOFF.md`.

### The DMA endpoints must be recovered after a rebuild

Track A's IN direction stalled intermittently after exactly one short
transfer - roughly one run in two, which reads as flakiness rather than
a bug. Opening the control port resets the board, so enumeration lands
just after the bench arms its first transfer; `SET_CONFIGURATION` then
rebuilds the endpoint and clears AUTOSW under a transfer already in
flight. That transfer can never complete, and every caller polls "is the
channel still busy" before re-arming, so one stalled channel wedges the
direction for good.

Stopping the channel is necessary and **not sufficient**. A stopped IN
DMA leaves a bank partially filled and never validated; nothing frees
it, so the next transfer waits for a free bank that cannot arrive and
stalls identically. `EPRST` clears the banks and the data toggle. Both
tracks now do this; Track B owns enumeration so its timing never exposed
the bug, but its code was equally capable of it.

### The loop, measured per window

Theoretical maximum for a full-scale sine is ~1370.5 codes.

| Loop rate, each way | Track | Underruns | Windows |
|---|---|---|---|
| 200,000 sps | A | 0 | 1373.1 |
| 453,488 sps | A | 7-9 | mostly 1365-1377 |
| DAC 906,976 + capture 453,488 | A | 0 | 1028-1338 |
| DAC 906,976 + capture 453,488 | B | 0 | 1074-1345 |

**Read these per window, never per run.** The whole-run Goertzel at
453,488 sps reads 232 codes while nearly every window reads above 1360,
because a phase discontinuity cancels the average across five seconds.
That is the trap this document has warned about since the trigger-path
work, and it still nearly produced a report of a collapse that was not
happening.

### The 900 ksps loop, and single-channel capture

There are two ways to ask for ~900 ksps and they are not the same rate.

**Two channels.** `DAC 906,976 + capture 453,488 Hz per channel` is
906,976 conversions per second, the ADC's full in-spec output: two
channels convert round-robin off one trigger. Both tracks run it with
`under=0`, zero sequence gaps and zero CRC failures.

**One channel.** `--adc-channels 1` captures A0 alone, and the ceiling
is **886,363 sps at RC 44** - measured, and *lower* in conversions per
second than the two-channel figure. Both tracks run a matched loop
there, DAC and ADC both at 886,363 sps:

| Track | Underruns | Gaps | CRC bad | Windows |
|---|---|---|---|---|
| A | 0 | 0 | 0 | 1103-1383 |
| B | 0 | 0 | 0 | 1157-1379 |

A **matched** `906,976` on both sides is refused on either track, and
correctly so.

### The single-channel floor is measured, not scaled

RC 44 gives ratio 1.000; RC 43 gives **0.500** - every other trigger
dropped, RXBUFF and GOVRE both clear. The same silent cliff as the
two-channel case, in the same shape.

It is **not** half of 86. The obvious arithmetic - one channel does half
the conversions, so halve the compare value - yields 43 and walks
straight off the cliff, which is exactly what the first version of this
guard did and what the sweep caught. `ACQ_MIN_RC_FOR()` is therefore a
table of measured values, not a formula.

The reason one channel is *slower* per conversion: a two-channel trigger
converts its pair back to back and amortises the per-trigger overhead,
while a single conversion pays it in full. So two channels reach 906,976
conversions per second and one reaches 886,363.

Both tracks measure the identical cliff, which is the whole point of
keeping the oracle: `=0,0,1t` runs the sweep at one channel on either.

Capture alone is unchanged and still matches Track B at the in-spec
ceiling: 453,488 Hz per channel, 1.831 MB/s, 0 CRC failures, 0 sequence
gaps, ratio 1.000, tone at 1372.4 codes.

## Headline result: both tracks reach the full ADC rate

Same host, same receiver, same wire format:

| Trigger | Aggregate | Required | Track A | Track B |
|---|---|---|---|---|
| 200 kHz | 400 ksps | 0.80 MB/s | 0.806, ratio 1.000 | 0.806, ratio 1.000 |
| 400 kHz | 800 ksps | 1.60 MB/s | 1.613, ratio 1.000 | 1.613, ratio 1.000 |
| 488 kHz | 976,744 sps | 1.95 MB/s | **1.969, ratio 1.000** | **1.969, ratio 1.000** |

**Both tracks stream the ADC's entire output continuously, with no gaps**,
over ordinary USB CDC. Over eight seconds each delivers 3845 frames and
about 15.75 MB with zero sequence gaps, zero CRC errors, and a
measured-to-declared rate ratio of exactly one.

### A conclusion that was wrong twice

An earlier version of this document reported that the Arduino CDC capped
near 0.95 MB/s and that the bare-metal stack was roughly twice as fast.
Both the number and the explanation were wrong, and the sequence is worth
recording because the reasoning failed in two different ways.

**First error: blaming the transport.** The 0.95 MB/s ceiling was real
but self-inflicted. `stream_service()` tested `(bool)SerialUSB` on every
pass, and `Serial_::operator bool()` ends with `delay(10)`. Ten
milliseconds of pure sleep per service call was the entire ceiling. The
guard was also unnecessary: `Serial_::write` already returns zero without
blocking when the host has not set `lineState`. Deleting it took Track A
from 0.946 MB/s to 1.969 MB/s with no other change.

**Second error: blaming the compiler.** Before finding that, the gap was
attributed to gcc 4.8.3 versus gcc 15.2.1, on the strength of a measured
1.93x difference in a tight GPIO loop against a 2.07x difference in
throughput. Two experiments killed it:

- Rebuilding Track A with gcc 15.2.1 via
  `arduino-cli --build-property compiler.path=...` made the GPIO loop
  1.93x faster (138.3 ns to 71.5 ns) and left USB throughput **exactly
  unchanged** at 0.946 MB/s. That alone showed the write path was not the
  limit. `UDD_Send` also lives in the prebuilt
  `libsam_sam3x8e_gcc_rel.a`, so the new compiler never touched it.
- Compiling identical source with both compilers and comparing
  disassembly showed the difference is marginal, not 2x:

  ```
  copy_ptr  gcc 4.8.3   cmp / beq / ldrb / strb / adds / b    (6 per byte)
  copy_ptr  gcc 15.2.1  cmp / bne / ldrb.w+ / strb.w+ / b     (5 per byte)
  copy_idx  gcc 4.8.3   identical to gcc 15.2.1, instruction for instruction
  ```

  Track B's writer uses the indexed form, which both compilers compile
  the same way. The GPIO result simply did not generalise to a
  byte-copy loop.

**What actually settled it** was measuring instead of arguing. Timing
only the region inside `SerialUSB.write` gave an effective 8.925 MB/s,
about nine times the achieved rate. That located the cost outside the
transport immediately, and the `delay(10)` was found within minutes.

The transferable lesson: a throughput number is a property of the whole
loop, not of the call you suspect. Instrument the suspect region before
attributing anything to it.

### What survives about the DMA plan

The zero-copy argument is unaffected: `UDD_Send` still has the processor
copying every sample byte into the endpoint FIFO, which contradicts the
architecture's central rule. A vendor-class endpoint driven by UOTGHS
DMA remains the right destination on CPU-cost grounds.

But the throughput argument for it is gone. At full rate the write
occupies roughly a fifth of wall time, so about 80% of the processor is
still idle. DMA is now an efficiency improvement, not an enabler.

*Postscript, after the DMA work landed:* that conclusion held for
one-direction streaming and fell for full-rate duplex - the CPU-copy
paths capped gated OUT near 1.7 MB/s while capture streamed, and the
907 ksps full-duplex pair only ran once the playback ring was DMA-fed.
So: not needed for capture-only throughput, an enabler after all for
the full instrument. Endpoint DMA now works (see `docs/usb.md`) and
playback uses it; capture IN conversion is the current objective.

## How the USB stack was fixed

It did not enumerate for a long time. Register dumps showed everything
correct: clocks locked, PHY enabled, device attached, EP0 configured with
`CFGOK` set, interrupts unmasked. One `EORST` was serviced and no `SETUP`
ever followed.

Three real bugs were found and fixed along the way:

- `PMC_USB_USBS` was missing, so the PHY ran from PLLA rather than the
  UTMI PLL.
- `NBTRANS` was left at zero, which makes the controller reject the
  endpoint configuration outright.
- `DEVEPT` was written by assignment rather than OR, so configuring each
  endpoint disabled the previous ones.

None of those was the blocker. **The blocker was the interrupt path**:
`UOTGHS_Handler` serviced exactly one bus reset and then never fired
again, even with `PEP_0` unmasked in `DEVIMR`.

The fix was to stop relying on it. `usb_cdc_poll()` services the same
events from the main loop, and the device enumerated immediately at High
Speed. This is not a workaround so much as the right shape: control
transfers happen a few dozen times during enumeration and essentially
never afterwards, so polling them costs nothing, and only the bulk path
needs to be fast.

Why the interrupt never re-fires is still unexplained and worth
returning to, but it no longer blocks anything.

## The full loop works; the "frozen DAC" was the receiver's own bug

The complete chain - host-authored 1 kHz sine over bulk OUT, DAC0,
jumper, A0, ADC, bulk IN - runs simultaneously in both directions:
1024 frames in 5 s with zero sequence gaps, zero CRC errors, zero
overruns, Goertzel amplitude 1371 codes on A0 against a theoretical
maximum of ~1370, and A1 flat at 0.1 codes. DAC consumption at 200 ksps
and capture at 400 ksps aggregate, about 1.24 MB/s combined.

A full session was previously spent on a defect described as "playback
works, capture works, together the analog output freezes at mid scale".
That freeze never existed on the device. A stream from an earlier run
keeps flowing into the kernel's input buffer after the run ends; the
next run's receiver read ~800 kB of those stale frames first - the flat
mid-scale startup of an *old* capture - and the "1 sequence gap" it
reported on every run was the splice between the stale epoch and the
live one. Frame timestamps proved it: the capture contained one epoch at
device time ~0 s and a second at device time ~52 s, inside a 5-second
run. The device-side counters said all along that playback was
consuming host data on schedule, and they were right.

This is the *same* stale-buffer failure mode already recorded below
under "Two host-side bugs that looked like firmware bugs" - it bit
twice because a one-shot `tcflush` at open does not empty a buffer the
device is still refilling. `host/loopback.py` now drains the native
port until it stays silent for a full second, refuses to trust a
capture whose first frame is not near sequence zero, and reports tone
amplitude windowed against device timestamps so a late or intermittent
tone shows as what it is.

Two real firmware fixes came out of the same investigation, verified
independently: `usb_cdc_read()` used to discard the undrained tail of
an OUT bank after a clipped read (one short packet then byte-shifts the
whole sample stream), and the DACC + TIOA1 trigger path was exonerated
on hardware by command `M`, which plays gen's sine through play's exact
configuration with capture running and no USB involved.

The feed-margin problem was then closed for good, and the path there
uncovered a macOS behaviour worth its own record. Four feed policies
were measured: select()-paced writes in a shared loop starve on poll
granularity (~1% shortfall, underruns); free-running blocking writes
saturate the queue, and **a pressured macOS CDC-ACM output path
silently drops ~128-byte chunks that write() has already counted** -
measured as ~75 clean phase jumps per second on the DAC with every
counter on both sides green, and confirmed by byte conservation
(host-written minus device-received ~= jumps x 128 B); clock pacing at
the exact byte rate still dropped at every tested lead. The clean
policy, now in `host/loopback.py`: a real-time thread polls TIOCOUTQ
and bursts 16 KB only into a *truly empty* queue. Result: zero
underruns, zero gaps, 1371 +/- 2 codes in every 40 ms window of a run,
reproducible across tones.

The host threads use `host/rt.py`: macOS's QoS class plus the Mach
THREAD_TIME_CONSTRAINT real-time band (the CoreAudio I/O policy),
stdlib-only via ctypes. There is no thread-to-core pinning on XNU;
the real-time band is the mechanism that exists, and it measurably
suffices.

One firmware lesson came out of the same investigation: a CDC device
must keep accepting bulk OUT even when nothing consumes it, because
macOS's close() waits for in-flight write URBs that a NAKing pipe
never completes, wedging the host process in close() while it holds
the port. The main loop now drains and discards OUT when neither
playback nor a bench sink owns it.

## Two host-side bugs that looked like firmware bugs

Both produced symptoms that pointed convincingly at the device, and both
cost real time. They are recorded because the misdirection is the
lesson.

**Slow parsing dropped bytes.** The receiver parsed each frame inline,
including a per-sample Python loop. At around 0.9 MB/s it could not keep
up, so the port stopped being drained and the kernel buffer overflowed.
The symptom was samples attributed to ADC channels that were not enabled,
plus sequence jumps: exactly what a firmware framing bug looks like.
Splitting capture from parsing fixed it.

**Stale buffered data.** Restarting a stream resets the sequence number
to zero, but bytes from the previous run were still queued in the kernel
buffer. The receiver saw old high-numbered frames followed by new
zero-numbered ones, reported a single enormous sequence jump, and counted
more samples than the ADC could possibly have produced. Flushing the port
before starting the capture clock fixed it.

The tell in both cases was arithmetic: the frame count exceeded what the
configured sample rate could generate. **A receiver reporting more data
than the source can produce is describing its own bug.**

## The ~10-byte playback loss, settled within tolerance (issue #20)

**Closed on a bound, not a mechanism, 2026-08-29.** While capture IN
DMA is armed, the device occasionally loses a forward-only run of
~10 bytes from host-fed playback. The agreed tolerance is **1% of a
playback window's bytes**; everything recorded on current firmware
across both benches sits under 0.01% per window (worst characterized
event: 0.64%, windows-desk, midnight batch). The integrity suite
asserts the bound and xfail-documents the residual, and discriminates
the neighbouring classes so none can hide under another: host chunk
drops (128-byte multiples, macOS only), bidirectional jitter (#24,
matched forward/backward pairs), and this loss (forward-only,
non-128-multiple).

Facts a reader needs before trusting a counter: **no device counter
sees this loss.** play_partial, underruns, spans and even the byte
deficit stay clean through a losing run - the device counts every
byte as received and still skips samples at the DAC (verified across
150 runs with in-session counters, records/issue20-counters-macos.jsonl).
Detection is host-side, by the ramp test. Do not read under=0 as
integrity.

The rate has **per-host weather**: hour-scale on/off, macOS 10-50x
hotter than Windows in the one simultaneously sampled hour
(2026-08-29 14:00-15:00Z, both arms saturating 73-95% here at ~0.01%
intensity while windows-desk read 0-19%). Both arms track the weather
together on each bench; earlier arm-asymmetry readings were weather
moving between sequential series. Full record in
records/issue20-*.jsonl, five datasets, benches and dates attached.
Reopen #20 if the bound breaks or a new size class appears.

## Found by the test suite: host-fed playback lost samples

**Fixed.** Samples the host wrote did not all reach the DAC, and nothing
on either side noticed. The cause was one register read too many.

`play_service()` asked the OUT DMA channel two questions - how far have
you got, and have you finished - and each question was a separate read
of `UOTGHS_DEVDMASTATUS`. `usb_dma_out_received()` read `BUFF_COUNT`;
`usb_dma_out_busy()`, a few hundred nanoseconds later, read `CHANN_ENB`
out of the same register. When the transfer completed between the two
reads, the byte count belonged to an earlier instant than the verdict
that the span was over:

- `done` came back short by whatever the controller had landed in
  between - tens to a few hundred bytes,
- `fill_off` was therefore computed as a non-zero offset into a slot
  that was in fact complete,
- the next span was armed at that offset, *behind* data already in
  SRAM, and the bytes arriving next overwrote samples that had arrived
  but had not yet been played.

Overwritten, not dropped: the output skipped forward, always forward,
by less than one slot, with the ring's own counters describing a
perfectly healthy transfer. `play_bytes_in` under-reported by exactly
the same amount, which is why the byte accounting never closed.

Every number lines up. The window is one iteration's worth of
arithmetic between two loads, against a service loop measured on Track
A at 247,000 passes in 3 s, about 12 us apart; spans complete about 50
times a second at 200 ksps,
so a few percent of them land in the window - 3 to 13 events per 3 s
run, observed. The loss per event is bounded by what the DMA can land
in that window, which is why every one of the sixty-odd measured
events was smaller than a 1024-byte slot: 12 to 370 bytes.

The fix is one read, decoded twice (`usb_dma_out_status()`, the same
name on both tracks since the #14 rename). After it, at 200 ksps:

| | Before | After |
|---|---|---|
| Ramp discontinuities, 3 s | 3-13 | 0 (5 runs B, 4 runs A) |
| `host_tx - play_bytes_in` over 3 s | 1,536-9,216 B | 0 B, every run but one (384 B) |
| Spans ending off a slot edge | 6-14 per run | 0 |

`play_partial` is that last row, and it stays in the firmware as a
tripwire: the arithmetic says a stream span cannot end anywhere but on
a slot edge, so a non-zero count is this defect or its next relative.
`assert_spans_whole()` checks it on every measurement that touches
playback.

### The evidence that pointed at the host was the wrong kind

The earlier write-up reasoned that because both tracks lost samples
identically, and Track A and Track B share no source, the fault had to
be on the host. That inference does not hold, and it cost time.

`sketches/bringup/play.cpp` says in its own header comment that it is
deliberately identical to `drivers/play.c` "down to the trigger source,
the ring geometry, the prime threshold and the multi-slot DMA spans".
The tracks share no *file*; they share the *algorithm*, line for line,
including both reads of `DEVDMASTATUS`. Two transliterations of one
design failing the same way is evidence for a design fault, not against
it. Independence of implementation is what would have made that
argument work, and there was none.

The same review found that Track A was still latching the next playback
slot at `play_produced - play_consumed >= 2u`, the guard Track B fixed
in ebd90d5 - so the cross-check that "reproduced" the defect on Track A
was run against firmware carrying a second, known, uncorrected source
of exactly this symptom. Track A now has the guard too. Keeping the
tracks feature-equivalent is an instruction in `CLAUDE.md`; this is what
it is for.

### What was suspected and cleared

**`END_B_EN` on the receiving channel.** On a DMA channel that receives,
that bit lets the endpoint discard whatever is left in the current bank
when the DMA buffer runs out - a plausible mechanism for a silent,
sub-packet, always-forward loss. It was tested by making the bit
switchable at runtime and alternating it within one session, one
firmware image, one cable: 6-13 events with it set, 5-11 with it clear.
Not the cause. The arm keeps the bit, and the toggle was removed again.

### What is left is the host's, and it has a different fingerprint

The fix does not make the loop perfect, and the residue is worth
knowing apart from what it replaced. On a loaded machine a 3 s run
still occasionally skips - roughly one run in eight while the suite or
a build is running alongside, and not once in 22 runs on a quiet one.

The two are told apart by the size of the loss:

| | Device-side, fixed | Host-side, open |
|---|---|---|
| Loss sizes measured | 12, 20, 22, 24, 32, 62, 64, ... 336, 352, 356, 360, 366 B - arbitrary, no common factor | 128, 128, 128, 128, 256, 128 B - **every one a multiple of 128** |
| `play_partial` | 6-14 per run | 0 |
| Rate | 3-13 per 3 s run, always | 0-4 per 3 s run, only under load |

An arbitrary size is what a race window produces, because the amount
lost is however much DMA landed inside it. A fixed quantum is what a
chunked copy produces, and 128 bytes is the size `docs/usb.md` already
records macOS's CDC-ACM output path discarding from a pressured tty
queue with `write()` having counted them.

The byte accounting agrees: on runs that skip, `host_tx - play_bytes_in`
exceeds the ramp's loss by the same 256-384 B of end-of-run residue that
clean runs show, so the missing bytes never reached the device at all.
That is the comparison the previous session wanted and could not make,
because `play_bytes_in` under-reported by a varying amount; it does not
any more.

`test_host_fed_ramp_loses_no_samples` encodes the distinction: an
arbitrary forward jump fails the test outright, a whole 128-byte chunk
reports as an xfail naming the host, and a quiet machine passes it.

### Playback still starves at RC 65, 32 and 28

> **Superseded, and re-measured 2026-08-27.** The cause was
> `PLAY_PRIME_BUFS = 4` - the DAC's timer started on an eighth of a ring
> - and `3cf34fe` raised it to 24. Re-run on current firmware, same
> bench, `tools/bench.py --only play`, 3 s per rate:
>
> | RC | rate | underruns | byte deficit |
> |---|---|---|---|
> | 195 | 200,000 | 0 | 0.214% |
> | 130 | 300,000 | 0 | 0 |
> | 98 | 397,959 | 0 | 0 |
> | **65** | **600,000** | **0** | **0** |
> | 44 | 886,363 | 0 *(see below)* | 0.403-0.562% |
> | 39 | 1,000,000 | 0 | 0.763% |
> | **32** | **1,218,750** | **0** | **0** |
> | **28** | **1,392,857** | **0** | 0.629% |
>
> **The three rates this section is about - 65, 32, 28 - now run with
> zero underruns**, against the 9 to 17 recorded below. The table that
> follows is history.
>
> The deficits are the macOS byte loss and are a different defect: they
> reproduce, they are xfailed in the suite with the mechanism named, and
> Windows conserves every byte at the same rates (`docs/windows.md`).
>
> One ladder pass showed **199 underruns at RC 44**, and three repeats of
> that rate alone showed zero. Not reproducible, so not a finding -
> recorded because it was seen, not because it means anything yet.

Recorded here as "related and probably the same mechanism". It is not.
Measured after the fix, five play-only runs each, underruns per 3 s:

| RC | sps | Before | After |
|---|---|---|---|
| 195 | 200,000 | 5/5 clean | 5/5 clean, 0 underruns |
| 98 | 397,959 | 5/5 clean | 5/5 clean, 0 underruns |
| **65** | 600,000 | 0/5 clean, ~17 | **0/5 clean, 9-13** |
| 44 | 886,363 | 5/5 clean | 5/5 clean, 0 underruns |
| 39 | 1,000,000 | 5/5 clean | 5/5 clean, 0 underruns |
| **32** | 1,218,750 | 1/5 clean | **3/5 clean, 35-36 when it fails** |
| **28** | 1,392,857 | 1/5 clean | **1/5 clean, 38-39 when it fails** |

Unchanged, and `partial` is zero in all of them. It is a feed-policy
problem, tracked on its own in `docs/HANDOFF.md`.

The new `spans` counter says something useful about it: a run that
starves arms *few, large* spans (RC 32, failing: 464 spans in 3 s) and a
run that does not arms many small ones (RC 32, clean: 6,610). The two
outcomes are visible from the first milliseconds and hold for the whole
run, which matches what the host-side queue measurements already said.

## Found by the test suite: three defects, fixed

**`SET_LINE_CODING` was answered before its data stage.** Opening the
native port cost 25 s in `open()` and another 25 s in `tcsetattr()`,
every time, on Track B only. A control write is SETUP, then the host's
data, then a zero-length IN as the status stage; the device sent the
status ZLP immediately, so the seven bytes still to come were never
accepted and macOS retried until it gave up. The SETUP log (`u`) showed
thirteen `bm=21 req=20 len=7` where there should be one. Track A opened
in 0.00 s on the same cable throughout, which is what ruled out the
marginal cable and the host driver. Fixed; four consecutive opens now
measure 0.00 s.

**The console dropped commands typed while it was printing.**
`uart_getc()` read `UART_RHR` directly, so anything arriving while the
main loop sat inside a printf was lost - and the reply to `0` alone
swallows the next seventeen characters at 115200. A `=0,0,1t` sent
straight after a stop consistently lost its rate arguments and ran a
two-channel sweep instead. RX is now interrupt buffered. Track A never
had this; Arduino's `Serial` is interrupt driven.

**The frame header declared the requested rate, not the real one.**
Asking for 210,000 Hz gets RC 185 and 210,810 conversions per second,
and the header said 210,000. Every host-side frequency derived from it
was wrong by the same 0.4% with every counter clean. Both tracks now
report `39 MHz / RC`.

**The playback ring could latch an unfilled slot.** At ENDTX the PDC has
already moved TNPR into TPR, so the slot being queued is
`play_consumed + 2` and needs `play_produced >= play_consumed + 3`; the
guard checked for 2. Found while investigating the lost samples above -
it is a real latent defect but **it did not change that symptom**, and
is fixed on its own merits: it turns a silently emitted unfilled buffer
into a counted underrun. Fixed on Track B at the time and on Track A
only later, which mattered: see "The evidence that pointed at the host
was the wrong kind" above.

## The slew alarm that was the sampling beat

`test_no_sample_step_exceeds_the_waveform_slope` failed about one run
in three, reporting a 91-code step against its 69-code limit - the
invariant-5 alarm, which reads as samples spliced from two points in
time. It first appeared after the test venv moved to Python 3.14, and
it is not the interpreter: a venv rebuilt on the old 3.9.6 failed it 2
runs in 6 as well. It was there before, and the recorded two-track pass
of 2026-08-22 got past it by luck.

The measurement is **bimodal, not noisy**: 49-51 codes or 88-92, never
between. That is the signature of a fixed phase relationship decided at
start, not of random corruption. Instrumenting the largest step and
printing its neighbourhood shows what it is:

```
 d=-42   d=-42   d=+1   d=-88   d=-43   d=-42
```

One sample repeats, the next step spans two DAC updates, and the pair
sums to -87 - exactly the two-update slope - with the sine's phase
intact either side. Nothing is lost and nothing is spliced: the DAC
update clock and the ADC trigger are separate TC channels at the same
nominal rate, free running against each other, and when they beat, one
ADC sample lands inside a DAC update it has already seen. About 700 of
these appear in a 3 s run when the beat is present and none when it is
not, which is the bimodality.

**The threshold was wrong, not the device.** The helper's documented
default margin is 3.0. The device-only control - `M`, the host removed
from the DAC side entirely - has always used 3.0 and measures 38-43
codes against an analytic 17, which is 2.2-2.5x by itself. The host-fed
test carried 1.6 only because it was an xfail while the lost-sample
defect was open, so the margin was never exercised against clean
behaviour; when the defect closed and the xfail came off, the number
came with it unexamined. Raised to 3.0. Five runs since pass while
still showing both modes (92, 49, 92, 49, 49).

A splice is orders of magnitude clear of either line, so the test still
catches what it was written for. What the suite has for real sample
loss is the ramp, which is byte-exact and stayed green throughout.

Worth noting for the next reader: **a threshold that has only ever run
under an xfail has not been tested**. When an xfail is removed, the
numbers it was hiding need re-deriving, not inheriting.

### And then the widened margin caught something real

With the margin at 3.0 the test failed again on Track A, this time at
**1911 codes against a 129-code limit** - forty-four times the analytic
step, and larger than the tone's own full-scale amplitude. That is not
the beat; it is a genuine discontinuity, and the wider threshold caught
it anyway, which is what a threshold set from the mechanism rather than
from the observed spread is supposed to do.

It is the host's chunk drop, arriving in a sine instead of a ramp. One
128-byte chunk is 64 samples; at 200 ksps against a 1 kHz tone that is
a 115.2 degree phase jump, and a jump that size produces a step of up
to 2,314 codes. 1911 sits inside that.

The proof available is the same one the ramp test uses: the device's
byte accounting is exact, and `host_tx_bytes - play.bytes_in` measures
**0 on every healthy run** - five runs, byte for byte. So the slew test
now makes the same three-way distinction the ramp test does. A step
over the limit with the device short by a whole multiple of 128 bytes
is macOS, reported as an xfail that names it. A step over the limit
with the byte counts matching is the device, and still fails outright.

Neither test can be read as "the sine looked wrong, therefore the
firmware is broken" any more, which is the mistake that cost a
fortnight the first time.

## Found by testing the daemon: the banner costs eleven underruns

The daemon's `status` reply included the device description, and the
description was found by asking the board which track it runs - which
means asking for the banner. Playback through the daemon then underran
**exactly 11 times per run, three runs out of three**, where
`measure.run_loop` on the same rates gives none.

Isolated by elimination rather than argued about:

| Variant | Underruns |
|---|---|
| `run_loop`, no daemon | 0, 0, 0 |
| daemon, subscriber, status polled mid-stream | 11, 12, 11 |
| daemon, subscriber, counters read after stop | 0, 0 |
| daemon, no subscriber | 0, 0 |
| mid-stream: host reads the console for 1 s, sends nothing | 0, 0 |
| mid-stream: `B`, the short counters report | 0, 0 |
| mid-stream: `which_track` (sends `h`) | 11, 11 |
| mid-stream: `h` alone | 11, 11 |

So it is not the daemon's fan-out competing for the GIL, and not the
host reading a port. It is the **device** printing: the banner is a
long console print, the main loop is inside it, and `play_service()`
does not run while it is. The ring drains and the DAC repeats a buffer,
which is exactly what the underrun counter is for. `B` is short enough
not to matter; the banner is not.

That is the same arithmetic as the rule already in `CLAUDE.md` - a
printf costs about 3.5 ms against a 0.95 us conversion - arriving from
the other direction: not an ISR this time, but a main loop that owes
the DAC a buffer every few hundred microseconds.

**Consequences, now built into the daemon.** `status` is answerable
from the host alone and touches nothing; the device description is
asked for once and cached, since the track cannot change without a
reflash; counters are a separate op a client asks for deliberately. A
front end polling status twice a second would otherwise have corrupted
every playback it watched, and every counter would have said the host
was at fault.

**The rule this leaves:** on a poll path, ask the device nothing.

## The daemon runs free-threaded, and it matters under load

The question was whether the daemon's own work - fan-out, recording,
anything a real front end asks for - competes with the real-time feeder
through the GIL. It does, and the measurement is not subtle.

Same script, same board, same rates, four pure-Python threads burning
CPU inside the daemon process for four seconds:

| Build | Underruns | Frames read (quiet run: ~890) |
|---|---|---|
| 3.14.6, GIL | 13 | **132** |
| 3.14.6, free-threaded | 0 | 891 |

On the GIL build the burners take the interpreter away from both
real-time threads: playback underruns *and* capture collapses to 15% of
the frames, because the reader cannot drain the port either. On the
free-threaded build the same load is invisible - underruns zero, frames
identical to a quiet run, and the quiet runs either side of it agree.

**Why this was cheap to try.** The free-threaded ABI needs its own
wheels and most projects do not ship them yet. The daemon is stdlib
only, so it needs none: `python3.14t -m venv` and it runs. The property
that looked like an inconvenience earlier in the evening is what made
the experiment a five-minute change.

**Why it is safe here.** Without the GIL, `x += 1` on a shared
attribute is no longer implicitly atomic. Every counter in the daemon
is either written by exactly one thread - `frames_read` by the reader,
`sent_frames` by that session's sender - or written under the lock that
already guards its queue, as `dropped` is. The full test suite passes
on the free-threaded build: 86 tests, and faster than on the GIL build
because the threads genuinely overlap.

**What it does not fix.** Load in *other* processes is the operating
system's scheduler, not the GIL, and nothing here changes that. This
decouples the daemon's own threads from each other, which is the part
the daemon owns.

## Where the latency is, in microseconds

The counters say a buffer went dry. They do not say by how much the
thread that fills it was late, and that is the number any fix has to
move. `host/jitter.py` records three latencies in log-2 microsecond
buckets - the interval between device reads that returned data, the
cost of fanning one frame out to every client and the recorder, and the
interval between the feeder's writes - and the daemon reports them in
`status`.

Validated against a condition already known to be bad, which is the
only honest way to introduce an instrument. Four pure-Python threads
burning CPU in the daemon process, 200 ksps loop, four seconds:

| Build, load | read gap max | feed gap max | Underruns |
|---|---|---|---|
| GIL, quiet | 5.4 ms | 2.3 ms | 0 |
| GIL, 4 burners | **92 ms** | **72 ms** | 18 |
| free-threaded, 4 burners | 5.1 ms | 2.3 ms | 0 |

That is the mechanism stated in the units that matter. The playback
ring is 32 KB, which is about 80 ms at 200 ksps and about 18 ms at the
full rate. A 72 ms gap between writes empties it; a 2.3 ms gap does
not. Nothing here needed to be inferred from an underrun count.

Two figures worth keeping from the healthy case. Fan-out costs a mean
of 45 us per frame and never exceeded 127 us in these runs, so it is
not what delays the reader. And the feeder's write gap is ~1.28 ms mean
with a 2.3 ms maximum on a quiet machine, which is comfortable against
80 ms and much less comfortable against 18 ms - which is the argument
for ring depth, now with a number attached.

## Objective 0a: a hypothesis disproved, and better evidence than it

The theory was that the feeder paces against the host's crystal while
the DAC consumes on the device's, so the cushion drifts out over a run.
It is wrong, and the way it fell apart is worth keeping, because two
plausible measurements had to be thrown away first.

**Two drift figures, both artifacts.** Pacing on device timestamps
appeared to show the device clock running 6% fast. It is not. The first
version anchored device time at the first frame the host read, which is
typically 0.19 s old because the stream starts before the read loop
does; anchoring host time and the byte count at the same instant did
not fix it, because the *observation* of device time lags by however
deep the kernel buffer is, and a draining backlog makes device time
appear to advance faster than real time. The arithmetic settles it: 
1,916,176 samples arrived in 3.00 s, which reads as 638,725 sps against
a declared 600,000 - and 600,725 sps once the 0.19 s of pre-roll is
removed. The device clock is right to 0.1%.

**Which leaves the real finding.** At RC 65 the host fed 1.225 MB/s
against a nominal need of 1.200 MB/s - a 2% *surplus* - and still
underran 7 to 10 times per 3 s run. **The starvation is not a rate
deficit.** No pacing correction can fix a feed that is already ahead on
average.

**What did fix it, and what that says.** The buggy version, which
believed it was 228 KB behind, wrote until the queue blocked and
underran zero times in four runs out of four. Its span counts are the
tell:

| Feed | Underruns per 3 s | OUT DMA spans |
|---|---|---|
| clock-paced, 20 KB lead | 7, 8, 6, 8 | ~237 |
| over-fed into saturation | 0, 0, 0, 0 | ~3,525 |

That is exactly the discriminator this objective already records - a
starving run arms few large spans, a healthy one arms many small ones -
and it now has a second rate confirming it. The mechanism is on the
device: under a trickle feed the OUT DMA arms few, large spans that
take too long to complete, and the ring runs dry underneath them.

**Why the fix is not shipped.** Writing until the queue blocks is
free-running into saturation, and a pressured tty output queue is
exactly where macOS drops 128-byte chunks. It trades a counted underrun
for a silent data loss. The feed policy change was reverted; only the
finding is kept.

**The next experiment**, then, is not about clocks: hold a bounded lead
measured against the device's consumption rather than the kernel queue,
target 70-80% ring occupancy, and watch the span count. If spans stay
high while the queue stays shallow, the mechanism is confirmed and the
policy is safe. If spans collapse the moment the queue drains, the
arming policy in the firmware is what needs changing, not the feed.

## Capture over endpoint DMA, and what it cost to get right

The CPU no longer touches sample data on Track B. Each capture buffer
carries 32 bytes of headroom in front of its payload, so a finished
frame is 4096 contiguous bytes: the PDC is pointed at the samples, the
processor writes only the header, and one DMA sends both. That closes
the last violation of invariant 1.

Getting there took four measurements, and the first version looked
perfect while losing data.

**One 4096-byte transfer per frame streams cleanly and starves the
ADC.** No sequence gaps, no CRC failures, no DMA stalls - and 439 ADC
general overruns in a 4 s run at the full rate, against **zero** on the
CPU-copy path. It was only visible because the previous firmware was
flashed back and measured rather than assumed to be equivalent.

The mechanism is bus contention: the USB DMA holds the matrix while the
ADC's PDC is trying to write the next conversion into SRAM, and the
conversion is lost. Two changes were needed, and the 2x2 is why both:

| Capture ring | Transfer size | GOVRE per 4 s at full rate |
|---|---|---|
| bank 0 | 4096 B | 439 |
| bank 1 | 4096 B | 202 |
| bank 0 | 512 B | 77 |
| bank 1 | 512 B | **0** |

So transfers are packet-sized - which also keeps every transfer exactly
one bulk packet, so nothing short is ever emitted mid-frame - and the
capture ring moved to bank 1 while the playback ring moved to bank 0.
A swap, not a shrink: playback keeps all 32 KB of depth.

**This answers an open question in `docs/scope.md`.** Whether the two
SRAM banks are distinct bus-matrix slaves, and whether placement
actually removes contention, was listed as needing the datasheet and a
measurement. It does, and the measurement is the table above.

### The objective's premise was wrong

Objective 1 said the CPU copy was the source of the capture resyncs
that hold full-rate purity at 90-95%. It is not. Loop mode at the
full-rate pair, three runs each:

| Path | Median window (codes) | resync |
|---|---|---|
| DMA | 1291, 1293, 1298 | 2 |
| CPU copy | 1292, 1306, 1293 | 2 |

Indistinguishable. Whatever limits purity at the full-rate pair, it is
not the copy, and the resync count is identical either way. What the
change does buy is the invariant, the processor time the copy used, and
a capture-only stream at the full rate that is now as clean as the CPU
path while doing no copying. The 200 ksps loop stays byte-exact:
deficit 0, under=0, partial=0.

Worth keeping as a rule: **a firmware change that looks equivalent must
be measured against the firmware it replaces, not against expectation.**
Reflashing the old build took three minutes and was the only reason the
439 overruns were attributed to this change rather than to the board.

### Track A has this change too, and the linker was never the obstacle

Same struct, same packet-sized transfers, same per-direction DMA mode
setters, and the capture ring pinned to bank 1 exactly as here. Done
2026-08-25.

**The blocker on record did not exist.** This section used to say Track
A "links against the Arduino core's script and has no way to pin a
buffer to a bank". Two facts out of the installed toolchain say
otherwise, and neither had ever been checked:

- the stock Due `flash.ld` already declares
  `sram1 (rwx) : ORIGIN = 0x20080000, LENGTH = 0x00008000`, and nothing
  is placed in it;
- `platform.txt` links with `-T{build.variant.path}/{build.ldscript}`
  and `boards.txt` sets `build.ldscript`, so it substitutes like any
  other build property - the same mechanism `build.f_cpu` already
  relies on.

`linker/arduino_due_x_sram1.ld` is that script with two changes, and
`tools/sketch.sh` computes the relative path and passes it. Both
changes are load-bearing:

1. **`ram` shrinks from 96K to bank 0's 64K.** The stock region spans
   0x20070000..0x20088000, which *includes* bank 1 - so `.bss` grows
   into the bank the DMA buffer is pinned to and lands on top of it with
   no diagnostic. It already did: before this, the sketch's `.bss` ended
   at 0x20081B6C, 6.5 KB inside bank 1.
2. **A `.sram1` output section**, placed last in the script so that
   `_end` - which is where `syscalls_sam3.c`'s `_sbrk()` starts the heap
   - stays in bank 0.

The stack follows `ram` and therefore moves from the top of bank 1 to
the top of bank 0, which is the point: leaving it in bank 1 would put
every push and pop in the way of the PDC writes the separation exists to
protect. That leaves 9032 bytes for stack and heap together, against
Track B's 8784 - the same budget, not a new risk.

### What it measures

Three firmwares, flashed and measured the same way in the same session,
capture-only at the full rate (`5`, 4 s, three runs each) and the
full-rate loop:

| Track A build | GOVRE per 4 s, capture-only | Median window in loop mode |
|---|---|---|
| CPU copy (the path it replaces) | 0, 0, 0 | 1213.3 |
| DMA, ring in bank 0 | 42, 44, 35 | 1255.6 *(check - one arm, three runs)* |
| **DMA, ring in bank 1** | **0, 0, 0** | **1255.6** |

Same shape as Track B's 2x2 above, and the same cause: 35-44 overruns
in bank 0 against Track B's 77, zero in bank 1 against Track B's zero.
`dma-frames` equals `frames` and `dma-stalls` is 0, so every frame goes
out by DMA and none of them falls back.

**The 81 in the old text was not the copy path's number.** It was this
port's own, measured in bank 0 - the row above, not the row below it.
The copy path measures **zero** in capture-only mode, re-measured here
across three runs. Anything that quoted 81 as the cost of copying was
reading the table upside down.

**Purity improves, which Track B's did not.** Median window over six
full-rate loop runs each: 1213.3 on the copy path against 1255.6 on
DMA, and every one of the six DMA runs beats every one of the six copy
runs (1252.2-1266.7 against 1207.5-1218.9). Against a theoretical
maximum of 1370.5. The bank-0 arm reaches the same 1255.6, so it is the
DMA path buying this and not the placement.

**Loop-mode GOVRE does not separate the arms**, and six runs each is not
enough to say it ever will: copy 1, 13, 67, 93, 480, 881; DMA in bank 1
9, 12, 14, 24, 145, 473. Medians 80 against 19, distributions
overlapping. Read the capture-only column for the placement question -
that one is clean - and do not quote a loop-mode overrun figure from a
single run in either direction.

## Measured figures

| Quantity | Value |
|---|---|
| DAC output range | **578 mV to 2771 mV**, `calibration.json` - measured with a scope on the pin. The 546-2760 this line used to give is the retired ADC-derived pair, which folds the ADC's own offset into the DAC's span |
| ADC aggregate ceiling | RC 86; RC 85 silently halves. 906,976 sps at MCK 78 (976,744 at the old MCK 84) |
| Multiplexer crosstalk | +/-1 code at slow tracking |
| USB, Arduino CDC | 0.8 MB/s gapless, ~0.95 MB/s ceiling |
| USB, bare-metal CDC | **1.83 MB/s gapless at full in-spec ADC rate** |
| Capture at max in-spec (MCK 78) | 453,488 Hz/ch declared, 453,489 measured, ratio 1.000 |
| Full loop, duplex | 200 ksps DAC + 400 ksps ADC. Re-taken 08-27 on current firmware, 3 runs: tone median **1368.6-1372.2** codes, **99.3%** of windows at or above the 1340 floor, 10-12 flagged overrun frames per 3 s run, 0 sequence gaps. The "+/-2 in every window" this line used to claim does not hold - the low windows are the spliced ones, which invariant 5 flags rather than hides |
| USB IN only (RT threaded host) | 5.20 MB/s |
| USB OUT only (RT threaded host) | 5.03 MB/s, matched the device counter - but read without draining the pipeline, so it could not have shown a shortfall; see docs/usb.md |
| USB duplex (RT threaded host) | 2.77 in + 2.47 out = 5.25 MB/s combined |
| **Matched loop ceiling** | **453,488 sps DAC + 906,976 sps capture, solid** (under=0, gaps=0, 1372 codes) |
| **AWG (play-only) ceiling** | **1.383 Msps solid** (RC 28, under=0, 2.81 MB/s feed); DACC saturates ~1.41 M over-triggered |
| Asymmetric loop (AWG + 200 kHz monitor) | solid to 600 ksps DAC; 650 k = 4 underruns/5 s |
| USB via endpoint DMA (playback path converted) | IN 32.0 / OUT 26.6 byte-perfect / duplex 16.95 MB/s (single runs) |
| USB endpoint DMA, **run-to-run spread** | **35-59%, not the ~5% recorded before**: five 4 s runs give IN 19.8-30.5, OUT 17.9-28.2, duplex 8.2-20.0 MB/s. Suite floors are set from the minima, not the typical figure |
| Host-fed playback, 200 ksps | **byte-exact**: `play_bytes_in` equals the host's `write()` count, 0 ramp discontinuities, 0 partial spans |
| **Full-rate pair (DAC 907 k + ADC 907 k aggregate)** | runs with **under=0** on DMA playback; purity 90-95% pending IN-side DMA and a cable swap |
| ~1.7 MB/s "gated OUT" cap | explained: DMA re-arm/service latency x transfer granularity, not FIFO interleave; removed by multi-slot spans |
| printf, 40-char line | 3600 us |

### Windows 11, second board, 2026-08-25

Measured with `tools/bench.py` and `tools/loop.py` (pyserial; `host/` is
POSIX-only). Byte figures taken after a drain; underruns with a prompt
stop. Full context and caveats in `docs/windows.md`.

| Quantity | Value |
|---|---|
| Playback byte conservation, RC 195 to RC 28 | **0 B deficit at all eight rates** (200,000 to 1,392,857 sps), design feed policy |
| Playback underruns | **`under=0`** to 1,218,750 sps; 15 (0.4%) at 1,392,857, past the stated DACC limit |
| Capture, 453,488 sps/ch x 2 ch | **2240 frames, seq 0..2239, 0 gaps, 0 dropped, 0 bad CRC**, 1.82 MB/s |
| Full loop, 453,488 sps, 1 ch | tone **1370.8 codes**; 40 ms windows 1365.8-1367.5, spread 1.5 |
| Full loop, 200,000 sps, 1 ch | tone **1370.7 codes**; windows spread **0.1** |
| USB endpoint DMA IN | 34.14 MB/s |
| USB endpoint DMA OUT | **37.58 MB/s with 0 B deficit** after a drain |
| USB endpoint DMA duplex | 18.94 in + 28.41 out = **47.35 MB/s aggregate** |
| Objective 0c close wedge | **0 in 52 cycles** across two reproducers |
| Converter rate at RC 44 and RC 39 | **1.6% slow** by the device's own `runus`, confirming the slow-converter half of objective 0i |
| GPIO set+clear pair | 138.3 ns (Track A) / 71.5 ns (Track B) |

## Next

The live objective list is in `docs/HANDOFF.md`: capture IN over
endpoint DMA, the cable swap, the second pair, the dual-DAC purity
signatures, equivalent-time reconstruction. Longer-horizon items parked
here:

1. Understand why the UOTGHS interrupt stops firing after the first
   reset. Polling works, but the cause is unknown and may bite
   elsewhere.
2. The bank-overcommit behaviour when the host stops draining, common
   to the manual `usb_cdc_write` and the IN DMA path: device counters
   read far above the wire, so flood benchmarks trust host numbers
   only. Harmless in normal operation; understand it before relying on
   device-side byte counts anywhere else.
3. Burst mode, for capture bursts above the sustainable stream rate.
4. Twelve-channel capture, now that the transport can carry full rate.
