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
/*
 * The playback configuration with gen's data source: DACC triggered by
 * TIOA1 and playing the flash sine table, no USB involved. Config and
 * start are split so the caller can reproduce the full loop's ordering
 * - DACC and timer first, capture second, clock last - which is what
 * makes the mimic command a control for the USB path.
 */
void     gen_prepare_tioa1(uint32_t dac_hz);  /* DACC + TC1 config, clock off */
void     gen_go_tioa1(void);                  /* start the TC1 clock */
/*
 * Drive the DACC from TC0 channel 1 (TIOA1) instead of the ADC's TIOA0,
 * so the DAC update rate can be swept independently of acquisition.
 */
bool     gen_start_independent(uint32_t dac_hz);
uint32_t gen_configured_rc(void);
void     gen_stop(void);
uint32_t gen_sine_hz(uint32_t trigger_hz);        /* trigger_hz / GEN_TABLE_LEN */

extern volatile uint32_t gen_endtx_count;

/*
 * Dispatched from the single DACC_Handler, which play.cpp owns: two
 * modules want the end-of-transmit event and only one can own the
 * vector, so the owner dispatches on which source is active.
 */
void     gen_endtx(void);

#endif /* GEN_H */
