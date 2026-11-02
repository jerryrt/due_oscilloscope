# Measurement scripts

Every script here produced, or reproduces, a figure quoted in `../docs/`. They are bench scripts kept as they were
run (hence the plain style); each starts with a docstring naming what it measured, the document that quotes it and
the wiring and image it needs. The shared, tested pieces live in `../tools/` (`h7_ets.py`, `h7_metrics.py`,
`h7_awg.py`, `h7_awg_sweep.py`, `h7_stream_check.py`, `h7_usb_probe.py`).

| script | figure it backs | wiring it needs |
|---|---|---|
| `dc_accuracy_vs_adc_clock.py` | docs/10, DC accuracy per ADC clock | Due DAC0 -> CH1 |
| `coupling_check.py`, `gain_table.py` | docs/12 | Due DAC0 -> CH1, DAC1 -> CH2 |
| `two_channel_dac_check.py` | docs/11 | Due DAC0 -> CH1, DAC1 -> CH2 |
| `vout_sine_and_square.py` | docs/13 (first, coarse) | VOUT -> CH2 |
| `playback_controls.py` | docs/14 | VOUT -> CH2, image10a |
| `observer_bandwidth_due.py` | docs/15 | Due DAC0 -> CH1 |
| `stall_repro*.py` | docs/15 (the fixed stall) | VOUT -> CH2, image11h-k |
| `../tools/h7_awg_sweep.py` (`ladder feed etsrate etsbw etsamp large`) | docs/14, 15, 16 | VOUT -> CH1 or CH2 (`H7_OBS`) |

Wiring has changed during this work (Due and VOUT on CH1/CH2 at different times); the Due is now disconnected from
the H7, so the scripts that need it cannot be re-run as they stand.

Not kept: the PE3 / generator-chain bisect script (`bisect.py`) was removed from the scratch directory when it was found
shadowing the standard `bisect` module; its result (PE3 alone does not stall the acquisition, the generator chain with
PE3 held low does) is recorded in docs/15 and in the commit that fixed the stall. Debug one-offs (`live.py`, `one.py`,
`probe1.py`, ...) were not kept.
