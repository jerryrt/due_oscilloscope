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
 *   0  stop streaming
 *   ?  streaming statistics
 *
 * Loopback wiring: DAC0 -> A0, DAC1 -> A1.
 */

#include "acq.h"
#include "gen.h"
#include "stream.h"

#define LED_MASK (1u << 27)   /* pin 13 = PB27 */

static uint32_t heartbeat_at;
static bool led_on;

static void banner(void)
{
	Serial.println("#");
	Serial.println("# due_oscilloscope :: Track A bring-up oracle");
	Serial.print("# built ");
	Serial.print(__DATE__);
	Serial.print(" ");
	Serial.println(__TIME__);
	Serial.print("# SystemCoreClock = ");
	Serial.println(SystemCoreClock);
	Serial.println("# commands: h=help p=printf-cost g=gpio-cost f=fault");
	Serial.println("#           r=read a0/a1  s=dac sweep  x=crosstalk");
	Serial.println("#           t=trigger-rate sweep (TC+ADC+PDC)");
	Serial.println("#           1..5=stream 50k/100k/200k/400k/488372 Hz");
	Serial.println("#           0=stop stream   ?=stream stats");
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
static void cmd_rate_sweep(void)
{
	/* Chosen so integer division lands on consecutive RC values 90 down
	 * to 82, which is where the ADC ceiling sits. */
	static const uint32_t rates[] = {
		100000, 400000,
		466666, 471910, 477272, 482758, 488372,
		494117, 500000, 506024, 512195
	};
	const uint32_t nbuf_target = 8;
	char buf[160];

	acq_init();

	Serial.println("# TC->ADC->PDC rate sweep, 2 channels (A0=AD7, A1=AD6)");
	Serial.println("#   want      RC   TCexact   measured    ratio  RXBUFF GOVRE");
	Serial.flush();

	for (unsigned i = 0; i < sizeof(rates) / sizeof(rates[0]); i++) {
		acq_start(rates[i]);

		/* Synchronise to a buffer boundary before timing, so the
		 * measurement is not quantised by where the window happened to
		 * start. Precision then depends only on ISR latency. */
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
		uint32_t tcexact = TC_CLOCK1_HZ / rc;
		uint32_t us      = t1 - t0;

		uint64_t samples   = (uint64_t)got * ACQ_BUF_SAMPLES;
		uint32_t aggregate = us ? (uint32_t)((samples * 1000000ull) / us) : 0;
		uint32_t measured  = aggregate / 2u;   /* 2 conversions per trigger */
		uint32_t ratio_x1000 = tcexact ?
			(uint32_t)(((uint64_t)measured * 1000ull) / tcexact) : 0;

		snprintf(buf, sizeof(buf),
		         "# %7lu %7lu %9lu %10lu   %2lu.%03lu %7lu %5lu",
		         (unsigned long)rates[i], (unsigned long)rc,
		         (unsigned long)tcexact, (unsigned long)measured,
		         (unsigned long)(ratio_x1000 / 1000u),
		         (unsigned long)(ratio_x1000 % 1000u),
		         (unsigned long)acq_rxbuff_overruns,
		         (unsigned long)acq_govre);
		Serial.println(buf);
		Serial.flush();
	}
	Serial.println("# ratio 1.000 means every trigger produced a conversion pair");
	Serial.flush();
}

/*
 * 488372 Hz is the measured ceiling for two channels: one step faster
 * and the ADC silently drops every other trigger with no status bit set.
 * See docs/hardware.md.
 */
static void cmd_stream(uint32_t trigger_hz)
{
	char buf[128];

	stream_start(trigger_hz);
	snprintf(buf, sizeof(buf),
	         "# streaming: trigger %lu Hz, %lu sps aggregate, sine %lu Hz on DAC0",
	         (unsigned long)trigger_hz, (unsigned long)(trigger_hz * 2u),
	         (unsigned long)gen_sine_hz(trigger_hz));
	Serial.println(buf);
	Serial.println("# DAC1 holds mid scale: A1 must read flat, or demux is wrong");
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
	pinMode(LED_BUILTIN, OUTPUT);
	analogWriteResolution(12);
	analogReadResolution(12);
	Serial.begin(115200);
	SerialUSB.begin(0);          /* native port; CDC ignores baud */
	while (!Serial && millis() < 2000) { }
	banner();
	heartbeat_at = millis();
}

void loop()
{
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

	stream_service();

	if (Serial.available()) {
		switch (Serial.read()) {
		case 'h': banner();          break;
		case 'p': measure_printf();  break;
		case 'g': measure_gpio();    break;
		case 'f': trigger_fault();   break;
		case 'r': cmd_read();        break;
		case 's': cmd_sweep();       break;
		case 'x': cmd_crosstalk();   break;
		case 't': cmd_rate_sweep();  break;
		case '1': cmd_stream(50000);   break;
		case '2': cmd_stream(100000);  break;
		case '3': cmd_stream(200000);  break;
		case '4': cmd_stream(400000);  break;
		case '5': cmd_stream(488372);  break;
		case '0': stream_stop(); Serial.println("# stream stopped");
		          Serial.flush();      break;
		case '?': cmd_stream_stats();  break;
		default:                     break;
		}
	}
}
