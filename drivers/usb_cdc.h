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
