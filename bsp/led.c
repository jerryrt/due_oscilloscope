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

/*
 * The Due's two other SAM3X-driven LEDs: TXL on PA21 and RXL on PC30,
 * both active low. Repurposed as USB activity indicators - TXL for the
 * IN direction (device to host), RXL for OUT (host to device) - since
 * nothing here drives the UART lines they were named after.
 */
#define TXL_MASK (1u << 21)   /* PA21 */
#define RXL_MASK (1u << 30)   /* PC30 */

void led_aux_init(void)
{
	PMC->PMC_PCER0 = (1u << ID_PIOA) | (1u << ID_PIOC);
	PIOA->PIO_PER = TXL_MASK;
	PIOA->PIO_OER = TXL_MASK;
	PIOA->PIO_SODR = TXL_MASK;   /* active low: start off */
	PIOC->PIO_PER = RXL_MASK;
	PIOC->PIO_OER = RXL_MASK;
	PIOC->PIO_SODR = RXL_MASK;
}

void led_tx(int on)
{
	if (on)
		PIOA->PIO_CODR = TXL_MASK;
	else
		PIOA->PIO_SODR = TXL_MASK;
}

void led_rx(int on)
{
	if (on)
		PIOC->PIO_CODR = RXL_MASK;
	else
		PIOC->PIO_SODR = RXL_MASK;
}

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
