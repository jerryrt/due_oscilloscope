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

#define PLAY_NBUF        8
#define PLAY_BUF_SAMPLES 512
#define PLAY_BUF_BYTES   (PLAY_BUF_SAMPLES * 2)

bool play_start(uint32_t dac_hz);
void play_stop(void);
bool play_active(void);
void play_service(void);          /* drain USB OUT into the ring */
void play_dump(void);

extern volatile uint32_t play_produced;    /* buffers filled from USB */
extern volatile uint32_t play_consumed;    /* buffers handed to the PDC */
extern volatile uint32_t play_underruns;
extern volatile uint32_t play_bytes_in;
extern volatile uint32_t play_isr_calls;
extern volatile uint32_t play_endtx_seen;

#endif /* PLAY_H */
