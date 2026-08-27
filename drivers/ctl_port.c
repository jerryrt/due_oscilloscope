/*
 * Track B's side of lib/due_shared/src/ctl_port.h.
 *
 * Thin by design. Every function here is a name change and nothing
 * else, which is the point: the protocol stops naming this track's
 * headers, and what it needs instead is five lines of forwarding that
 * a second track can write for itself.
 *
 * Bare metal, so all four dependencies are this project's own -
 * usb_cdc.c for the endpoint, bsp.c for the clock and the console,
 * load.c for the monitor.
 */
#include "ctl_port.h"

#include "bsp.h"
#include "load.h"
#include "usb_cdc.h"

size_t ctl_port_read(uint8_t *dst, size_t max)
{
	return usb_ctl_read(dst, max);
}

size_t ctl_port_write(const uint8_t *src, size_t len)
{
	return usb_ctl_write(src, len);
}

uint32_t ctl_port_micros(void)
{
	return micros();
}

uint32_t ctl_port_millis(void)
{
	return millis();
}

uint32_t ctl_port_out_drain_polls(void)
{
	return usb_out_drain_polls;
}

bool ctl_port_load_sample(load_report_t *out)
{
	/*
	 * True even when the cycle counter is not counting. `available`
	 * inside the report says that, and it is a different statement
	 * from "this track has no load monitor" - which is what returning
	 * false means and what Track A will return until it grows one.
	 */
	load_sample(out);
	return true;
}

void ctl_port_console_flush(void)
{
	uart_flush();
}
