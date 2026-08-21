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

#define LED_MASK (1u << 27)

static void banner(void)
{
	printf("#\n");
	printf("# due_oscilloscope :: Track B bare-metal bring-up\n");
	printf("# built %s %s\n", __DATE__, __TIME__);
	printf("# SystemCoreClock = %lu\n", (unsigned long)SystemCoreClock);
	printf("# commands: h=help p=printf-cost g=gpio-cost f=fault\n");
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

/*
 * Branch to an even address. Cortex-M3 requires the Thumb bit set in
 * every branch target, so this raises INVSTATE, which escalates to a
 * HardFault because UsageFault is not separately enabled.
 */
static void trigger_fault(void)
{
	printf("# triggering deliberate hard fault (INVSTATE)...\n");
	uart_flush();

	void (*bad)(void) = (void (*)(void))0x20000000;
	bad();

	printf("# unreachable\n");
}

int main(void)
{
	uint32_t heartbeat_at;
	int led_state = 0;

	/* WDT is enabled out of reset on this part and will reset the board
	 * roughly every 15 s if not serviced. Nothing here services it. */
	WDT->WDT_MR = WDT_MR_WDDIS;

	led_init();
	uart_init(115200);
	systick_init();

	/* Unbuffered, so output appears as it is produced rather than at
	 * flush points that would distort the printf measurement. */
	setvbuf(stdout, NULL, _IONBF, 0);

	banner();
	heartbeat_at = millis();

	for (;;) {
		uint32_t now = millis();

		if (now - heartbeat_at >= (led_state ? 100u : 900u)) {
			led_state = !led_state;
			if (led_state)
				led_on();
			else
				led_off();
			heartbeat_at = now;
		}

		int c = uart_getc();
		switch (c) {
		case 'h': banner();         break;
		case 'p': measure_printf(); break;
		case 'g': measure_gpio();   break;
		case 'f': trigger_fault();  break;
		default:                    break;
		}
	}
}
