# Phase 6c: AWG update rates, the acquisition stall, and ETS (image11)

Firmware `fw/image11/main.c` (builds a-l; the last measured is l, BUILD_ID 12). Host: `tools/h7_awg.py`
(waveforms + the swing cap), `tools/h7_awg_sweep.py` (ladder, feed, ets, etsbw), `tools/h7_ets.py`.

## Changes that matter
- **The host enforces the swing cap.** The firmware no longer reads playback codes (invariant 1 restored).
  `h7_awg.check_codes` refuses, never clamps, anything outside 2036 +- 330 codes (about +-2 V) and any
  write that is not whole 2048-byte units. Six tests; disabling the check fails three of them.
- **OUT unit is 2048 bytes** (4 packets), the update-rate floor is 40 ticks (5 MS/s, the vendor's figure),
  and a vendor request (OUT 0x7F) returns the unit to the boot loader, so a flash no longer waits for a timer.
- **The CH2 acquisition stall is fixed.** The generator start blocks the main loop for about 21 ms, i.e. about 21
  frames. The double-buffer bookkeeping chose the idle buffer by frame parity and rewrote the address of the buffer the
  DMA was filling; the DMA flagged a transfer error (`TEIF1`) and disabled itself, after which the ADC
  overran for ever. Found with a live dump of `DMA2_LISR = 0x600`, `S1CR` EN clear, and bisected: PE3 alone does not
  stall; the generator chain with PE3 held low does. Now the idle buffer is taken from the DMA's current-target bit and
  frames skipped by a long block are counted as lost and flagged (about 19-20 per generator start, none in a run).
- **Three harness faults that looked like hardware, all found and fixed:** a writer thread starving the reader (use a
  separate process, killed with its parent), not draining the acquisition stream while setup probes ran (the host
  stops polling the IN endpoint and the ring overflows), and an orphaned writer from a timed-out run holding the port.
  Something on the host also opens a new port for a while after enumeration (ModemManager, probably); the
  harness waits until the acquisition start counter has been still for 12 s.

## Update-rate ladder (10 kHz, 300-code sine; observer CH2 at 2 Msps; linux-x1, 2026-11-02)
| update rate | rate ratio | underruns | amp / ideal | THD % | residual mV |
|---|---|---|---|---|---|
| 0.25 MS/s | 0.99989 | 0 | 0.988 | 0.26 | 44.0 |
| 0.50 | 1.00018 | 0 | 0.991 | 0.20 | 38.4 |
| 1.00 | 1.00013 | 0 | 0.992 | 0.15 | 38.3 |
| 2.00 | 1.00052 | 0 | 0.992 | 0.15 | 38.6 |
| 2.50 | 1.00007 | 0 | 0.991 | 0.14 | 38.7 |
| 4.00 | 1.00025 | 0 | 0.992 | 0.15 | 39.2 |
| 5.00 | 1.00024 | 0 | 0.992 | 0.14 | 39.4 |
"Rate ratio" is samples consumed per second of host wall time over the programmed rate (device counter; the
host clock limits it to about 0.05 %). The USB feed alone (acquisition off) also holds 5 MS/s with no underruns and
at least 1555 samples buffered. Verified: the DAC is triggered and fed at every rate, and the 10 kHz output is
right in amplitude (0.9 % low everywhere) with 0.14-0.26 % THD. Not verified by this table: whether each
200 ns step settles; the 2 Msps observer cannot see it, and the next two sections are why that matters.

## ETS (`h7_ets.py`)
Both timers count the same 200 MHz base. A waveform that repeats every W = points x update_ticks ticks, sampled
every P_a ticks (P_a/g coprime to W/g), is sampled at phases (k P_a) mod W; the host bins them in g-tick bins
and rebuilds one cycle at g x 5 ns (g = 8: 40 ns). The unknown constant shift (timer start offset plus
ADC delay) is removed by aligning to the expected waveform. A capture with a gap in the frame sequence numbers
is cut to its longest gapless run. Tests: six, each mutation (phase formula, coprime search) fails one or more.
Needs numpy: run them with `.venv-gui`; under `.venv` they skip, and a skip is not a pass.
- **Self-consistency, 100 kHz square, +-150 codes, 5 MS/s update, 4 s:** P_a = 104 ticks (1.923 Msps),
  136 ticks and 105 ticks (off the 8-tick grid) gave the same waveform: low -0.70 V, high +0.78 V, 10-90 %
  edge 960 ns, overshoot 1.6-1.7 %, about 31,000 samples per 40 ns bin. Agreement across ADC periods says
  the reconstruction does not depend on a timing assumption that failed.
- **10 kHz sine at 5 MS/s** rebuilt: rms 38 mV from the ideal staircase.

## The AWG's analog bandwidth
Frequency response of DAC + output stage + CH2, 100-code sine, 5 MS/s update, ETS, three seconds per row:
| f kHz | points/cycle | amp V (0.598 ideal) | dB | THD % |
|---|---|---|---|---|
| 10 | 500 | 0.595 | -0.04 | 0.60 |
| 50 | 100 | 0.519 | -1.23 | 0.34 |
| 100 | 50 | 0.386 | -3.81 | 0.66 |
| 200 | 25 | 0.231 | -8.27 | 1.21 |
| 250 | 20 | 0.184 | -10.25 | 2.14 |
| 500 | 10 | 0.078 | -17.71 | 1.48 |
| 1000 | 5 | 0.024 | -27.80 | not meaningful |
The observer was checked separately with the Due DAC (1 MS/s, flat to 100 kHz apart from its own hold)
as the source into H7 **CH1** (CH2 assumed the same; they share a design): relative to 10 kHz it reads
-0.17 dB at 100 kHz and -1.61 dB at 200 kHz, against -0.14 and -0.58 expected from the Due's hold alone,
with about +-0.4 dB scatter. So the observer is within about 1 dB to 200 kHz and the roll-off above is the
generator: **-3 dB near 85 kHz** *(derived from the two measurements, +-0.5 dB, CH1/CH2 assumed alike)*, roughly a
single pole to 500 kHz. It is also why the 100 kHz square reached only 82 % of its swing.

## What it means for the AWG, and what is open
- Above about 1 MS/s the update rate no longer improves the output (THD flat at 0.14-0.15 %, bandwidth set by
  the stage); 5 MS/s is delivered and correct as a feed, but buys nothing at the output.
- The stage, not the converter, sets maximum frequency: a sine is within 1.2 dB to 50 kHz and 3.8 dB at 100 kHz.
- Open: absolute amplitude and level accuracy against a reference instrument (CH1/CH2 and the DAC volts
  are the H7 reading itself); whether the stage's roll-off is the op-amp or a filter fitted on this board (the
  schematic D268-5 is available); step settling at small amplitude; amplitudes above +-2 V; the 0-20 mA output.
