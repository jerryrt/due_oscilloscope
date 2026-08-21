/*
 * Binary sample streaming over the native USB port.
 *
 * Track A uses SerialUSB, whose stack copies into the endpoint FIFO a
 * byte at a time and never touches the UOTGHS DMA. That is acceptable
 * here and only here: this is the reference implementation, and the
 * measurement it produces tells us what the CDC path can actually
 * sustain. The real path drives the USB DMA directly.
 *
 * Control and logging stay on the programming port so that a stray
 * print can never corrupt a frame.
 */

#include <Arduino.h>
#include "acq.h"
#include "gen.h"
#include "frame.h"

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

void stream_start(uint32_t trigger_hz)
{
	acq_init();
	gen_init();

	seq = 0;
	frames_sent = 0;
	bytes_sent = 0;
	pending_overrun = 0;
	write_fail = 0;
	short_write = 0;
	resync_count = 0;
	rate_hz = trigger_hz;

	gen_start();
	acq_start(trigger_hz);

	started_us = micros();
	active = true;
}

void stream_stop(void)
{
	active = false;
	acq_stop();
	gen_stop();
}

bool stream_active(void)
{
	return active;
}

/*
 * Called from the main loop. Sends at most a few frames per call so the
 * command interface stays responsive.
 */
void stream_service(void)
{
	if (!active)
		return;

	/*
	 * The core's CDC write spins on TXINI once lineState is set, and
	 * availableForWrite() is a constant, so there is no flow-control
	 * signal to test. If the host has closed the port, writing would
	 * block forever and wedge the board. Checking the connection is the
	 * only guard available.
	 *
	 * It does not cover a host that holds the port open but stops
	 * reading; nothing in this API can. That is a property of the CDC
	 * path, and one more reason the real transport drives the USB DMA
	 * directly.
	 */
	if (!(bool)SerialUSB) {
		/* Keep the ring from filling while nobody is listening. */
		while (acq_frame_available())
			acq_frame_release();
		return;
	}

	for (int budget = 0; budget < 4 && acq_frame_available(); budget++) {
		frame_header_t h;

		/*
		 * If the ISR has lapped us, the oldest unsent buffers are being
		 * overwritten by the PDC as we read them. Sending one anyway
		 * yields a frame that passes its header CRC while carrying
		 * spliced data, which is exactly the silent corruption the
		 * protocol exists to prevent.
		 *
		 * Skip forward to the newest buffer that is still safe and flag
		 * the discontinuity instead.
		 */
		uint32_t produced = acq_produced;
		if (produced - acq_consumed >= ACQ_NBUF - 1u) {
			acq_consumed = produced - (ACQ_NBUF - 2u);
			resync_count++;
		}
		uint32_t overruns = acq_rxbuff_overruns + acq_govre +
		                    acq_ring_overflow + resync_count;

		h.magic[0] = FRAME_MAGIC0; h.magic[1] = FRAME_MAGIC1;
		h.magic[2] = FRAME_MAGIC2; h.magic[3] = FRAME_MAGIC3;
		h.version         = FRAME_VERSION;
		h.flags           = FRAME_FLAG_CONTINUOUS;
		h.bits_per_sample = 12;
		h.packing         = 0;
		h.seq             = seq++;
		h.sample_rate_hz  = rate_hz;
		h.n_samples       = ACQ_BUF_SAMPLES;
		h.channel_mask    = (1u << 7) | (1u << 6);   /* AD7=A0, AD6=A1 */
		h.timestamp_us    = micros();
		h.overrun_count   = overruns;

		if (overruns != pending_overrun) {
			h.flags |= FRAME_FLAG_OVERRUN;
			pending_overrun = overruns;
		}

		h.header_crc32 = frame_crc32((const uint8_t *)&h,
		                             sizeof(h) - sizeof(uint32_t));

		const uint8_t *payload = (const uint8_t *)acq_frame_data();

		/* The core's CDC discards silently unless the host has set
		 * lineState, and write() then returns 0. Counting attempts
		 * rather than accepted bytes would report a stream that is not
		 * actually leaving the board. */
		size_t w1 = SerialUSB.write((const uint8_t *)&h, sizeof(h));
		size_t w2 = SerialUSB.write(payload,
		                            ACQ_BUF_SAMPLES * sizeof(uint16_t));

		if (w1 == 0 && w2 == 0)
			write_fail++;
		else if (w1 + w2 < sizeof(h) + ACQ_BUF_SAMPLES * sizeof(uint16_t))
			short_write++;

		acq_frame_release();
		frames_sent++;
		bytes_sent += w1 + w2;
	}
}

void stream_report(char *buf, size_t n)
{
	uint32_t us = micros() - started_us;
	uint32_t kbps = us ? (uint32_t)(((uint64_t)bytes_sent * 1000ull) / us) : 0;

	snprintf(buf, n,
	         "# frames=%lu accepted=%lu %lu.%03lu MB/s prod=%lu cons=%lu "
	         "ringovf=%lu rxbuff=%lu govre=%lu endtx=%lu "
	         "wfail=%lu wshort=%lu resync=%lu usb=%d",
	         (unsigned long)frames_sent, (unsigned long)bytes_sent,
	         (unsigned long)(kbps / 1000u), (unsigned long)(kbps % 1000u),
	         (unsigned long)acq_produced, (unsigned long)acq_consumed,
	         (unsigned long)acq_ring_overflow,
	         (unsigned long)acq_rxbuff_overruns,
	         (unsigned long)acq_govre,
	         (unsigned long)gen_endtx_count,
	         (unsigned long)write_fail, (unsigned long)short_write,
	         (unsigned long)resync_count, (int)(bool)SerialUSB);
}
