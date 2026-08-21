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
 */

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
	Serial.begin(115200);
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

	if (Serial.available()) {
		switch (Serial.read()) {
		case 'h': banner();          break;
		case 'p': measure_printf();  break;
		case 'g': measure_gpio();    break;
		case 'f': trigger_fault();   break;
		default:                     break;
		}
	}
}
