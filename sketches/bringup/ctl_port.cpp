/*
 * Track A's side of lib/due_shared/src/ctl_port.h.
 *
 * The parser, the CRC, the framing and every error path are the shared
 * ctl.c that Track B runs. What is here is the seven primitives and the
 * per-opcode data, which is the part a track genuinely does its own way.
 *
 * Objective 1c's second half is this file. It is not a second
 * implementation of docs/control-protocol.md - writing one of those was
 * the plan until the wire format, the CRC and the dispatcher moved into
 * the shared library, and the reason not to is that two transcriptions
 * of one document are two chances to misread it. See
 * docs/shared-source.md.
 */
#include "ctl_port.h"
#include "load.h"

#include <Arduino.h>
#include <string.h>

#include "track_id.h"
#include "gen.h"
#include "acq.h"
#include "ctlusb.h"
#include "play.h"
#include "stream.h"

/*
 * The command endpoints are manual FIFO and polled from the main loop,
 * which is what drivers/usb_cdc.c does for Track B's pair too. The DMA
 * channels are spoken for by the sample path, and a control channel
 * carrying a few dozen bytes a second has no use for one.
 */
#define FIFO(ep)  (((volatile uint8_t (*)[0x8000])UOTGHS_RAM_ADDR)[(ep)])

static uint32_t ctl_out_rd_off;

size_t ctl_port_read(uint8_t *dst, size_t max)
{
	uint32_t st = UOTGHS->UOTGHS_DEVEPTISR[CTL_EP_OUT];
	uint32_t byct, n;
	volatile uint8_t *fifo;

	if (!ctlusb_ok())
		return 0;
	if (!(st & UOTGHS_DEVEPTISR_RXOUTI))
		return 0;

	byct = (st & UOTGHS_DEVEPTISR_BYCT_Msk) >> UOTGHS_DEVEPTISR_BYCT_Pos;
	if (byct <= ctl_out_rd_off) {
		/*
		 * A zero-length packet, or a bank this call already emptied:
		 * release it and move on. Not releasing it is the defect this
		 * endpoint shipped with - an allocated bulk OUT that nobody
		 * hands back NAKs for ever, and the writer stalls at 48 KB.
		 */
		ctl_out_rd_off = 0;
		UOTGHS->UOTGHS_DEVEPTICR[CTL_EP_OUT] = UOTGHS_DEVEPTICR_RXOUTIC;
		UOTGHS->UOTGHS_DEVEPTIDR[CTL_EP_OUT] = UOTGHS_DEVEPTIDR_FIFOCONC;
		return 0;
	}

	n = byct - ctl_out_rd_off;
	if (n > max)
		n = (uint32_t)max;

	fifo = FIFO(CTL_EP_OUT);
	for (uint32_t i = 0; i < n; i++)
		dst[i] = fifo[ctl_out_rd_off + i];
	ctl_out_rd_off += n;
	ctlusb_out_bytes += n;

	/* Hand the bank back only once every byte in it has been taken. */
	if (ctl_out_rd_off >= byct) {
		ctl_out_rd_off = 0;
		ctlusb_out_banks++;
		UOTGHS->UOTGHS_DEVEPTICR[CTL_EP_OUT] = UOTGHS_DEVEPTICR_RXOUTIC;
		UOTGHS->UOTGHS_DEVEPTIDR[CTL_EP_OUT] = UOTGHS_DEVEPTIDR_FIFOCONC;
	}
	return n;
}

size_t ctl_port_write(const uint8_t *src, size_t len)
{
	size_t done = 0;

	if (!ctlusb_ok())
		return 0;

	while (done < len) {
		volatile uint8_t *fifo;
		uint32_t n;

		/*
		 * No spinning. If no bank is free the host is not reading,
		 * and blocking here would hand a stalled host the power to
		 * stop the main loop - which is the failure this project
		 * already has a name for. The caller counts the short write
		 * as a dropped answer instead.
		 */
		if (!(UOTGHS->UOTGHS_DEVEPTISR[CTL_EP_IN] & UOTGHS_DEVEPTISR_TXINI))
			break;

		n = (uint32_t)(len - done);
		if (n > CTL_EP_SIZE)
			n = CTL_EP_SIZE;

		fifo = FIFO(CTL_EP_IN);
		for (uint32_t i = 0; i < n; i++)
			fifo[i] = src[done + i];

		UOTGHS->UOTGHS_DEVEPTICR[CTL_EP_IN] = UOTGHS_DEVEPTICR_TXINIC;
		UOTGHS->UOTGHS_DEVEPTIDR[CTL_EP_IN] = UOTGHS_DEVEPTIDR_FIFOCONC;
		done += n;
	}
	return done;
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
	return ctlusb_out_banks;
}

int ctl_port_temp(ctl_temp_t *out, uint16_t samples)
{
	return acq_read_temp(out, samples);
}

void ctl_port_console_flush(void)
{
	Serial.flush();
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
	/*
	 * Banks handed back on the command endpoint. Track B counts main
	 * loop passes that took its drain branch; the number means the
	 * same thing - the device is consuming what the host sends - and
	 * is the witness that separates a stalled device from a stalled
	 * host.
	 */
	out->drain_polls = ctlusb_out_banks;
}

/*
 * Not on this track, and answered as CTL_ERR_OPCODE rather than zeroes.
 *
 * ctl_stream_stats_t carries usb_reset, usb_setup, usb_stall,
 * usb_configured, usb_devisr, usb_ep0isr and usb_devimr, which are
 * counters kept by Track B's own USB stack. This track enumerates
 * through the Arduino core and has no equivalent, and reporting zero
 * for a counter that does not exist is a measurement claim this
 * firmware cannot make. Same for the bench counters, which count DMA
 * arms on a path Track B drives and this one does not.
 */
/*
 * CTL_OP_GEN. The whole of this track's part: the semantics, the
 * clamping and the words all live in the shared layer, and what is here
 * is the call into this track's own generator.
 */
bool ctl_port_gen_get(ctl_gen_t *out)
{
	out->shape      = gen_shape;
	out->sync       = gen_sync;
	out->points     = gen_points;
	out->amp        = gen_amp;
	out->sync_amp   = gen_sync_amp;
	out->trigger_hz = gen_trigger_hz();
	out->output_hz  = gen_hz_for(out->trigger_hz, gen_points, gen_sync);
	return true;
}

void ctl_port_gen_set(uint8_t shape, uint16_t points, uint8_t sync,
                      uint16_t amp, uint16_t sync_amp)
{
	if (sync_amp)
		gen_set_sync_amp(sync_amp);
	gen_set_shape(shape);
	if (points)
		gen_set_points(points);
	if (amp)
		gen_set_amp(amp);
	gen_set_sync(sync);
}

/*
 * Which optional opcodes this build implements. See ctl_port.h.
 *
 * No stream stats and no bench: ctl_stream_stats_t and ctl_bench_t
 * carry Track B's own USB stack counters - usb_devisr, usb_ep0isr,
 * usb_devimr - and this track enumerates through the Arduino core and
 * has no equivalent. Not debt; a different stack has different
 * counters.
 *
 * No rate trace: ctl_port_rate_page() above refuses unconditionally,
 * and this word must agree with it.
 */
uint32_t ctl_port_capabilities(void)
{
	return CTL_CAP_OCCUPANCY | CTL_CAP_LOAD | CTL_CAP_TEMP | CTL_CAP_GEN
	     | CTL_CAP_HEARTBEAT;
}

bool ctl_port_stream_stats(ctl_stream_stats_t *out)
{
	(void)out;
	return false;
}

bool ctl_port_bench(ctl_bench_t *out)
{
	(void)out;
	return false;
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

/*
 * No rate trace on this track: play.h here has no PLAY_RATE_TRACE at
 * all. Track B compiles its own out by default as well
 * (PLAY_RATE_TRACE_ENABLED 0), so a host already has to handle this
 * refusal and it is not a new shape.
 */
int ctl_port_rate_page(uint8_t *body, size_t max, uint16_t offset)
{
	(void)body; (void)max; (void)offset;
	return -1;
}

bool ctl_port_load_sample(load_report_t *out)
{
	/*
	 * True even when the cycle counter is not counting. `available`
	 * inside the report says that, and it is a different statement
	 * from "this track has no load monitor", which is what returning
	 * false meant while this was a stub.
	 *
	 * The monitor is lib/due_shared/src/load.c and both tracks compile
	 * it. What the Arduino core does not do is enable DWT's counter -
	 * load_init() does, and checks that it counts rather than assuming
	 * it, because a counter stuck at zero reports a loop with no pass
	 * longer than one cycle: a wrong answer that looks like a very good
	 * one.
	 */
	load_sample(out);
	return true;
}
