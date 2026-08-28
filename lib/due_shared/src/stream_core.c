/*
 * The framer, shared (issue #14).
 *
 * This file was drivers/stream.c's and sketches/bringup/stream.cpp's
 * middle 200 lines, written twice and diverging - the two copies had
 * already grown different counters and one of them had lost DMA on the
 * capture-only path. What moved here is policy: frame building,
 * sequencing, overrun accounting, the resync rule. What did not move
 * is hardware: everything this file touches outside itself goes
 * through the names stream_port.h declares, and each track provides
 * those over its own register programming.
 *
 * Instrumentation is the union of what the two copies had grown:
 * write_fail/short_write and the usb_us/usb_bytes transport timing
 * were Track A's, and Track B gains them by the move.
 */
#include <string.h>

#include "frame.h"
#include "stream_core.h"
#include "stream_port.h"

static bool     active;
static uint32_t seq, rate_hz, frames_sent, bytes_sent, started_us;
static uint32_t pending_overrun, resync_count;
static uint32_t write_fail, short_write;
static uint32_t usb_us, usb_bytes;

typedef enum { TX_IDLE, TX_HEADER, TX_PAYLOAD, TX_DMA } tx_phase_t;
static tx_phase_t     tx_phase;
static size_t         tx_off;
static frame_header_t tx_hdr;

/* The headroom in front of each capture buffer is sized in each
 * track's acq.h, which cannot see this type. If they ever disagree
 * the header would be written over the first samples of its own
 * payload. */
_Static_assert(sizeof(frame_header_t) == STREAM_HDR_BYTES,
               "capture header headroom must match the frame header");

static bool     tx_dma;
static uint32_t dma_frames, dma_stalls;

/*
 * How much of a frame goes out per DMA transfer.
 *
 * One 4096-byte transfer measurably starves the ADC's PDC: 439 general
 * overruns in a 4 s run at the full rate against none on the CPU-copy
 * path, because the USB DMA holds the bus matrix while the PDC is
 * trying to write the next conversion into SRAM. Moving the capture
 * ring to the other bank halved it, which named the mechanism, and
 * smaller transfers give the PDC gaps to win arbitration in.
 *
 * 512 keeps every transfer exactly one bulk packet, so the stream stays
 * packet-aligned and no short packet is ever emitted mid-frame.
 */
#define DMA_CHUNK_BYTES  512u

bool stream_core_start(uint32_t trigger_hz, bool with_gen,
                       unsigned n_channels, bool usb)
{
	acq_init();
	if (with_gen)
		gen_init();

	seq = frames_sent = bytes_sent = 0;
	pending_overrun = resync_count = 0;
	write_fail = short_write = 0;
	usb_us = usb_bytes = 0;
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
	 * writes IN while streaming, and the two modes must never be
	 * mixed on one endpoint: the FIFO path owns FIFOCON by hand and
	 * DMA needs the hardware to switch banks itself.
	 *
	 * Every USB start arms it, capture-only included: Track B ran the
	 * host-fed loop's capture on the CPU path for six days because
	 * 6c96eed armed DMA in one of its two start functions and missed
	 * the other. One start function, so it cannot happen again.
	 */
	tx_dma = usb;
	dma_frames = dma_stalls = 0;
	if (tx_dma)
		usb_dma_mode_in(true);

	active = true;
	return true;
}

void stream_core_stop(void)
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
		 * channel through a bounded stop, and an aborted transfer
		 * stops reading the buffer just as surely as a finished one
		 * does. The worst case is one corrupted frame already on the
		 * wire; the alternative is a board that has to be
		 * power-cycled.
		 */
		usb_dma_mode_in(false);
		tx_dma = false;
	}
	tx_phase = TX_IDLE;
	tx_off = 0;
	acq_stop();
	gen_stop();
}

bool stream_core_active(void)
{
	return active;
}

void stream_core_get_stats(stream_core_stats_t *out)
{
	out->active          = active;
	out->started_us      = started_us;
	out->frames          = frames_sent;
	out->bytes           = bytes_sent;
	out->run_us          = active ? (micros() - started_us) : 0u;
	out->rate_hz         = rate_hz;
	out->resync          = resync_count;
	out->pending_overrun = pending_overrun;
	out->write_fail      = write_fail;
	out->short_write     = short_write;
	out->usb_us          = usb_us;
	out->usb_bytes       = usb_bytes;
	out->dma_frames      = dma_frames;
	out->dma_stalls      = dma_stalls;
}

/*
 * Called from each track's stream_service. Sends at most a few frames
 * per call so the command interface stays responsive.
 */
void stream_core_service(void)
{
	if (!active)
		return;

	/*
	 * With the port closed, discard rather than queue. The transport
	 * already returns 0 without blocking when the host is not
	 * listening, but a frame half-way through transmission would then
	 * sit in TX_HEADER forever while the PDC laps the ring behind it.
	 * Dropping keeps the counters honest: the frames are gone either
	 * way, and the ones that follow stay continuous.
	 *
	 * The genuine hazard is a host that holds the port open and stops
	 * reading, and no API here detects that.
	 */
	if (!stream_port_ready()) {
		while (acq_frame_available())
			acq_frame_release();
		tx_phase = TX_IDLE;
		tx_off = 0;
		return;
	}

	for (int budget = 0; budget < 4; budget++) {
		const uint8_t *payload;
		size_t plen = STREAM_BUF_SAMPLES * sizeof(uint16_t);
		uint32_t t_in;
		size_t w;

		/*
		 * A DMA in flight owns the buffer it is reading, so the
		 * frame is not released and the next one is not started
		 * until it has finished. Releasing early would hand the
		 * PDC a buffer the USB controller is still sending.
		 */
		if (tx_phase == TX_DMA) {
			uint8_t *frame = acq_frame_bytes();

			if (usb_dma_in_busy())
				return;
			if (tx_off < STREAM_FRAME_BYTES) {
				uint32_t n = STREAM_FRAME_BYTES - tx_off;

				if (n > DMA_CHUNK_BYTES)
					n = DMA_CHUNK_BYTES;
				/*
				 * Deliberately not counted into usb_us /
				 * usb_bytes. Arming a DMA is four register
				 * writes and returns long before the bytes
				 * are on the wire, so timing it and dividing
				 * reports the speed of the register file:
				 * 145 MB/s on a 1.8 MB/s link, which is
				 * worse than no figure at all. The CPU write
				 * path is the only thing those two describe.
				 */
				if (!usb_dma_in_start(frame + tx_off, n)) {
					dma_stalls++;
					return;
				}
				tx_off += n;
				continue;
			}
			bytes_sent += STREAM_FRAME_BYTES;
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
		 * here and nowhere else. Re-running the lap check while a frame
		 * is in flight would move acq_consumed, and with it the payload
		 * pointer, out from under the transfer.
		 */
		if (tx_phase == TX_IDLE) {
			uint32_t produced, overruns;

			if (!acq_frame_available())
				return;

			produced = acq_produced;

			/*
			 * If the writer has lapped the reader, the oldest buffers
			 * are being overwritten as they are read. Sending one
			 * yields a frame that passes its CRC while carrying data
			 * spliced across two points in time, so skip to the newest
			 * safe buffer and count the discontinuity instead.
			 */
			if (produced - acq_consumed >= STREAM_NBUF - 1u) {
				acq_consumed = produced - (STREAM_NBUF - 2u);
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

		/*
		 * A CDC pipe is a byte stream with no frame boundaries, so a
		 * short write is not something the receiver can recover from:
		 * it loses byte alignment and starts misreading channel tags.
		 * Transmission is therefore resumable across service calls and
		 * never abandoned part-way. usb_us/usb_bytes take the time
		 * spent inside the transport only, so the effective rate of
		 * the write path can be separated from everything else the
		 * loop does.
		 */
		if (tx_phase == TX_HEADER) {
			const uint8_t *hp = (const uint8_t *)&tx_hdr;

			t_in = micros();
			w = stream_port_write(hp + tx_off, sizeof(tx_hdr) - tx_off);
			usb_us += micros() - t_in;
			usb_bytes += w;
			tx_off += w;
			if (tx_off < sizeof(tx_hdr)) {
				/* A transport that is not draining returns 0.
				 * Counting attempts rather than accepted bytes
				 * would report a stream that is not actually
				 * leaving the board. */
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
		w = stream_port_write(payload + tx_off, plen - tx_off);
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
