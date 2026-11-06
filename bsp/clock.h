/*
 * Master clock selection. The project runs MULA=14 (MCK 90 MHz), which
 * is out of specification; see sketches/bringup/clock.h and
 * docs/hardware.md.
 */
#ifndef CLOCK_H
#define CLOCK_H
#include <stdint.h>
#include <stdbool.h>

#define MCK_MULA_90   14u
/* The operating point, set by CMake from FIRMWARE_MCK_HZ. */
#ifndef MCK_MULA_DEFAULT
#define MCK_MULA_DEFAULT MCK_MULA_90
#endif

bool clock_set_mck(uint32_t mula);
#endif
