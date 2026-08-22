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

#include "clock.h"
#include "bootlog.h"
#include "acq.h"
#include "gen.h"
#include "stream.h"
#include "play.h"
#include "usbdma.h"

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

static void banner(void)
{
	Serial.println("#");
	Serial.println("# due_oscilloscope :: Track A bring-up oracle");
	Serial.print("# built ");
	Serial.print(__DATE__);
	Serial.print(" ");
	Serial.println(__TIME__);
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
	Serial.println("# commands: h=help p=printf-cost g=gpio-cost f=fault");
	Serial.println("#           r=read a0/a1  s=dac sweep  x=crosstalk");
	Serial.println("#           t=trigger-rate sweep (TC+ADC+PDC)");
	Serial.print("#           1..5=stream 50k/100k/200k/400k Hz, 5=max in-spec (");
	Serial.print((SystemCoreClock / 2u) / ACQ_MIN_RC);
	Serial.println(")");
	Serial.println("#           0=stop everything   ?=stream stats");
	Serial.println("#           w=stream over UART   u=usb registers");
	Serial.println("#           F=flood IN  R=sink OUT  X=duplex  B=bench stats");
	Serial.println("#           G/T/Y = the same three via endpoint DMA");
	Serial.println("#           L=full loop HOST->DAC->ADC->HOST");
	Serial.println("#           P=play only  V=ring dump  D=loop diagnostic");
	Serial.println("#           =<dac>[,<adc>[,<nch>]] before L/P/t: rates, channels");
	Serial.println("#           M=mimic loop without USB (gen sine on TIOA1 + capture)");
	Serial.println("#           d=DAC max update-rate sweep");
	Serial.println("#           j/k=DAC 1.5M/3.0M indep + capture 200k");
	Serial.println("#           z=software reset (tests GPBR retention)");
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
	uint16_t a0 = analogRead(A0);
	uint16_t a1 = analogRead(A1);
	char buf[96];

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

		analogWrite(DAC0, c);
		analogWrite(DAC1, inv);
		delay(5);

		uint16_t a0 = analogRead(A0);
		uint16_t a1 = analogRead(A1);

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
static void cmd_crosstalk(void)
{
	char buf[128];
	uint16_t lo, hi;

	Serial.println("# crosstalk: hold one channel, swing the other");

	analogWrite(DAC1, 2048);
	analogWrite(DAC0, 0);
	delay(10);
	lo = analogRead(A1);
	analogWrite(DAC0, 4095);
	delay(10);
	hi = analogRead(A1);
	snprintf(buf, sizeof(buf),
	         "# DAC1 held 2048: A1 = %4u (DAC0=0) -> %4u (DAC0=4095), bleed %+d codes",
	         lo, hi, (int)hi - (int)lo);
	Serial.println(buf);

	analogWrite(DAC0, 2048);
	analogWrite(DAC1, 0);
	delay(10);
	lo = analogRead(A0);
	analogWrite(DAC1, 4095);
	delay(10);
	hi = analogRead(A0);
	snprintf(buf, sizeof(buf),
	         "# DAC0 held 2048: A0 = %4u (DAC1=0) -> %4u (DAC1=4095), bleed %+d codes",
	         lo, hi, (int)hi - (int)lo);
	Serial.println(buf);

	Serial.println("# bleed is in ADC codes; 1 code = 0.8 mV. Full swing is 2747 codes.");
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
	         "# streaming: trigger %lu Hz, %lu sps aggregate, sine %lu Hz on DAC0",
	         (unsigned long)trigger_hz, (unsigned long)(trigger_hz * 2u),
	         (unsigned long)gen_sine_hz(trigger_hz));
	Serial.println(buf);
	Serial.println("# DAC1 holds mid scale: A1 must read flat, or demux is wrong");
	Serial.flush();
}

/*
 * Stream over the programming-port UART. Bandwidth-limited: 115200 baud
 * carries about 11.5 kB/s, so 2 kHz of trigger (2 channels, 2 bytes) at
 * 8 kB/s fits with margin. ASCII output must stay silent while this
 * runs, since frames and logs share the one port here.
 */
static void cmd_stream_uart(uint32_t trigger_hz)
{
	char buf[128];

	if (!stream_start_uart(trigger_hz)) {
		Serial.println("# refused");
		Serial.flush();
		return;
	}
	snprintf(buf, sizeof(buf),
	         "# uart-stream: trigger %lu Hz, sine %lu Hz - binary follows",
	         (unsigned long)trigger_hz,
	         (unsigned long)gen_sine_hz(trigger_hz));
	Serial.println(buf);
	Serial.flush();
}

static void cmd_stream_stats(void)
{
	char buf[192];

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
	char buf[192];

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
	banner();
	heartbeat_at = millis();
}

void loop()
{
	static uint32_t rate_arg[3];
	static unsigned rate_idx;
	static bool     rate_entry;
	static uint32_t led_usb_at;
	static uint32_t led_in_last, led_out_last;
	char buf[192];

	stream_loop_passes++;

	/* Heartbeat: if this stops, the board hung or faulted. */
	uint32_t now = millis();
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
	 * Keep bulk OUT drained when nothing is consuming it. A CDC device
	 * that lets the pipe NAK indefinitely wedges the host: macOS's
	 * close() waits for in-flight write URBs to complete, and tcflush
	 * cannot recall a URB already at the controller, so the host process
	 * hangs in close() holding the port. The core's receive ring is only
	 * 512 bytes, so it stops accepting as soon as nothing reads it.
	 */
	if (!play_active() && !stream_out_in_use() && !usbdma_out_claimed()) {
		for (int b = 0; b < 512 && SerialUSB.available() > 0; b++)
			(void)SerialUSB.read();
	}

	if (!Serial.available())
		return;

	int c = Serial.read();

	/*
	 * Rate arguments: "=<dac>[,<adc>]" typed before a command letter.
	 * The '=' introducer keeps bare digits working as the stream
	 * presets; while an entry is open, digits and one comma are
	 * argument text. The next command letter consumes the arguments and
	 * closes the entry.
	 */
	if (c == '=') {
		rate_arg[0] = rate_arg[1] = rate_arg[2] = 0;
		rate_idx = 0;
		rate_entry = true;
		return;
	}
	if (rate_entry && c >= '0' && c <= '9') {
		rate_arg[rate_idx] = rate_arg[rate_idx] * 10u + (uint32_t)(c - '0');
		return;
	}
	if (rate_entry && c == ',' && rate_idx < 2) {
		rate_idx++;
		return;
	}
	rate_entry = false;

	switch (c) {
	case 'h': banner();          break;
	case 'p': measure_printf();  break;
	case 'g': measure_gpio();    break;
	case 'f': trigger_fault();   break;
	case 'r': cmd_read();        break;
	case 's': cmd_sweep();       break;
	case 'x': cmd_crosstalk();   break;
	case 't': cmd_rate_sweep(rate_arg[2] ? rate_arg[2] : 2u); break;
	case 'd': cmd_dac_sweep();   break;
	case 'j': cmd_dac_crosscheck(1500000); break;
	case 'k': cmd_dac_crosscheck(3000000); break;
	case '1': cmd_stream(50000);   break;
	case '2': cmd_stream(100000);  break;
	case '3': cmd_stream(200000);  break;
	case '4': cmd_stream(400000);  break;
	/* Highest rate the ADC sustains, derived from the measured cliff at
	 * RC 86. That compare value holds across master clock settings,
	 * because the timer and ADC clocks scale together. */
	case '5': cmd_stream((SystemCoreClock / 2u) / ACQ_MIN_RC); break;
	case '0': stream_stop(); play_stop();
	          Serial.println("# stream stopped");
	          Serial.flush();      break;
	case '?': cmd_stream_stats();  break;
	case 'u': cmd_usb_dump();      break;
	case 'w': cmd_stream_uart(2000); break;
	case 'F': stream_flood_start(); state_log("bench=flood(IN)");
	          Serial.println("# flood: IN only");
	          Serial.flush(); break;
	case 'R': stream_sink_start(); state_log("bench=sink(OUT)");
	          Serial.println("# sink: OUT only, send data now");
	          Serial.flush(); break;
	case 'X': stream_duplex_start(); state_log("bench=duplex");
	          Serial.println("# duplex: IN and OUT together");
	          Serial.flush(); break;
	/*
	 * The same three over UOTGHS endpoint DMA. The Arduino core never
	 * programs a DMA channel itself; these take the bulk endpoints away
	 * from it and drive the controller directly, which is what makes
	 * the two tracks comparable on the transport as well as the
	 * converters.
	 */
	case 'G': stream_flood_dma_start(); state_log("bench=flood-dma");
	          Serial.println("# flood: IN via DMA");
	          Serial.flush(); break;
	case 'T': stream_sink_dma_start(); state_log("bench=sink-dma");
	          Serial.println("# sink: OUT via DMA, send data now");
	          Serial.flush(); break;
	case 'Y': stream_duplex_dma_start(); state_log("bench=duplex-dma");
	          Serial.println("# duplex: IN+OUT via DMA");
	          Serial.flush(); break;
	/*
	 * The complete loop: the host supplies the waveform, the DAC emits
	 * it, the jumper carries it to the ADC, and the capture comes back
	 * over the same USB pipe. Both directions run at once, which is the
	 * target configuration.
	 *
	 * "=<dac>[,<adc>]L"; one number sets both, none means 200k.
	 */
	case 'L': {
		uint32_t dac_hz = rate_arg[0] ? rate_arg[0] : 200000u;
		uint32_t adc_hz = rate_arg[1] ? rate_arg[1] : dac_hz;
		unsigned nch    = rate_arg[2] ? rate_arg[2] : 2u;

		if (!play_start(dac_hz)) {
			snprintf(buf, sizeof(buf), "# loop: DAC %lu sps refused",
			         (unsigned long)dac_hz);
			Serial.println(buf);
			Serial.flush();
			break;
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
			break;
		}
		snprintf(buf, sizeof(buf),
		         "# loop: DAC %lu sps from USB, ADC %lu Hz/ch x%u ch",
		         (unsigned long)dac_hz, (unsigned long)adc_hz, nch);
		Serial.println(buf);
		Serial.println("# DAC0 carries the waveform, DAC1 holds mid scale");
		Serial.flush();
		break;
	}
	/* Playback with NO capture stream, to separate a fault in the DAC
	 * path from an interaction between the two service loops. */
	case 'P': {
		uint32_t dac_hz = rate_arg[0] ? rate_arg[0] : 200000u;

		if (play_start(dac_hz))
			snprintf(buf, sizeof(buf),
			         "# play only: DAC %lu sps from USB, no capture",
			         (unsigned long)dac_hz);
		else
			snprintf(buf, sizeof(buf), "# play only: %lu sps refused",
			         (unsigned long)dac_hz);
		Serial.println(buf);
		Serial.flush();
		break;
	}
	case 'Q': cmd_profile();  break;
	case 'V': play_dump();    break;
	case 'D': diag_start();   break;
	/*
	 * The loop's timing skeleton with no USB in it: gen's sine through
	 * play's exact DACC + TIOA1 configuration, capture running, ordering
	 * matched to what L does once the ring primes. Observe with D: if
	 * cdr7 swings, the fault needs USB to appear; if it freezes, the
	 * trigger/DACC/ADC interaction is the fault.
	 */
	case 'M':
		play_stop();
		gen_init();
		gen_prepare_tioa1(200000u);
		if (!stream_start_capture_only(200000u, 2)) {
			Serial.println("# mimic: capture refused");
			Serial.flush();
			break;
		}
		gen_go_tioa1();
		Serial.println("# mimic loop: gen sine on TIOA1 at 200000 sps, capture 200000 Hz");
		Serial.println("# press D and read cdr7: swing = USB at fault, frozen = trigger path");
		Serial.flush();
		break;
	/*
	 * A software reset must not clear the backup domain. If the boot
	 * counter still reads 1 afterwards, the counter itself is not
	 * retaining and cannot be used as evidence about resets.
	 */
	case 'z': Serial.println("# software reset now"); Serial.flush();
	          RSTC->RSTC_CR = RSTC_CR_KEY(0xA5u) | RSTC_CR_PROCRST;
	          break;
	case 'B': stream_bench_report(buf, sizeof(buf));
	          Serial.println(buf);
	          snprintf(buf, sizeof(buf),
	                   "# play: in=%lu produced=%lu consumed=%lu under=%lu "
	                   "isr=%lu endtx=%lu svc=%lu rebuilds=%lu "
	                   "act-in=%lu act-out=%lu",
	                   (unsigned long)play_bytes_in,
	                   (unsigned long)play_produced,
	                   (unsigned long)play_consumed,
	                   (unsigned long)play_underruns,
	                   (unsigned long)play_isr_calls,
	                   (unsigned long)play_endtx_seen,
	                   (unsigned long)play_svc_calls,
	                   (unsigned long)usbdma_rebuilds,
	                   (unsigned long)usb_in_activity,
	                   (unsigned long)usb_out_activity);
	          Serial.println(buf); Serial.flush(); break;
	default:                     break;
	}

	/* A dispatched command consumes any rate arguments. */
	rate_arg[0] = rate_arg[1] = rate_arg[2] = 0;
	rate_idx = 0;
}
