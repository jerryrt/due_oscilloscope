/*
 * Track B's side of lib/due_shared/src/ctl_port.h.
 *
 * Thin by design. Every function here is a name change and nothing
 * else, which is the point: the protocol stops naming this track's
 * headers, and what it needs instead is five lines of forwarding that
 * a second track can write for itself.
 *
 * Bare metal, so all four dependencies are this project's own -
 * usb_cdc.c for the endpoint, bsp.c for the clock and the console,
 * load.c for the monitor.
 */
#include "ctl_port.h"
#include <string.h>

#include "track_id.h"
#include "acq.h"
#include "bsp.h"
#include "load.h"
#include "stream.h"
#include "play.h"
#include "usb_cdc.h"
#include "sam.h"

/*
 * The wire structs are copies of stream.c's, so that this stays a copy
 * and not a field-by-field mapping that can be got wrong silently. That
 * is only safe while they agree, so say so to the compiler rather than
 * in a comment. The assertions live here rather than beside the parser
 * because this is where the memcpy they guard now is.
 */
_Static_assert(sizeof(ctl_stream_stats_t) == sizeof(stream_stats_t),
               "ctl_stream_stats_t and stream_stats_t have diverged");
_Static_assert(sizeof(ctl_bench_t) == sizeof(stream_bench_t),
               "ctl_bench_t and stream_bench_t have diverged");

size_t ctl_port_read(uint8_t *dst, size_t max)
{
	return usb_ctl_read(dst, max);
}

size_t ctl_port_write(const uint8_t *src, size_t len)
{
	return usb_ctl_write(src, len);
}

uint32_t ctl_port_micros(void)
{
	return micros();
}

uint32_t ctl_port_millis(void)
{
	return millis();
}

uint32_t ctl_port_out_drain_polls(void)
{
	return usb_out_drain_polls;
}

bool ctl_port_load_sample(load_report_t *out)
{
	/*
	 * True even when the cycle counter is not counting. `available`
	 * inside the report says that, and it is a different statement
	 * from "this track has no load monitor" - which is what returning
	 * false means and what Track A will return until it grows one.
	 */
	load_sample(out);
	return true;
}

void ctl_port_console_flush(void)
{
	uart_flush();
}

/* ------------------------------------------------------------------ */
/* The per-opcode data                                                  */
/* ------------------------------------------------------------------ */

void ctl_port_identity(ctl_identity_t *out)
{
	static const char build[] = __DATE__ " " __TIME__;

	out->track         = FW_TRACK;
	out->frame_bytes   = ACQ_FRAME_BYTES;
	out->frame_samples = ACQ_BUF_SAMPLES;
	out->mck_hz        = SystemCoreClock;
	out->adc_clock_hz  = SystemCoreClock / 4u;
	memcpy(out->build, build,
	       sizeof(build) - 1u < sizeof(out->build)
	           ? sizeof(build) - 1u : sizeof(out->build));
}

void ctl_port_counters(ctl_counters_t *out)
{
	out->dev_us      = micros();
	out->bytes_in    = play_bytes_in;
	out->produced    = play_produced;
	out->consumed    = play_consumed;
	out->underruns   = play_underruns;
	out->isr_calls   = play_isr_calls;
	out->endtx_seen  = play_endtx_seen;
	out->spans       = play_spans;
	out->partial     = play_partial;
	out->occ_min     = play_occ_min;
	out->svc_calls   = play_svc_calls;
	out->loop_passes = stream_loop_passes;
	out->run_us      = play_run_us;
	out->abandoned   = play_abandoned;
	out->drain_polls = usb_out_drain_polls;
}

bool ctl_port_stream_stats(ctl_stream_stats_t *out)
{
	stream_stats_t st;

	stream_get_stats(&st);
	memcpy(out, &st, sizeof(*out));
	return true;
}

bool ctl_port_bench(ctl_bench_t *out)
{
	stream_bench_t b;

	stream_get_bench(&b);
	memcpy(out, &b, sizeof(*out));
	return true;
}

int ctl_port_occupancy(uint8_t *body, size_t max)
{
	ctl_occupancy_t *o = (ctl_occupancy_t *)body;
	uint8_t *p = body + sizeof(*o);
	uint32_t traced = play_occ_traced;

	if (max < sizeof(*o) + PLAY_NBUF * sizeof(uint32_t) + PLAY_OCC_TRACE)
		return -1;
	if (traced > PLAY_OCC_TRACE)
		traced = PLAY_OCC_TRACE;

	o->dev_us      = micros();
	o->occ_min     = play_occ_min;
	o->endtx_seen  = play_endtx_seen;
	o->run_us      = play_run_us;
	o->consumed    = play_consumed;
	o->nbuf        = (uint8_t)PLAY_NBUF;
	o->trace_decim = (uint8_t)PLAY_OCC_DECIM;
	o->trace_n     = (uint16_t)traced;

	for (unsigned i = 0; i < PLAY_NBUF; i++) {
		uint32_t v = play_occ_hist[i];

		memcpy(p, &v, sizeof(v));
		p += sizeof(v);
	}
	for (uint32_t i = 0; i < traced; i++)
		*p++ = play_occ_trace[i];

	return (int)(p - body);
}

int ctl_port_rate_page(uint8_t *body, size_t max, uint16_t offset)
{
	ctl_rate_page_t *rp = (ctl_rate_page_t *)body;
	uint8_t *p = body + sizeof(*rp);
	uint32_t total = play_rate_traced;
	uint32_t page, n;

	if (max < sizeof(*rp) + sizeof(uint32_t))
		return -1;
	/*
	 * The page size is what is left of the buffer after the header,
	 * computed rather than written down, so raising CTL_MAX_PAYLOAD
	 * cannot leave a stale constant behind.
	 */
	page = (uint32_t)((max - sizeof(*rp)) / sizeof(uint32_t));

	if (total > PLAY_RATE_TRACE)
		total = PLAY_RATE_TRACE;
	n = offset >= total ? 0u : total - offset;
	if (n > page)
		n = page;

	rp->decim    = (uint8_t)PLAY_RATE_DECIM;
	rp->reserved = 0;
	rp->total    = (uint16_t)total;
	rp->offset   = offset;
	rp->count    = (uint16_t)n;

	for (uint32_t i = 0; i < n; i++) {
		uint32_t v = play_rate_us[offset + i];

		memcpy(p, &v, sizeof(v));
		p += sizeof(v);
	}
	return (int)(p - body);
}
