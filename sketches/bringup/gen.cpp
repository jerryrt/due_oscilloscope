#include <Arduino.h>
#include <math.h>
#include "acq.h"
#include "gen.h"

#define TRGSEL_TIOA1 (2u << 1)   /* DACC_MR.TRGSEL: 2 = TIOA1 */

static uint32_t dac_rc;

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

uint32_t gen_configured_rc(void)
{
	return dac_rc;
}

/*
 * Independent DAC timebase on TC0 channel 1.
 *
 * In TAG mode each trigger converts exactly one sample, whichever
 * channel its tag names, so DAC conversions per second equals the
 * trigger rate. One ENDTX marks a whole table pass, which makes the
 * achieved rate directly countable: table length times ENDTX count over
 * elapsed time. That is the same technique used to find the ADC ceiling,
 * and it needs no help from the capture path.
 */
bool gen_start_independent(uint32_t dac_hz)
{
	uint32_t tc_clock = SystemCoreClock / 2u;

	if (dac_hz == 0)
		return false;
	dac_rc = tc_clock / dac_hz;
	if (dac_rc < 2u)
		return false;

	gen_stop();
	gen_endtx_count = 0;

	/* Each TC channel has its own peripheral ID: ID_TC0 is TC0 channel
	 * 0, ID_TC1 is TC0 channel 1. Clocking only ID_TC0 leaves channel 1
	 * dead, and TIOA1 never toggles. */
	PMC->PMC_PCER0 = (1u << ID_TC1);
	TC0->TC_CHANNEL[1].TC_CCR = TC_CCR_CLKDIS;
	TC0->TC_CHANNEL[1].TC_IDR = 0xffffffff;
	TC0->TC_CHANNEL[1].TC_CMR = TCCLKS_TIMER_CLOCK1
	                          | TC_CMR_WAVE
	                          | WAVSEL_UP_RC
	                          | ACPA_CLEAR
	                          | ACPC_SET;
	TC0->TC_CHANNEL[1].TC_RA = dac_rc / 2u;
	TC0->TC_CHANNEL[1].TC_RC = dac_rc;

	DACC->DACC_TPR  = (uint32_t)gen_table;
	DACC->DACC_TCR  = GEN_TABLE_LEN;
	DACC->DACC_TNPR = (uint32_t)gen_table;
	DACC->DACC_TNCR = GEN_TABLE_LEN;

	(void)DACC->DACC_ISR;
	DACC->DACC_IDR = 0xffffffff;
	DACC->DACC_IER = DACC_IER_ENDTX;
	NVIC_ClearPendingIRQ(DACC_IRQn);
	NVIC_SetPriority(DACC_IRQn, 1);
	NVIC_EnableIRQ(DACC_IRQn);

	DACC->DACC_PTCR = DACC_PTCR_TXTEN;
	DACC->DACC_MR &= ~DACC_MR_TRGSEL_Msk;
	DACC->DACC_MR |= DACC_MR_TRGEN | TRGSEL_TIOA1;

	TC0->TC_CHANNEL[1].TC_CCR = TC_CCR_CLKEN | TC_CCR_SWTRG;
	return true;
}

void gen_stop(void)
{
	DACC->DACC_MR &= ~(DACC_MR_TRGEN | DACC_MR_TRGSEL_Msk);
	DACC->DACC_PTCR = DACC_PTCR_TXTDIS;
	DACC->DACC_IDR = 0xffffffff;
	NVIC_DisableIRQ(DACC_IRQn);
	TC0->TC_CHANNEL[1].TC_CCR = TC_CCR_CLKDIS;
}

/*
 * The DACC driven from TIOA1 by gen's own table, with the clock left
 * stopped. play.cpp differs from this known-good path in exactly two
 * ways at once: its data arrives over USB, and its trigger is TIOA1
 * rather than the ADC's TIOA0. Splitting config from start lets the
 * caller match the loop's ordering exactly, so a fault that survives
 * here is in the trigger path and one that does not is in USB.
 */
void gen_prepare_tioa1(uint32_t dac_hz)
{
	uint32_t rc = (SystemCoreClock / 2u) / dac_hz;

	gen_stop();
	gen_endtx_count = 0;
	dac_rc = rc;

	PMC->PMC_PCER0 = (1u << ID_TC1);
	TC0->TC_CHANNEL[1].TC_CCR = TC_CCR_CLKDIS;
	TC0->TC_CHANNEL[1].TC_IDR = 0xffffffff;
	TC0->TC_CHANNEL[1].TC_CMR = TCCLKS_TIMER_CLOCK1
	                          | TC_CMR_WAVE
	                          | WAVSEL_UP_RC
	                          | ACPA_CLEAR
	                          | ACPC_SET;
	TC0->TC_CHANNEL[1].TC_RA = rc / 2u;
	TC0->TC_CHANNEL[1].TC_RC = rc;

	DACC->DACC_TPR  = (uint32_t)gen_table;
	DACC->DACC_TCR  = GEN_TABLE_LEN;
	DACC->DACC_TNPR = (uint32_t)gen_table;
	DACC->DACC_TNCR = GEN_TABLE_LEN;

	(void)DACC->DACC_ISR;
	DACC->DACC_IDR = 0xffffffff;
	DACC->DACC_IER = DACC_IER_ENDTX;
	NVIC_ClearPendingIRQ(DACC_IRQn);
	NVIC_SetPriority(DACC_IRQn, 1);
	NVIC_EnableIRQ(DACC_IRQn);

	DACC->DACC_PTCR = DACC_PTCR_TXTEN;
	DACC->DACC_MR &= ~DACC_MR_TRGSEL_Msk;
	DACC->DACC_MR |= DACC_MR_TRGEN | TRGSEL_TIOA1;
}

void gen_go_tioa1(void)
{
	TC0->TC_CHANNEL[1].TC_CCR = TC_CCR_CLKEN | TC_CCR_SWTRG;
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
