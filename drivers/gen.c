/*
 * DAC playback, triggered by the same TIOA0 as the ADC.
 *
 * DACC TAG mode drives both channels from one PDC stream: DAC0 gets a
 * sine, DAC1 a fixed mid-scale level. The constant channel is a
 * demultiplexing check, not filler - a sine appearing on A1 means the
 * channel tags are being read wrong.
 *
 * The sine table is generated with an integer approximation rather than
 * libm, to keep the bare-metal image free of the soft-float library for
 * one startup computation.
 */

#include "sam.h"
#include "acq.h"
#include "gen.h"

#define DC_CODE 2048u

static uint16_t gen_table[GEN_TABLE_LEN];
volatile uint32_t gen_endtx_count;

/*
 * Fixed-point sine, Bhaskara-style approximation on the half period,
 * mirrored for the other half. Peak error is well under one LSB at
 * 12-bit resolution, which is all this needs.
 */
static int32_t sine_q15(uint32_t i, uint32_t n)
{
	int32_t sign = 1;
	int32_t num, den;
	/* x scaled so that a half period spans 0..32768 */
	int32_t x = (int32_t)((i * 65536u) / n);

	if (x >= 32768) {
		x -= 32768;
		sign = -1;
	}
	/* sin(pi*t) ~= 16t(1-t) / (5 - 4t(1-t)), t = x/32768 in Q15 */
	{
		int32_t t  = x;                       /* Q15 */
		int32_t om = 32768 - t;               /* 1 - t */
		int32_t tm = (t * om) >> 15;          /* t(1-t) */
		num = 16 * tm;
		den = 5 * 32768 - 4 * tm;
		/* num << 15 overflows int32 at the peak: at t = 0.5 it is
		 * 2^17 << 15 = 2^32, which wraps to zero and flattens the
		 * waveform to roughly a tenth of full scale. Widen first. */
		return sign * (int32_t)(((int64_t)num << 15) / den);   /* Q15 */
	}
}

static void build_table(void)
{
	for (unsigned i = 0; i < GEN_SINE_POINTS; i++) {
		int32_t s = sine_q15(i, GEN_SINE_POINTS);      /* -32768..32767 */
		int32_t code = 2048 + ((s * 2047) >> 15);

		if (code < 0)
			code = 0;
		if (code > 4095)
			code = 4095;

		gen_table[2 * i]     = (uint16_t)((0u << 12) | (uint16_t)code);
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
	NVIC_SetPriority(DACC_IRQn, 1);
	NVIC_EnableIRQ(DACC_IRQn);

	DACC->DACC_PTCR = DACC_PTCR_TXTEN;
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
 * Called from the single DACC_Handler in play.c. Two modules want the
 * end-of-transmit event, and only one of them can own the vector, so the
 * owner dispatches on which source is active.
 */
void gen_endtx(void)
{
	if (DACC->DACC_ISR & DACC_ISR_ENDTX) {
		DACC->DACC_TNPR = (uint32_t)gen_table;
		DACC->DACC_TNCR = GEN_TABLE_LEN;
		gen_endtx_count++;
	}
}
