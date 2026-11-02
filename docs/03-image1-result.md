# 03 - Image 1 result (2026-11-01, bench linux-x1)

Images: `fw/image1/main.c`, two builds of it (arm-none-eabi-gcc 14.2.1 from the host, not a container).
Both pass `scripts/check_image.py`; reset vector 0x0802001b, SP 0x20020000.

| build | size | behaviour intended |
|---|---|---|
| image1.bin | 164 B | PI8 (run LED, low = on) toggles; no other peripheral |
| image1b.bin | 224 B | same, plus a ~0.1 s pulse of PG1 (buzzer, high = on) each cycle |

## Observed
- Flash path works: both images written through the stock boot loader (0.9 s), the unit left the boot loader about 1 s later and did not re-enumerate (the images have no USB).
- Stock V2.33 restored the same way (14.0 s); afterwards identity, version, board, boot registers and all 16 calibration blocks read back identical to `../h7tool_backup/device_dump`, TVCC set value 1400 mV. Due A0 is back at 1698 codes.
- With image 1 running the Due's A0 read 0.0 codes (TVCC off); with stock it read 1696.1 (TVCC measured 1.376 V). TVCC off cannot tell a dead unit from a running one.
- **No LED activity and no beep were seen with either image** (reported by the owner; the second after a power cycle).

## Not established
Whether our code ran at all. Candidates, none tested: wrong pin or polarity on this board revision (D428-9; the pin map is from D253-6 and the public source); a wrong clock-enable bit or base address in `main.c` (checked by eye against the address map only); a hardware watchdog reset loop; a power domain (e.g. the display board LED supply) that stock enables and we do not.

## Incident
The first recovery attempt failed because the wrong key was pressed, not because of the image.
