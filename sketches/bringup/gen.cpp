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

uint8_t  gen_shape  = GEN_SHAPE_SINE;
uint16_t gen_points = GEN_SINE_POINTS;

/*
 * One point of the selected shape, as a 12-bit code. `t` is the
 * position in a cycle and `period` the points in one, so resolution
 * changes `period` and nothing else here.
 */
static int32_t shape_code(unsigned t, unsigned period)
{
	unsigned half = period / 2u;

	switch (gen_shape) {
	case GEN_SHAPE_SQUARE:
		return (t < half) ? 4095 : 0;
	case GEN_SHAPE_RAMP:
		/* Divide by period, not period - 1: the wrap is then the
		 * same step as every other, instead of a flat spot in the
		 * one waveform that has none. */
		return (int32_t)((t * 4096u) / period);
	case GEN_SHAPE_TRIANGLE: {
		unsigned u = (t < half) ? t : (period - t);
		return half ? (int32_t)((u * 4095u) / half) : 2048;
	}
	case GEN_SHAPE_DC:
		return (int32_t)DC_CODE;
	case GEN_SHAPE_SINE:
	default:
		return (int32_t)(2047.5 + 2047.0
		                 * sin((2.0 * M_PI * t) / (double)period));
	}
}

static void build_table(void);

uint16_t gen_amp = GEN_AMP_FULL;

void gen_set_amp(uint32_t amp)
{
	if (amp > GEN_AMP_FULL)
		amp = GEN_AMP_FULL;
	if (amp < GEN_AMP_MIN)
		amp = GEN_AMP_MIN;
	gen_amp = (uint16_t)amp;
	build_table();
}

uint16_t gen_sync_amp = GEN_SYNC_AMP_FULL;

void gen_set_sync_amp(uint32_t amp)
{
	if (amp > GEN_AMP_FULL)
		amp = GEN_AMP_FULL;
	if (amp < GEN_AMP_MIN)
		amp = GEN_AMP_MIN;
	gen_sync_amp = (uint16_t)amp;
	build_table();
}

uint8_t gen_sync = GEN_SYNC_CYCLE;

/*
 * The sync level at table index `i`. Rising edge at phase 0, so a scope
 * triggered on it puts the waveform's phase 0 at the trigger point -
 * one trigger period later, for the TAG interleave.
 */
static uint16_t sync_code(unsigned i, unsigned period)
{
	unsigned t, half;

	switch (gen_sync) {
	case GEN_SYNC_CYCLE:
		t = period ? (i % period) : 0u;
		half = period / 2u;
		return gen_scale_code((t < half) ? 4095 : 0, gen_sync_amp);
	case GEN_SYNC_WRAP:
		return gen_scale_code(
			(i < GEN_SINE_POINTS / 2u) ? 4095 : 0, gen_sync_amp);
	case GEN_SYNC_OFF:
	default:
		return DC_CODE;
	}
}

static void build_table(void)
{
	const unsigned period = gen_points ? gen_points : GEN_SINE_POINTS;

	/*
	 * SOLO: every entry tagged DAC0, so the converter updates it on
	 * every trigger instead of every other one and the table holds
	 * GEN_TABLE_LEN points of waveform instead of GEN_SINE_POINTS.
	 * The output frequency doubles; the sync, the bench trigger and
	 * the demultiplexing check are all given up for it.
	 */
	if (gen_sync == GEN_SYNC_SOLO) {
		for (unsigned i = 0; i < GEN_TABLE_LEN; i++) {
			int32_t code = shape_code(i % period, period);

			if (code < 0)
				code = 0;
			if (code > 4095)
				code = 4095;
			gen_table[i] = (uint16_t)((0u << 12)
			                          | gen_scale_code(code,
			                                           gen_amp));
		}
		return;
	}

	for (unsigned i = 0; i < GEN_SINE_POINTS; i++) {
		int32_t code = shape_code(i % period, period);

		if (code < 0)
			code = 0;
		if (code > 4095)
			code = 4095;

		/* The waveform is scaled; the sync is not - it is a trigger
		 * and wants every volt of edge it can get. */
		gen_table[2 * i]     = (uint16_t)((0u << 12)
		                                  | gen_scale_code(code,
		                                                   gen_amp));
		gen_table[2 * i + 1] = (uint16_t)((1u << 12)
		                                  | sync_code(i, period));
	}
}

void gen_set_sync(uint32_t mode)
{
	gen_sync = (mode > GEN_SYNC_MAX) ? (uint8_t)GEN_SYNC_OFF
	                                 : (uint8_t)mode;
	build_table();
}

void gen_set_shape(uint32_t shape)
{
	gen_shape = (shape > GEN_SHAPE_MAX) ? (uint8_t)GEN_SHAPE_SINE
	                                    : (uint8_t)shape;
	build_table();
}

/* Which resolutions exist is the contract's business, not this track's:
 * gen_points_for() is in the shared layer so the host, the console and
 * the control channel cannot round differently. */
void gen_set_points(uint32_t points)
{
	gen_points = gen_points_for(points);
	build_table();
}

/*
 * The rate the converter is actually clocked at, as the hardware holds
 * it. DACC_MR says whether a trigger is enabled and which TIOA; that TC
 * channel's RC is the divisor. Read back rather than remembered, for
 * the same reason every other readback here is: a stored copy is a
 * second source of truth that goes stale when play or a stop touches
 * the register.
 */
uint32_t gen_trigger_hz(void)
{
	uint32_t mr = DACC->DACC_MR;
	uint32_t sel, rc;

	if (!(mr & DACC_MR_TRGEN))
		return 0u;
	sel = (mr & DACC_MR_TRGSEL_Msk) >> DACC_MR_TRGSEL_Pos;
	if (sel != 1u && sel != 2u)
		return 0u;
	rc = TC0->TC_CHANNEL[sel - 1u].TC_RC;
	return rc ? (SystemCoreClock / 2u) / rc : 0u;
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
 *
 * Called from the single DACC_Handler in play.cpp rather than owning
 * the vector: play.cpp wants the same event for the host-fed ring, and
 * only one definition of the handler can exist.
 */
void gen_endtx(void)
{
	if (DACC->DACC_ISR & DACC_ISR_ENDTX) {
		DACC->DACC_TNPR = (uint32_t)gen_table;
		DACC->DACC_TNCR = GEN_TABLE_LEN;
		gen_endtx_count++;
	}
}
