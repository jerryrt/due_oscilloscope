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
/* IBCTLCH0 and CH1, 0-3; IBCTLDACCORE, 0-3. Defaulted to the
 * datasheet's characterisation condition - see gen.h. */
uint8_t gen_ibctl_ch   = GEN_IBCTL_CH_CHARACTERISED;
uint8_t gen_ibctl_core = GEN_IBCTL_CORE_CHARACTERISED;

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

uint8_t  gen_shape  = GEN_SHAPE_SINE;
uint16_t gen_points = GEN_SINE_POINTS;

void gen_set_shape(uint32_t shape)
{
	gen_shape = (shape > GEN_SHAPE_MAX) ? (uint8_t)GEN_SHAPE_SINE
	                                    : (uint8_t)shape;
	build_table();
}

/* Which resolutions exist is the contract's business, not this
 * track's: gen_points_for() is in the shared layer so the host, the
 * console and the control channel cannot round differently. */
void gen_set_points(uint32_t points)
{
	gen_points = gen_points_for(points);
	build_table();
}

/*
 * The rate the converter is actually being clocked at, as the hardware
 * holds it - not an echo of what anyone asked for.
 *
 * Same reason acq_mr() and gen_acr() read back instead of remembering:
 * a stored copy is a second source of truth that goes stale the moment
 * anything else touches the register, and the DACC's trigger is touched
 * by gen, by play and by every stop. DACC_MR says whether a trigger is
 * enabled and which TIOA it is; that TC channel's RC says the divisor.
 *
 * Zero when nothing is clocking it, which is a different statement from
 * a frequency and is why ctl_gen_t carries the trigger as well as the
 * output.
 */
uint32_t gen_trigger_hz(void)
{
	uint32_t mr = DACC->DACC_MR;
	uint32_t sel, rc;

	if (!(mr & DACC_MR_TRGEN))
		return 0u;
	/* TRGSEL 1 is TIOA0 and 2 is TIOA1, so the TC channel is one
	 * less. Anything else is a trigger this driver did not set. */
	sel = (mr & DACC_MR_TRGSEL_Msk) >> DACC_MR_TRGSEL_Pos;
	if (sel != 1u && sel != 2u)
		return 0u;
	rc = TC0->TC_CHANNEL[sel - 1u].TC_RC;
	return rc ? (SystemCoreClock / 2u) / rc : 0u;
}

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

void gen_set_sync(uint32_t mode)
{
	gen_sync = (mode > GEN_SYNC_MAX) ? (uint8_t)GEN_SYNC_OFF
	                                 : (uint8_t)mode;
	build_table();
}

/*
 * The sync level at table index `i`. Rising edge at phase 0, which for
 * every shape here is the start of the cycle - so a scope triggered on
 * the sync's rising edge puts the waveform's phase 0 at the trigger
 * point, one trigger period later for the TAG interleave.
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

/*
 * One point of the selected shape, as a 12-bit DAC code.
 *
 * `t` is the position within a cycle and `period` the points in one, so
 * every shape here is scale-free: resolution changes what `period` is
 * and nothing else. Integer only - see gen.h for why that is a
 * constraint and not a preference.
 */
static int32_t shape_code(unsigned t, unsigned period)
{
	unsigned half = period / 2u;

	switch (gen_shape) {
	case GEN_SHAPE_SQUARE:
		return (t < half) ? 4095 : 0;
	case GEN_SHAPE_RAMP:
		/*
		 * A rising sawtooth that wraps, so the last point is one
		 * step below full scale rather than at it: dividing by
		 * `period` and not by `period - 1` is what keeps the step
		 * between the last point and the next cycle's first equal
		 * to every other step. Ending at 4095 would make the wrap
		 * a step of zero and put a one-sample flat spot in the
		 * only place a sawtooth has no flat spots.
		 */
		return (int32_t)((t * 4096u) / period);
	case GEN_SHAPE_TRIANGLE: {
		unsigned u = (t < half) ? t : (period - t);
		return half ? (int32_t)((u * 4095u) / half) : 2048;
	}
	case GEN_SHAPE_DC:
		return DC_CODE;
	case GEN_SHAPE_SINE:
	default:
		return 2048 + ((sine_q15(t, period) * 2047) >> 15);
	}
}

static void build_table(void)
{
	/*
	 * Resolution first, then TWOCYCLE on top of it.
	 *
	 * TWOCYCLE fits two periods into the space one would occupy rather
	 * than lengthening the table, so the wrap stays at GEN_TABLE_LEN
	 * and only the waveform speeds up. That is the whole point: the
	 * wrap is a PDC reload and has been exactly one period in every
	 * build this project has run, so "follows the table" and "follows
	 * the waveform" have never been separable. Here they fold at 512
	 * and at 2 * period respectively.
	 *
	 * Composing it with gen_points rather than replacing it: at the
	 * default 256 this is byte-for-byte the table the TWOCYCLE arm has
	 * always built, so its recorded issue-#5 results still describe
	 * the thing they were taken on. Resolution 128 in the NORMAL
	 * layout builds the same *waveform* by the other route, and the
	 * two differ only in where the fold lands - which is exactly the
	 * distinction the arm exists to make.
	 */
	const unsigned period = (gen_layout == GEN_LAYOUT_TWOCYCLE)
	                      ? (gen_points / 2u) : gen_points;

	/*
	 * SOLO: every entry tagged DAC0, so the converter updates it on
	 * every trigger instead of every other one and the table holds
	 * GEN_TABLE_LEN points of waveform instead of GEN_SINE_POINTS.
	 * The output frequency doubles; the sync, the bench trigger and
	 * the demultiplexing check are all given up for it.
	 */
	if (gen_sync == GEN_SYNC_SOLO) {
		for (unsigned i = 0; i < GEN_TABLE_LEN; i++) {
			int32_t code = period ? shape_code(i % period, period)
			                      : (int32_t)DC_CODE;

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
		int32_t code = period ? shape_code(i % period, period)
		                      : (int32_t)DC_CODE;
		uint16_t v0 = DC_CODE, v1 = DC_CODE;

		if (code < 0)
			code = 0;
		if (code > 4095)
			code = 4095;

		/*
		 * The waveform goes where the layout says, and the sync
		 * goes on the other pin. GEN_LAYOUT_DC gets neither: it is
		 * the control arm in which nothing swings anywhere.
		 */
		/* The waveform is scaled; the sync is NOT. The sync is a
		 * trigger and wants every volt of edge it can get - and
		 * scaling it would couple the bench's trigger quality to
		 * an amplitude chosen for the signal. */
		if (gen_layout == GEN_LAYOUT_SWAPPED) {
			v1 = gen_scale_code(code, gen_amp);
			v0 = sync_code(i, period);
		} else if (gen_layout != GEN_LAYOUT_DC) {
			v0 = gen_scale_code(code, gen_amp);
			v1 = sync_code(i, period);
		}

		gen_table[2 * i]     = (uint16_t)((0u << 12) | v0);
		gen_table[2 * i + 1] = (uint16_t)((1u << 12) | v1);
	}
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

/*
 * TC0 channel 1's compare value, as the hardware holds it.
 *
 * Read back rather than remembered, like gen_trigger_hz(), acq_mr() and
 * gen_acr() above: the rate a caller asked for and the rate the timer
 * was given differ by an integer division, and the sweep this feeds
 * exists to report exactly that difference.
 */
uint32_t gen_configured_rc(void)
{
	return TC0->TC_CHANNEL[1].TC_RC;
}

/*
 * Independent DAC timebase on TC0 channel 1, config and start together.
 *
 * In TAG mode each trigger converts exactly one sample, whichever
 * channel its tag names, so DAC conversions per second equals the
 * trigger rate. One ENDTX marks a whole table pass, which makes the
 * achieved rate directly countable: table length times ENDTX count over
 * elapsed time. That is the technique that found the ADC ceiling, and it
 * needs no help from the capture path.
 *
 * The refusal is the point of it being a separate entry rather than the
 * two calls the mimic preset makes: a compare value below 2 is a rate
 * the timer cannot produce, and the sweep asks for rates that are meant
 * to be refused.
 */
bool gen_start_independent(uint32_t dac_hz)
{
	if (dac_hz == 0)
		return false;
	if ((SystemCoreClock / 2u) / dac_hz < 2u)
		return false;

	gen_prepare_tioa1(dac_hz);
	gen_go_tioa1();
	return true;
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
