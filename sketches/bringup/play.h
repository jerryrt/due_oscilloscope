/*
 * Host-fed DAC playback: the arbitrary waveform generator path.
 *
 * Mirror image of the capture ring. The host streams 16-bit half-words
 * with the DACC channel tag already set in bits [13:12], the PDC feeds
 * them to the DACC, and the CPU only moves pointers.
 *
 * The failure mode here is underrun, the dual of capture overrun: the
 * DAC needs a buffer the host has not supplied. It is counted and
 * reported rather than hidden by repeating the previous buffer, on the
 * same principle that governs the capture path.
 */

#ifndef PLAY_H
#define PLAY_H

#include <stdint.h>

#define PLAY_NBUF         12
#define PLAY_BUF_SAMPLES  1024

extern uint16_t play_buf[PLAY_NBUF][PLAY_BUF_SAMPLES];

bool     play_start(uint32_t dac_hz);
void     play_stop(void);
bool     play_active(void);
void     play_service(void);      /* drain USB OUT into the ring */
uint32_t play_configured_rc(void);

extern volatile uint32_t play_produced;    /* buffers filled from USB */
extern volatile uint32_t play_consumed;    /* buffers handed to the PDC */
extern volatile uint32_t play_underruns;
extern volatile uint32_t play_bytes_in;
extern volatile uint32_t play_started_us;

#endif /* PLAY_H */
