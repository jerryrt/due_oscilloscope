/* Board support for the Arduino Due (SAM3X8E), bare metal. */

#ifndef BSP_H
#define BSP_H

#include <stdint.h>
#include <stdbool.h>

/* UART on the programming port: PA8 = URXD, PA9 = UTXD, via the 16U2. */
void uart_init(uint32_t baud);
void uart_putc_polled(char c);          /* safe from fault context */
void uart_puts_polled(const char *s);
bool uart_rx_ready(void);
int  uart_getc(void);                   /* -1 if nothing pending */
void uart_flush(void);                  /* wait for the shift register */

/* LED: pin 13 = PB27. */
void led_init(void);
void led_on(void);
void led_off(void);
void led_toggle(void);
void led_blink_forever(int count);      /* fault codes; no SysTick needed */

/* Timebase. */
void     systick_init(void);
uint32_t millis(void);
uint32_t micros(void);

#endif /* BSP_H */
