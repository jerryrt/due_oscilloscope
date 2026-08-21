/*
 * Master clock selection. See sketches/bringup/clock.h and
 * docs/hardware.md for why MULA=12 (78 MHz) is the operating point:
 * it is the only reachable setting that keeps the ADC clock inside its
 * 20 MHz datasheet limit.
 */
#ifndef CLOCK_H
#define CLOCK_H
#include <stdint.h>
#include <stdbool.h>

#define MCK_MULA_78   12u
#define MCK_MULA_84   13u
#define MCK_MULA_90   14u
#define MCK_MULA_DEFAULT MCK_MULA_78

bool clock_set_mck(uint32_t mula);
#endif
