/* Host harness for targets/h7tool/fw/ui/h7_ui.c: fake GPIO registers, a decoder for the hand-clocked SPI the panel
 * sees, and a model of the I2C expander, printing what each saw. tests/test_h7_ui.py compares the output with the
 * values docs/22 records. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "h7_ui.h"

#define GPIOB 0x58020400u
#define GPIOE 0x58021000u
#define GPIOG 0x58021800u
#define GPIOH 0x58021C00u
#define RCC_AHB4ENR 0x58024540u

static struct { uint32_t a, v; } regs[256];
static int nregs;
static uint32_t odr[4];                       /* B, E, G, H */
static int chip_present = 1;
static unsigned long delay_total_us;
static int quiet;

static int port_index(uint32_t base) { return base == GPIOB ? 0 : base == GPIOE ? 1 : base == GPIOG ? 2 : base == GPIOH ? 3 : -1; }
static uint32_t *slot(uint32_t a)
{
	for (int i = 0; i < nregs; i++) if (regs[i].a == a) return &regs[i].v;
	regs[nregs].a = a; regs[nregs].v = 0; return &regs[nregs++].v;
}

/* ---- SPI sniffer ---- */
static int spi_bits; static uint8_t spi_shift;
static void spi_on_write(void)
{
	/* called after every GPIOH/GPIOE write: a rising edge on PH6 while PE1 is low clocks one bit */
	static int prev_sck = 1, prev_cs = 1;
	int sck = (odr[3] >> 6) & 1, cs = (odr[1] >> 1) & 1;
	if (cs && !prev_cs) spi_bits = 0;
	if (!cs && sck && !prev_sck) {
		spi_shift = (uint8_t)((spi_shift << 1) | ((odr[3] >> 7) & 1));
		if (++spi_bits == 8) {
			if (!quiet) printf("S %c %02x\n", ((odr[2] >> 15) & 1) ? 'D' : 'C', spi_shift);
			spi_bits = 0;
		}
	}
	prev_sck = sck; prev_cs = cs;
}

/* ---- I2C expander model: SCL PB6, SDA PG0, address 0xB6 ---- */
static uint8_t exp_regs[256];
static int i2c_slave_low, i2c_started, i2c_clk, i2c_matched, i2c_read, i2c_nbytes, i2c_rd_phase;
static uint8_t i2c_shift, i2c_reg, i2c_rdbyte;
static uint8_t txn[16]; static int ntx;
static char rdbuf[32];

static int sda_line(void) { return (int)(odr[2] & 1) && !i2c_slave_low; }
static int scl_line(void) { return (int)((odr[0] >> 6) & 1); }

static void i2c_flush(void)
{
	if (!quiet && ntx) {
		printf("I");
		for (int i = 0; i < ntx; i++) printf(" %02x", txn[i]);
		printf("%s\n", rdbuf);
	}
	ntx = 0; rdbuf[0] = 0;
}

static void i2c_byte_done(uint8_t b)
{
	if (ntx < 16) txn[ntx++] = b;
	if (i2c_nbytes == 0) { i2c_matched = chip_present && (b & 0xFE) == 0xB6; i2c_read = b & 1; i2c_slave_low = i2c_matched; }
	else if (!i2c_read) {
		if (i2c_nbytes == 1) i2c_reg = b; else exp_regs[i2c_reg++] = b;
		i2c_slave_low = i2c_matched;
	}
	i2c_nbytes++;
}

static void i2c_update(int old_scl, int old_sda)
{
	int scl = scl_line(), sda = sda_line();
	if (scl && old_scl && old_sda && !sda) {                    /* START or repeated START */
		if (i2c_started && i2c_nbytes) { /* repeated start keeps the transaction */ }
		else { ntx = 0; rdbuf[0] = 0; }
		i2c_started = 1; i2c_clk = 0; i2c_nbytes = 0; i2c_slave_low = 0; i2c_rd_phase = 0;
		return;
	}
	if (scl && old_scl && !old_sda && sda) {                    /* STOP */
		i2c_flush(); i2c_started = 0; i2c_slave_low = 0; return;
	}
	if (!i2c_started) return;
	if (scl && !old_scl) {                                      /* rising edge */
		i2c_clk++;
		if (i2c_clk <= 8 && !i2c_rd_phase) i2c_shift = (uint8_t)((i2c_shift << 1) | sda);
	}
	if (!scl && old_scl) {                                      /* falling edge */
		if (i2c_rd_phase) {
			if (i2c_clk < 8) i2c_slave_low = !((i2c_rdbyte >> (7 - i2c_clk)) & 1);
			else i2c_slave_low = 0;                             /* the master's ack/nak clock follows */
			if (i2c_clk == 9) i2c_clk = 0;
		} else if (i2c_clk == 8) {
			i2c_byte_done(i2c_shift);
		} else if (i2c_clk == 9) {
			i2c_slave_low = 0; i2c_clk = 0;
			if (i2c_read && i2c_matched) {                      /* data follows the address ack, MSB first */
				i2c_rd_phase = 1;
				i2c_rdbyte = exp_regs[i2c_reg];
				i2c_slave_low = !((i2c_rdbyte >> 7) & 1);
				snprintf(rdbuf, sizeof rdbuf, " -> %02x", i2c_rdbyte);
			}
		}
	}
}

/* ---- the register seam h7_ui.c is built against ---- */
static int forbidden;
uint32_t h7ui_host_rd(uint32_t a)
{
	if ((a & ~0x3FFu) == GPIOG && (a & 0x3FFu) == 0x10) return (uint32_t)sda_line();
	return *slot(a);
}

void h7ui_host_wr(uint32_t a, uint32_t v)
{
	uint32_t base = a & ~0x3FFu, off = a & 0x3FFu;
	int pi = port_index(base);
	if (a != RCC_AHB4ENR && pi < 0) { printf("BAD address %08x\n", a); forbidden++; return; }
	if (pi == 3 && off == 0x18 && (v & ((1u << 9) | (1u << 25)))) { printf("BAD PH9 written\n"); forbidden++; }
	if (pi == 2 && off == 0x18 && (v & ((1u << 1) | (1u << 17)))) { printf("BAD PG1 written\n"); forbidden++; }
	if (pi == 3 && off == 0x00 && (((v ^ *slot(a)) >> 18) & 3)) { printf("BAD PH9 mode changed\n"); forbidden++; }
	if (pi == 2 && off == 0x00 && (((v ^ *slot(a)) >> 2) & 3)) { printf("BAD PG1 mode changed\n"); forbidden++; }
	if (pi >= 0 && off == 0x18) {
		int os = scl_line(), od = sda_line();
		uint32_t set = v & 0xFFFFu, rst = v >> 16;
		odr[pi] = (odr[pi] & ~rst) | set;
		if (pi == 3 || pi == 1) spi_on_write();
		if (pi == 0 || pi == 2) i2c_update(os, od);
		return;
	}
	*slot(a) = v;
}

static void delay(uint32_t us) { delay_total_us += us; }

int main(int argc, char **argv)
{
	const char *sc = argc > 1 ? argv[1] : "";
	exp_regs[0x10] = 0x23;
	h7ui_set_delay(delay);
	odr[0] = odr[2] = ~0u;                       /* lines idle high until the driver says otherwise */
	if (!strcmp(sc, "lcd_init")) { h7lcd_init(); }
	else if (!strcmp(sc, "fill")) {
		quiet = 1; h7lcd_init(); quiet = 0;
		h7lcd_fill_rect(2, 3, 4, 2, 0xF81F);
	}
	else if (!strcmp(sc, "bounds")) {
		printf("R %d %d %d %d %d\n", h7lcd_begin(0, 0, 0, 5), h7lcd_begin(240, 0, 1, 1), h7lcd_begin(0, 319, 1, 2),
		       h7lcd_begin(1, 0, 240, 1), h7lcd_begin(239, 319, 1, 1));
		h7lcd_end();
	}
	else if (!strcmp(sc, "fill_clip")) { quiet = 1; h7lcd_init(); quiet = 0; h7lcd_fill_rect(230, 310, 20, 20, 0x1234); }
	else if (!strcmp(sc, "expander")) {
		printf("R %d\n", h7ui_expander_init());
		h7ui_backlight(0x40);
		h7ui_led(H7UI_LED_RUN, 0x20);
		h7ui_led(H7UI_LED_CHG_GREEN, 0x10);
		h7ui_led(H7UI_LED_CHG_RED, 0x00);
		h7ui_led((enum h7ui_led)3, 0xFF);        /* out of range: must write nothing */
	}
	else if (!strcmp(sc, "nochip")) { chip_present = 0; printf("R %d\n", h7ui_expander_init()); }
	else { printf("unknown scenario\n"); return 2; }
	printf("forbidden %d\n", forbidden);
	printf("delay_us %lu\n", delay_total_us);
	return 0;
}
