#include <Arduino.h>
#include <math.h>
#include "acq.h"
#include "gen.h"

/* DAC1 held at mid scale; A1 should read a flat ~1.65 V equivalent. */
#define DC_CODE  2048u

static uint16_t gen_table[GEN_TABLE_LEN];
volatile uint32_t gen_endtx_count;

static void build_table(void)
{
	for (unsigned i = 0; i < GEN_SINE_POINTS; i++) {
		double phase = (2.0 * M_PI * i) / GEN_SINE_POINTS;
		/* Full-scale sine centred in the 12-bit range. */
		uint16_t s = (uint16_t)(2047.5 + 2047.0 * sin(phase));

		gen_table[2 * i]     = (uint16_t)((0u << 12) | (s & 0x0fffu));
		gen_table[2 * i + 1] = (uint16_t)((1u << 12) | DC_CODE);
	}
}

uint32_t gen_sine_hz(uint32_t trigger_hz)
{
	return trigger_hz / GEN_TABLE_LEN;
}

void gen_init(void)
{
	build_table();

	PMC->PMC_PCER1 = (1u << (ID_DACC - 32));
	DACC->DACC_CR = DACC_CR_SWRST;

	DACC->DACC_MR = DACC_MR_TAG
	              | DACC_MR_REFRESH(1)
	              | (0x10u << DACC_MR_STARTUP_Pos)
	              | DACC_MR_MAXS;

	DACC->DACC_CHER = DACC_CHER_CH0 | DACC_CHER_CH1;
}

void gen_start(void)
{
	gen_stop();
	gen_endtx_count = 0;

	DACC->DACC_TPR  = (uint32_t)gen_table;
	DACC->DACC_TCR  = GEN_TABLE_LEN;
	DACC->DACC_TNPR = (uint32_t)gen_table;
	DACC->DACC_TNCR = GEN_TABLE_LEN;

	(void)DACC->DACC_ISR;
	DACC->DACC_IDR = 0xffffffff;
	DACC->DACC_IER = DACC_IER_ENDTX;

	NVIC_ClearPendingIRQ(DACC_IRQn);
	NVIC_SetPriority(DACC_IRQn, 1);       /* below the ADC handler */
	NVIC_EnableIRQ(DACC_IRQn);

	DACC->DACC_PTCR = DACC_PTCR_TXTEN;

	/* Trigger last, so nothing is emitted until the PDC is armed. */
	DACC->DACC_MR |= DACC_MR_TRGEN | TRGSEL_TIOA0;
}

void gen_stop(void)
{
	DACC->DACC_MR &= ~(DACC_MR_TRGEN | DACC_MR_TRGSEL_Msk);
	DACC->DACC_PTCR = DACC_PTCR_TXTDIS;
	DACC->DACC_IDR = 0xffffffff;
	NVIC_DisableIRQ(DACC_IRQn);
}

/*
 * Re-arm the next-pointer at the same table, so playback loops forever
 * with no CPU involvement beyond two register writes per table pass.
 */
void DACC_Handler(void)
{
	if (DACC->DACC_ISR & DACC_ISR_ENDTX) {
		DACC->DACC_TNPR = (uint32_t)gen_table;
		DACC->DACC_TNCR = GEN_TABLE_LEN;
		gen_endtx_count++;
	}
}
