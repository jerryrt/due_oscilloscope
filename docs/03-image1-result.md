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

## Update: the beep works (image1c.bin)
The stock V2.33 firmware beeps once at boot, so its buzzer code was located in the disassembly
(`arm-none-eabi-objdump -b binary -m arm -M force-thumb -D --adjust-vma=0x08020000`; the image builds
peripheral addresses with movw/movt pairs, so a search for 32-bit address words finds nothing).

- Beep start/stop at 0x0802b6e0..0x0802b8c4, state struct at 0x24020cd4 (g_tBeep).
- Pin depends on a flag byte at 0x240279b8: flag set -> **PH9** (GPIOH BSRR 0x58021c18, bit 9 on), clear -> PG1 (GPIOG BSRR).
- The flag is set by the function at 0x08096818: ID word masked with ~0xF equal to 0x4200, 0x4280 or 0x4460 sets it.
  This unit's board register 0xFF60 reads 0x4289, which masks to 0x4280, so the flag is 1 and the buzzer is on PH9.
- image1c.bin (pulses PH9, PG1 and PI8; GPIOG/H/I clocks enabled in RCC_AHB4ENR) was flashed from stock via
  FC6 0xFF7F=2 and the owner heard the beep. **First confirmed sign of our code running on this unit.**
- Which of the three pins sounded was not separated (all three were driven together); the stock code points at PH9.
- The LED on PI8 was not reported. Stock restored again and verified (identity, version, board, boot, 16 calibration blocks, TVCC 1400 mV).

## Update: TVCC control and the self-timed return to the boot loader (fw/image2)
Stock reading (V2.33 disassembly, board 0x4289 => hardware flag set):
- set_tvcc_mv(mv) at 0x0809a0f0: mv==0 -> PC13 low (TVCC off). Otherwise code = calibration fit of the requested voltage
  (function 0x0802d990 with this unit's 0xC0C0.. table), clamped to 127; code written to the pot (0x08058ac0), then PC13 high.
- Pot write 0x08058ac0: I2C start, address byte 0x5E, ack, code byte, ack, stop. Soft I2C pins as in the public source:
  SCL PI7 (BSRR set 0x80 / reset 0x800000 on GPIOI), SDA PF15 (0x8000 / 0x80000000 on GPIOF). So these pins hold on D428-9.
- Linear fit on this unit: V = 1.1922 + 0.030731 * code (code 5 -> 1.3457 V, code 100 -> 4.2652 V).

Result: fw/image2 (-DTEST_TVCC -DRUN_MS=20000) writes the pot with PC13 low, enables TVCC only after both bytes were ACKed,
code 7 (clamped to 5..20). The Due's A0 read **1737.1 codes = 1.409 V** (sd 2.5) for the whole 20 s; the formula gives 1.407 V.
TVCC off afterwards (A0 0.0). First confirmed hardware control from our own firmware.

Self-timed return: after RUN_MS the image drives PC13 low, writes 0x5AA51234 to 0x20000000, DSB, SYSRESETREQ.
The boot loader came back with no key press, both with image2a (peripheral-free, 8 s) and image2b. The unit leaves USB
~1 s after the write but only starts the new app about 6-7 s later (the loader's own delay), so budget for it.
`scripts/h7_cycle.sh <image.bin>` enters the boot loader from stock and flashes; stock is restored afterwards with
h7_bl_flash.py and verified (identity, version, board, boot, 16 calibration blocks, TVCC 1400 mV: all identical).

## Update: USB core and ULPI PHY bring-up from our own image (fw/image3, step 1)
`image3a.bin` (1,048 bytes, polling, no interrupts, clocks left at reset HSI 64 MHz, no PLL, stock register sequence from
docs/04) enables the 12 ULPI pins (AF10), the OTG_HS and ULPI clocks, resets the core, forces device mode, sets the FIFO layout,
soft-connects, and handles only bus reset and enumeration-done. It answers no control transfers. Returns to the boot loader after 15 s.

Host (dmesg, linux-x1): `new high-speed USB device number 123 using xhci_hcd`, then
`device descriptor read/64, error -110` and `-71`, then the loader reappears. So the PHY, the ULPI wiring, the core and the
high-speed chirp all work from our code with **no PLL**; only the control endpoint is unanswered, as intended.
Stock is NOT on the unit at the moment of this note: restore it with h7_bl_flash.py.
