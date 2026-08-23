/*
 * Host-fed DAC playback: HOST -> USB -> DAC.
 *
 * Mirror image of the capture ring. The host streams 16-bit half-words
 * with the DACC channel tag already in bits [13:12]; the PDC feeds them
 * to the DACC; the processor only moves indices.
 *
 * Bytes land in the playback ring directly from the endpoint FIFO, so
 * there is no staging buffer between USB and the DAC.
 *
 * The failure mode is underrun, the dual of capture overrun: the DAC
 * needs a buffer the host has not supplied yet. It is counted and
 * reported rather than concealed by repeating the previous buffer.
 */

#ifndef PLAY_H
#define PLAY_H

#include <stdint.h>
#include <stdbool.h>

/*
 * Ring depth is the margin against host scheduling gaps: the queue-
 * gated host feed loses ~1 ms per burst to empty-queue detection, and
 * the ring must carry playback across that gap at full rate. 8 slots
 * (4 KB, ~2.9 ms at the DACC ceiling) measurably starved during duplex;
 * 32 slots is ~11.8 ms at the ceiling, and 32 KB of SRAM this project
 * has nothing better to spend on.
 */
/*
 * The DACC's own ceiling, measured: RC 28 is 1,392,857 updates per
 * second and the converter needs about 54.7 MCK cycles each, so faster
 * is not a rate it can make. The trigger will happily run there and the
 * DAC will simply not keep up, which reads downstream as an underrun
 * storm rather than as a refusal.
 *
 * The ADC path has refused past its floor since bring-up. This one did
 * not, so `=1950000,200000,2P` was acknowledged rather than refused
 * until the daemon's tests went looking for the device's own words.
 */
#define PLAY_MIN_RC      28u

#define PLAY_NBUF        32
#define PLAY_BUF_SAMPLES 512
#define PLAY_BUF_BYTES   (PLAY_BUF_SAMPLES * 2)

bool play_start(uint32_t dac_hz);
void play_stop(void);
bool play_active(void);
void play_service(void);          /* drain USB OUT into the ring */
void play_dump(void);
const uint8_t *play_ring_base(void);   /* for mapping DACC_TPR to a slot */

extern volatile uint32_t play_produced;    /* buffers filled from USB */
extern volatile uint32_t play_consumed;    /* buffers handed to the PDC */
extern volatile uint32_t play_underruns;
extern volatile uint32_t play_bytes_in;
extern volatile uint32_t play_isr_calls;
extern volatile uint32_t play_endtx_seen;
extern volatile uint32_t play_svc_calls;   /* play_service entries while active */
extern volatile uint32_t play_spans;       /* OUT DMA transfers armed */
extern volatile uint32_t play_partial;     /* spans that ended off a slot edge */


#endif /* PLAY_H */
