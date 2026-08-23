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

/*
 * TC_CMR fields.
 *
 * TIMER_CLOCK1 is MCK/2, so 39 MHz at the MCK 78 this project runs -
 * not the 42 MHz an earlier version of this comment claimed from the
 * 84 MHz era. Every RC figure here divides 39 MHz: RC 86 is 453,488 Hz,
 * RC 44 is 886,363. The stale number made the arithmetic look wrong.
 *
 * The trigger is TIOA0 from TC0 channel 0 in waveform mode: the counter
 * counts up and resets on RC compare, so trigger rate = 39 MHz / RC,
 * with RA at RC/2 for a 50% duty edge. Rates are held in RC rather than
 * Hz because RC is what the hardware has, and because the ADC and timer
 * clocks both scale with MCK - which is why the measured cliffs sit at
 * a fixed RC whatever MCK is set to.
 */
#define TCCLKS_TIMER_CLOCK1   (0u << 0)
#define WAVSEL_UP_RC          (2u << 13)
#define ACPA_CLEAR            (2u << 16)
#define ACPC_SET              (1u << 18)

/* ADC_MR / DACC_MR trigger select: 1 = TIOA0, 2 = TIOA1. */
#define TRGSEL_TIOA0          (1u << 1)
#define TRGSEL_TIOA1          (2u << 1)

#define ACQ_NBUF              4
#define ACQ_BUF_SAMPLES       2032   /* 4064 B payload + 32 B header = 8 x 512 */
#define ACQ_HDR_BYTES         32     /* sizeof(frame_header_t) */
#define ACQ_FRAME_BYTES       (ACQ_HDR_BYTES + ACQ_BUF_SAMPLES * 2)

/*
 * A capture buffer with its frame header in front of it.
 *
 * The header sits in the same allocation as the payload, immediately
 * before it, so a finished frame is 4096 contiguous bytes and the USB
 * DMA can send it in one transfer. The PDC is pointed at `samples` and
 * never touches `hdr`; the processor writes `hdr` and never touches
 * `samples`. That is invariant 1 expressed in a struct: the only thing
 * the CPU does to a sample is decide which buffer it lives in.
 *
 * Aligned to 4 because both the PDC and the UOTGHS DMA want word
 * addresses.
 */
typedef struct __attribute__((aligned(4))) {
	uint8_t  hdr[ACQ_HDR_BYTES];
	uint16_t samples[ACQ_BUF_SAMPLES];
} acq_slot_t;

/* If the header ever grows, the frame stops being 8 x 512 bytes and
 * every short-packet rule in docs/protocol.md breaks quietly. */
_Static_assert(ACQ_FRAME_BYTES % 512 == 0,
               "a frame must be a whole number of 512-byte packets");

/*
 * Measured on this board: with two channels enabled, RC 86 works and
 * RC 85 drops every other trigger with no status bit set. Refuse
 * anything faster rather than trusting flags that stay clear. See
 * docs/hardware.md.
 *
 * The real limit is the conversion rate, not the trigger rate: each
 * trigger converts every enabled channel back to back, so the floor
 * scales with channel count. ACQ_MIN_RC is the two-channel value, and
 * acq_start scales it - one channel may trigger twice as fast for the
 * same 906,976 conversions per second.
 */
#define ACQ_MIN_RC            86u

/*
 * And measured again for one channel: RC 44 gives ratio 1.000, RC 43
 * gives 0.500 - every other trigger dropped, no status bit set.
 *
 * Note it is NOT half of 86. One channel tops out at 886,363
 * conversions per second against 906,976 for two, because a two-channel
 * trigger converts its pair back to back and amortises the per-trigger
 * overhead that a single conversion pays in full. Scaling the
 * two-channel floor arithmetically gives 43 and walks straight off the
 * cliff, which is what the first version of this did.
 */
#define ACQ_MIN_RC_1CH        44u

/* Minimum compare value for a given channel count. Measured, not derived. */
#define ACQ_MIN_RC_FOR(n)     ((n) == 1u ? ACQ_MIN_RC_1CH : ACQ_MIN_RC)

extern acq_slot_t acq_slot[ACQ_NBUF];

void     acq_init(void);
bool     acq_start(uint32_t trigger_hz, unsigned n_channels);
void     acq_stop(void);
uint32_t acq_configured_rc(void);
uint16_t acq_channel_mask(void);   /* ADC channel indices now enabled */

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
	return acq_slot[acq_consumed % ACQ_NBUF].samples;
}

/* The whole frame - header headroom first - for a single DMA. */
static inline uint8_t *acq_frame_bytes(void)
{
	return acq_slot[acq_consumed % ACQ_NBUF].hdr;
}

static inline void acq_frame_release(void)
{
	acq_consumed++;
}

#endif /* ACQ_H */
