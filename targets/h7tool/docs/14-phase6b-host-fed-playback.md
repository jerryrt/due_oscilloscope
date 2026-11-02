# Phase 6b: host-fed playback (image10a)

The host writes DAC codes (halfwords, 12-bit right-aligned) to the stream
port. Each 512-byte packet is one OUT transfer by DMA into the next unit of a
32 KiB ring (64 units of 256 samples) in D2 SRAM at 0x30038000; the DAC drains
the ring through TIM6 and DMA1 stream 5, circular. Start with vendor OUT 0x23
(prime units; 0 stops), counters IN 0x07 (`h7_usb_probe.py pstart|pstop|play`);
the update rate is the generator's TIM6 period (`gperiod`).
- **Back-pressure, not loss:** a unit is armed only while the ring has room, so a
  full ring NAKs the host. Short packets (host writes not a multiple of 512
  bytes) are counted and dropped.
- **Prime and underrun:** TIM6 starts only when `prime` units are buffered and
  stops (the DAC holds its last value) when occupancy falls below 16 samples;
  each stop counts one underrun. This is the lesson CLAUDE.md records for the Due
  (`PLAY_PRIME_BUFS`), built in from the start.
- **PLAY_GUARD (debug only, on):** the CPU reads every arriving code and refuses
  the stream, stopping the output, if one lies outside the +-330-code swing cap.
  This breaks invariant 1 on purpose, because the stage reaches +-10 V; it goes
  when the owner raises the cap or the host enforces it.
- Disabling an OUT endpoint needs global OUT NAK first (`SGONAK`, wait
  `GONAKEFF`, `EPDIS`); the first version did not do that.

## Measured, linux-x1, 2026-11-02 (VOUT wired to CH2, `h7_play_check.py`)
- 5 s, 1 kHz sine, 300 codes, 250 kS/s: the device took 5193 units and consumed
  1,313,408 samples; written minus consumed equals the reported occupancy
  (16,000 samples), so nothing was lost; underruns 0, guard trips 0, short
  packets 0, minimum occupancy 1017 (the prime). CH2 reads the fundamental at
  1.800 V (ideal 1.795), mean +0.061 V, residual about 32 mV rms, which is
  the scale of CH2's own noise.
- Control 1 (writer paused for 1 s): underruns 1, resumes 2, minimum occupancy
  15, then playback recovers on its own. The counter can fire.
- Control 2 (one code of 3000 in the stream): guard trips 1 after three units
  were accepted, output stopped (on 0), PE3 low, DAC parked at 2036. The guard
  can fire.

## Not covered
Rates above 500 kS/s and amplitudes above +-2 V (both refused by firmware
until the owner decides), long-duration byte conservation against a reference
count, the DAC's own sample-rate and the stage's bandwidth limits, and
simultaneous acquisition and playback beyond this test (it ran 2.5 Msps CH2
acquisition alongside).
