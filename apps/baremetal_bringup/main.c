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
#include "play.h"
#include "playstat.h"
#include "usb_cdc.h"

#define LED_MASK (1u << 27)

static void banner(void)
{
	printf("#\n");
	printf("# due_oscilloscope :: Track B bare-metal bring-up\n");
	printf("# built %s %s\n", __DATE__, __TIME__);
	printf("# SystemCoreClock = %lu  ADC clk = %lu (max 20000000)\n",
	       (unsigned long)SystemCoreClock, (unsigned long)(SystemCoreClock / 4u));
	printf("# commands: h=help p=printf-cost g=gpio-cost f=fault\n");
	printf("#           r=read a0/a1  s=dac sweep  x=crosstalk\n");
	printf("#           t=trigger-rate sweep (TC+ADC+PDC)\n");
	printf("#           1..5=stream 50k/100k/200k/400k Hz, 5=max in-spec (%lu)\n",
	       (unsigned long)((SystemCoreClock / 2u) / ACQ_MIN_RC));
	printf("#           0=stop stream   ?=stream stats\n");
	printf("#           w=stream over UART   u=usb registers\n");
	printf("#           F=flood IN  R=sink OUT  X=duplex  B=bench stats\n");
	printf("#           G/T/Y = same three via DMA\n");
	printf("#           L=full loop HOST->DAC->ADC->HOST\n");
	printf("#           P=play only  V=ring dump  D=loop diagnostic\n");
	printf("#           O=playback ring occupancy histogram\n");
	printf("#           =<dac>[,<adc>[,<nch>]] before L/P/t: rates, channels\n");
	printf("#           M=mimic loop without USB (gen sine on TIOA1 + capture)\n");
	printf("#           Q=main-loop profile  z=software reset\n");
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
 * Verify that the ADC converts at the rate the timer was told to
 * produce. Everything downstream is sized against this, and the failure
 * mode is silent: an over-fast trigger is ignored with no status bit
 * set, which looks exactly like clean data at half the rate.
 */
static void cmd_rate_sweep(unsigned n_channels)
{
	static const uint32_t rates[] = {
		100000, 400000,
		466666, 471910, 477272, 482758, 488372,
		494117, 500000
	};
	/* RC 48 down to 43, to bracket the single-channel cliff. */
	static const uint32_t rates1[] = {
		200000, 780000, 795918, 812500, 829787,
		847826, 866666, 886363, 906976
	};
	const uint32_t *list = (n_channels == 1) ? rates1 : rates;
	unsigned n_list = (n_channels == 1)
	                ? sizeof(rates1) / sizeof(rates1[0])
	                : sizeof(rates) / sizeof(rates[0]);
	const uint32_t nbuf_target = 8;

	acq_init();

	printf("# TC->ADC->PDC rate sweep, %u channel%s, min RC %lu\n",
	       n_channels, n_channels == 1 ? " (A0=AD7)" : "s (A0=AD7, A1=AD6)",
	       (unsigned long)ACQ_MIN_RC_FOR(n_channels));
	printf("#   want      RC   TCexact   measured    ratio  RXBUFF GOVRE\n");
	uart_flush();

	for (unsigned i = 0; i < n_list; i++) {
		if (!acq_start(list[i], n_channels)) {
			printf("# %7lu       -         -    REFUSED (below ACQ_MIN_RC)\n",
			       (unsigned long)list[i]);
			uart_flush();
			continue;
		}

		uint32_t sync = acq_buffers_done;
		uint32_t guard = micros();
		while (acq_buffers_done == sync && (micros() - guard) < 2000000u)
			{ }

		uint32_t t0 = micros();
		uint32_t b0 = acq_buffers_done;
		while (acq_buffers_done - b0 < nbuf_target &&
		       (micros() - t0) < 2000000u)
			{ }
		uint32_t t1 = micros();
		uint32_t got = acq_buffers_done - b0;

		acq_stop();

		uint32_t rc      = acq_configured_rc();
		uint32_t tcexact = (SystemCoreClock / 2u) / rc;
		uint32_t us      = t1 - t0;
		uint64_t samples = (uint64_t)got * ACQ_BUF_SAMPLES;
		uint32_t agg     = us ? (uint32_t)((samples * 1000000ull) / us) : 0;
		uint32_t measured = agg / n_channels;
		uint32_t ratio_x1000 = tcexact ?
			(uint32_t)(((uint64_t)measured * 1000ull) / tcexact) : 0;

		printf("# %7lu %7lu %9lu %10lu   %2lu.%03lu %7lu %5lu\n",
		       (unsigned long)list[i], (unsigned long)rc,
		       (unsigned long)tcexact, (unsigned long)measured,
		       (unsigned long)(ratio_x1000 / 1000u),
		       (unsigned long)(ratio_x1000 % 1000u),
		       (unsigned long)acq_rxbuff_overruns,
		       (unsigned long)acq_govre);
		uart_flush();
	}
	printf("# rates past the measured ceiling are refused, not attempted\n");
	uart_flush();
}

/*
 * Stream over the programming-port UART. Bandwidth-limited: 115200 baud
 * carries about 11.5 kB/s, so 2 kHz of trigger (2 channels, 2 bytes)
 * at 8 kB/s fits with margin. ASCII output must stay silent while this
 * runs, since frames and logs share the one port here.
 */
static void cmd_stream_uart(uint32_t trigger_hz)
{
	if (!stream_start_uart(trigger_hz)) {
		printf("# refused\n");
		uart_flush();
		return;
	}
	printf("# uart-stream: trigger %lu Hz, sine %lu Hz - binary follows\n",
	       (unsigned long)trigger_hz, (unsigned long)gen_sine_hz(trigger_hz));
	uart_flush();
}

static void cmd_stream(uint32_t trigger_hz)
{
	if (!stream_start(trigger_hz)) {
		printf("# refused: %lu Hz is past the measured ADC ceiling\n",
		       (unsigned long)trigger_hz);
		uart_flush();
		return;
	}
	printf("# streaming: trigger %lu Hz, %lu sps aggregate, sine %lu Hz\n",
	       (unsigned long)trigger_hz, (unsigned long)(trigger_hz * 2u),
	       (unsigned long)gen_sine_hz(trigger_hz));
	printf("# DAC1 holds mid scale: A1 must read flat, or demux is wrong\n");
	uart_flush();
}

/*
 * Loop diagnostic: periodic snapshots taken while both service loops run.
 *
 * One run separates four hypotheses that the aggregate counters cannot
 * tell apart: a stalled ring (prod/cons stop), a PDC reading a stale
 * address (tpr stops walking the slots), a starved service loop (svc
 * stops advancing), and a capture path serving stale data while the DAC
 * output actually moves (cdr7 is the ADC's live last A0 conversion, read
 * straight from the register and bypassing the ring, the framer and USB).
 *
 * Snapshots go to memory and print only after the last one, because a
 * printf mid-run would stall the very loops being observed. The reads
 * are registers and counters, not the sample stream; `next` peeks one
 * half-word at DACC_TPR to see what the PDC is about to fetch, which is
 * a diagnostic exception to the no-CPU-on-samples rule, not a data path.
 */
#define DIAG_N 12u
#define DIAG_INTERVAL_MS 150u

struct diag_snap {
	uint32_t ms, prod, cons, endtx, svc;
	uint32_t tpr, tcr, tnpr;
	uint16_t next, cdr7, cdr6;
	uint32_t aprod, acons;
};

static struct diag_snap diag[DIAG_N];
static unsigned diag_count;
static uint32_t diag_next_ms;
static bool     diag_run;

static void diag_start(void)
{
	diag_count = 0;
	diag_next_ms = millis();
	diag_run = true;
}

static void diag_service(void)
{
	if (!diag_run)
		return;

	if (diag_count < DIAG_N) {
		uint32_t now = millis();
		struct diag_snap *s;

		if ((int32_t)(now - diag_next_ms) < 0)
			return;

		s = &diag[diag_count++];
		s->ms    = now;
		s->prod  = play_produced;
		s->cons  = play_consumed;
		s->endtx = play_endtx_seen;
		s->svc   = play_svc_calls;
		s->tpr   = DACC->DACC_TPR;
		s->tcr   = DACC->DACC_TCR;
		s->tnpr  = DACC->DACC_TNPR;
		s->next  = *(volatile uint16_t *)s->tpr;
		s->cdr7  = (uint16_t)ADC->ADC_CDR[7];
		s->cdr6  = (uint16_t)ADC->ADC_CDR[6];
		s->aprod = acq_produced;
		s->acons = acq_consumed;
		diag_next_ms = now + DIAG_INTERVAL_MS;
		return;
	}

	diag_run = false;

	{
		uint32_t base = (uint32_t)play_ring_base();

		printf("# diag: play ring base=%08lx slot=%u B nslots=%u\n",
		       (unsigned long)base, PLAY_BUF_BYTES, PLAY_NBUF);
		printf("#    ms  prod  cons endtx    svc  tpr=slot+off  tcr"
		       "  next(tag,code)  cdr7 cdr6  aprod acons\n");
		for (unsigned i = 0; i < DIAG_N; i++) {
			struct diag_snap *s = &diag[i];
			uint32_t off = s->tpr - base;

			printf("# %5lu %5lu %5lu %5lu %6lu  %lu+%-4lu %4lu"
			       "  %04x(t%u,%4u)  %4u %4u  %5lu %5lu\n",
			       (unsigned long)(s->ms - diag[0].ms),
			       (unsigned long)s->prod, (unsigned long)s->cons,
			       (unsigned long)s->endtx, (unsigned long)s->svc,
			       (unsigned long)(off / PLAY_BUF_BYTES),
			       (unsigned long)(off % PLAY_BUF_BYTES),
			       (unsigned long)s->tcr,
			       s->next, (s->next >> 12) & 3u, s->next & 0x0fffu,
			       s->cdr7 & 0x0fffu, s->cdr6 & 0x0fffu,
			       (unsigned long)s->aprod, (unsigned long)s->acons);
		}
		uart_flush();
	}
}

/*
 * Where the main loop's time goes.
 *
 * The DMA benches re-arm at most one transfer per main-loop pass, so
 * the cost of a pass is a throughput ceiling, not a curiosity. Track A
 * carries the identical command so the two can be compared directly -
 * which is the only way to tell a real difference from a difference in
 * how the two were built.
 *
 * Results are ns per call.
 */
/*
 * Dump the playback ring's occupancy distribution.
 *
 * Printed as a bare comma-separated list rather than key=value pairs:
 * 32 buckets as `occ0=..` would be a long line for a parse that gains
 * nothing, and the index is the occupancy, so position is the key.
 */
static void cmd_occ_hist(void)
{
	printf("# play_occ min=%lu endtx=%lu runus=%lu consumed=%lu hist=",
	       (unsigned long)play_occ_min,
	       (unsigned long)play_endtx_seen,
	       (unsigned long)play_run_us,
	       (unsigned long)play_consumed);
	for (unsigned i = 0; i < PLAY_NBUF; i++)
		printf("%lu%s", (unsigned long)play_occ_hist[i],
		       i + 1u < PLAY_NBUF ? "," : "");
	printf("\n");
	uart_flush();

	printf("# play_occ_trace decim=%u n=%lu v=", PLAY_OCC_DECIM,
	       (unsigned long)play_occ_traced);
	for (unsigned i = 0; i < play_occ_traced; i++) {
		printf("%u%s", (unsigned)play_occ_trace[i],
		       i + 1u < play_occ_traced ? "," : "");
		/* 256 entries is more than one UART buffer holds. */
		if ((i & 31u) == 31u)
			uart_flush();
	}
	printf("\n");
	uart_flush();

	/*
	 * Absolute microseconds at every PLAY_RATE_DECIM-th consumed
	 * buffer. The host differences them; sending deltas here would
	 * throw away the only reading that survives a disturbed sample.
	 */
	printf("# play_rate decim=%u n=%lu us=", (unsigned)PLAY_RATE_DECIM,
	       (unsigned long)play_rate_traced);
	for (unsigned i = 0; i < play_rate_traced; i++) {
		printf("%lu%s", (unsigned long)play_rate_us[i],
		       i + 1u < play_rate_traced ? "," : "");
		if ((i & 15u) == 15u)
			uart_flush();
	}
	printf("\n");
	uart_flush();
}

static void cmd_profile(void)
{
	const uint32_t n = 20000;
	uint32_t t0, t1;

	printf("# main-loop profile, ns per call\n");
	uart_flush();

#define PROF(label, expr)                                            \
	do {                                                         \
		t0 = micros();                                       \
		for (uint32_t i = 0; i < n; i++) { expr; }            \
		t1 = micros();                                       \
		printf("# %-22s %6lu ns\n", label,                   \
		       (unsigned long)(((uint64_t)(t1 - t0) * 1000ull) / n)); \
		uart_flush();                                        \
	} while (0)

	PROF("empty loop", __asm__ volatile(""));
	PROF("millis()", (void)millis());
	PROF("micros()", (void)micros());
	PROF("usb_cdc_ready()", (void)usb_cdc_ready());
	PROF("usb_dma_out_busy()", (void)usb_dma_out_busy());
	PROF("usb_cdc_poll()", usb_cdc_poll());
	PROF("play_service()", play_service());
	PROF("stream_service()", stream_service());
	PROF("diag_service()", diag_service());
#undef PROF

	printf("# note: services early-return unless started\n");
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

/* ------------------------------------------------------------------ */
/* The command layer                                                   */
/*                                                                     */
/* Parsing and execution are separated because a second transport is   */
/* coming: the native port will carry a binary framed protocol         */
/* (docs/control-protocol.md) with a different parser, and both must   */
/* reach the same executor. Two implementations of "start playback"    */
/* would drift, and the refusal wording is part of what the host is    */
/* told, not decoration.                                               */
/*                                                                     */
/* Structure only. The UART is still the only caller and every command */
/* behaves exactly as it did.                                          */
/* ------------------------------------------------------------------ */

typedef struct {
	int      op;           /* the command letter */
	uint32_t arg[3];       /* "=<a>[,<b>[,<c>]]" typed before it */
} cmd_t;

/*
 * Feed one received character; true when `out` holds a whole command.
 *
 * The '=' introducer is what keeps bare digits working as the stream
 * presets: while an entry is open, digits and up to two commas are
 * argument text, and the next command letter consumes the arguments
 * and closes the entry.
 */
static bool cmd_parse_ascii(int c, cmd_t *out)
{
	static uint32_t arg[3];
	static unsigned idx;
	static bool entry;

	if (c == '=') {
		arg[0] = arg[1] = arg[2] = 0;
		idx = 0;
		entry = true;
		return false;
	}
	if (entry && c >= '0' && c <= '9') {
		arg[idx] = arg[idx] * 10u + (uint32_t)(c - '0');
		return false;
	}
	if (entry && c == ',' && idx < 2) {
		idx++;
		return false;
	}
	if (c < 0)
		return false;

	entry = false;
	out->op = c;
	out->arg[0] = arg[0];
	out->arg[1] = arg[1];
	out->arg[2] = arg[2];
	/* A dispatched command consumes its arguments. */
	arg[0] = arg[1] = arg[2] = 0;
	idx = 0;
	return true;
}

/* Carry out one parsed command. The only place a command is executed,
 * whichever transport delivered it. */
static void cmd_execute(const cmd_t *cmd)
{
	switch (cmd->op) {
	case 'h': banner();         break;
	case 'p': measure_printf(); break;
	case 'g': measure_gpio();   break;
	case 'f': trigger_fault();  break;
	case 'r': cmd_read();       break;
	case 's': cmd_sweep();      break;
	case 'x': cmd_crosstalk();  break;
	case 't': cmd_rate_sweep(cmd->arg[2] ? cmd->arg[2] : 2u); break;
	case '1': cmd_stream(50000);  break;
	case '2': cmd_stream(100000); break;
	case '3': cmd_stream(200000); break;
	case '4': cmd_stream(400000); break;
	/*
	 * Max in-spec rate, derived from the running clock exactly as
	 * Track A does. A hardcoded 488372 Hz lingered here from the
	 * MCK=84 MHz era and was silently refused by the ACQ_MIN_RC
	 * guard at 78 MHz - the guard doing its job on a stale preset.
	 */
	case '5': cmd_stream((SystemCoreClock / 2u) / ACQ_MIN_RC); break;
	case '0': stream_stop(); play_stop();
	          printf("# stream stopped\n"); uart_flush(); break;
	case '?': stream_report();  break;
	case 'u': usb_cdc_dump();   break;
	case 'F': stream_flood_start();
	          printf("# flood: IN only\n"); uart_flush(); break;
	case 'R': stream_sink_start();
	          printf("# sink: OUT only\n"); uart_flush(); break;
	case 'X': stream_duplex_start();
	          printf("# duplex: IN and OUT together\n"); uart_flush(); break;
	case 'G': stream_flood_dma_start();
	          printf("# flood: IN via DMA\n"); uart_flush(); break;
	case 'T': stream_sink_dma_start();
	          printf("# sink: OUT via DMA\n"); uart_flush(); break;
	case 'Y': stream_duplex_dma_start();
	          printf("# duplex: IN+OUT via DMA\n"); uart_flush(); break;
	/*
	 * The complete loop: the host supplies the waveform, the DAC
	 * emits it, the jumper carries it to the ADC, and the capture
	 * comes back over the same USB pipe. Both directions run at
	 * once, which is the target configuration.
	 */
	case 'L': {
		/* "=<dac>[,<adc>]L"; one number sets both, none = 200k. */
		uint32_t dac_hz = cmd->arg[0] ? cmd->arg[0] : 200000u;
		uint32_t adc_hz = cmd->arg[1] ? cmd->arg[1] : dac_hz;
		unsigned nch    = cmd->arg[2] ? cmd->arg[2] : 2u;

		if (!play_start(dac_hz)) {
			printf("# loop: DAC %lu sps refused (max %lu)\n",
			       (unsigned long)dac_hz, (unsigned long)((SystemCoreClock / 2u) / PLAY_MIN_RC));
			uart_flush();
			break;
		}
		if (!stream_start_capture_only(adc_hz, nch)) {
			play_stop();
			printf("# loop: ADC %lu Hz x%u ch refused (max %lu)\n",
			       (unsigned long)adc_hz, nch,
			       (unsigned long)((SystemCoreClock / 2u)
			                       / ACQ_MIN_RC_FOR(nch)));
			uart_flush();
			break;
		}
		printf("# loop: DAC %lu sps from USB, ADC %lu Hz/ch x%u ch\n",
		       (unsigned long)dac_hz, (unsigned long)adc_hz, nch);
		printf("# DAC0 carries the waveform, DAC1 holds mid scale\n");
		uart_flush();
		break;
	}
	/* Playback with NO capture stream, to separate a fault in the
	 * DAC path from an interaction between the two service loops. */
	case 'P': {
		uint32_t dac_hz = cmd->arg[0] ? cmd->arg[0] : 200000u;

		if (play_start(dac_hz))
			printf("# play only: DAC %lu sps from USB, no capture\n",
			       (unsigned long)dac_hz);
		else
			printf("# play only: %lu sps refused (max %lu)\n",
			       (unsigned long)dac_hz, (unsigned long)((SystemCoreClock / 2u) / PLAY_MIN_RC));
		uart_flush();
		break;
	}
	case 'Q': cmd_profile(); break;
	/*
	 * Software reset. The test suite holds the control port open
	 * for a whole session, because opening it asserts NRSTB and
	 * costs a reset plus a native-port re-glob every time; this is
	 * how it recovers a wedged device without giving that up.
	 * Track A has always had it and docs/HANDOFF.md has always
	 * listed it here, so this closes a documented parity gap
	 * rather than adding a feature.
	 */
	case 'z': printf("# software reset now\n"); uart_flush();
	          RSTC->RSTC_CR = RSTC_CR_KEY(0xA5u) | RSTC_CR_PROCRST;
	          break;
	case 'V': play_dump(); break;
	case 'D': diag_start(); break;
	/*
	 * The loop's timing skeleton with no USB in it: gen's flash sine
	 * through play's exact DACC + TIOA1 configuration, capture
	 * running, ordering matched to what L does once the ring primes.
	 * Observe with D: if cdr7 swings, the fault needs USB to appear;
	 * if it freezes, the trigger/DACC/ADC interaction is the fault.
	 */
	case 'M':
		play_stop();
		gen_init();
		gen_prepare_tioa1(200000u);
		stream_start_capture_only(200000u, 2);
		gen_go_tioa1();
		printf("# mimic loop: gen sine on TIOA1 at 200000 sps, capture 200000 Hz\n");
		printf("# press D and read cdr7: swing = USB at fault, frozen = trigger path\n");
		uart_flush();
		break;
	case 'B': stream_bench_report();
	          printf("# play: in=%lu produced=%lu consumed=%lu under=%lu isr=%lu endtx=%lu spans=%lu partial=%lu occmin=%lu\n",
	                 (unsigned long)play_bytes_in,
	                 (unsigned long)play_produced,
	                 (unsigned long)play_consumed,
	                 (unsigned long)play_underruns,
	                 (unsigned long)play_isr_calls,
	                 (unsigned long)play_endtx_seen,
	                 (unsigned long)play_spans,
	                 (unsigned long)play_partial,
	                 (unsigned long)play_occ_min);
	          uart_flush(); break;
	/*
	 * The occupancy histogram, off the `B` path deliberately.
	 * `B` is polled mid-stream by the daemon and must stay one
	 * short line; this is 32 buckets and belongs where `V`
	 * already lives, which is between runs.
	 */
	case 'O': cmd_occ_hist(); break;
	case 'w': cmd_stream_uart(2000); break;
	default:                    break;
	}
}


int main(void)
{
	uint32_t heartbeat_at;
	int led_state = 0;
	uint32_t led_usb_at = 0;
	uint32_t led_in_last = 0, led_out_last = 0;
	cmd_t cmd;

	/* WDT is enabled out of reset on this part and will reset the board
	 * roughly every 15 s if not serviced. Nothing here services it. */
	WDT->WDT_MR = WDT_MR_WDDIS;

	/* Before anything derives a rate from it. */
	clock_set_mck(MCK_MULA_DEFAULT);

	led_init();
	led_aux_init();
	uart_init(115200);
	systick_init();
	dac_init();
	adc_init();
	usb_cdc_init();

	/* Unbuffered, so output appears as it is produced rather than at
	 * flush points that would distort the printf measurement. */
	setvbuf(stdout, NULL, _IONBF, 0);

	banner();
	heartbeat_at = millis();

	for (;;) {
		uint32_t now = millis();

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

		usb_cdc_poll();
		play_service();
		stream_service();
		diag_service();

		/*
		 * Keep bulk OUT drained when nothing is consuming it. A CDC
		 * device that lets the pipe NAK indefinitely wedges the host:
		 * macOS's close() waits for in-flight write URBs to complete,
		 * and tcflush cannot recall a URB already at the controller,
		 * so the host process hangs in close() holding the port.
		 */
		if (!play_active() && !stream_out_in_use()) {
			static uint8_t scrap[512];
			for (int b = 0; b < 4; b++)
				if (usb_cdc_read(scrap, sizeof(scrap)) == 0)
					break;
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

		int c = uart_getc();

		if (cmd_parse_ascii(c, &cmd))
			cmd_execute(&cmd);
	}
}
