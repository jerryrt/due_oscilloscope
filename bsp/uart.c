/*
 * UART driver for the Due programming port.
 *
 * The 16U2 bridges this UART to USB CDC, so from the SAM3X8E side it is
 * an ordinary UART peripheral and needs no USB stack at all. That is
 * what makes printf debugging cheap here; see docs/debugging.md.
 *
 * Output is polled, not interrupt-driven. Polled output is slow, but it
 * works with interrupts disabled and from fault context, which is
 * exactly when diagnostics matter most.
 */

#include "sam.h"
#include "bsp.h"

#define PIN_URXD (1u << 8)   /* PA8 */
#define PIN_UTXD (1u << 9)   /* PA9 */

void uart_init(uint32_t baud)
{
	/* Clock PIOA and the UART. */
	PMC->PMC_PCER0 = (1u << ID_PIOA) | (1u << ID_UART);

	/* Hand PA8/PA9 to peripheral A. */
	PIOA->PIO_PDR  = PIN_URXD | PIN_UTXD;
	PIOA->PIO_ABSR &= ~(PIN_URXD | PIN_UTXD);

	/* Reset and disable before reconfiguring. */
	UART->UART_CR = UART_CR_RSTRX | UART_CR_RSTTX
	              | UART_CR_RXDIS | UART_CR_TXDIS;

	/* 8N1 is implied: the SAM3X UART has no character-length field.
	 * Parity none, normal channel mode. */
	UART->UART_MR = UART_MR_PAR_NO | UART_MR_CHMODE_NORMAL;

	/* Baud = MCK / (16 * CD). At 84 MHz and 115200 this is 45.57, so
	 * CD = 46 gives ~114130 baud, an error of -0.9%. Well inside the
	 * ~2-3% a UART tolerates. */
	UART->UART_BRGR = (SystemCoreClock / baud) / 16u;

	UART->UART_IDR = 0xffffffff;
	UART->UART_CR  = UART_CR_RXEN | UART_CR_TXEN;
}

void uart_putc_polled(char c)
{
	while (!(UART->UART_SR & UART_SR_TXRDY))
		{ }
	UART->UART_THR = c;
}

void uart_puts_polled(const char *s)
{
	while (*s)
		uart_putc_polled(*s++);
}

bool uart_rx_ready(void)
{
	return (UART->UART_SR & UART_SR_RXRDY) != 0;
}

int uart_getc(void)
{
	if (!uart_rx_ready())
		return -1;
	return (int)(UART->UART_RHR & 0xff);
}

void uart_flush(void)
{
	while (!(UART->UART_SR & UART_SR_TXEMPTY))
		{ }
}
