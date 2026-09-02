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
#include "ctl.h"
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

/*
 * The heartbeat's timer, Track A's own programming.
 *
 * TC0 channel 2, the same channel Track B uses for the same job - and
 * written separately on purpose. Invariant 3 keeps register programming
 * per track because two independent programmings of one peripheral is
 * what makes a behavioural divergence point at one of them; a shared
 * setup would trade that away for twenty lines. The frame the interrupt
 * sends is protocol and is shared.
 *
 * Channels 0 and 1 are acq's and gen's on this track too.
 *
 * pmc_enable_periph_clk() rather than a direct PMC_PCER0 write: this
 * track has the Arduino core's libsam under it and uses its accessors
 * where they exist, which is itself part of the divergence being kept.
 */
void ctl_port_heartbeat_timer(uint32_t period_ms)
{
	uint32_t rc;

	if (period_ms == 0u) {
		NVIC_DisableIRQ(TC2_IRQn);
		TC0->TC_CHANNEL[2].TC_IDR = TC_IDR_CPCS;
		TC0->TC_CHANNEL[2].TC_CCR = TC_CCR_CLKDIS;
		return;
	}

	pmc_enable_periph_clk(ID_TC2);

	TC0->TC_CHANNEL[2].TC_CCR = TC_CCR_CLKDIS;
	TC0->TC_CHANNEL[2].TC_IDR = 0xFFFFFFFFu;
	(void)TC0->TC_CHANNEL[2].TC_SR;

	TC0->TC_CHANNEL[2].TC_CMR = TC_CMR_TCCLKS_TIMER_CLOCK4
	                          | TC_CMR_WAVE
	                          | TC_CMR_WAVSEL_UP_RC;

	/* TIMER_CLOCK4 is MCK/128; SystemCoreClock is 78 MHz here, not the
	 * 84 boards.txt believes, so derive it rather than hard-coding. */
	rc = ((SystemCoreClock / 128u) / 1000u) * period_ms;
	if (rc < 2u)
		rc = 2u;
	TC0->TC_CHANNEL[2].TC_RC = rc;

	TC0->TC_CHANNEL[2].TC_IER = TC_IER_CPCS;
	/* Below the core's USB and the PDC: this reports, it does not move
	 * samples, and it must never delay something that does. */
	NVIC_SetPriority(TC2_IRQn, 3);
	NVIC_ClearPendingIRQ(TC2_IRQn);
	NVIC_EnableIRQ(TC2_IRQn);

	TC0->TC_CHANNEL[2].TC_CCR = TC_CCR_CLKEN | TC_CCR_SWTRG;
}

extern "C" void TC2_Handler(void)
{
	(void)TC0->TC_CHANNEL[2].TC_SR;
	ctl_heartbeat_emit_isr();
}

/* ------------------------------------------------------------------ */
/* Issue #52: the USB host's frame clock                               */
/* ------------------------------------------------------------------ */
/*
 * The same reference Track B keeps, programmed independently as
 * invariant 3 requires. Both tracks read UOTGHS_DEVFNUM; neither shares
 * the code that does it.
 *
 * The gate differs on purpose. Track B asks usb_cdc_configured(),
 * because it owns its enumeration state. This track does not - the
 * Arduino core owns it - so the reference is gated on EVIDENCE instead:
 * FNUM advancing is what a host emitting SOF looks like, and nothing
 * else produces it.
 *
 * That evidence gate is not simply an equally valid alternative to
 * Track B's: measured on linux-x1, Track A read -30,777 ppm where
 * Track B read -9.8 on the same board in the same afternoon, because
 * FNUM advancing detects a host that STARTS emitting SOF but cannot
 * detect one that STOPS - a frozen FNUM is indistinguishable from "no
 * new frame has arrived yet", and the fast path below returns on
 * exactly that comparison, so a whole outage was swallowed without
 * ever reaching a check. Track B's gate resets `started` and takes a
 * fresh epoch when the port de-configures; this one carried a single
 * span straight across the discontinuity.
 *
 * The cost was quantised and silent: one 2048-frame FNUM wrap at cold
 * boot and exactly two per native-port bounce, over a 20x range of
 * outage, with `ambiguous` and `restarts` both left at 0 - so the
 * device reported a poisoned span as a clean one. clockref.c's epoch
 * comment describes this same signature from before Track B was fixed:
 * a fixed offset divided by a growing window.
 *
 * The idea was right and half the evidence was being thrown away.
 * FNUM staying frozen is itself evidence of a host that has stopped,
 * and the fast path discarded it. It is counted now.
 */
static uint32_t sof_frames_ext;
static uint32_t sof_edge_frames;
static uint64_t sof_elapsed_us;   /* accumulated wrap-safe; micros() wraps at 71.6 min */
static uint64_t sof_edge_elapsed;
static uint32_t sof_restarts_n;
static uint32_t sof_ambiguous_n;
static uint16_t sof_last_fnum;
static uint32_t sof_last_us;
static bool     sof_started;
static uint32_t sof_still;        /* consecutive polls with FNUM unchanged */

/*
 * How many unchanged polls mean the host has stopped rather than simply
 * not arrived yet.
 *
 * A frame lands every 1 ms and an idle pass is ~7 us, so a NORMAL gap
 * between frames is on the order of 143 polls. This is more than an
 * order of magnitude above that, and still only ~35 ms of outage - far
 * below the 1.5 s stall guard, which is the band where the defect
 * lived.
 *
 * Deliberately a POLL count and not a duration. micros() costs 869 ns
 * and must not run on the fast path: drivers/clockref.c records that it
 * did once, and tests/test_load.py's uniformity guard is what caught it
 * - 98.5% spread across three log2 buckets against a 99% floor. An
 * integer increment costs nothing and keeps that guard green.
 *
 * The consequence of being wrong in either direction is mild, which is
 * why a round number is enough: too low restarts a healthy span and
 * loses a little history, too high leaves a small window in which the
 * old defect survives. Neither reports a wrong number, because a
 * restarted span is clean by construction.
 */
#define SOF_STILL_RESTART   5000u

/* Called once per main-loop pass. One register read and a comparison. */
void ctl_port_sof_poll(void)
{
	uint32_t fn = UOTGHS->UOTGHS_DEVFNUM;
	uint16_t cur = (uint16_t)((fn & UOTGHS_DEVFNUM_FNUM_Msk) >>
	                          UOTGHS_DEVFNUM_FNUM_Pos);
	/* Common pass ends here - see drivers/clockref.c: micros() costs
	 * 869 ns and must not run on every pass. */
	if (cur == sof_last_fnum && sof_started) {
		/*
		 * The other half of the evidence, and this is what it
		 * costs to discard it. A host that stopped emitting SOF
		 * looks exactly like one whose next frame has not arrived,
		 * for one poll. It does not look like that for 5000.
		 *
		 * Dropping `started` here is the same act as Track B's
		 * `if (!usb_cdc_configured()) started = false;` - the span
		 * ends and the next one takes a fresh epoch, rather than
		 * being carried across a discontinuity that nothing
		 * downstream can see.
		 */
		if (++sof_still >= SOF_STILL_RESTART) {
			sof_still = 0u;
			sof_started = false;
			sof_frames_ext = 0u;
			sof_edge_frames = 0u;
			sof_elapsed_us = 0u;
			sof_edge_elapsed = 0u;
			sof_restarts_n++;
		}
		return;
	}
	sof_still = 0u;

	uint32_t now = micros();

	if (!sof_started) {
		/* Not "configured" but "moving": two polls that differ are a
		 * host emitting SOF, and a stuck value is not. */
		if (cur != sof_last_fnum && sof_last_fnum != 0u)
			sof_started = true;
		sof_last_fnum = cur;
		sof_last_us = now;
		return;
	}

	/* FNUM wraps every 2048 frames; a pass that blocked longer than
	 * that cannot be resolved, so it is counted rather than guessed. */
	/* Restart the span rather than poison it - see drivers/clockref.c.
	 * A health figure that goes dark for ever after one stall is the
	 * wrong shape. */
	if ((uint32_t)(now - sof_last_us) > 1500000u) {
		sof_ambiguous_n++;
		sof_restarts_n++;
		sof_frames_ext = 0u;
		sof_edge_frames = 0u;
		sof_elapsed_us = 0u;
		sof_edge_elapsed = 0u;
		sof_last_fnum = cur;
		sof_last_us = now;
		return;
	}

	/* 64-bit from small wrap-safe deltas: micros() wraps at 71.6 min and
	 * a difference of two absolute readings is wrong across two wraps. */
	sof_elapsed_us += (uint64_t)(uint32_t)(now - sof_last_us);

	{
		uint32_t step = (uint32_t)((cur - sof_last_fnum) & 2047u);

		sof_frames_ext += step;
		/* Latch only on a single-frame advance - see
		 * drivers/clockref.c for the measurement that motivates it.
		 * A longer pass leaves the edge unlocated, and a stale
		 * timestamp is worse than a later one. */
		if (step == 1u) {
			sof_edge_frames = sof_frames_ext;
			sof_edge_elapsed = sof_elapsed_us;
		}
	}
	sof_last_fnum = cur;
	sof_last_us = now;
}

extern "C" int ctl_port_sof(uint32_t *frames, uint64_t *dev_us,
                            uint32_t *ambiguous, uint32_t *restarts)
{
	if (ambiguous)
		*ambiguous = sof_ambiguous_n;
	if (restarts)
		*restarts = sof_restarts_n;
	if (!sof_started)
		return 0;
	if (frames)
		*frames = sof_edge_frames;
	if (dev_us)
		*dev_us = sof_edge_elapsed;
	return 1;
}

extern "C" uint32_t ctl_port_mck_hz(void)
{
	return SystemCoreClock;
}
