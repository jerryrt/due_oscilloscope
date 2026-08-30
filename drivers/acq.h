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

#include "frame.h"

#define ACQ_NBUF              4
/* The geometry is the wire contract and lives in the shared frame.h,
 * which derives the header size from the struct and carries the
 * 512-byte assert. These are the track-local spellings of it. */
#define ACQ_BUF_SAMPLES       FRAME_SAMPLES
#define ACQ_HDR_BYTES         FRAME_HDR_BYTES
#define ACQ_FRAME_BYTES       FRAME_BYTES

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

/*
 * Three channels, for the issue #5 impedance rig on A2. **Provisional -
 * derived, not measured**, which is exactly what the note above says not
 * to do, so it is deliberately conservative rather than tight: 906,976
 * conversions per second over three channels is 302,325 triggers, RC
 * 129, and this rounds up. The measured floor belongs here as soon as
 * the sweep has been run; nothing in the rig needs the top of the range,
 * which is why the placeholder is safe to work behind. *(check)*
 */
#define ACQ_MIN_RC_3CH        132u

/* Minimum compare value for a given channel count. Measured, not derived. */
#define ACQ_MIN_RC_FOR(n)     ((n) == 1u ? ACQ_MIN_RC_1CH :   \
                               (n) == 3u ? ACQ_MIN_RC_3CH : ACQ_MIN_RC)

extern acq_slot_t acq_slot[ACQ_NBUF];

/* ADC track/settling time, applied at the next acq_init(). See acq.c. */
extern uint8_t acq_tracktim;
extern uint8_t acq_settling;
void acq_set_timing(uint32_t tracktim, uint32_t settling);

/* Which channel joins A0 in a two-channel capture. See acq.c. */
extern uint8_t acq_pair_second;
void acq_set_pair(uint32_t a_number);

void     acq_init(void);
bool     acq_start(uint32_t trigger_hz, unsigned n_channels);
void     acq_stop(void);
uint32_t acq_configured_rc(void);
uint16_t acq_channel_mask(void);   /* ADC channel indices now enabled */
uint32_t acq_mr(void);             /* ADC_MR as the hardware holds it */

extern volatile uint32_t acq_buffers_done;
extern volatile uint32_t acq_rxbuff_overruns;
extern volatile uint32_t acq_govre;
extern volatile uint32_t acq_produced;
extern volatile uint32_t acq_consumed;
extern volatile uint32_t acq_ring_overflow;

/*
 * Real functions, not static inlines, since the framer moved to
 * lib/due_shared (issue #14): the shared file cannot include this
 * header, so it links against these through stream_port.h's identical
 * declarations. They run once per frame; inlining never mattered.
 */
bool acq_frame_available(void);
const uint16_t *acq_frame_data(void);
/* The whole frame - header headroom first - for a single DMA. */
uint8_t *acq_frame_bytes(void);
void acq_frame_release(void);

/*
 * Capture-side completion trace, off by default (issue #44).
 *
 * windows-desk asked for the one thing every host-side instrument on
 * #44 is blind to: whether a lost frame is the converter falling behind
 * or the transfer failing to collect it. `timestamp_us` in the frame
 * header cannot separate those - it is taken when the frame is queued
 * for USB, so a late conversion and a late transfer look the same.
 *
 * So this records, per completed PDC buffer:
 *
 *   acq_trace_us   micros() at ENDRX, which is the conversion side
 *   acq_trace_occ  acq_produced - acq_consumed at that same instant,
 *                  so a run that loses frames can be read for whether
 *                  the ring was full when it happened
 *
 * Same shape as play.h's PLAY_RATE_TRACE and for the same reasons: a
 * fixed array, a saturating count, written in the ISR and drained by
 * `Q` after the run. Never printed during it - invariant 6, and
 * h_mimic's pattern.
 *
 * Off by default because it perturbs the path it measures. One micros()
 * per completed buffer is ~1.4 us against a 2.24 ms buffer at the full
 * rate, so 0.06% - but "small" is not "free", and the play trace made
 * the same call. Build with -DACQ_RATE_TRACE_ENABLED=1.
 */
#ifndef ACQ_RATE_TRACE_ENABLED
#define ACQ_RATE_TRACE_ENABLED 0
#endif

#define ACQ_RATE_TRACE 256

extern volatile uint32_t acq_trace_us[ACQ_RATE_TRACE];
extern volatile uint8_t  acq_trace_occ[ACQ_RATE_TRACE];
extern volatile uint32_t acq_traced;   /* entries written, saturating */

#endif /* ACQ_H */
