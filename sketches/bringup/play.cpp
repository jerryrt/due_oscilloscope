/*
 * Host-fed DAC playback for Track A. See play.h for the shape of the
 * ring; this file is the Arduino-stack half of it.
 *
 * Register configuration is deliberately identical to drivers/play.c,
 * down to the trigger source, the ring geometry, the prime threshold
 * and the multi-slot DMA spans, so that a difference in measured
 * behaviour between the tracks means a real difference and not a
 * different setup. The only thing that differs is who enumerates.
 */

#include <Arduino.h>
#include "acq.h"          /* TCCLKS_/WAVSEL_/ACPA_/ACPC_ */
#include "gen.h"
#include "play.h"
#include "console_out.h"
#include "console_port.h"
#include "usbdma.h"

#define TRGSEL_TIOA1 (2u << 1)   /* DACC_MR.TRGSEL: 2 = TIOA1 */

static uint16_t play_buf[PLAY_NBUF][PLAY_BUF_SAMPLES]
	__attribute__((aligned(4)));

volatile uint32_t play_produced;
volatile uint32_t play_consumed;
volatile uint32_t play_underruns;
volatile uint32_t play_bytes_in;
volatile uint32_t play_isr_calls;
volatile uint32_t play_endtx_seen;
volatile uint32_t play_occ_hist[PLAY_NBUF];
volatile uint32_t play_occ_min;
volatile uint8_t  play_occ_trace[PLAY_OCC_TRACE];
volatile uint32_t play_occ_traced;
volatile uint32_t play_run_us;
static uint32_t run_t0_us;
volatile uint32_t play_svc_calls;
volatile uint32_t play_spans;         /* OUT DMA transfers armed */
volatile uint32_t play_partial;       /* spans that ended off a slot edge */

static uint32_t fill_off;            /* byte offset into the filling buffer */
static uint32_t dac_rc;
static bool     active;
static bool     primed;
static bool     dma_inflight;        /* an OUT-endpoint DMA is running */
static uint32_t dma_asked;           /* bytes requested of that transfer */
static uint32_t dma_start_off;       /* fill_off when it started */
static uint32_t dma_published;       /* slots already published from it */
static uint32_t dma_counted;         /* bytes of it already in play_bytes_in */

/*
 * Enough queued to ride out host scheduling jitter before the first
 * conversion, so priming never emits a burst of stale repeats.
 *
 * 24, matching drivers/play.c, measured independently on this track.
 * Three runs per rate, counters read inside the run:
 *
 *   prime   underruns          occmin
 *      4    0-7                2-8
 *     24    0 in all nine      21-29
 *
 * Matches objective 0i's Track B result: the ring stops living at the
 * ENDTX guard and the startup burst goes away.
 *
 * Read the counters before run_loop drains them, not after - this
 * track repeats its last buffer for ~2 s after the feeder stops (see
 * PLAY_ABANDON_MS below), and a post-drain read describes that
 * shutdown tail, not the run, which made this constant look inert
 * when it was not.
 */
#define PLAY_PRIME_BUFS 24u

/*
 * How long the host may be silent before playback gives up. Ported
 * from drivers/play.c, same constant and same rule: without it this
 * track repeats its last buffer indefinitely once the feed stops,
 * which is what made PLAY_PRIME_BUFS look inert above.
 *
 * Half a second is many hundreds of buffers at every rate on the
 * ladder, so it cannot fire on a host that is merely slow; it fires
 * on a host that has gone. play_abandoned counts it so the behaviour
 * change is never silent.
 */
#define PLAY_ABANDON_MS 500u

volatile uint32_t play_abandoned;
static uint32_t abandon_bytes;
static uint32_t abandon_at_ms;

bool play_active(void) { return active; }

uint32_t play_configured_rc(void) { return dac_rc; }

const uint8_t *play_ring_base(void) { return (const uint8_t *)play_buf; }

static void dac_tc_init(uint32_t rc)
{
	/* Each timer channel has its own peripheral ID: channel 1 is
	 * ID_TC1, not ID_TC0. Clocking the wrong one leaves TIOA1 dead. */
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
}

bool play_start(uint32_t dac_hz)
{
	uint32_t rc;

	if (dac_hz == 0)
		return false;
	rc = (SystemCoreClock / 2u) / dac_hz;
	if (rc < PLAY_MIN_RC)
		return false;

	play_stop();

	play_produced = 0;
	play_spans = 0;
	play_partial = 0;
	play_consumed = 0;
	play_underruns = 0;
	play_bytes_in = 0;
	play_isr_calls = 0;
	play_endtx_seen = 0;
	play_abandoned = 0;
	abandon_bytes = 0;
	abandon_at_ms = millis();
	for (unsigned i = 0; i < PLAY_NBUF; i++)
		play_occ_hist[i] = 0;
	play_occ_min = PLAY_NBUF;
	play_occ_traced = 0;
	play_run_us = 0;
	run_t0_us = 0;
	play_svc_calls = 0;
	fill_off = 0;
	dac_rc = rc;
	dma_inflight = false;

	/* The ring is fed by endpoint DMA. Only OUT: in loop mode capture
	 * owns IN at the same time, and the pair form would release it. */
	usb_dma_mode_out(true);

	/* Silence until the host supplies something: mid scale on both,
	 * with the channel tag alternating so the DACC sees a well-formed
	 * two-channel stream from the first conversion. */
	for (unsigned b = 0; b < PLAY_NBUF; b++)
		for (unsigned i = 0; i < PLAY_BUF_SAMPLES; i++)
			play_buf[b][i] = (uint16_t)(((i & 1u) << 12) | 2048u);

	PMC->PMC_PCER1 = (1u << (ID_DACC - 32));
	DACC->DACC_CR = DACC_CR_SWRST;
	/* Every path that resets the DACC re-applies the output bias, or a
	 * capture silently undoes what the console was told it set. */
	gen_apply_acr();
	DACC->DACC_MR = DACC_MR_TAG
	              | DACC_MR_REFRESH(1)
	              | (0x10u << DACC_MR_STARTUP_Pos)
	              | DACC_MR_MAXS;
	DACC->DACC_CHER = DACC_CHER_CH0 | DACC_CHER_CH1;

	dac_tc_init(rc);

	/* The consumer starts owning buffers 0 and 1, matching
	 * play_consumed = 0 and the TNPR slot at play_consumed + 1. */
	DACC->DACC_TPR  = (uint32_t)play_buf[0];
	DACC->DACC_TCR  = PLAY_BUF_SAMPLES;
	DACC->DACC_TNPR = (uint32_t)play_buf[1];
	DACC->DACC_TNCR = PLAY_BUF_SAMPLES;

	(void)DACC->DACC_ISR;
	DACC->DACC_IDR = 0xffffffff;
	DACC->DACC_IER = DACC_IER_ENDTX;
	NVIC_ClearPendingIRQ(DACC_IRQn);
	NVIC_SetPriority(DACC_IRQn, 1);       /* below the ADC handler */
	NVIC_EnableIRQ(DACC_IRQn);

	DACC->DACC_PTCR = DACC_PTCR_TXTEN;
	DACC->DACC_MR |= DACC_MR_TRGEN | TRGSEL_TIOA1;

	/*
	 * Do not start the timer yet. Starting an empty ring guarantees a
	 * burst of underruns while the host is still filling it, and every
	 * repeat emits stale audio. play_service starts the clock once
	 * enough buffers are queued.
	 */
	active = true;
	primed = false;
	return true;
}

void play_stop(void)
{
	if (active)
		usb_dma_mode_out(false);
	active = false;
	primed = false;
	dma_inflight = false;
	TC0->TC_CHANNEL[1].TC_CCR = TC_CCR_CLKDIS;
	DACC->DACC_MR &= ~(DACC_MR_TRGEN | DACC_MR_TRGSEL_Msk);
	DACC->DACC_PTCR = DACC_PTCR_TXTDIS;
	DACC->DACC_IDR = 0xffffffff;
	NVIC_DisableIRQ(DACC_IRQn);
}

/*
 * Fill the ring by endpoint DMA: bulk OUT data moves from the FIFO into
 * the playback buffers with no CPU copy at all. Invariant 1, which this
 * path is the most tempting place in the firmware to break.
 *
 * One transfer is in flight at a time, aimed at as many contiguous free
 * slots as the ring allows. Single-slot transfers cap throughput at
 * roughly slot-size over service latency, because a new transfer can
 * only start on a main-loop pass; a multi-slot span keeps the
 * controller busy across many passes.
 *
 * The reservation stays two slots short of the reader because the PDC
 * owns both the buffer it is emitting and the one latched in TNPR.
 */
void play_service(void)
{
	if (!active)
		return;

	play_svc_calls++;

	/*
	 * millis(), not micros(): this runs on every pass while active and
	 * micros() costs five times as much, and half a second needs no
	 * better resolution than a millisecond.
	 */
	{
		uint32_t ms = millis();

		if (play_bytes_in != abandon_bytes) {
			abandon_bytes = play_bytes_in;
			abandon_at_ms = ms;
		} else if (abandon_bytes != 0
		           && ms - abandon_at_ms > PLAY_ABANDON_MS) {
			/*
			 * Only after something has arrived. Abandonment means
			 * "was receiving, then stopped"; a run that has not
			 * started yet is a different thing, and timing it from
			 * play_start stopped playback before the host had
			 * finished priming its feeder.
			 */
			play_abandoned++;
			play_stop();
			return;
		}
	}

	/* The core rebuilds endpoint configuration on bus reset and
	 * SET_CONFIGURATION, clearing AUTOSW and re-enabling its own
	 * receive interrupt. Put it back before relying on either. */
	usbdma_keepalive();

	if (dma_inflight) {
		/*
		 * Publish progress while the transfer runs, not just at its
		 * end: a multi-slot span takes many milliseconds to complete,
		 * and a consumer that only learned of new data at completion
		 * would drain the ring against a frozen counter and underrun
		 * with the bytes already in SRAM. BUFF_COUNT counts down as
		 * the DMA lands bytes, so completed slots can be published
		 * incrementally and exactly.
		 */
		/*
		 * One snapshot, decoded twice. Asking the hardware separately
		 * how far it got and whether it had finished let the transfer
		 * end between the two questions, and the pair of answers then
		 * described a state that never existed: a span recorded as
		 * short resumed the next one behind the data already in SRAM,
		 * and the bytes in between were overwritten before the DAC
		 * ever read them.
		 */
		uint32_t st = usb_dma_out_status();
		uint32_t left = (st & UOTGHS_DEVDMASTATUS_BUFF_COUNT_Msk)
		                >> UOTGHS_DEVDMASTATUS_BUFF_COUNT_Pos;
		bool busy = (st & UOTGHS_DEVDMASTATUS_CHANN_ENB) != 0;
		uint32_t done = dma_asked > left ? dma_asked - left : 0;
		uint32_t slots_done = (dma_start_off + done) / PLAY_BUF_BYTES;

		if (slots_done > dma_published) {
			__DMB();
			play_produced += slots_done - dma_published;
			dma_published = slots_done;
			/* A multi-slot span is armed once but lands over many
			 * milliseconds; bump here too or the indicator goes
			 * dark during the busiest part of a transfer. */
			usb_out_activity++;
		}
		/*
		 * Byte accounting has to be exact to be worth anything: the
		 * question it answers is whether the device received every
		 * byte the host wrote, and an under-report of unknown size
		 * cannot answer it. Publish the in-flight progress on every
		 * pass rather than a whole span behind it.
		 */
		play_bytes_in += done - dma_counted;
		dma_counted = done;

		if (busy)
			goto prime;

		dma_inflight = false;
		fill_off = (dma_start_off + done) % PLAY_BUF_BYTES;
		/*
		 * A stream span is armed with a length that ends exactly on a
		 * slot edge, and nothing may end it early, so a non-zero
		 * fill_off here means the transfer stopped somewhere the
		 * arithmetic did not expect and the next span will resume at
		 * the wrong offset.
		 */
		if (fill_off != 0)
			play_partial++;
	}

	if (!dma_inflight &&
	    play_produced - play_consumed < PLAY_NBUF - 2u) {
		uint32_t slot = play_produced % PLAY_NBUF;
		uint32_t free_slots = (PLAY_NBUF - 2u)
		                    - (play_produced - play_consumed);
		uint32_t until_wrap = PLAY_NBUF - slot;
		uint32_t span = free_slots < until_wrap ? free_slots
		                                        : until_wrap;
		uint8_t *dst = (uint8_t *)play_buf[slot] + fill_off;

		dma_asked = span * PLAY_BUF_BYTES - fill_off;
		dma_start_off = fill_off;
		dma_published = 0;
		dma_counted = 0;
		if (usb_dma_out_start_stream(dst, dma_asked)) {
			dma_inflight = true;
			play_spans++;
		}
	}

prime:
	if (!primed && play_produced >= PLAY_PRIME_BUFS) {
		primed = true;
		run_t0_us = micros();
		TC0->TC_CHANNEL[1].TC_CCR = TC_CCR_CLKEN | TC_CCR_SWTRG;
	}
	if (primed)
		play_run_us = micros() - run_t0_us;
}

/*
 * Hand the PDC the next filled buffer. If the host has not kept up,
 * count an underrun and let the current buffer repeat rather than
 * emitting whatever happens to be in memory.
 */
static void play_endtx(void)
{
	play_isr_calls++;
	if (!(DACC->DACC_ISR & DACC_ISR_ENDTX))
		return;
	play_endtx_seen++;

	/*
	 * Consumer half of a single-producer/single-consumer ring:
	 * play_consumed is written only here, play_produced only by
	 * play_service. One writer per counter makes this lock-free, and
	 * addressing is derived from play_consumed alone.
	 *
	 * Three, not two: ENDTX fires once the PDC has already latched
	 * TNPR into TPR, so the buffer just finished is play_consumed, the
	 * one now emitting is play_consumed + 1, and TNPR must be loaded
	 * with play_consumed + 2 - so latching it needs play_produced >=
	 * play_consumed + 3. At two, ENDTX could latch a slot the DMA was
	 * still filling: a phase jump with no underrun counted, the exact
	 * discontinuity invariant 5 exists to make impossible. Falling one
	 * short now counts an underrun and repeats instead.
	 *
	 * Sample before the decision, not after: the only quantity that
	 * distinguishes a run that starves from one that does not. Same
	 * place in the ISR as drivers/play.c, since sampling it anywhere
	 * else measures a different moment.
	 */
	{
		uint32_t occ = play_produced - play_consumed;

		play_occ_hist[occ < PLAY_NBUF ? occ : PLAY_NBUF - 1u]++;
		if (occ < play_occ_min)
			play_occ_min = occ;
		if (play_endtx_seen % PLAY_OCC_DECIM == 0u &&
		    play_occ_traced < PLAY_OCC_TRACE)
			play_occ_trace[play_occ_traced++] = (uint8_t)occ;
	}

	if (play_produced - play_consumed >= 3u) {
		play_consumed++;
		__DMB();
		DACC->DACC_TNPR =
			(uint32_t)play_buf[(play_consumed + 1u) % PLAY_NBUF];
	} else {
		/*
		 * Nothing new to queue. Repeat the current buffer rather than
		 * emitting whatever memory happens to hold, and count it: an
		 * underrun that is concealed becomes a signal defect the host
		 * would blame on the analog path.
		 */
		play_underruns++;
		DACC->DACC_TNPR =
			(uint32_t)play_buf[play_consumed % PLAY_NBUF];
	}
	DACC->DACC_TNCR = PLAY_BUF_SAMPLES;
}

/*
 * Sole owner of the DACC vector, dispatching to whichever source is
 * driving the converter. gen.cpp plays a fixed table from flash;
 * play.cpp plays a ring fed over USB. They are never active at once.
 */
void DACC_Handler(void)
{
	if (active)
		play_endtx();
	else
		gen_endtx();
}

/*
 * Dump what actually landed in the playback ring.
 *
 * The host knows exactly what it sent, so comparing the first samples of
 * a filled buffer against that is the shortest path from "the output is
 * wrong" to "the data arrived wrong" or "the data arrived right and the
 * DAC is misreading it".
 */
void play_dump(void)
{
	const uint16_t *b = play_buf[1];   /* one the host filled */

	con_str("# DACC_MR="); con_hex32(DACC->DACC_MR, 8);
	con_str(" TAG=");      con_u32(!!(DACC->DACC_MR & DACC_MR_TAG));
	con_str(" MAXS=");     con_u32(!!(DACC->DACC_MR & DACC_MR_MAXS));
	con_str(" WORD=");     con_u32(!!(DACC->DACC_MR & DACC_MR_WORD));
	con_str(" TRGEN=");    con_u32(!!(DACC->DACC_MR & DACC_MR_TRGEN));
	con_str(" TRGSEL=");
	con_u32((DACC->DACC_MR & DACC_MR_TRGSEL_Msk) >> 1);
	con_str(" CHSR=");     con_hex32(DACC->DACC_CHSR, 8);
	con_nl();
	con_str("# play_dump buf1 ");
	con_kv_u32("fill_off", fill_off);       con_ch(' ');
	con_kv_u32("produced", play_produced);  con_ch(':'); con_nl();

	for (int row = 0; row < 2; row++) {
		con_str("#  ");
		for (int i = 0; i < 8; i++) {
			uint16_t v = b[row * 8 + i];

			con_ch(' ');  con_hex32(v, 4);
			con_str("(t"); con_u32((v >> 12) & 3u);
			con_ch(',');   con_u32w(v & 0x0fffu, 4, ' ');
			con_ch(')');
		}
		con_nl();
	}
	console_flush();
}
