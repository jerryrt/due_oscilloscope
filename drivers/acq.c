#include "sam.h"
#include "acq.h"
#include "analog.h"

uint16_t acq_buf[ACQ_NBUF][ACQ_BUF_SAMPLES];

volatile uint32_t acq_buffers_done;
volatile uint32_t acq_rxbuff_overruns;
volatile uint32_t acq_govre;
volatile uint32_t acq_produced;
volatile uint32_t acq_consumed;
volatile uint32_t acq_ring_overflow;

static volatile uint32_t filling;
static uint32_t configured_rc;
static uint16_t configured_mask = (1u << ADC_CH_A0) | (1u << ADC_CH_A1);

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
	TC0->TC_CHANNEL[0].TC_RA = rc / 2u;
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

	/*
	 * ADCClock = MCK / ((PRESCAL+1) * 2) = 84/4 = 21 MHz, which is ABOVE
	 * the 20 MHz maximum in datasheet Table 46-28. The prescaler is
	 * coarse: PRESCAL=2 gives 14 MHz and is in spec, at roughly 650 ksps
	 * aggregate instead of 976,744. Deliberate; see docs/hardware.md.
	 */
	ADC->ADC_MR = ADC_MR_PRESCAL(1)
	            | (0xfu << ADC_MR_STARTUP_Pos)
	            | ADC_MR_TRACKTIM(0)
	            | (0u << ADC_MR_SETTLING_Pos)
	            | (1u << ADC_MR_TRANSFER_Pos);

	ADC->ADC_EMR = ADC_EMR_TAG;
	ADC->ADC_CHDR = 0xffffu;
	ADC->ADC_CHER = (1u << ADC_CH_A0) | (1u << ADC_CH_A1);
}

bool acq_start(uint32_t trigger_hz, unsigned n_channels)
{
	uint32_t tc_clock = SystemCoreClock / 2u;
	uint32_t rc;

	if (trigger_hz == 0)
		return false;

	rc = tc_clock / trigger_hz;

	/*
	 * The ADC ignores a trigger that arrives before it is ready and sets
	 * no flag when it does, so an over-fast rate looks like clean data
	 * at half the frequency. Refuse it here; it cannot be detected
	 * later.
	 *
	 * The floor scales with channel count because the constraint is
	 * conversions per second, not triggers: one channel may be
	 * triggered twice as fast as two for the same converter load.
	 */
	if (n_channels == 0 || n_channels > 2)
		return false;
	if (rc < ACQ_MIN_RC_FOR(n_channels))
		return false;

	acq_stop();

	/*
	 * Single channel captures A0 alone at the full conversion rate.
	 * The sequencer converts enabled channels in ascending index
	 * order, and the tag in each sample names the channel, so the host
	 * demultiplexes without being told which mode this is.
	 */
	configured_mask = (n_channels == 1)
	                ? (uint16_t)(1u << ADC_CH_A0)
	                : (uint16_t)((1u << ADC_CH_A0) | (1u << ADC_CH_A1));
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

	ADC->ADC_RPR  = (uint32_t)acq_buf[0];
	ADC->ADC_RCR  = ACQ_BUF_SAMPLES;
	ADC->ADC_RNPR = (uint32_t)acq_buf[1];
	ADC->ADC_RNCR = ACQ_BUF_SAMPLES;

	(void)ADC->ADC_ISR;
	ADC->ADC_IDR = 0xffffffff;
	ADC->ADC_IER = ADC_IER_ENDRX | ADC_IER_RXBUFF;

	NVIC_ClearPendingIRQ(ADC_IRQn);
	NVIC_SetPriority(ADC_IRQn, 0);
	NVIC_EnableIRQ(ADC_IRQn);

	ADC->ADC_PTCR = ADC_PTCR_RXTEN;
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

void ADC_Handler(void)
{
	uint32_t status = ADC->ADC_ISR;

	if (status & ADC_ISR_GOVRE)
		acq_govre++;

	if (status & ADC_ISR_RXBUFF)
		acq_rxbuff_overruns++;

	if (status & ADC_ISR_ENDRX) {
		filling = (filling + 1u) % ACQ_NBUF;
		ADC->ADC_RNPR = (uint32_t)acq_buf[(filling + 1u) % ACQ_NBUF];
		ADC->ADC_RNCR = ACQ_BUF_SAMPLES;
		acq_buffers_done++;

		if (acq_produced - acq_consumed >= ACQ_NBUF - 1u)
			acq_ring_overflow++;
		acq_produced++;
	}
}
