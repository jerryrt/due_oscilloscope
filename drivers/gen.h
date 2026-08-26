#ifndef GEN_H
#define GEN_H
#include <stdint.h>

#define GEN_SINE_POINTS 256
#define GEN_TABLE_LEN   (GEN_SINE_POINTS * 2)

/*
 * What build_table() puts on each DAC, selected at runtime.
 *
 * One image and one code path for every arm, because the binary selects
 * which state issue #5 draws: two builds would change the layout as
 * well as the waveform, and an absent artifact in the second arm could
 * not be read. The table lives in RAM and is rebuilt by gen_init(),
 * which the M preset calls before every capture, so this costs nothing
 * but a branch.
 *
 * NORMAL     sine on DAC0, DC on DAC1 - what this project has always run
 * SWAPPED    DC on DAC0, sine on DAC1 - is it DAC1, or a DAC pin?
 * TWOCYCLE   two sine periods in the same table - separates the PDC
 *            reload at the wrap from the waveform, which have been the
 *            same event in every build so far
 * DC         no sine anywhere - is a swinging output needed at all?
 *
 * Every arm keeps DAC0 on even slots and DAC1 on odd, so a swap moves
 * the values and not the update timing.
 */
#define GEN_LAYOUT_NORMAL    0u
#define GEN_LAYOUT_SWAPPED   1u
#define GEN_LAYOUT_TWOCYCLE  2u
#define GEN_LAYOUT_DC        3u

extern uint8_t gen_layout;
void gen_set_layout(uint32_t layout);

void     gen_init(void);
void     gen_start(void);
void     gen_prepare_tioa1(uint32_t dac_hz);  /* DACC + TC1 config, clock off */
void     gen_go_tioa1(void);                  /* start the TC1 clock */
void     gen_stop(void);
uint32_t gen_sine_hz(uint32_t trigger_hz);

extern volatile uint32_t gen_endtx_count;

void gen_endtx(void);   /* dispatched from DACC_Handler */
#endif
