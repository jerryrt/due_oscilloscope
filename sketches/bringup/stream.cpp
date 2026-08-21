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

enum bench_mode { BENCH_OFF, BENCH_FLOOD, BENCH_SINK };
static bench_mode bench;
static uint32_t bench_bytes, bench_t0, bench_frames;
static uint16_t bench_payload[ACQ_BUF_SAMPLES];

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

static void stream_start_common(uint32_t trigger_hz, bool with_gen);

/*
 * Capture without touching the DAC, so the DACC can be left running on
 * its own independent timebase. This is what makes it possible to check
 * the measured DAC ceiling against the frequency actually produced,
 * rather than trusting a count of PDC completions.
 */
void stream_start_capture_only(uint32_t trigger_hz)
{
	stream_start_common(trigger_hz, false);
}

void stream_start(uint32_t trigger_hz)
{
	stream_start_common(trigger_hz, true);
}

static void stream_start_common(uint32_t trigger_hz, bool with_gen)
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
	rate_hz = trigger_hz;

	if (with_gen)
		gen_start();
	acq_start(trigger_hz);

	started_us = micros();
	active = true;
}

void stream_bench_service(void);

void stream_stop(void)
{
	active = false;
	bench = BENCH_OFF;
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
	stream_bench_service();

	if (!active)
		return;

	/*
	 * Do NOT test (bool)SerialUSB here.
	 *
	 * Serial_::operator bool() ends with delay(10). Calling it once per
	 * service pass costs ten milliseconds of pure sleep and was, by
	 * itself, the reason this path appeared to cap at about half the
	 * link rate. Time spent inside the write corresponded to nearly
	 * 9 MB/s; the ceiling was the guard, not the transport.
	 *
	 * It was never needed either. Serial_::write returns 0 without
	 * blocking when the host has not set lineState, so a closed port is
	 * already handled. The genuine hazard is a host that holds the port
	 * open and stops reading, and no API here detects that.
	 */
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
		/* Time spent inside the transport only, so the effective rate
		 * of the write path can be separated from everything else the
		 * loop does. */
		uint32_t t_in = micros();
		size_t w1 = SerialUSB.write((const uint8_t *)&h, sizeof(h));
		size_t w2 = SerialUSB.write(payload,
		                            ACQ_BUF_SAMPLES * sizeof(uint16_t));
		usb_us += micros() - t_in;
		usb_bytes += w1 + w2;

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
	         "wfail=%lu wshort=%lu resync=%lu usb=%d inwrite=%lu.%03lu MB/s",
	         (unsigned long)frames_sent, (unsigned long)bytes_sent,
	         (unsigned long)(kbps / 1000u), (unsigned long)(kbps % 1000u),
	         (unsigned long)acq_produced, (unsigned long)acq_consumed,
	         (unsigned long)acq_ring_overflow,
	         (unsigned long)acq_rxbuff_overruns,
	         (unsigned long)acq_govre,
	         (unsigned long)gen_endtx_count,
	         (unsigned long)write_fail, (unsigned long)short_write,
	         (unsigned long)resync_count, (int)(bool)SerialUSB,
	         (unsigned long)(usb_us ? ((uint64_t)usb_bytes * 1000ull / usb_us) / 1000u : 0),
	         (unsigned long)(usb_us ? ((uint64_t)usb_bytes * 1000ull / usb_us) % 1000u : 0));
}

/* ------------------------------------------------------------------ */
/* Transport benchmarks                                                */
/* ------------------------------------------------------------------ */

void stream_flood_start(void)
{
	stream_stop();
	/* A recognisable ramp, so a desynchronised host is obvious. */
	for (unsigned i = 0; i < ACQ_BUF_SAMPLES; i++)
		bench_payload[i] = (uint16_t)(((i & 1u) ? 6u : 7u) << 12) | (i & 0x0fffu);
	seq = 0;
	bench_bytes = 0;
	bench_frames = 0;
	bench_t0 = micros();
	bench = BENCH_FLOOD;
}

void stream_sink_start(void)
{
	stream_stop();
	bench_bytes = 0;
	bench_frames = 0;
	bench_t0 = micros();
	bench = BENCH_SINK;
}

void stream_bench_service(void)
{
	if (bench == BENCH_FLOOD) {
		for (int budget = 0; budget < 8; budget++) {
			frame_header_t h;

			h.magic[0] = FRAME_MAGIC0; h.magic[1] = FRAME_MAGIC1;
			h.magic[2] = FRAME_MAGIC2; h.magic[3] = FRAME_MAGIC3;
			h.version         = FRAME_VERSION;
			h.flags           = FRAME_FLAG_CONTINUOUS;
			h.bits_per_sample = 12;
			h.packing         = 0;
			h.seq             = seq++;
			h.sample_rate_hz  = 0;          /* synthetic, not acquired */
			h.n_samples       = ACQ_BUF_SAMPLES;
			h.channel_mask    = (1u << 7) | (1u << 6);
			h.timestamp_us    = micros();
			h.overrun_count   = 0;
			h.header_crc32 = frame_crc32((const uint8_t *)&h,
			                             sizeof(h) - sizeof(uint32_t));

			size_t w1 = SerialUSB.write((const uint8_t *)&h, sizeof(h));
			if (w1 != sizeof(h))
				break;
			size_t w2 = SerialUSB.write((const uint8_t *)bench_payload,
			                            sizeof(bench_payload));
			bench_bytes += w1 + w2;
			bench_frames++;
			if (w2 != sizeof(bench_payload))
				break;
		}
	} else if (bench == BENCH_SINK) {
		uint8_t tmp[512];
		for (int budget = 0; budget < 16; budget++) {
			int avail = SerialUSB.available();
			if (avail <= 0)
				break;
			int n = avail > (int)sizeof(tmp) ? (int)sizeof(tmp) : avail;
			int got = SerialUSB.readBytes((char *)tmp, n);
			if (got <= 0)
				break;
			bench_bytes += (uint32_t)got;
		}
	}
}

void stream_bench_report(char *buf, size_t n)
{
	uint32_t us = micros() - bench_t0;
	uint32_t kbps = us ? (uint32_t)(((uint64_t)bench_bytes * 1000ull) / us) : 0;

	snprintf(buf, n, "# bench=%s bytes=%lu frames=%lu %lu.%03lu MB/s",
	         bench == BENCH_FLOOD ? "flood(IN)" :
	         bench == BENCH_SINK  ? "sink(OUT)" : "off",
	         (unsigned long)bench_bytes, (unsigned long)bench_frames,
	         (unsigned long)(kbps / 1000u), (unsigned long)(kbps % 1000u));
}
