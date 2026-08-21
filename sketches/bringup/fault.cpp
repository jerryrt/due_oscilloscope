/*
 * HardFault reporting for Track A.
 *
 * Overrides the core's weak HardFault_Handler, which aliases __halt and
 * therefore turns every fault into a silent lockup. Without a debug
 * probe that is the worst possible behaviour: the board simply stops
 * with no indication of where or why.
 *
 * Output goes out the programming port by polled UART writes rather than
 * Serial.print(). Serial is interrupt-driven and ring-buffered, and
 * neither can be relied upon from fault context. Polling touches only
 * UART_SR and UART_THR and works with interrupts disabled.
 *
 * This file is the reference for the equivalent Track B BSP code.
 */

#include <Arduino.h>

#define LED_MASK (1u << 27)   /* pin 13 = PB27 */

static void fputc_polled(char c)
{
	while (!(UART->UART_SR & UART_SR_TXRDY)) { }
	UART->UART_THR = c;
}

static void fputs_polled(const char *s)
{
	while (*s)
		fputc_polled(*s++);
}

static void fput_hex(uint32_t v)
{
	static const char hex[] = "0123456789abcdef";

	fputs_polled("0x");
	for (int i = 28; i >= 0; i -= 4)
		fputc_polled(hex[(v >> i) & 0xf]);
}

static void fput_kv(const char *k, uint32_t v)
{
	fputs_polled("#   ");
	fputs_polled(k);
	fputs_polled(" = ");
	fput_hex(v);
	fputs_polled("\r\n");
}

/*
 * Blink a fault code forever. Deliberately avoids delay(): SysTick may
 * not be running, and in fault context nothing about the scheduler or
 * the tick can be assumed. Busy loops only.
 */
static void blink_forever(int count)
{
	for (;;) {
		for (int i = 0; i < count; i++) {
			PIOB->PIO_SODR = LED_MASK;
			for (volatile uint32_t d = 0; d < 1500000; d++) { }
			PIOB->PIO_CODR = LED_MASK;
			for (volatile uint32_t d = 0; d < 1500000; d++) { }
		}
		for (volatile uint32_t d = 0; d < 9000000; d++) { }
	}
}

extern "C" void hard_fault_report(uint32_t *sp)
{
	uint32_t cfsr = SCB->CFSR;

	fputs_polled("\r\n#\r\n# *** HARD FAULT ***\r\n");

	/* Exception frame stacked by the core, in architectural order. */
	fput_kv("R0   ", sp[0]);
	fput_kv("R1   ", sp[1]);
	fput_kv("R2   ", sp[2]);
	fput_kv("R3   ", sp[3]);
	fput_kv("R12  ", sp[4]);
	fput_kv("LR   ", sp[5]);
	fput_kv("PC   ", sp[6]);
	fput_kv("xPSR ", sp[7]);

	fput_kv("CFSR ", cfsr);
	fput_kv("HFSR ", SCB->HFSR);
	fput_kv("MMFAR", SCB->MMFAR);
	fput_kv("BFAR ", SCB->BFAR);

	/* Decode the bits that identify the common causes. */
	fputs_polled("# cause:");
	if (SCB->HFSR & SCB_HFSR_FORCED_Msk)
		fputs_polled(" FORCED(escalated)");
	if (cfsr & (1u << 16)) fputs_polled(" UNDEFINSTR");
	if (cfsr & (1u << 17)) fputs_polled(" INVSTATE");
	if (cfsr & (1u << 18)) fputs_polled(" INVPC");
	if (cfsr & (1u << 24)) fputs_polled(" UNALIGNED");
	if (cfsr & (1u << 25)) fputs_polled(" DIVBYZERO");
	if (cfsr & (1u << 8))  fputs_polled(" IBUSERR");
	if (cfsr & (1u << 9))  fputs_polled(" PRECISERR");
	if (cfsr & (1u << 10)) fputs_polled(" IMPRECISERR");
	if (cfsr & (1u << 1))  fputs_polled(" DACCVIOL");
	fputs_polled("\r\n");

	fputs_polled("# PC identifies the faulting instruction.\r\n");
	fputs_polled("# Cross-reference against the .map file.\r\n");
	fputs_polled("# halting, blinking 3\r\n#\r\n");

	blink_forever(3);
}

/*
 * Naked so the compiler emits no prologue: the stack pointer must be
 * captured exactly as the exception left it. Bit 2 of EXC_RETURN says
 * whether the frame was stacked on MSP or PSP.
 */
extern "C" __attribute__((naked)) void HardFault_Handler(void)
{
	__asm volatile (
		"tst lr, #4              \n"
		"ite eq                  \n"
		"mrseq r0, msp           \n"
		"mrsne r0, psp           \n"
		"b hard_fault_report     \n"
	);
}
