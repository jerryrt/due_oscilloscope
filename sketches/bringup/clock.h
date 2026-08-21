/*
 * Master clock selection.
 *
 * The Due's 12 MHz crystal and datasheet Table 46-22 pin the options
 * down hard: FIN must be 8-16 MHz, so with a 12 MHz crystal DIVA can
 * only be 1, and PLLA = 12 MHz x (MULA+1) must land in 96-192 MHz. With
 * the master clock prescaler at /2 that leaves MCK as a multiple of 6:
 *
 *   MULA  PLLA     MCK    ADC clk (PRESCAL=1, /4)
 *   ----  -------  -----  -----------------------
 *     12  156 MHz  78     19.5 MHz   in spec
 *     13  168 MHz  84     21.0 MHz   5% over the 20 MHz maximum
 *     14  180 MHz  90     22.5 MHz   12.5% over, and MCK over the
 *                                    core's rated 84 MHz
 *
 * 80 MHz, which would give exactly 20.0 MHz, is unreachable: it needs
 * DIVA=3 and an FIN of 4 MHz, below the 8 MHz minimum.
 *
 * This project runs at MULA=12 so the ADC clock stays inside spec. See
 * docs/hardware.md.
 */

#ifndef CLOCK_H
#define CLOCK_H

#include <stdint.h>

#define MCK_MULA_78   12u
#define MCK_MULA_84   13u
#define MCK_MULA_90   14u

#define MCK_MULA_DEFAULT MCK_MULA_78

bool     clock_set_mck(uint32_t mula);
uint32_t clock_plla_hz(uint32_t mula);

#endif /* CLOCK_H */
