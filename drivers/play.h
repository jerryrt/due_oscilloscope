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
 * second and the converter needs about 54.7 MCK cycles each, so
 * faster is not a rate it can make. The trigger will happily run
 * there and the DAC will simply not keep up, which reads downstream
 * as an underrun storm rather than as a refusal.
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
/* Times playback stopped itself because nothing arrived for
 * PLAY_ABANDON_MS. Non-zero means a host went away mid-run - which used
 * to leave bulk OUT undrained and hang that host in close(). */
extern volatile uint32_t play_abandoned;
extern volatile uint32_t play_bytes_in;
extern volatile uint32_t play_isr_calls;
extern volatile uint32_t play_endtx_seen;
extern volatile uint32_t play_svc_calls;   /* play_service entries while active */
extern volatile uint32_t play_spans;       /* OUT DMA transfers armed */
extern volatile uint32_t play_partial;     /* spans that ended off a slot edge */

/*
 * Ring occupancy sampled at the instant that decides an underrun.
 * The host could ask over the console during a run instead, but at
 * the rates where the ring is short that costs more underruns than
 * it measures - so the device keeps its own distribution, one array
 * increment in the ENDTX path, read out afterwards with `O`.
 *
 * Indexed by occupancy in slots, saturating at the top bucket.
 */
extern volatile uint32_t play_occ_hist[PLAY_NBUF];
extern volatile uint32_t play_occ_min;     /* fewest slots ever seen at ENDTX */

/*
 * A decimated trace of the same quantity, because the histogram cannot
 * answer the question that matters: whether a run starts deep and
 * decays, or never fills at all. Every PLAY_OCC_DECIM-th ENDTX, so 256
 * entries span 4096 buffers - the whole of a 3 s run at the low rates
 * and all of the startup transient at the high ones.
 */
#define PLAY_OCC_TRACE  256
#define PLAY_OCC_DECIM  16

extern volatile uint8_t  play_occ_trace[PLAY_OCC_TRACE];
extern volatile uint32_t play_occ_traced;  /* entries written, saturating */

/*
 * Microseconds the converter has actually been running, by the device's
 * own clock, measured from the instant the trigger was started.
 *
 * Without it the device's true consumption rate can only be inferred
 * from the host's clock, which is the very comparison in question: a
 * feed that tracks the host's idea of the rate drains the ring at a
 * fraction of a percent, and there is no way to tell a slow host from a
 * fast device without asking each to time itself.
 */
extern volatile uint32_t play_run_us;

/*
 * A decimated trace of the converter's own clock, so the rate can be
 * read *within* a run and not only across one - play_run_us over
 * play_consumed cannot tell a converter that held one rate from one
 * that changed state part-way through.
 *
 * Sampled every PLAY_RATE_DECIM-th *consumed* buffer rather than
 * every ENDTX, so a window is exactly PLAY_RATE_DECIM buffers of data
 * regardless of underruns inside it. Absolute microseconds, not
 * deltas, so the span stays exact even if one sample is disturbed.
 * micros() is safe in the ENDTX handler because SysTick stays at
 * reset priority 0 while DACC is priority 1, so this handler cannot
 * hold off the tick it reads.
 *
 * OFF by default, and that is a correctness decision, not a cost one:
 * sampling micros() inside the ENDTX handler perturbs the
 * timing-critical window it measures and has produced forward-jump
 * corruption on the ramp test. Turn it on for an investigation only;
 * do not judge sample integrity on a build that has it on.
 */
#ifndef PLAY_RATE_TRACE_ENABLED
#define PLAY_RATE_TRACE_ENABLED 0
#endif

#define PLAY_RATE_TRACE 256
#define PLAY_RATE_DECIM 32u

extern volatile uint32_t play_rate_us[PLAY_RATE_TRACE];
extern volatile uint32_t play_rate_traced;  /* entries written, saturating */


#endif /* PLAY_H */
