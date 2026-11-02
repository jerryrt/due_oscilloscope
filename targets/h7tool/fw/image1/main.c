/* Image 1: no USB, no clocks, no TVCC. Beeps the buzzer on PG1 (high = on,
 * schematic) briefly each cycle and drives the run LED on PI8
 * (low = on, from the public source; polarity unconfirmed on this
 * unit) and loops. The core stays on its reset clock (HSI). */
#include <stdint.h>

#define RCC_AHB4ENR  (*(volatile uint32_t *)0x58024540u)
#define GPIOI_MODER  (*(volatile uint32_t *)0x58022000u)
#define GPIOI_BSRR   (*(volatile uint32_t *)0x58022018u)
#define LED_PIN      8u
#define GPIOG_MODER (*(volatile uint32_t *)0x58021800u)
#define GPIOG_BSRR  (*(volatile uint32_t *)0x58021818u)
#define BUZ_PIN      1u
#define GPIOH_MODER (*(volatile uint32_t *)0x58021C00u)
#define GPIOH_BSRR  (*(volatile uint32_t *)0x58021C18u)
#define BUZH_PIN     9u

extern uint32_t _estack, _sidata, _sdata, _edata, _sbss, _ebss;

static void spin(volatile uint32_t n) { while (n--) { } }

static void default_handler(void) { for (;;) { } }

void Reset_Handler(void)
{
	uint32_t *s = &_sidata, *d = &_sdata;
	while (d < &_edata) *d++ = *s++;
	for (d = &_sbss; d < &_ebss; ) *d++ = 0;

	RCC_AHB4ENR |= (1u << 8) | (1u << 7) | (1u << 6); /* GPIOI, GPIOH, GPIOG clocks */
	(void)RCC_AHB4ENR;
	GPIOI_MODER = (GPIOI_MODER & ~(3u << (LED_PIN * 2))) | (1u << (LED_PIN * 2));

	GPIOG_MODER = (GPIOG_MODER & ~(3u << (BUZ_PIN * 2))) | (1u << (BUZ_PIN * 2));
	GPIOH_MODER = (GPIOH_MODER & ~(3u << (BUZH_PIN * 2))) | (1u << (BUZH_PIN * 2));

	for (;;) {
		GPIOI_BSRR = 1u << (LED_PIN + 16);     /* low  = on  */
		GPIOG_BSRR = 1u << BUZ_PIN;            /* buzzer on (high) */
		GPIOH_BSRR = 1u << BUZH_PIN;           /* same, board-id 0x42x0/0x4460 pin (stock) */
		spin(400000u);
		GPIOG_BSRR = 1u << (BUZ_PIN + 16);     /* buzzer off */
		GPIOH_BSRR = 1u << (BUZH_PIN + 16);
		spin(3600000u);
		GPIOI_BSRR = 1u << LED_PIN;            /* high = off */
		spin(4000000u);
	}
}

__attribute__((section(".isr_vector"), used))
void (*const vectors[])(void) = {
	(void (*)(void))&_estack,
	Reset_Handler,
	default_handler, default_handler, default_handler, default_handler,
};
