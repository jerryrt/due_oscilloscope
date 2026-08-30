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
#include <stdbool.h>

#include "ctl_wire.h"   /* ctl_temp_t: the temperature report is a wire format */
#include "frame.h"      /* FRAME_CH_*: the channel tags are wire contract */

/*
 * The tag values are wire contract and live in frame.h, which carries
 * the A-label-to-AD-channel table explaining why they are 7, 6 and 5.
 * These are this track's spelling of them.
 */
#define ADC_CH_A0  FRAME_CH_A0
#define ADC_CH_A1  FRAME_CH_A1
#define ADC_CH_A2  FRAME_CH_A2

void     dac_init(void);
void     dac_write(unsigned ch, uint16_t code12);   /* ch 0 or 1 */

void     adc_init(void);
uint16_t adc_read(unsigned ch);                     /* one channel */

/*
 * The on-die temperature sensor, ADC channel 15 behind ADC_ACR.TSON.
 * Averages `samples` conversions (clamped to the CTL_TEMP_SAMPLES_*
 * range) and restores whatever channels were enabled. Returns CTL_TEMP_OK,
 * CTL_TEMP_UNSUPPORTED or CTL_TEMP_BUSY - see ctl_port.h. Refused while
 * the ADC is hardware-triggered, because switching channels under a
 * running capture would corrupt it.
 *
 * ctl_temp_t carries what the reading may and may not be used to claim -
 * read it before quoting a number from here. Issue #11.
 */
int      adc_read_temp(ctl_temp_t *out, uint16_t samples);
/*
 * Measurement conditions for a polled reading: maximum tracking and
 * settling, set rather than inherited, and restored by the matching
 * _end. Returns -1 and changes nothing if a capture is running or a
 * measurement is already open.
 *
 * Issue #16: `x` inherited whatever last wrote ADC_MR, which was
 * TRACKTIM 0 on one track and 15 on the other, and that was worth a
 * sign flip and a factor of four on the same board. Tracking time is
 * the dominant term for multiplexer bleed, so a bleed figure taken at
 * an inherited tracking time is a figure about the previous command.
 * Same argument as adc_read_temp(); see adc.c.
 */
int      adc_measure_begin(void);
void     adc_measure_end(void);

void     adc_read_pair(unsigned cha, unsigned chb,
                       uint16_t *a, uint16_t *b);   /* one sequence */
extern volatile uint32_t adc_pair_restarts;  /* issue #23: STARTs re-kicked */
extern volatile uint32_t adc_pair_timeouts;  /* pairs abandoned incomplete */

/* 12-bit code to millivolts against a 3.3 V reference. */
static inline uint32_t code_to_mv(uint16_t code)
{
	return ((uint32_t)code * 3300u) / 4095u;
}

#endif /* ANALOG_H */
