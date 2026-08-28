/*
 * Binary sample streaming over the native USB port.
 *
 * A finished frame goes out by endpoint DMA: 4096 contiguous bytes -
 * the header written into the headroom in front of the payload - read
 * straight out of the capture ring by the controller, with the
 * processor never touching a sample. Same shape as Track B, which is
 * the point; the two tracks share no source and stay comparable by
 * being transliterations of each other.
 *
 * The SerialUSB path below it stays for the UART transport and for a
 * host that has not configured the endpoints. It copies into the
 * endpoint FIFO a byte at a time, so it is not a sample path; it is a
 * fallback that keeps working when the DMA one cannot be claimed.
 *
 * Control and logging stay on the programming port so that a stray
 * print can never corrupt a frame.
 */

#include <Arduino.h>
#include "acq.h"
#include "gen.h"
#include "frame.h"
#include "play.h"
#include "stream.h"
#include "stream_core.h"
#include "stream_port.h"
#include "usbdma.h"

/*
 * Transport selection. The UART variant exists for the same reason it
 * does in Track B: it demonstrates the whole chain - timer trigger,
 * ADC, PDC, framing, host demux - on a link that cannot be blamed for
 * anything. It is bandwidth-limited, not capability-limited; the frames
 * are byte-identical.
 */
typedef enum { XPORT_USB, XPORT_UART } xport_t;
static xport_t xport;

enum bench_mode { BENCH_OFF, BENCH_FLOOD, BENCH_SINK, BENCH_DUPLEX,
                  BENCH_FLOOD_DMA, BENCH_SINK_DMA, BENCH_DUPLEX_DMA };
static bench_mode bench;
static uint32_t bench_in_bytes, bench_out_bytes, bench_t0, bench_turn;
static uint16_t bench_payload[ACQ_BUF_SAMPLES];
static uint8_t  bench_scratch[512];

volatile uint32_t stream_loop_passes;
static uint32_t dma_in_arms, dma_out_arms;

/* The bench stamps its own sequence numbers; the capture stream's live
 * in the shared framer now. */
static uint32_t bench_seq;

/* The framer - frame building, sequencing, overrun accounting, the
 * resync rule - is lib/due_shared/src/stream_core.c now, one copy for
 * both tracks (issue #14). Its view of the capture ring layout must be
 * this track's. */
static_assert(STREAM_NBUF == ACQ_NBUF &&
              STREAM_BUF_SAMPLES == ACQ_BUF_SAMPLES &&
              STREAM_HDR_BYTES == ACQ_HDR_BYTES &&
              STREAM_FRAME_BYTES == ACQ_FRAME_BYTES,
              "stream_port.h ring layout must match acq.h");

/*
 * The shared framer's transport, this track's plumbing: the core's
 * Serial objects underneath, which is exactly what Track B must never
 * link.
 */
size_t stream_port_write(const uint8_t *p, size_t n)
{
	if (xport == XPORT_UART) {
		Serial.write(p, n);
		return n;
	}
	{
		size_t w = SerialUSB.write(p, n);

		if (w)
			usb_in_activity++;
		return w;
	}
}

/*
 * Whether the transport can accept anything at all.
 *
 * Do NOT use (bool)SerialUSB for this. Serial_::operator bool() ends
 * with delay(10), so calling it once per service pass costs ten
 * milliseconds of pure sleep and was, by itself, the reason this path
 * once appeared to cap at about half the link rate: time spent inside
 * the write corresponded to nearly 9 MB/s, and the ceiling was the
 * guard. dtr() reads the same lineState with no delay.
 */
bool stream_port_ready(void)
{
	return xport == XPORT_UART ? true : SerialUSB.dtr();
}

/*
 * Capture without touching the DAC, so the DACC can be left running on
 * its own independent timebase. This is what makes the full loop
 * possible: generation and capture come from different sources.
 */
bool stream_start_capture_only(uint32_t trigger_hz, unsigned n_channels)
{
	xport = XPORT_USB;
	return stream_core_start(trigger_hz, false, n_channels, true);
}

bool stream_start(uint32_t trigger_hz)
{
	xport = XPORT_USB;
	return stream_core_start(trigger_hz, true, 2, true);
}

bool stream_start_uart(uint32_t trigger_hz)
{
	xport = XPORT_UART;
	return stream_core_start(trigger_hz, true, 2, false);
}

void stream_stop(void)
{
	stream_core_stop();
	if (bench == BENCH_FLOOD_DMA || bench == BENCH_SINK_DMA ||
	    bench == BENCH_DUPLEX_DMA)
		usb_dma_mode(false, false);
	bench = BENCH_OFF;
}

bool stream_active(void)
{
	return stream_core_active();
}

/*
 * Whether a bench mode is consuming bulk OUT. The main loop drains the
 * endpoint when nothing does: a CDC device that stops accepting OUT
 * data wedges the host, because macOS's close() waits for in-flight
 * write URBs that a NAKing pipe never completes.
 */
bool stream_in_in_use(void)
{
	return stream_core_active() ||
	       bench == BENCH_FLOOD || bench == BENCH_DUPLEX ||
	       bench == BENCH_FLOOD_DMA || bench == BENCH_DUPLEX_DMA;
}

bool stream_out_in_use(void)
{
	return bench == BENCH_SINK || bench == BENCH_DUPLEX ||
	       bench == BENCH_SINK_DMA || bench == BENCH_DUPLEX_DMA;
}

/*
 * Called from the main loop. Sends at most a few frames per call so the
 * command interface stays responsive.
 */
void stream_bench_service(void);

void stream_service(void)
{
	stream_bench_service();
	stream_core_service();
}


int stream_dma_report(char *buf, size_t n)
{
	stream_core_stats_t cs;

	stream_core_get_stats(&cs);
	return snprintf(buf, n, "# dma-frames=%lu dma-stalls=%lu",
	                (unsigned long)cs.dma_frames,
	                (unsigned long)cs.dma_stalls);
}

void stream_report(char *buf, size_t n)
{
	stream_core_stats_t cs;
	uint32_t us, kbps;

	stream_core_get_stats(&cs);
	us = micros() - cs.started_us;
	kbps = us ? (uint32_t)(((uint64_t)cs.bytes * 1000ull) / us) : 0;

	snprintf(buf, n,
	         "# frames=%lu bytes=%lu %lu.%03lu MB/s prod=%lu cons=%lu "
	         "ringovf=%lu resync=%lu rxbuff=%lu govre=%lu endtx=%lu "
	         "wfail=%lu wshort=%lu dtr=%d inwrite=%lu.%03lu MB/s (cpu path)",
	         (unsigned long)cs.frames, (unsigned long)cs.bytes,
	         (unsigned long)(kbps / 1000u), (unsigned long)(kbps % 1000u),
	         (unsigned long)acq_produced, (unsigned long)acq_consumed,
	         (unsigned long)acq_ring_overflow,
	         (unsigned long)cs.resync,
	         (unsigned long)acq_rxbuff_overruns,
	         (unsigned long)acq_govre,
	         (unsigned long)gen_endtx_count,
	         (unsigned long)cs.write_fail, (unsigned long)cs.short_write,
	         /* dtr() reads lineState directly; (bool)SerialUSB would
	          * report the same thing after a delay(10). */
	         (int)SerialUSB.dtr(),
	         (unsigned long)(cs.usb_us ? ((uint64_t)cs.usb_bytes * 1000ull / cs.usb_us) / 1000u : 0),
	         (unsigned long)(cs.usb_us ? ((uint64_t)cs.usb_bytes * 1000ull / cs.usb_us) % 1000u : 0));
}

/* ------------------------------------------------------------------ */
/* Transport benchmarks                                                */
/* ------------------------------------------------------------------ */

static void bench_reset(bench_mode m)
{
	stream_stop();
	/* A recognisable ramp, so a desynchronised host is obvious. */
	for (unsigned i = 0; i < ACQ_BUF_SAMPLES; i++)
		bench_payload[i] = (uint16_t)((((i & 1u) ? 6u : 7u) << 12)
		                              | (i & 0x0fffu));
	bench_seq = 0;
	bench_in_bytes = 0;
	bench_out_bytes = 0;
	dma_in_arms = dma_out_arms = 0;
	stream_loop_passes = 0;
	bench_t0 = micros();
	bench = m;
}

void stream_flood_start(void)  { bench_reset(BENCH_FLOOD); }
void stream_sink_start(void)   { bench_reset(BENCH_SINK); }
void stream_duplex_start(void) { bench_reset(BENCH_DUPLEX); }

/*
 * Budgets are expressed in bytes and kept equal between directions.
 *
 * Track B's first duplex measurement gave a 3.4:1 ratio that turned out
 * to be very close to the 4:1 ratio of the budgets the two loops had
 * been given. An asymmetry produced by the scheduler is not a property
 * of the transport, so the budgets are matched and the order alternates.
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
		h.sample_rate_hz  = 0;          /* synthetic, not acquired */
		h.channel_mask    = (1u << 7) | (1u << 6);
		h.timestamp_us    = micros();
		h.overrun_count   = 0;
		h.play_consumed   = 0;
		h.header_crc32 = frame_crc32((const uint8_t *)&h,
		                             sizeof(h) - sizeof(uint32_t));

		w1 = SerialUSB.write((const uint8_t *)&h, sizeof(h));
		if (w1 != sizeof(h))
			return;                 /* pipe closed; resume next call */
		w2 = SerialUSB.write((const uint8_t *)bench_payload,
		                     sizeof(bench_payload));
		bench_in_bytes += w1 + w2;
		sent += (uint32_t)(w1 + w2);
		bench_seq++;
		if (w2 != sizeof(bench_payload))
			return;
	}
}

/*
 * Drain through Serial_::read rather than readBytes: Stream::readBytes
 * goes through timedRead, which calls millis() per byte and turns a
 * transport measurement into a measurement of the timeout helper.
 */
static void bench_pull_out(uint32_t byte_budget)
{
	uint32_t got_total = 0;

	while (got_total < byte_budget) {
		int avail = SerialUSB.available();
		int n, i;

		if (avail <= 0)
			return;
		n = avail > (int)sizeof(bench_scratch) ?
		    (int)sizeof(bench_scratch) : avail;
		for (i = 0; i < n; i++) {
			int c = SerialUSB.read();
			if (c < 0)
				break;
			bench_scratch[i] = (uint8_t)c;
		}
		if (i)
			usb_out_activity++;
		bench_out_bytes += (uint32_t)i;
		got_total += (uint32_t)i;
		if (i < n)
			return;
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
	default:
		break;
	}
}

void stream_bench_report(char *buf, size_t n)
{
	/*
	 * Report byte counts only, never a rate.
	 *
	 * The device cannot time its own benchmark reliably: opening the
	 * control port resets the board, so the window start is unrelated
	 * to when the host began measuring. Track B once divided by that
	 * bogus window and reported 0.27 MB/s for a transfer the host had
	 * clocked at 3.05 MB/s, with both agreeing on the byte count.
	 */
	(void)bench_t0;
	snprintf(buf, n,
	         "# bench=%s  IN %lu B   OUT %lu B  passes=%lu arms-in=%lu arms-out=%lu "
	         "rebuilds=%lu inbusy=%d",
	         bench == BENCH_FLOOD  ? "flood"  :
	         bench == BENCH_SINK   ? "sink"   :
	         bench == BENCH_DUPLEX ? "duplex" :
	         bench == BENCH_FLOOD_DMA  ? "flood-dma"  :
	         bench == BENCH_SINK_DMA   ? "sink-dma"   :
	         bench == BENCH_DUPLEX_DMA ? "duplex-dma" : "off",
	         (unsigned long)bench_in_bytes,
	         (unsigned long)bench_out_bytes,
	         (unsigned long)stream_loop_passes,
	         (unsigned long)dma_in_arms,
	         (unsigned long)dma_out_arms,
	         (unsigned long)usbdma_rebuilds,
	         (int)usb_dma_in_busy());
}

/* ------------------------------------------------------------------ */
/* DMA benchmarks                                                      */
/* ------------------------------------------------------------------ */

/*
 * Double-buffered so nothing blocks: one frame is in flight under DMA
 * while the next is being prepared. The processor writes only the
 * 32-byte header; the 4064-byte payload is never touched by it, which
 * is the property the architecture actually asks for - and the one the
 * core's byte-at-a-time FIFO copy cannot provide at any rate.
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

static void dma_bench_reset(bench_mode m, bool in_dma, bool out_dma)
{
	bench_reset(m);
	usb_dma_mode(in_dma, out_dma);
	if (in_dma)
		dma_seed_payloads();
	dma_tx_slot = dma_rx_slot = 0;
	dma_in_inflight = dma_out_inflight = 0;
}

void stream_flood_dma_start(void)
{
	dma_bench_reset(BENCH_FLOOD_DMA, true, false);
}

void stream_sink_dma_start(void)
{
	dma_bench_reset(BENCH_SINK_DMA, false, true);
}

void stream_duplex_dma_start(void)
{
	dma_bench_reset(BENCH_DUPLEX_DMA, true, true);
}

void stream_bench_dma_service(void)
{
	switch (bench) {
	case BENCH_FLOOD_DMA:  usbdma_keepalive(); dma_push_in();  break;
	case BENCH_SINK_DMA:   usbdma_keepalive(); dma_pull_out(); break;
	case BENCH_DUPLEX_DMA: usbdma_keepalive();
	                       dma_push_in(); dma_pull_out(); break;
	default: break;
	}
}
