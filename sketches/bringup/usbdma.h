/*
 * UOTGHS endpoint DMA on top of the Arduino CDC stack.
 *
 * The core keeps what it is good at - enumeration, descriptors, control
 * transfers, the 1200-baud erase - and this takes over the bulk data
 * path, so that Track A moves samples the same way Track B does: the
 * controller reads and writes SRAM directly and the processor never
 * touches a sample.
 *
 * What makes this different from the bare-metal driver is that the core
 * still owns the endpoints and rebuilds their configuration on every bus
 * reset and SET_CONFIGURATION, with AUTOSW clear and its own receive
 * interrupt re-enabled. A sketch gets no hook into either event, so the
 * mode is re-asserted by polling instead: usbdma_keepalive() notices a
 * rebuild and puts the endpoint back. Missing that recreates exactly the
 * one-transfer stall documented in docs/HANDOFF.md.
 */

#ifndef USBDMA_H
#define USBDMA_H

#include <stdint.h>

/*
 * Claim or release the bulk endpoints. Claiming an endpoint stops the
 * core's ISR from draining it and switches it to AUTOSW; releasing
 * hands it back so SerialUSB works normally again. Always release what
 * you claimed: the capture path writes through the core, and an IN
 * endpoint left in AUTOSW breaks it.
 */
void     usbdma_mode(bool in_dma, bool out_dma);

/*
 * One direction at a time, because the two have different owners:
 * playback claims OUT and capture claims IN, and in loop mode both are
 * claimed at once. The pair form above sets both and would have each
 * caller release the other's endpoint.
 */
void     usbdma_mode_in(bool on);
void     usbdma_mode_out(bool on);
void     usbdma_keepalive(void);   /* re-assert after a core rebuild */
bool     usbdma_ready(void);
bool     usbdma_out_claimed(void);

bool     usbdma_out_busy(void);
uint32_t usbdma_out_status(void);   /* raw DEVDMASTATUS, read once */
bool     usbdma_out_start(void *buf, uint32_t len);         /* stops short */
bool     usbdma_out_start_stream(void *buf, uint32_t len);  /* runs on */

bool     usbdma_in_busy(void);
uint32_t usbdma_in_residue(void);
bool     usbdma_in_start(const void *buf, uint32_t len);

/*
 * Activity counters for the front-panel LEDs: any byte moved or DMA
 * armed bumps one of these, and the main loop samples them to decide
 * whether the indicator should be lit. Counters rather than flags so a
 * sampler that misses an interval still sees that something happened.
 */
extern volatile uint32_t usb_in_activity;    /* device -> host */
extern volatile uint32_t usb_out_activity;   /* host -> device */

/* How often the core rebuilt the endpoint out from under us. Normal at
 * enumeration; climbing during a run means the link is resetting. */
extern volatile uint32_t usbdma_rebuilds;

void     usbdma_dump(void);

#endif /* USBDMA_H */
