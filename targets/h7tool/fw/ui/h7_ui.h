/*
 * The H7-TOOL's display, backlight and LEDs, for the D428-9 unit with board register 0x4289 (docs/22). Every pin and
 * value here was read from the stock boot loader and then observed on the unit; docs/22 holds the evidence and says
 * what is still open. Nothing here touches PH9 (the buzzer on this unit), PG1, PC13 (TVCC) or the keys.
 *
 *   panel      ST7789, portrait 240 columns by 320 rows, MADCTL 0xC0, RGB565, on SPI5 (PH6 SCK, PH7 data, mode 3, 8-bit
 *              frames; -DH7UI_HW_SPI=0 clocks the pins by hand instead), chip select PE1 (low), D/C PG15 (low = command), power enable PH15. The panel resets
 *              itself at power-on, so there is no reset pin.
 *   expander   AW9523B at 8-bit address 0xB6 on a soft I2C, SCL PB6 and SDA PG0. Backlight is output P0_0, the LEDs
 *              are P1_0..P1_2.
 *
 * Speed, measured on the unit (docs/22): a full-screen fill takes 25 ms on SPI5 at kernel/2 with the core at 400 MHz,
 * which is the wire time; at the 64 MHz reset clock the CPU feeding the FIFO limits it to about 250 ms (about 120 ms with
 * the instruction cache on). The hand-clocked pins take about 3 s.
 *
 * Constant time and memory: no allocation, every loop is bounded. A call is slow, though: the panel is written a bit
 * at a time and an expander write is about 1.5 ms at the default bus speed, so none of this belongs in an ISR or in
 * the sample path (CLAUDE.md invariants 6 and 7). The caller supplies the delay.
 */
#ifndef H7_UI_H
#define H7_UI_H

#include <stdint.h>

#define H7LCD_W 240u
#define H7LCD_H 320u

/* Microsecond busy-wait supplied by the image (its clock decides the count). Must be set before any other call. */
void h7ui_set_delay(void (*delay_us)(uint32_t us));

/* ---- expander: backlight and LEDs ---- */

/* Output P0_0 is the backlight, P1_0 and P1_1 the two halves of the CHG LED and P1_2 the RUN LED. Which colour is which
 * on CHG rests on one report each (docs/22) *(check)*. P1_3 lit nothing that was seen. */
enum h7ui_led {
	H7UI_LED_CHG_GREEN = 0,   /* P1_0, register 0x20 */
	H7UI_LED_CHG_RED   = 1,   /* P1_1, register 0x21 */
	H7UI_LED_RUN       = 2,   /* P1_2, register 0x22 */
	H7UI_LED_COUNT
};

/* LED current is level/255 of 37 mA (the chip's full range, as the boot loader sets it). 0x20 is about 4.6 mA. */
#define H7UI_LED_DEFAULT 0x20u

/* Configure the expander as the boot loader does and leave every LED off and the backlight where it was.
 * Returns 1 if the chip answered with its ID (0x23), 0 if not; on 0 nothing else was written. */
int  h7ui_expander_init(void);
void h7ui_backlight(uint8_t level);               /* 0 off .. 255 full */
void h7ui_led(enum h7ui_led led, uint8_t level);  /* 0 off */
/* Returns 1 if the write was acknowledged. */
int  h7ui_expander_write(uint8_t reg, uint8_t val);

/* ---- panel ---- */

/* SPI5 waits that gave up; 0 means every transfer completed. Always 0 on the hand-clocked build. */
unsigned h7ui_spi_errors(void);
/* The first timeout stops all further SPI5 use (so a stuck peripheral costs microseconds, not minutes) and keeps the
 * SR and CR1 it saw, for diagnosis. */
uint32_t h7ui_spi_status_at_error(void);
uint32_t h7ui_spi_control_at_error(void);

/* Power the panel, send the boot loader's model 0/1 initialisation, and turn the display on. The picture memory
 * is undefined afterwards; fill it before the backlight is turned up. About 0.35 s. */
void h7lcd_init(void);

/* Open a window (x, y, w, h wholly inside 240x320) and stream w*h RGB565 pixels with h7lcd_pixel(); h7lcd_end() closes it.
 * Returns 0, and opens nothing, for an empty or out-of-range window. */
int  h7lcd_begin(unsigned x, unsigned y, unsigned w, unsigned h);
void h7lcd_pixel(uint16_t rgb565);
void h7lcd_end(void);
/* Fills the part of the rectangle that lies on the glass. */
void h7lcd_fill_rect(unsigned x, unsigned y, unsigned w, unsigned h, uint16_t rgb565);

/* DMA2 stream 3 into the SPI5 FIFO (docs/22). The CPU feed tops out near 25 ms for a full screen whatever the clock; DMA
 * runs at the wire. Both need SPI5 active (not the pins fallback) and return 0 when they cannot send, having sent nothing
 * or an incomplete picture, so the caller can redraw with the pixel calls. They block until the data is out.
 * h7lcd_blit sends `bytes` (even; big-endian RGB565) from src to the window opened by h7lcd_begin; src must be memory DMA2
 * can read with no data cache in front of it. h7lcd_fill_dma opens the window itself and repeats one pixel, kept in the
 * two bytes given to h7ui_set_dma_scratch (same kind of memory). h7ui_dma_errors counts transfers that gave up. */
int h7lcd_blit(const uint8_t *src, uint32_t bytes);

/* Screen capture. The panel cannot be read back (its data pad is the write line), so the driver can keep a shadow copy of
 * everything sent: give it H7LCD_W * H7LCD_H * 2 bytes with h7ui_set_shadow(); every pixel that goes out afterwards is also
 * stored there, big-endian RGB565, row after row. The shadow starts as whatever the memory held and the panel's memory after
 * a reset is not defined, so draw the whole screen once before trusting a capture. A DMA call that gave up leaves the
 * shadow untouched though the panel may hold part of it. h7ui_draw_count() counts closed windows (h7lcd_end and the DMA
 * calls): a capture that sees it change while reading has torn. */
void h7ui_set_shadow(uint8_t *fb);
const uint8_t *h7ui_shadow(void);
uint32_t h7ui_draw_count(void);

/* 1 when SPI5 was clocked from PLL2 (160 MHz, 80 MHz bit clock) at its set-up, 0 when it runs from the 100 MHz APB2 clock
 * (PLL2 busy, not the state the images leave, or no lock, or the hand-clocked build). */
int h7ui_spi_fast(void);
int h7lcd_fill_dma(unsigned x, unsigned y, unsigned w, unsigned h, uint16_t rgb565);
void h7ui_set_dma_scratch(uint8_t *two_bytes);
unsigned h7ui_dma_errors(void);

#endif
