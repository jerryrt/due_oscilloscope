/*
 * Millisecond tick with microsecond interpolation.
 *
 * SysTick belongs to the BSP in the bare-metal build. Under FreeRTOS the
 * kernel claims it instead, and SysTick_Handler is routed to
 * xPortSysTickHandler in the vector table. See docs/rtos.md.
 */

#include "sam.h"
#include "bsp.h"

static volatile uint32_t ms_ticks;

void systick_init(void)
{
	SysTick->LOAD = (SystemCoreClock / 1000u) - 1u;
	SysTick->VAL  = 0;
	SysTick->CTRL = SysTick_CTRL_CLKSOURCE_Msk
	              | SysTick_CTRL_TICKINT_Msk
	              | SysTick_CTRL_ENABLE_Msk;
}

void SysTick_Handler(void)
{
	ms_ticks++;
}

uint32_t millis(void)
{
	return ms_ticks;
}

/*
 * Read the tick counter and the down-counter consistently. If the tick
 * advances between the two reads the pair is inconsistent, so retry.
 */
uint32_t micros(void)
{
	uint32_t m, v, m2;

	do {
		m  = ms_ticks;
		v  = SysTick->VAL;
		m2 = ms_ticks;
	} while (m != m2);

	uint32_t load = SysTick->LOAD + 1u;
	uint32_t elapsed = load - v;

	return m * 1000u + (elapsed / (SystemCoreClock / 1000000u));
}
