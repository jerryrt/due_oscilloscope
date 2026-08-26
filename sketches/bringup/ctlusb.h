/*
 * The native port's second CDC function on Track A.
 *
 * Track B builds its whole configuration descriptor by hand
 * (drivers/usb_cdc.c) and can simply write two functions into it. This
 * track leaves enumeration to the Arduino core, which knows about one
 * CDC and nothing else, so the second function is added through the
 * core's own extension point: PLUGGABLE_USB_ENABLED is defined in sam
 * 1.6.12 and USBCore.cpp dispatches setup/getInterface/getDescriptor to
 * PluggableUSB(). A module registered there contributes interfaces and
 * endpoints without the core being patched, which is what keeps
 * enumeration the core's job and this track an independent oracle.
 *
 * The numbers need no negotiation. The core's CDC takes interfaces 0-1
 * and EP1-3; PluggableUSB_::plug() then hands out interface 2 and EP4,
 * which is exactly the layout drivers/usb_cdc.c hardcodes. That is
 * checked at registration rather than assumed - docs/control-protocol.md
 * requires the two tracks to present *identical* descriptors, and a
 * silent renumbering here would be a wire divergence nothing else looks
 * for.
 */
#ifndef CTLUSB_H
#define CTLUSB_H

#include <stdint.h>
#include <stddef.h>

/*
 * Did the second function register, on the contracted interface and
 * endpoint numbers? Registration happens in a global constructor
 * because the core attaches USB before setup() runs; this is how a
 * sketch finds out whether it took.
 */
bool ctlusb_ok(void);

/* EP numbers, matching drivers/usb_cdc.c. */
#define CTL_EP_ACM   4u
#define CTL_EP_OUT   5u
#define CTL_EP_IN    6u
#define CTL_EP_SIZE  512u

/*
 * Re-establish EP4-6 after a DEVEPTCFG write to an endpoint below them.
 * Every such write re-allocates and slides the window above it
 * (40.5.1.6), so anything that touches EP2 or EP3 must call this.
 */
void ctlusb_realloc_endpoints(void);

/*
 * Mask EP4-6 in the core's interrupt controller. They are manual FIFO
 * and polled; an unserviced endpoint interrupt storms the ISR and stops
 * the main loop. Re-apply after anything that may have re-enabled them.
 */
void ctlusb_quiesce_interrupts(void);

extern volatile uint32_t ctlusb_reallocs;
extern volatile uint32_t ctlusb_cfg_fail;

#endif /* CTLUSB_H */
