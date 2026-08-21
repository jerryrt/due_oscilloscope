/*
 * ADC, software-triggered single conversions.
 *
 * Deliberately configured for accuracy rather than speed here: maximum
 * tracking and settling time. This is a DC test, throughput is
 * irrelevant, and generous tracking keeps multiplexer crosstalk out of
 * the baseline measurement so that wiring faults are unambiguous.
 *
 * The fast configuration, where TRACKTIM is traded against crosstalk,
 * belongs with the TC-triggered PDC path.
 */

#include "sam.h"
#include "analog.h"

void adc_init(void)
{
	/* ID_ADC is 37, so it lives in PCER1 at bit (37 - 32). */
	PMC->PMC_PCER1 = (1u << (ID_ADC - 32));

	ADC->ADC_CR = ADC_CR_SWRST;

	/* ADCClock = MCK / ((PRESCAL + 1) * 2) = 84 MHz / 4 = 21 MHz,
	 * just under the ~22 MHz maximum. */
	ADC->ADC_MR = ADC_MR_PRESCAL(1)
	            | (0xfu << ADC_MR_STARTUP_Pos)
	            | ADC_MR_TRACKTIM(15)
	            | (3u << ADC_MR_SETTLING_Pos)
	            | (2u << ADC_MR_TRANSFER_Pos);

	/* Channel index in LCDR[15:12]: free, and makes the stream
	 * self-describing once the PDC path exists. */
	ADC->ADC_EMR = ADC_EMR_TAG;

	ADC->ADC_CHDR = 0xffffu;
}

uint16_t adc_read(unsigned ch)
{
	ADC->ADC_CHDR = 0xffffu;
	ADC->ADC_CHER = (1u << ch);

	ADC->ADC_CR = ADC_CR_START;
	while (!(ADC->ADC_ISR & (1u << ch)))
		{ }

	return (uint16_t)(ADC->ADC_CDR[ch] & 0x0fffu);
}

/*
 * Both channels from one trigger. The sequencer converts every enabled
 * channel per trigger event, in ascending channel index order, so this
 * is the same ordering the PDC path will see.
 */
void adc_read_pair(unsigned cha, unsigned chb, uint16_t *a, uint16_t *b)
{
	uint32_t mask = (1u << cha) | (1u << chb);

	ADC->ADC_CHDR = 0xffffu;
	ADC->ADC_CHER = mask;

	ADC->ADC_CR = ADC_CR_START;
	while ((ADC->ADC_ISR & mask) != mask)
		{ }

	*a = (uint16_t)(ADC->ADC_CDR[cha] & 0x0fffu);
	*b = (uint16_t)(ADC->ADC_CDR[chb] & 0x0fffu);
}
