#ifndef GEN_H
#define GEN_H
#include <stdint.h>

#define GEN_SINE_POINTS 256
#define GEN_TABLE_LEN   (GEN_SINE_POINTS * 2)

void     gen_init(void);
void     gen_start(void);
void     gen_prepare_tioa1(uint32_t dac_hz);  /* DACC + TC1 config, clock off */
void     gen_go_tioa1(void);                  /* start the TC1 clock */
void     gen_stop(void);
uint32_t gen_sine_hz(uint32_t trigger_hz);

extern volatile uint32_t gen_endtx_count;

void gen_endtx(void);   /* dispatched from DACC_Handler */
#endif
