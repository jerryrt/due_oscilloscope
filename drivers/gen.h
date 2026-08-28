#ifndef GEN_H
#define GEN_H
#include <stdint.h>
#include <stdbool.h>

#include "ctl_wire.h"   /* the generator's value space, shared */

/*
 * The table this track's PDC actually walks. The point count is the
 * contract's GEN_TABLE_POINTS; the buffer, the builder and every
 * register below are this track's own - invariant 3 keeps gen internals
 * independent so that two programmings of one converter disagreeing
 * points at one of them.
 */
#define GEN_SINE_POINTS GEN_TABLE_POINTS
#define GEN_TABLE_LEN   (GEN_SINE_POINTS * 2)

/*
 * What build_table() puts on each DAC, selected at runtime.
 *
 * One image and one code path for every arm, because the binary selects
 * which state issue #5 draws: two builds would change the layout as
 * well as the waveform, and an absent artifact in the second arm could
 * not be read. The table lives in RAM and is rebuilt by gen_init(),
 * which the M preset calls before every capture, so this costs nothing
 * but a branch.
 *
 * NORMAL     sine on DAC0, DC on DAC1 - what this project has always run
 * SWAPPED    DC on DAC0, sine on DAC1 - is it DAC1, or a DAC pin?
 * TWOCYCLE   two sine periods in the same table - separates the PDC
 *            reload at the wrap from the waveform, which have been the
 *            same event in every build so far
 * DC         no sine anywhere - is a swinging output needed at all?
 *
 * Every arm keeps DAC0 on even slots and DAC1 on odd, so a swap moves
 * the values and not the update timing.
 */
#define GEN_LAYOUT_NORMAL    0u
#define GEN_LAYOUT_SWAPPED   1u
#define GEN_LAYOUT_TWOCYCLE  2u
#define GEN_LAYOUT_DC        3u

/* DACC output-stage bias. Applied after every DACC_CR_SWRST. See gen.c. */
/*
 * The datasheet's characterisation condition, and the default.
 *
 * Tables 46-38 and 46-40 specify every published DAC figure - INL, DNL,
 * SNR, THD, SINAD - at IBCTLDACCORE=01 with IBCTLCHx=10. Anything else
 * is the part running outside the conditions its own numbers describe.
 *
 * **These were 0 until 2026-08-28, and that was worse than not writing
 * ACR at all.** Measured on Track B, which has no Arduino core anywhere
 * in the image: a booted board that has never written ACR reads
 * 0x000001AA, and 0x1AA decodes to IBCTLCH0=2, IBCTLCH1=2,
 * IBCTLDACCORE=1 - the characterised condition already - plus bits 5
 * and 7, which the SAM3X datasheet does not define. So gen_apply_acr()
 * with a zero default was not the no-op it looked like: it moved the
 * converter *off* the characterised bias every time gen_init() ran,
 * which is every capture.
 *
 * Writing 2/1 gives 0x10A: the same three defined fields as the
 * untouched value, with bits 5 and 7 cleared. Whether those two matter
 * is not known here and is not claimed - what is known is that 0x10A is
 * the documented condition and 0x000 is not.
 */
#define GEN_IBCTL_CH_CHARACTERISED    2u
#define GEN_IBCTL_CORE_CHARACTERISED  1u

extern uint8_t gen_ibctl_ch;
extern uint8_t gen_ibctl_core;
void     gen_set_ibctl(uint32_t ch, uint32_t core);
void     gen_apply_acr(void);
uint32_t gen_acr(void);

extern uint8_t gen_layout;
void gen_set_layout(uint32_t layout);

/*
 * Shape, the second axis, and orthogonal to layout on purpose.
 *
 * gen_layout answers "which pin, and where does the PDC wrap fall" and
 * every one of its arms is an issue-#5 experiment whose results are
 * recorded against it. Shape answers "what does the converter emit".
 * Keeping them separate means the swapped and two-cycle diagnostics
 * still run, and now run against something other than a sine.
 *
 * Integer tables only. The M3 has no FPU and this file hand-rolls a
 * fixed-point sine specifically to keep the soft-float library out of
 * the image; square, ramp and triangle are integer by construction, so
 * the shape axis costs nothing that the sine has not already paid.
 *
 * GEN_SHAPE_DC and GEN_LAYOUT_DC overlap and are not the same thing:
 * the layout arm puts a level on *both* pins as an issue-#5 control,
 * the shape puts a level on the one the layout selected. An AWG whose
 * shape list has a hole in it is the more confusing of the two.
 */
extern uint8_t gen_shape;
void gen_set_shape(uint32_t shape);

/*
 * Resolution: points per cycle, and the frequency ceiling that follows.
 *
 * This is the trade a bench AWG makes and it is not hidden here. The
 * table is GEN_SINE_POINTS long and the trigger clocks one point per
 * update, so a cycle takes `gen_points` updates and the output is
 *
 *     f = trigger_hz / (2 * gen_points)
 *
 * - the 2 because DACC TAG mode interleaves DAC0 and DAC1, so half of
 * every update belongs to the other channel. Fewer points is a coarser
 * staircase and a proportionally higher frequency; more points is a
 * smoother waveform that takes proportionally longer to get through one
 * cycle. Nothing about the converter changes: the update rate is fixed
 * by the trigger, and resolution decides how many updates a cycle
 * spends.
 *
 * It must *divide* GEN_SINE_POINTS. The table wraps at 256 points and
 * the PDC restarts it there; a resolution that does not divide 256
 * leaves a partial cycle at the wrap, which is a phase step in the
 * analog output once per reload - the exact defect invariant 5 exists
 * to refuse. So 2, 4, 8, 16, 32, 64, 128, 256 and nothing else.
 *
 * Default 256, which is what this project has always run, so no
 * existing measurement moves.
 *
 * The trap, and it is a real one. The host's issue-#5 instruments -
 * fold_profile() and pair_fold() in host/measure.py - fold the capture
 * at GEN_TABLE_LEN because that has been the generator's period in
 * every build. Change the resolution and that assumption is wrong: the
 * fold period becomes 2 * gen_points. Do not read an issue-#5 sweep
 * taken at a resolution other than 256 without saying so.
 */

/*
 * The sync output: a trigger for the bench, on the channel that is not
 * carrying the waveform.
 *
 * Why it exists, measured. Triggering a scope on the signal itself
 * turns amplitude noise into time jitter by dividing it by the slew
 * rate at the trigger level - about 20 mV sits on a DAC pin here, 15 mV
 * of it with the DAC not driven at all, and a ramp rising 4.5 mV per
 * sample therefore shakes 27 us where a square does not shake at all.
 * `docs/awg.md` has the full slope experiment. A sync is a full-scale
 * step every time, so the same noise buys almost no jitter, and the
 * signal channel is then measured rather than being asked to trigger as
 * well.
 *
 * It is phase-locked by construction and not by adjustment: DACC TAG
 * mode feeds both channels from one PDC stream clocked by one trigger,
 * so the sync cannot drift against the waveform. It lags it by exactly
 * one trigger period - the interleave - which is a fixed offset and a
 * measurable one.
 *
 * OFF     the channel holds mid scale. This is the demultiplexing arm
 *         this project has always run: a waveform appearing there means
 *         the channel tags are being read wrong.
 * CYCLE   50% square, one cycle per waveform cycle, rising at phase 0.
 *         The default, and a *better* demux check than OFF: a flat line
 *         is also what a channel nobody writes looks like, so DC cannot
 *         tell "correctly holding 2048" from "not driven". A square
 *         proves the channel is alive and correctly tagged.
 * WRAP    50% square, one cycle per table wrap. Identical to CYCLE at
 *         the default resolution and different at every other, because
 *         the wrap is the PDC reload rather than the waveform - which
 *         is the event issue #5 locks to.
 *
 * 50% duty rather than a narrow pulse, and that is a bench decision.
 * The scope's EXT trigger input tops out at 1.2 V here while the DAC
 * sits at 0.52-2.82 V, so the trigger must be AC coupled to be usable
 * at all - and AC coupling makes a narrow pulse's baseline droop with
 * its duty cycle, moving the effective threshold. A square does not
 * droop.
 *
 * GEN_LAYOUT_DC ignores this. That arm exists so that nothing swings on
 * either pin, and a sync square would defeat the control it is.
 */
extern uint16_t gen_amp;      /* 1..256, 256 = full scale */
void gen_set_amp(uint32_t amp);

extern uint16_t gen_sync_amp;  /* 1..256, the sync's own swing */
void gen_set_sync_amp(uint32_t amp);

extern uint8_t gen_sync;
void gen_set_sync(uint32_t mode);

/* The rate clocking the converter right now, read back from DACC_MR and
 * the TC channel it names; 0 when nothing is. Never a stored echo. */
uint32_t gen_trigger_hz(void);

extern uint16_t gen_points;
void gen_set_points(uint32_t points);

void     gen_init(void);
void     gen_start(void);
void     gen_prepare_tioa1(uint32_t dac_hz);  /* DACC + TC1 config, clock off */
void     gen_go_tioa1(void);                  /* start the TC1 clock */
/*
 * Drive the DACC from TC0 channel 1 (TIOA1) instead of the ADC's TIOA0,
 * so the DAC update rate can be swept independently of acquisition.
 * gen_configured_rc() is the compare value the timer actually holds.
 */
bool     gen_start_independent(uint32_t dac_hz);
uint32_t gen_configured_rc(void);

void     gen_stop(void);
extern volatile uint32_t gen_endtx_count;

void gen_endtx(void);   /* dispatched from DACC_Handler */
#endif
