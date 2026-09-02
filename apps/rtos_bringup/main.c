/*
 * Track C: the FreeRTOS application, stage C2.
 *
 * C1 is build-and-boot only, and deliberately so:
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
#include "gen.h"
#include "play.h"
#include "playstat.h"
#include "stream.h"
#include "usb_cdc.h"
#include "clockref.h"
#include "ctl.h"
#include "frame.h"

/*
 * Static allocation everywhere. Every task's stack and control block
 * is a fixed object here, so invariant 7's "every buffer is fixed and
 * known at build time" holds literally and the image links no
 * allocator at all.
 */
/* The service task carries a playstat_t and a 512-byte scrap buffer in
 * its frame, so it is not the minimal stack. The console task runs the
 * command bodies, some of which are register dumps with their own
 * locals. */
#define SERVICE_STACK     (configMINIMAL_STACK_SIZE * 6)
#define CONSOLE_STACK     (configMINIMAL_STACK_SIZE * 6)

static StaticTask_t service_tcb;
static StackType_t  service_stack[SERVICE_STACK];
static StaticTask_t console_tcb;
static StackType_t  console_stack[CONSOLE_STACK];

/*
 * Set by the console task around a command, read by the service task.
 *
 * The service task free-runs and never blocks, which is what keeps the
 * bulk OUT drain at full throughput - and a task that never blocks also
 * never lets a lower-priority one run. So it yields, but only while
 * there is console work: `volatile` and one word, written by one task
 * and read by the other, so no lock is needed and none is taken on the
 * sample path.
 */
static volatile uint32_t console_busy;

static StaticTask_t idle_tcb;
static StackType_t  idle_stack[configMINIMAL_STACK_SIZE];
static StaticTask_t timer_tcb;
static StackType_t  timer_stack[configTIMER_TASK_STACK_DEPTH];



/*
 * The service task: Track B's main loop, verbatim, in one task - not
 * split into the five services it runs, deliberately.
 *
 * C4 asks whether a scheduler underneath changes the timing of a data
 * path that is otherwise byte-identical. Splitting the services
 * across tasks would answer a different question, since the
 * priorities and yield points become policy choices of their own: a
 * throughput difference would then be the kernel, or the policy, with
 * nothing in the measurement to separate them. One task running the
 * same statements in the same order isolates the kernel's own cost -
 * the tick ISR, the context save, the port layer - which is the only
 * part that is not a design decision.
 *
 * It is also the only shape that respects the loop's own constraint:
 * the bulk OUT drain below runs EVERY pass (see Track B's main.c -
 * gating it to 1 kHz cost the suite several failures and a wedge, for
 * about 2 MB/s of drain against a host writing ~1.8 MB/s), and a task
 * that blocks on a tick cannot deliver that. So the drain has to stay
 * in a free-running task, and a free-running task at the top priority
 * starves everything below it unless it yields, which is a policy
 * choice again.
 *
 * One task now, as a measured baseline; a split is a later experiment
 * against it. console_feed() is the last statement here for the same
 * reason it is last in Track B's loop, and it is what lets this be
 * one task without starving the console.
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
			clockref_poll();
		}
		play_service();
		stream_service();
		/*
		 * diag_service() is deliberately not called here: it is
		 * `static` in Track B's main.c and appears in no header,
		 * so it is Track B's own application diagnostic (the `D`
		 * trace) rather than a shared driver service.
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
		/*
		 * The whole reason for two tasks: Track B calls
		 * console_feed() inline and pays for it - a console command
		 * runs *inside* the loop, so a long print stops the sample
		 * path dead for its duration. A scheduler fixes that by
		 * construction, and without changing when output reaches
		 * the wire (test_banner_order depends on that ordering).
		 *
		 * So the console lives in a lower-priority task and this one
		 * yields to it only while there is work: idle, nothing yields
		 * and the drain runs at full rate; busy, this task gives up a
		 * tick at a time and the sample path keeps running while the
		 * print takes as long as the UART takes.
		 *
		 * uart_rx_ready() is one register read and is the cheapest
		 * question that answers "is anything about to happen".
		 */
		if (console_busy || uart_rx_ready())
			vTaskDelay(1);
	}
}

/*
 * The console: everything that prints, at a priority the sample path
 * outranks.
 *
 * console_feed() dispatches the command bodies, so putting it here puts
 * every console print here with it - which is the point. Nothing in
 * this task touches sample data, and the acquisition ISR sits above
 * configMAX_SYSCALL_INTERRUPT_PRIORITY, so neither this task's priority
 * nor any critical section it takes can delay a conversion.
 */
static void console_task(void *arg)
{
	(void)arg;
	for (;;) {
		int c = uart_getc();

		if (c < 0) {
			console_busy = 0;
			vTaskDelay(1);
			continue;
		}
		/* Raised before the dispatch and cleared only when the
		 * input has drained, so a multi-line command keeps the
		 * service task yielding for its whole duration rather
		 * than for the first byte of it. */
		console_busy = 1;
		console_feed(c);
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
 * being copied here.
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

/*
 * `y`: the time source, read twice about a millisecond apart. Picked
 * to avoid colliding with Track B's own bindings (`T` and `k` are
 * both taken).
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
 * C2's capture surface. The bodies are `console_cmd_stream()` and
 * `stream_stop()`, both shared, so these are adapters and nothing
 * else. What is here is what C2 needs to be measured against Track B.
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
 * `M` and `=<n>q`: instruments for the DAC/ADC-timing displacement
 * mechanism (docs/awg.md), and the reason Track C carries them at all.
 *
 * Track C's driver objects are byte-identical `.text` to Track B's -
 * acq, adc, dac, gen, play, stream, usb_cdc, all of them - and its
 * layout is completely different, because `main()` is. Same compiler,
 * same machine code, different arrangement: comparing Track C against
 * Track B isolates layout from codegen, which comparing Track A
 * against Track B cannot, since those differ in both at once.
 *
 * Both bodies are copied from Track B's h_mimic and h_fws rather than
 * shared, and that is debt: they belong behind the console seam like
 * the rate sweep now is.
 */
static void c_fws(const uint32_t *a)
{
	uint32_t fws = a[0] ? a[0] : 4u;

	if (fws < 4u)
		fws = 4u;
	if (fws > 6u)
		fws = 6u;
	EFC0->EEFC_FMR = EEFC_FMR_FWS(fws);
	EFC1->EEFC_FMR = EEFC_FMR_FWS(fws);
	con_str("# fws: "); con_u32(fws);
	con_str(" (fmr0="); con_hex32(EFC0->EEFC_FMR, 8);
	con_str(" fmr1="); con_hex32(EFC1->EEFC_FMR, 8);
	con_ch(')'); con_nl();
	console_flush();
}

static void c_mimic(const uint32_t *a)
{
	uint32_t dac_hz = a[0] ? a[0] : 200000u;
	uint32_t adc_hz = a[1] ? a[1] : dac_hz;
	unsigned nch    = a[2] ? a[2] : 2u;

	/* Banner before the starts, for the reason Track B's carries:
	 * ~7 ms of blocked loop laid over the first samples otherwise. */
	con_str("# mimic loop: gen "); con_str(gen_shape_name(gen_shape));
	con_str(" on TIOA1 at "); con_u32(dac_hz);
	con_str(" sps, capture "); con_u32(adc_hz);
	con_str(" Hz"); con_nl();
	console_flush();
	play_stop();
	gen_init();
	gen_prepare_tioa1(dac_hz);
	if (!stream_start_capture_only(adc_hz, nch)) {
		con_str("# mimic loop: refused, the ADC would not start");
		con_nl();
		console_flush();
		return;
	}
	gen_go_tioa1();
}

static void c_play(const uint32_t *a)
{
	console_cmd_play(a[0] ? a[0] : 200000u);
}

static void c_loop(const uint32_t *a)
{
	console_cmd_loop(a[0] ? a[0] : 200000u,
	                 a[1] ? a[1] : (a[0] ? a[0] : 200000u),
	                 a[2] ? a[2] : 2u);
}

/*
 * `z` and `Z`, both verbatim from Track B. An absent letter here must
 * error like CTL_ERR_OPCODE does on the control channel - never
 * return cleanly as a no-op - so a caller can tell "not implemented"
 * from "nothing happened" (see CLAUDE.md).
 */
static void c_reset(const uint32_t *a)
{
	(void)a;
	con_str("# software reset now"); con_nl();
	console_flush();
	RSTC->RSTC_CR = RSTC_CR_KEY(0xA5u) | RSTC_CR_PROCRST;
}

static void c_detach(const uint32_t *a)
{
	con_str("# detaching the native port for ");
	con_u32(a[0] ? a[0] : 250u); con_str(" ms"); con_nl();
	console_flush();
	usb_cdc_detach_cycle(a[0]);
}

/* Track B's `T`, verbatim - same driver call, same line on the wire. */
static void c_sink_dma(const uint32_t *a)
{
	(void)a;
	stream_sink_dma_start();
	con_str("# sink: OUT via DMA"); con_nl();
	console_flush();
}

/*
 * `u`: the control channel's own counters, for the defect where
 * Track C loses the link after a fixed number of transactions.
 *
 * ctl_dump() is shared (lib/due_shared/src/ctl.c) and prints frames,
 * bad, txdrop, the parser state and the ping sequence - which between
 * them say whether the device stopped receiving, stopped answering, or
 * answered into a pipe nobody drained.
 */
static void c_usb(const uint32_t *a)
{
	(void)a;
	/* Matches Track B's `u`: usb_cdc_dump() then ctl_dump(). */
	usb_cdc_dump();
	ctl_dump();
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
	{ 'T', c_sink_dma },
	{ 'P', c_play },
	{ 'L', c_loop },
	{ 'z', c_reset },
	{ 'Z', c_detach },
	{ 'y', c_time  },
	{ 'v', c_ident },
	{ 'h', c_help  },
	{ '0', c_stop  },
	{ '1', c_s50   },
	{ '2', c_s100  },
	{ '3', c_s200  },
	{ '4', c_s400  },
	{ '?', c_stats },
	{ 'B', c_bench },
	{ 'u', c_usb   },
	{ 'M', c_mimic },
	{ 'q', c_fws   },
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

	/* WDT is enabled out of reset on this part and resets the board
	 * roughly every 15 s if not serviced; FreeRTOS does not service
	 * it either. Disabled here, in the same place Track B does. */
	WDT->WDT_MR = WDT_MR_WDDIS;

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
	clockref_init();

	/*
	 * The identity line before the scheduler starts, not after -
	 * establishing that ordering now, before C2 needs it: whatever
	 * this image says about itself, it says before anything is
	 * scheduled.
	 */
	console_identity(FW_TRACK, (unsigned long)SystemCoreClock);
	console_flush();

	/*
	 * Two tasks, split on the DEADLINE boundary rather than the
	 * service boundary: the sample path has one and the console does
	 * not, which is the only distinction the hardware forces. The
	 * service task never blocks (see the note on service_task()), so
	 * the idle task runs only when the tick preempts it, and that
	 * overhead is exactly what C4 measures.
	 */
	xTaskCreateStatic(service_task, "svc", SERVICE_STACK, NULL,
	                  3, service_stack, &service_tcb);
	xTaskCreateStatic(console_task, "con", CONSOLE_STACK, NULL,
	                  1, console_stack, &console_tcb);

	vTaskStartScheduler();

	/* Only reached if the scheduler could not start, which with static
	 * allocation means a configuration error rather than exhaustion. */
	led_blink_forever(2);
	return 0;
}
