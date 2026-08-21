#ifndef GEN_H
#define GEN_H
#include <stdint.h>

/*
 * DAC playback driven by the same TIOA0 that triggers the ADC, so
 * generation and capture are phase-coherent by construction.
 *
 * DACC TAG mode: bits [13:12] of each half-word select the channel, so
 * one PDC stream feeds both DACs. The table interleaves a sine for DAC0
 * with a fixed DC level for DAC1. Each channel therefore updates every
 * other trigger, and the DC channel doubles as a demux check: if the
 * host ever shows a sine on A1, the channel tags are being read wrong.
 */
#define GEN_SINE_POINTS   256
#define GEN_TABLE_LEN     (GEN_SINE_POINTS * 2)   /* interleaved */

void     gen_init(void);
void     gen_start(void);
void     gen_stop(void);
uint32_t gen_sine_hz(uint32_t trigger_hz);        /* trigger_hz / GEN_TABLE_LEN */

extern volatile uint32_t gen_endtx_count;

#endif /* GEN_H */
