/*
 * Host-fed DAC playback: HOST -> USB -> DAC.
 *
 * Mirror image of the capture ring. The host streams 16-bit half-words
 * with the DACC channel tag already in bits [13:12], the PDC feeds them
 * to the DACC, and the CPU only moves indices.
 *
 * Except here it also moves the bytes. Track B fills this ring by
 * endpoint DMA and never touches a sample; the Arduino CDC stack has no
 * DMA path at all, so Track A copies out of the core's receive ring one
 * byte at a time. That is the whole point of the oracle: it says what
 * the stock stack can sustain, and the difference against Track B is
 * the value of driving the controller directly.
 *
 * The failure mode is underrun, the dual of capture overrun: the DAC
 * needs a buffer the host has not supplied yet. It is counted and
 * reported rather than concealed by repeating the previous buffer, on
 * the same principle that governs the capture path.
 */

#ifndef PLAY_H
#define PLAY_H

#include <stdint.h>

/*
 * Same geometry as Track B, so the host feeds both identically: 32 KB
 * of ring is ~11.8 ms of margin at the DACC ceiling, and 512-sample
 * slots are exactly one 1 KB span of host writes.
 */
#define PLAY_NBUF         32
#define PLAY_BUF_SAMPLES  512
#define PLAY_BUF_BYTES    (PLAY_BUF_SAMPLES * 2)

bool     play_start(uint32_t dac_hz);
void     play_stop(void);
bool     play_active(void);
void     play_service(void);      /* drain USB OUT into the ring */
void     play_dump(void);
uint32_t play_configured_rc(void);
const uint8_t *play_ring_base(void);   /* for mapping DACC_TPR to a slot */

extern volatile uint32_t play_produced;    /* buffers filled from USB */
extern volatile uint32_t play_consumed;    /* buffers handed to the PDC */
extern volatile uint32_t play_underruns;
extern volatile uint32_t play_bytes_in;
extern volatile uint32_t play_isr_calls;
extern volatile uint32_t play_endtx_seen;
extern volatile uint32_t play_svc_calls;   /* play_service entries while active */

#endif /* PLAY_H */
