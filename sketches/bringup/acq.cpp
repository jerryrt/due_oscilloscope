/*
 * TC0 channel 0 drives TIOA0, which triggers the ADC. The ADC's PDC
 * writes conversions straight into SRAM with the CPU out of the path.
 *
 * The ISR does nothing but reload the PDC next-pointer and bump
 * counters. Everything else belongs outside the real-time path.
 */

#include <Arduino.h>
#include "acq.h"

/*
 * Bank 1, so that the PDC writing conversions and the USB DMA reading
 * finished frames are not arbitrating for the same bus matrix slave as
 * the playback ring and everything else. Measured on Track B: a
 * 4096-byte transfer out of bank 0 costs 439 ADC overruns per 4 s at
 * the full rate, and moving the ring halved it.
 *
 * The placement needs linker/arduino_due_x_sram1.ld, which
 * cmake/track_a.cmake links directly. Building without it puts this
 * in .bss, which still links and still runs - which is why the
 * script is a line in the build rather than a caller's argument.
 */
acq_slot_t acq_slot[ACQ_NBUF] __attribute__((section(".sram1")));

/*
 * ADC track and settling time, applied at the next acq_init(). Track
 * B's acq.c carries the same control under the same command.
 *
 * Runtime rather than a #define on purpose. The defect this exists to
 * test is bimodal per run and its incidence tracks the binary - four
 * bytes of bss have moved it - so a compile-time sweep compares images
 * and cannot separate the constant from the layout. One image that
 * takes the value from the host compares only the constant.
 *
 * 0/0 is what this project has always streamed at, and is the default,
 * so nothing changes unless a host asks for it. docs/hardware.md warns
 * that the +/-1 code crosstalk baseline was taken at the maximum of
 * both and "does not retire the crosstalk risk" because "crosstalk
 * bites when tracking time is short".
 */
uint8_t acq_tracktim = 0;   /* 0-15 */
uint8_t acq_settling = 0;   /* 0-3  */

void acq_set_timing(uint32_t tracktim, uint32_t settling)
{
	acq_tracktim = (uint8_t)(tracktim > 15u ? 15u : tracktim);
	acq_settling = (uint8_t)(settling > 3u ? 3u : settling);
}

volatile uint32_t acq_buffers_done;
volatile uint32_t acq_rxbuff_overruns;
volatile uint32_t acq_govre;
volatile uint32_t acq_produced;
volatile uint32_t acq_consumed;
volatile uint32_t acq_ring_overflow;

static volatile uint32_t filling;     /* index currently in PDC RPR */
static uint32_t configured_rc;
static uint16_t configured_mask;

/*
 * A0 is AD7 and A1 is AD6. The sequencer converts enabled channels in
 * ascending channel-index order, so each trigger yields AD6 then AD7,
 * i.e. A1 before A0. The channel tag in LCDR[15:12] is what the host
 * demultiplexes on, so label order never has to be assumed.
 */

/*
 * Which channel joins A0 in a two-channel capture: A1 or A2. Track B's
 * acq.c carries the same control under the same command and the same
 * default.
 *
 * The impedance sweep compared A1 against A2 inside one three-channel
 * frame, where ascending index converts A2 first and A1 second - so
 * source and conversion slot moved together and the sweep could not
 * separate them. ADC_MR.USEQ was the obvious control and does not work
 * on this part: SEQR1 reads back exactly as written and the converter
 * still returns tag 0 and floating-pin values.
 *
 * This is the control that does work, and it needs no sequencer. A0+A1
 * and A0+A2 both put the channel under test in slot 0 with the sine in
 * slot 1, so the two configurations differ in the source and in nothing
 * else. Interleave them and the state draw cancels too.
 *
 * Two channels only, which is all this track's acq_start() accepts and
 * all the arm needs. The three-channel path is a separate parity gap.
 */
uint8_t acq_pair_second = ACQ_CH_A1;

void acq_set_pair(uint32_t a_number)
{
	acq_pair_second = (a_number == 2u) ? (uint8_t)ACQ_CH_A2 : (uint8_t)ACQ_CH_A1;
}

static void tc_init(uint32_t rc)
{
	PMC->PMC_PCER0 = (1u << ID_TC0);

	TC0->TC_CHANNEL[0].TC_CCR = TC_CCR_CLKDIS;
	TC0->TC_CHANNEL[0].TC_IDR = 0xffffffff;

	TC0->TC_CHANNEL[0].TC_CMR = TCCLKS_TIMER_CLOCK1
	                          | TC_CMR_WAVE
	                          | WAVSEL_UP_RC
	                          | ACPA_CLEAR
	                          | ACPC_SET;

	configured_rc = rc;
	TC0->TC_CHANNEL[0].TC_RA = rc / 2u;              /* 50% duty */
	TC0->TC_CHANNEL[0].TC_RC = rc;
}

uint32_t acq_configured_rc(void)
{
	return configured_rc;
}

uint16_t acq_channel_mask(void)
{
	return configured_mask;
}

/*
 * ADC_MR as the hardware holds it, not as anyone remembers setting it.
 *
 * The same discipline Track B records: acq_set_timing() and acq_init()
 * are separated by a whole capture, ADC_MR is written by more than one
 * path, and a reading that comes back through a printf of a variable
 * rather than of the peripheral proves nothing about the converter.
 * TRACKTIM is bits 27:24 and SETTLING 21:20; the host decodes them,
 * because decoding on the device cost 3.8 ms of blocked main loop when
 * Track B measured it and the raw word costs 1.3.
 */
uint32_t acq_mr(void)
{
	return ADC->ADC_MR;
}

/*
 * Software-triggered polled reads, this track's own.
 *
 * Not `analogRead()`: acq_init() sets ADC_EMR_TAG, which puts the
 * channel index in LCDR[15:12] so the streaming path can demultiplex
 * without being told the mode. The Arduino core's analogRead() reads
 * LCDR and does not mask that, so once TAG is on it returns
 * tag|value - for a converter that cannot exceed 4095, and worse,
 * the tag can name the wrong channel: the sequencer converts every
 * enabled channel per trigger in ascending index order, so the
 * core's single-channel read can land on whichever conversion
 * finished last.
 *
 * Reading through the core while this track programs the same
 * peripheral itself is the divergence invariant 3 names - `acq`/`adc`
 * internals stay per track - and Track B has had `adc_read` /
 * `adc_read_pair` all along.
 *
 * Masked to 12 bits at the source, so no caller has to know TAG is on.
 */
uint16_t acq_read_one(unsigned ch)
{
	ADC->ADC_CHDR = 0xffffu;
	ADC->ADC_CHER = (1u << ch);

	ADC->ADC_CR = ADC_CR_START;
	while (!(ADC->ADC_ISR & (1u << ch)))
		{ }

	return (uint16_t)(ADC->ADC_CDR[ch] & 0x0fffu);
}

/*
 * Measurement conditions for a polled reading, set here rather than
 * inherited, and restored afterwards.
 *
 * Same argument as acq_read_temp(): the variable is not which track,
 * it is whatever last touched the register. `x` used to run at
 * TRACKTIM 0 / SETTLING 0 here and TRACKTIM 15 / SETTLING 3 on
 * Track B - the two ends of the range - because each track's `x`
 * inherited whatever its own init had left. On the `=2C` arm that
 * was worth a sign flip and a factor of four between two builds of
 * the same command on the same board minutes apart.
 *
 * Tracking time is the dominant term for multiplexer bleed, so a
 * crosstalk measurement that inherits it is measuring its own history.
 * These are the same conditions the temperature read sets, so the two
 * deliberate measurements on this part now agree about what "polled
 * and accurate" means.
 *
 * Refuses while the ADC is hardware-triggered, for invariant 5's
 * reason: this rewrites ADC_MR and the channel enables, and doing that
 * under a running capture puts foreign conversions in the ring.
 */
static uint32_t measure_saved_mr;
static uint32_t measure_saved_cher;
static bool     measure_active;

int acq_measure_begin(void)
{
	if (ADC->ADC_MR & ADC_MR_TRGEN)
		return -1;
	if (measure_active)
		return -1;

	measure_saved_mr   = ADC->ADC_MR;
	measure_saved_cher = ADC->ADC_CHSR;
	measure_active     = true;

	ADC->ADC_MR = ADC_MR_PRESCAL(1)
	            | (0xfu << ADC_MR_STARTUP_Pos)
	            | ADC_MR_TRACKTIM(15)
	            | (3u << ADC_MR_SETTLING_Pos)
	            | (1u << ADC_MR_TRANSFER_Pos);
	return 0;
}

void acq_measure_end(void)
{
	if (!measure_active)
		return;
	ADC->ADC_CHDR = 0xffffu;
	ADC->ADC_CHER = measure_saved_cher;
	ADC->ADC_MR   = measure_saved_mr;
	measure_active = false;
}

/*
 * Both channels from one trigger. The sequencer converts every enabled
 * channel per trigger event in ascending channel index order, so this is
 * the same ordering the PDC path sees - which is what makes a polled
 * reading comparable with a streamed one.
 */
volatile uint32_t acq_pair_restarts;
volatile uint32_t acq_pair_timeouts;

void acq_read_pair(unsigned cha, unsigned chb, uint16_t *a, uint16_t *b)
{
	uint32_t mask = (1u << cha) | (1u << chb);
	unsigned attempt;

	ADC->ADC_CHDR = 0xffffu;
	ADC->ADC_CHER = mask;

	/*
	 * Bounded, with re-kicks: one START occasionally converts only
	 * part of the enabled pair. Measured on Track A: the second
	 * measurement session's first START completes ch7 and
	 * never ch5 - ISR shows EOC7 set, EOC5 never arrives - and a
	 * second START completes the pair immediately. The sequencer
	 * mechanism is not established; the bound is the contract
	 * (invariant 7: never spin unbounded on hardware), the counters
	 * are the record, and the instrument prints them so a retried
	 * conversion can never pass silently as a clean one.
	 *
	 * 1 ms per attempt is ~500x a two-channel conversion at 19.5 MHz
	 * ADCclk; three attempts bound the worst case at ~3 ms.
	 */
	for (attempt = 0; attempt < 3u; attempt++) {
		uint32_t t0 = micros();

		if (attempt)
			acq_pair_restarts++;
		ADC->ADC_CR = ADC_CR_START;
		while ((ADC->ADC_ISR & mask) != mask)
			if (micros() - t0 > 1000u)
				break;
		if ((ADC->ADC_ISR & mask) == mask)
			break;
	}
	if ((ADC->ADC_ISR & mask) != mask)
		acq_pair_timeouts++;

	*a = (uint16_t)(ADC->ADC_CDR[cha] & 0x0fffu);
	*b = (uint16_t)(ADC->ADC_CDR[chb] & 0x0fffu);
}

/*
 * The on-die temperature sensor: ADC channel 15, enabled by
 * ADC_ACR.TSON. See ctl_temp_t in ctl_wire.h for why it exists and,
 * more importantly, for what a reading from it may and may not be used
 * to claim - the short version is that it is an upper bound on ADVREF
 * noise rather than a value, and it is not a temperature in degrees.
 *
 * Register programming, so this is Track A's own by invariant 3. Track
 * B's is drivers/adc.c; what is shared is the payload and the meaning
 * of its fields, which is protocol rather than programming.
 *
 * Bounded by a time budget rather than by EOC15 alone. A converter that
 * never raises the flag - a part without the sensor, or TSON not taking
 * - would otherwise spin here for ever, and invariant 7 applies to a
 * debug path when a host can reach it.
 */
int acq_read_temp(ctl_temp_t *out, uint16_t samples)
{
	uint32_t saved_cher, saved_mr;
	uint32_t sum = 0;
	uint16_t got = 0;
	uint16_t lo = 0xffffu, hi = 0;

	if (samples < CTL_TEMP_SAMPLES_MIN)
		samples = CTL_TEMP_SAMPLES_DEFAULT;
	if (samples > CTL_TEMP_SAMPLES_MAX)
		samples = CTL_TEMP_SAMPLES_MAX;

	/*
	 * Whatever was enabled goes back afterwards: leaving channel 15 in
	 * the sequencer would change the conversion order of the next
	 * stream, and channel count divides the aggregate rate - a silent
	 * change to every number a run reports.
	 *
	 * Refused while the ADC is hardware-triggered. Reading the sensor
	 * disables the capture's channels and enables channel 15, which
	 * would put sensor conversions into the capture ring -
	 * discontinuous data presented as continuous, invariant 5. TRGEN
	 * is the actual condition; a software flag would be a second
	 * account of it that can disagree.
	 */
	if (ADC->ADC_MR & ADC_MR_TRGEN)
		return CTL_TEMP_BUSY;

	saved_cher = ADC->ADC_CHSR;
	saved_mr   = ADC->ADC_MR;

	/*
	 * The sensor's own tracking time, set here rather than inherited.
	 *
	 * The two tracks were measured reading the die sensor 0.84 codes
	 * apart - four times the ~0.20 codes that
	 * `records/advref-temp.jsonl` bounds ADVREF's whole short-term
	 * noise at - purely because they idle at different ADC_MR: Track A
	 * at TRACKTIM 0 from acq_init(), Track B at 15 from adc_init().
	 * Converging the idle configs would not have fixed it, only moved
	 * it: both tracks *stream* at TRACKTIM 0, so a reading taken after
	 * a capture would still differ from one taken after boot. The
	 * variable is not which track, it is whatever last touched the
	 * register.
	 *
	 * So the measurement sets its own conditions and restores them.
	 * TRACKTIM 15 and SETTLING 3 are the maxima, which is what a
	 * high-impedance source wants - one ADC clock of tracking does not
	 * charge the sample capacitor from a bandgap, and it reads low,
	 * which is the same charge-sharing docs/noise.md describes for an
	 * undriven input reading its neighbour. On a debug path that
	 * already spends 1 ms on TSON startup they cost nothing.
	 *
	 * This also changes what `adc_mr` in the report is for: it was a
	 * variable to be recorded, and it is now a constant to be checked.
	 */
	ADC->ADC_MR = ADC_MR_PRESCAL(1)
	            | (0xfu << ADC_MR_STARTUP_Pos)
	            | ADC_MR_TRACKTIM(15)
	            | (3u << ADC_MR_SETTLING_Pos)
	            | (1u << ADC_MR_TRANSFER_Pos);

	ADC->ADC_ACR |= ADC_ACR_TSON;

	/* The sensor's startup, spent once rather than per conversion. */
	{
		uint32_t t0 = micros();

		while (micros() - t0 < 1000u)
			;
	}

	ADC->ADC_CHDR = 0xffffu;
	ADC->ADC_CHER = ADC_CHER_CH15;

	/*
	 * Throw the first conversion away.
	 *
	 * Found in this command's own output: a reading whose mean was
	 * 992 came back with `min 175`, an 800-code outlier in a
	 * distribution otherwise spanning 10. The channel has just been
	 * switched and the sequencer may have been mid-conversion on
	 * another one when this was called, so the first CDR[15] is not
	 * necessarily this channel's settled result.
	 *
	 * It matters because min/max is reported as the spread. One stray
	 * sample there reads as a sensor that is noisy by hundreds of
	 * codes, on a measurement whose entire purpose is a fraction of a
	 * code - and it would have been read as the sensor rather than as
	 * this function.
	 */
	{
		uint32_t t0 = micros();

		ADC->ADC_CR = ADC_CR_START;
		while (!(ADC->ADC_ISR & ADC_ISR_EOC15) && micros() - t0 < 200u)
			;
		(void)ADC->ADC_CDR[15];
	}

	while (got < samples) {
		uint32_t t0 = micros();
		uint16_t v;
		bool timed_out = false;

		ADC->ADC_CR = ADC_CR_START;
		while (!(ADC->ADC_ISR & ADC_ISR_EOC15)) {
			if (micros() - t0 > 200u) {
				timed_out = true;
				break;
			}
		}
		if (timed_out)
			break;
		v = (uint16_t)(ADC->ADC_CDR[15] & ADC_CDR_DATA_Msk);
		sum += v;
		if (v < lo)
			lo = v;
		if (v > hi)
			hi = v;
		got++;
	}

	/*
	 * The registers as they were *during* the conversions, captured
	 * before the restore below.
	 *
	 * They were read after it at first, which reported acr with TSON
	 * already cleared - the report said the sensor was off in the
	 * measurement it was describing. The whole reason these two fields
	 * are on the wire is that a reading taken at one track/settling
	 * time is not comparable with one taken at another, so a value
	 * from after the fact answers the wrong question.
	 */
	out->adc_mr  = ADC->ADC_MR;
	out->adc_acr = ADC->ADC_ACR;

	ADC->ADC_CHDR = 0xffffu;
	ADC->ADC_CHER = saved_cher;
	ADC->ADC_ACR &= ~ADC_ACR_TSON;
	ADC->ADC_MR = saved_mr;

	if (!got)
		return CTL_TEMP_UNSUPPORTED;

	out->dev_us   = micros();
	/* x16 so the average survives the integer it is reported in. */
	out->code_x16 = (uint32_t)((sum * 16u) / got);
	out->code_min = lo;
	out->code_max = hi;
	out->samples  = got;
	out->channel  = 15u;
	out->reserved = 0;
	return CTL_TEMP_OK;
}

void acq_init(void)
{
	PMC->PMC_PCER1 = (1u << (ID_ADC - 32));

	ADC->ADC_CR = ADC_CR_SWRST;

	/*
	 * ADCClock = MCK / ((PRESCAL+1) * 2) = 78/4 = 19.5 MHz, under the
	 * 20 MHz datasheet maximum (Table 46-28); see docs/hardware.md.
	 *
	 * Tracking is minimal because this is the fast path; the crosstalk
	 * cost is measured, not avoided - see acq_set_timing().
	 */
	ADC->ADC_MR = ADC_MR_PRESCAL(1)
	            | (0xfu << ADC_MR_STARTUP_Pos)
	            | ADC_MR_TRACKTIM(acq_tracktim)
	            | ((uint32_t)acq_settling << ADC_MR_SETTLING_Pos)
	            | (1u << ADC_MR_TRANSFER_Pos);

	ADC->ADC_EMR = ADC_EMR_TAG;      /* channel index in LCDR[15:12] */
	ADC->ADC_CHDR = 0xffffu;
	configured_mask = (uint16_t)((1u << ACQ_CH_A0) | (1u << ACQ_CH_A1));
	ADC->ADC_CHER = configured_mask;
}

bool acq_start(uint32_t trigger_hz, unsigned n_channels)
{
	uint32_t rc;

	if (trigger_hz == 0)
		return false;

	rc = TC_CLOCK1_HZ / trigger_hz;

	/*
	 * The ADC ignores a trigger that arrives before it is ready and
	 * sets no flag when it does, so an over-fast rate reads as clean
	 * data at half the frequency. Refuse it here; nothing downstream
	 * can tell the difference later.
	 *
	 * The floor is per channel count and measured for each, not scaled:
	 * see ACQ_MIN_RC_1CH.
	 */
	if (n_channels == 0 || n_channels > 2)
		return false;
	if (rc < ACQ_MIN_RC_FOR(n_channels))
		return false;

	acq_stop();

	/*
	 * Single channel captures A0 alone at the full single-channel
	 * conversion rate. The sequencer converts enabled channels in
	 * ascending index order and each sample carries its channel tag,
	 * so the host demultiplexes without being told which mode this is.
	 */
	configured_mask = (n_channels == 1)
	                ? (uint16_t)(1u << ACQ_CH_A0)
	                : (uint16_t)((1u << ACQ_CH_A0) | (1u << acq_pair_second));
	ADC->ADC_CHDR = 0xffffu;
	ADC->ADC_CHER = configured_mask;

	acq_buffers_done = 0;
	acq_rxbuff_overruns = 0;
	acq_govre = 0;
	acq_produced = 0;
	acq_consumed = 0;
	acq_ring_overflow = 0;
	filling = 0;

	tc_init(rc);

	/* Prime the PDC: current buffer plus the next one. */
	ADC->ADC_RPR  = (uint32_t)acq_slot[0].samples;
	ADC->ADC_RCR  = ACQ_BUF_SAMPLES;
	ADC->ADC_RNPR = (uint32_t)acq_slot[1].samples;
	ADC->ADC_RNCR = ACQ_BUF_SAMPLES;

	(void)ADC->ADC_ISR;                      /* clear stale flags */
	ADC->ADC_IDR = 0xffffffff;
	ADC->ADC_IER = ADC_IER_ENDRX | ADC_IER_RXBUFF;

	NVIC_ClearPendingIRQ(ADC_IRQn);
	NVIC_SetPriority(ADC_IRQn, 0);           /* above everything else */
	NVIC_EnableIRQ(ADC_IRQn);

	ADC->ADC_PTCR = ADC_PTCR_RXTEN;

	/* Hardware trigger from TIOA0. Set last, so nothing converts until
	 * the PDC is armed. */
	ADC->ADC_MR |= ADC_MR_TRGEN | TRGSEL_TIOA0;

	TC0->TC_CHANNEL[0].TC_CCR = TC_CCR_CLKEN | TC_CCR_SWTRG;
	return true;
}

void acq_stop(void)
{
	TC0->TC_CHANNEL[0].TC_CCR = TC_CCR_CLKDIS;
	ADC->ADC_MR &= ~(ADC_MR_TRGEN | ADC_MR_TRGSEL_Msk);
	ADC->ADC_PTCR = ADC_PTCR_RXTDIS;
	ADC->ADC_IDR = 0xffffffff;
	NVIC_DisableIRQ(ADC_IRQn);
}

/*
 * Runs above everything else. Reloads the PDC next-pointer and counts.
 * No printf, no arithmetic beyond an index, nothing that can block.
 */
void ADC_Handler(void)
{
	uint32_t status = ADC->ADC_ISR;

	if (status & ADC_ISR_GOVRE)
		acq_govre++;

	if (status & ADC_ISR_RXBUFF) {
		/* Both RCR and RNCR hit zero: the reload deadline was missed
		 * and samples were lost. */
		acq_rxbuff_overruns++;
	}

	if (status & ADC_ISR_ENDRX) {
		/* The PDC has already promoted the next descriptor, so RPR now
		 * points at filling+1. Load the one after that. */
		filling = (filling + 1u) % ACQ_NBUF;
		ADC->ADC_RNPR =
			(uint32_t)acq_slot[(filling + 1u) % ACQ_NBUF].samples;
		ADC->ADC_RNCR = ACQ_BUF_SAMPLES;
		acq_buffers_done++;

		/* Lapping the consumer means samples were overwritten before
		 * they were sent. Distinct from RXBUFF, which means the PDC
		 * itself ran dry. */
		if (acq_produced - acq_consumed >= ACQ_NBUF - 1u)
			acq_ring_overflow++;
		acq_produced++;
	}
}

/* See the note in acq.h: the shared framer links these through
 * stream_port.h and cannot see this header. */
bool acq_frame_available(void)
{
	return acq_produced != acq_consumed;
}

const uint16_t *acq_frame_data(void)
{
	return acq_slot[acq_consumed % ACQ_NBUF].samples;
}

uint8_t *acq_frame_bytes(void)
{
	return acq_slot[acq_consumed % ACQ_NBUF].hdr;
}

void acq_frame_release(void)
{
	acq_consumed++;
}
