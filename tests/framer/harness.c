/*
 * A test with power over 5d6e7ab, which is what that commit asked for
 * and did not have.
 *
 * The fix stops stream_core_service()'s not-ready path releasing the
 * head buffer while a USB DMA is reading it. It was found by reading,
 * and the commit says plainly that no test exercises the window.
 * tools/soak_close_stream.py cannot: it is identical on the pre-fix
 * image, because the corrupted bytes go to a host that has already
 * closed and the stop that follows resets all framer state. So the
 * window has to be driven, not soaked.
 *
 * stream_port.h is a complete record of what the framer reaches
 * outside itself - that is the property issue #14 built it for - so
 * the whole seam mocks on a host compiler and the state machine can be
 * stepped one service call at a time.
 *
 * Two things are asserted, matching the commit's two consequences:
 *
 *   1. the head buffer is not released while the DMA that owns it is
 *      still running;
 *   2. no header is memcpy'd into a buffer while that DMA is running.
 *
 * And the harness reports whether the framer still makes progress once
 * the transfer completes, so "wait" cannot be satisfied by wedging.
 *
 * Built twice by tests/test_framer_close.py: once against the real
 * stream_core.c and once against a copy with the guard removed. The
 * mutant must fail, or this file is decoration - see #28's "measure
 * your test's power, not just its result".
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "stream_core.h"
#include "stream_port.h"

/* --- the mocked world -------------------------------------------- */

static uint8_t  ring[STREAM_NBUF][STREAM_FRAME_BYTES];
static unsigned head;                 /* which buffer acq hands out */

static bool     mock_ready = true;    /* DTR */
static bool     mock_busy;            /* a DMA is reading the head */
static bool     mock_available = true;

static unsigned n_release;            /* acq_frame_release() calls */
static unsigned n_dma_start;
static unsigned n_write_while_busy;   /* the corruption, counted */
static unsigned n_release_while_busy; /* the other one */

volatile uint32_t acq_produced, acq_consumed;
volatile uint32_t acq_rxbuff_overruns, acq_govre, acq_ring_overflow;
volatile uint32_t play_consumed;
volatile uint32_t stream_loop_passes;
uint32_t SystemCoreClock = 78000000u;

void     acq_init(void) { }
bool     acq_start(uint32_t hz, unsigned n) { (void)hz; (void)n; return true; }
void     acq_stop(void) { }
uint16_t acq_channel_mask(void) { return 0x3u; }
uint32_t acq_configured_rc(void) { return 195u; }
bool     acq_frame_available(void) { return mock_available; }
uint8_t *acq_frame_bytes(void) { return ring[head]; }
const uint16_t *acq_frame_data(void) { return (const uint16_t *)ring[head]; }

void acq_frame_release(void)
{
	if (mock_busy)
		n_release_while_busy++;
	n_release++;
	acq_consumed++;
	head = (head + 1u) % STREAM_NBUF;
	/* One frame at a time: the producer is not the thing under test. */
	mock_available = false;
}

void gen_init(void) { }
void gen_start(void) { }
void gen_stop(void) { }

bool usb_dma_in_busy(void) { return mock_busy; }

bool usb_dma_in_start(const void *buf, uint32_t len)
{
	(void)buf; (void)len;
	n_dma_start++;
	mock_busy = true;            /* the controller now owns the head */
	return true;
}

void usb_dma_mode_in(bool on) { (void)on; }

size_t stream_port_write(const uint8_t *p, size_t n) { (void)p; return n; }
bool   stream_port_ready(void) { return mock_ready; }

size_t usb_port_write(const uint8_t *p, size_t n) { (void)p; return n; }
size_t usb_port_read(uint8_t *p, size_t n) { (void)p; (void)n; return 0; }
uint32_t usb_dma_in_residue(void) { return 0; }
bool usb_dma_out_start_stream(void *b, uint32_t l) { (void)b; (void)l; return false; }
bool usb_dma_out_done(uint32_t *left) { (void)left; return true; }
void usb_dma_mode(bool i, bool o) { (void)i; (void)o; }
void usb_dma_keepalive(void) { }

static uint32_t now_us;
uint32_t micros(void) { return now_us += 100u; }

/*
 * The corruption is a write into a buffer a DMA is sourcing, so watch
 * the bytes rather than trusting the state machine to confess. The
 * head is stamped with a canary the moment a transfer starts; anything
 * that disturbs it while mock_busy is a write into an active source.
 */
static uint8_t canary[STREAM_HDR_BYTES];

static void arm_canary(void)
{
	memset(canary, 0xA5, sizeof(canary));
	memcpy(ring[head], canary, sizeof(canary));
}

static void check_canary(void)
{
	if (mock_busy && memcmp(ring[head], canary, sizeof(canary)) != 0)
		n_write_while_busy++;
}

int main(void)
{
	int fail = 0;

	if (!stream_core_start(200000u, false, 2u, true)) {
		printf("FAIL start\n");
		return 1;
	}

	/* One service call takes an available frame to TX_DMA and arms a
	 * transfer, which leaves the controller owning the head. */
	acq_produced = 1;
	mock_available = true;
	stream_core_service();
	if (n_dma_start == 0 || !mock_busy) {
		printf("FAIL setup: no DMA armed (starts=%u busy=%d)\n",
		       n_dma_start, (int)mock_busy);
		return 1;
	}

	/* The host closes the port mid-transfer. DTR drops from the USB
	 * ISR, so the very next service call takes the not-ready path
	 * with the transfer still running. */
	arm_canary();
	mock_ready = false;

	stream_core_service();
	check_canary();
	stream_core_service();      /* the pre-fix TX_IDLE header write */
	check_canary();

	if (n_release_while_busy) {
		printf("FAIL released the head buffer while its DMA ran "
		       "(%u times)\n", n_release_while_busy);
		fail = 1;
	}
	if (n_write_while_busy) {
		printf("FAIL wrote a header into an active DMA source "
		       "(%u times)\n", n_write_while_busy);
		fail = 1;
	}

	/* Waiting must not mean wedging: once the controller lets go, the
	 * frame is released and the framer returns to idle. */
	mock_busy = false;
	stream_core_service();
	if (n_release == 0) {
		printf("FAIL never released after the DMA completed\n");
		fail = 1;
	}

	printf("%s releases=%u while_busy=%u header_writes_while_busy=%u\n",
	       fail ? "FAIL" : "PASS", n_release, n_release_while_busy,
	       n_write_while_busy);
	return fail;
}
