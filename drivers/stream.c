/*
 * Framed sample streaming over the bare-metal CDC (Track B).
 *
 * Same wire format as Track A, so the host receiver cannot tell the two
 * apart. The difference is underneath: this path never blocks, because
 * usb_cdc_write refuses rather than spins when the host stops draining.
 */

#include "sam.h"
#include "bsp.h"
#include "acq.h"
#include "gen.h"
#include "frame.h"
#include "play.h"
#include "stream.h"
#include "stream_core.h"
#include "stream_port.h"
#include "usb_cdc.h"
#include <stdio.h>
#include <string.h>

/*
 * Transport selection.
 *
 * The bare-metal UOTGHS stack does not enumerate yet (see docs), so the
 * UART transport exists so that Track B can demonstrate the same
 * end-to-end chain: timer trigger, ADC, PDC, framing, host demux and
 * tone detection. It is bandwidth-limited, not capability-limited - the
 * frame format is byte-identical to Track A's.
 */
typedef enum { XPORT_USB, XPORT_UART } xport_t;
static xport_t  xport;
enum bench_mode { BENCH_OFF, BENCH_FLOOD, BENCH_SINK, BENCH_DUPLEX,
                  BENCH_FLOOD_DMA, BENCH_SINK_DMA, BENCH_DUPLEX_DMA };
static enum bench_mode bench;
static uint32_t bench_in_bytes, bench_out_bytes, bench_t0;
static uint32_t bench_resets;
static uint32_t bench_turn;
static uint16_t bench_payload[ACQ_BUF_SAMPLES];
static uint8_t  bench_scratch[512];

volatile uint32_t stream_loop_passes;
static uint32_t dma_in_arms, dma_out_arms;

/* The bench stamps its own sequence numbers; the capture stream's live
 * in the shared framer now. */
static uint32_t bench_seq;

/* Declared, reset and reported since the file was written, incremented
 * nowhere. Kept so STREAM_STATS's wire layout and its readers do not
 * move in a refactor commit; it reports the 0 it always has. */
static uint32_t refused;

/* The framer - frame building, sequencing, overrun accounting, the
 * resync rule - is lib/due_shared/src/stream_core.c now, one copy for
 * both tracks (issue #14). Its view of the capture ring layout must be
 * this track's. */
_Static_assert(STREAM_NBUF == ACQ_NBUF &&
               STREAM_BUF_SAMPLES == ACQ_BUF_SAMPLES &&
               STREAM_HDR_BYTES == ACQ_HDR_BYTES &&
               STREAM_FRAME_BYTES == ACQ_FRAME_BYTES,
               "stream_port.h ring layout must match acq.h");

/*
 * The shared framer's transport, this track's registers: bare-metal
 * uart/usb_cdc underneath, never the Arduino core's objects.
 */
size_t stream_port_write(const uint8_t *p, size_t n)
{
	if (xport == XPORT_UART) {
		for (size_t i = 0; i < n; i++)
			uart_putc_polled((char)p[i]);
		return n;
	}
	return usb_cdc_write(p, n);
}

bool stream_port_ready(void)
{
	return xport == XPORT_UART ? true : usb_cdc_ready();
}

bool stream_start_uart(uint32_t trigger_hz)
{
	xport = XPORT_UART;
	refused = 0;
	return stream_core_start(trigger_hz, true, 2, false);
}

bool stream_start(uint32_t trigger_hz)
{
	xport = XPORT_USB;
	refused = 0;
	return stream_core_start(trigger_hz, true, 2, true);
}

/*
 * Capture only, leaving the DACC alone so play.c can drive it from the
 * host. This is what makes the full loop possible: generation and
 * capture come from different sources on independent timebases.
 */
bool stream_start_capture_only(uint32_t trigger_hz, unsigned n_channels)
{
	xport = XPORT_USB;
	refused = 0;
	return stream_core_start(trigger_hz, false, n_channels, true);
}

void stream_stop(void)
{
	stream_core_stop();
	if (bench == BENCH_FLOOD_DMA || bench == BENCH_SINK_DMA ||
	    bench == BENCH_DUPLEX_DMA)
		usb_dma_mode(false, false);
	bench = BENCH_OFF;
}

/*
 * Whether a bench mode is consuming bulk OUT. The main loop drains the
 * endpoint when nothing does: a CDC device that stops accepting OUT
 * data wedges the host, because macOS's close() waits for in-flight
 * write URBs that a NAKing pipe never completes - and tcflush cannot
 * recall a URB already handed to the controller.
 */
bool stream_out_in_use(void)
{
	return bench == BENCH_SINK || bench == BENCH_DUPLEX ||
	       bench == BENCH_SINK_DMA || bench == BENCH_DUPLEX_DMA;
}

/*
 * Whether anything is writing bulk IN. The mirror of
 * stream_out_in_use, and it exists for a sharper reason: only this
 * path may write IN while streaming, because the FIFO path owns
 * FIFOCON by hand and DMA needs the hardware to switch banks itself.
 * Anything else that wants to send on IN - the playback status record
 * the rate loop is closed on - has to ask first and stay silent when
 * this is true.
 */
bool stream_in_in_use(void)
{
	return stream_core_active() ||
	       bench == BENCH_FLOOD || bench == BENCH_DUPLEX ||
	       bench == BENCH_FLOOD_DMA || bench == BENCH_DUPLEX_DMA;
}

void stream_bench_service(void);

void stream_service(void)
{
	stream_bench_service();
	stream_core_service();
}


void stream_get_stats(stream_stats_t *out)
{
	stream_core_stats_t cs;

	stream_core_get_stats(&cs);
	out->dma_frames      = cs.dma_frames;
	out->dma_stalls      = cs.dma_stalls;
	out->frames          = cs.frames;
	out->bytes           = cs.bytes;
	out->run_us          = cs.run_us;
	out->produced        = acq_produced;
	out->consumed        = acq_consumed;
	out->ring_overflow   = acq_ring_overflow;
	out->resync          = cs.resync;
	out->refused         = refused;
	out->rxbuff_overruns = acq_rxbuff_overruns;
	out->govre           = acq_govre;
	out->gen_endtx       = gen_endtx_count;
	out->usb_reset       = usb_reset_count;
	out->usb_setup       = usb_setup_count;
	out->usb_stall       = usb_stall_count;
	out->usb_configured  = usb_configured;
	out->usb_line_state  = usb_line_state;
	out->usb_cfg_fail    = usb_cfg_fail;
	out->usb_isr         = usb_isr_count;
	out->usb_devisr      = usb_last_devisr;
	out->usb_ep0isr      = usb_last_ep0isr;
	out->usb_devimr      = usb_devier_snap;
}

/*
 * The throughput division stays on the host. The device reports bytes
 * and microseconds; a rate is arithmetic over two of its counters and
 * nothing about it needs a Cortex-M3 to do it, least of all one that is
 * streaming.
 */
void stream_get_bench(stream_bench_t *out)
{
	out->mode         = (uint32_t)bench;
	out->in_bytes     = bench_in_bytes;
	out->out_bytes    = bench_out_bytes;
	out->elapsed_us   = micros() - bench_t0;
	out->resets       = bench_resets;
	out->turn         = bench_turn;
	out->dma_in_arms  = dma_in_arms;
	out->dma_out_arms = dma_out_arms;
	out->loop_passes  = stream_loop_passes;
}

void stream_report(void)
{
	stream_core_stats_t cs;
	uint32_t us, kbps;

	stream_core_get_stats(&cs);
	us = micros() - cs.started_us;
	kbps = us ? (uint32_t)(((uint64_t)cs.bytes * 1000ull) / us) : 0;

	/*
	 * ADC_MR read back from the peripheral, not echoed from the
	 * variable that was meant to reach it: the track/settling sweep
	 * found neither TRACKTIM nor SETTLING moving issue #5, and a
	 * negative result is only as good as the proof that the knob was
	 * connected. TRACKTIM is bits 27:24, SETTLING 21:20.
	 *
	 * Raw, and sharing this printf, because the cost of a console
	 * command is the bytes it puts on the UART and not the number of
	 * calls - decoding the two fields here read as free and measured
	 * 3.8 ms, a fifth of what `?` cost in total. Invariant 8 is about
	 * exactly that. The host decodes instead.
	 */
	printf("# dma-frames=%lu dma-stalls=%lu adcmr=%08lx acr=%08lx\n",
	       (unsigned long)cs.dma_frames, (unsigned long)cs.dma_stalls,
	       (unsigned long)acq_mr(), (unsigned long)gen_acr());
	printf("# frames=%lu bytes=%lu %lu.%03lu MB/s prod=%lu cons=%lu "
	       "ringovf=%lu resync=%lu refused=%lu rxbuff=%lu govre=%lu "
	       "endtx=%lu rst=%lu setup=%lu stall=%lu cfg=%lu dtr=%lu cfgfail=%lu\n"
	       "# usb isr=%lu devisr=%08lx ep0isr=%08lx devimr=%08lx\n",
	       (unsigned long)cs.frames, (unsigned long)cs.bytes,
	       (unsigned long)(kbps / 1000u), (unsigned long)(kbps % 1000u),
	       (unsigned long)acq_produced, (unsigned long)acq_consumed,
	       (unsigned long)acq_ring_overflow, (unsigned long)cs.resync,
	       (unsigned long)refused,
	       (unsigned long)acq_rxbuff_overruns, (unsigned long)acq_govre,
	       (unsigned long)gen_endtx_count,
	       (unsigned long)usb_reset_count, (unsigned long)usb_setup_count,
	       (unsigned long)usb_stall_count, (unsigned long)usb_configured,
	       (unsigned long)usb_line_state, (unsigned long)usb_cfg_fail,
	       (unsigned long)usb_isr_count, (unsigned long)usb_last_devisr,
	       (unsigned long)usb_last_ep0isr, (unsigned long)usb_devier_snap);
	uart_flush();
}

/* ------------------------------------------------------------------ */
/* Transport benchmarks                                                */
/* ------------------------------------------------------------------ */

static void bench_reset(enum bench_mode m)
{
	stream_stop();
	for (unsigned i = 0; i < ACQ_BUF_SAMPLES; i++)
		bench_payload[i] = (uint16_t)((((i & 1u) ? 6u : 7u) << 12)
		                              | (i & 0x0fffu));
	bench_seq = 0;
	bench_in_bytes = 0;
	bench_out_bytes = 0;
	dma_in_arms = dma_out_arms = 0;
	stream_loop_passes = 0;
	bench_t0 = micros();
	bench_resets++;
	bench = m;
}

void stream_flood_start(void)  { bench_reset(BENCH_FLOOD); }
void stream_sink_start(void)   { bench_reset(BENCH_SINK); }
void stream_duplex_start(void) { bench_reset(BENCH_DUPLEX); }

/*
 * Budgets are expressed in bytes and kept equal between directions.
 *
 * The first duplex measurement gave 2.85 MB/s in and 0.85 out, and that
 * 3.4:1 ratio was very close to the 4:1 ratio of the budgets these two
 * loops were given. An asymmetry produced by the scheduler is not a
 * property of the transport, so the budgets are now matched and the
 * order alternates.
 */
#define BENCH_FRAME_BYTES  (32u + ACQ_BUF_SAMPLES * 2u)

static void bench_push_in(uint32_t byte_budget)
{
	uint32_t sent = 0;

	while (sent < byte_budget) {
		frame_header_t h;
		size_t w1, w2;

		h.magic[0] = FRAME_MAGIC0; h.magic[1] = FRAME_MAGIC1;
		h.magic[2] = FRAME_MAGIC2; h.magic[3] = FRAME_MAGIC3;
		h.version         = FRAME_VERSION;
		h.flags           = FRAME_FLAG_CONTINUOUS;
		h.seq             = bench_seq;
		h.sample_rate_hz  = 0;        /* synthetic, not acquired */
		h.channel_mask    = (1u << 7) | (1u << 6);
		h.timestamp_us    = micros();
		h.overrun_count   = 0;
		h.play_consumed   = 0;
		h.header_crc32 = frame_crc32((const uint8_t *)&h,
		                             sizeof(h) - sizeof(uint32_t));

		w1 = usb_cdc_write((const uint8_t *)&h, sizeof(h));
		if (w1 != sizeof(h))
			return;               /* bank full; resume next call */
		w2 = usb_cdc_write((const uint8_t *)bench_payload,
		                   sizeof(bench_payload));
		bench_in_bytes += w1 + w2;
		sent += (uint32_t)(w1 + w2);
		bench_seq++;
		if (w2 != sizeof(bench_payload))
			return;
	}
}

static void bench_pull_out(uint32_t byte_budget)
{
	uint32_t got_total = 0;

	while (got_total < byte_budget) {
		size_t n = usb_cdc_read(bench_scratch, sizeof(bench_scratch));
		if (n == 0)
			return;
		bench_out_bytes += n;
		got_total += (uint32_t)n;
	}
}

void stream_bench_dma_service(void);

void stream_bench_service(void)
{
	stream_bench_dma_service();

	switch (bench) {
	case BENCH_FLOOD:
		bench_push_in(8u * BENCH_FRAME_BYTES);
		break;
	case BENCH_SINK:
		bench_pull_out(8u * BENCH_FRAME_BYTES);
		break;
	case BENCH_DUPLEX:
		/* Equal byte budgets, and alternate which goes first so
		 * neither direction is systematically favoured. */
		if (bench_turn++ & 1u) {
			bench_push_in(BENCH_FRAME_BYTES);
			bench_pull_out(BENCH_FRAME_BYTES);
		} else {
			bench_pull_out(BENCH_FRAME_BYTES);
			bench_push_in(BENCH_FRAME_BYTES);
		}
		break;
	default: break;
	}
}

void stream_bench_report(void)
{
	/*
	 * Report byte counts only, never a rate.
	 *
	 * The device cannot time its own benchmark reliably: opening the
	 * control port resets the board, so the window start is not related
	 * to when the host began measuring. An earlier version divided by
	 * that bogus window and reported 0.27 MB/s for a transfer the host
	 * had clocked at 3.05 MB/s, with both agreeing on the byte count.
	 *
	 * The byte counts are trustworthy and are what the host needs; it
	 * has its own clock.
	 */
	printf("# bench=%s  IN %lu B   OUT %lu B  passes=%lu arms-in=%lu arms-out=%lu\n",
	       bench == BENCH_FLOOD  ? "flood"  :
	       bench == BENCH_SINK   ? "sink"   :
	       bench == BENCH_DUPLEX ? "duplex" :
	       bench == BENCH_FLOOD_DMA ? "flood-dma" :
	       bench == BENCH_SINK_DMA ? "sink-dma" :
	       bench == BENCH_DUPLEX_DMA ? "duplex-dma" : "off",
	       (unsigned long)bench_in_bytes,
	       (unsigned long)bench_out_bytes,
	       (unsigned long)stream_loop_passes,
	       (unsigned long)dma_in_arms,
	       (unsigned long)dma_out_arms);
	uart_flush();
}


/* ------------------------------------------------------------------ */
/* DMA benchmarks                                                      */
/* ------------------------------------------------------------------ */

/*
 * Double-buffered so nothing blocks: one frame is in flight under DMA
 * while the next is being prepared. The processor writes only the
 * 32-byte header; the 4064-byte payload is never touched by it, which
 * is the property the architecture actually asks for.
 */
#define DMA_FRAME_BYTES  (32u + ACQ_BUF_SAMPLES * 2u)

/*
 * Frames per DMA transfer.
 *
 * One. The re-arm gap between a completed transfer and the main-loop
 * pass that starts the next looked like it should cost several percent
 * on IN, so this was tried at two - and Track A got measurably slower,
 * 28.7-29.7 MB/s against 30.2-31.2. Building a second header per arm
 * costs more than the gap it removes, micros() alone being 1427 ns on
 * that track. Kept as a knob because the experiment is worth being able
 * to repeat, and set to the value that measured best.
 */
#define DMA_FRAMES_PER_XFER 1u
#define DMA_XFER_BYTES   (DMA_FRAME_BYTES * DMA_FRAMES_PER_XFER)

static uint8_t dma_tx[2][DMA_XFER_BYTES] __attribute__((aligned(4)));
static uint8_t dma_rx[2][2048]            __attribute__((aligned(4)));
static uint8_t dma_tx_slot, dma_rx_slot;
static uint32_t dma_in_inflight, dma_out_inflight;

static void dma_build_frame(uint8_t *dst)
{
	frame_header_t *h = (frame_header_t *)dst;

	h->magic[0] = FRAME_MAGIC0; h->magic[1] = FRAME_MAGIC1;
	h->magic[2] = FRAME_MAGIC2; h->magic[3] = FRAME_MAGIC3;
	h->version         = FRAME_VERSION;
	h->flags           = FRAME_FLAG_CONTINUOUS;
	h->seq             = bench_seq++;
	h->sample_rate_hz  = 0;
	h->channel_mask    = (1u << 7) | (1u << 6);
	h->timestamp_us    = micros();
	h->overrun_count   = 0;
	h->play_consumed   = 0;
	h->header_crc32    = frame_crc32(dst, sizeof(*h) - sizeof(uint32_t));
}

static void dma_seed_payloads(void)
{
	for (int s = 0; s < 2; s++)
		for (unsigned f = 0; f < DMA_FRAMES_PER_XFER; f++) {
			uint16_t *p = (uint16_t *)(dma_tx[s]
			                           + f * DMA_FRAME_BYTES + 32u);

			for (unsigned i = 0; i < ACQ_BUF_SAMPLES; i++)
				p[i] = (uint16_t)((((i & 1u) ? 6u : 7u) << 12)
				                  | (i & 0x0fffu));
		}
}

static void dma_push_in(void)
{
	if (usb_dma_in_busy())
		return;
	if (dma_in_inflight) {
		bench_in_bytes += dma_in_inflight - usb_dma_in_residue();
		dma_in_inflight = 0;
	}
	for (unsigned f = 0; f < DMA_FRAMES_PER_XFER; f++)
		dma_build_frame(dma_tx[dma_tx_slot] + f * DMA_FRAME_BYTES);
	if (usb_dma_in_start(dma_tx[dma_tx_slot], DMA_XFER_BYTES)) {
		dma_in_inflight = DMA_XFER_BYTES;
		dma_tx_slot ^= 1u;
		dma_in_arms++;
	}
}

static void dma_pull_out(void)
{
	/* One read: byte count and channel-enabled share the register, and
	 * two reads ask two different instants. See drivers/play.c. */
	uint32_t st = usb_dma_out_status();

	if (st & UOTGHS_DEVDMASTATUS_CHANN_ENB)
		return;
	if (dma_out_inflight) {
		uint32_t left = (st & UOTGHS_DEVDMASTATUS_BUFF_COUNT_Msk)
		                >> UOTGHS_DEVDMASTATUS_BUFF_COUNT_Pos;

		bench_out_bytes += dma_out_inflight > left
		                 ? dma_out_inflight - left : 0;
		dma_out_inflight = 0;
	}
	/*
	 * Stream variant, no END_TR_EN. With it, every short packet the
	 * host's pacing produces ended the transfer, so a 2048-byte buffer
	 * absorbed an average of 347 bytes before needing a re-arm through
	 * the main loop - and that re-arm latency, not the wire, was what
	 * the OUT number measured. The playback ring learned this already;
	 * the bench had not.
	 */
	if (usb_dma_out_start_stream(dma_rx[dma_rx_slot], sizeof(dma_rx[0]))) {
		dma_out_inflight = sizeof(dma_rx[0]);
		dma_rx_slot ^= 1u;
		dma_out_arms++;
	}
}

void stream_flood_dma_start(void)
{
	bench_reset(BENCH_FLOOD_DMA);
	usb_dma_mode(true, false);
	dma_seed_payloads();
	dma_tx_slot = dma_rx_slot = 0;
	dma_in_inflight = dma_out_inflight = 0;
}

void stream_sink_dma_start(void)
{
	bench_reset(BENCH_SINK_DMA);
	usb_dma_mode(false, true);
	dma_tx_slot = dma_rx_slot = 0;
	dma_in_inflight = dma_out_inflight = 0;
}

void stream_duplex_dma_start(void)
{
	bench_reset(BENCH_DUPLEX_DMA);
	usb_dma_mode(true, true);
	dma_seed_payloads();
	dma_tx_slot = dma_rx_slot = 0;
	dma_in_inflight = dma_out_inflight = 0;
}

void stream_bench_dma_service(void)
{
	switch (bench) {
	case BENCH_FLOOD_DMA:  dma_push_in();  break;
	case BENCH_SINK_DMA:   dma_pull_out(); break;
	case BENCH_DUPLEX_DMA: dma_push_in(); dma_pull_out(); break;
	default: break;
	}
}
