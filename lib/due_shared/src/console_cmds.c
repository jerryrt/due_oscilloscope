/*
 * Console handler bodies that are application logic, shared by both
 * tracks.
 *
 * `console.c` is the console's *surface* - the command table, the
 * argument parser, the help text and the dispatch. This file is the
 * handler bodies that touch no register: the ones that program
 * registers directly (cmd_crosstalk, cmd_profile, measure_gpio) stay
 * per track, invariant 3 doing its job.
 *
 * What arrives here must reach the outside world through console_port.h
 * and the other shared ports only. `printf`/`uart_flush` on Track B and
 * `Serial.print`/`Serial.flush` on Track A both become
 * console_write()/console_flush().
 */
#include <stdio.h>

#include "console.h"
#include "console_port.h"
#include "console_out.h"
#include "ctl_port.h"
#include "ctl_wire.h"

/*
 * `f`: prove the fault handler by taking one deliberately.
 *
 * A jump to the start of SRAM, which is not executable code, so the
 * core takes an INVSTATE usage fault and the handler reports it. The
 * point is that the *reporter* works; a board that faults silently is
 * one that cannot tell you why it stopped, and this project has no
 * debug probe.
 *
 * The flush before the jump is load-bearing: the message has to be on
 * the wire before control leaves, or the evidence dies with the fault.
 */
void console_trigger_fault(void)
{
	console_write("# triggering deliberate hard fault (INVSTATE)...\n");
	console_flush();

	void (*bad)(void) = (void (*)(void))0x20000000;
	bad();

	console_write("# unreachable\n");
	console_flush();
}

/*
 * `w` with no argument: what the internal generator is set to. Asks
 * ctl_port_gen_get(), the per-track half, and answers "no generator on
 * this track" when there is none; ctl_gen_describe() formats it.
 */
void console_gen_report(void)
{
	ctl_gen_t g;

	if (!ctl_port_gen_get(&g)) {
		console_write("# no generator on this track\n");
		console_flush();
		return;
	}
	con_str("# ");
	ctl_gen_describe(&g);
	con_nl();
	console_flush();
}


/*
 * The crosstalk settle wait, spun on the device clock rather than any
 * track's delay().
 *
 * Shared because the two copies must not differ, not merely because
 * they were duplicated: this measures what happens *between* two
 * conversions, so a wait that differs between tracks changes the thing
 * being measured and the two figures stop being comparable. delay()
 * must not be used here - it calls yield() and snaps to the SysTick
 * millisecond, neither the same duration nor the same activity as a
 * spin.
 */
void console_bleed_settle(uint32_t ms)
{
	uint32_t t0 = ctl_port_micros();

	while (ctl_port_micros() - t0 < ms * 1000u)
		{ }
}

/*
 * `1`..`5`: start a capture stream, and say what it is about to do.
 *
 * BANNER FIRST, THEN START, and the order is load-bearing: capture is
 * device-driven, so the ring starts filling the moment the timer runs,
 * and a console line costs 13-20 ms of blocked main loop (invariant 8)
 * against a ring that holds only a few milliseconds of runway. Printing
 * after the start spends that runway before the first drain, and the
 * lost frames are gone before anyone reads them. The banner announces
 * intent; a refusal follows it if the start fails, and no host reads
 * the banner alone as success. See docs/debugging.md for which other
 * sites are and are not hazards by this same measure.
 *
 * The generator half needs no port: ctl_port_gen_get() already returns
 * the shape, points and sync, and gen_shape_name()/gen_hz_for() are
 * shared. Only the start is per track.
 */
void console_cmd_stream(uint32_t trigger_hz)
{
	ctl_gen_t g;
	bool have_gen = ctl_port_gen_get(&g);

	con_str("# streaming: trigger "); con_u32(trigger_hz);
	con_str(" Hz, "); con_u32(trigger_hz * 2u);
	con_str(" sps aggregate");
	if (have_gen) {
		con_str(", "); con_str(gen_shape_name(g.shape)); con_ch(' ');
		con_u32(gen_hz_for(trigger_hz, g.points, g.sync));
		con_str(" Hz ("); con_u32(g.points);
		con_str(" pts/cycle)");
	}
	con_nl();

	if (have_gen)
		console_write(g.sync == GEN_SYNC_OFF
		              ? "# DAC1 holds mid scale: A1 must read flat, "
		                "or demux is wrong\n"
		              : "# DAC1 carries the sync: A1 must show a "
		                "square, not the waveform\n");
	console_flush();

	if (!console_port_stream_start(trigger_hz)) {
		con_str("# refused: "); con_u32(trigger_hz);
		con_str(" Hz is past the measured ADC ceiling"); con_nl();
		console_flush();
	}
}

/*
 * `=<dac>P`: playback with no capture. One body for every track:
 * nothing in it is track-specific, only a refusal message and a
 * ceiling reached through one port call.
 */
void console_cmd_play(uint32_t dac_hz)
{
	if (console_port_play_start(dac_hz)) {
		con_str("# play only: DAC "); con_u32(dac_hz);
		con_str(" sps from USB, no capture"); con_nl();
	} else {
		con_str("# play only: "); con_u32(dac_hz);
		con_str(" sps refused (max ");
		con_u32(console_port_play_max_hz());
		con_ch(')'); con_nl();
	}
	console_flush();
}

/*
 * `=<dac>[,<adc>[,<nch>]]L`: host-fed playback with simultaneous
 * capture.
 *
 * The banner order is load-bearing, not style: it goes out before the
 * CAPTURE start, never between it and the first frame, because capture
 * is device-driven and the ring fills the moment the timer runs - print
 * after starting and the banner's own cost in blocked main loop can
 * outrun the ring's runway. See docs/debugging.md.
 *
 * `play_start` stays ahead of the banner deliberately: playback is
 * host-driven and nothing flows until the host feeds, so it is not a
 * hazard by that same measure - only the capture start is. Keeping one
 * copy is what keeps that ordering true on every track.
 */
void console_cmd_loop(uint32_t dac_hz, uint32_t adc_hz, unsigned nch)
{
	if (!console_port_play_start(dac_hz)) {
		con_str("# loop: DAC "); con_u32(dac_hz);
		con_str(" sps refused (max ");
		con_u32(console_port_play_max_hz());
		con_ch(')'); con_nl();
		console_flush();
		return;
	}

	con_str("# loop: DAC "); con_u32(dac_hz);
	con_str(" sps from USB, ADC "); con_u32(adc_hz);
	con_str(" Hz/ch x"); con_u32(nch); con_str(" ch"); con_nl();
	con_str("# DAC0 carries the waveform, DAC1 holds mid scale"); con_nl();
	console_flush();

	if (!console_port_capture_only_start(adc_hz, nch)) {
		console_port_play_stop();
		con_str("# loop: ADC "); con_u32(adc_hz);
		con_str(" Hz x"); con_u32(nch);
		con_str(" ch refused (max ");
		con_u32((console_port_mck_hz() / 2u)
		        / console_port_acq_min_rc(nch));
		con_ch(')'); con_nl();
		console_flush();
	}
}

/*
 * `=,,<nch>t`: the TC -> ADC -> PDC rate sweep, in one place.
 *
 * One implementation, merged from what each track's separate version
 * did better:
 *
 * - The RC ladder, not a rate list: walking RC one step at a time
 *   through the cliff measures both sides of ACQ_MIN_RC, where a target
 *   rate list can resolve to RCs that are all on one side of the floor
 *   and refuse almost every row. A sweep whose job is to find a cliff
 *   must have points on both sides of it.
 * - `trigger` and `measured` as separate columns, and `measured` PER
 *   CHANNEL: one ADC behind a multiplexer means channel count divides
 *   the aggregate, so the per-channel number is what a column called
 *   `measured` has to report.
 * - The header carries MCK and the ADC clock, printed NOMINAL and
 *   labelled so on the wire - the divisor arithmetic below is integer
 *   on this same value; the measured clock is mck_meas_hz in the
 *   telemetry heartbeat.
 */
void console_cmd_rate_sweep(unsigned n_channels)
{
	/* RC values, not rates: the trigger is TC_CLOCK / RC with RC an
	 * integer, so an RC ladder walks the hardware's own steps. Dense
	 * either side of the 2-channel floor at 86 and the 1-channel floor
	 * at 44, since the floor is what this command exists to find. */
	static const uint32_t rcs2[] = {
		390, 100, 96, 92, 90, 88, 87, 86, 85, 84, 83, 82, 80, 78
	};
	static const uint32_t rcs1[] = {
		195, 50, 49, 48, 47, 46, 45, 44, 43, 42, 41, 40
	};
	const uint32_t *rcs  = (n_channels == 1) ? rcs1 : rcs2;
	const unsigned  nrcs = (n_channels == 1)
	                     ? sizeof(rcs1) / sizeof(rcs1[0])
	                     : sizeof(rcs2) / sizeof(rcs2[0]);
	const uint32_t  nbuf_target = 8;
	uint32_t tc_clock = console_port_mck_hz() / 2u;
	uint32_t min_rc   = console_port_acq_min_rc(n_channels);

	console_port_acq_init();

	con_str("# TC->ADC->PDC rate sweep, "); con_u32(n_channels);
	con_str(" channel");
	con_str(n_channels == 1 ? " (A0=AD7)" : "s (A0=AD7, A1=AD6)");
	con_str(", MCK ");     con_u32(console_port_mck_hz());
	con_str(" Hz nominal, ADC clk "); con_u32(console_port_mck_hz() / 4u);
	con_str(" Hz nominal, min RC "); con_u32(min_rc); con_nl();
	con_str("#     RC   trigger  measured    ratio  RXBUFF GOVRE"); con_nl();
	console_flush();

	for (unsigned i = 0; i < nrcs; i++) {
		uint32_t want = tc_clock / rcs[i];
		uint32_t sync, guard, t0, t1, b0, got, rc, trigger, us;
		uint32_t measured, ratio_x1000, rxbuff, govre;
		uint64_t samples;

		if (!console_port_acq_start(want, n_channels)) {
			con_str("# "); con_u32w(rcs[i], 6, ' ');
			con_ch(' ');   con_u32w(want, 9, ' ');
			con_str("         -        -       -     -"
			        "   REFUSED (RC < ");
			con_u32(min_rc); con_ch(')'); con_nl();
			console_flush();
			continue;
		}

		/* Wait out the buffer in flight, then time a whole number
		 * of completions: a partial first buffer would make the
		 * short arm read fast. */
		sync  = console_port_acq_buffers_done();
		guard = ctl_port_micros();
		while (console_port_acq_buffers_done() == sync &&
		       (ctl_port_micros() - guard) < 2000000u)
			{ }
		t0 = ctl_port_micros();
		b0 = console_port_acq_buffers_done();
		while (console_port_acq_buffers_done() - b0 < nbuf_target &&
		       (ctl_port_micros() - t0) < 2000000u)
			{ }
		t1  = ctl_port_micros();
		got = console_port_acq_buffers_done() - b0;
		console_port_acq_stop();

		rc      = console_port_acq_configured_rc();
		trigger = rc ? tc_clock / rc : 0u;
		us      = t1 - t0;
		samples = (uint64_t)got * console_port_acq_buf_samples();
		/* Per channel, not aggregate. One ADC behind a multiplexer:
		 * channel count divides the rate, and the column a reader
		 * compares against `trigger` has to be the same quantity. */
		measured = us
		         ? (uint32_t)((samples * 1000000ull) / us) / n_channels
		         : 0u;
		ratio_x1000 = trigger
		            ? (uint32_t)(((uint64_t)measured * 1000ull) / trigger)
		            : 0u;
		console_port_acq_overruns(&rxbuff, &govre);

		con_str("# "); con_u32w(rcs[i], 6, ' ');
		con_ch(' ');   con_u32w(trigger, 9, ' ');
		con_ch(' ');   con_u32w(measured, 9, ' ');
		con_str("   "); con_u32w(ratio_x1000 / 1000u, 2, ' ');
		con_ch('.');   con_u32w(ratio_x1000 % 1000u, 3, '0');
		con_ch(' ');   con_u32w(rxbuff, 7, ' ');
		con_ch(' ');   con_u32w(govre, 5, ' ');
		con_nl();
		console_flush();
	}
	con_str("# ratio 1.000 = every trigger produced a conversion");
	con_nl();
	console_flush();
}
