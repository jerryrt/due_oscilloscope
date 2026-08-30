/*
 * Track B bring-up: bare-metal counterpart of sketches/bringup.
 *
 * Feature-equivalent to the Track A oracle on purpose. Same commands,
 * same output format, same measurements, so the two can be compared
 * directly and any divergence is a real difference rather than an
 * artefact of the harness.
 *
 * Commands over the programming port at 115200:
 *   h  help
 *   p  measure printf cost
 *   g  measure GPIO toggle cost
 *   f  trigger a deliberate hard fault
 */

#include <stdio.h>

#include "sam.h"
#include "bsp.h"
#include "clock.h"
#include "analog.h"
#include "acq.h"
#include "gen.h"
#include "stream.h"
#include "frame.h"
#include "play.h"
#include "play_report.h"
#include "playstat.h"
#include "ctl.h"
#include "console.h"          /* the shared command surface */
#include "ctl_port.h"   /* ctl_port_gen_get: the console reads the
                            * generator through the same hook the control
                            * channel does, so the two cannot disagree */
#include "load.h"
#include "usb_cdc.h"
#include "track_id.h"
#include "fw_version.h"

#define LED_MASK (1u << 27)

/*
 * One line saying which firmware this is. Same format on both tracks -
 * see lib/due_shared/src/fw_version.h - so a host reads one regular expression rather
 * than matching the banner's prose, and so a board can be identified
 * without paying for the banner (89 ms of blocked main loop, invariant
 * 8). `v` prints exactly this and nothing else.
 */
/*
 * The line itself is console_identity() in lib/due_shared: the format
 * and the order of its arguments are what measure.parse_identity reads,
 * so they are wire contract and have one home. FW_TRACK and the clock
 * are this track's to supply.
 */
static void identity_line(void)
{
	console_identity(FW_TRACK, (unsigned long)SystemCoreClock);
}

/*
 * This track's own facts, then the shared command list.
 *
 * The list used to be twenty-eight printf lines here and twenty-eight
 * more in Track A's sketch, which is how the two command sets came to
 * differ by twelve without anyone deciding they should - issue #13.
 * console_help() prints one table, so a command that exists on one
 * track and not the other now says so on both.
 *
 * The numbers stay here, where they can be computed. A shared help line
 * carrying "453488" would be a figure written down a second time, and
 * this project's rule about invented numbers applies hardest to the
 * ones that look derived.
 */
static void banner(void)
{
	printf("#\n");
	printf("# due_oscilloscope :: Track B bare-metal bring-up\n");
	identity_line();
	printf("# SystemCoreClock = %lu  ADC clk = %lu (max 20000000)\n",
	       (unsigned long)SystemCoreClock, (unsigned long)(SystemCoreClock / 4u));
	printf("# max in-spec trigger = %lu Hz (RC %u); presets 1..4 are 50k/100k/200k/400k\n",
	       (unsigned long)((SystemCoreClock / 2u) / ACQ_MIN_RC),
	       (unsigned)ACQ_MIN_RC);
	printf("# h for the command list\n");
	printf("#\n");
}

/*
 * `h`: the facts, then the list.
 *
 * They are split because boot prints the banner and `h` is typed. The
 * list is 47 lines now that it names what this track has *not* got, and
 * every one of them is UART time the main loop is not draining bulk OUT
 * for - invariant 8, and the banner was already the most expensive
 * thing on the console at 89 ms. Boot pays for the identity it has to
 * print and nothing else; the list costs what it costs, to whoever asks
 * for it.
 */
static void cmd_help(void)
{
	banner();
	printf("# commands:\n");
	console_help();
	printf("#\n");
}

/* Fixed-point ns with two decimals, avoiding a float-enabled printf. */
static void print_ns(const char *label, uint32_t us, uint32_t n)
{
	uint32_t ns_x100 = (uint32_t)(((uint64_t)us * 100000ull) / n);

	printf("# %s: %lu.%02lu ns per set+clear pair\n", label,
	       (unsigned long)(ns_x100 / 100u),
	       (unsigned long)(ns_x100 % 100u));
}

static void measure_printf(void)
{
	const int n = 20;
	const char *line = "0123456789012345678901234567890123456789";

	printf("# measuring printf cost, 20 x 40-char lines\n");
	uart_flush();

	uint32_t t0 = micros();
	for (int i = 0; i < n; i++)
		printf("%s\n", line);
	uart_flush();
	uint32_t t1 = micros();

	printf("# printf: %lu us per 40-char line (polled, synchronous)\n",
	       (unsigned long)((t1 - t0) / n));
	printf("# this is why printf never goes in an ISR\n");
	uart_flush();
}

static void measure_gpio(void)
{
	const uint32_t n = 100000;

	printf("# measuring GPIO toggle cost, 100k pairs\n");
	uart_flush();

	uint32_t t0 = micros();
	for (uint32_t i = 0; i < n; i++) {
		PIOB->PIO_SODR = LED_MASK;
		PIOB->PIO_CODR = LED_MASK;
	}
	uint32_t t1 = micros();

	uint32_t t2 = micros();
	for (uint32_t i = 0; i < n; i++) {
		led_on();
		led_off();
	}
	uint32_t t3 = micros();

	print_ns("direct PIO ", t1 - t0, n);
	print_ns("via bsp led", t3 - t2, n);
	printf("# use direct PIO writes for ISR instrumentation\n");
	uart_flush();
}
/* The M preset's ADC-start-to-DAC-start gap. See case 'K'. */
static uint32_t mimic_start_delay_us;

/* "=<n>x": how many crosstalk observations. See cmd_crosstalk(). */
static uint32_t crosstalk_repeats;


static void cmd_read(void)
{
	uint16_t a0, a1, a2;

	adc_read_pair(ADC_CH_A0, ADC_CH_A1, &a0, &a1);
	a2 = adc_read(ADC_CH_A2);
	/*
	 * A2 is read separately rather than as a pair, because it is
	 * the impedance arm and pairing it would convert it straight
	 * after another channel - which is the one thing this rig
	 * exists to hold still. Software-triggered with a generous
	 * tracking time, so this is a DC reading and not a sample of
	 * the artifact.
	 */
	printf("# A0(AD7) = %4u  %4lu mV    A1(AD6) = %4u  %4lu mV    "
	       "A2(AD5) = %4u  %4lu mV\n",
	       a0, (unsigned long)code_to_mv(a0),
	       a1, (unsigned long)code_to_mv(a1),
	       a2, (unsigned long)code_to_mv(a2));
	uart_flush();
}

/*
 * Step both DACs and read both ADCs. DAC1 is driven inverse to DAC0 so a
 * swapped pair of jumpers shows up immediately rather than reading
 * plausibly.
 *
 * The endpoints of this table are the measurement that matters: the DAC
 * is not rail to rail, and the true limits on this board have to be
 * measured rather than assumed.
 */
static void cmd_sweep(void)
{
	printf("# DAC sweep. DAC1 is driven inverse to DAC0.\n");
	printf("# code   DAC0mV   A0code   A0mV  |  DAC1mV   A1code   A1mV\n");
	uart_flush();

	for (uint32_t code = 0; code <= 4095u; code += 256u) {
		uint16_t c = (uint16_t)(code > 4095u ? 4095u : code);
		uint16_t inv = (uint16_t)(4095u - c);
		uint16_t a0, a1;

		dac_write(0, c);
		dac_write(1, inv);

		/* Let the output settle; REFRESH and the RC of the pin are
		 * far slower than the conversion itself. */
		for (volatile uint32_t d = 0; d < 200000u; d++) { }

		adc_read_pair(ADC_CH_A0, ADC_CH_A1, &a0, &a1);

		printf("# %4u   %6lu   %6u  %5lu  |  %6lu   %6u  %5lu\n",
		       c, (unsigned long)code_to_mv(c), a0,
		       (unsigned long)code_to_mv(a0),
		       (unsigned long)code_to_mv(inv), a1,
		       (unsigned long)code_to_mv(a1));
		uart_flush();
	}
	printf("# note: A0/A1 columns are the DAC output as actually measured\n");
	uart_flush();
}

/*
 * Measure multiplexer crosstalk properly: hold one channel's DAC fixed
 * and swing the other, then look at whether the held channel moved.
 *
 * An earlier version swung both DACs at once, which cannot isolate
 * anything: each channel's change was fully explained by its own DAC.
 *
 * The ADC has one sample-and-hold behind a 16:1 multiplexer, so residual
 * charge from the previously converted channel contaminates the next.
 * Any movement in the held channel is that bleed.
 *
 * Tracking time is generous here, so this is close to a best case. The
 * fast configuration used for streaming will look worse.
 */
/*
 * How long to wait for a DAC output to settle before converting -
 * "=<n>,<ms>x", default CTL_BLEED_SETTLE_MS.
 *
 * It is a knob because the excursion issue #16 is about recurs on a
 * fixed *cadence* rather than at random, and only moving the cadence
 * separates a beat against something periodic from a count kept in
 * software. Moving it is what measured the 64 ms period.
 *
 * This used to be a busy loop of 400,000 iterations here and delay(10)
 * on Track A, so the same command waited different times on the two
 * tracks and their figures were not comparable. Wall clock on both now.
 */
static uint32_t crosstalk_settle_ms;

/*
 * Multiplexer bleed, repeated - "=<n>,<ms>x".
 *
 * **It prints a distribution, never one number, and in the order taken.**
 * Issue #16 measured this quantity to be spread on an otherwise idle
 * board: about 0 codes or about 160, the loud ones 10-15% of
 * observations, with ADC_MR read back identical in both. 160 codes is
 * 5.8% of the 2747-code full swing, so the two answers disagree about
 * whether the multiplexer is clean, and a single draw reported as a
 * measurement is the defect whichever value is right.
 *
 * **It is not two modes, which is what the order settled.** The loud
 * observations recur on a fixed cadence inside a run, and the cadence
 * moves with the settle time so that gap x observation-duration is a
 * multiple of 64 ms at every setting tested. A beat against something
 * periodic, then - not a coin flip and not a startup condition.
 *
 * **Which channel is set by the conversion position, not the pin** -
 * see the `=<n>C` note below. The A0 arm has never shown it on either
 * track in any pairing.
 *
 * **Each arm carries a control that swings nothing**, writing the same
 * DAC code twice where the real arm writes 0 then 4095. Same writes,
 * same waits, same conversions. On the *driven* channel it has never
 * once been loud - 0 in 1,005 observations on Track A and 0 in 225 on
 * Track B - which is what makes that excursion about the swing rather
 * than the reading. On a *bare* channel it is loud: `=2C` reads a
 * standing +37 codes with nothing swung and +95 with, so those are two
 * effects and the control is what tells them apart. docs/noise.md.
 *
 * **What it assumes about the bench, which differs between ours.** The
 * A1 arm holds DAC1 at mid scale and swings DAC0. Where DAC1 is
 * jumpered to A1 that pin is *driven* to the held level; where DAC1
 * goes to a scope's external trigger it is *free*, and one
 * sample-and-hold behind a 16:1 mux makes a free input read a smeared
 * copy of whatever was converted before it. The command works either
 * way and does not measure the same thing - so it says which it found.
 */
static void cmd_crosstalk(void)
{
	int16_t a1_bleed[CTL_BLEED_MAX], a0_bleed[CTL_BLEED_MAX];
	int16_t a1_still[CTL_BLEED_MAX], a0_still[CTL_BLEED_MAX];
	uint16_t a1b_lo[CTL_BLEED_MAX], a1b_hi[CTL_BLEED_MAX];
	uint16_t a1s_lo[CTL_BLEED_MAX], a1s_hi[CTL_BLEED_MAX];
	uint16_t a0b_lo[CTL_BLEED_MAX], a0b_hi[CTL_BLEED_MAX];
	uint16_t a0s_lo[CTL_BLEED_MAX], a0s_hi[CTL_BLEED_MAX];
	unsigned n = crosstalk_repeats ? crosstalk_repeats : CTL_BLEED_DEFAULT;
	uint32_t ms = crosstalk_settle_ms ? crosstalk_settle_ms
	                                  : CTL_BLEED_SETTLE_MS;
	uint16_t a0, a1, lo, hi;
	char line[224];
	unsigned i;

	if (n > CTL_BLEED_MAX)
		n = CTL_BLEED_MAX;
	if (ms > CTL_BLEED_SETTLE_MAX_MS)
		ms = CTL_BLEED_SETTLE_MAX_MS;

	if (adc_measure_begin() != 0) {
		printf("# crosstalk: refused, the ADC is hardware-triggered - stop the capture first (0)\n");
	uart_flush();
	return;
	}

	printf("# crosstalk: hold one channel, swing the other, %u times,"
	       " %lu ms settle\n", n, (unsigned long)ms);
	printf("# each arm has a control that writes the same code twice, so"
	       " the swing is the only difference\n");
	/*
	 * The conditions as the hardware holds them, not as this function
	 * believes it set them. Issue #16 spent a bench session on two
	 * tracks disagreeing about a bleed figure while both printed the
	 * same prose; the register is the only account that cannot drift
	 * from what was measured. Raw, and decoded by the host - the cost
	 * of a console command is the bytes it puts on the wire.
	 */
	printf("# adcmr=%08lx (this command's own; restored after)\n",
	       (unsigned long)acq_mr());
	uart_flush();

	/*
	 * The pads too, not only the converter. Issue #16(b)'s leading
	 * suspect for the tracks' 3.3x disagreement on a bare channel is
	 * what the two startups leave on the pins: the Arduino core walks
	 * every pin at init, this build touches none, and a pull-up is
	 * ~100k toward VDDIO on a pin nothing drives. Raw registers,
	 * decoded by the reader - PUSR reads 1 where the pull-up is
	 * DISABLED, PSR 1 where the PIO (not the peripheral) owns the
	 * pin. A0=PA16, A1=PA24, A2=PA23, all PIOA.
	 */
	printf("# pioa: psr=%08lx osr=%08lx pusr=%08lx ifsr=%08lx\n",
	       (unsigned long)PIOA->PIO_PSR,
	       (unsigned long)PIOA->PIO_OSR,
	       (unsigned long)PIOA->PIO_PUSR,
	       (unsigned long)PIOA->PIO_IFSR);
	uart_flush();

	/*
	 * The pair `C` selected, not a hardcoded A1. Issue #16's named
	 * test is whether the excursion follows the *pin* or the
	 * *position*, and only `=2C` can ask it: A2 is 5 and A1 is 6, so
	 * either way the second channel converts BEFORE A0 (7) - the
	 * sequencer goes by channel index and `adc_read_pair`'s argument
	 * order only chooses which CDR is read out afterwards. So `=2C`
	 * swaps the pin while holding the conversion position fixed,
	 * which is exactly the one variable worth moving.
	 */
	const unsigned second = acq_pair_second;

	for (i = 0; i < n; i++) {
		/* Hold DAC1 mid scale; swing DAC0. Watch the second channel. */
		dac_write(1, 2048);
		dac_write(0, 0);
		console_bleed_settle(ms);
		adc_read_pair(ADC_CH_A0, second, &a0, &lo);

		dac_write(0, 4095);
		console_bleed_settle(ms);
		adc_read_pair(ADC_CH_A0, second, &a0, &hi);
		a1_bleed[i] = (int16_t)((int)hi - (int)lo);
		a1b_lo[i] = lo; a1b_hi[i] = hi;

		/* Same arm with nothing swung: DAC0 is written twice at the
		 * same code. Identical writes, waits and conversions, so a
		 * difference here is not crosstalk from a moving neighbour. */
		dac_write(0, 2048);
		console_bleed_settle(ms);
		adc_read_pair(ADC_CH_A0, second, &a0, &lo);

		dac_write(0, 2048);
		console_bleed_settle(ms);
		adc_read_pair(ADC_CH_A0, second, &a0, &hi);
		a1_still[i] = (int16_t)((int)hi - (int)lo);
		a1s_lo[i] = lo; a1s_hi[i] = hi;

		/* Hold DAC0 mid scale; swing DAC1. Watch A0. */
		dac_write(0, 2048);
		dac_write(1, 0);
		console_bleed_settle(ms);
		adc_read_pair(ADC_CH_A0, second, &lo, &a1);

		dac_write(1, 4095);
		console_bleed_settle(ms);
		adc_read_pair(ADC_CH_A0, second, &hi, &a1);
		a0_bleed[i] = (int16_t)((int)hi - (int)lo);
		a0b_lo[i] = lo; a0b_hi[i] = hi;

		/* And its control. */
		dac_write(1, 2048);
		console_bleed_settle(ms);
		adc_read_pair(ADC_CH_A0, second, &lo, &a1);

		dac_write(1, 2048);
		console_bleed_settle(ms);
		adc_read_pair(ADC_CH_A0, second, &hi, &a1);
		a0_still[i] = (int16_t)((int)hi - (int)lo);
		a0s_lo[i] = lo; a0s_hi[i] = hi;
	}

	/*
	 * Name the channel that was watched. With `=2C` selected these
	 * rows are about A2 and a label saying A1 would be a figure
	 * attributed to the wrong pin - which is the class of error this
	 * whole issue is about.
	 */
	const char *sname = (second == ADC_CH_A2) ? "A2" : "A1";
	char label[64];

	snprintf(label, sizeof(label), "%s bleed (DAC1 held, DAC0 swung)", sname);
	ctl_bleed_describe(line, sizeof(line), label, a1_bleed, n);
	printf("%s\n", line);
	snprintf(label, sizeof(label), "%s bleed", sname);
	ctl_bleed_values(line, sizeof(line), label, a1_bleed, n);
	printf("%s\n", line);
	ctl_bleed_raw(line, sizeof(line), label, a1b_lo, a1b_hi, n);
	printf("%s\n", line);
	snprintf(label, sizeof(label), "%s control (nothing swung)", sname);
	ctl_bleed_describe(line, sizeof(line), label, a1_still, n);
	printf("%s\n", line);
	snprintf(label, sizeof(label), "%s control", sname);
	ctl_bleed_values(line, sizeof(line), label, a1_still, n);
	printf("%s\n", line);
	ctl_bleed_raw(line, sizeof(line), label, a1s_lo, a1s_hi, n);
	printf("%s\n", line);
	uart_flush();

	snprintf(label, sizeof(label),
	         "A0 bleed (DAC0 held, DAC1 swung, %s in pair)", sname);
	ctl_bleed_describe(line, sizeof(line), label, a0_bleed, n);
	printf("%s\n", line);
	ctl_bleed_values(line, sizeof(line), "A0 bleed", a0_bleed, n);
	printf("%s\n", line);
	ctl_bleed_raw(line, sizeof(line), "A0 bleed", a0b_lo, a0b_hi, n);
	printf("%s\n", line);
	ctl_bleed_describe(line, sizeof(line),
	                   "A0 control (nothing swung)", a0_still, n);
	printf("%s\n", line);
	ctl_bleed_values(line, sizeof(line), "A0 control", a0_still, n);
	printf("%s\n", line);
	ctl_bleed_raw(line, sizeof(line), "A0 control", a0s_lo, a0s_hi, n);
	printf("%s\n", line);

	/*
	 * Which bench this is, read rather than assumed. With DAC1
	 * jumpered to A1, holding DAC1 at 2048 drives A1 to about 2048;
	 * with A1 free it sits wherever the mux left it.
	 */
	dac_write(1, 2048);
	console_bleed_settle(ms);
	adc_read_pair(ADC_CH_A0, ADC_CH_A1, &a0, &a1);
	printf("# A1 reads %u with DAC1 held at 2048: %s\n", a1,
	       (a1 > 1800u && a1 < 2300u) ? "DAC1 -> A1 is fitted"
	                                  : "A1 looks undriven - see docs/noise.md");
	printf("# bleed is in ADC codes; 1 code = 0.8 mV. Full swing is 2747 codes.\n");
	printf("# taken at TRACKTIM 15, SETTLING 3 - this command's own, not"
	       " whatever ADC_MR held\n");
	printf("# pair-conv: restarts=%lu timeouts=%lu (nonzero: see #23)\n",
	       (unsigned long)adc_pair_restarts,
	       (unsigned long)adc_pair_timeouts);
	uart_flush();

	adc_measure_end();
}

/*
 * Verify that the ADC converts at the rate the timer was told to
 * produce. Everything downstream is sized against this, and the failure
 * mode is silent: an over-fast trigger is ignored with no status bit
 * set, which looks exactly like clean data at half the rate.
 */
static void cmd_rate_sweep(unsigned n_channels)
{
	static const uint32_t rates[] = {
		100000, 400000,
		466666, 471910, 477272, 482758, 488372,
		494117, 500000
	};
	/* RC 48 down to 43, to bracket the single-channel cliff. */
	static const uint32_t rates1[] = {
		200000, 780000, 795918, 812500, 829787,
		847826, 866666, 886363, 906976
	};
	const uint32_t *list = (n_channels == 1) ? rates1 : rates;
	unsigned n_list = (n_channels == 1)
	                ? sizeof(rates1) / sizeof(rates1[0])
	                : sizeof(rates) / sizeof(rates[0]);
	const uint32_t nbuf_target = 8;

	acq_init();

	printf("# TC->ADC->PDC rate sweep, %u channel%s, min RC %lu\n",
	       n_channels, n_channels == 1 ? " (A0=AD7)" : "s (A0=AD7, A1=AD6)",
	       (unsigned long)ACQ_MIN_RC_FOR(n_channels));
	printf("#   want      RC   TCexact   measured    ratio  RXBUFF GOVRE\n");
	uart_flush();

	for (unsigned i = 0; i < n_list; i++) {
		if (!acq_start(list[i], n_channels)) {
			printf("# %7lu       -         -    REFUSED (below ACQ_MIN_RC)\n",
			       (unsigned long)list[i]);
			uart_flush();
			continue;
		}

		uint32_t sync = acq_buffers_done;
		uint32_t guard = micros();
		while (acq_buffers_done == sync && (micros() - guard) < 2000000u)
			{ }

		uint32_t t0 = micros();
		uint32_t b0 = acq_buffers_done;
		while (acq_buffers_done - b0 < nbuf_target &&
		       (micros() - t0) < 2000000u)
			{ }
		uint32_t t1 = micros();
		uint32_t got = acq_buffers_done - b0;

		acq_stop();

		uint32_t rc      = acq_configured_rc();
		uint32_t tcexact = (SystemCoreClock / 2u) / rc;
		uint32_t us      = t1 - t0;
		uint64_t samples = (uint64_t)got * ACQ_BUF_SAMPLES;
		uint32_t agg     = us ? (uint32_t)((samples * 1000000ull) / us) : 0;
		uint32_t measured = agg / n_channels;
		uint32_t ratio_x1000 = tcexact ?
			(uint32_t)(((uint64_t)measured * 1000ull) / tcexact) : 0;

		printf("# %7lu %7lu %9lu %10lu   %2lu.%03lu %7lu %5lu\n",
		       (unsigned long)list[i], (unsigned long)rc,
		       (unsigned long)tcexact, (unsigned long)measured,
		       (unsigned long)(ratio_x1000 / 1000u),
		       (unsigned long)(ratio_x1000 % 1000u),
		       (unsigned long)acq_rxbuff_overruns,
		       (unsigned long)acq_govre);
		uart_flush();
	}
	printf("# rates past the measured ceiling are refused, not attempted\n");
	uart_flush();
}

/*
 * Stream over the programming-port UART. Bandwidth-limited: 115200 baud
 * carries about 11.5 kB/s, so 2 kHz of trigger (2 channels, 2 bytes)
 * at 8 kB/s fits with margin. ASCII output must stay silent while this
 * runs, since frames and logs share the one port here.
 */
static void cmd_stream_uart(uint32_t trigger_hz)
{
	if (!stream_start_uart(trigger_hz)) {
		printf("# refused\n");
		uart_flush();
		return;
	}
	printf("# uart-stream: trigger %lu Hz, %s %lu Hz - binary follows\n",
	       (unsigned long)trigger_hz, gen_shape_name(gen_shape),
	       (unsigned long)gen_hz_for(trigger_hz, gen_points, gen_sync));
	uart_flush();
}

/*
 * What the generator is doing, in the contract's words.
 *
 * The sentence itself is ctl_gen_describe() in the shared layer, so the
 * console and CTL_OP_GEN cannot describe the same state differently and
 * the two tracks cannot drift apart in how they say it. This function
 * is the part that is genuinely this track's: where the bytes go.
 */
/* console_gen_report() is shared - lib/due_shared/src/console_cmds.c */

/*
 * console_cmd_stream() is shared - lib/due_shared/src/
 * console_cmds.c. Issue #41's ordering lives there now, once.
 * This track supplies console_port_stream_start() below.
 */


/*
 * Loop diagnostic: periodic snapshots taken while both service loops run.
 *
 * One run separates four hypotheses that the aggregate counters cannot
 * tell apart: a stalled ring (prod/cons stop), a PDC reading a stale
 * address (tpr stops walking the slots), a starved service loop (svc
 * stops advancing), and a capture path serving stale data while the DAC
 * output actually moves (cdr7 is the ADC's live last A0 conversion, read
 * straight from the register and bypassing the ring, the framer and USB).
 *
 * Snapshots go to memory and print only after the last one, because a
 * printf mid-run would stall the very loops being observed. The reads
 * are registers and counters, not the sample stream; `next` peeks one
 * half-word at DACC_TPR to see what the PDC is about to fetch, which is
 * a diagnostic exception to the no-CPU-on-samples rule, not a data path.
 */
#define DIAG_N 12u
#define DIAG_INTERVAL_MS 150u

struct diag_snap {
	uint32_t ms, prod, cons, endtx, svc;
	uint32_t tpr, tcr, tnpr;
	uint16_t next, cdr7, cdr6;
	uint32_t aprod, acons;
};

static struct diag_snap diag[DIAG_N];
static unsigned diag_count;
static uint32_t diag_next_ms;
static bool     diag_run;

static void diag_start(void)
{
	diag_count = 0;
	diag_next_ms = millis();
	diag_run = true;
}

static void diag_service(void)
{
	if (!diag_run)
		return;

	if (diag_count < DIAG_N) {
		uint32_t now = millis();
		struct diag_snap *s;

		if ((int32_t)(now - diag_next_ms) < 0)
			return;

		s = &diag[diag_count++];
		s->ms    = now;
		s->prod  = play_produced;
		s->cons  = play_consumed;
		s->endtx = play_endtx_seen;
		s->svc   = play_svc_calls;
		s->tpr   = DACC->DACC_TPR;
		s->tcr   = DACC->DACC_TCR;
		s->tnpr  = DACC->DACC_TNPR;
		s->next  = *(volatile uint16_t *)s->tpr;
		s->cdr7  = (uint16_t)ADC->ADC_CDR[7];
		s->cdr6  = (uint16_t)ADC->ADC_CDR[6];
		s->aprod = acq_produced;
		s->acons = acq_consumed;
		diag_next_ms = now + DIAG_INTERVAL_MS;
		return;
	}

	diag_run = false;

	{
		uint32_t base = (uint32_t)play_ring_base();

		printf("# diag: play ring base=%08lx slot=%u B nslots=%u\n",
		       (unsigned long)base, PLAY_BUF_BYTES, PLAY_NBUF);
		printf("#    ms  prod  cons endtx    svc  tpr=slot+off  tcr"
		       "  next(tag,code)  cdr7 cdr6  aprod acons\n");
		for (unsigned i = 0; i < DIAG_N; i++) {
			struct diag_snap *s = &diag[i];
			uint32_t off = s->tpr - base;

			printf("# %5lu %5lu %5lu %5lu %6lu  %lu+%-4lu %4lu"
			       "  %04x(t%u,%4u)  %4u %4u  %5lu %5lu\n",
			       (unsigned long)(s->ms - diag[0].ms),
			       (unsigned long)s->prod, (unsigned long)s->cons,
			       (unsigned long)s->endtx, (unsigned long)s->svc,
			       (unsigned long)(off / PLAY_BUF_BYTES),
			       (unsigned long)(off % PLAY_BUF_BYTES),
			       (unsigned long)s->tcr,
			       s->next, (s->next >> 12) & 3u, s->next & 0x0fffu,
			       s->cdr7 & 0x0fffu, s->cdr6 & 0x0fffu,
			       (unsigned long)s->aprod, (unsigned long)s->acons);
		}
		uart_flush();
	}
}

/*
 * Where the main loop's time goes.
 *
 * The DMA benches re-arm at most one transfer per main-loop pass, so
 * the cost of a pass is a throughput ceiling, not a curiosity. Track A
 * carries the identical command so the two can be compared directly -
 * which is the only way to tell a real difference from a difference in
 * how the two were built.
 *
 * Results are ns per call.
 */
/*
 * Dump the playback ring's occupancy distribution.
 *
 * Printed as a bare comma-separated list rather than key=value pairs:
 * 32 buckets as `occ0=..` would be a long line for a parse that gains
 * nothing, and the index is the occupancy, so position is the key.
 */
static void cmd_occ_hist(void)
{
	printf("# play_occ min=%lu endtx=%lu runus=%lu consumed=%lu hist=",
	       (unsigned long)play_occ_min,
	       (unsigned long)play_endtx_seen,
	       (unsigned long)play_run_us,
	       (unsigned long)play_consumed);
	for (unsigned i = 0; i < PLAY_NBUF; i++)
		printf("%lu%s", (unsigned long)play_occ_hist[i],
		       i + 1u < PLAY_NBUF ? "," : "");
	printf("\n");
	uart_flush();

	printf("# play_occ_trace decim=%u n=%lu v=", PLAY_OCC_DECIM,
	       (unsigned long)play_occ_traced);
	for (unsigned i = 0; i < play_occ_traced; i++) {
		printf("%u%s", (unsigned)play_occ_trace[i],
		       i + 1u < play_occ_traced ? "," : "");
		/* 256 entries is more than one UART buffer holds. */
		if ((i & 31u) == 31u)
			uart_flush();
	}
	printf("\n");
	uart_flush();

	/*
	 * Absolute microseconds at every PLAY_RATE_DECIM-th consumed
	 * buffer. The host differences them; sending deltas here would
	 * throw away the only reading that survives a disturbed sample.
	 */
	printf("# play_rate decim=%u n=%lu us=", (unsigned)PLAY_RATE_DECIM,
	       (unsigned long)play_rate_traced);
	for (unsigned i = 0; i < play_rate_traced; i++) {
		printf("%lu%s", (unsigned long)play_rate_us[i],
		       i + 1u < play_rate_traced ? "," : "");
		if ((i & 15u) == 15u)
			uart_flush();
	}
	printf("\n");

	/*
	 * The capture side of the same question (#44). Absolute
	 * microseconds at each completed PDC buffer, and the ring
	 * occupancy at that instant - so a run that lost frames can be
	 * read for whether the converter fell behind or the transfer
	 * failed to collect. The frame header's timestamp_us cannot
	 * separate those: it is taken when the frame is queued for USB.
	 */
#if ACQ_RATE_TRACE_ENABLED
	printf("# acq_rate n=%lu us=", (unsigned long)acq_traced);
	for (unsigned i = 0; i < acq_traced; i++) {
		printf("%lu%s", (unsigned long)acq_trace_us[i],
		       i + 1u < acq_traced ? "," : "");
		if ((i & 15u) == 15u)
			uart_flush();
	}
	printf(" occ=");
	for (unsigned i = 0; i < acq_traced; i++) {
		printf("%u%s", (unsigned)acq_trace_occ[i],
		       i + 1u < acq_traced ? "," : "");
		if ((i & 31u) == 31u)
			uart_flush();
	}
	printf("\n");
#endif
	uart_flush();
}

static void cmd_profile(void)
{
	const uint32_t n = 20000;
	uint32_t t0, t1;

	printf("# main-loop profile, ns per call\n");
	uart_flush();

#define PROF(label, expr)                                            \
	do {                                                         \
		t0 = micros();                                       \
		for (uint32_t i = 0; i < n; i++) { expr; }            \
		t1 = micros();                                       \
		printf("# %-22s %6lu ns\n", label,                   \
		       (unsigned long)(((uint64_t)(t1 - t0) * 1000ull) / n)); \
		uart_flush();                                        \
	} while (0)

	PROF("empty loop", __asm__ volatile(""));
	PROF("millis()", (void)millis());
	PROF("micros()", (void)micros());
	/*
	 * load_tick() is measured by the same command that condemned
	 * micros(). It runs on every pass of this loop, so if it ever
	 * stops being negligible here it has stopped being an instrument
	 * and started being part of what it measures. The count it adds
	 * while profiling is deliberate: the profile is not a normal pass
	 * and it should be visible in the histogram as one.
	 */
	PROF("load_tick()", load_tick());
	PROF("usb_cdc_ready()", (void)usb_cdc_ready());
	PROF("usb_dma_out_busy()", (void)usb_dma_out_busy());
	PROF("usb_cdc_poll()", usb_cdc_poll());
	PROF("play_service()", play_service());
	PROF("stream_service()", stream_service());
	PROF("diag_service()", diag_service());
	PROF("ctl_service()", ctl_service());
	{
		static uint8_t scratch[64];

		/* Split out because ctl_service() measured 2141 ns while
		 * doing nothing, which is more than stream_service(). The
		 * question is whether the cost is the endpoint read or the
		 * wrapper around it, and guessing has a poor record here. */
		PROF("usb_ctl_read()", (void)usb_ctl_read(scratch,
		                                          sizeof(scratch)));
	}
#undef PROF

	printf("# note: services early-return unless started\n");
	uart_flush();
}

/*
 * Branch to an even address. Cortex-M3 requires the Thumb bit set in
 * every branch target, so this raises INVSTATE, which escalates to a
 * HardFault because UsageFault is not separately enabled.
 */
/*
 * Block the main loop for a known number of milliseconds.
 *
 * Exists to validate the load monitor, and it is the only way to do
 * that honestly: every other long pass on this board - a printf, a
 * sweep, the profile itself - has a duration nobody knows independently,
 * so agreeing with it would prove only that two unknowns match. This
 * one has a duration the *host* chose, so the monitor can be checked
 * against a number it was not told.
 *
 * Busy-waits on millis() rather than sleeping: the point is to occupy
 * the loop, which is exactly what a wedged pass does.
 *
 * Development only, like trigger_fault. It is not in the control
 * protocol's command set and must not be: a deployed instrument with a
 * remote "stop responding for a while" is a defect, not a feature.
 */
static void cmd_stall(uint32_t ms)
{
	uint32_t until;

	if (ms == 0u)
		ms = 10u;
	if (ms > 2000u)
		ms = 2000u;    /* long enough to see, short of a watchdog */

	/*
	 * Deliberately silent. A printf here lands in the very pass this
	 * command exists to measure - 36 characters at 115200 baud is
	 * 3.1 ms - and the monitor would faithfully report the stall plus
	 * the announcement of it. That was measured, not guessed: with the
	 * message in, a 5 ms stall read 7.2 ms and a 1500 ms stall read
	 * 1502.7 ms, the same 2-3 ms offset at both ends. The answer to
	 * "did it work" is the load report, not an echo.
	 */
	until = millis() + ms;
	while ((int32_t)(millis() - until) < 0)
		;
}

/* console_trigger_fault() is shared - lib/due_shared/src/console_cmds.c */

/*
 * Find the DACC's maximum update rate.
 *
 * In TAG mode one trigger produces one conversion, so the achieved rate
 * is table length times ENDTX count over elapsed time. Counting the
 * peripheral's own completions avoids needing the ADC to observe the
 * output, and gives the same kind of hard number the ADC sweep produced.
 *
 * Track A has carried this since DAC bring-up and this track had no
 * equivalent - issue #13. Independent source, same command, same
 * printed format, which is invariant 3: two programmings of one
 * converter disagreeing is the finding, and it cannot be had if only
 * one of them can be asked.
 */
static void cmd_dac_sweep(void)
{
	static const uint32_t rates[] = {
		 100000,  500000,  800000, 1000000, 1200000,
		1500000, 1750000, 2000000, 2500000, 3000000
	};

	gen_init();
	printf("# DACC update-rate sweep, TC0 ch1 (TIOA1), TAG mode\n");
	printf("#     want      RC   TCexact    measured    ratio\n");
	uart_flush();

	for (unsigned i = 0; i < sizeof(rates) / sizeof(rates[0]); i++) {
		uint32_t sync, guard, t0, t1, e0, got;
		uint32_t rc, tcexact, us, measured, ratio_x1000;
		uint64_t convs;

		if (!gen_start_independent(rates[i])) {
			printf("# %8lu       -         -    REFUSED\n",
			       (unsigned long)rates[i]);
			uart_flush();
			continue;
		}

		/* Start counting on a table boundary, so the first interval
		 * is a whole number of passes rather than whatever remained
		 * of the one in flight. */
		sync  = gen_endtx_count;
		guard = micros();
		while (gen_endtx_count == sync && (micros() - guard) < 500000u)
			;

		t0 = micros();
		e0 = gen_endtx_count;
		while (gen_endtx_count - e0 < 64u && (micros() - t0) < 1000000u)
			;
		t1 = micros();
		got = gen_endtx_count - e0;

		gen_stop();

		rc      = gen_configured_rc();
		tcexact = rc ? (SystemCoreClock / 2u) / rc : 0u;
		us      = t1 - t0;
		convs   = (uint64_t)got * GEN_TABLE_LEN;
		measured = us ? (uint32_t)((convs * 1000000ull) / us) : 0u;
		ratio_x1000 = tcexact
			? (uint32_t)(((uint64_t)measured * 1000ull) / tcexact) : 0u;

		printf("# %8lu %7lu %9lu %11lu   %2lu.%03lu\n",
		       (unsigned long)rates[i], (unsigned long)rc,
		       (unsigned long)tcexact, (unsigned long)measured,
		       (unsigned long)(ratio_x1000 / 1000u),
		       (unsigned long)(ratio_x1000 % 1000u));
		uart_flush();
	}
	printf("# ratio 1.000 means every trigger produced a DAC update\n");
	uart_flush();
}

/*
 * Cross-check the DAC ceiling against the frequency it actually emits.
 *
 * ENDTX counts PDC completions, which equal conversions only if the DACC
 * back-pressures the PDC when it cannot keep up. Driving the DAC on its
 * own timebase and capturing the result gives an independent measure: a
 * GEN_TABLE_LEN-entry table played at R conversions per second must
 * produce a tone at R/GEN_TABLE_LEN, whatever the trigger was set to.
 */
static void cmd_dac_crosscheck(uint32_t dac_hz)
{
	gen_init();
	if (!gen_start_independent(dac_hz)) {
		printf("# refused\n");
		uart_flush();
		return;
	}
	if (!stream_start_capture_only(200000, 2)) {
		gen_stop();
		printf("# capture refused\n");
		uart_flush();
		return;
	}

	/*
	 * These three lines print AFTER the capture start, which is the
	 * shape #41 was about - and they stay that way deliberately.
	 *
	 * docs/debugging.md prices this site at +4.77 ms of margin
	 * against a 20.32 ms runway, "about one added banner line from
	 * biting". It survives only because the capture here is fixed at
	 * 200,000 Hz, where the ring holds longest. Add a fourth line and
	 * it becomes cmd_stream: frames lost before the host sees any.
	 *
	 * Moving them above stream_start_capture_only() - which is what
	 * cmd_stream and h_loop did - would fix the margin and break the
	 * measurement. The interval between gen_start_independent() and
	 * the capture start sets the sampling phase against the DAC's
	 * table wrap, and h_mimic's comment records that as a free
	 * variable fixed for a run by the instruction timing between the
	 * two starts. Putting ~110 characters of UART in there would move
	 * it by milliseconds, and this command is an instrument for issue
	 * #5, which is about one sample per table wrap.
	 *
	 * So: not an oversight, and not safe to "fix" the way the others
	 * were. If a print is ever needed here, put it above
	 * gen_start_independent() where it costs nothing.
	 */
	printf("# DAC indep %lu Hz (RC %lu), capture 200000 Hz\n",
	       (unsigned long)dac_hz, (unsigned long)gen_configured_rc());
	printf("# if the DAC truly runs at the trigger, tone = %lu Hz\n",
	       (unsigned long)(dac_hz / GEN_TABLE_LEN));
	printf("# if it saturates near 1539700, tone = 3007 Hz instead\n");
	uart_flush();
}

/*
 * Endpoint state, readable while a stream is running.
 *
 * The banner reports CFGOK once, at boot, which is exactly when nothing
 * is wrong yet. The question this exists for is whether the sample
 * endpoints are still configured *during* a capture, after the AUTOSW
 * writes and the control-endpoint re-allocations have been running
 * against each other for a few thousand passes.
 *
 * It matters more here than it did on the track it came from. Any write
 * to UOTGHS_DEVEPTCFG re-allocates that endpoint's DPRAM - the ALLOC bit
 * is in the same register - and datasheet 40.5.1.6 says the x+1 window
 * then slides up and loses its data. That was inert while EP3 was the
 * last endpoint and became a wedge the day EP4-EP6 appeared, which is
 * this track. CFGOK is the controller's own answer to "did the
 * allocation take", and guessing at DPRAM arithmetic is how an endpoint
 * that never configured gets blamed on software.
 *
 * EPEN and CFGOK are different questions and both are printed: CFGOK
 * describes a configuration, DEVEPT says which endpoints are actually
 * enabled, and an endpoint can read configured while disabled.
 */
static void cmd_endpoint_state(void)
{
	char ok[8];

	for (unsigned e = 0; e < 7; e++)
		ok[e] = (UOTGHS->UOTGHS_DEVEPTISR[e]
		         & UOTGHS_DEVEPTISR_CFGOK) ? '1' : '0';
	ok[7] = 0;

	printf("# ep cfgok[0..6]=%s devept=%08lx devctrl=%08lx\n",
	       ok, (unsigned long)UOTGHS->UOTGHS_DEVEPT,
	       (unsigned long)UOTGHS->UOTGHS_DEVCTRL);
	printf("# epcfg: ");
	for (unsigned e = 0; e < 7; e++)
		printf("%08lx%s", (unsigned long)UOTGHS->UOTGHS_DEVEPTCFG[e],
		       e == 6 ? "\n" : " ");
	uart_flush();
}

/* ------------------------------------------------------------------ */
/* The command layer                                                   */
/*                                                                     */
/* The *surface* - which letters are commands, what arguments they     */
/* take, what `h` prints and what happens to a letter this track has   */
/* not got - is lib/due_shared/src/console.c, compiled by both tracks. */
/* Everything below is this track's handlers, which is where the       */
/* registers are. See console.h for why the line falls there.          */
/*                                                                     */
/* Parsing and execution stay separated for the reason they always     */
/* were: the native port carries a binary framed protocol              */
/* (docs/control-protocol.md) with a different parser, and both reach  */
/* the same handlers. Two implementations of "start playback" would    */
/* drift, and the refusal wording is part of what the host is told,    */
/* not decoration.                                                     */
/* ------------------------------------------------------------------ */

static void h_help(const uint32_t *a)  { (void)a; cmd_help(); }
static void h_ident(const uint32_t *a) { (void)a; identity_line(); }
static void h_printf(const uint32_t *a){ (void)a; measure_printf(); }
static void h_gpio(const uint32_t *a)  { (void)a; measure_gpio(); }
static void h_fault(const uint32_t *a) { (void)a; console_trigger_fault(); }
static void h_read(const uint32_t *a)  { (void)a; cmd_read(); }
static void h_sweep(const uint32_t *a) { (void)a; cmd_sweep(); }
static void h_xtalk(const uint32_t *a)
{
	crosstalk_repeats = a[0];
	crosstalk_settle_ms = a[1];
	cmd_crosstalk();
}
static void h_ratesweep(const uint32_t *a) { cmd_rate_sweep(a[2] ? a[2] : 2u); }
static void h_dac_sweep(const uint32_t *a) { (void)a; cmd_dac_sweep(); }
static void h_dac_15m(const uint32_t *a)   { (void)a; cmd_dac_crosscheck(1500000); }
static void h_dac_30m(const uint32_t *a)   { (void)a; cmd_dac_crosscheck(3000000); }
static void h_epstate(const uint32_t *a)   { (void)a; cmd_endpoint_state(); }

static void h_s50(const uint32_t *a)  { (void)a; console_cmd_stream(50000); }
static void h_s100(const uint32_t *a) { (void)a; console_cmd_stream(100000); }
static void h_s200(const uint32_t *a) { (void)a; console_cmd_stream(200000); }
static void h_s400(const uint32_t *a) { (void)a; console_cmd_stream(400000); }
/*
 * The top preset is derived, not written down: the highest rate the
 * ADC sustains follows from the measured cliff at RC 86, and that
 * compare value holds across master clock settings because the timer
 * and the ADC clock scale together. A literal 500000 here was from the
 * MCK=84 MHz era and was silently refused by the ACQ_MIN_RC guard at
 * 78 MHz - the guard doing its job on a stale preset.
 */
static void h_smax(const uint32_t *a)
{
	(void)a;
	console_cmd_stream((SystemCoreClock / 2u) / ACQ_MIN_RC);
}

static void h_stop(const uint32_t *a)
{
	(void)a;
	stream_stop();
	play_stop();
	printf("# stream stopped\n");
	uart_flush();
}

static void h_stats(const uint32_t *a) { (void)a; stream_report(); }
static void h_usb(const uint32_t *a)   { (void)a; usb_cdc_dump(); ctl_dump(); }
static void h_uart_stream(const uint32_t *a) { (void)a; cmd_stream_uart(2000); }

static void h_flood(const uint32_t *a)
{
	(void)a;
	stream_flood_start();
	printf("# flood: IN only\n");
	uart_flush();
}

static void h_sink(const uint32_t *a)
{
	(void)a;
	stream_sink_start();
	printf("# sink: OUT only\n");
	uart_flush();
}

static void h_duplex(const uint32_t *a)
{
	(void)a;
	stream_duplex_start();
	printf("# duplex: IN and OUT together\n");
	uart_flush();
}

static void h_flood_dma(const uint32_t *a)
{
	(void)a;
	stream_flood_dma_start();
	printf("# flood: IN via DMA\n");
	uart_flush();
}

static void h_sink_dma(const uint32_t *a)
{
	(void)a;
	stream_sink_dma_start();
	printf("# sink: OUT via DMA\n");
	uart_flush();
}

static void h_duplex_dma(const uint32_t *a)
{
	(void)a;
	stream_duplex_dma_start();
	printf("# duplex: IN+OUT via DMA\n");
	uart_flush();
}

/*
 * The complete loop: the host supplies the waveform, the DAC emits it,
 * the jumper carries it to the ADC, and the capture comes back over the
 * same USB pipe. Both directions run at once, which is the target
 * configuration.
 */
static void h_loop(const uint32_t *a)
{
	/* "=<dac>[,<adc>]L"; one number sets both, none = 200k. */
	uint32_t dac_hz = a[0] ? a[0] : 200000u;
	uint32_t adc_hz = a[1] ? a[1] : dac_hz;
	unsigned nch    = a[2] ? a[2] : 2u;

	if (!play_start(dac_hz)) {
		printf("# loop: DAC %lu sps refused (max %lu)\n",
		       (unsigned long)dac_hz, (unsigned long)((SystemCoreClock / 2u) / PLAY_MIN_RC));
		uart_flush();
		return;
	}
	/*
	 * Banner before the CAPTURE start, for issue #41's reason - and
	 * this site is the one 67d3990 did not fix. docs/debugging.md's
	 * class audit priced it at the time: ~102 characters of banner
	 * against 8.96 ms of ring, margin **-5.89 ms**, and it was left
	 * because only cmd_stream had been measured.
	 *
	 * Measured here before the change, four runs at each of two
	 * rates: `first_overrun` was 2 at 453,488 Hz and 1 at 402,061 in
	 * every single run - frames lost before the first frame ships,
	 * which is #41's signature exactly and close to what the margin
	 * predicts (2.6 and 1.8 frames).
	 *
	 * The play_start above stays where it is. Playback is
	 * host-driven and nothing flows until the host feeds, which is
	 * why h_play is explicitly NOT a hazard in that audit; capture
	 * is device-driven and fills the moment the timer runs. Only the
	 * capture start needs the banner ahead of it.
	 */
	printf("# loop: DAC %lu sps from USB, ADC %lu Hz/ch x%u ch\n",
	       (unsigned long)dac_hz, (unsigned long)adc_hz, nch);
	printf("# DAC0 carries the waveform, DAC1 holds mid scale\n");
	uart_flush();
	if (!stream_start_capture_only(adc_hz, nch)) {
		play_stop();
		printf("# loop: ADC %lu Hz x%u ch refused (max %lu)\n",
		       (unsigned long)adc_hz, nch,
		       (unsigned long)((SystemCoreClock / 2u)
		                       / ACQ_MIN_RC_FOR(nch)));
		uart_flush();
		return;
	}
}

/* Playback with NO capture stream, to separate a fault in the DAC path
 * from an interaction between the two service loops. */
static void h_play(const uint32_t *a)
{
	uint32_t dac_hz = a[0] ? a[0] : 200000u;

	if (play_start(dac_hz))
		printf("# play only: DAC %lu sps from USB, no capture\n",
		       (unsigned long)dac_hz);
	else
		printf("# play only: %lu sps refused (max %lu)\n",
		       (unsigned long)dac_hz, (unsigned long)((SystemCoreClock / 2u) / PLAY_MIN_RC));
	uart_flush();
}

static void h_profile(const uint32_t *a) { (void)a; cmd_profile(); }

/*
 * `l` reports; `=1l` reports and then clears. The counters are
 * cumulative so two readings give a rate over any interval the host
 * chooses - but max_cycles is a maximum, not a counter, and
 * differencing a maximum is meaningless. Clearing has to be explicit
 * rather than a side effect of reading, or two consumers of this
 * channel would silently steal each other's worst case.
 */
static void h_load(const uint32_t *a)
{
	load_dump();
	if (a[0])
		load_clear();
}

static void h_stall(const uint32_t *a) { cmd_stall(a[0]); }

/*
 * Software reset. The test suite holds the control port open for a
 * whole session, because opening it asserts NRSTB and costs a reset
 * plus a native-port re-glob every time; this is how it recovers a
 * wedged device without giving that up.
 */
/*
 * A software unplug of the native port. `z` is a processor reset only -
 * RSTC_CR_PROCRST leaves the UOTGHS running and its pull-up attached,
 * so the host never sees a disconnect and a wedged close() is not
 * released by it. This is the one that detaches.
 */
static void h_detach(const uint32_t *a)
{
	printf("# detaching the native port for %lu ms\n",
	       (unsigned long)(a[0] ? a[0] : 250u));
	uart_flush();
	usb_cdc_detach_cycle(a[0]);
}

static void h_reset(const uint32_t *a)
{
	(void)a;
	printf("# software reset now\n");
	uart_flush();
	RSTC->RSTC_CR = RSTC_CR_KEY(0xA5u) | RSTC_CR_PROCRST;
}

static void h_ring(const uint32_t *a) { (void)a; play_dump(); }
static void h_diag(const uint32_t *a) { (void)a; diag_start(); }

/*
 * "=<us>K". The gap between the ADC start and the DAC start, in
 * microseconds, held across runs and applied by the M preset.
 *
 * The two states this issue draws are selected by the binary and not by
 * anything the host does - three states on one image and one on the
 * next, with the changed code never executed. The M preset's comment
 * below names the only free variable that layout could plausibly move:
 * gen sits on TIOA1 while the ADC sits on TIOA0, so the sampling phase
 * relative to the DAC table wrap is fixed for a run by the instruction
 * timing between the two starts, and a different layout is a different
 * number of instructions.
 *
 * This makes that variable settable, so the hypothesis can be tested
 * inside one image instead of by flashing two. Debug-only, on a preset
 * that is already debug-only, and it busy-waits.
 */
static void h_mimic_gap(const uint32_t *a)
{
	mimic_start_delay_us = a[0];
	printf("# mimic start delay: %lu us (next M)\n",
	       (unsigned long)mimic_start_delay_us);
	uart_flush();
}

/*
 * The loop's timing skeleton with no USB in it: gen's flash sine
 * through play's exact DACC + TIOA1 configuration, capture running,
 * ordering matched to what L does once the ring primes. Observe with D:
 * if cdr7 swings, the fault needs USB to appear; if it freezes, the
 * trigger/DACC/ADC interaction is the fault.
 */
static void h_mimic(const uint32_t *a)
{
	/*
	 * "=<dac>[,<adc>]M", defaulting to 200000 for both, which is
	 * what this preset always did.
	 *
	 * Settable because this is the only path in the firmware where
	 * the DAC update clock and the ADC trigger are two independent
	 * timers - gen_prepare_tioa1() selects TIOA1 where every other
	 * path leaves the DACC on the ADC's TIOA0. That makes the
	 * sampling phase relative to the DAC's table wrap a free
	 * variable, fixed for a run by the instruction timing between the
	 * two starts, and it is the one structural difference between
	 * this preset and the ordinary capture path that issue #5 does
	 * not appear on.
	 *
	 * Giving the two clocks slightly different rates walks that phase
	 * through a full period within one capture, so one run samples
	 * the whole phase space instead of whichever point a run happened
	 * to start at. A defect that is bimodal per run and constant
	 * within it is what a fixed free variable looks like; this is how
	 * to test that without needing a board that is currently
	 * reproducing.
	 */
	uint32_t dac_hz = a[0] ? a[0] : 200000u;
	uint32_t adc_hz = a[1] ? a[1] : dac_hz;
	/*
	 * "=<dac>,<adc>,<nch>M". Three channels puts the issue #5
	 * impedance arm on A2 into the same capture as A1 and the sine on
	 * A0, so the arms are matched inside one run instead of compared
	 * across runs that draw different states.
	 */
	unsigned nch    = a[2] ? a[2] : 2u;

	/*
	 * Everything the console has to say is said before the converters
	 * start. These two lines used to run after gen_go_tioa1(), which
	 * is ~7 ms of blocked main loop laid over the first samples of
	 * every capture this preset takes - invariant 8, on the path the
	 * suite calls its continuity control. Measured not to change what
	 * that path reports, on one image with the two orders alternated;
	 * moved anyway, because it had no business being there.
	 */
	/*
	 * The shape as it is, not as this line used to assume. It said
	 * "sine" whatever `W` had put in the table, so a square capture
	 * came with a banner claiming a sine over it - issue #9 flagged it
	 * twice, and it is the kind of stale claim that gets read as data
	 * later. gen_shape_name() is the shared spelling, so the two
	 * tracks cannot drift on the word either.
	 */
	printf("# mimic loop: gen %s on TIOA1 at %lu sps, capture %lu Hz\n",
	       gen_shape_name(gen_shape),
	       (unsigned long)dac_hz, (unsigned long)adc_hz);
	printf("# press D and read cdr7: swing = USB at fault, frozen = trigger path\n");
	uart_flush();
	play_stop();
	gen_init();
	gen_prepare_tioa1(dac_hz);
	/*
	 * Checked, unlike every earlier version of this line. A refusal is
	 * silent otherwise: gen still runs, the banner above has already
	 * claimed a capture, and the host reads an empty stream from a
	 * device that reported success. This is the preset the splice
	 * census measures, so a refusal that says nothing would be scored
	 * as a clean run.
	 */
	if (!stream_start_capture_only(adc_hz, nch)) {
		printf("# mimic loop: refused, the ADC would not start\n");
		uart_flush();
		return;
	}
	if (mimic_start_delay_us) {
		uint32_t t0 = micros();
		while (micros() - t0 < mimic_start_delay_us)
			;
	}
	gen_go_tioa1();
}

/*
 * "=<n>C": which channel pairs with A0 in a two-channel capture, 1 for
 * A1 and 2 for A2. It is how source impedance is told apart from
 * conversion slot - see acq_set_pair().
 */
static void h_pair(const uint32_t *a)
{
	acq_set_pair(a[0]);
	printf("# capture pair: A0 + A%u (next 2ch stream)\n",
	       acq_pair_second == ADC_CH_A2 ? 2u : 1u);
	uart_flush();
}

/*
 * "=<n>N": generator layout, 0 normal, 1 swapped, 2 two-cycle, 3
 * all-DC. Rebuilt now and again by gen_init(), which M calls. See gen.h
 * for what each arm is for.
 */
static void h_layout(const uint32_t *a)
{
	static const char *const names[] = {
		"normal: sine DAC0, DC DAC1",
		"swapped: DC DAC0, sine DAC1",
		"two-cycle: two sine periods per wrap",
		"all-DC: no sine on either",
	};

	gen_set_layout(a[0]);
	printf("# gen layout %u = %s\n", (unsigned)gen_layout, names[gen_layout]);
	uart_flush();
}

/*
 * "=<shape>,<points>W": the internal generator's waveform.
 *
 * shape 0 sine, 1 square, 2 ramp, 3 triangle, 4 DC. points is the
 * resolution - how many table points one cycle spends - and rounds down
 * to a power of two in 2..256, because those are the only counts that
 * divide the table without leaving a partial cycle at the PDC wrap.
 * Omitting it keeps the current value.
 *
 * Resolution is a frequency knob and the report says so: the update
 * rate is the trigger's, so halving the points halves the time a cycle
 * takes and doubles the output frequency, at the cost of a coarser
 * staircase. That trade is the whole reason it is exposed - see gen.h.
 *
 * Rebuilt now and again by gen_init(), which M calls.
 */
static void h_wave(const uint32_t *a)
{
	gen_set_shape(a[0]);
	if (a[1])
		gen_set_points(a[1]);
	/* "=<shape>,<pts>,<amp>W". amp in 1/256ths of full scale, about
	 * mid, so a small waveform still moves the converter every update
	 * without spanning its range - which is what lets a scope come up
	 * ten times in the vertical. Omitting it keeps the current
	 * amplitude. */
	if (a[2])
		gen_set_amp(a[2]);
	console_gen_report();
}

/*
 * "=<n>J": the sync output, 0 off, 1 per cycle, 2 per table wrap.
 *
 * A trigger for the bench, on whichever DAC pin is not carrying the
 * waveform. Triggering a scope on the signal itself divides the pin's
 * ~20 mV of noise by the waveform's slew rate at the trigger level,
 * which is why a ramp shakes 27 us and a square does not shake at all -
 * docs/awg.md. A full-scale sync edge makes that term vanish, and it
 * cannot drift against the waveform because one PDC stream and one
 * trigger feed both.
 *
 * The scope's EXT input tops out at 1.2 V here and the DAC sits at
 * 0.52-2.82 V, so AC-couple the trigger or it will never fire.
 */
static void h_sync(const uint32_t *a)
{
	gen_set_sync(a[0]);
	/* "=<mode>,<amp>J". The sync's own swing, in 256ths, so a
	 * full-scale square on the pin next to the signal can be shrunk
	 * and the disturbance it may be causing tested rather than argued
	 * about. */
	if (a[1])
		gen_set_sync_amp(a[1]);
	console_gen_report();
}

/*
 * "=<ch>,<core>I": DACC_ACR's IBCTLCHx and IBCTLDACCORE, applied at the
 * next DACC init. "=2,1I" is the Arduino core's value and the
 * datasheet's characterisation condition; 0,0 is reset, which is what
 * this project has always run. See gen.c.
 */
static void h_ibctl(const uint32_t *a)
{
	gen_set_ibctl(a[0], a[1]);
	printf("# dacc ibctl: ch=%u core=%u (next DACC init)\n",
	       (unsigned)gen_ibctl_ch, (unsigned)gen_ibctl_core);
	uart_flush();
}

/*
 * "=<tracktim>,<settling>A". Applied at the next acq_init(), so set it
 * before starting a stream. One image sweeps the whole range, which is
 * the only way to compare the constant rather than comparing two
 * binaries - see acq.c.
 */
static void h_adc_timing(const uint32_t *a)
{
	acq_set_timing(a[0], a[1]);
	printf("# adc timing: tracktim=%u settling=%u (next stream)\n",
	       (unsigned)acq_tracktim, (unsigned)acq_settling);
	uart_flush();
}

/*
 * "=<n>e": the on-die temperature sensor, n conversions averaged.
 *
 * On the console as well as the control channel because a bench reading
 * wants no host, and because the two paths going through one
 * implementation is what makes them comparable. ctl_temp_t carries what
 * this may and may not be used to claim - it is an upper bound on
 * ADVREF noise, not a value, and not a temperature in degrees. Issue
 * #11.
 */
static void h_temp(const uint32_t *a)
{
	ctl_temp_t t;

	if (adc_read_temp(&t, (uint16_t)a[0]) != CTL_TEMP_OK) {
		printf("# temp: refused - a capture is armed, or no sensor here\n");
		uart_flush();
		return;
	}
	printf("# temp: code %lu.%02lu (min %u max %u, n=%u) adcmr=%08lx adcacr=%08lx\n",
	       (unsigned long)(t.code_x16 / 16u),
	       (unsigned long)((t.code_x16 % 16u) * 100u / 16u),
	       (unsigned)t.code_min, (unsigned)t.code_max, (unsigned)t.samples,
	       (unsigned long)t.adc_mr, (unsigned long)t.adc_acr);
	uart_flush();
}

static void h_bench(const uint32_t *a)
{
	(void)a;
	stream_bench_report();
	{
		char line[192];
		play_report_t r = {
			.bytes_in   = play_bytes_in,
			.produced   = play_produced,
			.consumed   = play_consumed,
			.underruns  = play_underruns,
			.isr_calls  = play_isr_calls,
			.endtx_seen = play_endtx_seen,
			.svc_calls  = play_svc_calls,
			.spans      = play_spans,
			.partial    = play_partial,
			.occ_min    = play_occ_min,
		};
		play_report_format(line, sizeof line, &r);
		printf("%s\n", line);
	}
	uart_flush();
}

/*
 * The occupancy histogram, off the `B` path deliberately. `B` is polled
 * mid-stream by the daemon and must stay one short line; this is 32
 * buckets and belongs where `V` already lives, which is between runs.
 */
static void h_occ(const uint32_t *a) { (void)a; cmd_occ_hist(); }

/*
 * What this track implements, in the shared surface's terms.
 *
 * Order is this file's convenience - console.c scans by key and the
 * help's order comes from its own table - so these are grouped the way
 * the handlers above are written.
 *
 * A letter absent from here is answered "not implemented on this
 * track", which is the console's CTL_ERR_OPCODE. Four are absent today
 * and every one of them is Track A's: `d`, `j` and `k` are the DAC
 * bring-up sweeps and `E` reads endpoint state during a stream, which
 * this track has no equivalent of. Issue #13 has the list; `console_missing()`
 * prints it from this table rather than from anyone's memory.
 */
const console_binding_t console_bindings[] = {
	{ 'h', h_help },        { 'v', h_ident },       { 'p', h_printf },
	{ 'g', h_gpio },        { 'f', h_fault },

	{ 'r', h_read },        { 's', h_sweep },       { 'x', h_xtalk },
	{ 't', h_ratesweep },   { 'd', h_dac_sweep },   { 'j', h_dac_15m },
	{ 'k', h_dac_30m },

	{ '1', h_s50 },         { '2', h_s100 },        { '3', h_s200 },
	{ '4', h_s400 },        { '5', h_smax },        { '0', h_stop },
	{ '?', h_stats },       { 'u', h_usb },         { 'w', h_uart_stream },
	{ 'E', h_epstate },

	{ 'F', h_flood },       { 'R', h_sink },        { 'X', h_duplex },
	{ 'G', h_flood_dma },   { 'T', h_sink_dma },    { 'Y', h_duplex_dma },
	{ 'B', h_bench },

	{ 'L', h_loop },        { 'P', h_play },        { 'M', h_mimic },
	{ 'V', h_ring },        { 'D', h_diag },        { 'O', h_occ },

	{ 'W', h_wave },        { 'J', h_sync },        { 'N', h_layout },
	{ 'I', h_ibctl },

	{ 'C', h_pair },        { 'A', h_adc_timing },  { 'e', h_temp },

	{ 'Q', h_profile },     { 'l', h_load },        { 'S', h_stall },
	{ 'K', h_mimic_gap },   { 'Z', h_detach },      { 'z', h_reset },

	{ 0, 0 },
};


int main(void)
{
	uint32_t heartbeat_at;
	int led_state = 0;
	uint32_t led_usb_at = 0;
	uint32_t led_in_last = 0, led_out_last = 0;

	/* WDT is enabled out of reset on this part and will reset the board
	 * roughly every 15 s if not serviced. Nothing here services it. */
	WDT->WDT_MR = WDT_MR_WDDIS;

	/* Before anything derives a rate from it. */
	clock_set_mck(MCK_MULA_DEFAULT);

	led_init();
	led_aux_init();
	uart_init(115200);
	systick_init();
	load_init();
	dac_init();
	adc_init();
	usb_cdc_init();

	/* Unbuffered, so output appears as it is produced rather than at
	 * flush points that would distort the printf measurement. */
	setvbuf(stdout, NULL, _IONBF, 0);

	banner();
	heartbeat_at = millis();

	uint32_t ctl_ms = 0;
	uint32_t usb_ms = 0;

	for (;;) {
		uint32_t now;

		/*
		 * First thing in the pass, so the interval measured is the
		 * whole pass rather than the part after the timebase read.
		 */
		load_tick();

		now = millis();
		stream_loop_passes++;

		if (now - heartbeat_at >= (led_state ? 100u : 900u)) {
			led_state = !led_state;
			if (led_state)
				led_on();
			else
				led_off();
			heartbeat_at = now;
		}

		/*
		 * USB activity on the two spare LEDs: TXL lights while the IN
		 * direction moves data, RXL while OUT does. Driven from byte
		 * and DMA-start counters the driver already bumps, sampled at
		 * 50 ms so even a slow trickle reads as a visible flicker.
		 */
		if (now - led_usb_at >= 50u) {
			led_tx(usb_in_activity != led_in_last);
			led_rx(usb_out_activity != led_out_last);
			led_in_last = usb_in_activity;
			led_out_last = usb_out_activity;
			led_usb_at = now;
		}

		/*
		 * Control transfers, at most once a millisecond.
		 *
		 * Same argument as the control channel below, and the same
		 * measurement behind it: this reads UOTGHS_DEVISR every pass
		 * and costs about 1.2 us of a 7.8 us one. The expense is not
		 * the instruction, it is the peripheral bus and its
		 * clock-domain crossing - the CPU stalls, and nothing in the
		 * pipeline can hide that.
		 *
		 * It is asking about an event that happens a few dozen times
		 * at enumeration and essentially never afterwards, so at one
		 * pass in a hundred thousand it was oversampled by about that
		 * factor. USB allows 500 ms for most control requests and
		 * 50 ms for the SET_ADDRESS status stage; a millisecond of
		 * added latency is invisible against either, and costs about
		 * twenty milliseconds spread across a whole enumeration.
		 *
		 * The real fix is UOTGHS_IRQn, which is written
		 * (UOTGHS_Handler) and has never been enabled. This is the
		 * one-line version of it.
		 */
		if (now != usb_ms) {
			usb_ms = now;
			usb_cdc_poll();
		}
		play_service();
		stream_service();
		diag_service();

		/*
		 * Keep bulk OUT drained when nothing is consuming it. A CDC
		 * device that lets the pipe NAK indefinitely wedges the host:
		 * macOS's close() waits for in-flight write URBs to complete,
		 * and tcflush cannot recall a URB already at the controller,
		 * so the host process hangs in close() holding the port.
		 */
		/*
		 * Every pass, and it was tried the other way.
		 *
		 * Gating this to 1 kHz like the two polls above buys 1.68 us
		 * of a 6.77 us pass - and the suite went from 233 passed to
		 * 223 passed and a wedge. Four banks per millisecond is about
		 * 2 MB/s of drain capacity against a host that writes at
		 * ~1.8 MB/s during playback, so the margin was gone. This is
		 * not a poll that finds nothing; it is the guarantee that the
		 * pipe never NAKs indefinitely, and its *throughput* is the
		 * guarantee, not just its existence.
		 */
		if (!play_active() && !stream_out_in_use()) {
			static uint8_t scrap[512];

			/* Counted so that "the device stopped draining" is a
			 * reading and not a theory. It is the one thing every
			 * 0c diagnosis has had to assume. */
			usb_out_drain_polls++;
			for (int b = 0; b < 4; b++)
				if (usb_cdc_read(scrap, sizeof(scrap)) == 0)
					break;
		}

		/*
		 * The control channel, at most once a millisecond.
		 *
		 * Servicing it every pass cost 2141 ns of a 9700 ns pass -
		 * more than stream_service() - to poll an endpoint that
		 * receives a command ten times a second. The cost is a UOTGHS
		 * register read, which is far dearer than an SRAM one:
		 * usb_ctl_read() alone measures 1205 ns doing nothing. `Q`
		 * reports both, which is how this was found rather than
		 * argued.
		 *
		 * A millisecond is still 100x faster than any host can
		 * notice on a status poll, and it leaves the drain with
		 * 2 KB/ms of capacity against command traffic measured in
		 * bytes. It is gated here rather than inside ctl_service
		 * because `now` is already in a register, so the check is
		 * free where a second millis() would not be.
		 *
		 * The drain still has to happen: an allocated OUT endpoint
		 * that nobody reads NAKs forever and hangs the host in
		 * close(). Once a millisecond is draining; never is not.
		 */
		if (now != ctl_ms) {
			ctl_ms = now;
			ctl_service();
		}

		/*
		 * Playback status on bulk IN, so the host can close a rate
		 * loop on what the converter actually consumed. Only in
		 * play-only: in loop mode IN carries frames and is on DMA,
		 * and the FIFO path must not touch an endpoint DMA owns.
		 *
		 * usb_cdc_write never spins - it gives up when no bank is
		 * free - so a host that stops reading costs a dropped record
		 * and not a stalled main loop. The host tolerates gaps: it
		 * differences whichever records arrive.
		 */
		if (play_active() && !stream_in_in_use()) {
			static uint32_t last_stat_ms;
			uint32_t now_ms = millis();

			if ((uint32_t)(now_ms - last_stat_ms) >= PLAYSTAT_MS) {
				playstat_t st;

				last_stat_ms = now_ms;
				st.magic[0] = PLAYSTAT_MAGIC0;
				st.magic[1] = PLAYSTAT_MAGIC1;
				st.magic[2] = PLAYSTAT_MAGIC2;
				st.magic[3] = PLAYSTAT_MAGIC3;
				st.version   = PLAYSTAT_VERSION;
				st.pad[0] = st.pad[1] = st.pad[2] = 0;
				/*
				 * Each field is a 32-bit aligned volatile read
				 * and so atomic on this core, but the set is
				 * not sampled as one. A one-buffer skew against
				 * a window the host averages over hundreds of
				 * milliseconds is below the noise it is
				 * measuring.
				 */
				st.consumed  = play_consumed;
				st.underruns = play_underruns;
				st.bytes_in  = play_bytes_in;
				st.dev_us    = micros();
				st.crc32     = frame_crc32((const uint8_t *)&st,
				                           sizeof(st)
				                           - sizeof(st.crc32));
				usb_cdc_write((const uint8_t *)&st, sizeof(st));
			}
		}

		console_feed(uart_getc());
	}
}
