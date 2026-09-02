/*
 * ADC, software-triggered single conversions.
 *
 * Deliberately configured for accuracy rather than speed here: maximum
 * tracking and settling time. This is a DC test, throughput is
 * irrelevant, and generous tracking keeps multiplexer crosstalk out of
 * the baseline measurement so that wiring faults are unambiguous.
 *
 * The fast configuration, where TRACKTIM is traded against crosstalk,
 * belongs with the TC-triggered PDC path.
 */

#include <stdbool.h>

#include "sam.h"
#include "bsp.h"        /* micros() */
#include "analog.h"

void adc_init(void)
{
	/* ID_ADC is 37, so it lives in PCER1 at bit (37 - 32). */
	PMC->PMC_PCER1 = (1u << (ID_ADC - 32));

	ADC->ADC_CR = ADC_CR_SWRST;

	/*
	 * ADCClock = MCK / ((PRESCAL + 1) * 2) = 78 MHz / 4 = 19.5 MHz,
	 * under the 20 MHz datasheet maximum (Table 46-28); see
	 * docs/hardware.md.
	 */
	ADC->ADC_MR = ADC_MR_PRESCAL(1)
	            | (0xfu << ADC_MR_STARTUP_Pos)
	            | ADC_MR_TRACKTIM(15)
	            | (3u << ADC_MR_SETTLING_Pos)
	            | (2u << ADC_MR_TRANSFER_Pos);

	/* Channel index in LCDR[15:12]: free, and makes the stream
	 * self-describing once the PDC path exists. */
	ADC->ADC_EMR = ADC_EMR_TAG;

	ADC->ADC_CHDR = 0xffffu;

	/*
	 * Pad pull-ups off on every analog pin, as Track A has always run:
	 * the Arduino core's init() disables the pull-up on every pin, and
	 * bare metal inherits the reset default, which is enabled. That
	 * difference is worth a factor of 3.3 on bare-channel bleed - a
	 * floating pad reads its neighbour through the multiplexer at
	 * -282 codes (Track A) against -937 here, and dropping the
	 * pull-up takes this track to -338. It also unloads every driven
	 * pin: 50-150k to 3.3 V hangs on the DAC outputs and the jumpered
	 * inputs otherwise.
	 *
	 * AD0-7 = PA2,3,4,6,16,22,23,24 (descending A7..A0); AD10-13 =
	 * PB17-20; DAC0/1 = PB15/16. Disabling pull-ups on the remaining
	 * digital pins as well was measured and changes nothing (-335), so
	 * only the analog pads are named.
	 */
	PIOA->PIO_PUDR = (1u << 2) | (1u << 3) | (1u << 4) | (1u << 6)
	               | (1u << 16) | (1u << 22) | (1u << 23) | (1u << 24);
	PIOB->PIO_PUDR = (1u << 15) | (1u << 16) | (1u << 17) | (1u << 18)
	               | (1u << 19) | (1u << 20);
}

uint16_t adc_read(unsigned ch)
{
	ADC->ADC_CHDR = 0xffffu;
	ADC->ADC_CHER = (1u << ch);

	ADC->ADC_CR = ADC_CR_START;
	while (!(ADC->ADC_ISR & (1u << ch)))
		{ }

	return (uint16_t)(ADC->ADC_CDR[ch] & 0x0fffu);
}

/*
 * Both channels from one trigger. The sequencer converts every enabled
 * channel per trigger event, in ascending channel index order, so this
 * is the same ordering the PDC path will see.
 */
volatile uint32_t adc_pair_restarts;
volatile uint32_t adc_pair_timeouts;

void adc_read_pair(unsigned cha, unsigned chb, uint16_t *a, uint16_t *b)
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
			adc_pair_restarts++;
		ADC->ADC_CR = ADC_CR_START;
		while ((ADC->ADC_ISR & mask) != mask)
			if (micros() - t0 > 1000u)
				break;
		if ((ADC->ADC_ISR & mask) == mask)
			break;
	}
	if ((ADC->ADC_ISR & mask) != mask)
		adc_pair_timeouts++;

	*a = (uint16_t)(ADC->ADC_CDR[cha] & 0x0fffu);
	*b = (uint16_t)(ADC->ADC_CDR[chb] & 0x0fffu);
}

/*
 * Measurement conditions for a polled reading, set here rather than
 * inherited, and restored afterwards.
 *
 * Same argument as adc_read_temp() below: the variable is not which
 * track, it is whatever last touched the register, and that is worth
 * more on a quantity more sensitive than a temperature. `x` ran at
 * TRACKTIM 0 / SETTLING 0 on Track A and TRACKTIM 15 / SETTLING 3 on
 * Track B - the two ends of the range - because each track's `x`
 * inherited whatever its own init had left. On the `=2C` arm that was
 * worth a sign flip and a factor of four between two builds of the
 * same command on the same board minutes apart, which makes a bleed
 * figure meaningless across tracks and across "before or after a
 * capture" within one.
 *
 * Tracking time is the dominant term for multiplexer bleed, so a
 * crosstalk measurement that inherits it is measuring its own history.
 * TRACKTIM 15 and SETTLING 3 are the maxima and are what a
 * high-impedance source wants; they are the same conditions the
 * temperature read already sets, so the two deliberate measurements on
 * this part now agree about what "polled and accurate" means.
 *
 * Refuses while the ADC is hardware-triggered, for invariant 5's
 * reason: this rewrites ADC_MR and the channel enables, and doing that
 * under a running capture puts foreign conversions in the ring.
 */
static uint32_t measure_saved_mr;
static uint32_t measure_saved_cher;
static bool     measure_active;

int adc_measure_begin(void)
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

void adc_measure_end(void)
{
	if (!measure_active)
		return;
	ADC->ADC_CHDR = 0xffffu;
	ADC->ADC_CHER = measure_saved_cher;
	ADC->ADC_MR   = measure_saved_mr;
	measure_active = false;
}

/*
 * The on-die temperature sensor: ADC channel 15, enabled by
 * ADC_ACR.TSON. See ctl_temp_t in ctl_wire.h for why it exists and,
 * more importantly, for what a reading from it may and may not be used
 * to claim.
 *
 * Register programming, so this is per track by invariant 3 - what is
 * shared is the payload and the meaning of its fields.
 *
 * The refusal path is a real one and worth having: TSON needs the
 * sensor's startup time before the first conversion is meaningful, and
 * a converter that never raises EOC15 would otherwise spin here. The
 * loop is bounded by a conversion budget rather than by a flag.
 */
int adc_read_temp(ctl_temp_t *out, uint16_t samples)
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
	 * Whatever was enabled goes back afterwards. This runs from the
	 * control channel, which a host may poll while a capture is
	 * configured but not running, and leaving channel 15 in the
	 * sequencer would change the conversion order of the next stream -
	 * channel count divides the aggregate rate, so that is a silent
	 * change to every number a run reports.
	 */
	/*
	 * Refuse while the ADC is hardware-triggered. Reading the sensor
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

	/*
	 * The sensor's startup, spent once rather than per conversion.
	 * Datasheet 46.7.4 gives t_START for the temperature sensor; this
	 * is comfortably past it and costs 1 ms on a debug path.
	 */
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

		ADC->ADC_CR = ADC_CR_START;
		/*
		 * Bounded by time, not by the flag alone. A conversion is
		 * ~1 us; 200 us is 200x that and is the difference between
		 * "this part has no sensor" and a main loop that never
		 * returns. Invariant 7 applies to the debug path too when
		 * the debug path is reachable from a host.
		 */
		while (!(ADC->ADC_ISR & ADC_ISR_EOC15)) {
			if (micros() - t0 > 200u)
				goto done;
		}
		v = (uint16_t)(ADC->ADC_CDR[15] & ADC_CDR_DATA_Msk);
		sum += v;
		if (v < lo)
			lo = v;
		if (v > hi)
			hi = v;
		got++;
	}

done:
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
	/* x16 so the average survives the integer it is reported in: 256
	 * samples of a 4-code-rms signal resolve to ~0.25 codes, and
	 * rounding that to a whole code throws away the measurement. */
	out->code_x16 = (uint32_t)((sum * 16u) / got);
	out->code_min = lo;
	out->code_max = hi;
	out->samples  = got;
	out->channel  = 15u;
	out->reserved = 0;
	return CTL_TEMP_OK;
}
