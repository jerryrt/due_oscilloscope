/* Image 19: USB-less test of the I2C expander (backlight and LEDs), with the LCD as the display.
 *
 * Pins and sequence are read from the stock boot loader (docs/22): panel
 * power PH15 high, reset PB6 (low pulse), chip select PE1 (low active),
 * D/C PG15 (low = command), SCK PH6 and data PH7 clocked by hand in
 * mode 3, backlight PH9 on TIM12_CH2. The ST7789 table is the boot
 * loader's model 0/1 table. The backlight is held at a low duty on
 * purpose: PH9 is also the buzzer pin in the stock app, and a low
 * average level keeps a buzzer behind it quiet. No other pin is touched
 * (TVCC, PG1 and the I2C pot are left alone). Core stays on its reset
 * clock (HSI, 64 MHz *(check)*). */
#include <stdint.h>

#define RCC_AHB4ENR  (*(volatile uint32_t *)0x58024540u)
#define RCC_APB1LENR (*(volatile uint32_t *)0x580244E8u)
#define GPIO(b, o)   (*(volatile uint32_t *)((b) + (o)))
#define GPIOB 0x58020400u
#define GPIOE 0x58021000u
#define GPIOG 0x58021800u
#define GPIOH 0x58021C00u
#define MODER 0x00u
#define OSPEEDR 0x08u
#define AFRH  0x24u
#define OTYPER 0x04u
#define PUPDR 0x0Cu
#define IDR   0x10u
#define BSRR  0x18u
#define TIM12(o) (*(volatile uint32_t *)(0x40001800u + (o)))
#define SYST_CSR     (*(volatile uint32_t *)0xE000E010u)
#define SYST_RVR     (*(volatile uint32_t *)0xE000E014u)
#define SYST_CVR     (*(volatile uint32_t *)0xE000E018u)
#define SCB_AIRCR    (*(volatile uint32_t *)0xE000ED0Cu)
#define BOOT_REQ     (*(volatile uint32_t *)0x20000000u)

#define BOOT_MAGIC   0x5AA51234u
#define CPU_HZ       64000000u
#ifndef RUN_MS
#define RUN_MS       0u
#endif
#ifndef BL_PERCENT
#define BL_PERCENT   0u                      /* backlight duty, 0 = leave PH9 alone; keep low, see the header */
#endif

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
	SCB_AIRCR = 0x05FA0004u;                 /* SYSRESETREQ */
	for (;;) { }
}

static void set_out(uint32_t port, unsigned pin)
{
	GPIO(port, MODER) = (GPIO(port, MODER) & ~(3u << (2 * pin))) | (1u << (2 * pin));
	GPIO(port, OSPEEDR) |= 3u << (2 * pin);
}

#define CS_L()  (GPIO(GPIOE, BSRR) = 1u << (1 + 16))
#define CS_H()  (GPIO(GPIOE, BSRR) = 1u << 1)
#define DC_L()  (GPIO(GPIOG, BSRR) = 1u << (15 + 16))
#define DC_H()  (GPIO(GPIOG, BSRR) = 1u << 15)
#define RST_L() (GPIO(GPIOB, BSRR) = 1u << (6 + 16))
#define RST_H() (GPIO(GPIOB, BSRR) = 1u << 6)

/* Mode 3: clock idles high, data changes with the clock low, the panel
 * samples on the rising edge. */
static void spi_byte(uint8_t b)
{
	for (int i = 7; i >= 0; i--) {
		GPIO(GPIOH, BSRR) = (1u << (6 + 16)) | ((b >> i & 1u) ? (1u << 7) : (1u << (7 + 16)));
		GPIO(GPIOH, BSRR) = 1u << 6;
	}
}

static void cmd(uint8_t c)           { DC_L(); CS_L(); spi_byte(c); CS_H(); }
static void dat(uint8_t d)           { DC_H(); CS_L(); spi_byte(d); CS_H(); }
static void cmd_n(uint8_t c, const uint8_t *p, unsigned n)
{
	cmd(c);
	while (n--) dat(*p++);
}

/* Boot loader model 0/1 table (H7-BOOT.bin 0x0800c88e..0x0800c9f4). */
static const uint8_t b2[] = { 0x0c, 0x0c, 0x00, 0x33, 0x33 };
static const uint8_t d0[] = { 0xa4, 0xa1 };
static const uint8_t e0[] = { 0xd0, 0x04, 0x0d, 0x11, 0x13, 0x2b, 0x3f, 0x54, 0x4c, 0x18, 0x0d, 0x0b, 0x1f, 0x23 };
static const uint8_t e1[] = { 0xd0, 0x04, 0x0c, 0x11, 0x13, 0x2c, 0x3f, 0x44, 0x51, 0x2f, 0x1f, 0x1f, 0x20, 0x23 };

static void lcd_init(void)
{
	static const uint8_t z = 0x00, c3a = 0x05, v35 = 0x35, v19 = 0x19, v2c = 0x2c,
	                     v01 = 0x01, v12 = 0x12, v20 = 0x20, v0f = 0x0f;
	cmd_n(0x36, &z, 1);
	cmd_n(0x3a, &c3a, 1);
	cmd_n(0xb2, b2, sizeof b2);
	cmd_n(0xb7, &v35, 1);
	cmd_n(0xbb, &v19, 1);
	cmd_n(0xc0, &v2c, 1);
	cmd_n(0xc2, &v01, 1);
	cmd_n(0xc3, &v12, 1);
	cmd_n(0xc4, &v20, 1);
	cmd_n(0xc6, &v0f, 1);
	cmd_n(0xd0, d0, sizeof d0);
	cmd_n(0xe0, e0, sizeof e0);
	cmd_n(0xe1, e1, sizeof e1);
	cmd(0x21);
	cmd(0x11);
	delay_ms(120);
	cmd(0x29);
	delay_ms(20);
}

static void window(void)
{
	static const uint8_t full[] = { 0x00, 0x00, 0x00, 0xEF };   /* 0..239 */
	cmd_n(0x2a, full, 4);
	cmd_n(0x2b, full, 4);
	cmd(0x2c);
}

/* Four 60-row bands red, green, blue, white; a 40x40 black square at the
 * top left (origin marker) and a one-pixel white border. */
static uint16_t pixel(unsigned x, unsigned y)
{
	if (x < 40 && y < 40) return 0x0000;
	if (x == 0 || y == 0 || x == 239 || y == 239) return 0xFFFF;
	switch (y / 60) {
	case 0:  return 0xF800;
	case 1:  return 0x07E0;
	case 2:  return 0x001F;
	default: return 0xFFFF;
	}
}

static void backlight(unsigned percent)
{
	RCC_APB1LENR |= 1u << 6;                 /* TIM12 */
	(void)RCC_APB1LENR;
	GPIO(GPIOH, MODER) = (GPIO(GPIOH, MODER) & ~(3u << 18)) | (2u << 18);   /* PH9 alternate */
	GPIO(GPIOH, AFRH) = (GPIO(GPIOH, AFRH) & ~(0xFu << 4)) | (2u << 4);     /* AF2 = TIM12_CH2 */
	TIM12(0x28) = 0;                         /* PSC */
	TIM12(0x2C) = CPU_HZ / 20000u - 1u;      /* 20 kHz */
	TIM12(0x38) = (CPU_HZ / 20000u) * percent / 100u;
	TIM12(0x18) = (6u << 12) | (1u << 11);   /* PWM mode 1, preload, channel 2 */
	TIM12(0x20) = 1u << 4;                   /* CC2E */
	TIM12(0x14) = 1u;                        /* update */
	TIM12(0x00) = 1u;                        /* counter enable */
}


#ifndef CHIP_INIT
#define CHIP_INIT 1                           /* 0 = write only the dimming registers */
#endif

/* Soft I2C to the expander at 8-bit address 0xB6: SCL PB6, SDA PG0, both
 * open drain with the internal pull-up as well (docs/22). */
#define SCL_H() (GPIO(GPIOB, BSRR) = 1u << 6)
#define SCL_L() (GPIO(GPIOB, BSRR) = 1u << (6 + 16))
#define SDA_H() (GPIO(GPIOG, BSRR) = 1u << 0)
#define SDA_L() (GPIO(GPIOG, BSRR) = 1u << (0 + 16))
#define SDA_RD() (GPIO(GPIOG, IDR) & 1u)
#define TI2C()  delay_us(20)

static void i2c_pins(void)
{
	GPIO(GPIOB, OTYPER) |= 1u << 6;
	GPIO(GPIOG, OTYPER) |= 1u << 0;
	GPIO(GPIOB, PUPDR) = (GPIO(GPIOB, PUPDR) & ~(3u << 12)) | (1u << 12);
	GPIO(GPIOG, PUPDR) = (GPIO(GPIOG, PUPDR) & ~3u) | 1u;
	SCL_H(); SDA_H();
	set_out(GPIOB, 6); set_out(GPIOG, 0);
}
static void i2c_start(void) { SDA_H(); SCL_H(); TI2C(); SDA_L(); TI2C(); SCL_L(); TI2C(); }
static void i2c_stop(void)  { SDA_L(); TI2C(); SCL_H(); TI2C(); SDA_H(); TI2C(); }
static int i2c_put(uint8_t b)                 /* 1 if acknowledged */
{
	for (int i = 7; i >= 0; i--) {
		if (b >> i & 1u) SDA_H(); else SDA_L();
		TI2C(); SCL_H(); TI2C(); SCL_L(); TI2C();
	}
	SDA_H(); TI2C(); SCL_H(); TI2C();
	int ack = !SDA_RD();
	SCL_L(); TI2C();
	return ack;
}
static uint8_t i2c_get_nak(void)
{
	uint8_t v = 0;
	SDA_H();
	for (int i = 0; i < 8; i++) {
		TI2C(); SCL_H(); TI2C();
		v = (uint8_t)(v << 1 | SDA_RD());
		SCL_L();
	}
	TI2C(); SCL_H(); TI2C(); SCL_L(); TI2C();   /* NAK: SDA stays high */
	return v;
}
static int chip_write(uint8_t reg, uint8_t val)
{
	i2c_start();
	int ok = i2c_put(0xB6) && i2c_put(reg) && i2c_put(val);
	i2c_stop();
	return ok;
}
static int chip_read(uint8_t reg, uint8_t *val)
{
	i2c_start();
	int ok = i2c_put(0xB6) && i2c_put(reg);
	if (ok) {
		SDA_H(); SCL_H(); TI2C();
		i2c_start();
		ok = i2c_put(0xB7);
		if (ok) *val = i2c_get_nak();
	}
	i2c_stop();
	return ok;
}

static void rect(unsigned x, unsigned y, unsigned w, unsigned h, uint16_t c)
{
	uint8_t xa[] = { 0, (uint8_t)x, 0, (uint8_t)(x + w - 1) };
	uint8_t ya[] = { 0, (uint8_t)y, 0, (uint8_t)(y + h - 1) };
	cmd_n(0x2a, xa, 4); cmd_n(0x2b, ya, 4); cmd(0x2c);
	DC_H(); CS_L();
	for (unsigned i = 0; i < w * h; i++) { spi_byte(c >> 8); spi_byte(c & 0xFF); }
	CS_H();
}

/* Step k of the schedule is shown as k white squares along the bottom. */
static void step_marker(unsigned k)
{
	rect(0, 215, 240, 25, 0x0000);
	for (unsigned i = 0; i < k; i++) rect(8 + i * 28, 218, 20, 20, 0xFFFF);
}

static void led_step(unsigned k, uint8_t reg)
{
	step_marker(k);
	chip_write(reg, 0x80);
	delay_ms(3000);
	chip_write(reg, 0x00);
	delay_ms(1000);
}

void Reset_Handler(void)
{
	uint32_t *s = &_sidata, *d = &_sdata;
	while (d < &_edata) *d++ = *s++;
	for (d = &_sbss; d < &_ebss; ) *d++ = 0;

	SYST_RVR = 0xFFFFFFu;
	SYST_CSR = 5u;

	RCC_AHB4ENR |= (1u << 1) | (1u << 4) | (1u << 6) | (1u << 7);   /* GPIOB, E, G, H */
	(void)RCC_AHB4ENR;

	CS_H(); DC_H();
	GPIO(GPIOH, BSRR) = (1u << 6) | (1u << 7);
	set_out(GPIOE, 1); set_out(GPIOG, 15);
	set_out(GPIOH, 6); set_out(GPIOH, 7);

	GPIO(GPIOH, BSRR) = 1u << 15;                   /* panel power on */
	set_out(GPIOH, 15);
	delay_ms(170);                                  /* the panel resets itself on power-up (D254 RC) *(check)* */

	lcd_init();
	window();
	DC_H(); CS_L();
	for (unsigned y = 0; y < 240; y++)
		for (unsigned x = 0; x < 240; x++) {
			uint16_t p = pixel(x, y);
			spi_byte(p >> 8); spi_byte(p & 0xFF);
		}
	CS_H();

	i2c_pins();
	delay_ms(2000);                                 /* time to look at the picture *before* the chip is used */

	/* Presence: the ID register reads 0x23. Top right: green = ID read, red = no answer or wrong. */
	uint8_t id = 0;
	int ok = chip_read(0x10, &id);
	rect(180, 8, 52, 24, (ok && id == 0x23) ? 0x07E0 : 0xF800);
	delay_ms(3000);

#if CHIP_INIT
	chip_write(0x04, 0xFE);                         /* boot loader values, docs/22 */
	chip_write(0x05, 0x90);
	chip_write(0x11, 0x13);                         /* push-pull, IMAX/4 for the indicator LEDs */
	chip_write(0x12, 0xFE);
	chip_write(0x13, 0xF0);
#endif
	led_step(1, 0x20);                              /* P1_0 */
	led_step(2, 0x21);                              /* P1_1 */
	led_step(3, 0x22);                              /* P1_2 */
	led_step(4, 0x23);                              /* P1_3 */

	/* Backlight, P0_0 (register 0x24): off, dim, mid, full. The marker is only visible while lit. */
#if CHIP_INIT
	chip_write(0x11, 0x10);                         /* full range, as the boot loader */
#endif
	step_marker(5);
	chip_write(0x24, 0x00);  delay_ms(3000);
	chip_write(0x24, 0x10);  delay_ms(3000);
	chip_write(0x24, 0x80);  delay_ms(3000);
	chip_write(0x24, 0xFF);  delay_ms(3000);

	return_to_boot_loader();
}

static void default_handler(void) { for (;;) { } }

__attribute__((section(".isr_vector"), used))
void (*const vectors[])(void) = {
	(void (*)(void))&_estack,
	Reset_Handler,
	default_handler, default_handler, default_handler, default_handler,
};
