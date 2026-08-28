#ifndef GEN_H
#define GEN_H
#include <stdint.h>

/*
 * DAC playback driven by the same TIOA0 that triggers the ADC, so
 * generation and capture are phase-coherent by construction.
 *
 * DACC TAG mode: bits [13:12] of each half-word select the channel, so
 * one PDC stream feeds both DACs. The table interleaves a sine for DAC0
 * with a fixed DC level for DAC1. Each channel therefore updates every
 * other trigger, and the DC channel doubles as a demux check: if the
 * host ever shows a sine on A1, the channel tags are being read wrong.
 */
#include "ctl_wire.h"   /* the generator's value space, shared */

/*
 * The table this track's PDC walks. The point count is the contract's
 * GEN_TABLE_POINTS; the buffer, the builder and every register below
 * are this track's own - invariant 3 keeps gen internals independent so
 * that two programmings of one converter disagreeing points at one of
 * them.
 */
#define GEN_SINE_POINTS   GEN_TABLE_POINTS
#define GEN_TABLE_LEN     (GEN_SINE_POINTS * 2)   /* interleaved */

/*
 * Shape and resolution: the same two axes Track B's gen.c carries, the
 * same command, the same printed format.
 *
 * Independent source, and deliberately so. Invariant 3 shares the wire
 * contract between the tracks and keeps *register programming* apart,
 * naming gen among the internals that stay independent: two
 * programmings of one converter is what makes a behavioural divergence
 * point at one of them. So this file uses libm's sin() where Track B
 * hand-rolls a fixed-point one, and the two agreeing on the analog
 * output is then evidence rather than a tautology. What must NOT differ
 * is the feature or the way it is asked for.
 *
 * Resolution is points per cycle and must divide GEN_SINE_POINTS, so a
 * cycle never straddles the PDC wrap: powers of two, 2 to 256. The
 * output frequency follows directly -
 *
 *     f = trigger_hz / (2 * gen_points)
 *
 * - the 2 because TAG mode spends half of every update on DAC1. Fewer
 * points buys frequency and costs staircase resolution; that trade is
 * the point of exposing it.
 */
/*
 * The sync output on DAC1: a trigger for the bench, and the same three
 * modes Track B's gen.c carries under the same command.
 *
 * Why, measured. Triggering a scope on the signal itself divides the
 * pin's amplitude noise - ~20 mV here, 15 mV of it with the DAC idle -
 * by the waveform's slew rate at the trigger level, so a ramp rising
 * 4.5 mV per sample shakes 27 us where a square does not shake at all.
 * A sync edge is full scale every time, so the same noise buys almost
 * no jitter, and the signal channel is measured rather than also being
 * asked to trigger. `docs/awg.md`.
 *
 * Phase-locked by construction: one PDC stream, one trigger, both
 * channels. It lags the waveform by exactly one trigger period, which
 * is the TAG interleave and a fixed offset.
 *
 * OFF     mid scale - the demux arm this project has always run.
 * CYCLE   50% square, one per waveform cycle, rising at phase 0. The
 *         default, and a better demux check than OFF: a flat line is
 *         also what an unwritten channel looks like, and a square is
 *         not.
 * WRAP    50% square, one per table wrap. Same as CYCLE at the default
 *         resolution, different at every other, because the wrap is the
 *         PDC reload rather than the waveform.
 *
 * 50% duty and not a narrow pulse: the scope's EXT input tops out at
 * 1.2 V here against a 0.52-2.82 V DAC, so the trigger has to be AC
 * coupled, and AC coupling makes a narrow pulse's baseline droop with
 * its duty cycle. A square does not droop.
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

/*
 * DACC_ACR: the output stage's bias current, and it had never been
 * written on this track. Track B's gen.c carries the same control under
 * the same command.
 *
 * Datasheet 45.7.11 calls IBCTLCHx "Analog Output Current Control -
 * allows to adapt the slew rate of the analog output", and Tables 46-38
 * and 46-40 specify every published DAC figure - INL, DNL, SNR, THD,
 * SINAD - at IBCTLDACCORE=01 with IBCTLCHx=10. At reset the field is 0,
 * so the part has been running outside the conditions its own numbers
 * describe.
 *
 * The Arduino core writes exactly the characterised value in
 * wiring_analog.c the first time a DAC channel is enabled - which this
 * track does not go through, because gen and play program the DACC
 * themselves. So a sketch built on the core still runs at reset bias
 * unless it writes ACR, and that is worth saying plainly: being on the
 * core is not the same as getting the core's register writes.
 *
 * It has to be applied *after* DACC_CR_SWRST and by every path that
 * issues one - gen_init() and play_init() both do. Setting it from a
 * console command alone would be silently undone by the next capture.
 */
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

extern uint8_t gen_ibctl_ch;      /* IBCTLCH0 and CH1, 0-3 */
extern uint8_t gen_ibctl_core;    /* IBCTLDACCORE, 0-3     */
void        gen_set_ibctl(uint32_t ch, uint32_t core);
void        gen_apply_acr(void);
uint32_t    gen_acr(void);        /* as the hardware holds it */

/*
 * What build_table() puts on each DAC, selected at runtime. Track B's
 * gen.h carries the same four arms under the same names and the same
 * command; the table builder below is this track's own.
 *
 * One image and one code path for every arm, because the binary selects
 * which state issue #5 draws: two builds would change the layout as
 * well as the waveform, and an absent artifact in the second arm could
 * not then be read. The table lives in RAM and gen_init() rebuilds it,
 * so an arm costs a branch and nothing else.
 *
 * NORMAL     sine on DAC0, sync on DAC1 - what this project has always
 *            run
 * SWAPPED    sync on DAC0, sine on DAC1 - is it DAC1, or a DAC pin?
 * TWOCYCLE   two waveform periods in one table - separates the PDC
 *            reload at the wrap from the waveform, which have been the
 *            same event in every build so far
 * DC         no waveform anywhere - is a swinging output needed at all?
 *
 * Every arm keeps DAC0 on even slots and DAC1 on odd, so a swap moves
 * the values and not the update timing.
 *
 * Why Track A needs them at all: this track is the oracle, and the
 * issue-#5 arms are most of what an oracle is for. Without them the
 * sweeps could be run on one track only, which is a divergence that
 * defeats the reason the second track exists - issue #13.
 */
#define GEN_LAYOUT_NORMAL    0u
#define GEN_LAYOUT_SWAPPED   1u
#define GEN_LAYOUT_TWOCYCLE  2u
#define GEN_LAYOUT_DC        3u

extern uint8_t gen_layout;
void        gen_set_layout(uint32_t layout);

extern uint8_t  gen_shape;
extern uint16_t gen_points;
void        gen_set_shape(uint32_t shape);
void        gen_set_points(uint32_t points);

void     gen_init(void);
void     gen_start(void);
/*
 * The playback configuration with gen's data source: DACC triggered by
 * TIOA1 and playing the flash sine table, no USB involved. Config and
 * start are split so the caller can reproduce the full loop's ordering
 * - DACC and timer first, capture second, clock last - which is what
 * makes the mimic command a control for the USB path.
 */
void     gen_prepare_tioa1(uint32_t dac_hz);  /* DACC + TC1 config, clock off */
void     gen_go_tioa1(void);                  /* start the TC1 clock */
/*
 * Drive the DACC from TC0 channel 1 (TIOA1) instead of the ADC's TIOA0,
 * so the DAC update rate can be swept independently of acquisition.
 */
bool     gen_start_independent(uint32_t dac_hz);
uint32_t gen_configured_rc(void);
void     gen_stop(void);

extern volatile uint32_t gen_endtx_count;

/*
 * Dispatched from the single DACC_Handler, which play.cpp owns: two
 * modules want the end-of-transmit event and only one can own the
 * vector, so the owner dispatches on which source is active.
 */
void     gen_endtx(void);

#endif /* GEN_H */
