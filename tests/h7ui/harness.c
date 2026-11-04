/* Host harness for targets/h7tool/fw/ui/h7_ui.c: fake GPIO registers, a decoder for the hand-clocked SPI the panel
 * sees, and a model of the I2C expander, printing what each saw. tests/test_h7_ui.py compares the output with the
 * values docs/22 records. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "h7_ui.h"
#ifndef H7UI_HW_SPI
#define H7UI_HW_SPI 1
#endif

#define GPIOB 0x58020400u
#define GPIOE 0x58021000u
#define GPIOG 0x58021800u
#define GPIOH 0x58021C00u
#define RCC_AHB4ENR 0x58024540u
#define RCC_APB2ENR 0x580244F0u
#define SPI5 0x40015000u
#define RCC_CR        0x58024400u
#define RCC_PLLCKSELR 0x58024428u
#define RCC_PLLCFGR   0x5802442Cu
#define RCC_PLL1DIVR  0x58024430u
#define RCC_PLL1FRACR 0x58024434u
#define RCC_PLL2DIVR  0x58024438u
#define RCC_D2CCIP1R  0x58024450u

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

/* ---- SPI5 model: checks the configuration the peripheral needs and the order the driver uses it in ---- */
static uint32_t sp_cr1, sp_cr2, sp_cfg1, sp_cfg2;
static int sp_active; static uint32_t sp_done; static int sp_dc, sp_cs_low, sp_eot_cleared, sp_eot_polls, sp_eot_seen;
static int pll_dead, pll_reads_left, pll_cr_writes;
static int sp_bad, sp_stuck, sp_modf; static unsigned long sp_sr_reads;
#define SPI_BAD(...) do { printf("BAD "); printf(__VA_ARGS__); printf("\n"); sp_bad++; } while (0)

static void sp_check_config(void)
{
	uint32_t c2 = sp_cfg2;
	if ((c2 & (1u << 22)) == 0) SPI_BAD("not master");
	if ((c2 & (1u << 25)) == 0 || (c2 & (1u << 24)) == 0) SPI_BAD("not CPOL=1 CPHA=1");
	if ((c2 & (1u << 26)) == 0) SPI_BAD("hardware slave select in use");
	if (((c2 >> 17) & 3u) != 1u) SPI_BAD("not simplex transmitter");
	if ((c2 & (1u << 15)) == 0) SPI_BAD("IOSWP not set: data would leave on the wrong pad");
	if ((c2 & (1u << 31)) == 0) SPI_BAD("AFCNTR not set: the clock would float while disabled");
	if ((sp_cfg1 & 31u) != 7u) SPI_BAD("not 8-bit frames");
	if (((sp_cfg1 >> 28) & 7u) != 0u) SPI_BAD("clock is not kernel/2, the rate measured clean on the unit");
	uint32_t m = *slot(GPIOH + 0x00u), af = *slot(GPIOH + 0x20u);
	if (((m >> 12) & 3u) != 2u || ((m >> 14) & 3u) != 2u) SPI_BAD("PH6/PH7 not alternate function");
	if (((af >> 24) & 0xFu) != 5u || ((af >> 28) & 0xFu) != 5u) SPI_BAD("PH6/PH7 not AF5");
	if (!(*slot(RCC_APB2ENR) & (1u << 20))) SPI_BAD("SPI5 clock not enabled");
}

static void sp_modf_check(void)
{
	/* master with software slave select and SSI low reads as "slave select asserted": a mode fault, which
	 * clears SPE and keeps the peripheral from starting until the flag is cleared (SR bit 9, IFCR bit 9) */
	if ((sp_cfg2 & (1u << 22)) && (sp_cfg2 & (1u << 26)) && !(sp_cr1 & (1u << 12))) { sp_modf = 1; sp_cr1 &= ~1u; sp_active = 0; }
}

static void sp_write_cr1(uint32_t v)
{
	int spe_old = sp_cr1 & 1u, spe = v & 1u, start = (v >> 9) & 1u;
	if (sp_modf && spe) v &= ~1u, spe = 0, start = 0;           /* refused while the fault is pending */
	if (spe && !spe_old) { if (sp_cr2 == 0 || sp_cr2 > 65535u) SPI_BAD("TSIZE %u", sp_cr2); sp_check_config(); }
	if (spe && start && !sp_active) {
		if (!sp_cs_low) SPI_BAD("transfer started with chip select high");
		sp_active = 1; sp_done = 0; sp_dc = (int)((odr[2] >> 15) & 1); sp_eot_cleared = 0; sp_eot_polls = 0; sp_eot_seen = 0;
	}
	if (!spe && spe_old && sp_stuck) { sp_active = 0; }
	else if (!spe && spe_old) {
		if (sp_active && sp_done != sp_cr2) SPI_BAD("SPE cleared after %u of %u frames", sp_done, sp_cr2);
		if (sp_active && !sp_eot_seen) SPI_BAD("SPE cleared before the transfer finished shifting out");
		if (sp_active && !sp_eot_cleared) SPI_BAD("EOT not cleared before SPE off");
		sp_active = 0;
	}
	sp_cr1 = v;
	sp_modf_check();
}

static void sp_txdr8(uint8_t b)
{
	if (!sp_active) { SPI_BAD("TXDR written with no transfer running"); return; }
	if (sp_done >= sp_cr2) { SPI_BAD("TXDR written past TSIZE"); return; }
	sp_done++;
	if (!quiet) printf("S %c %02x\n", sp_dc ? 'D' : 'C', b);
}

/* ---- the register seam h7_ui.c is built against ---- */
static int forbidden;
uint32_t h7ui_host_rd(uint32_t a)
{
	if ((a & ~0x3FFu) == GPIOG && (a & 0x3FFu) == 0x10) return (uint32_t)sda_line();
	if (a == SPI5 + 0x14u) {
		uint32_t sr = 0;
		sp_sr_reads++;
		if (sp_stuck) return 0;                                     /* a peripheral that never reports anything */
		if (sp_modf) return (1u << 9) | (1u << 1);                  /* MODF, and TXP as the real part showed */
		if (sp_active && sp_done < sp_cr2) sr |= 1u << 1;          /* TXP */
		/* the last frame takes a few polls to leave the shift register */
		if (sp_active && sp_done == sp_cr2 && ++sp_eot_polls >= 3) { sr |= 1u << 3; sp_eot_seen = 1; }   /* EOT */
		return sr;
	}
	if (a == RCC_CR) {                                                   /* PLL2RDY follows PLL2ON after a few reads, unless the part is dead */
		uint32_t v = *slot(a);
		if ((v & (1u << 26)) && !pll_dead && pll_reads_left-- <= 0) v |= 1u << 27; else v &= ~(1u << 27);
		*slot(a) = v;
		return v;
	}
	return *slot(a);
}

void h7ui_host_wr(uint32_t a, uint32_t v)
{
	uint32_t base = a & ~0x3FFu, off = a & 0x3FFu;
	int pi = port_index(base);
	if (base == (SPI5 & ~0x3FFu)) {
		if (off == 0x00) { sp_write_cr1(v); return; }
		if ((sp_cr1 & 1u) && (off == 0x04 || off == 0x08 || off == 0x0C)) SPI_BAD("config %02x written with SPE set", off);
		if (off == 0x04) sp_cr2 = v & 0xFFFFu; else if (off == 0x08) sp_cfg1 = v; else if (off == 0x0C) { sp_cfg2 = v; sp_modf_check(); }
		else if (off == 0x18) { if (v & (1u << 3)) sp_eot_cleared = 1; if (v & (1u << 9)) sp_modf = 0; }
		else if (off == 0x20) SPI_BAD("TXDR written as a word");
		return;
	}
	if (a == RCC_CR || a == RCC_PLLCKSELR || a == RCC_PLLCFGR || a == RCC_PLL2DIVR || a == RCC_D2CCIP1R) {
		uint32_t old = *slot(a);
		if (a == RCC_CR) {
			pll_cr_writes++;
			if ((v ^ old) & ~((1u << 26) | (1u << 27))) printf("BAD RCC_CR bits other than PLL2ON changed %08x -> %08x\n", old, v), forbidden++;
			if ((v & (1u << 26)) && !(old & (1u << 26))) pll_reads_left = 3;
		}
		if (a == RCC_PLLCKSELR && ((v ^ old) & ~(0x3Fu << 12))) printf("BAD PLLCKSELR outside DIVM2 changed\n"), forbidden++;
		if ((a == RCC_PLLCKSELR || a == RCC_PLLCFGR || a == RCC_PLL2DIVR) && (*slot(RCC_CR) & (1u << 26))) printf("BAD PLL2 setting written while PLL2 is on\n"), forbidden++;
		if (a == RCC_PLLCFGR && ((v ^ old) & ~((1u << 4) | (1u << 5) | (3u << 6) | (1u << 20)))) printf("BAD PLLCFGR bits of another PLL changed\n"), forbidden++;
		if (a == RCC_D2CCIP1R && (((v >> 16) & 7u) == 1u) && !(*slot(RCC_CR) & (1u << 27))) printf("BAD SPI45SEL moved to PLL2 before it was ready\n"), forbidden++;
		if (a == RCC_D2CCIP1R && ((v ^ old) & ~(7u << 16))) printf("BAD D2CCIP1R bits other than SPI45SEL changed\n"), forbidden++;
		*slot(a) = v; return;
	}
	if (a != RCC_AHB4ENR && a != RCC_APB2ENR && pi < 0) { printf("BAD address %08x\n", a); forbidden++; return; }
	if (pi == 3 && off == 0x18 && (v & ((1u << 9) | (1u << 25)))) { printf("BAD PH9 written\n"); forbidden++; }
	if (pi == 2 && off == 0x18 && (v & ((1u << 1) | (1u << 17)))) { printf("BAD PG1 written\n"); forbidden++; }
	if (pi == 3 && off == 0x00 && (((v ^ *slot(a)) >> 18) & 3)) { printf("BAD PH9 mode changed\n"); forbidden++; }
	if (pi == 2 && off == 0x00 && (((v ^ *slot(a)) >> 2) & 3)) { printf("BAD PG1 mode changed\n"); forbidden++; }
	if (pi >= 0 && off == 0x18) {
		int os = scl_line(), od = sda_line();
		uint32_t set = v & 0xFFFFu, rst = v >> 16;
		if (sp_active && !sp_stuck && ((pi == 1 && ((set | rst) & (1u << 1))) || (pi == 2 && ((set | rst) & (1u << 15)))))
			SPI_BAD("chip select or D/C changed during a transfer");
		odr[pi] = (odr[pi] & ~rst) | set;
		sp_cs_low = !((odr[1] >> 1) & 1u);
		if (pi == 3 || pi == 1) spi_on_write();
		if (pi == 0 || pi == 2) i2c_update(os, od);
		return;
	}
	*slot(a) = v;
}

void h7ui_host_wr8(uint32_t a, uint8_t v)
{
	if (a == SPI5 + 0x20u) { sp_txdr8(v); return; }
	printf("BAD 8-bit write to %08x\n", a); forbidden++;
}

static void delay(uint32_t us) { delay_total_us += us; }

int main(int argc, char **argv)
{
	const char *sc = argc > 1 ? argv[1] : "";
	exp_regs[0x10] = 0x23;
	*slot(RCC_CR) = 0x0303c025u; *slot(RCC_PLLCKSELR) = 0x52u; *slot(RCC_PLLCFGR) = 0x70008u; *slot(RCC_PLL1DIVR) = 0x0103029fu;
	h7ui_set_delay(delay);
	odr[0] = odr[2] = ~0u;                       /* lines idle high until the driver says otherwise */
	if (!strcmp(sc, "lcd_init")) { h7lcd_init(); }
	else if (!strcmp(sc, "fill")) {
		quiet = 1; h7lcd_init(); quiet = 0;
		h7lcd_fill_rect(2, 3, 4, 2, 0xF81F);
	}
	else if (!strcmp(sc, "bounds")) {
		quiet = 1; h7lcd_init(); quiet = 0;
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
	else if (!strcmp(sc, "spi_stuck")) {
		quiet = 1; h7lcd_init(); quiet = 0; sp_stuck = 1; sp_sr_reads = 0; h7lcd_fill_rect(0, 0, 240, 320, 0xFFFF);
		printf("sr_reads %lu\n", sp_sr_reads);
	}
	else if (!strcmp(sc, "pll2") || !strcmp(sc, "pll2_busy") || !strcmp(sc, "pll2_dead") || !strcmp(sc, "pll2_other")) {
		if (!strcmp(sc, "pll2_busy")) { *slot(RCC_CR) |= 1u << 26; *slot(RCC_PLL2DIVR) = 0x11111111u; }
		if (!strcmp(sc, "pll2_dead")) pll_dead = 1;
		if (!strcmp(sc, "pll2_other")) *slot(RCC_PLLCKSELR) = 0x1052u | (1u << 4) * 0;     /* DIVM1 5 but HSI: not the image's clock tree */
		if (!strcmp(sc, "pll2_other")) *slot(RCC_PLLCKSELR) = 0x40u;                       /* HSI, M = 4 */
		quiet = 1; h7lcd_init(); quiet = 0;
		printf("fast %d\n", h7ui_spi_fast());
		printf("cr %08x\npllcksel %08x\npllcfgr %08x\npll2divr %08x\nd2ccip1r %08x\npll1divr %08x\npll1fracr %08x\n", *slot(RCC_CR), *slot(RCC_PLLCKSELR),
		       *slot(RCC_PLLCFGR), *slot(RCC_PLL2DIVR), *slot(RCC_D2CCIP1R), *slot(RCC_PLL1DIVR), *slot(RCC_PLL1FRACR));
	}
	else if (!strcmp(sc, "shadow")) {
		static uint8_t buf[16 + 240 * 320 * 2 + 16];                                      /* guard bytes either side */
		memset(buf, 0xA5, sizeof buf);
		h7ui_set_shadow(buf + 16);
		quiet = 1; h7lcd_init();
		memset(buf + 16, 0, 240 * 320 * 2);
		h7lcd_fill_rect(2, 3, 4, 2, 0xF81F);
		h7lcd_fill_rect(230, 310, 20, 20, 0x1234);                                      /* clipped to the glass */
		h7lcd_begin(10, 20, 3, 2);                                                       /* a window filled with distinct pixels */
		for (unsigned i = 0; i < 6; i++) h7lcd_pixel((uint16_t)(0x0100u * (i + 1) + i + 1));
		h7lcd_end();
		h7lcd_begin(5, 5, 1, 1); h7lcd_pixel(0x1111); h7lcd_pixel(0x2222); h7lcd_end();    /* more pixels than the window */
		quiet = 0;
		unsigned guard_bad = 0;
		for (int i = 0; i < 16; i++) { if (buf[i] != 0xA5) guard_bad++; if (buf[16 + 240 * 320 * 2 + i] != 0xA5) guard_bad++; }
		printf("guard %u\ndraws %u\n", guard_bad, (unsigned)h7ui_draw_count());
		for (unsigned y = 0; y < 320; y++) for (unsigned x = 0; x < 240; x++) {
			const uint8_t *p = buf + 16 + (y * 240 + x) * 2;
			if (p[0] || p[1]) printf("px %u %u %02x%02x\n", x, y, p[0], p[1]);
		}
	}
	else if (!strcmp(sc, "nochip")) { chip_present = 0; printf("R %d\n", h7ui_expander_init()); }
	else { printf("unknown scenario\n"); return 2; }
	printf("spi %s\n", H7UI_HW_SPI ? "hw" : "sw");
	printf("forbidden %d\n", forbidden + sp_bad);
	printf("spi_errors %u\n", h7ui_spi_errors());
	printf("spi_sr_at_error %u\n", h7ui_spi_status_at_error());
	printf("delay_us %lu\n", delay_total_us);
	return 0;
}
