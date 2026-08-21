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

/* TC_CMR fields. TIMER_CLOCK1 is MCK/2 = 42 MHz. */
#define TCCLKS_TIMER_CLOCK1   (0u << 0)
#define WAVSEL_UP_RC          (2u << 13)   /* count up, reset on RC */
#define ACPA_CLEAR            (2u << 16)   /* RA compare clears TIOA */
#define ACPC_SET              (1u << 18)   /* RC compare sets TIOA */

/* ADC_MR / DACC_MR trigger select: 1 = TIOA0. */
#define TRGSEL_TIOA0          (1u << 1)

#define TC_CLOCK1_HZ          (SystemCoreClock / 2u)

/* 4 buffers gives two spare while one fills and one drains. */
#define ACQ_NBUF              4
#define ACQ_BUF_SAMPLES       2032        /* 4064 B payload + 32 B header = 8 x 512 */

extern uint16_t acq_buf[ACQ_NBUF][ACQ_BUF_SAMPLES];

void     acq_init(void);
void     acq_start(uint32_t trigger_hz);
void     acq_stop(void);
uint32_t acq_configured_rc(void);

/* Counters, all updated from the ADC ISR. */
extern volatile uint32_t acq_buffers_done;
extern volatile uint32_t acq_rxbuff_overruns;
extern volatile uint32_t acq_govre;

#endif /* ACQ_H */
