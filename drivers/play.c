#include "sam.h"
#include "acq.h"          /* TCCLKS_/WAVSEL_/ACPA_/ACPC_ and TRGSEL */
#include "play.h"
#include "usb_cdc.h"
#include "gen.h"

#define TRGSEL_TIOA1 (2u << 1)   /* DACC_MR.TRGSEL: 2 = TIOA1 */

/*
 * Bank 1, not bank 0: the 32-slot ring no longer fits bank 0 next to
 * the capture ring, and separating the two DMA rings across banks is
 * what the linker regions exist for anyway.
 */
/*
 * Bank 0, since the capture ring now needs bank 1 - see acq.c. The
 * playback pairing is the DACC's PDC reading while the USB DMA writes,
 * which is the same shape and now has bank 0 to itself.
 */
static uint16_t play_buf[PLAY_NBUF][PLAY_BUF_SAMPLES]
	__attribute__((aligned(4)));

volatile uint32_t play_produced;
volatile uint32_t play_consumed;
volatile uint32_t play_underruns;
volatile uint32_t play_bytes_in;
volatile uint32_t play_isr_calls;
volatile uint32_t play_endtx_seen;
volatile uint32_t play_svc_calls;
volatile uint32_t play_spans;         /* OUT DMA transfers armed */
volatile uint32_t play_partial;       /* spans that ended off a slot edge */

static uint32_t fill_off;            /* byte offset into the filling buffer */
static bool     active;
static bool     primed;
static bool     dma_inflight;        /* an OUT-endpoint DMA is running */
static uint32_t dma_asked;           /* bytes requested of that transfer */
static uint32_t dma_start_off;       /* fill_off when it started */
static uint32_t dma_published;       /* slots already published from it */
static uint32_t dma_counted;         /* bytes of it already in play_bytes_in */

#define PLAY_PRIME_BUFS 4u

bool play_active(void) { return active; }

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
	play_consumed = 0;
	play_underruns = 0;
	play_bytes_in = 0;
	play_svc_calls = 0;
	play_spans = 0;
	play_partial = 0;
	fill_off = 0;
	dma_inflight = false;

	/* The ring is fed by endpoint DMA; capture IN stays manual. */
	/* OUT only: capture may be running with IN on DMA, and taking
	 * that away here is how a loop ends up with one direction
	 * silently back on the FIFO path. */
	usb_cdc_dma_mode_out(true);

	/* Silence until the host supplies something: mid scale on both. */
	for (unsigned b = 0; b < PLAY_NBUF; b++)
		for (unsigned i = 0; i < PLAY_BUF_SAMPLES; i++)
			play_buf[b][i] = (uint16_t)(((i & 1u) << 12) | 2048u);

	PMC->PMC_PCER1 = (1u << (ID_DACC - 32));
	DACC->DACC_CR = DACC_CR_SWRST;
	DACC->DACC_MR = DACC_MR_TAG
	              | DACC_MR_REFRESH(1)
	              | (0x10u << DACC_MR_STARTUP_Pos)
	              | DACC_MR_MAXS;
	DACC->DACC_CHER = DACC_CHER_CH0 | DACC_CHER_CH1;

	dac_tc_init(rc);

	/* Consumer starts owning buffers 0 and 1, matching play_consumed
	 * = 0 and the TNPR slot at play_consumed + 1. */
	DACC->DACC_TPR  = (uint32_t)play_buf[0];
	DACC->DACC_TCR  = PLAY_BUF_SAMPLES;
	DACC->DACC_TNPR = (uint32_t)play_buf[1];
	DACC->DACC_TNCR = PLAY_BUF_SAMPLES;

	(void)DACC->DACC_ISR;
	DACC->DACC_IDR = 0xffffffff;
	DACC->DACC_IER = DACC_IER_ENDTX;
	NVIC_ClearPendingIRQ(DACC_IRQn);
	NVIC_SetPriority(DACC_IRQn, 1);
	NVIC_EnableIRQ(DACC_IRQn);

	DACC->DACC_PTCR = DACC_PTCR_TXTEN;
	DACC->DACC_MR |= DACC_MR_TRGEN | TRGSEL_TIOA1;

	/*
	 * Do not start the timer yet. Starting an empty ring guarantees a
	 * burst of underruns while the host is still filling it, and every
	 * repeat emits stale audio. play_service starts the clock once
	 * enough buffers are queued to ride out host jitter.
	 */
	active = true;
	primed = false;
	return true;
}

void play_stop(void)
{
	if (active)
		usb_cdc_dma_mode_out(false);
	active = false;
	TC0->TC_CHANNEL[1].TC_CCR = TC_CCR_CLKDIS;
	DACC->DACC_MR &= ~(DACC_MR_TRGEN | DACC_MR_TRGSEL_Msk);
	DACC->DACC_PTCR = DACC_PTCR_TXTDIS;
	DACC->DACC_IDR = 0xffffffff;
	NVIC_DisableIRQ(DACC_IRQn);
}

/*
 * Fill the ring by endpoint DMA: bulk OUT data moves from the FIFO into
 * the playback buffers with no CPU copy at all, which is the invariant
 * this architecture is built on. One transfer is in flight at a time,
 * aimed at the remainder of the slot being filled; END_TR_EN ends a
 * transfer early at a short packet, so arbitrary host write chunking
 * costs a partial slot to resume, never a byte.
 */
void play_service(void)
{
	if (!active)
		return;

	play_svc_calls++;

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
		 * described a state that never existed.
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
		}
		/*
		 * Byte accounting has to be exact to be worth anything: the
		 * question it answers is whether the device received every
		 * byte the host wrote, and an under-report of unknown size
		 * cannot answer it. Publish the in-flight progress on every
		 * pass and subtract it again when the next pass reads a
		 * larger figure, so play_bytes_in tracks BUFF_COUNT rather
		 * than lagging a whole span behind it.
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

	/*
	 * Span as many contiguous free slots as the ring allows in one
	 * transfer. One-slot transfers capped throughput at roughly
	 * slot-size over service latency (~1.7 MB/s measured), because a
	 * new transfer could only start on a main-loop pass; a multi-slot
	 * transfer keeps the DMA busy across many passes. The reservation
	 * stays two slots short of the reader because the PDC owns both
	 * the buffer it is emitting and the one latched in TNPR.
	 */
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
		TC0->TC_CHANNEL[1].TC_CCR = TC_CCR_CLKEN | TC_CCR_SWTRG;
	}
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
	 * Consumer half of a single-producer/single-consumer ring.
	 *
	 * play_consumed is written here and nowhere else; play_produced is
	 * written by play_service and nowhere else. One writer per counter
	 * is what makes this lock-free without a critical section, and an
	 * earlier version broke it by keeping a third index for addressing
	 * that drifted out of step with the availability counters.
	 *
	 * Addressing is now derived from play_consumed alone, so the buffer
	 * the guard protects is by construction the buffer the PDC reads.
	 */
	/*
	 * Three, not two.
	 *
	 * ENDTX fires once the PDC has already latched TNPR into TPR, so at
	 * this point the buffer just finished is play_consumed, the one now
	 * being emitted is play_consumed + 1, and TNPR has to be loaded
	 * with play_consumed + 2. Filled slots are those below
	 * play_produced, so latching that buffer needs play_produced to be
	 * at least play_consumed + 3.
	 *
	 * At two it latched a slot the DMA was still filling and the DAC
	 * emitted whatever the previous lap of the ring had left there - a
	 * phase jump in the analog output, with no underrun counted and
	 * every other counter clean, which is precisely the discontinuity
	 * invariant 5 exists to make impossible. It showed up as steps of
	 * 1000-2500 codes a few times a second in a captured 1 kHz sine
	 * whose largest legitimate step is 43. The producer publishes a
	 * multi-slot DMA span in one go while the consumer drains steadily,
	 * so the margin sawtooths down to exactly this boundary even when
	 * the ring looks comfortable on average.
	 *
	 * Falling one short now counts an underrun and repeats, which is
	 * the honest outcome: a repeated buffer is flagged, unfilled memory
	 * is not.
	 */
	if (play_produced - play_consumed >= 3u) {
		/* The buffer just finished is released; queue the next. */
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
 * driving the converter. gen.c plays a fixed table from flash; play.c
 * plays a ring fed over USB. They are never active at once.
 */
void DACC_Handler(void)
{
	if (active)
		play_endtx();
	else
		gen_endtx();
}

#include <stdio.h>
#include "bsp.h"

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

	printf("# DACC_MR=%08lx TAG=%d MAXS=%d WORD=%d TRGEN=%d TRGSEL=%lu CHSR=%08lx\n",
	       (unsigned long)DACC->DACC_MR,
	       (int)!!(DACC->DACC_MR & DACC_MR_TAG),
	       (int)!!(DACC->DACC_MR & DACC_MR_MAXS),
	       (int)!!(DACC->DACC_MR & DACC_MR_WORD),
	       (int)!!(DACC->DACC_MR & DACC_MR_TRGEN),
	       (unsigned long)((DACC->DACC_MR & DACC_MR_TRGSEL_Msk) >> 1),
	       (unsigned long)DACC->DACC_CHSR);
	printf("# play_dump buf1 fill_off=%lu produced=%lu:\n",
	       (unsigned long)fill_off, (unsigned long)play_produced);
	for (int row = 0; row < 2; row++) {
		printf("#  ");
		for (int i = 0; i < 8; i++) {
			uint16_t v = b[row * 8 + i];
			printf(" %04x(t%u,%4u)", v, (v >> 12) & 3u, v & 0x0fffu);
		}
		printf("\n");
	}
	uart_flush();
}
