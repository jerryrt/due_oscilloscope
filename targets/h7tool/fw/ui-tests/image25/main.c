/* Image 25: the driver's SPI5 path on the unit, with the peripheral's registers shown as hex digits when it fails;
 * the speed is measured as in image 24: a full-screen fill is timed with SysTick and
 * shown as white squares, one per 10 ms, along the bottom. Then a timed return to the boot loader.
 * Build: tools/build_image.sh fw/ui-tests/image24 image24a fw/ui/h7_ui.c -Ifw/ui [-DH7UI_HW_SPI=0 for the pins path]
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

/* Seven-segment hex digit, 10 wide by 18 tall, segments a..g. */
static void digit(unsigned x, unsigned y, unsigned v, uint16_t c)
{
	static const uint8_t seg[16] = { 0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F, 0x77, 0x7C, 0x39, 0x5E, 0x79, 0x71 };
	uint8_t m = seg[v & 15u];
	if (m & 0x01) h7lcd_fill_rect(x + 2, y,      6, 2, c);   /* a */
	if (m & 0x02) h7lcd_fill_rect(x + 8, y + 2,  2, 7, c);   /* b */
	if (m & 0x04) h7lcd_fill_rect(x + 8, y + 10, 2, 7, c);   /* c */
	if (m & 0x08) h7lcd_fill_rect(x + 2, y + 16, 6, 2, c);   /* d */
	if (m & 0x10) h7lcd_fill_rect(x,     y + 10, 2, 7, c);   /* e */
	if (m & 0x20) h7lcd_fill_rect(x,     y + 2,  2, 7, c);   /* f */
	if (m & 0x40) h7lcd_fill_rect(x + 2, y + 8,  6, 2, c);   /* g */
}

static void row(unsigned i, uint32_t v, uint16_t c)
{
	unsigned y = 20 + 26 * i;
	h7lcd_fill_rect(0, y, 6, 18, c);                       /* row marker */
	for (unsigned k = 0; k < 8; k++) digit(12 + 14 * k, y, (v >> (28 - 4 * k)) & 15u, c);
}

#define R32(a) (*(volatile uint32_t *)(a))

void Reset_Handler(void)
{
	uint32_t *s = &_sidata, *d = &_sdata;
	while (d < &_edata) *d++ = *s++;
	for (d = &_sbss; d < &_ebss; ) *d++ = 0;
	SYST_RVR = 0xFFFFFFu;
	SYST_CSR = 5u;

	h7ui_set_delay(delay_us);
	h7lcd_init();

	uint32_t t0 = SYST_CVR;
	h7lcd_fill_rect(0, 0, 240, 320, 0x0010);               /* the timed full-screen fill */
	uint32_t ticks = (t0 - SYST_CVR) & 0xFFFFFFu;
	uint32_t ms10 = ticks / (CPU_HZ / 100u);               /* units of 10 ms */
	h7lcd_fill_rect(0, 0, 240, 320, 0x0010);
	/* rows, top to bottom: SR then CR1 as they were when the wait gave up (0 if it never did), then live:
	 * SPI5 CFG1, CFG2, CR2, RCC D2CCIP1R (SPI4/5 clock select), RCC APB2ENR, RCC AHB4ENR */
	row(0, h7ui_spi_status_at_error(),  0xFFFF);
	row(1, h7ui_spi_control_at_error(), 0xFFE0);
	row(2, R32(0x40015008u), 0x07E0);
	row(3, R32(0x4001500Cu), 0x07FF);
	row(4, R32(0x40015004u), 0xF81F);
	row(5, R32(0x58024450u), 0xFD20);
	row(6, R32(0x580244F0u), 0x8410);
	row(7, R32(0x58024540u), 0x867D);
	for (uint32_t i = 0; i < ms10 && i < 20; i++) h7lcd_fill_rect(4 + 11 * i, 240, 8, 8, 0xFFFF);   /* fill time, 10 ms each */
	if (h7ui_spi_errors()) h7lcd_fill_rect(216, 270, 20, 20, 0xF800);
	delay_ms(120000);
	return_to_boot_loader();
}

static void default_handler(void) { for (;;) { } }

__attribute__((section(".isr_vector"), used))
void (*const vectors[])(void) = {
	(void (*)(void))&_estack,
	Reset_Handler,
	default_handler, default_handler, default_handler, default_handler,
};
