/*
 * Track C's millisecond tick, and why it does not call FreeRTOS.
 *
 * `millis()` and `micros()` are declared in bsp/bsp.h and live in
 * bsp/systick.c for the bare-metal build. Track C cannot link that file:
 * it defines SysTick_Handler *strongly*, and FreeRTOSConfig.h routes
 * that name to the kernel's handler, so two strong definitions would be
 * a duplicate symbol rather than an override.
 *
 * So the application provides them instead, which is invariant 4's shape
 * exactly - the drivers are unchanged and only the application differs.
 *
 * The obvious implementation is `xTaskGetTickCount()`, and it is wrong
 * here for a reason that is invisible until someone turns on a debug
 * flag eighteen months from now: `drivers/acq.c:266` calls micros()
 * from inside ADC_Handler() (behind `#if ACQ_RATE_TRACE_ENABLED`,
 * default 0), and that ISR sits *above*
 * configMAX_SYSCALL_INTERRUPT_PRIORITY and may call no FreeRTOS API at
 * all - the architecture docs/rtos.md settles, and the whole reason
 * Track C is tractable without rewriting the data path. A micros()
 * that called into the kernel would put an API call in that ISR the
 * moment the flag was set, and the failure would be a corrupted
 * kernel state rather than a compile error.
 *
 * A plain volatile counter has no such hazard: readable from any
 * context, at any priority, exactly as the bare-metal one is, so the
 * drivers keep working unmodified whatever they are compiled with.
 * The tick hook is how it advances - FreeRTOS calls
 * vApplicationTickHook() from xTaskIncrementTick(), which runs in the
 * SysTick interrupt, one increment, no API, same as bsp/systick.c's
 * handler.
 *
 * The one real difference: time does not advance until the scheduler
 * starts. Bare metal calls systick_init() early in main() and
 * millis() is live from that point; here xTaskIncrementTick() only
 * runs once vTaskStartScheduler() has, so anything timed during
 * initialisation reads 0 and a duration measured across the scheduler
 * start is wrong rather than merely coarse. C2 brings up services
 * that time their own startup, and this is the first thing that will
 * bite.
 */
#include "sam.h"

#include "FreeRTOS.h"
#include "task.h"

#include "bsp.h"

static volatile uint32_t ms_ticks;

void vApplicationTickHook(void)
{
	ms_ticks++;
}

/*
 * The kernel configures and owns SysTick, so there is nothing for this
 * to do. It exists because bsp.h declares it and a driver may call it;
 * a link error would be a worse answer than a documented no-op, and
 * silently re-programming SysTick underneath the scheduler would be
 * worse than either.
 */
void systick_init(void)
{
}

uint32_t millis(void)
{
	return ms_ticks;
}

/*
 * Read the tick counter and the down-counter consistently. If the tick
 * advances between the two reads the pair is inconsistent, so retry.
 *
 * Byte-for-byte the same interpolation as bsp/systick.c, and it is
 * valid here for a reason worth stating rather than assuming: FreeRTOS
 * programmes SysTick->LOAD as configCPU_CLOCK_HZ / configTICK_RATE_HZ
 * - 1, which at 78 MHz and 1000 Hz is 77,999 - the identical value
 * systick_init() writes bare metal. Read LOAD rather than recomputing
 * it, so that if the kernel's tick rate ever changes this follows.
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
