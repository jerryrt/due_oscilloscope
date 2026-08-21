/*
 * HardFault reporting.
 *
 * Bare-metal counterpart of sketches/bringup/fault.cpp, which was
 * verified on hardware first. Same output format deliberately, so the
 * two tracks can be compared line by line.
 *
 * Without a debug probe an unhandled fault is a silent lockup, which is
 * the worst possible failure mode. This turns it into a register dump
 * plus a blink code. The two report through independent paths, so a
 * broken UART still leaves the blink code working.
 */

#include "sam.h"
#include "bsp.h"

static void put_hex(uint32_t v)
{
	static const char hex[] = "0123456789abcdef";

	uart_puts_polled("0x");
	for (int i = 28; i >= 0; i -= 4)
		uart_putc_polled(hex[(v >> i) & 0xf]);
}

static void put_kv(const char *k, uint32_t v)
{
	uart_puts_polled("#   ");
	uart_puts_polled(k);
	uart_puts_polled(" = ");
	put_hex(v);
	uart_puts_polled("\r\n");
}

void hard_fault_report(uint32_t *sp)
{
	uint32_t cfsr = SCB->CFSR;

	uart_puts_polled("\r\n#\r\n# *** HARD FAULT ***\r\n");

	put_kv("R0   ", sp[0]);
	put_kv("R1   ", sp[1]);
	put_kv("R2   ", sp[2]);
	put_kv("R3   ", sp[3]);
	put_kv("R12  ", sp[4]);
	put_kv("LR   ", sp[5]);
	put_kv("PC   ", sp[6]);
	put_kv("xPSR ", sp[7]);

	put_kv("CFSR ", cfsr);
	put_kv("HFSR ", SCB->HFSR);
	put_kv("MMFAR", SCB->MMFAR);
	put_kv("BFAR ", SCB->BFAR);

	uart_puts_polled("# cause:");
	if (SCB->HFSR & SCB_HFSR_FORCED_Msk)
		uart_puts_polled(" FORCED(escalated)");
	if (cfsr & (1u << 16)) uart_puts_polled(" UNDEFINSTR");
	if (cfsr & (1u << 17)) uart_puts_polled(" INVSTATE");
	if (cfsr & (1u << 18)) uart_puts_polled(" INVPC");
	if (cfsr & (1u << 24)) uart_puts_polled(" UNALIGNED");
	if (cfsr & (1u << 25)) uart_puts_polled(" DIVBYZERO");
	if (cfsr & (1u << 8))  uart_puts_polled(" IBUSERR");
	if (cfsr & (1u << 9))  uart_puts_polled(" PRECISERR");
	if (cfsr & (1u << 10)) uart_puts_polled(" IMPRECISERR");
	if (cfsr & (1u << 1))  uart_puts_polled(" DACCVIOL");
	uart_puts_polled("\r\n");

	uart_puts_polled("# PC identifies the faulting instruction.\r\n");
	uart_puts_polled("# Cross-reference against the .map file.\r\n");
	uart_puts_polled("# halting, blinking 3\r\n#\r\n");
	uart_flush();

	led_blink_forever(3);
}

/*
 * Naked so no prologue runs: the stack pointer must be captured exactly
 * as the exception left it. Bit 2 of EXC_RETURN selects MSP or PSP.
 */
__attribute__((naked)) void HardFault_Handler(void)
{
	__asm volatile (
		"tst lr, #4              \n"
		"ite eq                  \n"
		"mrseq r0, msp           \n"
		"mrsne r0, psp           \n"
		"b hard_fault_report     \n"
	);
}
