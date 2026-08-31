/*
 * Console handler bodies that are application logic, shared by both
 * tracks (issue #45).
 *
 * `console.c` is the console's *surface* - the command table, the
 * argument parser, the help text and the dispatch. This file is the
 * other half of the same rescope: the handler bodies that touch no
 * register and were therefore written twice by hand.
 *
 * Measured before it was written, because "the handlers are duplicated"
 * is true and was not specific enough to plan from. Of 48 handlers per
 * track, all 48 sharing a command letter, 17 have a paired named body:
 *
 *   4 program registers directly - cmd_crosstalk, cmd_profile,
 *     cmd_rate_sweep, measure_gpio - and STAY per track. That is
 *     invariant 3 doing its job, and no amount of tidying should move
 *     them.
 *   13 touch no register at all: 269 lines on Track B and 260 on
 *     Track A, about 529 lines expressing one logic.
 *
 * So the prize is real but smaller than a line count of the two files
 * suggests, and it is bounded by a rule rather than by taste.
 *
 * What arrives here must reach the outside world through console_port.h
 * and the other shared ports only. `printf`/`uart_flush` on Track B and
 * `Serial.print`/`Serial.flush` on Track A both become
 * console_write()/console_flush(), which is the difference that made
 * these two copies look different while saying the same thing.
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
 * `w` with no argument: what the internal generator is set to.
 *
 * Already written to be track-agnostic before it moved - it asks
 * ctl_port_gen_get(), which is the per-track half, and answers "no
 * generator on this track" when there is none. ctl_gen_describe()
 * formats it, and ctl_wire.h notes that the description is shared while
 * the measurement behind it stays per track.
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
 * Shared because the two copies **must not differ**, not merely because
 * they were duplicated. Issue #16 measures what happens *between* two
 * conversions, so a wait that differs between the tracks changes the
 * thing being measured - and the two figures then are not comparable,
 * which is exactly what happened when Track B spun 400,000 iterations
 * and Track A called delay(10). Both were corrected to a micros() spin
 * and a comment on each side asked the other to stay that way.
 *
 * A comment is not a mechanism. One body is.
 *
 * ctl_port_micros() rather than a direct micros(): Track A's comes from
 * the Arduino core and Track B's from bsp.h, and the port already
 * exists to name that difference. delay() is what must not be used -
 * it calls yield() and snaps to the SysTick millisecond, so it is
 * neither the same duration nor the same activity as a spin.
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
 * BANNER FIRST, THEN START. Issue #41, and the order is the whole
 * point of this function existing once.
 *
 * Capture is device-driven: the ring fills from the moment the timer
 * runs and nothing has to ask it to. Invariant 8 prices a console line
 * at 13-20 ms of blocked main loop - this banner is ~160 characters and
 * was measured at 17.9-20.2 ms - while the ring holds STREAM_NBUF
 * frames, which at 453,488 Hz is 8.96 ms of runway. Printing after the
 * start spent the whole runway before the first drain and everything
 * past it was gone: exactly 3 frames, nine runs of nine, on three
 * benches and three hosts, with zero growth afterwards because the loss
 * is spent before the first transfer rather than leaking.
 *
 * The shape is h_mimic's, which already printed before starting for
 * this reason and is the preset whose zero-at-every-rate localised the
 * defect. The banner announces intent; a refusal follows it if the
 * start fails. No host reads the banner as success - measure.py takes
 * success as the *absence* of "refused" - so the refusal arriving
 * second changes nothing above it.
 *
 * Two sites are NOT hazards and must not be "fixed": h_play prints
 * after a host-driven start that flows nothing until fed, and
 * cmd_stream_uart has 2019 ms of margin. docs/debugging.md carries the
 * table.
 *
 * The generator half needs no port: ctl_port_gen_get() already returns
 * the shape, points and sync that the two copies read out of their own
 * file-scope globals, and gen_shape_name()/gen_hz_for() have been
 * shared since the control channel landed. Only the start is per track.
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
 * `=<dac>P`: playback with no capture.
 *
 * One body for three tracks. Track A's and Track B's were
 * byte-identical apart from the flush - `Serial.flush()` against
 * `uart_flush()` - and Track C had none at all, which is how the suite
 * came to fail on it. Nothing in it is track-specific: it is a refusal
 * message and a ceiling, and the ceiling is now one port call instead
 * of `(SystemCoreClock / 2u) / PLAY_MIN_RC` written out per track.
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
 * **The banner order is load-bearing and is not style.** It goes out
 * before the CAPTURE start, never between it and the first frame,
 * because capture is device-driven and the ring fills the moment the
 * timer runs: docs/debugging.md priced this site at ~102 characters of
 * banner against 8.96 ms of ring, margin -5.89 ms, and measured
 * `first_overrun` at 2 and 1 across four runs at two rates before it
 * was moved. That is issue #41's signature exactly.
 *
 * `play_start` stays ahead of the banner and that is deliberate too.
 * Playback is host-driven and nothing flows until the host feeds, so
 * it is not a hazard in that audit - only the capture start is.
 *
 * Keeping one copy is what keeps that ordering true on every track.
 * Three copies is three chances for someone to tidy the banner into
 * the wrong place, and only one of them would be measured.
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
 * ONE IMPLEMENTATION, and the choice between the two it replaces was
 * the owner's on issue #45. The two tracks had the same name and
 * genuinely different experiments - Track B swept a list of target
 * RATES and Track A a list of RC VALUES - so this was the one body on
 * the paired list that `tools/console_pairs.py` called "DIFFERENT
 * diagnostics" and meant it. It is a merge of the better half of each,
 * and the reasoning is recorded because the losing half of each was
 * better at something:
 *
 * FROM TRACK A: the ladder, and it is not a close call. Track A walks
 * RC one step at a time through the cliff - 88, 87, 86, 85 - so it
 * measures either side of ACQ_MIN_RC. Track B's rate list resolved to
 * RC 390, 97 and then 84 down to 78, every one of the last seven below
 * the floor: on the board it printed **two measured rows and seven
 * REFUSED**. A sweep whose job is to find a cliff must have points on
 * both sides of it.
 *
 * FROM TRACK B: the columns. `trigger` and `measured` are different
 * questions - what the integer divisor produces, and what the converter
 * actually delivered - and `measured` is PER CHANNEL. The first fact in
 * CLAUDE.md's "easy to get wrong" list is that channel count divides
 * the aggregate, so a column called `measured` has to be the
 * per-channel number a user asks for. Track A reported the aggregate.
 *
 * FROM TRACK A: the header carries MCK and the ADC clock. Issue #52 has
 * made MCK a measured quantity rather than a register readback - it
 * reads about -11 ppm from 78 MHz - so a rate sweep that does not
 * record the clock it divided is missing its own provenance.
 *
 * The ratio is unchanged and was never in dispute: both tracks computed
 * delivered-over-programmed and got there by different algebra that
 * cancels to the same number.
 */
void console_cmd_rate_sweep(unsigned n_channels)
{
	/*
	 * RC values, not rates. The trigger is TC_CLOCK / RC with RC an
	 * integer, so an RC ladder walks the hardware's own steps and a
	 * rate ladder only approximates them - and can land two entries
	 * on one RC without saying so.
	 *
	 * Dense either side of the 2-channel floor at 86 and the
	 * 1-channel floor at 44, because the floor is what this command
	 * exists to find. The wide first entry is the low-rate anchor.
	 */
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
	con_str(" Hz, ADC clk "); con_u32(console_port_mck_hz() / 4u);
	con_str(" Hz, min RC "); con_u32(min_rc); con_nl();
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
