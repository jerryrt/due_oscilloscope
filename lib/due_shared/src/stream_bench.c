/*
 * The transport benchmarks, shared.
 *
 * Two families. The CPU arms copy through the FIFO path and exist to
 * measure what that path costs; the DMA arms are double-buffered so
 * nothing blocks - one frame in flight while the next is prepared, the
 * processor writing only the 32-byte header - which is the property
 * the architecture actually asks for.
 *
 * Everything here reaches outside itself through stream_port.h, the
 * same rule as the framer, and the same test holds it to that.
 */
#include <string.h>

#include "frame.h"
#include "stream_bench.h"
#include "stream_core.h"
#include "stream_port.h"

static stream_bench_mode_t bench;
static uint32_t bench_in_bytes, bench_out_bytes, bench_t0;
static uint32_t bench_resets;
static uint32_t bench_turn;
static uint32_t bench_seq;
static uint16_t bench_payload[STREAM_BUF_SAMPLES];
static uint8_t  bench_scratch[512];
static uint32_t dma_in_arms, dma_out_arms;

/*
 * Budgets are expressed in bytes and kept equal between directions:
 * an asymmetry produced by unequal budgets is not a property of the
 * transport, so the two are matched and the order alternates.
 */
#define BENCH_FRAME_BYTES  (32u + STREAM_BUF_SAMPLES * 2u)

/*
 * Frames per DMA transfer. One measured best: building a second header
 * per arm costs more than the re-arm gap it would remove. Kept as a
 * knob so the experiment can be repeated.
 */
#define DMA_FRAME_BYTES     (32u + STREAM_BUF_SAMPLES * 2u)
#define DMA_FRAMES_PER_XFER 1u
#define DMA_XFER_BYTES      (DMA_FRAME_BYTES * DMA_FRAMES_PER_XFER)

static uint8_t dma_tx[2][DMA_XFER_BYTES] __attribute__((aligned(4)));
static uint8_t dma_rx[2][2048]           __attribute__((aligned(4)));
static uint8_t dma_tx_slot, dma_rx_slot;
static uint32_t dma_in_inflight, dma_out_inflight;

stream_bench_mode_t stream_bench_mode(void)
{
	return bench;
}

void stream_bench_get_stats(stream_bench_stats_t *out)
{
	out->mode         = (uint32_t)bench;
	out->in_bytes     = bench_in_bytes;
	out->out_bytes    = bench_out_bytes;
	out->elapsed_us   = micros() - bench_t0;
	out->resets       = bench_resets;
	out->turn         = bench_turn;
	out->dma_in_arms  = dma_in_arms;
	out->dma_out_arms = dma_out_arms;
}

void stream_bench_stop(void)
{
	if (bench == STREAM_BENCH_FLOOD_DMA || bench == STREAM_BENCH_SINK_DMA ||
	    bench == STREAM_BENCH_DUPLEX_DMA)
		usb_dma_mode(false, false);
	bench = STREAM_BENCH_OFF;
}

static void dma_build_frame(uint8_t *dst)
{
	frame_header_t *h = (frame_header_t *)dst;

	h->magic[0] = FRAME_MAGIC0; h->magic[1] = FRAME_MAGIC1;
	h->magic[2] = FRAME_MAGIC2; h->magic[3] = FRAME_MAGIC3;
	h->version         = FRAME_VERSION;
	h->flags           = FRAME_FLAG_CONTINUOUS;
	h->seq             = bench_seq++;
	h->sample_rate_hz  = 0;          /* synthetic, not acquired */
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

			for (unsigned i = 0; i < STREAM_BUF_SAMPLES; i++)
				p[i] = (uint16_t)((((i & 1u) ? 6u : 7u) << 12)
				                  | (i & 0x0fffu));
		}
}

void stream_bench_start(stream_bench_mode_t m)
{
	stream_core_stop();
	stream_bench_stop();

	/* A recognisable ramp, so a desynchronised host is obvious. */
	for (unsigned i = 0; i < STREAM_BUF_SAMPLES; i++)
		bench_payload[i] = (uint16_t)((((i & 1u) ? 6u : 7u) << 12)
		                              | (i & 0x0fffu));
	bench_seq = 0;
	bench_in_bytes = 0;
	bench_out_bytes = 0;
	dma_in_arms = dma_out_arms = 0;
	stream_loop_passes = 0;
	bench_t0 = micros();
	bench_resets++;

	switch (m) {
	case STREAM_BENCH_FLOOD_DMA:
		usb_dma_mode(true, false);
		dma_seed_payloads();
		break;
	case STREAM_BENCH_SINK_DMA:
		usb_dma_mode(false, true);
		break;
	case STREAM_BENCH_DUPLEX_DMA:
		usb_dma_mode(true, true);
		dma_seed_payloads();
		break;
	default:
		break;
	}
	dma_tx_slot = dma_rx_slot = 0;
	dma_in_inflight = dma_out_inflight = 0;

	bench = m;
}

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

		w1 = usb_port_write((const uint8_t *)&h, sizeof(h));
		if (w1 != sizeof(h))
			return;               /* bank full; resume next call */
		w2 = usb_port_write((const uint8_t *)bench_payload,
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
		size_t n = usb_port_read(bench_scratch, sizeof(bench_scratch));
		if (n == 0)
			return;
		bench_out_bytes += n;
		got_total += (uint32_t)n;
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
	uint32_t left;

	if (!usb_dma_out_done(&left))
		return;
	if (dma_out_inflight) {
		bench_out_bytes += dma_out_inflight > left
		                 ? dma_out_inflight - left : 0;
		dma_out_inflight = 0;
	}
	/*
	 * Stream variant, no END_TR_EN: with it, every short packet the
	 * host's pacing produces ends the transfer, so a large buffer
	 * absorbs only a fraction of its capacity before needing a re-arm -
	 * and re-arm latency, not the wire, is what the OUT number would
	 * then measure.
	 */
	if (usb_dma_out_start_stream(dma_rx[dma_rx_slot], sizeof(dma_rx[0]))) {
		dma_out_inflight = sizeof(dma_rx[0]);
		dma_rx_slot ^= 1u;
		dma_out_arms++;
	}
}

void stream_bench_service(void)
{
	switch (bench) {
	case STREAM_BENCH_FLOOD:
		bench_push_in(8u * BENCH_FRAME_BYTES);
		break;
	case STREAM_BENCH_SINK:
		bench_pull_out(8u * BENCH_FRAME_BYTES);
		break;
	case STREAM_BENCH_DUPLEX:
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
	case STREAM_BENCH_FLOOD_DMA:
		usb_dma_keepalive();
		dma_push_in();
		break;
	case STREAM_BENCH_SINK_DMA:
		usb_dma_keepalive();
		dma_pull_out();
		break;
	case STREAM_BENCH_DUPLEX_DMA:
		usb_dma_keepalive();
		dma_push_in();
		dma_pull_out();
		break;
	default:
		break;
	}
}
