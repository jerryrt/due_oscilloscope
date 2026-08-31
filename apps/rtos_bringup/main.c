/*
 * Track C: the FreeRTOS application, stage C1.
 *
 * C1 is build-and-boot only, and deliberately so. Issue #45's phasing:
 *
 *   C1  build only - the kernel as a CMake target, vector aliasing,
 *       configPRIO_BITS, an image that boots, blinks and answers `v`
 *       with its own track field. Nothing on the sample path.
 *   C2  the five services as tasks, capture only.
 *   C3  playback and the control channel.
 *   C4  the comparison docs/rtos.md asks for. C4 is the deliverable;
 *       C1-C3 are how you earn the right to measure it.
 *
 * WHAT THIS IS NOT. Track C links Track B's drivers/, bsp/ and lib/
 * unchanged, so it is not an independent programming of the silicon and
 * therefore not an oracle in invariant 3's sense. See track_id.h.
 *
 * The seam this rests on was verified before any of it was written:
 * Track B's main() drives exactly five callables - usb_cdc_poll,
 * play_service, stream_service, diag_service, ctl_service - which is
 * what makes invariant 4's "bare-metal and FreeRTOS builds link
 * identical driver code and differ only in main()" plausible rather
 * than aspirational. C2 maps those five onto tasks.
 */
#include <stdint.h>

#include "FreeRTOS.h"
#include "task.h"

#include "sam.h"          /* SystemInit, SystemCoreClock */

#include "bsp.h"
#include "clock.h"
#include "console.h"
#include "console_out.h"
#include "console_port.h" /* console_flush - the seam, not the port */
#include "track_id.h"

/*
 * Static allocation everywhere - issue #45 decision (4). Every task's
 * stack and control block is a fixed object here, so invariant 7's
 * "every buffer is fixed and known at build time" holds literally and
 * the image links no allocator at all.
 */
#define HEARTBEAT_STACK   configMINIMAL_STACK_SIZE
#define CONSOLE_STACK     (configMINIMAL_STACK_SIZE * 3)

static StaticTask_t heartbeat_tcb;
static StackType_t  heartbeat_stack[HEARTBEAT_STACK];
static StaticTask_t console_tcb;
static StackType_t  console_stack[CONSOLE_STACK];

static StaticTask_t idle_tcb;
static StackType_t  idle_stack[configMINIMAL_STACK_SIZE];
static StaticTask_t timer_tcb;
static StackType_t  timer_stack[configTIMER_TASK_STACK_DEPTH];

/*
 * The heartbeat, which under an RTOS is a different claim from the
 * bare-metal one.
 *
 * On Track B a blinking LED says "the main loop is running". Here it
 * says only "a task at this priority is being scheduled", which is
 * weaker: the scheduler can be running perfectly while a lower-priority
 * task starves. That distinction is C2's problem - issue #45 lists the
 * timer-driven heartbeat as an open question about which task, or no
 * task at all - and it is written down here so the LED is not read as
 * more than it is.
 */
static void heartbeat_task(void *arg)
{
	TickType_t last = xTaskGetTickCount();

	(void)arg;
	for (;;) {
		led_toggle();
		vTaskDelayUntil(&last, pdMS_TO_TICKS(500));
	}
}

/*
 * The console, polled from a task rather than from a superloop.
 *
 * uart_getc() returns -1 when nothing is pending, so this is a poll and
 * not a block, and the vTaskDelay is what stops it starving everything
 * below it. A blocking UART receive belongs behind a semaphore and an
 * ISR, which is C2's shape; doing it here would be the "day a driver
 * takes a semaphore" that issue #45 says stops Track C measuring the
 * kernel and starts it measuring a rewrite.
 */
static void console_task(void *arg)
{
	(void)arg;
	for (;;) {
		int c = uart_getc();

		if (c >= 0) {
			console_feed(c);
			continue;               /* drain what is already here */
		}
		vTaskDelay(pdMS_TO_TICKS(5));
	}
}

/*
 * C1's command surface, which is deliberately two letters.
 *
 * `v` is the one that matters: CLAUDE.md's rule is "ask a board what it
 * is with `v`, not with the banner", and a Track C image that cannot
 * answer it is not testable by any host tool. `h` is here so that a
 * human who types it is not met with silence.
 *
 * The full 48-letter surface arrives with the C-share work, not by
 * being copied here - copying it is precisely what issue #45 exists to
 * stop.
 */
static void c_ident(const uint32_t *a)
{
	(void)a;
	console_identity(FW_TRACK, (unsigned long)SystemCoreClock);
}

static void c_help(const uint32_t *a)
{
	(void)a;
	con_str("# due_oscilloscope :: Track C (FreeRTOS) stage C1");
	con_nl();
	con_str("#   v = identity line");        con_nl();
	con_str("#   h = this list");            con_nl();
	con_str("# C1 is build-and-boot only: no capture, no playback,");
	con_nl();
	con_str("#   no control channel. See issue #45.");
	con_nl();
	console_flush();
}

/* Terminated by a zero key and scanned rather than indexed - the shared
 * table decides the help's order, so this one may list what it likes. */
const console_binding_t console_bindings[] = {
	{ 'v', c_ident },
	{ 'h', c_help  },
	{ 0,   NULL    },
};

/*
 * An assert that blinks, because there is no debug probe on this board.
 * led_blink_forever needs no SysTick, which is what makes it safe to
 * call from a failed assertion inside the kernel.
 */
void rtos_assert_failed(const char *file, int line)
{
	taskDISABLE_INTERRUPTS();
	con_str("# ASSERT "); con_str(file);
	con_ch(':'); con_u32((uint32_t)line); con_nl();
	console_flush();
	led_blink_forever(3);
}

void vApplicationStackOverflowHook(TaskHandle_t task, char *name)
{
	(void)task;
	taskDISABLE_INTERRUPTS();
	con_str("# STACK OVERFLOW in "); con_str(name); con_nl();
	console_flush();
	led_blink_forever(4);
}

/* Static allocation makes these the kernel's way of asking us for
 * memory it would otherwise have malloc'd. */
void vApplicationGetIdleTaskMemory(StaticTask_t **tcb, StackType_t **stack,
                                   uint32_t *depth)
{
	*tcb = &idle_tcb;
	*stack = idle_stack;
	*depth = configMINIMAL_STACK_SIZE;
}

void vApplicationGetTimerTaskMemory(StaticTask_t **tcb, StackType_t **stack,
                                    uint32_t *depth)
{
	*tcb = &timer_tcb;
	*stack = timer_stack;
	*depth = configTIMER_TASK_STACK_DEPTH;
}

int main(void)
{
	SystemInit();
	clock_set_mck(MCK_MULA_DEFAULT);

	led_init();
	uart_init(115200);

	/*
	 * The identity line before the scheduler starts, not after.
	 *
	 * Issue #41's finding is that printing after starting the capture
	 * costs exactly three frames, and the rule it produced is that the
	 * banner goes first. There is no capture here yet, but the
	 * ordering is established now rather than discovered again at C2:
	 * whatever this image says about itself, it says before anything
	 * is scheduled.
	 */
	console_identity(FW_TRACK, (unsigned long)SystemCoreClock);
	console_flush();

	xTaskCreateStatic(heartbeat_task, "heartbeat", HEARTBEAT_STACK, NULL,
	                  1, heartbeat_stack, &heartbeat_tcb);
	xTaskCreateStatic(console_task, "console", CONSOLE_STACK, NULL,
	                  2, console_stack, &console_tcb);

	vTaskStartScheduler();

	/* Only reached if the scheduler could not start, which with static
	 * allocation means a configuration error rather than exhaustion. */
	led_blink_forever(2);
	return 0;
}
