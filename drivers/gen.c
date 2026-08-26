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

/*
 * DACC_ACR: the output stage's bias current, and it has never been
 * written here.
 *
 * Datasheet 45.7.11 calls IBCTLCHx "Analog Output Current Control -
 * allows to adapt the slew rate of the analog output", and Tables 46-38
 * and 46-40 specify every published DAC figure - INL, DNL, SNR, THD,
 * SINAD - at IBCTLDACCORE=01 with IBCTLCHx=10. At reset the field is 0,
 * so the part has been running outside the conditions its own numbers
 * describe. The Arduino core writes exactly the characterised value at
 * wiring_analog.c:232 the first time a DAC channel is enabled, which
 * makes this a track parity gap as well as a knob.
 *
 * It has to be applied *after* DACC_CR_SWRST, and by every path that
 * issues one - gen_init() and play_init() both do. Setting it from a
 * console command alone would be silently undone by the next capture,
 * which is the mistake ADC_MR's readback exists to catch.
 */
uint8_t gen_ibctl_ch;      /* IBCTLCH0 and CH1, 0-3 */
uint8_t gen_ibctl_core;    /* IBCTLDACCORE, 0-3    */

void gen_set_ibctl(uint32_t ch, uint32_t core)
{
	gen_ibctl_ch   = (uint8_t)(ch > 3u ? 3u : ch);
	gen_ibctl_core = (uint8_t)(core > 3u ? 3u : core);
}

void gen_apply_acr(void)
{
	DACC->DACC_ACR = DACC_ACR_IBCTLCH0(gen_ibctl_ch)
	               | DACC_ACR_IBCTLCH1(gen_ibctl_ch)
	               | DACC_ACR_IBCTLDACCORE(gen_ibctl_core);
}

/* As the hardware holds it. See acq_mr() for why this is not an echo. */
uint32_t gen_acr(void)
{
	return DACC->DACC_ACR;
}


static void build_table(void);

uint8_t gen_layout = GEN_LAYOUT_NORMAL;

void gen_set_layout(uint32_t layout)
{
	gen_layout = (layout > GEN_LAYOUT_DC) ? (uint8_t)GEN_LAYOUT_NORMAL
	                                      : (uint8_t)layout;
	build_table();
}

static void build_table(void)
{
	/*
	 * TWOCYCLE fits two sine periods into the same 256 points rather
	 * than lengthening the table, so the wrap stays at GEN_TABLE_LEN
	 * and only the waveform speeds up. That is the whole point: the
	 * wrap is a PDC reload and has been exactly one sine period in
	 * every build this project has run, so "follows the table" and
	 * "follows the waveform" have never been separable. Here they fold
	 * at 512 and 256 respectively.
	 */
	const unsigned period = (gen_layout == GEN_LAYOUT_TWOCYCLE)
	                      ? GEN_SINE_POINTS / 2u : GEN_SINE_POINTS;

	for (unsigned i = 0; i < GEN_SINE_POINTS; i++) {
		int32_t s = sine_q15(i % period, period);      /* -32768..32767 */
		int32_t code = 2048 + ((s * 2047) >> 15);
		uint16_t v0 = DC_CODE, v1 = DC_CODE;

		if (code < 0)
			code = 0;
		if (code > 4095)
			code = 4095;

		if (gen_layout == GEN_LAYOUT_SWAPPED)
			v1 = (uint16_t)code;
		else if (gen_layout != GEN_LAYOUT_DC)
			v0 = (uint16_t)code;

		gen_table[2 * i]     = (uint16_t)((0u << 12) | v0);
		gen_table[2 * i + 1] = (uint16_t)((1u << 12) | v1);
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
	gen_apply_acr();

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

/*
 * The playback configuration with gen's data source: DACC triggered by
 * TIOA1 and playing the flash sine table, no USB involved.
 *
 * This exists to split the full-loop freeze in two. play.c differs from
 * the known-good gen path in exactly two ways at once: its data arrives
 * over USB, and its trigger is TIOA1 instead of the ADC's TIOA0. If this
 * variant freezes under capture too, the trigger/DACC/ADC interaction is
 * at fault and USB is exonerated; if it plays cleanly, the fault is in
 * the USB duplex path. Config and start are split so the caller can
 * reproduce the loop's ordering: DACC and timer first, capture second,
 * clock last, exactly as play_service does once its ring is primed.
 */
void gen_prepare_tioa1(uint32_t dac_hz)
{
	uint32_t rc = (SystemCoreClock / 2u) / dac_hz;

	gen_stop();
	gen_endtx_count = 0;

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
	DACC->DACC_MR |= DACC_MR_TRGEN | TRGSEL_TIOA1;
}

void gen_go_tioa1(void)
{
	TC0->TC_CHANNEL[1].TC_CCR = TC_CCR_CLKEN | TC_CCR_SWTRG;
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
