/* The H7-TOOL display, backlight and LED driver. See h7_ui.h and docs/22. */
#include "h7_ui.h"

#ifndef H7UI_HW_SPI
#define H7UI_HW_SPI 1                /* 1 = SPI5 peripheral, 0 = clock the pins by hand (the first, slower path) */
#endif

#ifdef H7UI_HOST
uint32_t h7ui_host_rd(uint32_t addr);
void     h7ui_host_wr(uint32_t addr, uint32_t val);
void     h7ui_host_wr8(uint32_t addr, uint8_t val);
#define REG_RD(a)     h7ui_host_rd(a)
#define REG_WR(a, v)  h7ui_host_wr((a), (v))
#define REG_WR8(a, v) h7ui_host_wr8((a), (v))
#else
#define REG_RD(a)     (*(volatile uint32_t *)(a))
#define REG_WR(a, v)  (*(volatile uint32_t *)(a) = (v))
#define REG_WR8(a, v) (*(volatile uint8_t *)(a) = (uint8_t)(v))
#endif

#define RCC_AHB4ENR 0x58024540u
#define RCC_CR        0x58024400u
#define RCC_PLLCKSELR 0x58024428u
#define RCC_PLLCFGR   0x5802442Cu
#define RCC_PLL2DIVR  0x58024438u
#define RCC_D2CCIP1R  0x58024450u
#define RCC_AHB1ENR 0x58024538u
#define DMA2_LIFCR  0x40020408u
#define DMA2_S3     0x40020458u      /* stream 3: CR +0, NDTR +4, PAR +8, M0AR +0xC, FCR +0x14 */
#define DMAMUX1_C11 0x4002082Cu      /* DMA2 stream 3 is request line 11 of DMAMUX1 */
#define DMAREQ_SPI5_TX 86u           /* RM0433 DMAMUX1 request list *(check against the unit: the transfer completing is the proof)* */
#define RCC_APB2ENR 0x580244F0u
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
#define AFRL    0x20u

#define EXPANDER_ADDR 0xB6u
#define I2C_HALF_US   20u            /* 25 kHz: the pull-ups are the chip's own and the internal ones */
#define EXP_REG_ID    0x10u
#define EXP_ID        0x23u
#define EXP_REG_DIM_BACKLIGHT 0x24u  /* P0_0 */
#define EXP_REG_DIM_LED0      0x20u  /* P1_0; P1_n is 0x20 + n */

/* SPI5 (the STM32H7 SPI with FIFO): kernel clock is the APB2 clock at reset. */
#define SPI5_BASE   0x40015000u
#define SPI_CR1     (SPI5_BASE + 0x00u)
#define SPI_CR2     (SPI5_BASE + 0x04u)
#define SPI_CFG1    (SPI5_BASE + 0x08u)
#define SPI_CFG2    (SPI5_BASE + 0x0Cu)
#define SPI_SR      (SPI5_BASE + 0x14u)
#define SPI_IFCR    (SPI5_BASE + 0x18u)
#define SPI_TXDR    (SPI5_BASE + 0x20u)
#define SPI_CR1_SPE    (1u << 0)
#define SPI_CR1_CSTART (1u << 9)
#define SPI_CR1_SSI    (1u << 12)
#define SPI_SR_TXP     (1u << 1)
#define SPI_SR_EOT     (1u << 3)
#define SPI_IFCR_CLEAR ((1u << 3) | (1u << 4) | (1u << 11))   /* EOTC, TXTFC, SUSPC */
#define SPI_IFCR_ALL   0xFF8u                                  /* every flag clear bit, MODFC (9) among them */
#ifndef H7UI_FAST
#define H7UI_FAST 1                  /* 1 = feed SPI5 from PLL2 at 160 MHz (80 MHz bit clock) when PLL2 is free; 0 = stay on the 100 MHz APB2 clock */
#endif
#define PLL_SPINS 20000u             /* PLL2 locks in tens of microseconds; this is far more */
#ifndef SPI_MBR
#define SPI_MBR        0u            /* kernel clock / 2 = 50 MHz at the 100 MHz kernel clock; the stock rate, measured clean (docs/22) */
#endif
#define SPI_SPIN_MAX   4000u         /* one wait is a frame or a few at most (well under a millisecond); more means stuck */
#define SPI_CHUNK_MAX  65534u        /* TSIZE is 16 bits; an even count keeps whole pixels in a chunk */

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

/* Mode 3 by hand: the clock idles high, data changes while it is low, the panel samples the rising edge. This is the
 * whole path when H7UI_HW_SPI is 0, and the fallback when an SPI5 wait gives up. */
static void bitbang_byte(uint8_t b)
{
	for (int i = 7; i >= 0; i--) {
		REG_WR(GPIOH + BSRR, (1u << (6 + 16)) | (((b >> i) & 1u) ? (1u << 7) : (1u << (7 + 16))));
		REG_WR(GPIOH + BSRR, 1u << 6);
	}
}

static unsigned spi_errors;
static uint32_t spi_sr_at_error, spi_cr1_at_error;
static int hw_active = H7UI_HW_SPI;                      /* 1 while SPI5 carries the bytes */
unsigned h7ui_spi_errors(void) { return spi_errors; }
uint32_t h7ui_spi_status_at_error(void) { return spi_sr_at_error; }
uint32_t h7ui_spi_control_at_error(void) { return spi_cr1_at_error; }

/* PH6 and PH7 back to plain outputs, the clock high. */
static void pins_to_gpio(void)
{
	REG_WR(GPIOH + BSRR, (1u << 6) | (1u << 7));
	REG_WR(GPIOH + MODER, (REG_RD(GPIOH + MODER) & ~((3u << 12) | (3u << 14))) | (1u << 12) | (1u << 14));
	REG_WR(GPIOH + OSPEEDR, REG_RD(GPIOH + OSPEEDR) | (3u << 12) | (3u << 14));
}

#define SPI_SPIN_STUCK 0u
/* A wait that gives up costs SPI_SPIN_MAX reads once. The first timeout hands the panel to the hand-clocked pins for
 * good and keeps the status it saw, so a stuck peripheral costs a fraction of a millisecond and the picture still
 * arrives, slowly, with the error to read afterwards. */
static int spi_wait(uint32_t mask)
{
	for (uint32_t n = SPI_SPIN_MAX; n; n--)
		if (REG_RD(SPI_SR) & mask) return 1;
	spi_errors++;
	spi_sr_at_error = REG_RD(SPI_SR);
	spi_cr1_at_error = REG_RD(SPI_CR1);
	hw_active = 0;
	REG_WR(SPI_CR1, 0);
	pins_to_gpio();
	return SPI_SPIN_STUCK;
}

#if H7UI_HW_SPI
static int pll2_active;

/* Start PLL2 at 160 MHz (HSE 25 MHz / 5 x 128 / 4) and select it for SPI4/5. Only from the state the images leave RCC in:
 * PLL1 running from the HSE with M = 5, PLL2 off and unused. Anything else, or a PLL that does not lock, leaves the
 * 100 MHz APB2 clock in place (SPI5 still works, at 50 MHz). Returns 1 when SPI5 will run from PLL2. */
static int pll2_start(void)
{
	uint32_t cksel = REG_RD(RCC_PLLCKSELR);
	if ((REG_RD(RCC_CR) & (1u << 26)) || (cksel & 3u) != 2u || ((cksel >> 4) & 0x3Fu) != 5u || ((cksel >> 12) & 0x3Fu) != 0u) return 0;
	REG_WR(RCC_PLLCKSELR, cksel | (5u << 12));                                            /* DIVM2 = 5: 5 MHz reference */
	REG_WR(RCC_PLLCFGR, (REG_RD(RCC_PLLCFGR) & ~((1u << 4) | (1u << 5) | (3u << 6))) | (2u << 6) | (1u << 20));   /* no fraction, wide VCO, 4-8 MHz input, Q output on */
	REG_WR(RCC_PLL2DIVR, (127u) | (1u << 9) | (3u << 16) | (1u << 24));                   /* N 128 (640 MHz VCO), P 2, Q 4 (160 MHz), R 2 */
	REG_WR(RCC_CR, REG_RD(RCC_CR) | (1u << 26));
	for (uint32_t n = PLL_SPINS; n; n--)
		if (REG_RD(RCC_CR) & (1u << 27)) {
			REG_WR(RCC_D2CCIP1R, (REG_RD(RCC_D2CCIP1R) & ~(7u << 16)) | (1u << 16));      /* SPI45SEL = PLL2_Q */
			return 1;
		}
	REG_WR(RCC_CR, REG_RD(RCC_CR) & ~(1u << 26));                                         /* never locked: back off */
	return 0;
}

static int spi_ready;
static void spi_hw_init(void)
{
	if (spi_ready) return;
#if H7UI_FAST
	pll2_active = pll2_start();
#endif
	REG_WR(RCC_APB2ENR, REG_RD(RCC_APB2ENR) | (1u << 20));        /* SPI5 clock */
	(void)REG_RD(RCC_APB2ENR);
	REG_WR(GPIOH + MODER, (REG_RD(GPIOH + MODER) & ~((3u << 12) | (3u << 14))) | (2u << 12) | (2u << 14));   /* PH6, PH7 alternate */
	REG_WR(GPIOH + OSPEEDR, REG_RD(GPIOH + OSPEEDR) | (3u << 12) | (3u << 14));
	REG_WR(GPIOH + AFRL, (REG_RD(GPIOH + AFRL) & ~((0xFu << 24) | (0xFu << 28))) | (5u << 24) | (5u << 28));   /* AF5 */
	/* SSI first: with software slave select the peripheral reads SSI low as "slave select asserted", and a master that
	 * sees that takes a mode fault, switches itself off and refuses to start (SR bit 9). So SSI is high before the
	 * configuration that turns software select on is written, and any stale fault is cleared. */
	REG_WR(SPI_CR1, SPI_CR1_SSI);
	REG_WR(SPI_IFCR, SPI_IFCR_ALL);
	REG_WR(SPI_CFG1, (SPI_MBR << 28) | 7u);                         /* 8-bit frames, one-frame FIFO threshold */
	/* AFCNTR keeps the pins driven while the peripheral is off, so the clock idles high. Master, mode 3, software
	 * slave select (chip select is PE1), simplex transmitter, data on the pad the peripheral calls MISO (IOSWP). */
	REG_WR(SPI_CFG2, (1u << 31) | (1u << 26) | (1u << 25) | (1u << 24) | (1u << 22) | (1u << 17) | (1u << 15));
	REG_WR(SPI_CR1, SPI_CR1_SSI);
	spi_ready = 1;
}
#endif

static void spi_open(uint32_t frames)                            /* frames: 1..65535 */
{
	REG_WR(SPI_CR2, frames);
	REG_WR(SPI_CR1, SPI_CR1_SSI | SPI_CR1_SPE);
	REG_WR(SPI_CR1, SPI_CR1_SSI | SPI_CR1_SPE | SPI_CR1_CSTART);
}

static int spi_put(uint8_t b)                                    /* 1 if the byte went into the FIFO */
{
	if (!spi_wait(SPI_SR_TXP)) return 0;
	REG_WR8(SPI_TXDR, b);
	return 1;
}

static int spi_close(void)                                       /* 1 if the transfer finished shifting out */
{
	if (!spi_wait(SPI_SR_EOT)) return 0;
	REG_WR(SPI_IFCR, SPI_IFCR_CLEAR);
	REG_WR(SPI_CR1, SPI_CR1_SSI);
	return 1;
}

static uint32_t pix_left;              /* pixels still owed to the open window (see h7lcd_begin) */

/* The shadow copy of the picture (screen capture): the panel cannot be read back on this board, so every pixel sent is also
 * stored here, big-endian RGB565 as it went out. win_* is the open window and sh_cx/sh_cy the next pixel in it. */
static uint8_t *shadow;
static unsigned win_x, win_y, win_w, sh_cx, sh_cy;
static uint32_t draw_count;
void h7ui_set_shadow(uint8_t *fb) { shadow = fb; }
const uint8_t *h7ui_shadow(void) { return shadow; }
uint32_t h7ui_draw_count(void) { return draw_count; }
static void shadow_put(uint8_t hi, uint8_t lo)
{
	if (!shadow) return;
	uint8_t *d = shadow + (((win_y + sh_cy) * H7LCD_W) + win_x + sh_cx) * 2u;
	d[0] = hi; d[1] = lo;
	if (++sh_cx == win_w) { sh_cx = 0; sh_cy++; }
}
#if H7UI_HW_SPI
/* A whole solid window into the shadow, the one open now: a 16-bit store per pixel (the base is even, so every pixel is), not
 * the call and the cursor arithmetic of shadow_put. */
static void shadow_rect(unsigned w, unsigned h, uint8_t hi, uint8_t lo)
{
	if (!shadow) return;
	uint16_t v = (uint16_t)(hi | (lo << 8));                    /* little-endian store puts hi first in memory */
	for (unsigned y = 0; y < h; y++) {
		volatile uint16_t *d = (volatile uint16_t *)(void *)(shadow + (((win_y + y) * H7LCD_W) + win_x) * 2u);
		for (unsigned x = 0; x < w; x++) d[x] = v;
	}
	sh_cx = 0; sh_cy = h;
}

/* ---- DMA2 stream 3 feeding the SPI5 FIFO. One chunk is one SPI transaction of at most SPI_CHUNK_MAX bytes. ---- */
static uint8_t *dma_scratch;           /* where a fill's one pixel is kept: memory DMA2 can read, and no cache between */
static unsigned dma_err;

static int dma_wait(uint32_t addr, uint32_t mask, uint32_t want, uint32_t spins)
{
	while (spins--) if ((REG_RD(addr) & mask) == want) return 1;
	return 0;
}

/* Send `bytes` (even, 1..SPI_CHUNK_MAX) from src; circular makes the stream repeat the first `circ` bytes (circ >= 2). */
static int dma_chunk(const uint8_t *src, uint32_t bytes, uint32_t circ)
{
	REG_WR(RCC_AHB1ENR, REG_RD(RCC_AHB1ENR) | (1u << 1));                      /* DMA2 (and its DMAMUX) */
	(void)REG_RD(RCC_AHB1ENR);
	REG_WR(DMA2_S3, 0);                                                         /* stream off */
	if (!dma_wait(DMA2_S3, 1u, 0, 1000u)) return 0;
	REG_WR(DMA2_LIFCR, 0x3Du << 22);                                            /* every stream 3 flag */
	REG_WR(DMAMUX1_C11, DMAREQ_SPI5_TX);
	REG_WR(DMA2_S3 + 0x08u, SPI_TXDR);
	REG_WR(DMA2_S3 + 0x0Cu, (uint32_t)(uintptr_t)src);
	REG_WR(DMA2_S3 + 0x04u, circ ? circ : bytes);
	REG_WR(DMA2_S3 + 0x14u, 0);                                                 /* direct mode */
	REG_WR(DMA2_S3, (3u << 16) | (1u << 10) | (1u << 6) | (circ ? (1u << 8) : 0u));   /* high priority, memory increment, memory to peripheral */
	REG_WR(SPI_CFG1, REG_RD(SPI_CFG1) | (1u << 15));                            /* TXDMAEN */
	REG_WR(SPI_CR2, bytes);
	REG_WR(DMA2_S3, REG_RD(DMA2_S3) | 1u);                                      /* stream on: it waits for the SPI's request */
	REG_WR(SPI_CR1, SPI_CR1_SSI | SPI_CR1_SPE);
	REG_WR(SPI_CR1, SPI_CR1_SSI | SPI_CR1_SPE | SPI_CR1_CSTART);
	int ok = dma_wait(SPI_SR, SPI_SR_EOT, SPI_SR_EOT, 40u * bytes + 100000u);   /* well over the wire time at the slowest clock */
	REG_WR(DMA2_S3, 0);
	dma_wait(DMA2_S3, 1u, 0, 1000u);
	REG_WR(SPI_CFG1, REG_RD(SPI_CFG1) & ~(1u << 15));
	REG_WR(SPI_IFCR, SPI_IFCR_ALL);
	REG_WR(SPI_CR1, SPI_CR1_SSI);
	return ok;
}

void h7ui_set_dma_scratch(uint8_t *two_bytes) { dma_scratch = two_bytes; }
unsigned h7ui_dma_errors(void) { return dma_err; }
int h7ui_spi_fast(void) { return pll2_active; }

int h7lcd_blit(const uint8_t *src, uint32_t bytes)
{
	if (!hw_active || !spi_ready || pix_left == 0 || (bytes & 1u) || bytes == 0 || bytes / 2u > pix_left) return 0;
	for (uint32_t done = 0; done < bytes; ) {
		uint32_t n = bytes - done; if (n > SPI_CHUNK_MAX) n = SPI_CHUNK_MAX;
		if (!dma_chunk(src + done, n, 0)) { dma_err++; pix_left = 0; return 0; }
		done += n; pix_left -= n / 2u;
	}
	for (uint32_t i = 0; i < bytes; i += 2) shadow_put(src[i], src[i + 1]);
	return 1;
}

int h7lcd_fill_dma(unsigned x, unsigned y, unsigned w, unsigned h, uint16_t c)
{
	if (!dma_scratch || !hw_active || !spi_ready) return 0;
	if (x >= H7LCD_W || y >= H7LCD_H || w == 0 || h == 0) return 0;
	if (w > H7LCD_W - x) w = H7LCD_W - x;
	if (h > H7LCD_H - y) h = H7LCD_H - y;
	if (!h7lcd_begin(x, y, w, h)) return 0;
	dma_scratch[0] = (uint8_t)(c >> 8); dma_scratch[1] = (uint8_t)c;
	for (uint32_t left = w * h * 2u; left; ) {
		uint32_t n = left > SPI_CHUNK_MAX ? SPI_CHUNK_MAX : left;
		if (!dma_chunk(dma_scratch, n, 2u)) { dma_err++; h7lcd_end(); return 0; }
		left -= n;
	}
	pix_left = 0;
	shadow_rect(w, h, dma_scratch[0], dma_scratch[1]);
	h7lcd_end();
	return 1;
}

#else
int h7lcd_blit(const uint8_t *src, uint32_t bytes) { (void)src; (void)bytes; return 0; }
int h7lcd_fill_dma(unsigned x, unsigned y, unsigned w, unsigned h, uint16_t c) { (void)x; (void)y; (void)w; (void)h; (void)c; return 0; }
void h7ui_set_dma_scratch(uint8_t *two_bytes) { (void)two_bytes; }
unsigned h7ui_dma_errors(void) { return 0; }
int h7ui_spi_fast(void) { return 0; }
#endif

static void spi_byte(uint8_t b)
{
	if (hw_active) {
		spi_open(1);
		if (!spi_put(b)) { bitbang_byte(b); return; }            /* nothing went out: send it by hand */
		spi_close();                                            /* if this fails the byte is out already */
		return;
	}
	bitbang_byte(b);
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
	gpio_out(GPIOE, 1); gpio_out(GPIOG, 15);
#if H7UI_HW_SPI
	spi_hw_init();
#else
	gpio_out(GPIOH, 6); gpio_out(GPIOH, 7);
#endif
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

/* The pixel stream is one or more peripheral transactions, each closed and reopened by the pixel that needs it, with
 * chip select held low across them (on the hand-clocked path there is nothing to open). pix_left counts the pixels
 * still owed to the window, frames_left the frames the open transaction can still take. */
static uint32_t frames_left;

int h7lcd_begin(unsigned x, unsigned y, unsigned w, unsigned h)
{
	if (w == 0 || h == 0 || x >= H7LCD_W || y >= H7LCD_H || w > H7LCD_W - x || h > H7LCD_H - y) return 0;
	uint8_t xa[] = { (uint8_t)(x >> 8), (uint8_t)x, (uint8_t)((x + w - 1) >> 8), (uint8_t)(x + w - 1) };
	uint8_t ya[] = { (uint8_t)(y >> 8), (uint8_t)y, (uint8_t)((y + h - 1) >> 8), (uint8_t)(y + h - 1) };
	cmd_n(0x2a, xa, 4);
	cmd_n(0x2b, ya, 4);
	cmd(0x2c);
	DC_H(); CS_L();
	pix_left = w * h;
	frames_left = 0;
	win_x = x; win_y = y; win_w = w; sh_cx = sh_cy = 0;
	return 1;
}

void h7lcd_pixel(uint16_t c)
{
	if (pix_left == 0) return;                          /* more pixels than the window holds are dropped */
	pix_left--;
	uint8_t hi = (uint8_t)(c >> 8), lo = (uint8_t)c;
	shadow_put(hi, lo);
	if (!hw_active) { frames_left = 0; bitbang_byte(hi); bitbang_byte(lo); return; }
	if (frames_left == 0) {
		uint32_t f = (pix_left + 1u) * 2u;
		if (f > SPI_CHUNK_MAX) f = SPI_CHUNK_MAX;
		spi_open(f);
		frames_left = f;
	}
	if (!spi_put(hi)) { frames_left = 0; bitbang_byte(hi); bitbang_byte(lo); return; }   /* fell back: send it by hand */
	if (!spi_put(lo)) { frames_left = 0; bitbang_byte(lo); return; }
	frames_left -= 2;
	if (frames_left == 0) spi_close();
}

void h7lcd_end(void)
{
	if (frames_left && hw_active) spi_close();           /* fewer pixels than the window: end the transaction */
	frames_left = 0;
	pix_left = 0;
	CS_H();
	draw_count++;
}

void h7lcd_fill_rect(unsigned x, unsigned y, unsigned w, unsigned h, uint16_t c)
{
	if (x >= H7LCD_W || y >= H7LCD_H) return;
	if (w > H7LCD_W - x) w = H7LCD_W - x;                    /* clipped to the glass */
	if (h > H7LCD_H - y) h = H7LCD_H - y;
	if (!h7lcd_begin(x, y, w, h)) return;
	for (unsigned n = w * h; n; n--) h7lcd_pixel(c);
	h7lcd_end();
}
