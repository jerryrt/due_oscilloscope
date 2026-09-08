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
#include <string.h>

#include "console.h"
#include "console_port.h"
#include "console_out.h"
#include "ctl_port.h"
#include "ctl_wire.h"
#include "frame.h"    /* FRAME_CH_A0..A2, the channel tags the wire uses */

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
	/* The default for `=,,t` is here and nowhere else. The argument
	 * divides `measured` below, so a zero has to be resolved in the
	 * function that divides, not in the main() of each track that
	 * binds the letter - a copy per track is a guard a new track can
	 * omit without anything failing. Two channels is the sweep the
	 * ACQ_MIN_RC cliff was found on. */
	if (n_channels == 0)
		n_channels = 2;

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


/*
 * `=<ms>S`: block the main loop for a number of milliseconds the host
 * chose.
 *
 * It exists to validate the load monitor, and it is the only way to do
 * that honestly: every other long pass on this board - a printf, a
 * sweep, the profile itself - has a duration nobody knows
 * independently, so agreeing with it would prove only that two unknowns
 * match. This one has a duration the *host* chose, so the monitor can
 * be checked against a number it was not told.
 *
 * Development only, like console_trigger_fault(). It is not in the
 * control protocol's command set and must not be: a deployed
 * instrument with a remote "stop responding for a while" is a defect,
 * not a feature.
 *
 * DELIBERATELY SILENT, and that is measured rather than tidy. A printf
 * here lands in the very pass this command exists to measure - 36
 * characters at 115200 baud is 3.1 ms - and the monitor would
 * faithfully report the stall plus the announcement of it. With the
 * message in, a 5 ms stall read 7.2 ms and a 1500 ms stall read
 * 1502.7 ms: the same 2-3 ms offset at both ends. The answer to "did it
 * work" is the load report, not an echo.
 *
 * The clamp is here rather than in each track's binding for the reason
 * #68 gave for the rate sweep's channel count: a guard written once per
 * track is a guard a new track can omit with nothing failing. The upper
 * bound is long enough to see and short of the watchdog, and
 * test_control.py's heartbeat test asks for exactly it.
 */
void console_cmd_stall(uint32_t ms)
{
	if (ms == 0u)
		ms = 10u;
	if (ms > 2000u)
		ms = 2000u;    /* long enough to see, short of a watchdog */

	console_port_stall(ms);
}


/*
 * "N.NN ns per set+clear pair", from hundredths of a nanosecond.
 *
 * Fixed point, not float: a float formatter would be pulled into an
 * image whose only use for it is two debug lines, and no track has a
 * %f, %g or %e anywhere. The two decimals are what a float default
 * would have given, so the printed value is unchanged from when each
 * track computed this for itself.
 */
static void print_ns(const char *label, uint32_t us, uint32_t n)
{
	uint32_t ns_x100 = (uint32_t)(((uint64_t)us * 100000ull) / n);

	con_str("# "); con_str(label); con_str(": ");
	con_u32(ns_x100 / 100u); con_ch('.');
	con_u32w(ns_x100 % 100u, 2, '0');
	con_str(" ns per set+clear pair"); con_nl();
}

/*
 * `p`: what one 40-character console line costs, end to end.
 *
 * This is the measurement invariant 8 rests on - "printf is a debug
 * method, not an instrument" - so it is quoted between tracks and had
 * to be taken identically on each. It was not. Both tracks timed the
 * same twenty lines and then labelled the result differently, one
 * "polled, synchronous" and the other "flushed to the wire", which is
 * the ordinary way two hand-written copies of one measurement drift:
 * not in the arithmetic, where a diff would show it, but in what the
 * number is said to mean.
 */
void console_cmd_printf_cost(void)
{
	const int n = 20;
	const char *line = "0123456789012345678901234567890123456789";
	uint32_t t0, t1;

	con_str("# measuring printf cost, 20 x 40-char lines"); con_nl();
	console_flush();

	t0 = ctl_port_micros();
	/* Braces are load-bearing: con_nl() must stay INSIDE the loop, or
	 * this times n strings and one newline - a mistake that compiles
	 * clean, and has been made twice on Track B already. */
	for (int i = 0; i < n; i++) {
		con_str(line); con_nl();
	}
	/* Inside the interval: the cost is the bytes on the wire, not the
	 * bytes handed to a buffer. */
	console_flush();
	t1 = ctl_port_micros();

	con_str("# printf: "); con_u32((t1 - t0) / (uint32_t)n);
	con_str(" us per 40-char line (flushed to the wire)"); con_nl();
	con_str("# this is why printf never goes in an ISR"); con_nl();
	console_flush();
}

/*
 * `g`: what a GPIO toggle costs, direct and through this track's
 * board-support call.
 *
 * The pair is the point. Direct PIO is the only thing cheap enough to
 * put inside an ISR - about 12 ns - and the second arm says what the
 * convenient call costs instead. What the second arm IS differs
 * between tracks on purpose, so it comes back from the port with its
 * own name.
 */
void console_cmd_gpio_cost(void)
{
	const uint32_t n = 100000;
	uint32_t t0, t1, t2, t3;

	con_str("# measuring GPIO toggle cost, 100k pairs"); con_nl();
	console_flush();

	t0 = ctl_port_micros();
	console_port_toggle_direct(n);
	t1 = ctl_port_micros();

	t2 = ctl_port_micros();
	console_port_toggle_bsp(n);
	t3 = ctl_port_micros();

	print_ns("direct PIO ", t1 - t0, n);
	print_ns(console_port_toggle_bsp_name(), t3 - t2, n);
	con_str("# use direct PIO writes for ISR instrumentation"); con_nl();
	console_flush();
}


/*
 * ADC codes to millivolts at the nominal 3.3 V reference.
 *
 * NOMINAL, and the arithmetic is integer for the reason every other
 * printed figure on this console is: a float formatter would be pulled
 * into the image for one column. A bench that has measured its own
 * ADVREF corrects host-side - host/calibration.py owns that - and this
 * stays the reading the board can defend on its own.
 */
static uint32_t code_to_mv(uint16_t code)
{
	return ((uint32_t)code * 3300u) / 4095u;
}

/*
 * `r`: one DC reading of A0, A1 and A2.
 *
 * A2 is read on its own rather than as a pair, because it is the
 * impedance arm and pairing it would convert it straight after another
 * channel - which is the one thing this rig exists to hold still.
 * Software-triggered with a generous tracking time, so this is a DC
 * reading and not a sample of the artifact.
 *
 * That paragraph was true of Track B only. Track A's copy of this
 * command read A0 and A1 and stopped, so the two boards answered `r`
 * with different amounts of information and nothing said so - the
 * oracle cannot check a column it does not print. Sharing the body is
 * what makes the two answers the same question.
 */
void console_cmd_read(void)
{
	uint16_t a0, a1, a2;

	console_port_adc_read_pair(FRAME_CH_A0, FRAME_CH_A1, &a0, &a1);
	a2 = console_port_adc_read(FRAME_CH_A2);

	con_str("# A0(AD7) = "); con_u32w(a0, 4, ' ');
	con_str("  ");           con_u32w(code_to_mv(a0), 4, ' ');
	con_str(" mV    A1(AD6) = "); con_u32w(a1, 4, ' ');
	con_str("  ");           con_u32w(code_to_mv(a1), 4, ' ');
	con_str(" mV    A2(AD5) = "); con_u32w(a2, 4, ' ');
	con_str("  ");           con_u32w(code_to_mv(a2), 4, ' ');
	con_str(" mV"); con_nl();
	console_flush();
}

/*
 * `s`: step both DACs across the range and read both ADCs back.
 *
 * DAC1 is driven inverse to DAC0 so a swapped pair of jumpers shows up
 * immediately rather than reading plausibly. The endpoints of this
 * table are the measurement that matters: the DAC is not rail to rail
 * and the true limits on a given board have to be measured rather than
 * assumed.
 *
 * THE SETTLE IS THE SHARED PART, and it is why this body could not
 * stay in two places. The two tracks waited differently between
 * writing a code and converting it - Track A `delay(5)`, Track B an
 * untimed busy loop of 200,000 volatile iterations whose duration
 * nobody ever established - and this command measures what the output
 * has settled to. Two settle times are two experiments, and the whole
 * point of the second track is that its answer to one experiment can
 * be compared with the first's. console_bleed_settle() already exists
 * and already says this about itself; it is the same argument, one
 * command over.
 */
void console_cmd_dac_sweep_dc(void)
{
	con_str("# DAC sweep. DAC1 is driven inverse to DAC0."); con_nl();
	con_str("# code   DAC0mV   A0code   A0mV  |  DAC1mV   A1code   A1mV");
	con_nl();
	console_flush();

	for (uint32_t code = 0; code <= 4095u; code += 256u) {
		uint16_t c = (uint16_t)(code > 4095u ? 4095u : code);
		uint16_t inv = (uint16_t)(4095u - c);
		uint16_t a0, a1;

		console_port_dac_write(0, c);
		console_port_dac_write(1, inv);

		/* REFRESH and the RC of the pin are far slower than the
		 * conversion itself. One named constant, one duration, both
		 * tracks. */
		console_bleed_settle(CTL_BLEED_SETTLE_MS);

		console_port_adc_read_pair(FRAME_CH_A0, FRAME_CH_A1, &a0, &a1);

		con_str("# ");    con_u32w(c, 4, ' ');
		con_str("   ");   con_u32w(code_to_mv(c), 6, ' ');
		con_str("   ");   con_u32w(a0, 6, ' ');
		con_str("  ");    con_u32w(code_to_mv(a0), 5, ' ');
		con_str("  |  "); con_u32w(code_to_mv(inv), 6, ' ');
		con_str("   ");   con_u32w(a1, 6, ' ');
		con_str("  ");    con_u32w(code_to_mv(a1), 5, ' ');
		con_nl();
		console_flush();
	}
	con_str("# note: A0/A1 columns are the DAC output as actually measured");
	con_nl();
	console_flush();
}


/*
 * `d`: find the DACC's maximum update rate.
 *
 * In TAG mode one trigger produces one conversion, so the achieved
 * rate is table length times ENDTX count over elapsed time. Counting
 * the peripheral's own completions avoids needing the ADC to observe
 * the output, and gives the same kind of hard number the ADC sweep
 * produced.
 *
 * Timed over a whole number of table passes, starting on a boundary,
 * so the first interval is not whatever remained of the pass already
 * in flight.
 *
 * One body for every track, and invariant 3 is the reason rather than
 * an obstacle: two independent programmings of one converter
 * disagreeing is the finding, and it cannot be had if the two boards
 * are asked slightly different questions. They were. Track B guarded
 * the division by the configured RC and Track A did not, so a refusal
 * that still reported RC 0 would have divided by zero on one track and
 * printed a dash on the other.
 */
void console_cmd_dac_rate_sweep(void)
{
	static const uint32_t rates[] = {
		 100000,  500000,  800000, 1000000, 1200000,
		1500000, 1750000, 2000000, 2500000, 3000000
	};
	const uint32_t tc_clock = console_port_mck_hz() / 2u;
	const uint32_t table_len = console_port_gen_table_len();

	console_port_gen_init();
	con_str("# DACC update-rate sweep, TC0 ch1 (TIOA1), TAG mode"); con_nl();
	con_str("#     want      RC   TCexact    measured    ratio"); con_nl();
	console_flush();

	for (unsigned i = 0; i < sizeof(rates) / sizeof(rates[0]); i++) {
		uint32_t sync, guard, t0, t1, e0, got;
		uint32_t rc, tcexact, us, measured, ratio_x1000;
		uint64_t convs;

		if (!console_port_gen_start_independent(rates[i])) {
			con_str("# "); con_u32w(rates[i], 8, ' ');
			con_str("       -         -    REFUSED"); con_nl();
			console_flush();
			continue;
		}

		/* Start counting on a table boundary, so the first interval
		 * is a whole number of passes rather than whatever remained
		 * of the one in flight. */
		sync  = console_port_gen_endtx_count();
		guard = ctl_port_micros();
		while (console_port_gen_endtx_count() == sync &&
		       (ctl_port_micros() - guard) < 500000u)
			{ }

		t0 = ctl_port_micros();
		e0 = console_port_gen_endtx_count();
		while (console_port_gen_endtx_count() - e0 < 64u &&
		       (ctl_port_micros() - t0) < 1000000u)
			{ }
		t1  = ctl_port_micros();
		got = console_port_gen_endtx_count() - e0;

		console_port_gen_stop();

		rc      = console_port_gen_configured_rc();
		tcexact = rc ? tc_clock / rc : 0u;
		us      = t1 - t0;
		convs   = (uint64_t)got * table_len;
		measured = us ? (uint32_t)((convs * 1000000ull) / us) : 0u;
		ratio_x1000 = tcexact
		            ? (uint32_t)(((uint64_t)measured * 1000ull) / tcexact)
		            : 0u;

		con_str("# "); con_u32w(rates[i], 8, ' ');
		con_ch(' ');   con_u32w(rc, 7, ' ');
		con_ch(' ');   con_u32w(tcexact, 9, ' ');
		con_ch(' ');   con_u32w(measured, 11, ' ');
		con_str("   "); con_u32w(ratio_x1000 / 1000u, 2, ' ');
		con_ch('.');   con_u32w(ratio_x1000 % 1000u, 3, '0');
		con_nl();
		console_flush();
	}
	con_str("# ratio 1.000 means every trigger produced a DAC update");
	con_nl();
	console_flush();
}

/*
 * `j` and `k`: cross-check the DAC ceiling against the frequency it
 * actually emits.
 *
 * ENDTX counts PDC completions, which equal conversions only if the
 * DACC back-pressures the PDC when it cannot keep up. Driving the DAC
 * on its own timebase and capturing the result gives an independent
 * measure: a table of N entries played at R conversions per second
 * must produce a tone at R/N, whatever the trigger was set to.
 *
 * THE PRINT ORDER IS THE MEASUREMENT, and this is the one command
 * where a tidy-up would be a regression. The three lines below go out
 * AFTER the capture start, not before it as `1`..`5` and `L` do. The
 * interval between the generator start and the capture start fixes the
 * sampling phase against the DAC table's wrap - which is the quantity
 * this command exists to read, one sample per wrap - so the print's
 * UART time is part of what sets it. docs/debugging.md prices the site
 * at +4.77 ms of margin against a 20.32 ms runway: about one more
 * banner line from losing frames. It survives only because the capture
 * is pinned at 200,000 Hz, where the ring holds its longest runway. If
 * a print is ever needed here, put it ABOVE the generator start, where
 * it costs nothing.
 */
void console_cmd_dac_crosscheck(uint32_t dac_hz)
{
	console_port_gen_init();
	if (!console_port_gen_start_independent(dac_hz)) {
		con_str("# refused"); con_nl();
		console_flush();
		return;
	}
	if (!console_port_capture_only_start(200000, 2)) {
		/* Stopped, not left running. Track A returned here with the
		 * generator still driving TIOA1, so a refused cross-check
		 * left the DAC emitting into every measurement after it. */
		console_port_gen_stop();
		con_str("# capture refused"); con_nl();
		console_flush();
		return;
	}

	con_str("# DAC indep "); con_u32(dac_hz);
	con_str(" Hz (RC "); con_u32(console_port_gen_configured_rc());
	con_str("), capture 200000 Hz"); con_nl();
	con_str("# if the DAC truly runs at the trigger, tone = ");
	con_u32(dac_hz / console_port_gen_table_len());
	con_str(" Hz"); con_nl();
	con_str("# if it saturates near 1539700, tone = 3007 Hz instead");
	con_nl();
	console_flush();
}


/*
 * `w`: the capture stream over the programming-port UART.
 *
 * The banner names the waveform the same way `1`..`5` do, and through
 * the same accessor, so the two cannot describe one generator
 * differently. It goes out BEFORE the start for the reason
 * console_cmd_stream() gives at length: capture is device-driven and
 * the ring fills the moment the timer runs.
 *
 * Except it did not, on either track: both printed after the start.
 * That is safe here in a way it is not elsewhere - 2 kHz is a hundredth
 * of the rate the runway was priced at - but it is the same ordering
 * written the wrong way twice, and one body is how it stops being a
 * thing to remember.
 */
void console_cmd_stream_uart(uint32_t trigger_hz)
{
	ctl_gen_t g;
	bool have_gen = ctl_port_gen_get(&g);

	con_str("# uart-stream: trigger "); con_u32(trigger_hz);
	if (have_gen) {
		con_str(" Hz, "); con_str(gen_shape_name(g.shape)); con_ch(' ');
		con_u32(gen_hz_for(trigger_hz, g.points, g.sync));
		con_str(" Hz");
	}
	con_str(" - binary follows"); con_nl();
	console_flush();

	if (!console_port_stream_uart_start(trigger_hz)) {
		con_str("# refused"); con_nl();
		console_flush();
	}
}


/*
 * `O`: the playback ring's occupancy, its rate trace, and the capture
 * side of the same question.
 *
 * READ THROUGH THE CONTROL CHANNEL'S OWN FILLERS, not through the
 * counters directly. ctl_port_occupancy() and ctl_port_rate_page()
 * exist on every track because CTL_OP_OCCUPANCY and CTL_OP_RATE_TRACE
 * do, so calling them here costs one buffer and buys the guarantee
 * that the console and the command port cannot report different
 * numbers for one run. That matters more here than anywhere: `O` is
 * the ORACLE tests/test_play_counters.py holds the bulk-IN carrier
 * against, and an oracle that reads its own copy of the counters is
 * checking a transcription rather than the instrument.
 *
 * Printed as a bare comma-separated list rather than key=value pairs:
 * 32 buckets as `occ0=..` would be a long line for a parse that gains
 * nothing, and the index is the occupancy, so position is the key.
 *
 * The absolute microseconds are sent, not the deltas. The host
 * differences them; sending deltas would throw away the only reading
 * that survives a disturbed sample.
 */
void console_cmd_occ_hist(void)
{
	uint8_t body[CTL_MAX_PAYLOAD];
	ctl_occupancy_t o;
	const uint8_t *p;
	unsigned i;
	int n;

	n = ctl_port_occupancy(body, sizeof(body));
	if (n < (int)sizeof(o)) {
		con_str("# play_occ: not available on this track"); con_nl();
		console_flush();
		return;
	}
	memcpy(&o, body, sizeof(o));
	p = body + sizeof(o);

	con_str("# play_occ ");
	con_kv_u32("min", o.occ_min);          con_ch(' ');
	con_kv_u32("endtx", o.endtx_seen);     con_ch(' ');
	con_kv_u32("runus", o.run_us);         con_ch(' ');
	con_kv_u32("consumed", o.consumed);    con_str(" hist=");
	for (i = 0; i < o.nbuf; i++) {
		uint32_t v;

		memcpy(&v, p + i * sizeof(v), sizeof(v));
		con_u32(v);
		if (i + 1u < o.nbuf)
			con_ch(',');
	}
	con_nl();
	console_flush();

	p += (size_t)o.nbuf * sizeof(uint32_t);
	con_str("# play_occ_trace ");
	con_kv_u32("decim", o.trace_decim);    con_ch(' ');
	con_kv_u32("n", o.trace_n);            con_str(" v=");
	for (i = 0; i < o.trace_n; i++) {
		con_u32(p[i]);
		if (i + 1u < o.trace_n)
			con_ch(',');
		/* 256 entries is more than one UART buffer holds. */
		if ((i & 31u) == 31u)
			console_flush();
	}
	con_nl();
	console_flush();

	/* The playback rate trace, page by page - it does not fit one
	 * packet, and the pager is the control channel's, so the console
	 * cannot disagree with it about where the trace ends. */
	{
		ctl_rate_page_t pg;
		uint16_t off = 0;
		bool opened = false;

		for (;;) {
			int r = ctl_port_rate_page(body, sizeof(body), off);

			if (r < (int)sizeof(pg)) {
				if (!opened) {
					con_str("# play_rate: not built on "
					        "this track"); con_nl();
					console_flush();
				}
				break;
			}
			memcpy(&pg, body, sizeof(pg));
			if (!opened) {
				con_str("# play_rate ");
				con_kv_u32("decim", pg.decim);  con_ch(' ');
				con_kv_u32("n", pg.total);      con_str(" us=");
				opened = true;
			}
			for (i = 0; i < pg.count; i++) {
				uint32_t v;

				memcpy(&v, body + sizeof(pg) + i * sizeof(v),
				       sizeof(v));
				con_u32(v);
				if (pg.offset + i + 1u < pg.total)
					con_ch(',');
				if ((i & 15u) == 15u)
					console_flush();
			}
			off = (uint16_t)(pg.offset + pg.count);
			if (pg.count == 0 || off >= pg.total)
				break;
		}
		if (opened) {
			con_nl();
			console_flush();
		}
	}

	/*
	 * The capture side. Said to be absent rather than printed as
	 * nothing: with the trace compiled out this used to print no line
	 * at all, and a host cannot tell that from a run that captured
	 * nothing - which is the defect CTL_ERR_OPCODE exists to avoid on
	 * the control channel. Silence is the same trap with less
	 * information in it.
	 */
	{
		const uint32_t *us;
		const uint8_t *occ;
		uint32_t an;

		if (!console_port_acq_rate_trace(&an, &us, &occ)) {
			con_str("# acq_rate: not built on this track");
			con_nl();
			console_flush();
			return;
		}
		con_str("# acq_rate "); con_kv_u32("n", an);
		con_str(" us=");
		for (i = 0; i < an; i++) {
			con_u32(us[i]);
			if (i + 1u < an)
				con_ch(',');
			if ((i & 15u) == 15u)
				console_flush();
		}
		con_str(" occ=");
		for (i = 0; i < an; i++) {
			con_u32(occ[i]);
			if (i + 1u < an)
				con_ch(',');
			if ((i & 31u) == 31u)
				console_flush();
		}
		con_nl();
		console_flush();
	}
}


/*
 * `=<n>,<ms>x`: multiplexer bleed, measured properly.
 *
 * Hold one channel's DAC fixed and swing the other, then look at
 * whether the held channel moved. Swinging both at once cannot isolate
 * anything, since each channel's change would be fully explained by
 * its own DAC. The ADC has one sample-and-hold behind a 16:1
 * multiplexer, so residual charge from the previously converted
 * channel contaminates the next, and any movement in the held channel
 * is that bleed.
 *
 * It prints a distribution, never one number, and in the order taken:
 * this quantity is bimodal on an otherwise idle board, so a single
 * draw reported as a measurement is the defect whichever value it
 * lands on. The loud observations recur on a fixed cadence tied to the
 * settle time - a beat against something periodic, not a coin flip and
 * not a startup condition - which is why the settle is a knob.
 *
 * Each arm carries a control that swings nothing, writing the same DAC
 * code twice where the real arm writes 0 then 4095. Same writes, same
 * waits, same conversions, so a difference between arm and control
 * isolates the swing from the reading itself. docs/noise.md.
 *
 * EVERY READ IS THE TWO-CHANNEL SEQUENCE, and that is not a detail.
 * The conversion preceding the watched one is what bleeds into it, so
 * converting the watched channel alone measures something else
 * entirely - worth a sign and a factor of twelve when the two tracks
 * once did it differently, which made a bleed figure incomparable
 * across them. Which channel is watched follows the conversion
 * position, not the pin: A2 is channel 5 and A1 is 6, so either way
 * the second converts BEFORE A0 at 7, and `=2C` swaps the pin while
 * holding the position fixed.
 *
 * What it assumes about the bench differs between ours, so it reports
 * which it found rather than assuming: the A1 arm holds DAC1 at mid
 * scale and swings DAC0, and where DAC1 is jumpered to A1 that pin is
 * *driven* to the held level, while where DAC1 goes to a scope's
 * external trigger it is free and reads a smeared copy of whatever
 * converted before it.
 */
void console_cmd_crosstalk(unsigned repeats, uint32_t settle_ms)
{
	int16_t a1_bleed[CTL_BLEED_MAX], a0_bleed[CTL_BLEED_MAX];
	int16_t a1_still[CTL_BLEED_MAX], a0_still[CTL_BLEED_MAX];
	uint16_t a1b_lo[CTL_BLEED_MAX], a1b_hi[CTL_BLEED_MAX];
	uint16_t a1s_lo[CTL_BLEED_MAX], a1s_hi[CTL_BLEED_MAX];
	uint16_t a0b_lo[CTL_BLEED_MAX], a0b_hi[CTL_BLEED_MAX];
	uint16_t a0s_lo[CTL_BLEED_MAX], a0s_hi[CTL_BLEED_MAX];
	unsigned n  = repeats ? repeats : CTL_BLEED_DEFAULT;
	uint32_t ms = settle_ms ? settle_ms : CTL_BLEED_SETTLE_MS;
	uint32_t psr, osr, pusr, ifsr, restarts, timeouts;
	uint16_t a0, a1, lo, hi;
	unsigned second;
	unsigned i;
	bool a2;

	if (n > CTL_BLEED_MAX)
		n = CTL_BLEED_MAX;
	if (ms > CTL_BLEED_SETTLE_MAX_MS)
		ms = CTL_BLEED_SETTLE_MAX_MS;

	if (console_port_measure_begin() != 0) {
		con_str("# crosstalk: refused, the ADC is hardware-triggered"
		        " - stop the capture first (0)"); con_nl();
		console_flush();
		return;
	}

	con_str("# crosstalk: hold one channel, swing the other, ");
	con_u32(n); con_str(" times, "); con_u32(ms);
	con_str(" ms settle"); con_nl();
	con_str("# each arm has a control that writes the same code twice,"
	        " so the swing is the only difference"); con_nl();
	/*
	 * The conditions as the hardware holds them, not as this function
	 * believes it set them - a register cannot drift from what was
	 * measured. Raw, decoded by the host.
	 */
	con_str("# adcmr="); con_hex32(console_port_acq_mr(), 8);
	con_str(" (this command's own; restored after)"); con_nl();
	console_flush();

	/* PUSR reads 1 where the pull-up is DISABLED, PSR reads 1 where
	 * the PIO (not the peripheral) owns the pin. A0=PA16, A1=PA24,
	 * A2=PA23, all PIOA. */
	console_port_pad_state(&psr, &osr, &pusr, &ifsr);
	con_str("# pioa: psr="); con_hex32(psr, 8);
	con_str(" osr=");        con_hex32(osr, 8);
	con_str(" pusr=");       con_hex32(pusr, 8);
	con_str(" ifsr=");       con_hex32(ifsr, 8);
	con_nl();
	console_flush();

	second = console_port_acq_pair_second();

	for (i = 0; i < n; i++) {
		/* Hold DAC1 mid scale; swing DAC0. Watch the second channel. */
		console_port_dac_write(1, 2048);
		console_port_dac_write(0, 0);
		console_bleed_settle(ms);
		console_port_adc_read_pair(FRAME_CH_A0, second, &a0, &lo);

		console_port_dac_write(0, 4095);
		console_bleed_settle(ms);
		console_port_adc_read_pair(FRAME_CH_A0, second, &a0, &hi);
		a1_bleed[i] = (int16_t)((int)hi - (int)lo);
		a1b_lo[i] = lo; a1b_hi[i] = hi;

		/* Same arm with nothing swung: DAC0 written twice at the
		 * same code. Identical writes, waits and conversions, so a
		 * difference here is not crosstalk from a moving neighbour. */
		console_port_dac_write(0, 2048);
		console_bleed_settle(ms);
		console_port_adc_read_pair(FRAME_CH_A0, second, &a0, &lo);

		console_port_dac_write(0, 2048);
		console_bleed_settle(ms);
		console_port_adc_read_pair(FRAME_CH_A0, second, &a0, &hi);
		a1_still[i] = (int16_t)((int)hi - (int)lo);
		a1s_lo[i] = lo; a1s_hi[i] = hi;

		/* Hold DAC0 mid scale; swing DAC1. Watch A0. */
		console_port_dac_write(0, 2048);
		console_port_dac_write(1, 0);
		console_bleed_settle(ms);
		console_port_adc_read_pair(FRAME_CH_A0, second, &lo, &a1);

		console_port_dac_write(1, 4095);
		console_bleed_settle(ms);
		console_port_adc_read_pair(FRAME_CH_A0, second, &hi, &a1);
		a0_bleed[i] = (int16_t)((int)hi - (int)lo);
		a0b_lo[i] = lo; a0b_hi[i] = hi;

		/* And its control. */
		console_port_dac_write(1, 2048);
		console_bleed_settle(ms);
		console_port_adc_read_pair(FRAME_CH_A0, second, &lo, &a1);

		console_port_dac_write(1, 2048);
		console_bleed_settle(ms);
		console_port_adc_read_pair(FRAME_CH_A0, second, &hi, &a1);
		a0_still[i] = (int16_t)((int)hi - (int)lo);
		a0s_lo[i] = lo; a0s_hi[i] = hi;
	}

	/* Name the channel that was watched: with `=2C` selected these
	 * rows are about A2, and a label saying A1 would attribute the
	 * figure to the wrong pin. Whole literals rather than a label
	 * built at runtime - issue #49. */
	a2 = (second == FRAME_CH_A2);

	ctl_bleed_describe(a2 ? "A2 bleed (DAC1 held, DAC0 swung)"
	                      : "A1 bleed (DAC1 held, DAC0 swung)",
	                   a1_bleed, n);
	ctl_bleed_values(a2 ? "A2 bleed" : "A1 bleed", a1_bleed, n);
	ctl_bleed_raw(a2 ? "A2 bleed" : "A1 bleed", a1b_lo, a1b_hi, n);
	ctl_bleed_describe(a2 ? "A2 control (nothing swung)"
	                      : "A1 control (nothing swung)",
	                   a1_still, n);
	ctl_bleed_values(a2 ? "A2 control" : "A1 control", a1_still, n);
	ctl_bleed_raw(a2 ? "A2 control" : "A1 control", a1s_lo, a1s_hi, n);
	console_flush();

	ctl_bleed_describe(a2 ? "A0 bleed (DAC0 held, DAC1 swung, A2 in pair)"
	                      : "A0 bleed (DAC0 held, DAC1 swung, A1 in pair)",
	                   a0_bleed, n);
	ctl_bleed_values("A0 bleed", a0_bleed, n);
	ctl_bleed_raw("A0 bleed", a0b_lo, a0b_hi, n);
	ctl_bleed_describe("A0 control (nothing swung)", a0_still, n);
	ctl_bleed_values("A0 control", a0_still, n);
	ctl_bleed_raw("A0 control", a0s_lo, a0s_hi, n);

	/* Which bench this is, read rather than assumed. With DAC1
	 * jumpered to A1, holding DAC1 at 2048 drives A1 to about 2048;
	 * with A1 free it sits wherever the mux left it. */
	console_port_dac_write(1, 2048);
	console_bleed_settle(ms);
	console_port_adc_read_pair(FRAME_CH_A0, FRAME_CH_A1, &a0, &a1);
	con_str("# A1 reads "); con_u32(a1);
	con_str(" with DAC1 held at 2048: ");
	con_str((a1 > 1800u && a1 < 2300u)
	        ? "DAC1 -> A1 is fitted"
	        : "A1 looks undriven - see docs/noise.md");
	con_nl();
	con_str("# bleed is in ADC codes; 1 code = 0.8 mV."
	        " Full swing is 2747 codes."); con_nl();
	con_str("# taken at TRACKTIM 15, SETTLING 3 - this command's own,"
	        " not whatever ADC_MR held"); con_nl();
	console_port_pair_faults(&restarts, &timeouts);
	con_str("# pair-conv: ");
	con_kv_u32("restarts", restarts); con_ch(' ');
	con_kv_u32("timeouts", timeouts);
	con_str(" (nonzero: see #23)"); con_nl();

	console_port_measure_end();
	console_flush();
}


/*
 * `Q`'s frame and its rows. The list between them is each track's own -
 * see console.h for why that is the right split and not a shortcut.
 *
 * Integer nanoseconds from microseconds and a count, in one place, so
 * two tracks' rows are the same quantity. The label is padded to a
 * fixed width for the same reason the numbers are: a column that moves
 * between tracks is a column nobody diffs.
 */
void console_profile_begin(void)
{
	con_str("# main-loop profile, ns per call"); con_nl();
	console_flush();
}

void console_profile_row(const char *label, uint32_t us, uint32_t n)
{
	con_str("# ");
	con_strl(label, 22);
	con_ch(' ');
	con_u32w((uint32_t)(((uint64_t)us * 1000ull) / n), 6, ' ');
	con_str(" ns"); con_nl();
	console_flush();
}

void console_profile_end(void)
{
	con_str("# note: services early-return unless started"); con_nl();
	console_flush();
}


/*
 * `y`: two reads of the time source about 100 ms apart.
 *
 * The delta is the measurement and the absolute values say the counter
 * is live rather than stuck. Both are needed: a source frozen at a
 * large value passes a liveness check that only looks at the reading,
 * and one that advances at the wrong rate passes one that only looks
 * for movement.
 *
 * The wait is console_bleed_settle(), which spins on the device clock -
 * so this reads millis() against a micros()-derived wait, and the two
 * disagreeing is exactly the failure it is here to catch. Not each
 * track's own sleep: Track C's vTaskDelay() would test the tick
 * instead, which is a different question and not one the other two
 * can be asked.
 */
void console_cmd_time_check(void)
{
	uint32_t m0, u0, m1, u1;

	m0 = ctl_port_millis();
	u0 = ctl_port_micros();
	console_bleed_settle(100);
	m1 = ctl_port_millis();
	u1 = ctl_port_micros();

	con_str("# time ");
	con_kv_u32("millis", m1);            con_ch(' ');
	con_kv_u32("micros", u1);            con_ch(' ');
	con_kv_u32("d_ms", m1 - m0);         con_ch(' ');
	con_kv_u32("d_us", u1 - u0);
	con_str("  (asked for 100 ms)");     con_nl();
	console_flush();
}
