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
#include "console_out.h"
#include "stream_bench.h"
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

volatile uint32_t stream_loop_passes;

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

/* The bench arms' transport: always the USB bulk pair, through the
 * core's objects - which is the path being measured. */
size_t usb_port_write(const uint8_t *p, size_t n)
{
	size_t w = SerialUSB.write(p, n);

	if (w)
		usb_in_activity++;
	return w;
}

/*
 * Drain through Serial_::read rather than readBytes: Stream::readBytes
 * goes through timedRead, which calls millis() per byte and turns a
 * transport measurement into a measurement of the timeout helper.
 */
size_t usb_port_read(uint8_t *p, size_t n)
{
	int avail = SerialUSB.available();
	int take, i;

	if (avail <= 0)
		return 0;
	take = avail > (int)n ? (int)n : avail;
	for (i = 0; i < take; i++) {
		int c = SerialUSB.read();
		if (c < 0)
			break;
		p[i] = (uint8_t)c;
	}
	if (i)
		usb_out_activity++;
	return (size_t)i;
}

bool usb_dma_out_done(uint32_t *bytes_left)
{
	/* One read: byte count and channel-enabled share the register, and
	 * two reads ask two different instants. See drivers/play.c. */
	uint32_t st = usb_dma_out_status();

	if (st & UOTGHS_DEVDMASTATUS_CHANN_ENB)
		return false;
	*bytes_left = (st & UOTGHS_DEVDMASTATUS_BUFF_COUNT_Msk)
	              >> UOTGHS_DEVDMASTATUS_BUFF_COUNT_Pos;
	return true;
}

void usb_dma_keepalive(void)
{
	/* The core rebuilds endpoint configuration on bus reset and
	 * SET_CONFIGURATION; put the DMA mode back on the bench's
	 * schedule. */
	usbdma_keepalive();
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
	stream_bench_stop();
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
	stream_bench_mode_t m = stream_bench_mode();

	return stream_core_active() ||
	       m == STREAM_BENCH_FLOOD || m == STREAM_BENCH_DUPLEX ||
	       m == STREAM_BENCH_FLOOD_DMA || m == STREAM_BENCH_DUPLEX_DMA;
}

bool stream_out_in_use(void)
{
	stream_bench_mode_t m = stream_bench_mode();

	return m == STREAM_BENCH_SINK || m == STREAM_BENCH_DUPLEX ||
	       m == STREAM_BENCH_SINK_DMA || m == STREAM_BENCH_DUPLEX_DMA;
}

/*
 * Called from the main loop. Sends at most a few frames per call so the
 * command interface stays responsive.
 */
void stream_service(void)
{
	stream_bench_service();
	stream_core_service();
}


void stream_dma_report(void)
{
	stream_core_stats_t cs;

	stream_core_get_stats(&cs);
	con_str("# ");
	con_kv_u32("dma-frames", cs.dma_frames);  con_ch(' ');
	con_kv_u32("dma-stalls", cs.dma_stalls);
}

void stream_report(void)
{
	stream_core_stats_t cs;
	uint32_t us, kbps;

	stream_core_get_stats(&cs);
	us = micros() - cs.started_us;
	kbps = us ? (uint32_t)(((uint64_t)cs.bytes * 1000ull) / us) : 0;

	uint32_t inkbps = cs.usb_us
	        ? (uint32_t)(((uint64_t)cs.usb_bytes * 1000ull) / cs.usb_us)
	        : 0u;

	con_str("# ");
	con_kv_u32("frames", cs.frames);            con_ch(' ');
	con_kv_u32("bytes", cs.bytes);              con_ch(' ');
	con_u32(kbps / 1000u); con_ch('.');
	con_u32w(kbps % 1000u, 3, '0');             con_str(" MB/s ");
	con_kv_u32("prod", acq_produced);           con_ch(' ');
	con_kv_u32("cons", acq_consumed);           con_ch(' ');
	con_kv_u32("ringovf", acq_ring_overflow);   con_ch(' ');
	con_kv_u32("resync", cs.resync);            con_ch(' ');
	con_kv_u32("rxbuff", acq_rxbuff_overruns);  con_ch(' ');
	con_kv_u32("govre", acq_govre);             con_ch(' ');
	con_kv_u32("endtx", gen_endtx_count);       con_ch(' ');
	con_kv_u32("wfail", cs.write_fail);         con_ch(' ');
	con_kv_u32("wshort", cs.short_write);       con_ch(' ');
	/* dtr() reads lineState directly; (bool)SerialUSB would report the
	 * same thing after a delay(10). */
	con_kv_u32("dtr", (uint32_t)SerialUSB.dtr()); con_ch(' ');
	con_str("inwrite="); con_u32(inkbps / 1000u); con_ch('.');
	con_u32w(inkbps % 1000u, 3, '0');
	con_str(" MB/s (cpu path)");
}

/* ------------------------------------------------------------------ */
/* Transport benchmarks - policy in lib/due_shared/src/stream_bench.c  */
/* ------------------------------------------------------------------ */

void stream_flood_start(void)  { stream_bench_start(STREAM_BENCH_FLOOD); }
void stream_sink_start(void)   { stream_bench_start(STREAM_BENCH_SINK); }
void stream_duplex_start(void) { stream_bench_start(STREAM_BENCH_DUPLEX); }
void stream_flood_dma_start(void)
{
	stream_bench_start(STREAM_BENCH_FLOOD_DMA);
}
void stream_sink_dma_start(void)
{
	stream_bench_start(STREAM_BENCH_SINK_DMA);
}
void stream_duplex_dma_start(void)
{
	stream_bench_start(STREAM_BENCH_DUPLEX_DMA);
}

void stream_bench_report(void)
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
	stream_bench_stats_t bs;

	stream_bench_get_stats(&bs);
	con_str("# ");
	con_kvs("bench",
	        bs.mode == STREAM_BENCH_FLOOD  ? "flood"  :
	        bs.mode == STREAM_BENCH_SINK   ? "sink"   :
	        bs.mode == STREAM_BENCH_DUPLEX ? "duplex" :
	        bs.mode == STREAM_BENCH_FLOOD_DMA  ? "flood-dma"  :
	        bs.mode == STREAM_BENCH_SINK_DMA   ? "sink-dma"   :
	        bs.mode == STREAM_BENCH_DUPLEX_DMA ? "duplex-dma" : "off");
	con_str("  IN ");   con_u32(bs.in_bytes);   con_str(" B   OUT ");
	con_u32(bs.out_bytes);                      con_str(" B  ");
	con_kv_u32("passes", stream_loop_passes);   con_ch(' ');
	con_kv_u32("arms-in", bs.dma_in_arms);      con_ch(' ');
	con_kv_u32("arms-out", bs.dma_out_arms);    con_ch(' ');
	con_kv_u32("rebuilds", usbdma_rebuilds);    con_ch(' ');
	con_kv_u32("inbusy", (uint32_t)usb_dma_in_busy());
}
