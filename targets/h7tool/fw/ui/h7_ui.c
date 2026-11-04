/* The H7-TOOL display, backlight and LED driver. See h7_ui.h and docs/22. */
#include "h7_ui.h"

#ifdef H7UI_HOST
uint32_t h7ui_host_rd(uint32_t addr);
void     h7ui_host_wr(uint32_t addr, uint32_t val);
#define REG_RD(a)     h7ui_host_rd(a)
#define REG_WR(a, v)  h7ui_host_wr((a), (v))
#else
#define REG_RD(a)     (*(volatile uint32_t *)(a))
#define REG_WR(a, v)  (*(volatile uint32_t *)(a) = (v))
#endif

#define RCC_AHB4ENR 0x58024540u
#define GPIOB 0x58020400u
#define GPIOE 0x58021000u
#define GPIOG 0x58021800u
#define GPIOH 0x58021C00u
#define MODER   0x00u
#define OTYPER  0x04u
#define OSPEEDR 0x08u
#define PUPDR   0x0Cu
#define IDR     0x10u
#define BSRR    0x18u

#define EXPANDER_ADDR 0xB6u
#define I2C_HALF_US   20u            /* 25 kHz: the pull-ups are the chip's own and the internal ones */
#define EXP_REG_ID    0x10u
#define EXP_ID        0x23u
#define EXP_REG_DIM_BACKLIGHT 0x24u  /* P0_0 */
#define EXP_REG_DIM_LED0      0x20u  /* P1_0; P1_n is 0x20 + n */

#define H7LCD_MADCTL 0xC0u           /* the boot loader's direction 1: upright portrait on this glass */

static void (*delay_us_fn)(uint32_t);

void h7ui_set_delay(void (*delay_us)(uint32_t us)) { delay_us_fn = delay_us; }

static void dly(uint32_t us) { if (delay_us_fn) delay_us_fn(us); }
static void dly_ms(uint32_t ms) { while (ms--) dly(1000); }

static void gpio_out(uint32_t port, unsigned pin)
{
	REG_WR(port + MODER, (REG_RD(port + MODER) & ~(3u << (2 * pin))) | (1u << (2 * pin)));
	REG_WR(port + OSPEEDR, REG_RD(port + OSPEEDR) | (3u << (2 * pin)));
}

static int clocks_on;
static void gpio_clocks(void)
{
	if (clocks_on) return;
	REG_WR(RCC_AHB4ENR, REG_RD(RCC_AHB4ENR) | (1u << 1) | (1u << 4) | (1u << 6) | (1u << 7));   /* GPIOB, E, G, H */
	(void)REG_RD(RCC_AHB4ENR);
	clocks_on = 1;
}

/* ---- soft I2C: SCL PB6, SDA PG0, open drain, idle high ---- */

#define SCL_H()  REG_WR(GPIOB + BSRR, 1u << 6)
#define SCL_L()  REG_WR(GPIOB + BSRR, 1u << (6 + 16))
#define SDA_H()  REG_WR(GPIOG + BSRR, 1u << 0)
#define SDA_L()  REG_WR(GPIOG + BSRR, 1u << (0 + 16))
#define SDA_RD() (REG_RD(GPIOG + IDR) & 1u)

static int i2c_ready;
static void i2c_pins(void)
{
	if (i2c_ready) return;
	gpio_clocks();
	REG_WR(GPIOB + OTYPER, REG_RD(GPIOB + OTYPER) | (1u << 6));
	REG_WR(GPIOG + OTYPER, REG_RD(GPIOG + OTYPER) | (1u << 0));
	REG_WR(GPIOB + PUPDR, (REG_RD(GPIOB + PUPDR) & ~(3u << 12)) | (1u << 12));
	REG_WR(GPIOG + PUPDR, (REG_RD(GPIOG + PUPDR) & ~3u) | 1u);
	SCL_H(); SDA_H();
	gpio_out(GPIOB, 6); gpio_out(GPIOG, 0);
	i2c_ready = 1;
}

static void i2c_start(void) { SDA_H(); SCL_H(); dly(I2C_HALF_US); SDA_L(); dly(I2C_HALF_US); SCL_L(); dly(I2C_HALF_US); }
static void i2c_stop(void)  { SDA_L(); dly(I2C_HALF_US); SCL_H(); dly(I2C_HALF_US); SDA_H(); dly(I2C_HALF_US); }

static int i2c_put(uint8_t b)         /* 1 if acknowledged */
{
	for (int i = 7; i >= 0; i--) {
		if ((b >> i) & 1u) SDA_H(); else SDA_L();
		dly(I2C_HALF_US); SCL_H(); dly(I2C_HALF_US); SCL_L(); dly(I2C_HALF_US);
	}
	SDA_H(); dly(I2C_HALF_US); SCL_H(); dly(I2C_HALF_US);
	int ack = !SDA_RD();
	SCL_L(); dly(I2C_HALF_US);
	return ack;
}

static uint8_t i2c_get_nak(void)
{
	uint8_t v = 0;
	SDA_H();
	for (int i = 0; i < 8; i++) {
		dly(I2C_HALF_US); SCL_H(); dly(I2C_HALF_US);
		v = (uint8_t)((v << 1) | SDA_RD());
		SCL_L();
	}
	dly(I2C_HALF_US); SCL_H(); dly(I2C_HALF_US); SCL_L(); dly(I2C_HALF_US);   /* NAK: SDA stays high */
	return v;
}

int h7ui_expander_write(uint8_t reg, uint8_t val)
{
	i2c_pins();
	i2c_start();
	int ok = i2c_put(EXPANDER_ADDR) && i2c_put(reg) && i2c_put(val);
	i2c_stop();
	return ok;
}

static int expander_read(uint8_t reg, uint8_t *val)
{
	i2c_pins();
	i2c_start();
	int ok = i2c_put(EXPANDER_ADDR) && i2c_put(reg);
	if (ok) {
		SDA_H(); SCL_H(); dly(I2C_HALF_US);
		i2c_start();                          /* repeated start */
		ok = i2c_put(EXPANDER_ADDR | 1u);
		if (ok) *val = i2c_get_nak();
	}
	i2c_stop();
	return ok;
}

int h7ui_expander_init(void)
{
	uint8_t id = 0;
	if (!expander_read(EXP_REG_ID, &id) || id != EXP_ID) return 0;
	/* The boot loader's values (docs/22): P0_0 output and the rest input, P1_0..3 and P1_5..6 output, push-pull,
	 * full current range, P0_0 and P1_0..3 in LED mode, everything else GPIO. */
	h7ui_expander_write(0x04, 0xFE);
	h7ui_expander_write(0x05, 0x90);
	h7ui_expander_write(0x11, 0x10);
	h7ui_expander_write(0x12, 0xFE);
	h7ui_expander_write(0x13, 0xF0);
	for (unsigned i = 0; i < H7UI_LED_COUNT; i++) h7ui_led((enum h7ui_led)i, 0);
	return 1;
}

void h7ui_backlight(uint8_t level) { h7ui_expander_write(EXP_REG_DIM_BACKLIGHT, level); }

void h7ui_led(enum h7ui_led led, uint8_t level)
{
	if ((unsigned)led >= H7UI_LED_COUNT) return;
	h7ui_expander_write((uint8_t)(EXP_REG_DIM_LED0 + (unsigned)led), level);
}

/* ---- panel ---- */

#define CS_L() REG_WR(GPIOE + BSRR, 1u << (1 + 16))
#define CS_H() REG_WR(GPIOE + BSRR, 1u << 1)
#define DC_L() REG_WR(GPIOG + BSRR, 1u << (15 + 16))
#define DC_H() REG_WR(GPIOG + BSRR, 1u << 15)

/* Mode 3: the clock idles high, data changes while it is low, the panel samples the rising edge. */
static void spi_byte(uint8_t b)
{
	for (int i = 7; i >= 0; i--) {
		REG_WR(GPIOH + BSRR, (1u << (6 + 16)) | (((b >> i) & 1u) ? (1u << 7) : (1u << (7 + 16))));
		REG_WR(GPIOH + BSRR, 1u << 6);
	}
}

static void cmd(uint8_t c)  { DC_L(); CS_L(); spi_byte(c); CS_H(); }
static void dat(uint8_t d)  { DC_H(); CS_L(); spi_byte(d); CS_H(); }
static void cmd_n(uint8_t c, const uint8_t *p, unsigned n) { cmd(c); while (n--) dat(*p++); }
static void cmd_1(uint8_t c, uint8_t v) { cmd_n(c, &v, 1); }

/* The boot loader's model 0/1 table (H7-BOOT.bin 0x0800c88e..0x0800c9f4), with MADCTL for the upright direction. */
static const uint8_t t_b2[] = { 0x0c, 0x0c, 0x00, 0x33, 0x33 };
static const uint8_t t_d0[] = { 0xa4, 0xa1 };
static const uint8_t t_e0[] = { 0xd0, 0x04, 0x0d, 0x11, 0x13, 0x2b, 0x3f, 0x54, 0x4c, 0x18, 0x0d, 0x0b, 0x1f, 0x23 };
static const uint8_t t_e1[] = { 0xd0, 0x04, 0x0c, 0x11, 0x13, 0x2c, 0x3f, 0x44, 0x51, 0x2f, 0x1f, 0x1f, 0x20, 0x23 };

void h7lcd_init(void)
{
	gpio_clocks();
	CS_H(); DC_H();
	REG_WR(GPIOH + BSRR, (1u << 6) | (1u << 7));       /* clock idle high */
	gpio_out(GPIOE, 1); gpio_out(GPIOG, 15); gpio_out(GPIOH, 6); gpio_out(GPIOH, 7);
	REG_WR(GPIOH + BSRR, 1u << 15);                    /* panel power on */
	gpio_out(GPIOH, 15);
	dly_ms(170);                                       /* power-on reset of the panel, then its start-up time *(check)* */

	cmd_1(0x36, H7LCD_MADCTL);
	cmd_1(0x3a, 0x05);                                 /* RGB565 */
	cmd_n(0xb2, t_b2, sizeof t_b2);
	cmd_1(0xb7, 0x35);
	cmd_1(0xbb, 0x19);
	cmd_1(0xc0, 0x2c);
	cmd_1(0xc2, 0x01);
	cmd_1(0xc3, 0x12);
	cmd_1(0xc4, 0x20);
	cmd_1(0xc6, 0x0f);
	cmd_n(0xd0, t_d0, sizeof t_d0);
	cmd_n(0xe0, t_e0, sizeof t_e0);
	cmd_n(0xe1, t_e1, sizeof t_e1);
	cmd(0x21);                                         /* inversion on */
	cmd(0x11);                                         /* sleep out */
	dly_ms(120);
	cmd(0x29);                                         /* display on */
	dly_ms(20);
}

int h7lcd_begin(unsigned x, unsigned y, unsigned w, unsigned h)
{
	if (w == 0 || h == 0 || x >= H7LCD_W || y >= H7LCD_H || w > H7LCD_W - x || h > H7LCD_H - y) return 0;
	uint8_t xa[] = { (uint8_t)(x >> 8), (uint8_t)x, (uint8_t)((x + w - 1) >> 8), (uint8_t)(x + w - 1) };
	uint8_t ya[] = { (uint8_t)(y >> 8), (uint8_t)y, (uint8_t)((y + h - 1) >> 8), (uint8_t)(y + h - 1) };
	cmd_n(0x2a, xa, 4);
	cmd_n(0x2b, ya, 4);
	cmd(0x2c);
	DC_H(); CS_L();
	return 1;
}

void h7lcd_pixel(uint16_t c) { spi_byte((uint8_t)(c >> 8)); spi_byte((uint8_t)c); }

void h7lcd_end(void) { CS_H(); }

void h7lcd_fill_rect(unsigned x, unsigned y, unsigned w, unsigned h, uint16_t c)
{
	if (x >= H7LCD_W || y >= H7LCD_H) return;
	if (w > H7LCD_W - x) w = H7LCD_W - x;                    /* clipped to the glass */
	if (h > H7LCD_H - y) h = H7LCD_H - y;
	if (!h7lcd_begin(x, y, w, h)) return;
	for (unsigned n = w * h; n; n--) h7lcd_pixel(c);
	h7lcd_end();
}
