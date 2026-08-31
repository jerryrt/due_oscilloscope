/*
 * Track C: the FreeRTOS application, stage C2.
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

/* The five services, and the counters the loop keeps. The same
 * declarations Track B's main.c reaches for - invariant 4's "differ
 * only in main()" made literal. */
#include "load.h"
#include "analog.h"
#include "play.h"
#include "playstat.h"
#include "stream.h"
#include "usb_cdc.h"
#include "ctl.h"
#include "frame.h"

/*
 * Static allocation everywhere - issue #45 decision (4). Every task's
 * stack and control block is a fixed object here, so invariant 7's
 * "every buffer is fixed and known at build time" holds literally and
 * the image links no allocator at all.
 */
/* The service task carries a playstat_t and a 512-byte scrap buffer in
 * its frame, so it is not the minimal stack. */
#define SERVICE_STACK     (configMINIMAL_STACK_SIZE * 6)

static StaticTask_t service_tcb;
static StackType_t  service_stack[SERVICE_STACK];

static StaticTask_t idle_tcb;
static StackType_t  idle_stack[configMINIMAL_STACK_SIZE];
static StaticTask_t timer_tcb;
static StackType_t  timer_stack[configTIMER_TASK_STACK_DEPTH];



/*
 * The service task: Track B's main loop, verbatim, in one task.
 *
 * ================== WHY ONE TASK AND NOT FIVE =====================
 *
 * Issue #45's C2 says "the five services as tasks". This is one, and
 * the deviation is deliberate rather than a shortcut.
 *
 * C4 - the deliverable - asks whether a scheduler underneath changes
 * the timing of a data path that is otherwise byte-identical. Splitting
 * the services across tasks answers a different question, because the
 * priorities and yield points are *my* choices: a throughput difference
 * would then be the kernel, or my policy, and nothing in the
 * measurement separates them. One task running the same statements in
 * the same order isolates the kernel's own cost - the tick ISR, the
 * context save, the port layer - which is the only part that is not a
 * design decision.
 *
 * It is also the only shape that respects the loop's own constraint.
 * The bulk OUT drain below runs EVERY pass, and Track B's comment
 * prices that exactly: gating it to 1 kHz "buys 1.68 us of a 6.77 us
 * pass - and the suite went from 233 passed to 223 passed and a wedge",
 * because four banks per millisecond is ~2 MB/s of drain against a host
 * writing ~1.8 MB/s. **Its throughput is the guarantee, not its
 * existence.** A task that blocks on the 1 kHz tick cannot deliver
 * 143,000 passes a second, so any split has to keep the drain in a
 * free-running task - and a free-running task at the top priority
 * starves everything below it unless it yields, which is a policy
 * choice again.
 *
 * So: one task now as a measured baseline, and the split as a later
 * experiment against it. Raised on #45 rather than decided quietly.
 *
 * console_feed() is the last statement here for the same reason it is
 * last in Track B's loop, and it is what lets this be one task without
 * starving the console.
 */
static void service_task(void *arg)
{
	uint32_t heartbeat_at = millis();
	uint32_t led_usb_at = 0, led_in_last = 0, led_out_last = 0;
	uint32_t usb_ms = 0, ctl_ms = 0;
	bool led_state = false;

	(void)arg;
	for (;;) {
		uint32_t now;

		load_tick();
		now = millis();
		stream_loop_passes++;

		if (now - heartbeat_at >= (led_state ? 100u : 900u)) {
			led_state = !led_state;
			if (led_state)
				led_on();
			else
				led_off();
			heartbeat_at = now;
		}
		if (now - led_usb_at >= 50u) {
			led_tx(usb_in_activity != led_in_last);
			led_rx(usb_out_activity != led_out_last);
			led_in_last = usb_in_activity;
			led_out_last = usb_out_activity;
			led_usb_at = now;
		}
		if (now != usb_ms) {
			usb_ms = now;
			usb_cdc_poll();
		}
		play_service();
		stream_service();
		/*
		 * diag_service() is NOT called here, and that corrects
		 * issue #45's inventory.
		 *
		 * That issue lists "exactly five callables" as the seam -
		 * usb_cdc_poll, play_service, stream_service, diag_service,
		 * ctl_service - and I verified it by reading main.c. But
		 * diag_service is `static` in Track B's main.c and appears
		 * in no header: it is an application diagnostic (the `D`
		 * trace), not a driver service. **Four of the five are
		 * shared; the fifth is Track B's own.**
		 *
		 * Found by the linker rather than by reading, which is the
		 * point - grepping for the name found it in a *comment* in
		 * console_out.h and I took that for a declaration.
		 */

		/* Every pass. The drain's throughput is the guarantee that
		 * the pipe never NAKs indefinitely - see the note above. */
		if (!play_active() && !stream_out_in_use()) {
			static uint8_t scrap[512];

			usb_out_drain_polls++;
			for (int b = 0; b < 4; b++)
				if (usb_cdc_read(scrap, sizeof(scrap)) == 0)
					break;
		}
		if (now != ctl_ms) {
			ctl_ms = now;
			ctl_service();
		}
		if (play_active() && !stream_in_in_use()) {
			static uint32_t last_stat_ms;
			uint32_t now_ms = millis();

			if ((uint32_t)(now_ms - last_stat_ms) >= PLAYSTAT_MS) {
				playstat_t st;

				last_stat_ms = now_ms;
				st.magic[0] = PLAYSTAT_MAGIC0;
				st.magic[1] = PLAYSTAT_MAGIC1;
				st.magic[2] = PLAYSTAT_MAGIC2;
				st.magic[3] = PLAYSTAT_MAGIC3;
				st.version = PLAYSTAT_VERSION;
				st.pad[0] = st.pad[1] = st.pad[2] = 0;
				st.consumed = play_consumed;
				st.underruns = play_underruns;
				st.bytes_in = play_bytes_in;
				st.dev_us = micros();
				st.crc32 = frame_crc32((const uint8_t *)&st,
				                       sizeof(st)
				                       - sizeof(st.crc32));
				usb_cdc_write((const uint8_t *)&st, sizeof(st));
			}
		}
		console_feed(uart_getc());
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
	con_str("# due_oscilloscope :: Track C (FreeRTOS) stage C2");
	con_nl();
	con_str("#   v = identity line");        con_nl();
	con_str("#   h = this list");            con_nl();
	con_str("#   T = time source check (millis/micros)"); con_nl();
	con_str("#   1..4 = stream 50k/100k/200k/400k, 0 = stop, ? = stats");
	con_nl();
	con_str("# C2: the five services run in one task. See issue #45.");
	con_nl();
	console_flush();
}

/* Terminated by a zero key and scanned rather than indexed - the shared
 * table decides the help's order, so this one may list what it likes. */
/*
 * `T`: the time source, read twice about a millisecond apart.
 *
 * C2 groundwork rather than a convenience. millis() and micros() are
 * provided by the application on this track (apps/rtos_bringup/
 * time_rtos.c) because bsp/systick.c cannot be linked, and almost every
 * driver in the tree calls them - drivers/adc.c alone has ten sites. A
 * time source that silently returned 0, or that advanced at the wrong
 * rate, would not fail to link and would not fail to run: it would make
 * every duration C2 measures wrong, quietly.
 *
 * So it is checked on the wire before anything depends on it. Two reads
 * with a known delay between them: the delta is the measurement, and
 * the absolute values say the counter is live rather than stuck.
 */
static void c_time(const uint32_t *a)
{
	uint32_t m0, u0, m1, u1;

	(void)a;
	m0 = millis();  u0 = micros();
	vTaskDelay(pdMS_TO_TICKS(100));
	m1 = millis();  u1 = micros();

	con_str("# time ");
	con_kv_u32("millis", m1);            con_ch(' ');
	con_kv_u32("micros", u1);            con_ch(' ');
	con_kv_u32("d_ms", m1 - m0);         con_ch(' ');
	con_kv_u32("d_us", u1 - u0);
	con_str("  (asked for 100 ms)");     con_nl();
	console_flush();
}

/*
 * C2's capture surface.
 *
 * The bodies are `console_cmd_stream()` and `stream_stop()`, both
 * shared, so these are adapters and nothing else - which is the shape
 * issue #45's C-share-1 established for all 48 letters. The full
 * surface follows the same way; what is here is what C2 needs to be
 * measured against Track B.
 */
static void c_s50(const uint32_t *a)  { (void)a; console_cmd_stream(50000); }
static void c_s100(const uint32_t *a) { (void)a; console_cmd_stream(100000); }
static void c_s200(const uint32_t *a) { (void)a; console_cmd_stream(200000); }
static void c_s400(const uint32_t *a) { (void)a; console_cmd_stream(400000); }

static void c_stop(const uint32_t *a)
{
	(void)a;
	stream_stop();
	con_str("# stream stopped"); con_nl();
	console_flush();
}

static void c_stats(const uint32_t *a)
{
	(void)a;
	stream_report();
	con_nl();
	console_flush();
}

/*
 * `B`: the transport counters, and the one number C4 actually wants.
 *
 * stream_bench_report() carries `passes`, which is the service loop's
 * own iteration count. Against Track B's it is the kernel's overhead
 * expressed as the thing that matters - how much less work the sample
 * path gets done per second with a scheduler underneath it - and it is
 * the only figure that should differ between the tracks at all.
 */
static void c_bench(const uint32_t *a)
{
	(void)a;
	stream_bench_report();
	con_nl();
	console_flush();
}

/* Terminated by a zero key and scanned rather than indexed - the shared
 * table decides the help's order, so this one may list what it likes. */
const console_binding_t console_bindings[] = {
	{ 'v', c_ident },
	{ 'h', c_help  },
	{ 'T', c_time  },
	{ '0', c_stop  },
	{ '1', c_s50   },
	{ '2', c_s100  },
	{ '3', c_s200  },
	{ '4', c_s400  },
	{ '?', c_stats },
	{ 'B', c_bench },
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

	/*
	 * The same init sequence as Track B's main(), in the same order,
	 * because invariant 4 says the two builds differ only in main()
	 * and an init order is exactly the kind of difference that would
	 * make a later comparison meaningless.
	 *
	 * systick_init() is the documented no-op on this track - the
	 * kernel owns SysTick. It is called anyway so the sequence reads
	 * the same as Track B's and nobody has to notice its absence.
	 */
	led_init();
	led_aux_init();
	uart_init(115200);
	systick_init();
	load_init();
	dac_init();
	adc_init();
	usb_cdc_init();

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

	/*
	 * One task, and it never blocks - see the note on service_task().
	 * The idle task therefore runs only when the tick preempts this
	 * one, which is the bare-metal duty cycle plus the kernel's own
	 * overhead - and that overhead is exactly what C4 measures.
	 */
	xTaskCreateStatic(service_task, "svc", SERVICE_STACK, NULL,
	                  2, service_stack, &service_tcb);

	vTaskStartScheduler();

	/* Only reached if the scheduler could not start, which with static
	 * allocation means a configuration error rather than exhaustion. */
	led_blink_forever(2);
	return 0;
}
