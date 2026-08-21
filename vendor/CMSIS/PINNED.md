# Pinned vendor sources

Copied from `arduino:sam@1.6.12`, installed via arduino-cli on
2026-08-20. Pinned rather than referenced in place: a core update would
otherwise silently change the register definitions the firmware is built
against.

| Path | Origin |
|---|---|
| `Include/` | `system/CMSIS/CMSIS/Include/` |
| `Device/ATMEL/sam3xa/include/` | same path under `system/CMSIS/` |
| `Device/ATMEL/sam3xa/source/system_sam3xa.c` | same |

`SystemInit()` in `system_sam3xa.c` performs the clock bring-up this
project relies on: 12 MHz crystal, PLLA multiplier 14, divider 1, then
`PMC_MCKR_PRES_CLK_2`, giving MCK = 84 MHz. It also sets
`SystemCoreClock` to `CHIP_FREQ_CPU_MAX`.

Licence: Atmel/Microchip and ARM CMSIS terms as stated in the file
headers. Unmodified.
