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
 * The placement needs linker/arduino_due_x_sram1.ld, passed with
 * --build-property build.ldscript=... - see tools/sketch.sh. Building
 * without it puts this in .bss, which still links and still runs.
 */
acq_slot_t acq_slot[ACQ_NBUF] __attribute__((section(".sram1")));

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

void acq_init(void)
{
	PMC->PMC_PCER1 = (1u << (ID_ADC - 32));

	ADC->ADC_CR = ADC_CR_SWRST;

	/* ADCClock = MCK / ((PRESCAL+1) * 2) = 84/4 = 21 MHz, under the
	 * ABOVE the 20 MHz datasheet maximum (Table 46-28); see
	 * docs/hardware.md. Minimal tracking: this is the fast path, and the
	 * crosstalk cost of that is a thing to be measured, not avoided. */
	ADC->ADC_MR = ADC_MR_PRESCAL(1)
	            | (0xfu << ADC_MR_STARTUP_Pos)
	            | ADC_MR_TRACKTIM(0)
	            | (0u << ADC_MR_SETTLING_Pos)
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
