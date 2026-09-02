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
 * What build_table() puts on each DAC, selected at runtime rather
 * than at build time so that one binary covers every arm - a
 * separately built image would change the layout as well as the
 * waveform. The table lives in RAM and is rebuilt by gen_init(),
 * which the M preset calls before every capture.
 *
 * NORMAL     sine on DAC0, DC on DAC1 - what this project has always run
 * SWAPPED    DC on DAC0, sine on DAC1
 * TWOCYCLE   two sine periods in the same table, separating the PDC
 *            reload at the wrap from the waveform
 * DC         no sine anywhere
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
 * The datasheet's characterisation condition, and the default. Tables
 * 46-38 and 46-40 specify every published DAC figure at
 * IBCTLDACCORE=01 with IBCTLCHx=10; anything else runs outside the
 * conditions its own numbers describe.
 *
 * Not the same as the reset default: a booted board that has never
 * written ACR reads 0x1AA (IBCTLCH0=2, IBCTLCH1=2, IBCTLDACCORE=1,
 * plus two bits the datasheet leaves undefined), so writing 0 here
 * would not be a no-op - it would move the converter off the
 * characterised bias on every gen_init(). Writing 2/1 gives 0x10A,
 * the same three defined fields with the two undefined bits cleared.
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
 * Shape, the second axis, and orthogonal to layout on purpose:
 * gen_layout answers "which pin, and where does the PDC wrap fall",
 * shape answers "what does the converter emit". Keeping them separate
 * means the swapped and two-cycle diagnostics run against any shape.
 *
 * Integer tables only - the M3 has no FPU, so this file hand-rolls a
 * fixed-point sine to keep the soft-float library out of the image;
 * square, ramp and triangle are integer by construction.
 *
 * GEN_SHAPE_DC and GEN_LAYOUT_DC overlap and are not the same thing:
 * the layout arm puts a level on *both* pins, the shape puts a level
 * on the one the layout selected.
 */
extern uint8_t gen_shape;
void gen_set_shape(uint32_t shape);

/*
 * Resolution: points per cycle, and the frequency ceiling that
 * follows. The table is GEN_SINE_POINTS long and the trigger clocks
 * one point per update, so a cycle takes `gen_points` updates and the
 * output is
 *
 *     f = trigger_hz / (2 * gen_points)
 *
 * - the 2 because DACC TAG mode interleaves DAC0 and DAC1, so half of
 * every update belongs to the other channel. The update rate is fixed
 * by the trigger; resolution decides how many updates a cycle spends.
 *
 * It must *divide* GEN_SINE_POINTS: the table wraps at 256 points and
 * the PDC restarts it there, and a resolution that does not divide
 * 256 leaves a partial cycle at the wrap - a phase step in the analog
 * output once per reload, the exact defect invariant 5 refuses. So 2,
 * 4, 8, 16, 32, 64, 128, 256 and nothing else. Default 256.
 *
 * Changing it moves the fold period a host-side instrument assumes:
 * fold_profile() and pair_fold() in host/measure.py fold the capture
 * at GEN_TABLE_LEN, which is only correct at the default resolution -
 * the true fold period is 2 * gen_points.
 */

/*
 * The sync output: a trigger for the bench, on the channel that is
 * not carrying the waveform. Triggering a scope on the signal itself
 * turns amplitude noise into time jitter by dividing it by the slew
 * rate at the trigger level (~20 mV sits on a DAC pin here); a sync's
 * full-scale step buys almost no jitter instead. See docs/awg.md.
 *
 * Phase-locked by construction: DACC TAG mode feeds both channels
 * from one PDC stream clocked by one trigger, so the sync cannot
 * drift against the waveform - it lags by exactly one trigger period.
 *
 * OFF     mid scale. The demultiplexing arm this project has always
 *         run: a waveform there means the channel tags are read wrong.
 * CYCLE   50% square, one cycle per waveform cycle. The default, and
 *         a better demux check than OFF - DC cannot tell "correctly
 *         holding 2048" from "not driven".
 * WRAP    50% square, one cycle per table wrap. Same as CYCLE at the
 *         default resolution, different at every other, because the
 *         wrap is the PDC reload rather than the waveform.
 *
 * 50% duty rather than a narrow pulse: the scope's EXT trigger tops
 * out at 1.2 V while the DAC sits at 0.52-2.82 V, so the trigger must
 * be AC coupled, and AC coupling makes a narrow pulse's baseline droop
 * with its duty cycle. A square does not droop.
 *
 * GEN_LAYOUT_DC ignores this - that arm holds both pins level, and a
 * sync square would defeat the control it is.
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
