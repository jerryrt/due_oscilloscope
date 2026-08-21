/*
 * DACC in TAG mode.
 *
 * TAG mode puts the channel select in bits [13:12] of each written
 * half-word, so a single write stream can drive both DAC channels. That
 * is exactly how the PDC path will work later, so using it here means
 * the DMA version is not the first time the mode is exercised.
 *
 * Output is NOT rail to rail: roughly 1/6 to 5/6 of ADVREF, about
 * 0.55 V to 2.75 V. Measuring the true endpoints on this board is the
 * point of the sweep command.
 */

#include "sam.h"
#include "analog.h"

void dac_init(void)
{
	/* ID_DACC is 38, so it lives in PCER1 at bit (38 - 32). */
	PMC->PMC_PCER1 = (1u << (ID_DACC - 32));

	DACC->DACC_CR = DACC_CR_SWRST;

	DACC->DACC_MR = DACC_MR_TAG                       /* channel from data[13:12] */
	              | DACC_MR_REFRESH(1)
	              | (0x10u << DACC_MR_STARTUP_Pos)
	              | DACC_MR_MAXS;

	DACC->DACC_CHER = DACC_CHER_CH0 | DACC_CHER_CH1;
}

void dac_write(unsigned ch, uint16_t code12)
{
	while (!(DACC->DACC_ISR & DACC_ISR_TXRDY))
		{ }

	DACC->DACC_CDR = ((uint32_t)(ch & 1u) << 12) | (code12 & 0x0fffu);
}
