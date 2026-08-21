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
#include "stream.h"
#include "usb_cdc.h"
#include <stdio.h>

uint32_t frame_crc32(const uint8_t *data, size_t len)
{
	uint32_t c = 0xffffffffu;

	while (len--) {
		c ^= *data++;
		for (int k = 0; k < 8; k++)
			c = (c >> 1) ^ (0xedb88320u & (uint32_t)(-(int32_t)(c & 1u)));
	}
	return ~c;
}

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
static bool     active;
static uint32_t seq, rate_hz, frames_sent, bytes_sent, started_us;
static uint32_t pending_overrun, resync_count, refused;

typedef enum { TX_IDLE, TX_HEADER, TX_PAYLOAD } tx_phase_t;
static tx_phase_t     tx_phase;
static size_t         tx_off;
static frame_header_t tx_hdr;

static bool stream_start_common(uint32_t trigger_hz);

static size_t xport_write(const uint8_t *p, size_t n)
{
	if (xport == XPORT_UART) {
		for (size_t i = 0; i < n; i++)
			uart_putc_polled((char)p[i]);
		return n;
	}
	return usb_cdc_write(p, n);
}

static bool xport_ready(void)
{
	return xport == XPORT_UART ? true : usb_cdc_ready();
}

bool stream_start_uart(uint32_t trigger_hz)
{
	xport = XPORT_UART;
	return stream_start_common(trigger_hz);
}

bool stream_start(uint32_t trigger_hz)
{
	xport = XPORT_USB;
	return stream_start_common(trigger_hz);
}

static bool stream_start_common(uint32_t trigger_hz)
{
	acq_init();
	gen_init();

	seq = frames_sent = bytes_sent = 0;
	pending_overrun = resync_count = refused = 0;
	tx_phase = TX_IDLE;
	tx_off = 0;
	rate_hz = trigger_hz;

	if (!acq_start(trigger_hz, 2))
		return false;

	gen_start();
	started_us = micros();
	active = true;
	return true;
}

void stream_stop(void)
{
	active = false;
	acq_stop();
	gen_stop();
}

void stream_service(void)
{
	if (!active)
		return;

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
			tx_hdr.bits_per_sample = 12;
			tx_hdr.packing         = 0;
			tx_hdr.seq             = seq;
			tx_hdr.sample_rate_hz  = rate_hz;
			tx_hdr.n_samples       = ACQ_BUF_SAMPLES;
			tx_hdr.channel_mask    = (1u << 7) | (1u << 6);
			tx_hdr.timestamp_us    = micros();
			tx_hdr.overrun_count   = overruns;

			if (overruns != pending_overrun) {
				tx_hdr.flags |= FRAME_FLAG_OVERRUN;
				pending_overrun = overruns;
			}

			tx_hdr.header_crc32 =
				frame_crc32((const uint8_t *)&tx_hdr,
				            sizeof(tx_hdr) - sizeof(uint32_t));

			tx_off = 0;
			tx_phase = TX_HEADER;
		}

		/*
		 * A CDC pipe is a byte stream with no frame boundaries, so a
		 * short write is not something the receiver can recover from:
		 * it loses byte alignment and starts misreading channel tags.
		 * Transmission is therefore resumable across service calls and
		 * never abandoned part-way.
		 */
		if (tx_phase == TX_HEADER) {
			const uint8_t *hp = (const uint8_t *)&tx_hdr;

			tx_off += xport_write(hp + tx_off, sizeof(tx_hdr) - tx_off);
			if (tx_off < sizeof(tx_hdr))
				return;
			tx_off = 0;
			tx_phase = TX_PAYLOAD;
		}

		payload = (const uint8_t *)acq_frame_data();
		tx_off += xport_write(payload + tx_off, plen - tx_off);
		if (tx_off < plen)
			return;

		bytes_sent += sizeof(tx_hdr) + plen;
		tx_off = 0;
		tx_phase = TX_IDLE;

		acq_frame_release();
		frames_sent++;
		seq++;
	}
}


void stream_report(void)
{
	uint32_t us = micros() - started_us;
	uint32_t kbps = us ? (uint32_t)(((uint64_t)bytes_sent * 1000ull) / us) : 0;

	printf("# frames=%lu bytes=%lu %lu.%03lu MB/s prod=%lu cons=%lu "
	       "ringovf=%lu resync=%lu refused=%lu rxbuff=%lu govre=%lu "
	       "endtx=%lu rst=%lu setup=%lu stall=%lu cfg=%lu dtr=%lu cfgfail=%lu\n"
	       "# usb isr=%lu devisr=%08lx ep0isr=%08lx devimr=%08lx\n",
	       (unsigned long)frames_sent, (unsigned long)bytes_sent,
	       (unsigned long)(kbps / 1000u), (unsigned long)(kbps % 1000u),
	       (unsigned long)acq_produced, (unsigned long)acq_consumed,
	       (unsigned long)acq_ring_overflow, (unsigned long)resync_count,
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
