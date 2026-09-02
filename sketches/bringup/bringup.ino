/*
 * Track A bring-up oracle: UART printf and HardFault reporting.
 *
 * Verifies on real hardware the two diagnostic mechanisms that Track B
 * must reimplement bare metal, and measures the two timing claims the
 * documentation rests on:
 *
 *   - printf over the programming port costs milliseconds
 *   - a direct PIO register write costs nanoseconds
 *
 * That ratio is the reason acquisition instrumentation uses GPIO toggles
 * and never printf. See docs/debugging.md.
 *
 * Commands over the programming port at 115200:
 *   h  help
 *   p  measure printf cost
 *   g  measure GPIO toggle cost
 *   f  trigger a deliberate hard fault
 *   r  read A0/A1 once
 *   s  DAC sweep, both channels
 *   x  crosstalk probe
 *   t  TC/ADC/PDC trigger-rate sweep
 *   1-5 start streaming at a preset trigger rate
 *   0  stop everything
 *   ?  streaming statistics
 *   =<dac>[,<adc>] rate arguments for the next L or P
 *   L  full loop HOST -> DAC0 -> A0 -> HOST
 *   P  playback only
 *   V  playback ring and DACC register dump
 *   D  loop diagnostic: 12 snapshots at 150 ms, printed afterwards
 *   M  mimic loop without USB: gen sine on TIOA1 + capture
 *   F/R/X  transport benchmarks: flood IN, sink OUT, duplex
 *   u  USB register dump
 *
 * Loopback wiring: DAC0 -> A0, DAC1 -> A1.
 */

#include "play_report.h"
#include "console_out.h"          /* the shared debug emitters */
#include "console_port.h"         /* console_write / console_flush */
#include "clock.h"
#include "bootlog.h"
#include "acq.h"
#include "gen.h"
#include "stream.h"
#include "play.h"
#include "playstat.h"
#include "ctlusb.h"
#include "ctl.h"                    /* the shared parser */
#include "console.h"                /* the shared command surface */
#include "load.h"                   /* the shared main-loop monitor */
#include "ctl_port.h"               /* ctl_port_gen_get: the console reads
                                     * the generator through the same hook
                                     * the control channel does, so the two
                                     * cannot disagree */
#include "usbdma.h"
#include "frame.h"
#include "track_id.h"
#include "fw_version.h"

#define LED_MASK (1u << 27)   /* pin 13 = PB27 */

/*
 * The Due's two other SAM3X-driven LEDs: TXL on PA21 (pin 73) and RXL on
 * PC30 (pin 72), both active low. Repurposed as USB activity indicators
 * exactly as Track B does - TXL for the IN direction, RXL for OUT -
 * since nothing here drives the UART lines they were named after. The
 * Arduino variant only declares these pins; it never drives them.
 *
 * Direct PIO writes rather than digitalWrite: ~69 ns against ~2164 ns,
 * and the same rule that governs ISR instrumentation applies to
 * anything called from the service loop.
 */
#define TXL_MASK (1u << 21)   /* PA21 */
#define RXL_MASK (1u << 30)   /* PC30 */

static uint32_t heartbeat_at;
static bool led_on;

static void led_aux_init(void)
{
	PMC->PMC_PCER0 = (1u << ID_PIOA) | (1u << ID_PIOC);
	PIOA->PIO_PER  = TXL_MASK;
	PIOA->PIO_OER  = TXL_MASK;
	PIOA->PIO_SODR = TXL_MASK;   /* active low: start off */
	PIOC->PIO_PER  = RXL_MASK;
	PIOC->PIO_OER  = RXL_MASK;
	PIOC->PIO_SODR = RXL_MASK;
}

static void led_tx(int on)
{
	if (on)
		PIOA->PIO_CODR = TXL_MASK;
	else
		PIOA->PIO_SODR = TXL_MASK;
}

static void led_rx(int on)
{
	if (on)
		PIOC->PIO_CODR = RXL_MASK;
	else
		PIOC->PIO_SODR = RXL_MASK;
}

/*
 * One line saying which firmware this is. Same format on both tracks -
 * see version.h - so a host reads one regular expression rather than
 * matching the banner's prose, and so a board can be identified without
 * paying for the banner (89 ms of blocked main loop, invariant 8). `v`
 * prints exactly this and nothing else.
 */
/*
 * The line itself is console_identity() in lib/due_shared - see the
 * note beside its declaration. This track supplies FW_TRACK and the
 * clock and nothing else.
 */
static void identity_line(void)
{
	console_identity(FW_TRACK, (unsigned long)SystemCoreClock);
}

/*
 * This track's own facts, then the shared command list.
 *
 * console_help() prints one shared table, so a command that exists on
 * one track and not the other says so on both, rather than the two
 * per-track command sets silently drifting apart.
 *
 * The numbers stay here, where they can be computed. A shared help
 * line carrying "453488" would be a figure written down a second
 * time.
 */
static void banner(void)
{
	Serial.println("#");
	Serial.println("# due_oscilloscope :: Track A bring-up oracle");
	identity_line();
	Serial.print("# SystemCoreClock = ");
	Serial.print(SystemCoreClock);
	Serial.print("  F_CPU = ");
	Serial.println((uint32_t)F_CPU);
	if ((uint32_t)F_CPU != SystemCoreClock) {
		/* micros() divides by the compile-time F_CPU, so a mismatch
		 * silently skews every timing measurement. Build with
		 * --build-property build.f_cpu=<SystemCoreClock>L. */
		Serial.println("# WARNING: F_CPU != SystemCoreClock, micros() is wrong");
	}
	Serial.print("# ADC clock = ");
	Serial.print(SystemCoreClock / 4u);
	Serial.println(" Hz (PRESCAL=1); datasheet max 20000000");
	Serial.print("# max in-spec trigger = ");
	Serial.print((SystemCoreClock / 2u) / ACQ_MIN_RC);
	Serial.print(" Hz (RC ");
	Serial.print(ACQ_MIN_RC);
	Serial.println("); presets 1..4 are 50k/100k/200k/400k");
	{
		/* CFGOK per endpoint: the controller's own answer to "did
		 * this allocation take". Guessing at DPRAM arithmetic is how
		 * an endpoint that never configured gets blamed on software. */
		char ok[16];
		for (unsigned e = 0; e < 7; e++)
			ok[e] = (UOTGHS->UOTGHS_DEVEPTISR[e]
			         & UOTGHS_DEVEPTISR_CFGOK) ? '1' : '0';
		ok[7] = 0;
		Serial.print("# ep cfgok[0..6]: ");
		Serial.println(ok);
	}
	Serial.print("# control channel: ");
	Serial.println(ctlusb_ok() ? "registered (iface 2/3, EP4-6)"
	                           : "NOT registered - one CDC function only");
	Serial.println("# h for the command list");
	Serial.println("#");
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
	con_str("# commands:"); con_nl();
	console_help();
	con_str("#"); con_nl();
}

static void measure_printf(void)
{
	const int n = 20;
	const char *line = "0123456789012345678901234567890123456789";

	con_str("# measuring printf cost, 20 x 40-char lines"); con_nl();
	console_flush();

	uint32_t t0 = micros();
	/* Braces are load-bearing: con_nl() must stay INSIDE the loop, or
	 * this times n strings and one newline - a mistake that compiles
	 * clean, and has been made twice on Track B already. */
	for (int i = 0; i < n; i++) {
		con_str(line); con_nl();
	}
	console_flush();         /* include actual transmission, not just buffering */
	uint32_t t1 = micros();

	con_str("# printf: "); con_u32((t1 - t0) / n);
	con_str(" us per 40-char line (flushed to the wire)"); con_nl();
	con_str("# this is why printf never goes in an ISR"); con_nl();
	console_flush();
}

/*
 * "N.NN ns per set+clear pair", from hundredths of a nanosecond.
 *
 * Track B's equivalent is print_ns() in main.c, and the arithmetic here
 * is deliberately identical so the two tracks' figures are comparable
 * to the digit. It exists as a helper rather than open-coded twice for
 * the reason console_out.h gives for con_u32w: a call site that
 * computes its own field is a call site that can get it wrong.
 */
static void print_ns_x100(uint32_t ns_x100)
{
	con_u32(ns_x100 / 100u);
	con_ch('.');
	con_u32w(ns_x100 % 100u, 2, '0');
	con_str(" ns per set+clear pair");
	con_nl();
}

static void measure_gpio(void)
{
	const uint32_t n = 100000;

	con_str("# measuring GPIO toggle cost, 100k pairs"); con_nl();
	console_flush();

	uint32_t t0 = micros();
	for (uint32_t i = 0; i < n; i++) {
		PIOB->PIO_SODR = LED_MASK;
		PIOB->PIO_CODR = LED_MASK;
	}
	uint32_t t1 = micros();

	uint32_t t2 = micros();
	for (uint32_t i = 0; i < n; i++) {
		digitalWrite(LED_BUILTIN, HIGH);
		digitalWrite(LED_BUILTIN, LOW);
	}
	uint32_t t3 = micros();

	/*
	 * Fixed point, not float: a float formatter would be pulled into
	 * an image whose only use for it is two debug lines, and Track B
	 * has no %f, %g or %e anywhere. Same arithmetic as Track B's
	 * print_ns() and the same two decimals a float default would
	 * give, so the printed value is unchanged.
	 *
	 * What is deliberately NOT changed is what is measured: Track A
	 * times digitalWrite() where Track B times led_toggle(). That is
	 * a real, tracked divergence, not one to settle here by
	 * rewriting one side.
	 */
	con_str("# direct PIO : ");  print_ns_x100(((t1 - t0) * 100000ull) / n);
	con_str("# digitalWrite: "); print_ns_x100(((t3 - t2) * 100000ull) / n);
	con_str("# use direct PIO writes for ISR instrumentation"); con_nl();
	console_flush();
}

static uint32_t code_to_mv(uint16_t code)
{
	return ((uint32_t)code * 3300u) / 4095u;
}

static void cmd_read(void)
{
	uint16_t a0, a1;
	char buf[96];

	acq_read_pair(ACQ_CH_A0, ACQ_CH_A1, &a0, &a1);

	con_str("# A0(AD7) = "); con_u32w(a0, 4, ' ');
	con_str("  ");           con_u32w(code_to_mv(a0), 4, ' ');
	con_str(" mV    A1(AD6) = "); con_u32w(a1, 4, ' ');
	con_str("  ");           con_u32w(code_to_mv(a1), 4, ' ');
	con_str(" mV"); con_nl();
	Serial.flush();
}

/*
 * DAC1 is driven inverse to DAC0, so a swapped pair of jumpers shows up
 * at once instead of reading plausibly.
 */
static void cmd_sweep(void)
{
	char buf[128];

	Serial.println("# DAC sweep. DAC1 is driven inverse to DAC0.");
	Serial.println("# code   DAC0mV   A0code   A0mV  |  DAC1mV   A1code   A1mV");
	Serial.flush();

	for (uint32_t code = 0; code <= 4095u; code += 256u) {
		uint16_t c = (uint16_t)(code > 4095u ? 4095u : code);
		uint16_t inv = (uint16_t)(4095u - c);

		gen_write_dac(0, c);
		gen_write_dac(1, inv);
		delay(5);

		uint16_t a0, a1;

		acq_read_pair(ACQ_CH_A0, ACQ_CH_A1, &a0, &a1);

		con_str("# ");   con_u32w(c, 4, ' ');
		con_str("   ");  con_u32w(code_to_mv(c), 6, ' ');
		con_str("   ");  con_u32w(a0, 6, ' ');
		con_str("  ");   con_u32w(code_to_mv(a0), 5, ' ');
		con_str("  |  "); con_u32w(code_to_mv(inv), 6, ' ');
		con_str("   ");  con_u32w(a1, 6, ' ');
		con_str("  ");   con_u32w(code_to_mv(a1), 5, ' ');
		con_nl();
		Serial.flush();
	}
	Serial.println("# note: A0/A1 columns are the DAC output as actually measured");
	Serial.flush();
}

/*
 * Hold one channel's DAC fixed and swing the other; any movement in
 * the held channel is multiplexer bleed. Swinging both at once
 * isolates nothing.
 */
/*
 * "=<n>,<ms>x": how many crosstalk observations, and how long to let
 * a DAC output settle before converting.
 *
 * The settle time is a knob because the excursion this measures
 * recurs on a fixed *cadence* rather than at random, and only moving
 * the cadence separates a beat against something periodic from a
 * count kept in software.
 *
 * Timed by wall clock (micros()), not delay(), so run times stay
 * comparable against Track B's own busy-wait loop for the same
 * command.
 */
static uint32_t crosstalk_repeats;
static uint32_t crosstalk_settle_ms;

/*
 * Multiplexer bleed, repeated - "=<n>,<ms>x".
 *
 * It prints a distribution, never one number, and in the order taken.
 * This quantity is spread on an otherwise idle board: about 0 codes
 * or about 160, the loud ones 10-15% of observations, with ADC_MR
 * read back identical in both. 160 codes is 5.8% of the 2747-code
 * full swing, so the two answers disagree about whether the
 * multiplexer is clean, and a single draw reported as a measurement
 * is the defect whichever value is right.
 *
 * It is not two modes: the loud observations recur on a fixed
 * cadence inside a run, and the cadence moves with the settle time
 * so that gap x observation-duration is a multiple of 64 ms at every
 * setting tested. A beat against something periodic, then - not a
 * coin flip and not a startup condition.
 *
 * Which channel is set by the conversion position, not the pin - see
 * the `=<n>C` note below. The A0 arm has never shown it on either
 * track in any pairing.
 *
 * Each arm carries a control that swings nothing, writing the same
 * DAC code twice where the real arm writes 0 then 4095. Same writes,
 * same waits, same conversions. On the *driven* channel it has never
 * once been loud - 0 in 1,005 observations on Track A and 0 in 225
 * on Track B - which is what makes that excursion about the swing
 * rather than the reading. On a *bare* channel it is loud: `=2C`
 * reads a standing +37 codes with nothing swung and +95 with, so
 * those are two effects and the control is what tells them apart.
 * docs/noise.md.
 *
 * What it assumes about the bench, which differs between ours: the
 * A1 arm holds DAC1 at mid scale and swings DAC0. Where DAC1 is
 * jumpered to A1 that pin is *driven* to the held level; where DAC1
 * goes to a scope's external trigger it is *free*, and one
 * sample-and-hold behind a 16:1 mux makes a free input read a
 * smeared copy of whatever was converted before it. The command
 * works either way and does not measure the same thing, so it says
 * which it found.
 *
 * Track B's main.c carries the same command with the same arguments and
 * the same printed format; the summary wording is ctl_bleed_describe()
 * so neither track owns it.
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
	char buf[224];
	uint16_t a0, a1, lo, hi;
	unsigned i;

	if (n > CTL_BLEED_MAX)
		n = CTL_BLEED_MAX;
	if (ms > CTL_BLEED_SETTLE_MAX_MS)
		ms = CTL_BLEED_SETTLE_MAX_MS;

	if (acq_measure_begin() != 0) {
		Serial.println("# crosstalk: refused, the ADC is hardware-triggered - stop the capture first (0)");
	Serial.flush();
	return;
	}

	con_str("# crosstalk: hold one channel, swing the other, ");
	con_u32(n); con_str(" times, "); con_u32(ms);
	con_str(" ms settle"); con_nl();
	Serial.println("# each arm has a control that writes the same code"
	               " twice, so the swing is the only difference");
	/*
	 * The conditions as the hardware holds them, not as this function
	 * believes it set them: the register is the only account that
	 * cannot drift from what was measured.
	 */
	con_str("# adcmr="); con_hex32(acq_mr(), 8);
	con_str(" (this command's own; restored after)"); con_nl();
	Serial.flush();

	/*
	 * The pads too - main.c's twin says why: the pull-up was the
	 * dominant term of an earlier bare-channel disagreement between
	 * tracks, and the instrument never said what the pads were
	 * configured as. On this track the Arduino core walks every pin
	 * at init and analogRead's own path can rewrite one, so the
	 * attestation matters more here, not less. PUSR reads 1 where
	 * the pull-up is DISABLED. A0=PA16, A1=PA24, A2=PA23, all PIOA.
	 */
	con_str("# pioa: psr="); con_hex32(PIOA->PIO_PSR, 8);
	con_str(" osr=");        con_hex32(PIOA->PIO_OSR, 8);
	con_str(" pusr=");       con_hex32(PIOA->PIO_PUSR, 8);
	con_str(" ifsr=");       con_hex32(PIOA->PIO_IFSR, 8);
	con_nl();
	Serial.flush();

	/*
	 * The pair `C` selected, so a pin-versus-position test can be
	 * asked on this track too. See main.c for why `=2C` is the one
	 * variable worth moving.
	 *
	 * Every read is the two-channel sequence, which it was not: this
	 * used to call acq_read_one() and convert the watched channel
	 * with every other disabled, while Track B converted the pair.
	 * That was worth a sign and a factor of twelve - on `=2C` the
	 * same board minutes apart read a plateau of +95 codes with a
	 * loud +37 control on this track and -1205 with a clean control
	 * on Track B, so a bleed figure was not comparable across tracks.
	 * Same sequence on both now; the conversion preceding the
	 * watched one is the same conversion.
	 */
	const unsigned second = acq_pair_second;

	for (i = 0; i < n; i++) {
		gen_write_dac(1, 2048);
		gen_write_dac(0, 0);
		console_bleed_settle(ms);
		acq_read_pair(ACQ_CH_A0, second, &a0, &lo);
		gen_write_dac(0, 4095);
		console_bleed_settle(ms);
		acq_read_pair(ACQ_CH_A0, second, &a0, &hi);
		a1_bleed[i] = (int16_t)((int)hi - (int)lo);
		a1b_lo[i] = lo; a1b_hi[i] = hi;

		/* Same arm with nothing swung: DAC0 is written twice at the
		 * same code. Identical writes, waits and conversions, so a
		 * difference here is not crosstalk from a moving neighbour. */
		gen_write_dac(0, 2048);
		console_bleed_settle(ms);
		acq_read_pair(ACQ_CH_A0, second, &a0, &lo);
		gen_write_dac(0, 2048);
		console_bleed_settle(ms);
		acq_read_pair(ACQ_CH_A0, second, &a0, &hi);
		a1_still[i] = (int16_t)((int)hi - (int)lo);
		a1s_lo[i] = lo; a1s_hi[i] = hi;

		gen_write_dac(0, 2048);
		gen_write_dac(1, 0);
		console_bleed_settle(ms);
		acq_read_pair(ACQ_CH_A0, second, &lo, &a1);
		gen_write_dac(1, 4095);
		console_bleed_settle(ms);
		acq_read_pair(ACQ_CH_A0, second, &hi, &a1);
		a0_bleed[i] = (int16_t)((int)hi - (int)lo);
		a0b_lo[i] = lo; a0b_hi[i] = hi;

		/* And its control. */
		gen_write_dac(1, 2048);
		console_bleed_settle(ms);
		acq_read_pair(ACQ_CH_A0, second, &lo, &a1);
		gen_write_dac(1, 2048);
		console_bleed_settle(ms);
		acq_read_pair(ACQ_CH_A0, second, &hi, &a1);
		a0_still[i] = (int16_t)((int)hi - (int)lo);
		a0s_lo[i] = lo; a0s_hi[i] = hi;
	}

	/* Name the channel watched: with `=2C` these rows are about A2. */
	/*
	 * Whole literals rather than a label built at runtime - the same
	 * change as Track B's, and for the same reason: it was the last
	 * thing here needing a formatter and a 64-byte buffer for a
	 * string with two possible values. Issue #49.
	 */
	const bool a2 = (second == ACQ_CH_A2);

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
	Serial.flush();

	ctl_bleed_describe(a2 ? "A0 bleed (DAC0 held, DAC1 swung, A2 in pair)"
	                      : "A0 bleed (DAC0 held, DAC1 swung, A1 in pair)",
	                   a0_bleed, n);
	ctl_bleed_values("A0 bleed", a0_bleed, n);
	ctl_bleed_raw("A0 bleed", a0b_lo, a0b_hi, n);
	ctl_bleed_describe("A0 control (nothing swung)", a0_still, n);
	ctl_bleed_values("A0 control", a0_still, n);
	ctl_bleed_raw("A0 control", a0s_lo, a0s_hi, n);

	/* Which bench this is, read rather than assumed. */
	gen_write_dac(1, 2048);
	console_bleed_settle(ms);
	acq_read_pair(ACQ_CH_A0, ACQ_CH_A1, &a0, &a1);
	con_str("# A1 reads "); con_u32(a1);
	con_str(" with DAC1 held at 2048: ");
	con_str((a1 > 1800u && a1 < 2300u)
	        ? "DAC1 -> A1 is fitted"
	        : "A1 looks undriven - see docs/noise.md");
	con_nl();
	Serial.println("# bleed is in ADC codes; 1 code = 0.8 mV. Full swing is 2747 codes.");
	Serial.println("# taken at TRACKTIM 15, SETTLING 3 - this command's own,"
	               " not whatever ADC_MR held");
	con_str("# pair-conv: ");
	con_kv_u32("restarts", acq_pair_restarts); con_ch(' ');
	con_kv_u32("timeouts", acq_pair_timeouts);
	con_str(" (nonzero: see #23)"); con_nl();

	acq_measure_end();
	Serial.flush();
}



/*
 * console_cmd_stream() is shared - lib/due_shared/src/
 * console_cmds.c. Issue #41's ordering lives there now, once.
 * This track supplies console_port_stream_start() below.
 */


/*
 * Stream over the programming-port UART. Bandwidth-limited: 115200 baud
 * carries about 11.5 kB/s, so 2 kHz of trigger (2 channels, 2 bytes) at
 * 8 kB/s fits with margin. ASCII output must stay silent while this
 * runs, since frames and logs share the one port here.
 */
/*
 * What the generator is doing, in the contract's words.
 *
 * The sentence is ctl_gen_describe() in the shared layer, so the
 * console and CTL_OP_GEN cannot describe the same state differently and
 * the two tracks cannot drift apart in how they say it. What is here is
 * the part that is genuinely this track's: where the bytes go.
 */
/* console_gen_report() is shared - lib/due_shared/src/console_cmds.c */

static void cmd_stream_uart(uint32_t trigger_hz)
{
	if (!stream_start_uart(trigger_hz)) {
		con_str("# refused"); con_nl();
		console_flush();
		return;
	}
	con_str("# uart-stream: trigger "); con_u32(trigger_hz);
	con_str(" Hz, "); con_str(gen_shape_name(gen_shape)); con_ch(' ');
	con_u32(gen_hz_for(trigger_hz, gen_points, gen_sync));
	con_str(" Hz - binary follows"); con_nl();
	console_flush();
}

static void cmd_stream_stats(void)
{
	/*
	 * The two registers the console can set and nothing else can
	 * confirm, read from the peripheral rather than echoed. `A` and
	 * `I` are applied at the next acq_init()/DACC reset, so what was
	 * asked for and what the converter holds are different questions
	 * and only one of them is evidence.
	 *
	 * Sharing this line rather than adding one: the cost of a console
	 * command is the bytes it puts on the wire, and `?` is polled.
	 */
	stream_dma_report();
	con_str(" adcmr="); con_hex32(acq_mr(), 8);
	con_str(" acr=");   con_hex32(gen_acr(), 8);
	con_nl();
	stream_report();
	con_nl();
	console_flush();
}

/*
 * Find the DACC's maximum update rate.
 *
 * In TAG mode one trigger produces one conversion, so the achieved rate
 * is table length times ENDTX count over elapsed time. Counting the
 * peripheral's own completions avoids needing the ADC to observe the
 * output, and gives the same kind of hard number the ADC sweep produced.
 */
static void cmd_dac_sweep(void)
{
	static const uint32_t rates[] = {
		 100000,  500000,  800000, 1000000, 1200000,
		1500000, 1750000, 2000000, 2500000, 3000000
	};
	gen_init();
	con_str("# DACC update-rate sweep, TC0 ch1 (TIOA1), TAG mode"); con_nl();
	con_str("#     want      RC   TCexact    measured    ratio"); con_nl();
	console_flush();

	for (unsigned i = 0; i < sizeof(rates) / sizeof(rates[0]); i++) {
		if (!gen_start_independent(rates[i])) {
			con_str("# "); con_u32w(rates[i], 8, ' ');
			con_str("       -         -    REFUSED"); con_nl();
			console_flush();
			continue;
		}

		uint32_t sync = gen_endtx_count;
		uint32_t guard = micros();
		while (gen_endtx_count == sync && (micros() - guard) < 500000u)
			{ }

		uint32_t t0 = micros();
		uint32_t e0 = gen_endtx_count;
		while (gen_endtx_count - e0 < 64u && (micros() - t0) < 1000000u)
			{ }
		uint32_t t1 = micros();
		uint32_t got = gen_endtx_count - e0;

		gen_stop();

		uint32_t rc      = gen_configured_rc();
		uint32_t tcexact = (SystemCoreClock / 2u) / rc;
		uint32_t us      = t1 - t0;
		uint64_t convs   = (uint64_t)got * GEN_TABLE_LEN;
		uint32_t measured = us ? (uint32_t)((convs * 1000000ull) / us) : 0;
		uint32_t ratio_x1000 = tcexact ?
			(uint32_t)(((uint64_t)measured * 1000ull) / tcexact) : 0;

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
 * Cross-check the DAC ceiling against the frequency it actually emits.
 *
 * ENDTX counts PDC completions, which equal conversions only if the DACC
 * back-pressures the PDC when it cannot keep up. Driving the DAC on its
 * own timebase and capturing the result gives an independent measure: a
 * 512-entry table played at R conversions per second must produce a tone
 * at R/512, whatever the trigger was set to.
 */
static void cmd_dac_crosscheck(uint32_t dac_hz)
{
	gen_init();
	if (!gen_start_independent(dac_hz)) {
		con_str("# refused"); con_nl();
		console_flush();
		return;
	}
	if (!stream_start_capture_only(200000, 2)) {
		con_str("# capture refused"); con_nl();
		console_flush();
		return;
	}

	/*
	 * These three lines print AFTER the capture start, deliberately.
	 * docs/debugging.md prices this site at +4.77 ms of margin
	 * against a 20.32 ms runway - about one added banner line from
	 * biting. It survives only because capture here is fixed at
	 * 200,000 Hz, where the ring holds longest; a fourth line turns
	 * this into cmd_stream, losing frames before the host sees any.
	 *
	 * Moving them above stream_start_capture_only() would fix the
	 * margin and break the measurement: the interval between
	 * gen_start_independent() and the capture start sets the sampling
	 * phase against the DAC's table wrap, and this command exists to
	 * measure exactly that phase, one sample per table wrap. Putting
	 * ~110 characters of UART in there would move it by milliseconds.
	 *
	 * Not an oversight, and not safe to "fix" like the others. If a
	 * print is ever needed here, put it above
	 * gen_start_independent() where it costs nothing.
	 */
	con_str("# DAC indep "); con_u32(dac_hz);
	con_str(" Hz (RC "); con_u32(gen_configured_rc());
	con_str("), capture 200000 Hz"); con_nl();
	con_str("# if the DAC truly runs at the trigger, tone = ");
	con_u32(dac_hz / GEN_TABLE_LEN); con_str(" Hz"); con_nl();
	con_str("# if it saturates near 1539700, tone = 3007 Hz instead");
	con_nl();
	console_flush();
}

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
 * print mid-run would stall the very loops being observed. The reads are
 * registers and counters, not the sample stream; `next` peeks one
 * half-word at DACC_TPR to see what the PDC is about to fetch, which is
 * a diagnostic exception to the no-CPU-on-samples rule, not a data path.
 *
 * The interval is deliberately not a round divisor of anything being
 * generated: periodic diagnostics alias periodic signals.
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
	/*
	 * No buffer here, above the early return: declaring one there
	 * would set up a 192-byte stack frame on every idle main-loop
	 * pass for a function that returns immediately - `Q` measured
	 * this at 590 ns against Track B's 115 ns for the same function
	 * with no buffer, 475 ns on a ~9 us pass for nothing. It lives in
	 * the reporting block below, the only thing that uses it.
	 */
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
		char buf[192];

		con_str("# diag: play ring base="); con_hex32(base, 8);
		con_str(" slot="); con_u32(PLAY_BUF_BYTES);
		con_str(" B nslots="); con_u32(PLAY_NBUF); con_nl();
		Serial.println("#    ms  prod  cons endtx    svc  tpr=slot+off  tcr"
		               "  next(tag,code)  cdr7 cdr6  aprod acons");
		for (unsigned i = 0; i < DIAG_N; i++) {
			struct diag_snap *s = &diag[i];
			uint32_t off = s->tpr - base;

			con_str("# "); con_u32w(s->ms - diag[0].ms, 5, ' ');
			con_ch(' ');   con_u32w(s->prod, 5, ' ');
			con_ch(' ');   con_u32w(s->cons, 5, ' ');
			con_ch(' ');   con_u32w(s->endtx, 5, ' ');
			con_ch(' ');   con_u32w(s->svc, 6, ' ');
			con_str("  ");
			con_u32(off / PLAY_BUF_BYTES); con_ch('+');
			con_u32l(off % PLAY_BUF_BYTES, 4);
			con_ch(' ');   con_u32w(s->tcr, 4, ' ');
			con_str("  ");  con_hex32(s->next, 4);
			con_str("(t");  con_u32((s->next >> 12) & 3u);
			con_ch(',');    con_u32w(s->next & 0x0fffu, 4, ' ');
			con_str(")  "); con_u32w(s->cdr7 & 0x0fffu, 4, ' ');
			con_ch(' ');    con_u32w(s->cdr6 & 0x0fffu, 4, ' ');
			con_str("  ");  con_u32w(s->aprod, 5, ' ');
			con_ch(' ');    con_u32w(s->acons, 5, ' ');
			con_nl();
		}
		Serial.flush();
	}
}

/*
 * USB registers, the same set Track B's `u` prints.
 *
 * Track A never programs these itself - the core does - so this is a
 * read-only window used to compare what the stock stack leaves the
 * controller in against what the bare-metal driver sets up.
 */
static void cmd_usb_dump(void)
{
	uint32_t ctrl = UOTGHS->UOTGHS_CTRL;
	uint32_t dctl = UOTGHS->UOTGHS_DEVCTRL;
	uint32_t sr   = UOTGHS->UOTGHS_SR;
	char buf[176];

	con_str("# usb CTRL=");  con_hex32(ctrl, 8);
	con_str(" USBE=");       con_u32(!!(ctrl & UOTGHS_CTRL_USBE));
	con_str(" OTGPADE=");    con_u32(!!(ctrl & UOTGHS_CTRL_OTGPADE));
	con_str(" FRZCLK=");     con_u32(!!(ctrl & UOTGHS_CTRL_FRZCLK));
	con_str(" UIMOD=");      con_u32(!!(ctrl & UOTGHS_CTRL_UIMOD));
	con_str(" UIDE=");       con_u32(!!(ctrl & UOTGHS_CTRL_UIDE));
	con_nl();

	con_str("# usb DEVCTRL="); con_hex32(dctl, 8);
	con_str(" DETACH=");       con_u32(!!(dctl & UOTGHS_DEVCTRL_DETACH));
	con_str(" SPDCONF=");
	con_u32((dctl & UOTGHS_DEVCTRL_SPDCONF_Msk) >>
	        UOTGHS_DEVCTRL_SPDCONF_Pos);
	con_str("  SR=");          con_hex32(sr, 8);
	con_str(" CLKUSABLE=");    con_u32(!!(sr & UOTGHS_SR_CLKUSABLE));
	con_nl();

	con_str("# usb DEVIMR="); con_hex32(UOTGHS->UOTGHS_DEVIMR, 8);
	con_str(" DEVISR=");      con_hex32(UOTGHS->UOTGHS_DEVISR, 8);
	con_str(" EPT=");         con_hex32(UOTGHS->UOTGHS_DEVEPT, 8);
	con_str(" EP0CFG=");      con_hex32(UOTGHS->UOTGHS_DEVEPTCFG[0], 8);
	con_str(" EP0ISR=");      con_hex32(UOTGHS->UOTGHS_DEVEPTISR[0], 8);
	con_nl();

	con_str("# pmc PMC_USB="); con_hex32(PMC->PMC_USB, 8);
	con_str(" SR_LOCKU=");     con_u32(!!(PMC->PMC_SR & PMC_SR_LOCKU));
	con_str(" SCSR=");         con_hex32(PMC->PMC_SCSR, 8);
	con_nl();

	con_str("# ep2(OUT) CFG="); con_hex32(UOTGHS->UOTGHS_DEVEPTCFG[2], 8);
	con_str(" ISR=");           con_hex32(UOTGHS->UOTGHS_DEVEPTISR[2], 8);
	con_str("  ep3(IN) CFG=");  con_hex32(UOTGHS->UOTGHS_DEVEPTCFG[3], 8);
	con_str(" ISR=");           con_hex32(UOTGHS->UOTGHS_DEVEPTISR[3], 8);
	con_nl();

	/* The core never arms these; usbdma.cpp does. Printed in the same
	 * layout as Track B's dump so the two can be read side by side. */
	con_str("# dma ch1(OUT) CTRL=");
	con_hex32(UOTGHS->UOTGHS_DEVDMA[1].UOTGHS_DEVDMACONTROL, 8);
	con_str(" ST=");
	con_hex32(UOTGHS->UOTGHS_DEVDMA[1].UOTGHS_DEVDMASTATUS, 8);
	con_str("  ch2(IN) CTRL=");
	con_hex32(UOTGHS->UOTGHS_DEVDMA[2].UOTGHS_DEVDMACONTROL, 8);
	con_str(" ST=");
	con_hex32(UOTGHS->UOTGHS_DEVDMA[2].UOTGHS_DEVDMASTATUS, 8);
	con_nl();

	/*
	 * The activity LEDs, so a dark indicator can be told apart from a
	 * pin the sketch never took control of. PSR bit set means PIO owns
	 * it, OSR set means it is an output, ODSR is the driven level -
	 * and these are active low, so 0 is lit.
	 */
	con_str("# leds TXL(PA21) pio="); con_u32(!!(PIOA->PIO_PSR & TXL_MASK));
	con_str(" out=");                 con_u32(!!(PIOA->PIO_OSR & TXL_MASK));
	con_str(" lit=");                 con_u32(!(PIOA->PIO_ODSR & TXL_MASK));
	con_str("   RXL(PC30) pio=");     con_u32(!!(PIOC->PIO_PSR & RXL_MASK));
	con_str(" out=");                 con_u32(!!(PIOC->PIO_OSR & RXL_MASK));
	con_str(" lit=");                 con_u32(!(PIOC->PIO_ODSR & RXL_MASK));
	con_nl();

	usbdma_dump();
	Serial.flush();
}

/*
 * Where the main loop's time goes.
 *
 * Track A's loop measured 93k passes per second against Track B's 1.4M,
 * and the DMA benches re-arm at most once per pass, so that difference
 * is a throughput ceiling and not a curiosity. Guessing at it from the
 * source was unproductive; this times each candidate directly.
 *
 * Results are ns per call. Anything here that costs more than a few
 * hundred nanoseconds does not belong on a path that runs every pass.
 */
/*
 * Dump the playback ring's occupancy distribution.
 *
 * Byte-for-byte the format drivers/../main.c prints, because the suite
 * parses one regex for both tracks and docs/control-protocol.md makes
 * that a requirement rather than a convenience. Printed as a bare
 * comma-separated list rather than key=value pairs: 32 buckets as
 * `occ0=..` would be a long line for a parse that gains nothing, and
 * the index is the occupancy, so position is the key.
 *
 * Track B also emits a `play_rate` line here. This track has no rate
 * trace yet - it is the other half of objective 1c - and the host's
 * parser treats that line as optional, so its absence reads as "not
 * sampled" rather than as a malformed record.
 */
static void cmd_occ_hist(void)
{
	char buf[64];

	con_str("# play_occ ");
	con_kv_u32("min", play_occ_min);        con_ch(' ');
	con_kv_u32("endtx", play_endtx_seen);   con_ch(' ');
	con_kv_u32("runus", play_run_us);       con_ch(' ');
	con_kv_u32("consumed", play_consumed);  con_str(" hist=");
	Serial.print(buf);
	for (unsigned i = 0; i < PLAY_NBUF; i++) {
		con_u32(play_occ_hist[i]);
		if (i + 1u < PLAY_NBUF)
			con_ch(',');
		Serial.print(buf);
	}
	Serial.println();
	Serial.flush();

	con_str("# play_occ_trace ");
	con_kv_u32("decim", PLAY_OCC_DECIM);  con_ch(' ');
	con_kv_u32("n", play_occ_traced);     con_str(" v=");
	Serial.print(buf);
	for (unsigned i = 0; i < play_occ_traced; i++) {
		con_u32(play_occ_trace[i]);
		if (i + 1u < play_occ_traced)
			con_ch(',');
		Serial.print(buf);
		/* 256 entries is more than one buffer holds. */
		if ((i & 31u) == 31u)
			Serial.flush();
	}
	Serial.println();
	Serial.flush();
}


static void cmd_profile(void)
{
	const uint32_t n = 20000;
	char buf[128];
	uint32_t t0, t1;

	Serial.println("# main-loop profile, ns per call");
	Serial.flush();

#define PROF(label, expr)                                            \
	do {                                                         \
		t0 = micros();                                       \
		for (uint32_t i = 0; i < n; i++) { expr; }            \
		t1 = micros();                                       \
		con_str("# "); con_strl(label, 22); con_ch(' ');      \
		con_u32w((uint32_t)(((uint64_t)(t1 - t0) * 1000ull)   \
		                    / n), 6, ' ');                    \
		con_str(" ns"); con_nl();                             \
		console_flush();                                      \
	} while (0)

	PROF("empty loop", __asm__ volatile(""));
	/*
	 * The per-pass diagnostics, profiled because this loop once ran
	 * at 75.1 k passes/s against Track B's 160.4 k and invariant 3
	 * wants the two comparable. Each of these reads a UOTGHS register
	 * on every pass to ask about an event that happens tens of times
	 * a second - which is the exact shape of cost CLAUDE.md records
	 * Track B removing when gating ctl_service and usb_cdc_poll to
	 * 1 kHz took its idle pass from 9.72 to 6.70 us.
	 */
	PROF("UOTGHS_DEVEPT read", (void)UOTGHS->UOTGHS_DEVEPT);
	PROF("usbtrace_sample()", usbtrace_sample(0));
	PROF("devept_restore()", devept_restore());
	PROF("ctlusb_quiesce_int()", ctlusb_quiesce_interrupts());
	PROF("ctl_service()", ctl_service());
	PROF("millis()", (void)millis());
	PROF("micros()", (void)micros());
	PROF("Serial.available()", (void)Serial.available());
	PROF("SerialUSB.available()", (void)SerialUSB.available());
	PROF("SerialUSB.dtr()", (void)SerialUSB.dtr());
	PROF("usbdma_out_busy()", (void)usbdma_out_busy());
	PROF("usbdma_keepalive()", usbdma_keepalive());
	PROF("play_service()", play_service());
	PROF("stream_service()", stream_service());
	PROF("diag_service()", diag_service());
#undef PROF

	Serial.println("# note: services early-return unless started");
	Serial.flush();
}

/*
 * Branch to an even address. The Cortex-M3 requires the Thumb bit set in
 * every branch target, so this raises INVSTATE, which escalates to a
 * HardFault because UsageFault is not separately enabled.
 */
/* console_trigger_fault() is shared - lib/due_shared/src/console_cmds.c */

/*
 * Override the core's weak serialEventRun(), which runs after every
 * loop() and is invisible to `Q`.
 *
 * The stock one polls UARTClass::available() on all four hardware
 * serials - Serial, Serial1, Serial2, Serial3 - so it can dispatch a
 * serialEvent() handler. This sketch opens one of them and defines no
 * such handler, so three of those four calls ask a UART that was
 * never begun whether it has data, and the fourth duplicates what
 * console_feed() already does at the bottom of loop().
 *
 * Measured: Serial.available() is 372 ns on this board, so the stock
 * version is about 1.5 us of an 8.6 us pass (17%), spent outside
 * loop() where the profiler cannot see it. The cost is the core's
 * default policy, not anything the silicon requires, and a sketch
 * may decline it.
 *
 * Nothing is lost: serialEvent() and friends are weak empty stubs in
 * this image, and the console is read by console_feed() on both
 * tracks.
 */
void serialEventRun(void)
{
}

void setup()
{
	/* Before anything derives a rate from it. */
	clock_set_mck(MCK_MULA_DEFAULT);

	pinMode(LED_BUILTIN, OUTPUT);
	led_aux_init();
	analogWriteResolution(12);
	analogReadResolution(12);
	Serial.begin(115200);
	SerialUSB.begin(0);          /* native port; CDC ignores baud */
	while (!Serial && millis() < 2000) { }
	boot_log();
	/*
	 * Before the banner, so load_prev_cycles starts from a defined
	 * point rather than from whatever CYCCNT held at reset - the first
	 * delta would otherwise land in an arbitrary bucket and stay in
	 * the histogram for the whole run.
	 */
	load_init();

	/*
	 * The converters, so this board holds its own configuration from
	 * boot rather than the Arduino core's: before a stream, `?` on
	 * this track shows the core's own ADC_MR from analogRead(), which
	 * differs from Track B's - a confound for an idle-state
	 * measurement such as temperature.
	 *
	 * Neither call starts anything: acq_init() configures the ADC and
	 * leaves the timer stopped, gen_init() configures the DACC and
	 * builds the table but does not start a trigger - gen_start()
	 * does. A stream still calls both again with its own arguments.
	 */
	acq_init();
	gen_init();

	banner();
	heartbeat_at = millis();
}

/*
 * High-water mark on UOTGHS_DEVEPT.
 *
 * SET_CONFIGURATION demonstrably ran (_usbConfiguration=1) and its
 * handler calls UDD_InitEndpoints() immediately before setting that
 * flag, so EP1-6 should have been enabled - yet DEVEPT reads 1. Either
 * the enables never happened, or they happened and something cleared
 * them. A single sample cannot tell those apart and the main loop is
 * the only place that can watch. Costs one OR per pass.
 */
volatile uint32_t devept_seen;

/*
 * When did it change, and had the bus been reset when it did?
 *
 * The high-water mark above says EP1-6 *were* enabled and are not any
 * more. It cannot say when, which is the difference between "cleared
 * during configuration" and "cleared later, when something touched the
 * endpoints" - and those want different code read.
 *
 * So trace every change, with an independent witness for the one
 * explanation that would make this ordinary. UOTGHS_DEVCTRL carries
 * UADD and ADDEN: SET_ADDRESS writes them and a bus reset clears them,
 * in the controller, with no software involved. `_usbConfiguration` is
 * the core's own flag for the same question and it is only as good as
 * the core's EORST handler running. If DEVEPT drops to 1 while UADD is
 * still set, no reset happened and something in this image cleared six
 * endpoints. If UADD clears with it, the host reset the bus and the
 * core failed to notice, which is a different bug in a different file.
 *
 * Sixteen entries and a saturating index: this must not become the
 * thing that perturbs what it measures, and the interesting events are
 * the first ones. Two reads and a compare per pass.
 */
#define USBTRACE_N 32u
struct usbtrace_e {
	uint32_t us, pass, devept, devctrl, cfg;
};
static volatile struct usbtrace_e usbtrace[USBTRACE_N];
static volatile uint32_t usbtrace_n;      /* entries kept, saturating */
static volatile uint32_t usbtrace_drop;   /* changes past the sixteenth */

static inline void usbtrace_sample(uint32_t pass)
{
	extern volatile uint32_t _usbConfiguration;
	static uint32_t last_ept = 0xffffffffu, last_ctrl, last_cfg;
	uint32_t ept  = UOTGHS->UOTGHS_DEVEPT;
	uint32_t ctrl = UOTGHS->UOTGHS_DEVCTRL;
	uint32_t cfg  = _usbConfiguration;

	if (ept == last_ept && ctrl == last_ctrl && cfg == last_cfg)
		return;
	last_ept = ept; last_ctrl = ctrl; last_cfg = cfg;

	if (usbtrace_n >= USBTRACE_N) {
		usbtrace_drop++;
		return;
	}
	usbtrace[usbtrace_n].us      = micros();
	usbtrace[usbtrace_n].pass    = pass;
	usbtrace[usbtrace_n].devept  = ept;
	usbtrace[usbtrace_n].devctrl = ctrl;
	usbtrace[usbtrace_n].cfg     = cfg;
	usbtrace_n++;
}


/*
 * Put the enables back, a bounded number of times, and report what the
 * controller does with the write.
 *
 * The trace says EP1-6 are enabled at SET_CONFIGURATION and cleared
 * 2.5 ms later with the device still addressed, so no bus reset. That
 * narrows the question to one the controller can answer directly: does
 * EPEN stay set when it is written back? If it reads 0x7f and holds,
 * the clear was a one-off act by something in this image and the next
 * job is to find it. If it reads back 1, the controller is refusing to
 * enable these endpoints - which is DPRAM, not software, and CFGOK
 * reporting 1111111 is then describing configurations rather than
 * allocations.
 *
 * Bounded because an unbounded retry against a controller that refuses
 * is a main loop that does nothing else. Eight is enough to tell a
 * one-off from a fight, and usbtrace records every attempt with its
 * timestamp.
 */
#define DEVEPT_RESTORE_MAX 8u
static volatile uint32_t devept_restores;
static volatile uint32_t devept_after[DEVEPT_RESTORE_MAX];

static inline void devept_restore(void)
{
	extern volatile uint32_t _usbConfiguration;

	if (devept_restores >= DEVEPT_RESTORE_MAX)
		return;
	if (!_usbConfiguration || devept_seen != 0x7fu)
		return;
	if (UOTGHS->UOTGHS_DEVEPT == 0x7fu)
		return;

	UOTGHS->UOTGHS_DEVEPT |= 0x7eu;                  /* EP1-6 */
	devept_after[devept_restores] = UOTGHS->UOTGHS_DEVEPT;
	devept_restores++;
}


/* The M preset's ADC-start-to-DAC-start gap. See ha_mimic_gap(). */
static uint32_t mimic_start_delay_us;

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

static void ha_help(const uint32_t *a)
{
	(void)a;
	cmd_help();
}

static void ha_ident(const uint32_t *a)
{
	(void)a;
	identity_line();
}

static void ha_printf(const uint32_t *a)
{
	(void)a;
	measure_printf();
}

static void ha_gpio(const uint32_t *a)
{
	(void)a;
	measure_gpio();
}

static void ha_fault(const uint32_t *a)
{
	(void)a;
	console_trigger_fault();
}

static void ha_read(const uint32_t *a)
{
	(void)a;
	cmd_read();
}

static void ha_sweep(const uint32_t *a)
{
	(void)a;
	cmd_sweep();
}

static void ha_xtalk(const uint32_t *a)
{
	crosstalk_repeats = a[0];
	crosstalk_settle_ms = a[1];
	cmd_crosstalk();
}

static void ha_ratesweep(const uint32_t *a)
{
	console_cmd_rate_sweep(a[2] ? a[2] : 2u);
}

static void ha_dac_sweep(const uint32_t *a)
{
	(void)a;
	cmd_dac_sweep();
}

static void ha_dac_15m(const uint32_t *a)
{
	(void)a;
	cmd_dac_crosscheck(1500000);
}

static void ha_dac_30m(const uint32_t *a)
{
	(void)a;
	cmd_dac_crosscheck(3000000);
}

static void ha_s50(const uint32_t *a)
{
	(void)a;
	console_cmd_stream(50000);
}

static void ha_s100(const uint32_t *a)
{
	(void)a;
	console_cmd_stream(100000);
}

static void ha_s200(const uint32_t *a)
{
	(void)a;
	console_cmd_stream(200000);
}

static void ha_s400(const uint32_t *a)
{
	(void)a;
	console_cmd_stream(400000);
}

/* Highest rate the ADC sustains, derived from the measured cliff at
 * RC 86. That compare value holds across master clock settings,
 * because the timer and ADC clocks scale together. */
static void ha_smax(const uint32_t *a)
{
	(void)a;
	console_cmd_stream((SystemCoreClock / 2u) / ACQ_MIN_RC);
}

static void ha_stop(const uint32_t *a)
{
	(void)a;
	stream_stop(); play_stop();
	Serial.println("# stream stopped");
	Serial.flush();
}

static void ha_stats(const uint32_t *a)
{
	(void)a;
	cmd_stream_stats();
}

static void ha_usb(const uint32_t *a)
{
	(void)a;
	cmd_usb_dump();
}

static void ha_uart_stream(const uint32_t *a)
{
	(void)a;
	cmd_stream_uart(2000);
}

static void ha_flood(const uint32_t *a)
{
	(void)a;
	stream_flood_start(); state_log("bench=flood(IN)");
	Serial.println("# flood: IN only");
	Serial.flush();
}

static void ha_sink(const uint32_t *a)
{
	(void)a;
	stream_sink_start(); state_log("bench=sink(OUT)");
	Serial.println("# sink: OUT only, send data now");
	Serial.flush();
}

static void ha_duplex(const uint32_t *a)
{
	(void)a;
	stream_duplex_start(); state_log("bench=duplex");
	Serial.println("# duplex: IN and OUT together");
	Serial.flush();
}

/*
 * The same three over UOTGHS endpoint DMA. The Arduino core never
 * programs a DMA channel itself; these take the bulk endpoints away
 * from it and drive the controller directly, which is what makes
 * the two tracks comparable on the transport as well as the
 * converters.
 */
static void ha_flood_dma(const uint32_t *a)
{
	(void)a;
	stream_flood_dma_start(); state_log("bench=flood-dma");
	Serial.println("# flood: IN via DMA");
	Serial.flush();
}

static void ha_sink_dma(const uint32_t *a)
{
	(void)a;
	stream_sink_dma_start(); state_log("bench=sink-dma");
	Serial.println("# sink: OUT via DMA, send data now");
	Serial.flush();
}

static void ha_duplex_dma(const uint32_t *a)
{
	(void)a;
	stream_duplex_dma_start(); state_log("bench=duplex-dma");
	Serial.println("# duplex: IN+OUT via DMA");
	Serial.flush();
}

/*
 * The complete loop: the host supplies the waveform, the DAC emits
 * it, the jumper carries it to the ADC, and the capture comes back
 * over the same USB pipe. Both directions run at once, which is the
 * target configuration.
 *
 * "=<dac>[,<adc>]L"; one number sets both, none means 200k.
 */
static void ha_loop(const uint32_t *a)
{
	console_cmd_loop(a[0] ? a[0] : 200000u,
	                 a[1] ? a[1] : (a[0] ? a[0] : 200000u),
	                 a[2] ? a[2] : 2u);
}

/* Playback with NO capture stream, to separate a fault in the DAC
 * path from an interaction between the two service loops. */
static void ha_play(const uint32_t *a)
{
	console_cmd_play(a[0] ? a[0] : 200000u);
}

static void ha_occ(const uint32_t *a)
{
	(void)a;
	cmd_occ_hist();
}

static void ha_epstate(const uint32_t *a)
{
	(void)a;
	/*
	 * Endpoint state, readable while a stream is running.
	 *
	 * The banner reports CFGOK once, at boot, which is exactly when
	 * nothing is wrong yet. The question this exists for is whether
	 * the sample endpoints are still configured *during* a capture,
	 * once ep_apply_autosw() and the control-endpoint realloc have
	 * been running against each other for a few thousand passes.
	 */
	char ok[16];
	for (unsigned e = 0; e < 7; e++)
		ok[e] = (UOTGHS->UOTGHS_DEVEPTISR[e]
		         & UOTGHS_DEVEPTISR_CFGOK) ? '1' : '0';
	ok[7] = 0;
	con_str("# ep cfgok="); con_str(ok);
	con_str(" reallocs=");  con_u32(ctlusb_reallocs);
	con_str(" cfgfail=");   con_u32(ctlusb_cfg_fail);
	con_str(" ep2=");       con_hex32(UOTGHS->UOTGHS_DEVEPTCFG[2], 8);
	con_str(" ep3=");       con_hex32(UOTGHS->UOTGHS_DEVEPTCFG[3], 8);
	con_nl(); console_flush();

	/*
	 * The table the core actually scans, and the count it
	 * derives from it.
	 *
	 * USBCore's SET_CONFIGURATION handler counts endpoints by
	 * walking EndPoints[] to the first zero and hands that count
	 * to UDD_InitEndpoints(), which loops from 1. So a zero in
	 * the wrong slot silently truncates the whole thing, and
	 * DEVEPT ends up with only EP0 enabled - which is exactly
	 * what this branch reads (EPT=00000001 against 0000000f on
	 * a working build) while CFGOK still reports 1111111,
	 * because CFGOK describes a configuration and EPEN is what
	 * actually enables the endpoint.
	 *
	 * Printed rather than reasoned about: the count is the whole
	 * question and nothing else on the board reveals it.
	 */
	{
		extern uint32_t EndPoints[];
		unsigned count = 0;
		while (EndPoints[count] != 0)
			count++;
		con_str("# eptab count="); con_u32(count); con_str(" :");
		for (unsigned e = 0; e < 10; e++) {
			con_ch(' ');
			con_u32(EndPoints[e]);
		}
		con_nl(); console_flush();

		/*
		 * Did SET_CONFIGURATION ever run?
		 *
		 * USBCore sets _usbConfiguration in its SET_CONFIGURATION
		 * handler, immediately after UDD_InitEndpoints(), and
		 * clears it on bus reset. DEVEPT reads 1 and DEVCTRL says
		 * the device is addressed, so the question is whether the
		 * host never configured it or whether the handler ran and
		 * something undid it. Nothing else on the board
		 * distinguishes those.
		 */
		{
			extern volatile uint32_t _usbConfiguration;
			con_str("# usbcfg _usbConfiguration=");
			con_u32(_usbConfiguration);
			con_str(" deveptseen="); con_hex32(devept_seen, 8);
			con_str(" now=");        con_hex32(UOTGHS->UOTGHS_DEVEPT, 8);
			con_nl(); console_flush();
		}

		/*
		 * The trace. One line per change of DEVEPT, DEVCTRL or
		 * _usbConfiguration, in the order they happened, with
		 * micros() and the pass number.
		 *
		 * Read DEVCTRL first: bit 8 is ADDEN and bits 0-6 are
		 * UADD, both written by SET_ADDRESS and both cleared by
		 * the controller on a bus reset. An entry where DEVEPT
		 * falls to 1 while ADDEN is still set is a clear that no
		 * reset explains.
		 */
		{
			con_str("# usbrestore n="); con_u32(devept_restores);
			con_str(" after:");
			for (unsigned i = 0; i < devept_restores
			                  && i < DEVEPT_RESTORE_MAX; i++) {
				con_ch(' ');
				con_hex32(devept_after[i], 8);
			}
			con_nl(); console_flush();
			con_str("# ctlout ");
			con_kv_u32("banks", ctlusb_out_banks); con_ch(' ');
			con_kv_u32("bytes", ctlusb_out_bytes);
			con_nl(); console_flush();
			con_str("# usbsetup ");
			con_kv_u32("n", ctlusb_setup_n);       con_ch(' ');
			con_kv_u32("dropped", ctlusb_setup_drop);
			con_nl(); console_flush();
			for (unsigned i = 0; i < ctlusb_setup_n
			                  && i < CTLUSB_SETUP_N; i++) {
				con_str("# s"); con_u32w(i, 2, '0');
				con_str(" type="); con_hex32(ctlusb_setups[i].bmRequestType, 2);
				con_str(" req=");  con_hex32(ctlusb_setups[i].bRequest, 2);
				con_str(" val=");  con_hex32(ctlusb_setups[i].wValue, 4);
				con_str(" idx=");  con_hex32(ctlusb_setups[i].wIndex, 4);
				con_str(" len=");  con_u32(ctlusb_setups[i].wLength);
				con_str(" claimed="); con_u32(ctlusb_setups[i].claimed);
				con_nl(); console_flush();
			}
			con_str("# usbtrace ");
			con_kv_u32("n", usbtrace_n);           con_ch(' ');
			con_kv_u32("dropped", usbtrace_drop);
			con_str(" (us pass devept devctrl cfg)");
			con_nl(); console_flush();
			for (unsigned i = 0; i < usbtrace_n && i < USBTRACE_N; i++) {
				con_str("# t"); con_u32w(i, 2, '0');
				con_ch(' ');    con_u32w(usbtrace[i].us, 10, ' ');
				con_ch(' ');    con_u32w(usbtrace[i].pass, 10, ' ');
				con_ch(' ');    con_hex32(usbtrace[i].devept, 8);
				con_ch(' ');    con_hex32(usbtrace[i].devctrl, 8);
				con_ch(' ');    con_u32(usbtrace[i].cfg);
				con_nl(); console_flush();
			}
		}
	}
}

/*
 * "=<shape>,<pts>W": the internal generator's waveform.
 *
 * Track B's gen.c carries the same command with the same
 * arguments and the same printed format - independent source,
 * identical feature, which is invariant 3.
 *
 * shape 0 sine, 1 square, 2 ramp, 3 triangle, 4 DC. pts is the
 * resolution and rounds down to a power of two in 2..256;
 * omitting it keeps the current value. Halving the points
 * doubles the output frequency and coarsens the staircase,
 * which is the trade it exists to expose.
 */
static void ha_wave(const uint32_t *a)
{
	gen_set_shape(a[0]);
	if (a[1])
		gen_set_points(a[1]);
	/* "=<shape>,<pts>,<amp>W". amp in 1/256ths of full scale,
	 * about mid: a small waveform still moves the converter
	 * every update without spanning its range. */
	if (a[2])
		gen_set_amp(a[2]);
	console_gen_report();
}

/*
 * "=<n>J": the sync output, 0 off, 1 per cycle, 2 per table wrap.
 * Track B's main.c carries the same command with the same
 * arguments and the same printed format.
 *
 * A trigger for the bench, on DAC1. Triggering a scope on the
 * signal itself divides the pin's ~20 mV of noise by the
 * waveform's slew rate at the trigger level, which is why a ramp
 * shakes 27 us and a square does not shake at all - docs/awg.md.
 * The scope's EXT input tops out at 1.2 V against a 0.52-2.82 V
 * DAC, so AC-couple the trigger or it will never fire.
 */
static void ha_sync(const uint32_t *a)
{
	gen_set_sync(a[0]);
	/* "=<mode>,<amp>J". The sync's own swing, in 256ths. */
	if (a[1])
		gen_set_sync_amp(a[1]);
	console_gen_report();
}

/*
 * "=<n>C": which channel pairs with A0 in a two-channel capture,
 * 1 for A1 and 2 for A2. It is how source impedance is told apart
 * from conversion slot - see acq_set_pair().
 */
static void ha_pair(const uint32_t *a)
{
	acq_set_pair(a[0]);
	Serial.print("# capture pair: A0 + A");
	Serial.print(acq_pair_second == ACQ_CH_A2 ? 2 : 1);
	Serial.println(" (next 2ch stream)");
	Serial.flush();
}

/*
 * "=<n>N": generator layout, 0 normal, 1 swapped, 2 two-cycle,
 * 3 all-DC. Rebuilt now and again by gen_init(), which M calls.
 * See gen.h for what each arm is for.
 */
static void ha_layout(const uint32_t *a)
{
	static const char *const names[] = {
		"normal: sine DAC0, DC DAC1",
		"swapped: DC DAC0, sine DAC1",
		"two-cycle: two sine periods per wrap",
		"all-DC: no sine on either",
	};

	gen_set_layout(a[0]);
	Serial.print("# gen layout ");
	Serial.print(gen_layout);
	Serial.print(" = ");
	Serial.println(names[gen_layout]);
	Serial.flush();
}

static void ha_profile(const uint32_t *a)
{
	(void)a;
	cmd_profile();
}

static void ha_ring(const uint32_t *a)
{
	(void)a;
	play_dump();
}

static void ha_diag(const uint32_t *a)
{
	(void)a;
	diag_start();
}

/*
 * The loop's timing skeleton with no USB in it: gen's sine through
 * play's exact DACC + TIOA1 configuration, capture running, ordering
 * matched to what L does once the ring primes. Observe with D: if
 * cdr7 swings, the fault needs USB to appear; if it freezes, the
 * trigger/DACC/ADC interaction is the fault.
 */
static void ha_mimic(const uint32_t *a)
{
	/*
	 * "=<dac>[,<adc>[,<nch>]]M", defaulting to 200000 for both rates
	 * and two channels - which is what this preset always did, so no
	 * recorded run moves.
	 *
	 * Settable for the reason Track B records: this is the only path
	 * in the firmware where the DAC update clock and the ADC trigger
	 * are two independent timers, so the sampling phase relative to
	 * the DAC's table wrap is a free variable fixed for a run by the
	 * instruction timing between the two starts. Giving the clocks
	 * slightly different rates walks that phase through a full period
	 * inside one capture.
	 */
	uint32_t dac_hz = a[0] ? a[0] : 200000u;
	uint32_t adc_hz = a[1] ? a[1] : dac_hz;
	unsigned nch    = a[2] ? a[2] : 2u;
	char buf[192];

	/*
	 * Everything the console has to say is said before the converters
	 * start: printing after gen_go_tioa1() would lay milliseconds of
	 * blocked main loop over the first samples of every capture this
	 * preset takes - invariant 8, on the path the suite calls its
	 * continuity control.
	 */
	/*
	 * The shape as it is. gen_shape_name() is the shared spelling, so
	 * the two tracks cannot drift on the word either.
	 */
	con_str("# mimic loop: gen "); con_str(gen_shape_name(gen_shape));
	con_str(" on TIOA1 at "); con_u32(dac_hz);
	con_str(" sps, capture "); con_u32(adc_hz);
	con_str(" Hz x"); con_u32(nch); con_str(" ch"); con_nl();
	Serial.println("# press D and read cdr7: swing = USB at fault, frozen = trigger path");
	Serial.flush();

	play_stop();
	gen_init();
	gen_prepare_tioa1(dac_hz);
	if (!stream_start_capture_only(adc_hz, nch)) {
		Serial.println("# mimic loop: refused, the ADC would not start");
		Serial.flush();
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
 * "=<n>e": the on-die temperature sensor, n conversions averaged.
 *
 * On the console as well as the control channel because a bench reading
 * wants no host, and because the two paths going through one
 * implementation is what makes them comparable. ctl_temp_t carries what
 * this may and may not be used to claim - it is an upper bound on
 * ADVREF noise, not a value, and not a temperature in degrees. Issue
 * #11.
 */
static void ha_temp(const uint32_t *a)
{
	ctl_temp_t t;
	char buf[160];

	if (acq_read_temp(&t, (uint16_t)a[0]) != CTL_TEMP_OK) {
		Serial.println("# temp: refused - a capture is armed, or no sensor here");
		Serial.flush();
		return;
	}
	con_str("# temp: code "); con_u32(t.code_x16 / 16u); con_ch('.');
	con_u32w((t.code_x16 % 16u) * 100u / 16u, 2, '0');
	con_str(" (min "); con_u32(t.code_min);
	con_str(" max ");  con_u32(t.code_max);
	con_str(", n=");   con_u32(t.samples);
	con_str(") adcmr="); con_hex32(t.adc_mr, 8);
	con_str(" adcacr="); con_hex32(t.adc_acr, 8);
	con_nl();
	Serial.flush();
}

/*
 * `l` reports; `=1l` reports and then clears. The counters are
 * cumulative so two readings give a rate over any interval the host
 * chooses - but max_cycles is a maximum, not a counter, and
 * differencing a maximum is meaningless. Clearing has to be explicit
 * rather than a side effect of reading, or two consumers of this
 * channel would silently steal each other's worst case.
 */
static void ha_load(const uint32_t *a)
{
	load_dump();
	if (a[0])
		load_clear();
}

/*
 * "=<ms>S": block the main loop, to validate that `l` sees it.
 *
 * Deliberately silent. A printf here lands in the very pass this
 * command exists to measure - 36 characters at 115200 baud is 3.1 ms -
 * and the monitor would faithfully report the stall plus the
 * announcement of it. Measured on Track B, not guessed: with the
 * message in, a 5 ms stall read 7.2 ms and a 1500 ms stall read
 * 1502.7 ms, the same 2-3 ms offset at both ends. The answer to "did it
 * work" is the load report, not an echo.
 */
static void ha_stall(const uint32_t *a)
{
	uint32_t ms = a[0] ? a[0] : 10u;
	uint32_t until;

	if (ms > 2000u)
		ms = 2000u;    /* long enough to see, short of a watchdog */

	until = millis() + ms;
	while ((int32_t)(millis() - until) < 0)
		;
}

/*
 * "=<us>K". The gap between the ADC start and the DAC start, in
 * microseconds, held across runs and applied by the M preset above.
 *
 * The states a code-layout change can draw are selected by the binary
 * and not by anything the host does. M's comment names the only free
 * variable a layout change could plausibly move, and this makes that
 * variable settable, so a hypothesis can be tested inside one image
 * instead of by flashing two. Debug-only, on a preset that is already
 * debug-only, and it busy-waits.
 */
static void ha_mimic_gap(const uint32_t *a)
{
	char buf[96];

	mimic_start_delay_us = a[0];
	con_str("# mimic start delay: "); con_u32(mimic_start_delay_us);
	con_str(" us (next M)"); con_nl();
	Serial.flush();
}

/*
 * "=<ch>,<core>I": DACC_ACR's IBCTLCHx and IBCTLDACCORE, applied at the
 * next DACC init. "=2,1I" is the Arduino core's value and the
 * datasheet's characterisation condition; 0,0 is reset, which is what
 * this project has always run. See gen.h.
 */
static void ha_ibctl(const uint32_t *a)
{
	char buf[96];

	gen_set_ibctl(a[0], a[1]);
	con_str("# dacc ibctl: ");
	con_kv_u32("ch", gen_ibctl_ch);     con_ch(' ');
	con_kv_u32("core", gen_ibctl_core);
	con_str(" (next DACC init)"); con_nl();
	Serial.flush();
}

/*
 * "=<tracktim>,<settling>A". Applied at the next acq_init(), so set it
 * before starting a stream. One image sweeps the whole range, which is
 * the only way to compare the constant rather than comparing two
 * binaries - see acq.cpp.
 */
static void ha_adc_timing(const uint32_t *a)
{
	char buf[96];

	acq_set_timing(a[0], a[1]);
	con_str("# adc timing: ");
	con_kv_u32("tracktim", acq_tracktim); con_ch(' ');
	con_kv_u32("settling", acq_settling);
	con_str(" (next stream)"); con_nl();
	Serial.flush();
}

/*
 * "=<ms>Z": a software unplug of the native port, defaulting to
 * 250 ms. Track B's main.c carries the same command with the same
 * argument and the same default.
 *
 * It exists because objective 0c - the macOS close() wedge - is
 * recoverable in software: the host is waiting on the USB pipe and
 * only a disconnect aborts that. `z` below is not a substitute; it
 * leaves the pull-up attached and the host none the wiser.
 *
 * Necessarily typed on the programming port. Detaching takes the
 * control channel down with it, since both CDC functions are on
 * this one device.
 */
static void ha_detach(const uint32_t *a)
{
	unsigned long ms = a[0] ? a[0] : 250u;

	Serial.print("# detaching the native port for ");
	Serial.print(ms);
	Serial.println(" ms");
	Serial.flush();
	usbdma_detach_cycle(a[0]);
}

/*
 * A software reset must not clear the backup domain. If the boot
 * counter still reads 1 afterwards, the counter itself is not
 * retaining and cannot be used as evidence about resets.
 */
static void ha_reset(const uint32_t *a)
{
	(void)a;
	Serial.println("# software reset now"); Serial.flush();
	RSTC->RSTC_CR = RSTC_CR_KEY(0xA5u) | RSTC_CR_PROCRST;
}

static void ha_fws(const uint32_t *a)
{
	/*
	 * An instruction-fetch-timing arm, on the oracle. Debug-only, the
	 * class invariant 7 carves out.
	 *
	 * Track B showed that changing EEFC FMR FWS - and nothing else, on
	 * one image, with no rebuild - moves both the phase and the
	 * magnitude of the sensitivity to fetch timing seen elsewhere,
	 * with the three phase sets not overlapping at all. Invariant 3
	 * keeps this track for exactly that kind of claim: two tracks are
	 * two images, so a result that reproduces on both is independent
	 * rather than a property of one build.
	 *
	 * Clamped 4..6 for the same reason as Track B: SystemInit sets 4 at
	 * MCK 78 MHz, lower reads flash faster than the part guarantees, and
	 * higher is always safe.
	 */
	uint32_t fws = a[0] ? a[0] : 4u;

	if (fws < 4u)
		fws = 4u;
	if (fws > 6u)
		fws = 6u;
	EFC0->EEFC_FMR = EEFC_FMR_FWS(fws);
	EFC1->EEFC_FMR = EEFC_FMR_FWS(fws);
	Serial.print("# fws: "); Serial.print(fws);
	Serial.print(" (fmr0=0x"); Serial.print(EFC0->EEFC_FMR, HEX);
	Serial.print(" fmr1=0x"); Serial.print(EFC1->EEFC_FMR, HEX);
	Serial.println(")");
	Serial.flush();
}

static void ha_bench(const uint32_t *a)
{
	(void)a;
	stream_bench_report();
	con_nl();
	{
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
		/* The shared prefix, then this track's own counters at the
		 * offset it hands back. usbdma_rebuilds and the two activity
		 * counters are Track A's UOTGHS DMA stack and Track B has
		 * nothing to put there - a real per-track capability, unlike
		 * the `svc` that used to sit mid-line here. */
		play_report_print(&r);
		con_str(" rebuilds=");  con_u32(usbdma_rebuilds);
		con_str(" act-in=");    con_u32(usb_in_activity);
		con_str(" act-out=");   con_u32(usb_out_activity);
		con_nl();
	}
	Serial.flush();
}

/*
 * What this track implements, in the shared surface's terms.
 *
 * A letter absent from here is answered "not implemented on this
 * track", which is the console's CTL_ERR_OPCODE. `console_missing()`
 * prints the list from this table, so the parity count is computed
 * rather than remembered - a count arrived at by diffing two
 * dispatchers by hand goes stale the first time either track moves.
 */
const console_binding_t console_bindings[] = {
	{ 'h', ha_help },       { 'v', ha_ident },      { 'p', ha_printf },
	{ 'g', ha_gpio },       { 'f', ha_fault },

	{ 'r', ha_read },       { 's', ha_sweep },      { 'x', ha_xtalk },
	{ 't', ha_ratesweep },  { 'd', ha_dac_sweep },  { 'j', ha_dac_15m },
	{ 'k', ha_dac_30m },

	{ '1', ha_s50 },        { '2', ha_s100 },       { '3', ha_s200 },
	{ '4', ha_s400 },       { '5', ha_smax },       { '0', ha_stop },
	{ '?', ha_stats },      { 'u', ha_usb },        { 'w', ha_uart_stream },
	{ 'E', ha_epstate },

	{ 'F', ha_flood },      { 'R', ha_sink },       { 'X', ha_duplex },
	{ 'G', ha_flood_dma },  { 'T', ha_sink_dma },   { 'Y', ha_duplex_dma },
	{ 'B', ha_bench },

	{ 'L', ha_loop },       { 'P', ha_play },       { 'M', ha_mimic },
	{ 'V', ha_ring },       { 'D', ha_diag },       { 'O', ha_occ },

	{ 'W', ha_wave },       { 'J', ha_sync },       { 'N', ha_layout },
	{ 'I', ha_ibctl },

	{ 'C', ha_pair },       { 'A', ha_adc_timing }, { 'e', ha_temp },

	{ 'Q', ha_profile },    { 'l', ha_load },       { 'S', ha_stall },
	{ 'K', ha_mimic_gap },  { 'Z', ha_detach },     { 'z', ha_reset },
	{ 'q', ha_fws },

	{ 0, 0 },
};

void ctl_port_sof_poll(void);

void loop()
{
	/*
	 * One DWT read at the top of every pass. Inline and branchless -
	 * see load.h for why it is the cycle counter and not micros(),
	 * which costs 869 ns against a ~4 us idle pass and would tax the
	 * loop it measures by a fifth.
	 */
	load_tick();

	/* Issue #52: one register read, extending FNUM past its 11
	 * bits. Must be more often than its 2.048 s wrap; this loop
	 * runs at ~75 k passes/s, so that is not in doubt. */
	ctl_port_sof_poll();

	static uint32_t led_usb_at;
	static uint32_t led_in_last, led_out_last;
	static uint32_t diag_ms, ctl_ms;
	uint32_t now = millis();

	stream_loop_passes++;

	/*
	 * Every pass, and unconditionally. The core enables EP4-6's
	 * interrupts at SET_CONFIGURATION and again on every bus reset,
	 * and its ISR has no case for them - an OUT packet on EP5 then
	 * raises an interrupt nothing acknowledges and the handler
	 * re-enters for ever. The board keeps enumerating, because that
	 * is all the ISR is still doing, and answers nothing else.
	 * Cheap enough to do here rather than reason about when it is
	 * needed: one register write against a storm that presents as a
	 * dead board.
	 */
	ctlusb_quiesce_interrupts();

	/*
	 * The control channel, which is also what keeps its bulk OUT
	 * drained: ctl_service() reads the endpoint and answers, fulfilling
	 * the same drain obligation as any other endpoint - an allocated
	 * bulk OUT that nobody hands back NAKs forever and hangs the host
	 * in close().
	 *
	 * At most once a millisecond, matching Track B's gate on the same
	 * call: it costs 1964 ns to poll an endpoint that receives a
	 * command ten times a second, a hundredfold faster than a host
	 * can notice, and the drain obligation above is unchanged - once
	 * a millisecond is draining, never is not. Gated here rather than
	 * inside ctl_service() because `now` is already in a register.
	 *
	 * ctl_service() and the diag sampling below are two once-a-
	 * millisecond jobs kept on *different* passes deliberately: gating
	 * both on the same `now != <last>` fires them together on the
	 * first pass of each millisecond, which then costs 15 us against
	 * the usual 10 - enough to widen the idle-loop timing distribution
	 * and break test_load.py::test_the_idle_loop_is_fast_and_uniform,
	 * which exists to keep that distribution narrow enough for one
	 * slow pass to be unmistakable. The `else` below puts each job on
	 * its own pass instead, at 1 kHz each, a hundredfold margin under
	 * the ~100 k passes/s loop rate.
	 *
	 * The sample-path OUT drain further down is NOT gated and must
	 * not be: gating it to 1 kHz would narrow it to ~2 MB/s against a
	 * host that writes ~1.8 MB/s, and that margin is the guarantee.
	 */
	if (now != ctl_ms) {
		ctl_ms = now;
		ctl_service();
	} else if (now != diag_ms) {
		diag_ms = now;
		devept_seen |= UOTGHS->UOTGHS_DEVEPT;
		usbtrace_sample(stream_loop_passes);
		devept_restore();
	}

	/* Heartbeat: if this stops, the board hung or faulted. */
	if (now - heartbeat_at >= (led_on ? 100u : 900u)) {
		led_on = !led_on;
		if (led_on)
			PIOB->PIO_SODR = LED_MASK;
		else
			PIOB->PIO_CODR = LED_MASK;
		heartbeat_at = now;
	}

	/*
	 * USB activity on the two spare LEDs: TXL lights while the IN
	 * direction moves data, RXL while OUT does. Driven from the byte
	 * and DMA-arm counters the transport already bumps, sampled at
	 * 50 ms so even a slow trickle reads as a visible flicker.
	 */
	if (now - led_usb_at >= 50u) {
		led_tx(usb_in_activity != led_in_last);
		led_rx(usb_out_activity != led_out_last);
		led_in_last = usb_in_activity;
		led_out_last = usb_out_activity;
		led_usb_at = now;
	}

	play_service();
	stream_service();
	diag_service();

	/*
	 * Playback status on bulk IN, so the host can close a rate loop
	 * on what the converter actually consumed. Ported from
	 * apps/baremetal_bringup/main.c; the record layout is a
	 * byte-for-byte copy in playstat.h, because the host parses one
	 * magic and one CRC for both tracks.
	 *
	 * Play-only: in loop mode bulk IN carries capture frames and the
	 * endpoint is on DMA, so the FIFO path must not touch it -
	 * stream_in_in_use() is the guard. The host tolerates gaps, which
	 * is what makes it safe for the TXINI test below to fail and drop
	 * a record.
	 *
	 * TXINI is the invariant 7 guard, and testing it first is what
	 * makes the write bounded. Serial_::write() -> USBD_Send() ->
	 * UDD_Send() begins with an unbounded spin on TXINI -
	 *
	 *     while (TXINI != (UOTGHS->UOTGHS_DEVEPTISR[ep] & TXINI)) {}
	 *
	 * - and availableForWrite() cannot stand in for it either: it
	 * returns the constant EPX_SIZE - 1 regardless of bank state. So a
	 * host that fed OUT and stopped draining IN fills both banks and
	 * spins this loop forever unless TXINI is checked first: a free
	 * bank then lets the spin exit immediately, and no free bank drops
	 * the record instead.
	 */
	if (play_active() && !stream_in_in_use() && SerialUSB.dtr()
	    && (UOTGHS->UOTGHS_DEVEPTISR[CDC_TX] & UOTGHS_DEVEPTISR_TXINI)) {
		static uint32_t last_stat_ms;

		if ((uint32_t)(now - last_stat_ms) >= PLAYSTAT_MS) {
			playstat_t st;

			last_stat_ms = now;
			st.magic[0] = PLAYSTAT_MAGIC0;
			st.magic[1] = PLAYSTAT_MAGIC1;
			st.magic[2] = PLAYSTAT_MAGIC2;
			st.magic[3] = PLAYSTAT_MAGIC3;
			st.version  = PLAYSTAT_VERSION;
			st.pad[0] = st.pad[1] = st.pad[2] = 0;
			st.consumed  = play_consumed;
			st.underruns = play_underruns;
			st.bytes_in  = play_bytes_in;
			st.dev_us    = micros();
			st.crc32     = frame_crc32((const uint8_t *)&st,
			                           sizeof(st) - sizeof(st.crc32));
			if (SerialUSB.write((const uint8_t *)&st, sizeof(st)))
				usb_in_activity++;
		}
	}

	/*
	 * Keep bulk OUT drained when nothing is consuming it. A CDC device
	 * that lets the pipe NAK indefinitely wedges the host: macOS's
	 * close() waits for in-flight write URBs to complete, and tcflush
	 * cannot recall a URB already at the controller, so the host process
	 * hangs in close() holding the port. The core's receive ring is only
	 * 512 bytes, so it stops accepting as soon as nothing reads it.
	 */
	if (!play_active() && !stream_out_in_use() && !usbdma_out_claimed()) {
		/*
		 * read() alone, not available() then read(). Serial_::read()
		 * returns -1 on an empty ring, so the guard the loop needs
		 * is already inside the call it was going to make anyway -
		 * and available() is the dearer of the two, doing an add and
		 * a modulo where read() compares head against tail.
		 *
		 * The drain's *throughput* is the guarantee, not just its
		 * existence - CLAUDE.md, and Track B learned it by gating
		 * this and losing the margin - so a change here has to be
		 * faster or not happen. Same 512-byte bound per pass, one
		 * call per byte instead of two.
		 */
		for (int b = 0; b < 512 && SerialUSB.read() >= 0; b++)
			;
	}

	/*
	 * One byte to the shared console. It holds the "=" argument entry
	 * across calls and answers a command this track has not bound,
	 * which is why "nothing arrived" is fed to it rather than tested
	 * for here - see lib/due_shared/src/console.c.
	 */
	/*
	 * read() alone: UARTClass::read() returns -1 on an empty ring,
	 * which is exactly the value console_feed() treats as "nothing
	 * arrived". available() was a second call to answer a question
	 * read() already answers, on every pass of the loop.
	 */
	console_feed(Serial.read());
}
