/*
 * LED on pin 13 = PB27.
 *
 * Direct PIO register access throughout. Measured at ~69 ns per write
 * against ~2164 ns for the Arduino digitalWrite equivalent, which is why
 * instrumentation must never go through an abstraction layer.
 */

#include "sam.h"
#include "bsp.h"

#define LED_MASK (1u << 27)

void led_init(void)
{
	PMC->PMC_PCER0 = (1u << ID_PIOB);
	PIOB->PIO_PER  = LED_MASK;   /* PIO controls the pin */
	PIOB->PIO_OER  = LED_MASK;   /* output */
	PIOB->PIO_CODR = LED_MASK;   /* start off */
}

void led_on(void)     { PIOB->PIO_SODR = LED_MASK; }
void led_off(void)    { PIOB->PIO_CODR = LED_MASK; }

void led_toggle(void)
{
	if (PIOB->PIO_ODSR & LED_MASK)
		PIOB->PIO_CODR = LED_MASK;
	else
		PIOB->PIO_SODR = LED_MASK;
}

/*
 * Busy-loop blink for fault codes. Deliberately avoids SysTick: once a
 * fault has occurred nothing about the tick, the scheduler, or interrupt
 * state can be assumed.
 */
void led_blink_forever(int count)
{
	for (;;) {
		for (int i = 0; i < count; i++) {
			PIOB->PIO_SODR = LED_MASK;
			for (volatile uint32_t d = 0; d < 1500000; d++) { }
			PIOB->PIO_CODR = LED_MASK;
			for (volatile uint32_t d = 0; d < 1500000; d++) { }
		}
		for (volatile uint32_t d = 0; d < 9000000; d++) { }
	}
}
