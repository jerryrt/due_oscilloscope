/*
 * DAC and ADC access for the loopback bring-up.
 *
 * Software-triggered and polled. The TC-triggered, PDC-driven path comes
 * later; this exists to prove the wiring and to measure this board's
 * actual DAC endpoints, which are a Phase 1 deliverable.
 *
 * Loopback wiring:  DAC0 -> A0,  DAC1 -> A1
 *
 * A2 carries no DAC. It was the impedance arm of the issue #5 rig on
 * 2026-08-26 - two equal resistors between 3.3 V and GND with the tap on
 * the pin, swept 50 ohm to 5.5k against A1 at the same voltage behind a
 * DAC output, which is what made the pair a matched comparison.
 *
 * **The rig was removed when the sweep ended and A2 is disconnected.**
 * ADC_CH_A2 and the three-channel capture path stay, because the next
 * impedance question will want them and they cost nothing idle.
 */

#ifndef ANALOG_H
#define ANALOG_H

#include <stdint.h>

/*
 * Arduino's A0..A7 labels map to ADC channels in DESCENDING order. Code
 * that assumes A0 == AD0 reads the wrong pin.
 *
 *   A0 = PA16 = AD7      A4 = PA6  = AD3      A8  = PB17 = AD10
 *   A1 = PA24 = AD6      A5 = PA4  = AD2      A9  = PB18 = AD11
 *   A2 = PA23 = AD5      A6 = PA3  = AD1      A10 = PB19 = AD12
 *   A3 = PA22 = AD4      A7 = PA2  = AD0      A11 = PB20 = AD13
 */
#define ADC_CH_A0  7u
#define ADC_CH_A1  6u
#define ADC_CH_A2  5u

void     dac_init(void);
void     dac_write(unsigned ch, uint16_t code12);   /* ch 0 or 1 */

void     adc_init(void);
uint16_t adc_read(unsigned ch);                     /* one channel */
void     adc_read_pair(unsigned cha, unsigned chb,
                       uint16_t *a, uint16_t *b);   /* one sequence */

/* 12-bit code to millivolts against a 3.3 V reference. */
static inline uint32_t code_to_mv(uint16_t code)
{
	return ((uint32_t)code * 3300u) / 4095u;
}

#endif /* ANALOG_H */
