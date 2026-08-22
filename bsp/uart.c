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
 *
 * Input is the other way round, and has to be. uart_getc() used to read
 * UART_RHR directly, so a character that arrived while the main loop
 * was inside a printf was simply lost - and a printf costs about 3.5 ms
 * against one character every 87 us at 115200, so "# stream stopped"
 * alone swallows the next seventeen. A command sent straight after one
 * that prints was therefore dropped, silently and intermittently, which
 * is exactly what a rate argument typed before a command letter looks
 * like. Track A never had this because Arduino's Serial is interrupt
 * buffered; this is the same thing, smaller.
 */

#include "sam.h"
#include "bsp.h"

#define PIN_URXD (1u << 8)   /* PA8 */
#define PIN_UTXD (1u << 9)   /* PA9 */

/*
 * Receive ring. 64 bytes is far more than the longest command line and
 * the ISR is a handful of instructions, so it sits at the bottom of the
 * priority order where it cannot disturb the sample path.
 */
#define RX_RING 64u

static volatile uint8_t  rx_ring[RX_RING];
static volatile uint32_t rx_head, rx_tail;

void UART_Handler(void)
{
	while (UART->UART_SR & UART_SR_RXRDY) {
		uint8_t c = (uint8_t)(UART->UART_RHR & 0xffu);
		uint32_t next = (rx_head + 1u) % RX_RING;

		/* A full ring drops the newest rather than overwriting the
		 * oldest: a truncated command is refused, a corrupted one
		 * might be obeyed. */
		if (next != rx_tail) {
			rx_ring[rx_head] = c;
			rx_head = next;
		}
	}
}

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

	rx_head = rx_tail = 0;
	NVIC_ClearPendingIRQ(UART_IRQn);
	NVIC_SetPriority(UART_IRQn, 15);   /* below ADC 0 and DACC 1 */
	NVIC_EnableIRQ(UART_IRQn);
	UART->UART_IER = UART_IER_RXRDY;
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
	return rx_head != rx_tail;
}

int uart_getc(void)
{
	uint8_t c;

	if (rx_head == rx_tail)
		return -1;
	c = rx_ring[rx_tail];
	rx_tail = (rx_tail + 1u) % RX_RING;
	return (int)c;
}

void uart_flush(void)
{
	while (!(UART->UART_SR & UART_SR_TXEMPTY))
		{ }
}
