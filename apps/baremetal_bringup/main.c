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
#include "analog.h"

#define LED_MASK (1u << 27)

static void banner(void)
{
	printf("#\n");
	printf("# due_oscilloscope :: Track B bare-metal bring-up\n");
	printf("# built %s %s\n", __DATE__, __TIME__);
	printf("# SystemCoreClock = %lu\n", (unsigned long)SystemCoreClock);
	printf("# commands: h=help p=printf-cost g=gpio-cost f=fault\n");
	printf("#           r=read a0/a1  s=dac sweep  x=crosstalk\n");
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

static void cmd_read(void)
{
	uint16_t a0, a1;

	adc_read_pair(ADC_CH_A0, ADC_CH_A1, &a0, &a1);
	printf("# A0(AD7) = %4u  %4lu mV    A1(AD6) = %4u  %4lu mV\n",
	       a0, (unsigned long)code_to_mv(a0),
	       a1, (unsigned long)code_to_mv(a1));
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
static void cmd_crosstalk(void)
{
	uint16_t a0, a1, lo, hi;

	printf("# crosstalk: hold one channel, swing the other\n");

	/* Hold DAC1 mid scale; swing DAC0. Watch A1. */
	dac_write(1, 2048);
	dac_write(0, 0);
	for (volatile uint32_t d = 0; d < 400000u; d++) { }
	adc_read_pair(ADC_CH_A0, ADC_CH_A1, &a0, &lo);

	dac_write(0, 4095);
	for (volatile uint32_t d = 0; d < 400000u; d++) { }
	adc_read_pair(ADC_CH_A0, ADC_CH_A1, &a0, &hi);

	printf("# DAC1 held 2048: A1 = %4u (DAC0=0) -> %4u (DAC0=4095), bleed %+d codes\n",
	       lo, hi, (int)hi - (int)lo);

	/* Hold DAC0 mid scale; swing DAC1. Watch A0. */
	dac_write(0, 2048);
	dac_write(1, 0);
	for (volatile uint32_t d = 0; d < 400000u; d++) { }
	adc_read_pair(ADC_CH_A0, ADC_CH_A1, &lo, &a1);

	dac_write(1, 4095);
	for (volatile uint32_t d = 0; d < 400000u; d++) { }
	adc_read_pair(ADC_CH_A0, ADC_CH_A1, &hi, &a1);

	printf("# DAC0 held 2048: A0 = %4u (DAC1=0) -> %4u (DAC1=4095), bleed %+d codes\n",
	       lo, hi, (int)hi - (int)lo);

	printf("# bleed is in ADC codes; 1 code = 0.8 mV. Full swing is 2747 codes.\n");
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
	dac_init();
	adc_init();

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
		case 'r': cmd_read();       break;
		case 's': cmd_sweep();      break;
		case 'x': cmd_crosstalk();  break;
		default:                    break;
		}
	}
}
