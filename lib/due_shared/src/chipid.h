/*
 * The SAM3X8E's 128-bit unique identifier, read once at init.
 *
 * A board's identity has to come from the silicon that takes the
 * measurements. The programming port's USB serial names the ATmega16U2
 * that bridges the UART - a different chip on the same board - and the
 * native port's serial is a string the firmware chooses, identical on
 * every board. The EEFC's unique identifier is burned into the SAM3X
 * itself, so a row that carries it names the converter it was taken
 * with, wherever that board is plugged in.
 *
 * It lives in the shared tree although it touches a register. Invariant
 * 3 keeps register programming per track so that a behavioural
 * divergence points at one programming of the silicon; an identifier
 * has no behaviour to diverge, and two hand-copies of a command sequence
 * with a hazard in it would be two homes for one hazard. load.c already
 * reads DWT on the same reasoning.
 */
#ifndef CHIPID_H
#define CHIPID_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * RUNS FROM RAM WITH INTERRUPTS MASKED, AND MUST. While the identifier
 * is exposed (STUI .. SPUI) the flash plane it lives on answers with the
 * identifier instead of the program, so any fetch from flash in that
 * window - the routine itself, an ISR, a literal pool - executes the ID
 * as code. The routine sits in .ramfunc, which every track's linker
 * script copies to SRAM at reset, and it touches nothing outside itself.
 *
 * Call once, at init, before anything streams; never on the working
 * path (invariant 7) - it spins on FRDY twice, tens of microseconds
 * with nothing else able to run. out[0] is the most significant word as
 * the datasheet orders them.
 */
void chipid_read(uint32_t out[4]);

#ifdef __cplusplus
}
#endif

#endif
