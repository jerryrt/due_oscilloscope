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
static void identity_line(void)
{
	char buf[192];

	snprintf(buf, sizeof(buf), FW_ID_FORMAT,
	         FW_TRACK, FW_VERSION_STR, CTL_VERSION, FRAME_VERSION,
	         (unsigned long)SystemCoreClock,
	         (unsigned long)(SystemCoreClock / 4u),
	         (unsigned)ACQ_FRAME_BYTES, (unsigned)ACQ_BUF_SAMPLES,
	         __DATE__, __TIME__);
	Serial.println(buf);
}

/*
 * This track's own facts, then the shared command list.
 *
 * The list used to be twenty-eight Serial.println lines here and
 * twenty-eight more in Track B's main.c, which is how the two command
 * sets came to differ by twelve without anyone deciding they should -
 * issue #13. console_help() prints one table, so a command that exists
 * on one track and not the other now says so on both.
 *
 * The numbers stay here, where they can be computed. A shared help line
 * carrying "453488" would be a figure written down a second time.
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
	Serial.println("# commands:");
	console_help();
	Serial.println("#");
}

static void measure_printf(void)
{
	const int n = 20;
	const char *line = "0123456789012345678901234567890123456789";

	Serial.println("# measuring printf cost, 20 x 40-char lines");
	Serial.flush();

	uint32_t t0 = micros();
	for (int i = 0; i < n; i++)
		Serial.println(line);
	Serial.flush();          /* include actual transmission, not just buffering */
	uint32_t t1 = micros();

	Serial.print("# printf: ");
	Serial.print((t1 - t0) / n);
	Serial.println(" us per 40-char line (flushed to the wire)");
	Serial.println("# this is why printf never goes in an ISR");
	Serial.flush();
}

static void measure_gpio(void)
{
	const uint32_t n = 100000;

	Serial.println("# measuring GPIO toggle cost, 100k pairs");
	Serial.flush();

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

	Serial.print("# direct PIO : ");
	Serial.print(((t1 - t0) * 1000.0) / n);
	Serial.println(" ns per set+clear pair");
	Serial.print("# digitalWrite: ");
	Serial.print(((t3 - t2) * 1000.0) / n);
	Serial.println(" ns per set+clear pair");
	Serial.println("# use direct PIO writes for ISR instrumentation");
	Serial.flush();
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

	snprintf(buf, sizeof(buf),
	         "# A0(AD7) = %4u  %4lu mV    A1(AD6) = %4u  %4lu mV",
	         a0, (unsigned long)code_to_mv(a0),
	         a1, (unsigned long)code_to_mv(a1));
	Serial.println(buf);
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

		snprintf(buf, sizeof(buf),
		         "# %4u   %6lu   %6u  %5lu  |  %6lu   %6u  %5lu",
		         c, (unsigned long)code_to_mv(c), a0,
		         (unsigned long)code_to_mv(a0),
		         (unsigned long)code_to_mv(inv), a1,
		         (unsigned long)code_to_mv(a1));
		Serial.println(buf);
		Serial.flush();
	}
	Serial.println("# note: A0/A1 columns are the DAC output as actually measured");
	Serial.flush();
}

/*
 * Hold one channel's DAC fixed and swing the other; any movement in the
 * held channel is multiplexer bleed. Swinging both at once, as an
 * earlier version did, isolates nothing.
 */
/*
 * "=<n>,<ms>x": how many crosstalk observations, and how long to let a
 * DAC output settle before converting.
 *
 * The settle time is a knob because the excursion issue #16 is about
 * recurs on a fixed *cadence* rather than at random, and only moving
 * the cadence separates a beat against something periodic from a count
 * kept in software. Moving it is what measured the 64 ms period.
 *
 * Track B waited a 400,000-iteration busy loop where this waited
 * delay(10), so the same command waited different times on the two
 * tracks and their figures were not comparable. Wall clock on both now.
 */
static uint32_t crosstalk_repeats;
static uint32_t crosstalk_settle_ms;

/*
 * The settle wait, spun on micros() rather than delay().
 *
 * delay() calls yield() and snaps to the SysTick millisecond, so it is
 * neither the same duration nor the same activity as Track B's wait -
 * and issue #16 is a measurement of what happens *between* two
 * conversions, which is exactly what a differing wait changes. Two
 * instruments that disagree by a factor of three should not also
 * disagree about how they wait. Same spin as bleed_settle() in main.c.
 */
static void bleed_settle(uint32_t ms)
{
	uint32_t t0 = micros();

	while (micros() - t0 < ms * 1000u)
		{ }
}

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
 * way and does not measure the same thing, so it says which it found.
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

	snprintf(buf, sizeof(buf),
	         "# crosstalk: hold one channel, swing the other, %u times,"
	         " %lu ms settle", n, (unsigned long)ms);
	Serial.println(buf);
	Serial.println("# each arm has a control that writes the same code"
	               " twice, so the swing is the only difference");
	/*
	 * The conditions as the hardware holds them, not as this function
	 * believes it set them. Issue #16 spent a bench session on two
	 * tracks disagreeing about a bleed figure while both printed the
	 * same prose; the register is the only account that cannot drift
	 * from what was measured.
	 */
	snprintf(buf, sizeof(buf),
	         "# adcmr=%08lx (this command's own; restored after)",
	         (unsigned long)acq_mr());
	Serial.println(buf);
	Serial.flush();

	/*
	 * The pads too - main.c's twin says why (issue #16(b)): the
	 * pull-up was the dominant term of the tracks' bare-channel
	 * disagreement, and the instrument never said what the pads were
	 * configured as. On this track the Arduino core walks every pin
	 * at init and analogRead's own path can rewrite one, so the
	 * attestation matters more here, not less. PUSR reads 1 where
	 * the pull-up is DISABLED. A0=PA16, A1=PA24, A2=PA23, all PIOA.
	 */
	snprintf(buf, sizeof(buf),
	         "# pioa: psr=%08lx osr=%08lx pusr=%08lx ifsr=%08lx",
	         (unsigned long)PIOA->PIO_PSR,
	         (unsigned long)PIOA->PIO_OSR,
	         (unsigned long)PIOA->PIO_PUSR,
	         (unsigned long)PIOA->PIO_IFSR);
	Serial.println(buf);
	Serial.flush();

	/*
	 * The pair `C` selected, so issue #16's pin-versus-position test
	 * can be asked on this track too. See main.c for why `=2C` is the
	 * one variable worth moving.
	 *
	 * **Every read is the two-channel sequence, which it was not.** This
	 * called acq_read_one() and converted the watched channel with every
	 * other disabled, while Track B converted the pair. That is one
	 * difference and it was worth a sign and a factor of twelve: on
	 * `=2C` the same board minutes apart read a plateau of **+95 codes
	 * with a loud +37 control** on this track and **-1205 with a clean
	 * control** on Track B. The two were not the same measurement, so a
	 * bleed figure was not comparable across tracks - which is the class
	 * of error issue #16 exists to remove, one level up from the pin
	 * label. Same sequence on both now; the conversion preceding the
	 * watched one is the same conversion.
	 */
	const unsigned second = acq_pair_second;

	for (i = 0; i < n; i++) {
		gen_write_dac(1, 2048);
		gen_write_dac(0, 0);
		bleed_settle(ms);
		acq_read_pair(ACQ_CH_A0, second, &a0, &lo);
		gen_write_dac(0, 4095);
		bleed_settle(ms);
		acq_read_pair(ACQ_CH_A0, second, &a0, &hi);
		a1_bleed[i] = (int16_t)((int)hi - (int)lo);
		a1b_lo[i] = lo; a1b_hi[i] = hi;

		/* Same arm with nothing swung: DAC0 is written twice at the
		 * same code. Identical writes, waits and conversions, so a
		 * difference here is not crosstalk from a moving neighbour. */
		gen_write_dac(0, 2048);
		bleed_settle(ms);
		acq_read_pair(ACQ_CH_A0, second, &a0, &lo);
		gen_write_dac(0, 2048);
		bleed_settle(ms);
		acq_read_pair(ACQ_CH_A0, second, &a0, &hi);
		a1_still[i] = (int16_t)((int)hi - (int)lo);
		a1s_lo[i] = lo; a1s_hi[i] = hi;

		gen_write_dac(0, 2048);
		gen_write_dac(1, 0);
		bleed_settle(ms);
		acq_read_pair(ACQ_CH_A0, second, &lo, &a1);
		gen_write_dac(1, 4095);
		bleed_settle(ms);
		acq_read_pair(ACQ_CH_A0, second, &hi, &a1);
		a0_bleed[i] = (int16_t)((int)hi - (int)lo);
		a0b_lo[i] = lo; a0b_hi[i] = hi;

		/* And its control. */
		gen_write_dac(1, 2048);
		bleed_settle(ms);
		acq_read_pair(ACQ_CH_A0, second, &lo, &a1);
		gen_write_dac(1, 2048);
		bleed_settle(ms);
		acq_read_pair(ACQ_CH_A0, second, &hi, &a1);
		a0_still[i] = (int16_t)((int)hi - (int)lo);
		a0s_lo[i] = lo; a0s_hi[i] = hi;
	}

	/* Name the channel watched: with `=2C` these rows are about A2. */
	const char *sname = (second == ACQ_CH_A2) ? "A2" : "A1";
	char label[64];

	snprintf(label, sizeof(label), "%s bleed (DAC1 held, DAC0 swung)", sname);
	ctl_bleed_describe(buf, sizeof(buf), label, a1_bleed, n);
	Serial.println(buf);
	snprintf(label, sizeof(label), "%s bleed", sname);
	ctl_bleed_values(buf, sizeof(buf), label, a1_bleed, n);
	Serial.println(buf);
	ctl_bleed_raw(buf, sizeof(buf), label, a1b_lo, a1b_hi, n);
	Serial.println(buf);
	snprintf(label, sizeof(label), "%s control (nothing swung)", sname);
	ctl_bleed_describe(buf, sizeof(buf), label, a1_still, n);
	Serial.println(buf);
	snprintf(label, sizeof(label), "%s control", sname);
	ctl_bleed_values(buf, sizeof(buf), label, a1_still, n);
	Serial.println(buf);
	ctl_bleed_raw(buf, sizeof(buf), label, a1s_lo, a1s_hi, n);
	Serial.println(buf);
	Serial.flush();

	snprintf(label, sizeof(label),
	         "A0 bleed (DAC0 held, DAC1 swung, %s in pair)", sname);
	ctl_bleed_describe(buf, sizeof(buf), label, a0_bleed, n);
	Serial.println(buf);
	ctl_bleed_values(buf, sizeof(buf), "A0 bleed", a0_bleed, n);
	Serial.println(buf);
	ctl_bleed_raw(buf, sizeof(buf), "A0 bleed", a0b_lo, a0b_hi, n);
	Serial.println(buf);
	ctl_bleed_describe(buf, sizeof(buf),
	                   "A0 control (nothing swung)", a0_still, n);
	Serial.println(buf);
	ctl_bleed_values(buf, sizeof(buf), "A0 control", a0_still, n);
	Serial.println(buf);
	ctl_bleed_raw(buf, sizeof(buf), "A0 control", a0s_lo, a0s_hi, n);
	Serial.println(buf);

	/* Which bench this is, read rather than assumed. */
	gen_write_dac(1, 2048);
	bleed_settle(ms);
	acq_read_pair(ACQ_CH_A0, ACQ_CH_A1, &a0, &a1);
	snprintf(buf, sizeof(buf),
	         "# A1 reads %u with DAC1 held at 2048: %s", a1,
	         (a1 > 1800u && a1 < 2300u) ? "DAC1 -> A1 is fitted"
	                                    : "A1 looks undriven - see docs/noise.md");
	Serial.println(buf);
	Serial.println("# bleed is in ADC codes; 1 code = 0.8 mV. Full swing is 2747 codes.");
	Serial.println("# taken at TRACKTIM 15, SETTLING 3 - this command's own,"
	               " not whatever ADC_MR held");
	snprintf(buf, sizeof(buf),
	         "# pair-conv: restarts=%lu timeouts=%lu (nonzero: see #23)",
	         (unsigned long)acq_pair_restarts,
	         (unsigned long)acq_pair_timeouts);
	Serial.println(buf);

	acq_measure_end();
	Serial.flush();
}

/*
 * Verify that the ADC actually converts at the rate the TC was told to
 * produce. Everything downstream is sized against this number, and a
 * wrong trigger rate corrupts every later measurement while presenting
 * as an analog fault, so it is checked before anything is built on it.
 *
 * Two channels are enabled, so each trigger yields two conversions and
 * the aggregate rate is twice the trigger rate.
 */
static void cmd_rate_sweep(unsigned n_channels)
{
	/*
	 * Sweep the timer compare value rather than a frequency, so the test
	 * is independent of the master clock. An earlier version listed
	 * fixed frequencies chosen for a 42 MHz timer clock, and silently
	 * lost resolution around the cliff once MCK changed.
	 */
	static const uint32_t rcs2[] = {
		390, 100, 96, 92, 90, 88, 87, 86, 85, 84, 83, 82, 80, 78
	};
	/* One channel converts once per trigger, so its cliff sits near
	 * half the compare value. Bracketed rather than assumed. */
	static const uint32_t rcs1[] = {
		195, 50, 49, 48, 47, 46, 45, 44, 43, 42, 41, 40
	};
	const uint32_t *rcs = (n_channels == 1) ? rcs1 : rcs2;
	const unsigned n_rcs = (n_channels == 1)
	                     ? sizeof(rcs1) / sizeof(rcs1[0])
	                     : sizeof(rcs2) / sizeof(rcs2[0]);
	const uint32_t nbuf_target = 8;
	uint32_t tc_clock = SystemCoreClock / 2u;
	char buf[160];

	acq_init();

	snprintf(buf, sizeof(buf),
	         "# TC->ADC->PDC sweep, %u ch, MCK %lu Hz, ADC clk %lu Hz, min RC %lu",
	         n_channels,
	         (unsigned long)SystemCoreClock, (unsigned long)(SystemCoreClock / 4u),
	         (unsigned long)ACQ_MIN_RC_FOR(n_channels));
	Serial.println(buf);
	Serial.println("#     RC   trigger   aggregate    ratio  RXBUFF GOVRE");
	Serial.flush();

	for (unsigned i = 0; i < n_rcs; i++) {
		uint32_t hz = tc_clock / rcs[i];

		/*
		 * Rates past the measured cliff are refused rather than
		 * attempted: the ADC drops those triggers with no status bit
		 * set, so the sweep would report clean data at half the rate.
		 * The cliff itself was found before the guard existed and is
		 * recorded in docs/hardware.md.
		 */
		if (!acq_start(hz, n_channels)) {
			snprintf(buf, sizeof(buf),
			         "# %6lu %9lu           -        -       -     -"
			         "   REFUSED (RC < %lu)",
			         (unsigned long)rcs[i], (unsigned long)hz,
			         (unsigned long)ACQ_MIN_RC_FOR(n_channels));
			Serial.println(buf);
			Serial.flush();
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

		uint32_t us = t1 - t0;
		uint64_t samples = (uint64_t)got * ACQ_BUF_SAMPLES;
		uint32_t agg = us ? (uint32_t)((samples * 1000000ull) / us) : 0;
		uint32_t expect = hz * n_channels;   /* one per enabled channel */
		uint32_t ratio_x1000 = expect ?
			(uint32_t)(((uint64_t)agg * 1000ull) / expect) : 0;

		snprintf(buf, sizeof(buf),
		         "# %6lu %9lu %11lu   %2lu.%03lu %7lu %5lu",
		         (unsigned long)rcs[i], (unsigned long)hz,
		         (unsigned long)agg,
		         (unsigned long)(ratio_x1000 / 1000u),
		         (unsigned long)(ratio_x1000 % 1000u),
		         (unsigned long)acq_rxbuff_overruns,
		         (unsigned long)acq_govre);
		Serial.println(buf);
		Serial.flush();
	}
	Serial.println("# ratio 1.000 = every trigger produced a conversion pair");
	Serial.flush();
}

/*
 * The ceiling for two channels is TC compare value 86, whatever the
 * master clock: one step faster and the ADC silently drops every other
 * trigger with no status bit set. See docs/hardware.md.
 */
static void cmd_stream(uint32_t trigger_hz)
{
	char buf[128];

	if (!stream_start(trigger_hz)) {
		snprintf(buf, sizeof(buf),
		         "# refused: %lu Hz is past the measured ADC ceiling",
		         (unsigned long)trigger_hz);
		Serial.println(buf);
		Serial.flush();
		return;
	}
	snprintf(buf, sizeof(buf),
	         "# streaming: trigger %lu Hz, %lu sps aggregate, %s %lu Hz on "
	         "DAC0 (%u pts/cycle)",
	         (unsigned long)trigger_hz, (unsigned long)(trigger_hz * 2u),
	         gen_shape_name(gen_shape),
	         (unsigned long)gen_hz_for(trigger_hz, gen_points, gen_sync),
	         (unsigned)gen_points);
	Serial.println(buf);
	Serial.println(gen_sync == GEN_SYNC_OFF
	               ? "# DAC1 holds mid scale: A1 must read flat, or demux is wrong"
	               : "# DAC1 carries the sync: A1 must show a square, not the waveform");
	Serial.flush();
}

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
static void gen_report(void)
{
	char line[160];
	ctl_gen_t g;

	if (!ctl_port_gen_get(&g)) {
		Serial.println("# no generator on this track");
		Serial.flush();
		return;
	}
	ctl_gen_describe(line, sizeof(line), &g);
	Serial.print("# ");
	Serial.println(line);
	Serial.flush();
}

static void cmd_stream_uart(uint32_t trigger_hz)
{
	char buf[128];

	if (!stream_start_uart(trigger_hz)) {
		Serial.println("# refused");
		Serial.flush();
		return;
	}
	snprintf(buf, sizeof(buf),
	         "# uart-stream: trigger %lu Hz, %s %lu Hz - binary follows",
	         (unsigned long)trigger_hz, gen_shape_name(gen_shape),
	         (unsigned long)gen_hz_for(trigger_hz, gen_points, gen_sync));
	Serial.println(buf);
	Serial.flush();
}

static void cmd_stream_stats(void)
{
	char buf[192];
	int  n;

	n = stream_dma_report(buf, sizeof(buf));
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
	if (n > 0 && n < (int)sizeof(buf))
		snprintf(buf + n, sizeof(buf) - n, " adcmr=%08lx acr=%08lx",
		         (unsigned long)acq_mr(), (unsigned long)gen_acr());
	Serial.println(buf);
	stream_report(buf, sizeof(buf));
	Serial.println(buf);
	Serial.flush();
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
	char buf[144];

	gen_init();
	Serial.println("# DACC update-rate sweep, TC0 ch1 (TIOA1), TAG mode");
	Serial.println("#     want      RC   TCexact    measured    ratio");
	Serial.flush();

	for (unsigned i = 0; i < sizeof(rates) / sizeof(rates[0]); i++) {
		if (!gen_start_independent(rates[i])) {
			snprintf(buf, sizeof(buf), "# %8lu       -         -    REFUSED",
			         (unsigned long)rates[i]);
			Serial.println(buf);
			Serial.flush();
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

		snprintf(buf, sizeof(buf), "# %8lu %7lu %9lu %11lu   %2lu.%03lu",
		         (unsigned long)rates[i], (unsigned long)rc,
		         (unsigned long)tcexact, (unsigned long)measured,
		         (unsigned long)(ratio_x1000 / 1000u),
		         (unsigned long)(ratio_x1000 % 1000u));
		Serial.println(buf);
		Serial.flush();
	}
	Serial.println("# ratio 1.000 means every trigger produced a DAC update");
	Serial.flush();
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
	char buf[144];

	gen_init();
	if (!gen_start_independent(dac_hz)) {
		Serial.println("# refused");
		Serial.flush();
		return;
	}
	if (!stream_start_capture_only(200000, 2)) {
		Serial.println("# capture refused");
		Serial.flush();
		return;
	}

	snprintf(buf, sizeof(buf),
	         "# DAC indep %lu Hz (RC %lu), capture 200000 Hz",
	         (unsigned long)dac_hz, (unsigned long)gen_configured_rc());
	Serial.println(buf);
	snprintf(buf, sizeof(buf),
	         "# if the DAC truly runs at the trigger, tone = %lu Hz",
	         (unsigned long)(dac_hz / GEN_TABLE_LEN));
	Serial.println(buf);
	Serial.println("# if it saturates near 1539700, tone = 3007 Hz instead");
	Serial.flush();
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
	 * No buffer here. It used to be declared at the top, before the
	 * early return, so every idle main-loop pass paid to set up a
	 * 192-byte stack frame for a function that returns immediately -
	 * `Q` measured this at 590 ns against Track B's 115 for the same
	 * function with the same body and no buffer. That is 475 ns on a
	 * ~9 us pass, for nothing, and it is issue #13's performance
	 * parity in miniature: the tracks are transliterations, so a
	 * difference this size is a defect in one of them rather than a
	 * property of either. It lives in the reporting block below,
	 * which is the only thing that uses it.
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

		snprintf(buf, sizeof(buf),
		         "# diag: play ring base=%08lx slot=%u B nslots=%u",
		         (unsigned long)base, PLAY_BUF_BYTES, PLAY_NBUF);
		Serial.println(buf);
		Serial.println("#    ms  prod  cons endtx    svc  tpr=slot+off  tcr"
		               "  next(tag,code)  cdr7 cdr6  aprod acons");
		for (unsigned i = 0; i < DIAG_N; i++) {
			struct diag_snap *s = &diag[i];
			uint32_t off = s->tpr - base;

			snprintf(buf, sizeof(buf),
			         "# %5lu %5lu %5lu %5lu %6lu  %lu+%-4lu %4lu"
			         "  %04x(t%u,%4u)  %4u %4u  %5lu %5lu",
			         (unsigned long)(s->ms - diag[0].ms),
			         (unsigned long)s->prod, (unsigned long)s->cons,
			         (unsigned long)s->endtx, (unsigned long)s->svc,
			         (unsigned long)(off / PLAY_BUF_BYTES),
			         (unsigned long)(off % PLAY_BUF_BYTES),
			         (unsigned long)s->tcr,
			         s->next, (s->next >> 12) & 3u, s->next & 0x0fffu,
			         s->cdr7 & 0x0fffu, s->cdr6 & 0x0fffu,
			         (unsigned long)s->aprod, (unsigned long)s->acons);
			Serial.println(buf);
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

	snprintf(buf, sizeof(buf),
	         "# usb CTRL=%08lx USBE=%d OTGPADE=%d FRZCLK=%d UIMOD=%d UIDE=%d",
	         (unsigned long)ctrl,
	         (int)!!(ctrl & UOTGHS_CTRL_USBE),
	         (int)!!(ctrl & UOTGHS_CTRL_OTGPADE),
	         (int)!!(ctrl & UOTGHS_CTRL_FRZCLK),
	         (int)!!(ctrl & UOTGHS_CTRL_UIMOD),
	         (int)!!(ctrl & UOTGHS_CTRL_UIDE));
	Serial.println(buf);

	snprintf(buf, sizeof(buf),
	         "# usb DEVCTRL=%08lx DETACH=%d SPDCONF=%lu  SR=%08lx CLKUSABLE=%d",
	         (unsigned long)dctl,
	         (int)!!(dctl & UOTGHS_DEVCTRL_DETACH),
	         (unsigned long)((dctl & UOTGHS_DEVCTRL_SPDCONF_Msk) >>
	                         UOTGHS_DEVCTRL_SPDCONF_Pos),
	         (unsigned long)sr,
	         (int)!!(sr & UOTGHS_SR_CLKUSABLE));
	Serial.println(buf);

	snprintf(buf, sizeof(buf),
	         "# usb DEVIMR=%08lx DEVISR=%08lx EPT=%08lx EP0CFG=%08lx EP0ISR=%08lx",
	         (unsigned long)UOTGHS->UOTGHS_DEVIMR,
	         (unsigned long)UOTGHS->UOTGHS_DEVISR,
	         (unsigned long)UOTGHS->UOTGHS_DEVEPT,
	         (unsigned long)UOTGHS->UOTGHS_DEVEPTCFG[0],
	         (unsigned long)UOTGHS->UOTGHS_DEVEPTISR[0]);
	Serial.println(buf);

	snprintf(buf, sizeof(buf),
	         "# pmc PMC_USB=%08lx SR_LOCKU=%d SCSR=%08lx",
	         (unsigned long)PMC->PMC_USB,
	         (int)!!(PMC->PMC_SR & PMC_SR_LOCKU),
	         (unsigned long)PMC->PMC_SCSR);
	Serial.println(buf);

	snprintf(buf, sizeof(buf),
	         "# ep2(OUT) CFG=%08lx ISR=%08lx  ep3(IN) CFG=%08lx ISR=%08lx",
	         (unsigned long)UOTGHS->UOTGHS_DEVEPTCFG[2],
	         (unsigned long)UOTGHS->UOTGHS_DEVEPTISR[2],
	         (unsigned long)UOTGHS->UOTGHS_DEVEPTCFG[3],
	         (unsigned long)UOTGHS->UOTGHS_DEVEPTISR[3]);
	Serial.println(buf);

	/* The core never arms these; usbdma.cpp does. Printed in the same
	 * layout as Track B's dump so the two can be read side by side. */
	snprintf(buf, sizeof(buf),
	         "# dma ch1(OUT) CTRL=%08lx ST=%08lx  ch2(IN) CTRL=%08lx ST=%08lx",
	         (unsigned long)UOTGHS->UOTGHS_DEVDMA[1].UOTGHS_DEVDMACONTROL,
	         (unsigned long)UOTGHS->UOTGHS_DEVDMA[1].UOTGHS_DEVDMASTATUS,
	         (unsigned long)UOTGHS->UOTGHS_DEVDMA[2].UOTGHS_DEVDMACONTROL,
	         (unsigned long)UOTGHS->UOTGHS_DEVDMA[2].UOTGHS_DEVDMASTATUS);
	Serial.println(buf);

	/*
	 * The activity LEDs, so a dark indicator can be told apart from a
	 * pin the sketch never took control of. PSR bit set means PIO owns
	 * it, OSR set means it is an output, ODSR is the driven level -
	 * and these are active low, so 0 is lit.
	 */
	snprintf(buf, sizeof(buf),
	         "# leds TXL(PA21) pio=%d out=%d lit=%d   RXL(PC30) pio=%d out=%d lit=%d",
	         (int)!!(PIOA->PIO_PSR & TXL_MASK),
	         (int)!!(PIOA->PIO_OSR & TXL_MASK),
	         (int)!(PIOA->PIO_ODSR & TXL_MASK),
	         (int)!!(PIOC->PIO_PSR & RXL_MASK),
	         (int)!!(PIOC->PIO_OSR & RXL_MASK),
	         (int)!(PIOC->PIO_ODSR & RXL_MASK));
	Serial.println(buf);

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

	snprintf(buf, sizeof(buf), "# play_occ min=%lu endtx=%lu runus=%lu consumed=%lu hist=",
	         (unsigned long)play_occ_min,
	         (unsigned long)play_endtx_seen,
	         (unsigned long)play_run_us,
	         (unsigned long)play_consumed);
	Serial.print(buf);
	for (unsigned i = 0; i < PLAY_NBUF; i++) {
		snprintf(buf, sizeof(buf), "%lu%s", (unsigned long)play_occ_hist[i],
		         i + 1u < PLAY_NBUF ? "," : "");
		Serial.print(buf);
	}
	Serial.println();
	Serial.flush();

	snprintf(buf, sizeof(buf), "# play_occ_trace decim=%u n=%lu v=",
	         PLAY_OCC_DECIM, (unsigned long)play_occ_traced);
	Serial.print(buf);
	for (unsigned i = 0; i < play_occ_traced; i++) {
		snprintf(buf, sizeof(buf), "%u%s", (unsigned)play_occ_trace[i],
		         i + 1u < play_occ_traced ? "," : "");
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
		snprintf(buf, sizeof(buf), "# %-22s %6lu ns", label,  \
		         (unsigned long)(((uint64_t)(t1 - t0) * 1000ull) / n)); \
		Serial.println(buf);                                 \
		Serial.flush();                                      \
	} while (0)

	PROF("empty loop", __asm__ volatile(""));
	/*
	 * The per-pass diagnostics, profiled because issue #13 measured
	 * this loop at 75.1 k passes/s against Track B's 160.4 k and
	 * invariant 3 wants the two comparable. Each of these reads a
	 * UOTGHS register on every pass to ask about an event that
	 * happens tens of times a second - which is the exact shape of
	 * cost CLAUDE.md records Track B removing when gating ctl_service
	 * and usb_cdc_poll to 1 kHz took its idle pass from 9.72 to
	 * 6.70 us.
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
static void trigger_fault(void)
{
	Serial.println("# triggering deliberate hard fault (INVSTATE)...");
	Serial.flush();

	void (*bad)(void) = (void (*)(void))0x20000000;
	bad();

	Serial.println("# unreachable");
}

/*
 * Override the core's weak serialEventRun(), which runs after every
 * loop() and is invisible to `Q`.
 *
 * The stock one polls UARTClass::available() on **all four** hardware
 * serials - Serial, Serial1, Serial2, Serial3 - so it can dispatch a
 * serialEvent() handler. This sketch opens one of them and defines no
 * such handler, so three of those four calls ask a UART that was never
 * begun whether it has data, and the fourth duplicates what
 * console_feed() already does at the bottom of loop().
 *
 * Measured: Serial.available() is 372 ns on this board, so the stock
 * version is about 1.5 us of a 8.6 us pass - 17%, spent outside loop()
 * where the profiler cannot see it. It was found by disassembling the
 * symbol rather than by measuring, because there is no way to measure
 * it from inside the loop it sits after.
 *
 * This is issue #13's performance parity and it is also the concrete
 * case for CLAUDE.md's claim that "Arduino is an abstraction layer, not
 * a different architecture": the cost is the core's *default policy*,
 * not anything the silicon requires, and a sketch may decline it.
 *
 * Nothing is lost. serialEvent() and friends are weak empty stubs in
 * this image - the console is read by console_feed(), which is where
 * both tracks read theirs.
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
	 * boot rather than the Arduino core's.
	 *
	 * Found by #13's readback: before a stream, `?` on this track
	 * answered adcmr=10380200 - written by analogRead() inside the
	 * core, not by anything here - while Track B, which calls
	 * adc_init() in main(), answered 2f3f0100, its own. Two boards
	 * asked what their ADC is set to gave different answers while
	 * idle, and any idle measurement inherited whichever one it
	 * happened to be on. That is a confound for issue #11's
	 * temperature reading in particular, which is taken with nothing
	 * streaming.
	 *
	 * **The DAC half of that finding was wrong and is retracted
	 * here.** The idle acr=000001aa was reported as the core's too.
	 * It is not: Track B, which contains no Arduino core anywhere in
	 * the image, reads the same 000001aa at boot after its own
	 * dac_init()'s DACC_CR_SWRST. So 0x1aa is what the DACC holds
	 * when nothing has written ACR, on either track. Only the ADC
	 * half was ever a divergence.
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
/* registers are. See console.h for why the line falls there, and      */
/* issue #13 for what it cost to have the line nowhere at all.         */
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
	trigger_fault();
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
	cmd_rate_sweep(a[2] ? a[2] : 2u);
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
	cmd_stream(50000);
}

static void ha_s100(const uint32_t *a)
{
	(void)a;
	cmd_stream(100000);
}

static void ha_s200(const uint32_t *a)
{
	(void)a;
	cmd_stream(200000);
}

static void ha_s400(const uint32_t *a)
{
	(void)a;
	cmd_stream(400000);
}

/* Highest rate the ADC sustains, derived from the measured cliff at
 * RC 86. That compare value holds across master clock settings,
 * because the timer and ADC clocks scale together. */
static void ha_smax(const uint32_t *a)
{
	(void)a;
	cmd_stream((SystemCoreClock / 2u) / ACQ_MIN_RC);
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
	char buf[192];

	uint32_t dac_hz = a[0] ? a[0] : 200000u;
	uint32_t adc_hz = a[1] ? a[1] : dac_hz;
	unsigned nch    = a[2] ? a[2] : 2u;

	if (!play_start(dac_hz)) {
		snprintf(buf, sizeof(buf),
		         "# loop: DAC %lu sps refused (max %lu)",
		         (unsigned long)dac_hz, (unsigned long)((SystemCoreClock / 2u) / PLAY_MIN_RC));
		Serial.println(buf);
		Serial.flush();
		return;
	}
	if (!stream_start_capture_only(adc_hz, nch)) {
		play_stop();
		snprintf(buf, sizeof(buf),
		         "# loop: ADC %lu Hz x%u ch refused (max %lu)",
		         (unsigned long)adc_hz, nch,
		         (unsigned long)((SystemCoreClock / 2u)
		                         / ACQ_MIN_RC_FOR(nch)));
		Serial.println(buf);
		Serial.flush();
		return;
	}
	snprintf(buf, sizeof(buf),
	         "# loop: DAC %lu sps from USB, ADC %lu Hz/ch x%u ch",
	         (unsigned long)dac_hz, (unsigned long)adc_hz, nch);
	Serial.println(buf);
	Serial.println("# DAC0 carries the waveform, DAC1 holds mid scale");
	Serial.flush();
}

/* Playback with NO capture stream, to separate a fault in the DAC
 * path from an interaction between the two service loops. */
static void ha_play(const uint32_t *a)
{
	char buf[192];

	uint32_t dac_hz = a[0] ? a[0] : 200000u;

	if (play_start(dac_hz))
		snprintf(buf, sizeof(buf),
		         "# play only: DAC %lu sps from USB, no capture",
		         (unsigned long)dac_hz);
	else
		snprintf(buf, sizeof(buf),
		         "# play only: %lu sps refused (max %lu)",
		         (unsigned long)dac_hz, (unsigned long)((SystemCoreClock / 2u) / PLAY_MIN_RC));
	Serial.println(buf);
	Serial.flush();
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
	char buf2[128], ok[16];
	for (unsigned e = 0; e < 7; e++)
		ok[e] = (UOTGHS->UOTGHS_DEVEPTISR[e]
		         & UOTGHS_DEVEPTISR_CFGOK) ? '1' : '0';
	ok[7] = 0;
	snprintf(buf2, sizeof(buf2),
	         "# ep cfgok=%s reallocs=%lu cfgfail=%lu ep2=%08lx ep3=%08lx",
	         ok, (unsigned long)ctlusb_reallocs,
	         (unsigned long)ctlusb_cfg_fail,
	         (unsigned long)UOTGHS->UOTGHS_DEVEPTCFG[2],
	         (unsigned long)UOTGHS->UOTGHS_DEVEPTCFG[3]);
	Serial.println(buf2); Serial.flush();

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
		char eb[160];
		int  n = 0;
		unsigned count = 0;
		while (EndPoints[count] != 0)
			count++;
		n = snprintf(eb, sizeof(eb), "# eptab count=%u :", count);
		for (unsigned e = 0; e < 10 && n < (int)sizeof(eb) - 12; e++)
			n += snprintf(eb + n, sizeof(eb) - n, " %lu",
			              (unsigned long)EndPoints[e]);
		Serial.println(eb); Serial.flush();

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
			char cb[80];
			snprintf(cb, sizeof(cb),
			         "# usbcfg _usbConfiguration=%lu deveptseen=%08lx now=%08lx",
			         (unsigned long)_usbConfiguration,
			         (unsigned long)devept_seen,
			         (unsigned long)UOTGHS->UOTGHS_DEVEPT);
			Serial.println(cb); Serial.flush();
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
			char tb[160];
			int  tn = snprintf(tb, sizeof(tb),
			         "# usbrestore n=%lu after:",
			         (unsigned long)devept_restores);
			for (unsigned i = 0; i < devept_restores
			                  && i < DEVEPT_RESTORE_MAX; i++)
				tn += snprintf(tb + tn, sizeof(tb) - tn, " %08lx",
				               (unsigned long)devept_after[i]);
			Serial.println(tb); Serial.flush();
			snprintf(tb, sizeof(tb),
			         "# ctlout banks=%lu bytes=%lu",
			         (unsigned long)ctlusb_out_banks,
			         (unsigned long)ctlusb_out_bytes);
			Serial.println(tb); Serial.flush();
			tn = snprintf(tb, sizeof(tb),
			         "# usbsetup n=%lu dropped=%lu",
			         (unsigned long)ctlusb_setup_n,
			         (unsigned long)ctlusb_setup_drop);
			Serial.println(tb); Serial.flush();
			for (unsigned i = 0; i < ctlusb_setup_n
			                  && i < CTLUSB_SETUP_N; i++) {
				snprintf(tb, sizeof(tb),
				         "# s%02u type=%02x req=%02x val=%04x idx=%04x len=%u claimed=%u",
				         i, ctlusb_setups[i].bmRequestType,
				         ctlusb_setups[i].bRequest,
				         ctlusb_setups[i].wValue,
				         ctlusb_setups[i].wIndex,
				         ctlusb_setups[i].wLength,
				         ctlusb_setups[i].claimed);
				Serial.println(tb); Serial.flush();
			}
			snprintf(tb, sizeof(tb),
			         "# usbtrace n=%lu dropped=%lu (us pass devept devctrl cfg)",
			         (unsigned long)usbtrace_n,
			         (unsigned long)usbtrace_drop);
			Serial.println(tb); Serial.flush();
			for (unsigned i = 0; i < usbtrace_n && i < USBTRACE_N; i++) {
				snprintf(tb, sizeof(tb),
				         "# t%02u %10lu %10lu %08lx %08lx %lu",
				         i,
				         (unsigned long)usbtrace[i].us,
				         (unsigned long)usbtrace[i].pass,
				         (unsigned long)usbtrace[i].devept,
				         (unsigned long)usbtrace[i].devctrl,
				         (unsigned long)usbtrace[i].cfg);
				Serial.println(tb); Serial.flush();
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
	gen_report();
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
	gen_report();
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
	 * start. These lines used to run after gen_go_tioa1(), which lays
	 * milliseconds of blocked main loop over the first samples of
	 * every capture this preset takes - invariant 8, on the path the
	 * suite calls its continuity control.
	 */
	/*
	 * The shape as it is, not as this line used to assume - issue #9.
	 * gen_shape_name() is the shared spelling, so the two tracks
	 * cannot drift on the word either.
	 */
	snprintf(buf, sizeof(buf),
	         "# mimic loop: gen %s on TIOA1 at %lu sps, capture %lu Hz x%u ch",
	         gen_shape_name(gen_shape),
	         (unsigned long)dac_hz, (unsigned long)adc_hz, nch);
	Serial.println(buf);
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
	snprintf(buf, sizeof(buf),
	         "# temp: code %lu.%02lu (min %u max %u, n=%u) adcmr=%08lx adcacr=%08lx",
	         (unsigned long)(t.code_x16 / 16u),
	         (unsigned long)((t.code_x16 % 16u) * 100u / 16u),
	         (unsigned)t.code_min, (unsigned)t.code_max, (unsigned)t.samples,
	         (unsigned long)t.adc_mr, (unsigned long)t.adc_acr);
	Serial.println(buf);
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
 * The two states issue #5 draws are selected by the binary and not by
 * anything the host does. M's comment names the only free variable a
 * layout change could plausibly move, and this makes that variable
 * settable, so the hypothesis can be tested inside one image instead of
 * by flashing two. Debug-only, on a preset that is already debug-only,
 * and it busy-waits.
 */
static void ha_mimic_gap(const uint32_t *a)
{
	char buf[96];

	mimic_start_delay_us = a[0];
	snprintf(buf, sizeof(buf), "# mimic start delay: %lu us (next M)",
	         (unsigned long)mimic_start_delay_us);
	Serial.println(buf);
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
	snprintf(buf, sizeof(buf),
	         "# dacc ibctl: ch=%u core=%u (next DACC init)",
	         (unsigned)gen_ibctl_ch, (unsigned)gen_ibctl_core);
	Serial.println(buf);
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
	snprintf(buf, sizeof(buf),
	         "# adc timing: tracktim=%u settling=%u (next stream)",
	         (unsigned)acq_tracktim, (unsigned)acq_settling);
	Serial.println(buf);
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

static void ha_bench(const uint32_t *a)
{
	char buf[192];

	(void)a;
	stream_bench_report(buf, sizeof(buf));
	Serial.println(buf);
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
		int n = play_report_format(buf, sizeof(buf), &r);
		if (n > 0 && (unsigned)n < sizeof(buf))
			snprintf(buf + n, sizeof(buf) - n,
			         " rebuilds=%lu act-in=%lu act-out=%lu",
			         (unsigned long)usbdma_rebuilds,
			         (unsigned long)usb_in_activity,
			         (unsigned long)usb_out_activity);
	}
	Serial.println(buf); Serial.flush();
}

/*
 * What this track implements, in the shared surface's terms.
 *
 * A letter absent from here is answered "not implemented on this
 * track", which is the console's CTL_ERR_OPCODE. `console_missing()`
 * prints the list from this table, so the parity count is computed
 * rather than remembered - issue #13's 29/8/4 was arrived at by diffing
 * two dispatchers by hand, and a number arrived at that way is stale
 * the first time either track moves.
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

	{ 0, 0 },
};

void loop()
{
	/*
	 * One DWT read at the top of every pass. Inline and branchless -
	 * see load.h for why it is the cycle counter and not micros(),
	 * which costs 869 ns against a ~4 us idle pass and would tax the
	 * loop it measures by a fifth.
	 */
	load_tick();

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
	 * drained. This used to be ctlusb_drain_out(), which released the
	 * bank and discarded what was in it because nothing here spoke the
	 * protocol; ctl_service() reads the same endpoint and answers.
	 * The drain obligation is unchanged and is why this runs every
	 * pass whether or not a host is talking - an allocated bulk OUT
	 * that nobody hands back NAKs for ever.
	 */
	/*
	 * At most once a millisecond, which is the gate Track B's main.c
	 * put on the same call and for the same measured reason: it costs
	 * 1964 ns of this pass - more than stream_service() - to poll an
	 * endpoint that receives a command ten times a second, and the
	 * cost is a UOTGHS register read rather than an SRAM one.
	 *
	 * A millisecond is 100x faster than a host can notice on a status
	 * poll, and it leaves the drain with 2 KB/ms of capacity against
	 * command traffic measured in bytes. **The drain obligation is
	 * unchanged**: an allocated bulk OUT that nobody hands back NAKs
	 * for ever and hangs the host in close(). Once a millisecond is
	 * draining; never is not.
	 *
	 * Gated here rather than inside ctl_service() because `now` is
	 * already in a register, so the check is free where a second
	 * millis() would not be.
	 */
	/*
	 * Two once-a-millisecond jobs, deliberately on *different passes*.
	 *
	 * Each is a UOTGHS poll asking about an event that happens tens of
	 * times a second, and between them they were 5.2 us of a 10 us
	 * pass - issue #13's 2.14x gap against Track B, which had already
	 * gated its own equivalents.
	 *
	 * **Why the else, which is the part that is not obvious.** Gating
	 * both on `now != <last>` fires them on the same pass, the first
	 * of each millisecond, and that pass then costs 15 us against 10.
	 * At ~100 k passes/s that is 1% of passes one log2 bucket to the
	 * right - measured at 1.02% against 0.93% predicted - and
	 * test_load.py::test_the_idle_loop_is_fast_and_uniform failed on
	 * exactly that. It was right to: the instrument's value is that
	 * the idle distribution is narrow enough for one slow pass to be
	 * unmistakable, and a gate that manufactures a second mode spends
	 * that for speed.
	 *
	 * The `else` puts the diagnostics on the *second* pass of each
	 * millisecond instead. Same 1 kHz for both, neither pass carries
	 * both, and both stay inside the bucket the ungated pass is in.
	 * It needs two passes per millisecond to keep up, which at 100 k
	 * passes/s is a hundredfold margin; a loop slow enough to break
	 * that has already failed the floor assertion above it.
	 *
	 * ctl_service at 1 kHz is Track B's gate and its reasoning: it
	 * costs 1964 ns to poll an endpoint that receives a command ten
	 * times a second, a millisecond is 100x faster than a host can
	 * notice, and **the drain obligation is unchanged** - an allocated
	 * bulk OUT that nobody hands back NAKs for ever and hangs the host
	 * in close(). Once a millisecond is draining; never is not.
	 *
	 * The sample-path OUT drain further down is NOT gated and must not
	 * be: CLAUDE.md records that gating it to 1 kHz narrows it to
	 * ~2 MB/s against a host that writes ~1.8 MB/s, and that margin is
	 * the guarantee.
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
	 * Play-only, and nowhere else. In loop mode bulk IN carries
	 * capture frames and the endpoint is on DMA; the FIFO path must
	 * not touch an endpoint DMA owns. stream_in_in_use() is the
	 * guard and it is new on this track too.
	 *
	 * The host tolerates gaps: it differences whichever records
	 * arrive. That is what makes the TXINI test below safe to fail.
	 *
	 * TXINI IS THE INVARIANT 7 GUARD, AND IT USED TO BE ABSENT.
	 * This comment used to claim "SerialUSB.write returns short
	 * rather than spinning when no bank is free", and that is not
	 * true of this core. Serial_::write() calls USBD_Send() ->
	 * UDD_Send(), whose first statement is
	 *
	 *     while (TXINI != (UOTGHS->UOTGHS_DEVEPTISR[ep] & TXINI)) {}
	 *
	 * an unbounded spin, exactly as docs/hardware.md records from the
	 * same source. availableForWrite() cannot stand in for it either:
	 * it returns the constant EPX_SIZE - 1 whatever the banks are
	 * doing. So when a host fed the OUT pipe and stopped draining IN,
	 * both banks filled and the main loop spun here for ever - issue
	 * #33. Measured on linux-x1: hangs after 5.2 s of feed with no IN
	 * reader, at 1,317,888 bytes; with a reader draining IN, 15 s and
	 * 6,030,848 bytes with no stall. A stall watchdog on a TC
	 * interrupt caught the loop in this stage, with CFSR clean, which
	 * is how it was found at all - everything that could have
	 * reported it is main-loop-served and died with it.
	 *
	 * Testing TXINI first makes the write bounded: a free bank means
	 * UDD_Send's spin exits immediately, and no free bank means the
	 * record is dropped, which the host already tolerates.
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
