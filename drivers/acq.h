/*
 * TC-triggered ADC acquisition with PDC ping-pong (Track B).
 *
 * Register configuration is identical to sketches/bringup/acq.cpp, which
 * was verified on hardware first. Keeping them in step is the point: a
 * difference in measured behaviour should mean a real difference, not a
 * different configuration.
 */

#ifndef ACQ_H
#define ACQ_H

#include <stdint.h>
#include <stdbool.h>

/* TC_CMR fields. TIMER_CLOCK1 is MCK/2 = 42 MHz. */
#define TCCLKS_TIMER_CLOCK1   (0u << 0)
#define WAVSEL_UP_RC          (2u << 13)
#define ACPA_CLEAR            (2u << 16)
#define ACPC_SET              (1u << 18)

/* ADC_MR / DACC_MR trigger select: 1 = TIOA0. */
#define TRGSEL_TIOA0          (1u << 1)

#define ACQ_NBUF              4
#define ACQ_BUF_SAMPLES       2032   /* 4064 B payload + 32 B header = 8 x 512 */

/*
 * Measured on this board: RC 86 works, RC 85 drops every other trigger
 * with no status bit set. Refuse anything faster rather than trusting
 * flags that stay clear. See docs/hardware.md.
 */
#define ACQ_MIN_RC            86u

extern uint16_t acq_buf[ACQ_NBUF][ACQ_BUF_SAMPLES];

void     acq_init(void);
bool     acq_start(uint32_t trigger_hz, unsigned n_channels);
void     acq_stop(void);
uint32_t acq_configured_rc(void);

extern volatile uint32_t acq_buffers_done;
extern volatile uint32_t acq_rxbuff_overruns;
extern volatile uint32_t acq_govre;
extern volatile uint32_t acq_produced;
extern volatile uint32_t acq_consumed;
extern volatile uint32_t acq_ring_overflow;

static inline bool acq_frame_available(void)
{
	return acq_produced != acq_consumed;
}

static inline const uint16_t *acq_frame_data(void)
{
	return acq_buf[acq_consumed % ACQ_NBUF];
}

static inline void acq_frame_release(void)
{
	acq_consumed++;
}

#endif /* ACQ_H */
