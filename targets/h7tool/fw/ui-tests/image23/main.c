/* Image 23: the display, backlight and LED driver (fw/ui) on the unit, then a timed return to the boot loader.
 * Build: tools/build_image.sh fw/ui-tests/image23 image23a fw/ui/h7_ui.c -Ifw/ui
 *
 * Draws the portrait test picture (F, four coloured corners, border), then lights RUN, CHG green and CHG red in
 * turn for 2 s each at the default level, then steps the backlight 0x20, 0x80, 0xFF, 0x80. PH9 (the buzzer) is
 * never touched. Core stays on its reset clock (HSI, 64 MHz *(check)*). */
#include <stdint.h>
#include "h7_ui.h"

#define SYST_CSR  (*(volatile uint32_t *)0xE000E010u)
#define SYST_RVR  (*(volatile uint32_t *)0xE000E014u)
#define SYST_CVR  (*(volatile uint32_t *)0xE000E018u)
#define SCB_AIRCR (*(volatile uint32_t *)0xE000ED0Cu)
#define BOOT_REQ  (*(volatile uint32_t *)0x20000000u)
#define BOOT_MAGIC 0x5AA51234u
#define CPU_HZ 64000000u

extern uint32_t _estack, _sidata, _sdata, _edata, _sbss, _ebss;

static void delay_us(uint32_t us)
{
	uint32_t start = SYST_CVR, n = us * (CPU_HZ / 1000000u);
	while (((start - SYST_CVR) & 0xFFFFFFu) < n) { }
}
static void delay_ms(uint32_t ms) { while (ms--) delay_us(1000); }

static void return_to_boot_loader(void)
{
	BOOT_REQ = BOOT_MAGIC;
	__asm volatile ("dsb sy" ::: "memory");
	SCB_AIRCR = 0x05FA0004u;
	for (;;) { }
}

static void picture(void)
{
	h7lcd_fill_rect(0, 0, 240, 320, 0x0010);
	h7lcd_fill_rect(0, 0, 240, 2, 0xFFFF);   h7lcd_fill_rect(0, 318, 240, 2, 0xFFFF);
	h7lcd_fill_rect(0, 0, 2, 320, 0xFFFF);   h7lcd_fill_rect(238, 0, 2, 320, 0xFFFF);
	h7lcd_fill_rect(30, 30, 16, 100, 0xFFFF);
	h7lcd_fill_rect(30, 30, 60, 16, 0xFFFF);
	h7lcd_fill_rect(30, 70, 44, 16, 0xFFFF);
	h7lcd_fill_rect(4, 4, 20, 20, 0xF800);     h7lcd_fill_rect(216, 4, 20, 20, 0x07E0);
	h7lcd_fill_rect(4, 296, 20, 20, 0x001F);   h7lcd_fill_rect(216, 296, 20, 20, 0xFFE0);
}

void Reset_Handler(void)
{
	uint32_t *s = &_sidata, *d = &_sdata;
	while (d < &_edata) *d++ = *s++;
	for (d = &_sbss; d < &_ebss; ) *d++ = 0;
	SYST_RVR = 0xFFFFFFu;
	SYST_CSR = 5u;

	h7ui_set_delay(delay_us);
	h7lcd_init();
	picture();
	int chip = h7ui_expander_init();
	h7lcd_fill_rect(100, 4, 40, 20, chip ? 0x07E0 : 0xF800);      /* top middle: green = chip answered */
	delay_ms(3000);

	if (chip) {
		static const enum h7ui_led order[] = { H7UI_LED_RUN, H7UI_LED_CHG_GREEN, H7UI_LED_CHG_RED };
		for (unsigned i = 0; i < 3; i++) {
			h7lcd_fill_rect(100 + 14 * i, 40, 10, 10, 0xFFFF);   /* 1, 2, 3 squares: RUN, CHG green, CHG red */
			h7ui_led(order[i], H7UI_LED_DEFAULT);
			delay_ms(2000);
			h7ui_led(order[i], 0);
			delay_ms(500);
		}
		static const uint8_t level[] = { 0x20, 0x80, 0xFF, 0x80 };
		for (unsigned i = 0; i < 4; i++) { h7ui_backlight(level[i]); delay_ms(2000); }
	}
	return_to_boot_loader();
}

static void default_handler(void) { for (;;) { } }

__attribute__((section(".isr_vector"), used))
void (*const vectors[])(void) = {
	(void (*)(void))&_estack,
	Reset_Handler,
	default_handler, default_handler, default_handler, default_handler,
};
