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
#include "clock.h"
#include "analog.h"
#include "acq.h"
#include "gen.h"
#include "stream.h"
#include "frame.h"
#include "clockref.h"
#include "play.h"
#include "play_report.h"
#include "playstat.h"
#include "ctl.h"
#include "console_out.h"
#include "console.h"          /* the shared command surface */
#include "ctl_port.h"   /* ctl_port_gen_get: the console reads the
                            * generator through the same hook the control
                            * channel does, so the two cannot disagree */
#include "load.h"
#include "diag.h"
#include "usb_cdc.h"
#include "track_id.h"
#include "fw_version.h"


/*
 * One line saying which firmware this is. Same format on both tracks -
 * see version.h - so a host reads one regular expression rather than
 * matching the banner's prose, and so a board can be identified without
 * paying for the banner (89 ms of blocked main loop, invariant 8). `v`
 * prints exactly this and nothing else.
 */
/*
 * The line itself is console_identity() in lib/due_shared: its format
 * and argument order are what measure.parse_identity reads, so they
 * are wire contract with one home. FW_TRACK and the clock are this
 * track's to supply.
 */
static void identity_line(void)
{
	console_identity(FW_TRACK, (unsigned long)SystemCoreClock);
}

/*
 * This track's own facts, then the shared command list -
 * console_help() prints one table, so a command missing on one track
 * says so on both. Numbers are computed here rather than written as
 * literals, so a help line can't drift from what the hardware does.
 */
static void banner(void)
{
	con_str("#"); con_nl();
	con_str("# due_oscilloscope :: Track B bare-metal bring-up"); con_nl();
	identity_line();
	con_str("# SystemCoreClock = "); con_u32(SystemCoreClock);
	con_str("  ADC clk = ");         con_u32(SystemCoreClock / 4u);
	con_str(" (max 20000000)");      con_nl();
	con_str("# max in-spec trigger = ");
	con_u32((SystemCoreClock / 2u) / ACQ_MIN_RC);
	con_str(" Hz (RC "); con_u32(ACQ_MIN_RC);
	con_str("); presets 1..4 are 50k/100k/200k/400k"); con_nl();
	con_str("# h for the command list"); con_nl();
	con_str("#"); con_nl();
}

/*
 * `h`: the facts, then the list. Split because boot prints the banner
 * and `h` is typed - the list costs UART time the main loop is not
 * draining bulk OUT for (invariant 8), so boot pays only for the
 * identity it has to print.
 */
static void cmd_help(void)
{
	banner();
	con_str("# commands:"); con_nl();
	console_help();
	con_str("#"); con_nl();
}

/* The M preset's ADC-start-to-DAC-start gap. See case 'K'. */
static uint32_t mimic_start_delay_us;



/*
 * console_gen_report() and console_cmd_stream() are shared -
 * lib/due_shared/src/console_cmds.c. This track supplies
 * console_port_stream_start() below.
 */

/*
 * Where the main loop's time goes, in ns per call. The DMA benches
 * re-arm at most one transfer per main-loop pass, so the cost of a
 * pass is a throughput ceiling, not a curiosity. All three tracks
 * carry the command so the loops can be compared directly.
 *
 * The list is this track's; the harness - the count, the timing and
 * the row format - is console.h's CONSOLE_PROFILE(). See there for why
 * a shared list would have to be the union of three loops and would
 * report zeros for the rows a track does not run.
 */
static void cmd_profile(void)
{
	console_profile_begin();

	CONSOLE_PROFILE("empty loop", __asm__ volatile(""));
	CONSOLE_PROFILE("millis()", (void)millis());
	CONSOLE_PROFILE("micros()", (void)micros());
	/*
	 * load_tick() is measured by the same command that condemned
	 * micros(). It runs on every pass of this loop, so if it ever
	 * stops being negligible here it has stopped being an instrument
	 * and started being part of what it measures. The count it adds
	 * while profiling is deliberate: the profile is not a normal pass
	 * and it should be visible in the histogram as one.
	 */
	CONSOLE_PROFILE("load_tick()", load_tick());
	CONSOLE_PROFILE("usb_cdc_ready()", (void)usb_cdc_ready());
	CONSOLE_PROFILE("usb_dma_out_busy()", (void)usb_dma_out_busy());
	CONSOLE_PROFILE("usb_cdc_poll()", usb_cdc_poll());
	CONSOLE_PROFILE("clockref_poll()", clockref_poll());
	CONSOLE_PROFILE("play_service()", play_service());
	CONSOLE_PROFILE("stream_service()", stream_service());
	CONSOLE_PROFILE("diag_service()", diag_service());
	CONSOLE_PROFILE("ctl_service()", ctl_service());
	{
		static uint8_t scratch[64];

		/* Split out because ctl_service() measured 2141 ns while
		 * doing nothing, which is more than stream_service(). The
		 * question is whether the cost is the endpoint read or the
		 * wrapper around it, and guessing has a poor record here. */
		CONSOLE_PROFILE("usb_ctl_read()",
		                (void)usb_ctl_read(scratch, sizeof(scratch)));
	}

	console_profile_end();
}

/*
 * `S`'s per-track half: this track has one loop and the handler runs
 * inside it, so blocking here blocks exactly what the load monitor
 * measures. The clamp, the reason the command exists and the reason it
 * prints nothing are all in console_cmd_stall().
 *
 * Busy-waits on millis() rather than sleeping: the point is to occupy
 * the loop, which is exactly what a wedged pass does.
 */
void console_port_stall(uint32_t ms)
{
	uint32_t until = millis() + ms;

	while ((int32_t)(millis() - until) < 0)
		;
}

/*
 * Branch to an even address. The Cortex-M3 requires the Thumb bit set
 * in every branch target, so this raises INVSTATE, which escalates to
 * a HardFault because UsageFault is not separately enabled.
 */
/* console_trigger_fault() is shared - lib/due_shared/src/console_cmds.c */

/*
 * The command layer.
 *
 * The *surface* - which letters are commands, what arguments they
 * take, what `h` prints, and what happens to a letter this track has
 * not got - is lib/due_shared/src/console.c, compiled by both tracks.
 * Everything below is this track's handlers, where the registers are.
 *
 * Parsing and execution stay separated because the native port also
 * carries a binary framed protocol (docs/control-protocol.md) with a
 * different parser, and both reach the same handlers - so there is
 * only one implementation of "start playback" to drift.
 */

static void h_help(const uint32_t *a)  { (void)a; cmd_help(); }
static void h_ident(const uint32_t *a) { (void)a; identity_line(); }
static void h_printf(const uint32_t *a){ (void)a; console_cmd_printf_cost(); }
static void h_gpio(const uint32_t *a)  { (void)a; console_cmd_gpio_cost(); }
static void h_fault(const uint32_t *a) { (void)a; console_trigger_fault(); }
static void h_read(const uint32_t *a)  { (void)a; console_cmd_read(); }
static void h_sweep(const uint32_t *a) { (void)a; console_cmd_dac_sweep_dc(); }
static void h_xtalk(const uint32_t *a)
{
	console_cmd_crosstalk(a[0], a[1]);
}
static void h_ratesweep(const uint32_t *a)
{
	console_cmd_rate_sweep(a[2]);
}
static void h_dac_sweep(const uint32_t *a) { (void)a; console_cmd_dac_rate_sweep(); }
static void h_dac_15m(const uint32_t *a)   { (void)a; console_cmd_dac_crosscheck(1500000); }
static void h_dac_30m(const uint32_t *a)   { (void)a; console_cmd_dac_crosscheck(3000000); }
static void h_epstate(const uint32_t *a)   { (void)a; usb_cdc_endpoint_state(); }

static void h_s50(const uint32_t *a)  { (void)a; console_cmd_stream(50000); }
static void h_s100(const uint32_t *a) { (void)a; console_cmd_stream(100000); }
static void h_s200(const uint32_t *a) { (void)a; console_cmd_stream(200000); }
static void h_s400(const uint32_t *a) { (void)a; console_cmd_stream(400000); }
/*
 * The top preset is derived, not written down: the highest rate the
 * ADC sustains follows from the measured cliff at RC 86, and that
 * compare value holds across master clock settings because the timer
 * and the ADC clock scale together.
 */
static void h_smax(const uint32_t *a)
{
	(void)a;
	console_cmd_stream((SystemCoreClock / 2u) / ACQ_MIN_RC);
}

static void h_stop(const uint32_t *a)
{
	(void)a;
	stream_stop();
	play_stop();
	con_str("# stream stopped"); con_nl();
	uart_flush();
}

static void h_stats(const uint32_t *a) { (void)a; stream_report(); }
static void h_usb(const uint32_t *a)   { (void)a; usb_cdc_dump(); ctl_dump(); }
static void h_uart_stream(const uint32_t *a) { (void)a; console_cmd_stream_uart(2000); }

static void h_flood(const uint32_t *a)
{
	(void)a;
	stream_flood_start();
	con_str("# flood: IN only"); con_nl();
	uart_flush();
}

static void h_sink(const uint32_t *a)
{
	(void)a;
	stream_sink_start();
	con_str("# sink: OUT only"); con_nl();
	uart_flush();
}

static void h_duplex(const uint32_t *a)
{
	(void)a;
	stream_duplex_start();
	con_str("# duplex: IN and OUT together"); con_nl();
	uart_flush();
}

static void h_flood_dma(const uint32_t *a)
{
	(void)a;
	stream_flood_dma_start();
	con_str("# flood: IN via DMA"); con_nl();
	uart_flush();
}

static void h_sink_dma(const uint32_t *a)
{
	(void)a;
	stream_sink_dma_start();
	con_str("# sink: OUT via DMA"); con_nl();
	uart_flush();
}

static void h_duplex_dma(const uint32_t *a)
{
	(void)a;
	stream_duplex_dma_start();
	con_str("# duplex: IN+OUT via DMA"); con_nl();
	uart_flush();
}

/*
 * The complete loop: the host supplies the waveform, the DAC emits it,
 * the jumper carries it to the ADC, and the capture comes back over the
 * same USB pipe. Both directions run at once, which is the target
 * configuration.
 */
static void h_loop(const uint32_t *a)
{
	console_cmd_loop(a[0] ? a[0] : 200000u,
	                 a[1] ? a[1] : (a[0] ? a[0] : 200000u),
	                 a[2] ? a[2] : 2u);
}

/* Playback with NO capture stream, to separate a fault in the DAC path
 * from an interaction between the two service loops. */
static void h_play(const uint32_t *a)
{
	console_cmd_play(a[0] ? a[0] : 200000u);
}

static void h_profile(const uint32_t *a) { (void)a; cmd_profile(); }

/*
 * `l` reports; `=1l` reports and then clears. The counters are
 * cumulative so two readings give a rate over any interval the host
 * chooses - but max_cycles is a maximum, not a counter, and
 * differencing a maximum is meaningless. Clearing has to be explicit
 * rather than a side effect of reading, or two consumers of this
 * channel would silently steal each other's worst case.
 */
static void h_load(const uint32_t *a)
{
	load_dump();
	if (a[0])
		load_clear();
}

static void h_stall(const uint32_t *a) { console_cmd_stall(a[0]); }

/*
 * A software unplug of the native port. `z` is a processor reset only -
 * RSTC_CR_PROCRST leaves the UOTGHS running and its pull-up attached,
 * so the host never sees a disconnect and a wedged close() is not
 * released by it. This is the one that detaches.
 */
static void h_detach(const uint32_t *a)
{
	con_str("# detaching the native port for ");
	con_u32(a[0] ? a[0] : 250u); con_str(" ms"); con_nl();
	uart_flush();
	usb_cdc_detach_cycle(a[0]);
}

static void h_fws(const uint32_t *a)
{
	/*
	 * A debug-only knob in the class invariant 7 carves out - Q, l,
	 * the sweeps - never on the deployed path. Varies flash wait
	 * states to probe the instruction-fetch-timing mechanism behind
	 * the DAC displacement finding in docs/awg.md.
	 *
	 * Clamped to 4..6. SystemInit sets 4 for MCK 78 MHz; going lower
	 * would read flash faster than the part guarantees, which is a way
	 * to crash rather than an experiment. Higher is always safe: more
	 * wait states are slower and never wrong.
	 */
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
}

/*
 * Software reset. The test suite holds the control port open for a
 * whole session, because opening it asserts NRSTB and costs a reset
 * plus a native-port re-glob every time; this is how it recovers a
 * wedged device without giving that up.
 */
static void h_reset(const uint32_t *a)
{
	(void)a;
	con_str("# software reset now"); con_nl();
	uart_flush();
	RSTC->RSTC_CR = RSTC_CR_KEY(0xA5u) | RSTC_CR_PROCRST;
}

static void h_ring(const uint32_t *a) { (void)a; play_dump(); }
static void h_diag(const uint32_t *a) { (void)a; diag_start(); }

/*
 * "=<us>K". The gap between the ADC start and the DAC start, in
 * microseconds, held across runs and applied by the M preset.
 *
 * gen sits on TIOA1 while the ADC sits on TIOA0, so the sampling
 * phase relative to the DAC table's wrap is fixed for a run by the
 * instruction timing between the two starts - a different flash
 * layout is a different number of instructions there. This makes
 * that gap settable, so the effect can be probed inside one image
 * instead of by flashing two.
 *
 * Debug-only, on a preset that is already debug-only, and it
 * busy-waits.
 */
static void h_mimic_gap(const uint32_t *a)
{
	mimic_start_delay_us = a[0];
	con_str("# mimic start delay: "); con_u32(mimic_start_delay_us);
	con_str(" us (next M)"); con_nl();
	uart_flush();
}

/*
 * The loop's timing skeleton with no USB in it: gen's flash sine
 * through play's exact DACC + TIOA1 configuration, capture running,
 * ordering matched to what L does once the ring primes. Observe with D:
 * if cdr7 swings, the fault needs USB to appear; if it freezes, the
 * trigger/DACC/ADC interaction is the fault.
 */
static void h_mimic(const uint32_t *a)
{
	/*
	 * "=<dac>[,<adc>]M", defaulting to 200000 for both.
	 *
	 * Settable because this is the only path where the DAC update
	 * clock and the ADC trigger are two independent timers -
	 * gen_prepare_tioa1() selects TIOA1 where every other path leaves
	 * the DACC on the ADC's TIOA0. That makes the sampling phase
	 * relative to the DAC's table wrap a free variable, fixed for a
	 * run by the instruction timing between the two starts.
	 *
	 * Giving the two clocks slightly different rates walks that phase
	 * through a full period within one capture, so one run samples
	 * the whole phase space instead of whichever point it happened
	 * to start at.
	 */
	uint32_t dac_hz = a[0] ? a[0] : 200000u;
	uint32_t adc_hz = a[1] ? a[1] : dac_hz;
	/*
	 * "=<dac>,<adc>,<nch>M". Three channels puts the impedance arm on
	 * A2 into the same capture as A1 and the sine on A0, so the arms
	 * are matched inside one run instead of compared across runs.
	 */
	unsigned nch    = a[2] ? a[2] : 2u;

	/*
	 * Everything the console has to say is said before the converters
	 * start - invariant 8, since UART time here lands over the first
	 * samples of every capture this preset takes.
	 */
	/*
	 * The shape as it is, via gen_shape_name() - the shared spelling,
	 * so the banner cannot claim a shape the table doesn't hold.
	 */
	con_str("# mimic loop: gen "); con_str(gen_shape_name(gen_shape));
	con_str(" on TIOA1 at "); con_u32(dac_hz);
	con_str(" sps, capture "); con_u32(adc_hz);
	con_str(" Hz"); con_nl();
	con_str("# press D and read cdr7: swing = USB at fault, frozen = trigger path"); con_nl();
	uart_flush();
	play_stop();
	gen_init();
	gen_prepare_tioa1(dac_hz);
	/*
	 * Checked: an unhandled refusal here is silent otherwise - gen
	 * still runs, the banner above has already claimed a capture, and
	 * the host reads an empty stream from a device that reported
	 * success.
	 */
	if (!stream_start_capture_only(adc_hz, nch)) {
		con_str("# mimic loop: refused, the ADC would not start"); con_nl();
		uart_flush();
		return;
	}
	if (mimic_start_delay_us) {
		uint32_t t0 = micros();
		while (micros() - t0 < mimic_start_delay_us)
			;
	}
	gen_go_tioa1();
}

/*
 * "=<n>C": which channel pairs with A0 in a two-channel capture, 1 for
 * A1 and 2 for A2. It is how source impedance is told apart from
 * conversion slot - see acq_set_pair().
 */
static void h_pair(const uint32_t *a)
{
	acq_set_pair(a[0]);
	con_str("# capture pair: A0 + A");
	con_u32(acq_pair_second == ADC_CH_A2 ? 2u : 1u);
	con_str(" (next 2ch stream)"); con_nl();
	uart_flush();
}

/*
 * "=<n>N": generator layout, 0 normal, 1 swapped, 2 two-cycle, 3
 * all-DC. Rebuilt now and again by gen_init(), which M calls. See gen.h
 * for what each arm is for.
 */
static void h_layout(const uint32_t *a)
{
	static const char *const names[] = {
		"normal: sine DAC0, DC DAC1",
		"swapped: DC DAC0, sine DAC1",
		"two-cycle: two sine periods per wrap",
		"all-DC: no sine on either",
	};

	gen_set_layout(a[0]);
	con_str("# gen layout "); con_u32(gen_layout);
	con_str(" = "); con_str(names[gen_layout]); con_nl();
	uart_flush();
}

/*
 * "=<shape>,<points>W": the internal generator's waveform.
 *
 * shape 0 sine, 1 square, 2 ramp, 3 triangle, 4 DC. points is the
 * resolution - how many table points one cycle spends - and rounds down
 * to a power of two in 2..256, because those are the only counts that
 * divide the table without leaving a partial cycle at the PDC wrap.
 * Omitting it keeps the current value.
 *
 * Resolution is a frequency knob and the report says so: the update
 * rate is the trigger's, so halving the points halves the time a cycle
 * takes and doubles the output frequency, at the cost of a coarser
 * staircase. That trade is the whole reason it is exposed - see gen.h.
 *
 * Rebuilt now and again by gen_init(), which M calls.
 */
static void h_wave(const uint32_t *a)
{
	gen_set_shape(a[0]);
	if (a[1])
		gen_set_points(a[1]);
	/* "=<shape>,<pts>,<amp>W". amp in 1/256ths of full scale, about
	 * mid, so a small waveform still moves the converter every update
	 * without spanning its range - which is what lets a scope come up
	 * ten times in the vertical. Omitting it keeps the current
	 * amplitude. */
	if (a[2])
		gen_set_amp(a[2]);
	console_gen_report();
}

/*
 * "=<n>J": the sync output, 0 off, 1 per cycle, 2 per table wrap.
 *
 * A trigger for the bench, on whichever DAC pin is not carrying the
 * waveform. Triggering a scope on the signal itself divides the pin's
 * ~20 mV of noise by the waveform's slew rate at the trigger level,
 * which is why a ramp shakes 27 us and a square does not shake at all -
 * docs/awg.md. A full-scale sync edge makes that term vanish, and it
 * cannot drift against the waveform because one PDC stream and one
 * trigger feed both.
 *
 * The scope's EXT input tops out at 1.2 V here and the DAC sits at
 * 0.52-2.82 V, so AC-couple the trigger or it will never fire.
 */
static void h_sync(const uint32_t *a)
{
	gen_set_sync(a[0]);
	/* "=<mode>,<amp>J". The sync's own swing, in 256ths, so a
	 * full-scale square on the pin next to the signal can be shrunk
	 * and the disturbance it may be causing tested rather than argued
	 * about. */
	if (a[1])
		gen_set_sync_amp(a[1]);
	console_gen_report();
}

/*
 * "=<ch>,<core>I": DACC_ACR's IBCTLCHx and IBCTLDACCORE, applied at the
 * next DACC init. "=2,1I" is the Arduino core's value and the
 * datasheet's characterisation condition; 0,0 is reset, which is what
 * this project has always run. See gen.c.
 */
static void h_ibctl(const uint32_t *a)
{
	gen_set_ibctl(a[0], a[1]);
	con_str("# dacc ibctl: ");
	con_kv_u32("ch", gen_ibctl_ch);     con_ch(' ');
	con_kv_u32("core", gen_ibctl_core);
	con_str(" (next DACC init)"); con_nl();
	uart_flush();
}

/*
 * "=<tracktim>,<settling>A". Applied at the next acq_init(), so set it
 * before starting a stream. One image sweeps the whole range, which is
 * the only way to compare the constant rather than comparing two
 * binaries - see acq.c.
 */
static void h_adc_timing(const uint32_t *a)
{
	acq_set_timing(a[0], a[1]);
	con_str("# adc timing: ");
	con_kv_u32("tracktim", acq_tracktim); con_ch(' ');
	con_kv_u32("settling", acq_settling);
	con_str(" (next stream)"); con_nl();
	uart_flush();
}

/*
 * "=<n>e": the on-die temperature sensor, n conversions averaged.
 *
 * On the console as well as the control channel because a bench reading
 * wants no host, and because the two paths going through one
 * implementation is what makes them comparable. ctl_temp_t carries what
 * this may and may not be used to claim - it is an upper bound on
 * ADVREF noise, not a value, and not a temperature in degrees.
 */
static void h_temp(const uint32_t *a)
{
	ctl_temp_t t;

	if (adc_read_temp(&t, (uint16_t)a[0]) != CTL_TEMP_OK) {
		con_str("# temp: refused - a capture is armed, or no sensor here"); con_nl();
		uart_flush();
		return;
	}
	con_str("# temp: code "); con_u32(t.code_x16 / 16u); con_ch('.');
	con_u32w((t.code_x16 % 16u) * 100u / 16u, 2, '0');
	con_str(" (min "); con_u32(t.code_min);
	con_str(" max ");  con_u32(t.code_max);
	con_str(", n=");   con_u32(t.samples);
	con_str(") adcmr="); con_hex32(t.adc_mr, 8);
	con_str(" adcacr="); con_hex32(t.adc_acr, 8);
	con_nl();
	uart_flush();
}

static void h_bench(const uint32_t *a)
{
	(void)a;
	stream_bench_report();
	{
		play_report_t r = {
			.bytes_in   = play_bytes_in,
			.produced   = play_produced,
			.consumed   = play_consumed,
			.underruns  = play_underruns,
			.isr_calls  = play_isr_calls,
			.endtx_seen = play_endtx_seen,
			.svc_calls  = play_svc_calls,
			.spans      = play_spans,
			.partial    = play_partial,
			.occ_min    = play_occ_min,
		};
		play_report_print(&r);
		con_nl();
	}
	uart_flush();
}

/*
 * The occupancy histogram, off the `B` path deliberately. `B` is polled
 * mid-stream by the daemon and must stay one short line; this is 32
 * buckets and belongs where `V` already lives, which is between runs.
 */
static void h_occ(const uint32_t *a) { (void)a; console_cmd_occ_hist(); }

/*
 * What this track implements, in the shared surface's terms. A letter
 * absent from here is answered "not implemented on this track" - the
 * console's CTL_ERR_OPCODE - and console_missing() prints the list
 * from this table rather than from anyone's memory.
 */
const console_binding_t console_bindings[] = {
	{ 'h', h_help },        { 'v', h_ident },       { 'p', h_printf },
	{ 'g', h_gpio },        { 'f', h_fault },

	{ 'r', h_read },        { 's', h_sweep },       { 'x', h_xtalk },
	{ 't', h_ratesweep },   { 'd', h_dac_sweep },   { 'j', h_dac_15m },
	{ 'k', h_dac_30m },

	{ '1', h_s50 },         { '2', h_s100 },        { '3', h_s200 },
	{ '4', h_s400 },        { '5', h_smax },        { '0', h_stop },
	{ '?', h_stats },       { 'u', h_usb },         { 'w', h_uart_stream },
	{ 'E', h_epstate },

	{ 'F', h_flood },       { 'R', h_sink },        { 'X', h_duplex },
	{ 'G', h_flood_dma },   { 'T', h_sink_dma },    { 'Y', h_duplex_dma },
	{ 'B', h_bench },

	{ 'L', h_loop },        { 'P', h_play },        { 'M', h_mimic },
	{ 'V', h_ring },        { 'D', h_diag },        { 'O', h_occ },

	{ 'W', h_wave },        { 'J', h_sync },        { 'N', h_layout },
	{ 'I', h_ibctl },

	{ 'C', h_pair },        { 'A', h_adc_timing },  { 'e', h_temp },

	{ 'Q', h_profile },     { 'l', h_load },        { 'S', h_stall },
	{ 'K', h_mimic_gap },   { 'Z', h_detach },      { 'z', h_reset },
	{ 'q', h_fws },

	{ 0, 0 },
};


int main(void)
{
	uint32_t heartbeat_at;
	int led_state = 0;
	uint32_t led_usb_at = 0;
	uint32_t led_in_last = 0, led_out_last = 0;

	/* WDT is enabled out of reset on this part and will reset the board
	 * roughly every 15 s if not serviced. Nothing here services it. */
	WDT->WDT_MR = WDT_MR_WDDIS;

	/* Before anything derives a rate from it. */
	clock_set_mck(MCK_MULA_DEFAULT);

	led_init();
	led_aux_init();
	uart_init(115200);
	systick_init();
	load_init();
	dac_init();
	adc_init();
	usb_cdc_init();
	clockref_init();

	banner();
	heartbeat_at = millis();

	uint32_t ctl_ms = 0;
	uint32_t usb_ms = 0;

	for (;;) {
		uint32_t now;

		/*
		 * First thing in the pass, so the interval measured is the
		 * whole pass rather than the part after the timebase read.
		 */
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

		/*
		 * USB activity on the two spare LEDs: TXL lights while the IN
		 * direction moves data, RXL while OUT does. Driven from byte
		 * and DMA-start counters the driver already bumps, sampled at
		 * 50 ms so even a slow trickle reads as a visible flicker.
		 */
		if (now - led_usb_at >= 50u) {
			led_tx(usb_in_activity != led_in_last);
			led_rx(usb_out_activity != led_out_last);
			led_in_last = usb_in_activity;
			led_out_last = usb_out_activity;
			led_usb_at = now;
		}

		/*
		 * Control transfers, at most once a millisecond - same
		 * argument as the control channel below: this reads
		 * UOTGHS_DEVISR every pass and costs about 1.2 us of a
		 * 7.8 us one, all clock-domain-crossing bus cost rather
		 * than instruction cost, to ask about an event that happens
		 * a few dozen times at enumeration and essentially never
		 * after. USB allows 500 ms for most control requests
		 * (50 ms for SET_ADDRESS), so a millisecond of latency is
		 * invisible against either.
		 *
		 * The real fix is UOTGHS_IRQn (written as UOTGHS_Handler,
		 * never enabled). This is the one-line version of it.
		 */
		if (now != usb_ms) {
			usb_ms = now;
			usb_cdc_poll();
			clockref_poll();
		}
		play_service();
		stream_service();
		if (diag_armed())
			diag_service();

		/*
		 * Keep bulk OUT drained when nothing is consuming it, every
		 * pass. Gating this to 1 kHz like the two polls above was
		 * tried and cost the suite ten failures and a wedge: four
		 * banks/ms is ~2 MB/s of drain capacity against a host
		 * writing ~1.8 MB/s during playback, so gating erodes the
		 * margin that keeps the pipe from NAKing indefinitely and
		 * stranding the host in close().
		 */
		if (!play_active() && !stream_out_in_use()) {
			static uint8_t scrap[512];

			/* Counted so that "the device stopped draining" is a
			 * reading and not a theory. It is the one thing every
			 * 0c diagnosis has had to assume. */
			usb_out_drain_polls++;
			for (int b = 0; b < 4; b++)
				if (usb_cdc_read(scrap, sizeof(scrap)) == 0)
					break;
		}

		/*
		 * The control channel, at most once a millisecond. Servicing
		 * it every pass cost 2141 ns of a 9700 ns pass - a UOTGHS
		 * register read is far dearer than an SRAM one (`Q` measures
		 * usb_ctl_read() alone at 1205 ns doing nothing) - against an
		 * endpoint that receives a command ten times a second. A
		 * millisecond is still 100x faster than any host can notice
		 * on a status poll.
		 *
		 * Gated here rather than inside ctl_service() because `now`
		 * is already in a register. The drain still has to happen
		 * every pass: an unread OUT endpoint NAKs forever and hangs
		 * the host in close().
		 */
		if (now != ctl_ms) {
			ctl_ms = now;
			ctl_service();
		}

		/*
		 * Playback status on bulk IN, so the host can close a rate
		 * loop on what the converter actually consumed. Only in
		 * play-only: in loop mode IN carries frames and is on DMA,
		 * and the FIFO path must not touch an endpoint DMA owns.
		 *
		 * usb_cdc_write never spins - it gives up when no bank is
		 * free - so a host that stops reading costs a dropped record
		 * and not a stalled main loop. The host tolerates gaps: it
		 * differences whichever records arrive.
		 */
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
				st.version   = PLAYSTAT_VERSION;
				st.pad[0] = st.pad[1] = st.pad[2] = 0;
				/*
				 * Each field is a 32-bit aligned volatile read
				 * and so atomic on this core, but the set is
				 * not sampled as one. A one-buffer skew against
				 * a window the host averages over hundreds of
				 * milliseconds is below the noise it is
				 * measuring.
				 */
				st.consumed  = play_consumed;
				st.underruns = play_underruns;
				st.bytes_in  = play_bytes_in;
				st.dev_us    = micros();
				st.crc32     = frame_crc32((const uint8_t *)&st,
				                           sizeof(st)
				                           - sizeof(st.crc32));
				usb_cdc_write((const uint8_t *)&st, sizeof(st));
			}
		}

		console_feed(uart_getc());
	}
}
