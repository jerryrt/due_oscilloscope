/*
 * Host-fed DAC playback: HOST -> USB -> DAC.
 *
 * Mirror image of the capture ring. The host streams 16-bit half-words
 * with the DACC channel tag already in bits [13:12], the PDC feeds them
 * to the DACC, and the CPU only moves indices.
 *
 * The ring is filled by UOTGHS endpoint DMA, the same mechanism Track B
 * uses, so the processor never touches a sample here either. The
 * Arduino core keeps enumeration and control transfers; only the bulk
 * data path is taken over. See usbdma.h for how that coexists with a
 * stack that rebuilds its endpoints behind your back.
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
extern volatile uint32_t play_spans;       /* OUT DMA transfers armed */
extern volatile uint32_t play_partial;     /* spans that ended off a slot edge */
extern volatile uint32_t play_consumed;    /* buffers handed to the PDC */
extern volatile uint32_t play_underruns;
extern volatile uint32_t play_bytes_in;
extern volatile uint32_t play_isr_calls;
extern volatile uint32_t play_endtx_seen;
extern volatile uint32_t play_svc_calls;   /* play_service entries while active */

/*
 * Occupancy, sampled by the device at every ENDTX. Ported from
 * drivers/play.c, same names, same decimation, same output format -
 * docs/control-protocol.md and the suite both require the two tracks to
 * be indistinguishable here, and the whole point of the oracle is that
 * a number means the same thing on both.
 *
 * Why on the device and not on the host: at the top of the AWG ladder
 * the ring holds a few slots, and polling `B` at 20 Hz to watch it took
 * a run from 6 underruns to 30. Where you most want to observe,
 * observing is what breaks it.
 */
extern volatile uint32_t play_occ_hist[PLAY_NBUF];
extern volatile uint32_t play_occ_min;     /* fewest slots ever seen at ENDTX */

#define PLAY_OCC_TRACE  256
#define PLAY_OCC_DECIM  16
extern volatile uint8_t  play_occ_trace[PLAY_OCC_TRACE];
extern volatile uint32_t play_occ_traced;  /* entries written, saturating */

/*
 * Microseconds since the DAC's timer started, which is not the same as
 * since the host asked: the ring primes first. The device timing its
 * own run is what showed the host and the device agreeing to 0.02% and
 * took the clock off the suspect list.
 */
extern volatile uint32_t play_run_us;

#endif /* PLAY_H */
