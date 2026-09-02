/*
 * stream_port.h - what the shared framer reaches outside itself.
 *
 * This is a record, not an abstraction layer: it declares exactly the
 * functions and extern data stream_core.c uses, and
 * tests/test_shared_source.py asserts the two are equal, so nothing can
 * be added here without the framer actually calling it - a seam that
 * cannot grow without a test failing.
 *
 * Every declaration is a name both tracks must provide with the same
 * meaning - invariant 3's peer requirement made checkable at compile
 * time.
 *
 * The one asymmetry worth naming: on Track A, usb_dma_* is
 * sketches/bringup/usbdma.cpp taking the endpoints away from the
 * Arduino core; on Track B it is drivers/usb_cdc.c programming the
 * same silicon from scratch. Same names, same contract, independent
 * register programming - which is the point.
 */
#ifndef STREAM_PORT_H
#define STREAM_PORT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Capture ring layout. The values are the wire contract - a frame is
 * 32 bytes of header written into headroom plus 2032 samples, eight
 * 512-byte bulk packets exactly - and both tracks' acq.h carried them
 * word for word before they were shared here. Each track's stream file
 * asserts they match its acq.h.
 */
#define STREAM_NBUF        4
#define STREAM_BUF_SAMPLES 2032
#define STREAM_HDR_BYTES   32
#define STREAM_FRAME_BYTES (STREAM_HDR_BYTES + STREAM_BUF_SAMPLES * 2)

/* --- acquisition ------------------------------------------------- */
void     acq_init(void);
bool     acq_start(uint32_t trigger_hz, unsigned n_channels);
void     acq_stop(void);
uint16_t acq_channel_mask(void);
uint32_t acq_configured_rc(void);
bool     acq_frame_available(void);
uint8_t *acq_frame_bytes(void);
const uint16_t *acq_frame_data(void);
void     acq_frame_release(void);

extern volatile uint32_t acq_produced;
extern volatile uint32_t acq_consumed;   /* the resync rule writes it */
extern volatile uint32_t acq_rxbuff_overruns;
extern volatile uint32_t acq_govre;
extern volatile uint32_t acq_ring_overflow;

/* --- generator ---------------------------------------------------- */
void gen_init(void);
void gen_start(void);
void gen_stop(void);

/* --- playback ----------------------------------------------------- */
/* play.h stays per track; the framer stamps this one counter into
 * every frame header so the host can close its rate loop on it. */
extern volatile uint32_t play_consumed;

/* --- transport ---------------------------------------------------- */
/* Endpoint DMA: the sample path. Identical names, register programming
 * independent per track. */
bool     usb_dma_in_busy(void);
bool     usb_dma_in_start(const void *buf, uint32_t len);
void     usb_dma_mode_in(bool on);

/*
 * CPU write path: the fallback for the UART transport and for a host
 * that has not configured the endpoints. Each track's stream file
 * implements these over its own transport (uart/usb_cdc on B, the
 * core's Serial objects on A); a short return is backpressure, never
 * an error.
 */
size_t stream_port_write(const uint8_t *p, size_t n);
bool   stream_port_ready(void);

/* The bench arms' transport. Always the USB bulk pair, CPU path - the
 * UART switch above is the framer's business, not the bench's. A short
 * return is the bank refusing, never an error. */
size_t usb_port_write(const uint8_t *p, size_t n);
size_t usb_port_read(uint8_t *p, size_t n);

/* Endpoint DMA, bench side. usb_dma_out_done decodes one raw status
 * read per call - byte count and channel-enabled share the register -
 * returning false while the channel still runs, else *bytes_left holds
 * the residue and the channel is idle. The decode lives per track
 * because the register does.
 *
 * usb_dma_keepalive: on Track A the Arduino core rebuilds endpoint
 * configuration on bus reset and SET_CONFIGURATION, and this repairs it
 * on the bench's schedule. Track B has no core, so its implementation
 * is an empty function - the honest shape, since an #ifdef would hide
 * the asymmetry this header exists to record.
 */
uint32_t usb_dma_in_residue(void);
bool     usb_dma_out_start_stream(void *buf, uint32_t len);
bool     usb_dma_out_done(uint32_t *bytes_left);
void     usb_dma_mode(bool in_dma, bool out_dma);
void     usb_dma_keepalive(void);

/* Defined per track (its main loop increments it); the bench resets
 * it and the reports read it. */
extern volatile uint32_t stream_loop_passes;

/* --- platform ----------------------------------------------------- */
uint32_t micros(void);
extern uint32_t SystemCoreClock;

#ifdef __cplusplus
}
#endif

#endif /* STREAM_PORT_H */
