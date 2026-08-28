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

static bool     active;
static uint32_t seq;
static uint32_t rate_hz;
static uint32_t frames_sent;
static uint32_t bytes_sent;
static uint32_t started_us;
static uint32_t pending_overrun;
static uint32_t write_fail;
static uint32_t short_write;
static uint32_t resync_count;
static uint32_t usb_us;
static uint32_t usb_bytes;

/*
 * A CDC pipe is a byte stream with no frame boundaries, so a short write
 * is not something the receiver can recover from: it loses byte
 * alignment and starts misreading channel tags. Transmission is
 * therefore resumable across service calls and never abandoned
 * part-way, exactly as in Track B.
 */
typedef enum { TX_IDLE, TX_HEADER, TX_PAYLOAD, TX_DMA } tx_phase_t;
static tx_phase_t     tx_phase;
static size_t         tx_off;
static frame_header_t tx_hdr;

/* The headroom in front of each capture buffer is sized in acq.h,
 * which cannot see this type. If they ever disagree the header would
 * be written over the first samples of its own payload. */
static_assert(sizeof(frame_header_t) == ACQ_HDR_BYTES,
              "capture header headroom must match the frame header");

static bool     tx_dma;
static uint32_t dma_frames, dma_stalls;

/*
 * How much of a frame goes out per DMA transfer.
 *
 * One 4096-byte transfer measurably starves the ADC's PDC: measured on
 * Track B, 439 general overruns in a 4 s run at the full rate against
 * none on the CPU-copy path, because the USB DMA holds the bus matrix
 * while the PDC is trying to write the next conversion into SRAM.
 * Moving the capture ring to the other bank halved it, which named the
 * mechanism, and smaller transfers give the PDC gaps to win arbitration
 * in.
 *
 * 512 keeps every transfer exactly one bulk packet, so the stream stays
 * packet-aligned and no short packet is ever emitted mid-frame.
 */
#define DMA_CHUNK_BYTES  512u

static bool stream_start_common(uint32_t trigger_hz, bool with_gen,
                                unsigned n_channels);

static size_t xport_write(const uint8_t *p, size_t n)
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
static bool xport_ready(void)
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
	return stream_start_common(trigger_hz, false, n_channels);
}

bool stream_start(uint32_t trigger_hz)
{
	xport = XPORT_USB;
	return stream_start_common(trigger_hz, true, 2);
}

bool stream_start_uart(uint32_t trigger_hz)
{
	xport = XPORT_UART;
	return stream_start_common(trigger_hz, true, 2);
}

static bool stream_start_common(uint32_t trigger_hz, bool with_gen,
                                unsigned n_channels)
{
	acq_init();
	if (with_gen)
		gen_init();

	seq = 0;
	frames_sent = 0;
	bytes_sent = 0;
	pending_overrun = 0;
	write_fail = 0;
	short_write = 0;
	resync_count = 0;
	usb_us = 0;
	usb_bytes = 0;
	tx_phase = TX_IDLE;
	tx_off = 0;
	if (!acq_start(trigger_hz, n_channels))
		return false;

	/*
	 * Report the rate the hardware will actually produce, not the one
	 * that was asked for. The trigger is TC compare, so the rate is
	 * 39 MHz / RC and a request that does not divide 39 MHz truncates:
	 * asking for 210000 gets RC 185 and 210810 conversions per second.
	 * Declaring the request in the header makes every frequency the
	 * host derives from it wrong by the same fraction, silently, which
	 * is exactly the failure the exact-divisor rule exists to avoid.
	 */
	rate_hz = (SystemCoreClock / 2u) / acq_configured_rc();

	if (with_gen)
		gen_start();

	started_us = micros();

	/*
	 * Take the IN endpoint onto DMA for the duration. Only this path
	 * writes IN while streaming, and the two modes must never be mixed
	 * on one endpoint: the core's writer owns the FIFO by hand and DMA
	 * needs the hardware to switch banks itself.
	 */
	tx_dma = (xport == XPORT_USB);
	dma_frames = dma_stalls = 0;
	if (tx_dma)
		usb_dma_mode_in(true);

	active = true;
	return true;
}

void stream_bench_service(void);

void stream_stop(void)
{
	active = false;
	if (tx_dma) {
		/*
		 * Do NOT spin on "is the channel still busy" here. It was
		 * written that way first and it is an unbounded wait on a
		 * peer: if the host has stopped reading IN, the transfer
		 * never completes and the stop command never returns, which
		 * is invariant 7 broken on the one path a wedged host is
		 * most likely to reach. usb_dma_mode_in(false) aborts the
		 * channel through dma_channel_stop(), whose spin is bounded,
		 * and an aborted transfer stops reading the buffer just as
		 * surely as a finished one does. The worst case is one
		 * corrupted frame already on the wire; the alternative is a
		 * board that has to be power-cycled.
		 */
		usb_dma_mode_in(false);
		tx_dma = false;
	}
	tx_phase = TX_IDLE;
	tx_off = 0;
	if (bench == BENCH_FLOOD_DMA || bench == BENCH_SINK_DMA ||
	    bench == BENCH_DUPLEX_DMA)
		usb_dma_mode(false, false);
	bench = BENCH_OFF;
	acq_stop();
	gen_stop();
}

bool stream_active(void)
{
	return active;
}

/*
 * Whether a bench mode is consuming bulk OUT. The main loop drains the
 * endpoint when nothing does: a CDC device that stops accepting OUT
 * data wedges the host, because macOS's close() waits for in-flight
 * write URBs that a NAKing pipe never completes.
 */
bool stream_in_in_use(void)
{
	return stream_active() || bench == BENCH_FLOOD || bench == BENCH_DUPLEX ||
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
void stream_service(void)
{
	stream_bench_service();

	if (!active)
		return;

	/*
	 * With the port closed, discard rather than queue. Serial_::write
	 * already returns 0 without blocking when the host has not set
	 * lineState, but a frame half-way through transmission would then
	 * sit in TX_HEADER forever while the PDC laps the ring behind it.
	 * Dropping keeps the counters honest: the frames are gone either
	 * way, and the ones that follow stay continuous.
	 *
	 * The genuine hazard is a host that holds the port open and stops
	 * reading, and no API here detects that.
	 */
	if (!xport_ready()) {
		while (acq_frame_available())
			acq_frame_release();
		tx_phase = TX_IDLE;
		tx_off = 0;
		return;
	}

	for (int budget = 0; budget < 4; budget++) {
		const uint8_t *payload;
		size_t plen = ACQ_BUF_SAMPLES * sizeof(uint16_t);
		uint32_t t_in;
		size_t w;

		/*
		 * A DMA in flight owns the buffer it is reading, so the frame
		 * is not released and the next one is not started until it
		 * has finished. Releasing early would hand the PDC a buffer
		 * the USB controller is still sending.
		 */
		if (tx_phase == TX_DMA) {
			uint8_t *frame = acq_frame_bytes();

			if (usb_dma_in_busy())
				return;
			if (tx_off < ACQ_FRAME_BYTES) {
				uint32_t n = ACQ_FRAME_BYTES - tx_off;

				if (n > DMA_CHUNK_BYTES)
					n = DMA_CHUNK_BYTES;
				/*
				 * Deliberately not counted into usb_us /
				 * usb_bytes. Arming a DMA is four register
				 * writes and returns long before the bytes
				 * are on the wire, so timing it and dividing
				 * reports the speed of the register file:
				 * 145 MB/s on a 1.8 MB/s link, which is
				 * worse than no figure at all. `inwrite` in
				 * the report describes the CPU write path
				 * and nothing else.
				 */
				if (!usb_dma_in_start(frame + tx_off, n)) {
					dma_stalls++;
					return;
				}
				tx_off += n;
				continue;
			}
			bytes_sent += ACQ_FRAME_BYTES;
			tx_off = 0;
			tx_phase = TX_IDLE;
			acq_frame_release();
			frames_sent++;
			dma_frames++;
			seq++;
			continue;
		}

		/*
		 * Start a new frame only when the previous one is fully out.
		 *
		 * Everything that selects a buffer or builds a header happens
		 * here and nowhere else. Re-running the lap check while a
		 * frame is in flight would move acq_consumed, and with it the
		 * payload pointer, out from under the transfer.
		 */
		if (tx_phase == TX_IDLE) {
			uint32_t produced, overruns;

			if (!acq_frame_available())
				return;

			produced = acq_produced;

			/*
			 * If the ISR has lapped us, the oldest unsent buffers are
			 * being overwritten by the PDC as we read them. Sending
			 * one anyway yields a frame that passes its header CRC
			 * while carrying spliced data, which is exactly the silent
			 * corruption the protocol exists to prevent. Skip forward
			 * to the newest safe buffer and flag the discontinuity.
			 */
			if (produced - acq_consumed >= ACQ_NBUF - 1u) {
				acq_consumed = produced - (ACQ_NBUF - 2u);
				resync_count++;
			}

			overruns = acq_rxbuff_overruns + acq_govre +
			           acq_ring_overflow + resync_count;

			tx_hdr.magic[0] = FRAME_MAGIC0;
			tx_hdr.magic[1] = FRAME_MAGIC1;
			tx_hdr.magic[2] = FRAME_MAGIC2;
			tx_hdr.magic[3] = FRAME_MAGIC3;
			tx_hdr.version         = FRAME_VERSION;
			tx_hdr.flags           = FRAME_FLAG_CONTINUOUS;
			tx_hdr.seq             = seq;
			tx_hdr.sample_rate_hz  = rate_hz;
			tx_hdr.channel_mask    = acq_channel_mask();
			tx_hdr.timestamp_us    = micros();
			tx_hdr.overrun_count   = overruns;
			tx_hdr.play_consumed   = play_consumed;

			if (overruns != pending_overrun) {
				tx_hdr.flags |= FRAME_FLAG_OVERRUN;
				pending_overrun = overruns;
			}

			tx_hdr.header_crc32 =
				frame_crc32((const uint8_t *)&tx_hdr,
				            sizeof(tx_hdr) - sizeof(uint32_t));

			tx_off = 0;
			tx_phase = TX_HEADER;

			if (tx_dma) {
				/*
				 * The header is written into the headroom in
				 * front of this buffer's payload, so the two
				 * are one transfer. Thirty-two bytes of
				 * header is the only thing the processor
				 * writes; the 4064 bytes of samples are read
				 * by the DMA straight out of where the PDC
				 * left them.
				 */
				uint8_t *frame = acq_frame_bytes();

				memcpy(frame, &tx_hdr, sizeof(tx_hdr));
				tx_off = 0;
				tx_phase = TX_DMA;
				continue;
			}
		}

		/* Time spent inside the transport only, so the effective rate
		 * of the write path can be separated from everything else the
		 * loop does. */
		if (tx_phase == TX_HEADER) {
			const uint8_t *hp = (const uint8_t *)&tx_hdr;

			t_in = micros();
			w = xport_write(hp + tx_off, sizeof(tx_hdr) - tx_off);
			usb_us += micros() - t_in;
			usb_bytes += w;
			tx_off += w;
			if (tx_off < sizeof(tx_hdr)) {
				/* The core's CDC discards silently unless the host has
				 * set lineState, and write() then returns 0. Counting
				 * attempts rather than accepted bytes would report a
				 * stream that is not actually leaving the board. */
				if (w == 0)
					write_fail++;
				else
					short_write++;
				return;
			}
			tx_off = 0;
			tx_phase = TX_PAYLOAD;
		}

		payload = (const uint8_t *)acq_frame_data();
		t_in = micros();
		w = xport_write(payload + tx_off, plen - tx_off);
		usb_us += micros() - t_in;
		usb_bytes += w;
		tx_off += w;
		if (tx_off < plen) {
			if (w == 0)
				write_fail++;
			else
				short_write++;
			return;
		}

		bytes_sent += sizeof(tx_hdr) + plen;
		tx_off = 0;
		tx_phase = TX_IDLE;

		acq_frame_release();
		frames_sent++;
		seq++;
	}
}

/*
 * The DMA capture counters, on their own line and in Track B's exact
 * wording: the host's `?` parser keys off the text, so a difference in
 * spelling here is a difference the suite cannot see past.
 */
int stream_dma_report(char *buf, size_t n)
{
	return snprintf(buf, n, "# dma-frames=%lu dma-stalls=%lu",
	                (unsigned long)dma_frames, (unsigned long)dma_stalls);
}

void stream_report(char *buf, size_t n)
{
	uint32_t us = micros() - started_us;
	uint32_t kbps = us ? (uint32_t)(((uint64_t)bytes_sent * 1000ull) / us) : 0;

	snprintf(buf, n,
	         "# frames=%lu bytes=%lu %lu.%03lu MB/s prod=%lu cons=%lu "
	         "ringovf=%lu resync=%lu rxbuff=%lu govre=%lu endtx=%lu "
	         "wfail=%lu wshort=%lu dtr=%d inwrite=%lu.%03lu MB/s (cpu path)",
	         (unsigned long)frames_sent, (unsigned long)bytes_sent,
	         (unsigned long)(kbps / 1000u), (unsigned long)(kbps % 1000u),
	         (unsigned long)acq_produced, (unsigned long)acq_consumed,
	         (unsigned long)acq_ring_overflow,
	         (unsigned long)resync_count,
	         (unsigned long)acq_rxbuff_overruns,
	         (unsigned long)acq_govre,
	         (unsigned long)gen_endtx_count,
	         (unsigned long)write_fail, (unsigned long)short_write,
	         /* dtr() reads lineState directly; (bool)SerialUSB would
	          * report the same thing after a delay(10). */
	         (int)SerialUSB.dtr(),
	         (unsigned long)(usb_us ? ((uint64_t)usb_bytes * 1000ull / usb_us) / 1000u : 0),
	         (unsigned long)(usb_us ? ((uint64_t)usb_bytes * 1000ull / usb_us) % 1000u : 0));
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
	seq = 0;
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
		h.seq             = seq;
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
		seq++;
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
	h->seq             = seq++;
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
