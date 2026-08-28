/*
 * TC-triggered ADC acquisition with PDC ping-pong.
 *
 * Shared constants live here so Track A and Track B configure the
 * hardware identically. The Atmel CMSIS headers give only _Pos/_Msk for
 * these fields, so the values are spelled out with their meanings.
 */

#ifndef ACQ_H
#define ACQ_H

#include <stdint.h>
#include <stdbool.h>

#include "ctl_wire.h"   /* ctl_temp_t: the temperature report is a wire format */

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
#define WAVSEL_UP_RC          (2u << 13)   /* count up, reset on RC */
#define ACPA_CLEAR            (2u << 16)   /* RA compare clears TIOA */
#define ACPC_SET              (1u << 18)   /* RC compare sets TIOA */

/* ADC_MR / DACC_MR trigger select: 1 = TIOA0. */
#define TRGSEL_TIOA0          (1u << 1)

#define TC_CLOCK1_HZ          (SystemCoreClock / 2u)

/* 4 buffers gives two spare while one fills and one drains. */
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
 * addresses. Identical to Track B's acq_slot_t, deliberately: the two
 * tracks share no source, so the way they stay comparable is by being
 * transliterations of each other.
 */
typedef struct __attribute__((aligned(4))) {
	uint8_t  hdr[ACQ_HDR_BYTES];
	uint16_t samples[ACQ_BUF_SAMPLES];
} acq_slot_t;

/* If the header ever grows, the frame stops being 8 x 512 bytes and
 * every short-packet rule in docs/protocol.md breaks quietly. */
static_assert(ACQ_FRAME_BYTES % 512 == 0,
              "a frame must be a whole number of 512-byte packets");

/*
 * Measured on this board: RC 86 works, RC 85 drops every other trigger
 * with no status bit set. The compare value holds across master clock
 * settings, because the timer and ADC clocks scale together. Refuse
 * anything faster rather than trusting flags that stay clear; an
 * over-fast trigger cannot be detected after the fact. See
 * docs/hardware.md.
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
 * cliff.
 */
#define ACQ_MIN_RC_1CH        44u

/* Minimum compare value for a given channel count. Measured, not derived. */
#define ACQ_MIN_RC_FOR(n)     ((n) == 1u ? ACQ_MIN_RC_1CH : ACQ_MIN_RC)

extern acq_slot_t acq_slot[ACQ_NBUF];

void     acq_init(void);
/*
 * ADC track and settling time, applied at the next acq_init() - so set
 * them before starting a stream. See acq.cpp for why they are runtime
 * values rather than build constants.
 */
extern uint8_t acq_tracktim;
extern uint8_t acq_settling;
void     acq_set_timing(uint32_t tracktim, uint32_t settling);
uint32_t acq_mr(void);             /* ADC_MR as the hardware holds it */

/*
 * Software-triggered polled reads, masked to 12 bits.
 *
 * Use these rather than the core's analogRead(): acq_init() turns on
 * ADC_EMR_TAG and analogRead() does not mask the tag out of LCDR, so it
 * returns tag|value and can return it from the wrong channel. See
 * acq.cpp.
 */
uint16_t acq_read_one(unsigned ch);
void     acq_read_pair(unsigned cha, unsigned chb,
                       uint16_t *a, uint16_t *b);

/*
 * The on-die temperature sensor, ADC channel 15 behind ADC_ACR.TSON.
 * Averages `samples` conversions (clamped to the CTL_TEMP_SAMPLES_*
 * range) and restores whatever channels were enabled. False means no
 * conversion completed, which CTL_OP_TEMP answers as CTL_ERR_OPCODE.
 *
 * ctl_temp_t carries what the reading may and may not be used to claim -
 * read it before quoting a number from here. Issue #11.
 */
bool     acq_read_temp(ctl_temp_t *out, uint16_t samples);

/*
 * A0 is AD7, A1 is AD6, A2 is AD5 - the Arduino A0..A7 labels map to
 * AD7..AD0, descending, so nothing here may assume A0 == AD0. The
 * sequencer converts enabled channels in ascending channel-index order,
 * which is not label order either; the channel tag in LCDR[15:12] is
 * what the host demultiplexes on, so it never has to be assumed.
 *
 * In the header because the console prints which pair is selected and
 * would otherwise spell the index a second time.
 */
#define ACQ_CH_A0  7u
#define ACQ_CH_A1  6u
#define ACQ_CH_A2  5u

/*
 * Which channel pairs with A0 in a two-channel capture: ADC channel
 * index, A1 by default and A2 on request. Applied at the next
 * acq_start(). See acq.cpp for why the pair rather than the sequencer.
 */
extern uint8_t acq_pair_second;
void     acq_set_pair(uint32_t a_number);

bool     acq_start(uint32_t trigger_hz, unsigned n_channels);
void     acq_stop(void);
uint32_t acq_configured_rc(void);
uint16_t acq_channel_mask(void);   /* ADC channel indices now enabled */

/* Counters, all updated from the ADC ISR. */
extern volatile uint32_t acq_buffers_done;
extern volatile uint32_t acq_rxbuff_overruns;
extern volatile uint32_t acq_govre;

/*
 * Producer/consumer ring. acq_produced is written only by the ISR and
 * acq_consumed only by the main loop, so 32-bit aligned reads make the
 * pair safe without disabling interrupts.
 *
 * acq_ring_overflow counts the case that matters: the ISR lapping the
 * consumer, i.e. samples overwritten before they were sent.
 */
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
