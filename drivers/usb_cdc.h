/*
 * Minimal bare-metal USB CDC device on the SAM3X8E UOTGHS.
 *
 * Presents the same CDC-ACM interface as the Arduino core, so the host
 * receiver works against either track unchanged. What differs is the
 * implementation underneath, which is the point: Track A copies into the
 * endpoint FIFO a byte at a time, and this one is free to do better.
 */

#ifndef USB_CDC_H
#define USB_CDC_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

void   usb_cdc_init(void);
void   usb_cdc_dump(void);
void   usb_cdc_poll(void);

/* True once the host has configured the device and raised DTR. */
bool   usb_cdc_ready(void);
extern volatile uint32_t usb_in_activity;   /* bytes/transfers, IN  */
extern volatile uint32_t usb_out_activity;  /* bytes/transfers, OUT */

/*
 * Queue up to len bytes on the bulk IN endpoint. Returns the number
 * accepted, which may be zero. Never blocks: a host that stops draining
 * must not be able to wedge the board, which is exactly the failure the
 * Arduino CDC path has.
 */
size_t usb_cdc_write(const uint8_t *data, size_t len);

/*
 * Read whole banks from the bulk OUT endpoint.
 *
 * The Arduino core's equivalent calls accept() once per byte, which
 * refills its entire ring each time and costs several hundred cycles per
 * byte. This copies up to one 512-byte bank per call and releases it,
 * which is what the endpoint is designed for.
 */
size_t usb_cdc_read(uint8_t *dst, size_t max);

/*
 * DMA transfers on the bulk endpoints.
 *
 * The UOTGHS has a DMA channel per endpoint, so the controller can read
 * straight out of a caller's buffer with the processor never touching
 * the bytes. That is what the architecture asks for: the ADC's PDC
 * writes a buffer and the USB DMA reads the same buffer, no copy in
 * between.
 *
 * Start returns false if a transfer is already in flight. The buffer
 * must stay valid and unmodified until busy() reads false.
 */
/* Switch endpoints between manual-FIFO and DMA (AUTOSW) operation.
 * Never mix the two on one endpoint: the FIFO path owns FIFOCON by
 * hand, DMA needs the hardware to switch banks itself. */
void   usb_cdc_dma_mode(bool in_dma, bool out_dma);

bool   usb_dma_in_start(const void *buf, uint32_t len);
bool   usb_dma_in_busy(void);
uint32_t usb_dma_in_residue(void);

bool   usb_dma_out_start(void *buf, uint32_t len);
bool   usb_dma_out_start_stream(void *buf, uint32_t len);  /* no END_TR */

bool   usb_dma_out_busy(void);
uint32_t usb_dma_out_status(void);   /* raw DEVDMASTATUS, read once */

extern volatile uint32_t usb_reset_count;
extern volatile uint32_t usb_setup_count;
extern volatile uint32_t usb_stall_count;
extern volatile uint32_t usb_configured;
extern volatile uint32_t usb_line_state;
extern volatile uint32_t usb_cfg_fail;
extern volatile uint32_t usb_isr_count;
extern volatile uint32_t usb_last_devisr;
extern volatile uint32_t usb_last_ep0isr;
extern volatile uint32_t usb_devier_snap;

#endif /* USB_CDC_H */
