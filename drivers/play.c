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
static uint16_t play_buf[PLAY_NBUF][PLAY_BUF_SAMPLES]
	__attribute__((aligned(4), section(".sram1")));

volatile uint32_t play_produced;
volatile uint32_t play_consumed;
volatile uint32_t play_underruns;
volatile uint32_t play_bytes_in;
volatile uint32_t play_isr_calls;
volatile uint32_t play_endtx_seen;
volatile uint32_t play_svc_calls;

static uint32_t fill_off;            /* byte offset into the filling buffer */
static bool     active;
static bool     primed;

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
	if (rc < 2u)
		return false;

	play_stop();

	play_produced = 0;
	play_consumed = 0;
	play_underruns = 0;
	play_bytes_in = 0;
	play_svc_calls = 0;
	fill_off = 0;

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
	active = false;
	TC0->TC_CHANNEL[1].TC_CCR = TC_CCR_CLKDIS;
	DACC->DACC_MR &= ~(DACC_MR_TRGEN | DACC_MR_TRGSEL_Msk);
	DACC->DACC_PTCR = DACC_PTCR_TXTDIS;
	DACC->DACC_IDR = 0xffffffff;
	NVIC_DisableIRQ(DACC_IRQn);
}

/*
 * Drain the bulk OUT endpoint straight into the ring.
 *
 * usb_cdc_read writes into the destination given, so bytes go from the
 * endpoint bank into the playback buffer with no staging copy. Reads are
 * clipped to the remainder of the current buffer so a bank that straddles
 * a boundary is split rather than lost.
 */
void play_service(void)
{
	if (!active)
		return;

	play_svc_calls++;

	for (int budget = 0; budget < 16; budget++) {
		uint8_t *dst;
		uint32_t space;
		size_t got;

		/*
		 * The PDC owns two buffers at once: the one in TPR/TCR that it
		 * is emitting, and the one whose pointer is already latched in
		 * TNPR/TNCR. So the producer may only touch play_consumed + 2
		 * onward, and the reservation is two slots rather than one.
		 *
		 * Reserving only one let the producer overwrite a buffer the
		 * PDC had already latched but not yet started, which looks like
		 * nothing is wrong and emits half-written data.
		 */
		if (play_produced - play_consumed >= PLAY_NBUF - 2u)
			return;

		dst = (uint8_t *)play_buf[play_produced % PLAY_NBUF] + fill_off;
		space = PLAY_BUF_BYTES - fill_off;

		got = usb_cdc_read(dst, space);
		if (got == 0)
			return;

		play_bytes_in += (uint32_t)got;
		fill_off += (uint32_t)got;
		if (fill_off >= PLAY_BUF_BYTES) {
			fill_off = 0;
			/*
			 * Publish. The payload is written through a non-volatile
			 * pointer, so without this barrier the compiler may sink
			 * those stores past the counter increment, and the PDC is
			 * an independent bus master that would then read a buffer
			 * advertised as complete but not yet written.
			 */
			__DMB();
			play_produced++;
		}

		if (!primed && play_produced >= PLAY_PRIME_BUFS) {
			primed = true;
			TC0->TC_CHANNEL[1].TC_CCR = TC_CCR_CLKEN | TC_CCR_SWTRG;
		}
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
	if (play_produced - play_consumed >= 2u) {
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
