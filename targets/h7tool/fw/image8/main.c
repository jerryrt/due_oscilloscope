/* Image 8 (phase 4b): CH1 and CH2 acquisition, simultaneous.
 * (image7 = the CH1-only path this grew from.) ADC1 (PF11, 16-bit, stock
 * settings from docs/05) triggered by TIM3 update, DMA1 stream 1 in double
 * buffer mode writing straight into version-4 frame payloads in D2 SRAM,
 * streamed over the bulk IN endpoint. Vendor requests: IN 0x03 clock meter,
 * IN 0x04 acquisition counters, OUT 0x13 channel mask (1 CH1, 2 CH2, 3 both; planar frames), OUT 0x10 set the sample period (wValue |
 * wIndex << 16 = TIM3 ticks at 200 MHz, 80..2^31, only while stopped).
 * Default 1 Msps. Front end: DC coupling, gain 0 on both channels. Caches are
 * off. See docs/10-phase4a-adc-stream.md. */
#include <stdint.h>
#include "frame16.h"

#define R32(a)       (*(volatile uint32_t *)(a))
#define RCC_AHB1ENR  R32(0x580244D8u)
#define RCC_AHB4ENR  R32(0x580244E0u)
#define GPIOA        0x58020000u
#define GPIOB        0x58020400u
#define GPIOC        0x58020800u
#define GPIOH        0x58021C00u
#define GPIOI        0x58022000u
#define SYST_CSR     R32(0xE000E010u)
#define SYST_RVR     R32(0xE000E014u)
#define SYST_CVR     R32(0xE000E018u)
#define SCB_AIRCR    R32(0xE000ED0Cu)
#define BOOT_REQ     R32(0x20000000u)
#define BOOT_MAGIC   0x5AA51234u
static uint32_t cpu_hz = 64000000u;     /* HSI until the PLL is up */

#define USB          0x40040000u
#define GOTGCTL      R32(USB + 0x00)
#define GAHBCFG      R32(USB + 0x08)
#define GUSBCFG      R32(USB + 0x0C)
#define GRSTCTL      R32(USB + 0x10)
#define GINTSTS      R32(USB + 0x14)
#define GINTMSK      R32(USB + 0x18)
#define GRXFSIZ      R32(USB + 0x24)
#define DIEPTXF0     R32(USB + 0x28)
#define DIEPTXF(n)   R32(USB + 0x104 + 4 * ((n) - 1))
#define GCCFG        R32(USB + 0x38)
#define DCFG         R32(USB + 0x800)
#define DCTL         R32(USB + 0x804)
#define DSTS         R32(USB + 0x808)
#define DIEPMSK      R32(USB + 0x810)
#define DOEPMSK      R32(USB + 0x814)
#define DAINTMSK     R32(USB + 0x81C)
#define DIEPCTL(n)   R32(USB + 0x900 + 0x20 * (n))
#define DIEPINT(n)   R32(USB + 0x908 + 0x20 * (n))
#define DIEPTSIZ(n)  R32(USB + 0x910 + 0x20 * (n))
#define DOEPCTL(n)   R32(USB + 0xB00 + 0x20 * (n))
#define DOEPINT(n)   R32(USB + 0xB08 + 0x20 * (n))
#define DOEPTSIZ(n)  R32(USB + 0xB10 + 0x20 * (n))
#define PCGCCTL      R32(USB + 0xE00)

#ifndef RUN_MS
#define RUN_MS 60000u
#endif

extern uint32_t _estack, _sidata, _sdata, _edata, _sbss, _ebss;

static uint32_t ms_now;                                 /* SysTick reload = 1 ms */
static void tick(void);

static void delay_ms(uint32_t ms)
{
	uint32_t t = ms_now;
	while (ms_now - t < ms) tick();
}

static void return_to_boot_loader(void)
{
	BOOT_REQ = BOOT_MAGIC;
	__asm volatile ("dsb sy" ::: "memory");
	SCB_AIRCR = 0x05FA0004u;
	for (;;) { }
}

/* AF10, push-pull, no pull, very high speed. */
static void pin_af10(uint32_t port, unsigned pin)
{
	uint32_t m = 3u << (pin * 2);
	R32(port + 0x00) = (R32(port + 0x00) & ~m) | (2u << (pin * 2));       /* MODER */
	R32(port + 0x04) &= ~(1u << pin);                                     /* OTYPER */
	R32(port + 0x08) |= m;                                                /* OSPEEDR */
	R32(port + 0x0C) &= ~m;                                               /* PUPDR */
	uint32_t afr = port + (pin < 8 ? 0x20 : 0x24);
	unsigned sh = (pin & 7) * 4;
	R32(afr) = (R32(afr) & ~(0xFu << sh)) | (10u << sh);
}

static int wait_clear(volatile uint32_t *r, uint32_t bits)
{
	for (uint32_t n = 0x30D41; n; n--)
		if (!(*r & bits)) return 1;
	return 0;
}

static void flush_fifos(void)
{
	GRSTCTL = 0x420; wait_clear(&GRSTCTL, 0x20);        /* TX, all FIFOs */
	GRSTCTL = 0x10;  wait_clear(&GRSTCTL, 0x10);        /* RX */
}

static void ep_reset_all(void)
{
	for (unsigned i = 0; i < 8; i++) {
		DIEPCTL(i) = 0; DIEPTSIZ(i) = 0; DIEPINT(i) = 0xFB7F;
		DOEPCTL(i) = 0; DOEPTSIZ(i) = 0; DOEPINT(i) = 0xFB7F;
	}
}


/* ---- descriptors ------------------------------------------------------ */

#define VID 0x1209u   /* bench test pair, not an allocation *(check)* */
#define PID 0x0001u

static const uint8_t dev_desc[18] = {
	18, 1, 0x00, 0x02, 0xEF, 0x02, 0x01, 64,
	VID & 0xFF, VID >> 8, PID & 0xFF, PID >> 8, 0x01, 0x00, 1, 2, 3, 1,
};
static const uint8_t qual_desc[10] = { 10, 6, 0x00, 0x02, 0xEF, 0x02, 0x01, 64, 1, 0 };

/* One CDC-ACM function: IAD, comm interface (one interrupt IN), data
 * interface (bulk OUT, bulk IN). Interface/endpoint numbers per function. */
#define CDC_FUNC(ifc, intep, outep, inep) \
	8, 0x0B, (ifc), 2, 0x02, 0x02, 0x00, 0, \
	9, 4, (ifc), 0, 1, 0x02, 0x02, 0x00, 0, \
	5, 0x24, 0x00, 0x10, 0x01, \
	5, 0x24, 0x01, 0x00, (ifc) + 1, \
	4, 0x24, 0x02, 0x02, \
	5, 0x24, 0x06, (ifc), (ifc) + 1, \
	7, 5, 0x80 | (intep), 3, 16, 0, 0x10, \
	9, 4, (ifc) + 1, 0, 2, 0x0A, 0x00, 0x00, 0, \
	7, 5, (outep), 2, 0x00, 0x02, 0, \
	7, 5, 0x80 | (inep), 2, 0x00, 0x02, 0

#define CFG_LEN 141
static const uint8_t cfg_desc[CFG_LEN] = {
	9, 2, CFG_LEN, 0, 4, 1, 0, 0x80, 50,
	CDC_FUNC(0, 1, 2, 2),
	CDC_FUNC(2, 3, 4, 4),
};

static const char *const str_text[3] = {
	"due_oscilloscope", "H7 scope bring-up", 0 /* serial: chip UID */
};

static uint8_t strbuf[2 + 2 * 32];

static unsigned build_string(unsigned idx)
{
	unsigned n = 0;
	if (idx == 0) {
		strbuf[2] = 0x09; strbuf[3] = 0x04; n = 1;
	} else if (idx <= 2) {
		for (const char *p = str_text[idx - 1]; *p && n < 31; p++, n++) {
			strbuf[2 + 2 * n] = (uint8_t)*p; strbuf[3 + 2 * n] = 0;
		}
	} else {                                            /* UID, 12 bytes as hex */
		for (unsigned i = 0; i < 12; i++) {
			uint8_t b = *(volatile uint8_t *)(0x1FF1E800u + i);
			static const char hx[] = "0123456789ABCDEF";
			strbuf[2 + 4 * i] = hx[b >> 4]; strbuf[3 + 4 * i] = 0;
			strbuf[4 + 4 * i] = hx[b & 15]; strbuf[5 + 4 * i] = 0;
		}
		n = 24;
	}
	strbuf[0] = 2 + 2 * n; strbuf[1] = 3;
	return strbuf[0];
}

/* ---- DMA buffers (D2 SRAM; clocks enabled in Reset_Handler) ------------- */

#define DIEPDMA(n)   R32(USB + 0x914 + 0x20 * (n))
#define DOEPDMA(n)   R32(USB + 0xB14 + 0x20 * (n))
#define RCC_AHB2ENR  R32(0x580244DCu)

#define EP0BUF       ((uint8_t *)0x30000000u)          /* 256 B: descriptors out */
#define SETUPBUF     ((volatile uint8_t *)0x30000100u) /* 24 B: setup packets in */
#define RXBUF        ((volatile uint8_t *)0x30000120u) /* 64 B: control OUT data */

#define EPENA 0x80000000u
#define CNAK  0x04000000u
#define SNAK  0x08000000u
#define USBAEP 0x8000u

static uint8_t  config_value;
static uint8_t  dtr;
static uint8_t  line_coding[7] = { 0x00, 0xC2, 0x01, 0x00, 0, 0, 8 };   /* 115200 8N1 */
static uint32_t txbuf[16];
static uint32_t m_res[8];                        /* last clock-meter window */


static void tick(void)
{
	if (SYST_CSR & 0x10000u) ms_now++;                       /* COUNTFLAG */
}

static void ep0_arm_setup(void)
{
	DOEPTSIZ(0) = (3u << 29) | (1u << 19) | 24u;
	DOEPDMA(0) = (uint32_t)SETUPBUF;
	DOEPCTL(0) |= EPENA | USBAEP | CNAK;
}

static int ep0_wait_in_done(void)
{
	uint32_t t = ms_now;
	while (ms_now - t < 100u) {
		tick();
		if (DIEPINT(0) & 1u) { DIEPINT(0) = 1u; return 1; }
	}
	return 0;
}

static void ep0_send_packet(const uint8_t *p, unsigned n)
{
	DIEPDMA(0) = (uint32_t)p;
	DIEPTSIZ(0) = (1u << 19) | n;
	DIEPCTL(0) |= EPENA | CNAK;
	ep0_wait_in_done();
}

/* Data stage IN: copy to DMA-reachable RAM, send <= want bytes. */
static void ep0_send(const uint8_t *p, unsigned len, unsigned want)
{
	unsigned total = len < want ? len : want;
	if (total > 256) total = 256;
	for (unsigned i = 0; i < total; i++) EP0BUF[i] = p[i];
	unsigned off = 0;
	ep0_arm_setup();                                         /* for the status OUT */
	do {
		unsigned n = total - off > 64 ? 64 : total - off;
		ep0_send_packet(EP0BUF + off, n);
		off += n;
		if (n < 64) return;
	} while (off < total);
	if (total < want) ep0_send_packet(EP0BUF, 0);            /* exact multiple of 64 */
}

static void ep0_status_in(void)
{
	ep0_arm_setup();                                         /* no OUT stage: be ready for the next SETUP */
	ep0_send_packet(EP0BUF, 0);
}

static void ep0_stall(void)
{
	DIEPCTL(0) |= 1u << 21; DOEPCTL(0) |= 1u << 21;
	ep0_arm_setup();
}

/* Control-OUT data stage (<= 64 bytes). Returns bytes received. */
static unsigned ep0_recv(uint8_t *out)
{
	uint32_t t = ms_now;
	DOEPTSIZ(0) = (3u << 29) | (1u << 19) | 64u;
	DOEPDMA(0) = (uint32_t)RXBUF;
	DOEPCTL(0) |= EPENA | USBAEP | CNAK;
	while (ms_now - t < 100u) {
		tick();
		if (DOEPINT(0) & 1u) {
			unsigned got = 64u - (DOEPTSIZ(0) & 0x7Fu);
			DOEPINT(0) = 1u;
			for (unsigned i = 0; i < got && i < 64; i++) out[i] = RXBUF[i];
			return got;
		}
	}
	return 0;
}

/* ---- the acquisition path ------------------------------------------------
 * Scope CH1 = ADC1 channel 2 (PF11) on DMA1 stream 1; CH2 = ADC3 channel 1
 * (PC3_C) on DMA2 stream 1. Both are triggered by the same TIM3 update, so a
 * sample pair is simultaneous. Each DMA runs in double-buffer mode straight
 * into its own plane of a frame slot in D2 SRAM (planar payload, see
 * lib/wire/frame16.h), so the CPU never reads or writes a sample: it moves the
 * idle buffer's address to the next slot and writes the 32-byte header when a
 * frame goes to USB. A full ring points the DMA at a scrap slot; the frame is
 * counted lost and the next sent frame carries the overrun flag. */

#define TIM(b, o)    R32((b) + (o))
#define TIM2B 0x40000000u
#define TIM3B 0x40000400u
#define TIM5B 0x40000C00u
#define DBGMCU_IDC   R32(0x5C001000u)
#define GPIOF        0x58021400u
#define GPIOG        0x58021800u
#define RCC_AHB1ENR_ADC  ((1u << 5) | 1u | (1u << 1))       /* ADC12, DMA1, DMA2 */

static const uint32_t ADCB[2] = { 0x40022000u, 0x58026000u };   /* ADC1, ADC3 */
static const uint32_t CCRA[2] = { 0x40022308u, 0x58026308u };
static const uint32_t DMAB[2] = { 0x40020000u, 0x40020400u };   /* DMA1, DMA2; stream 1 */
static const uint32_t MUXC[2] = { 0x40020804u, 0x40020824u };   /* DMAMUX1 channel 1, 9 */
static const uint8_t  MUXREQ[2] = { 9, 115 };
static const uint8_t  ACH[2]  = { 2, 1 };                       /* ADC input channel */
#define ADCR(c, o)   R32(ADCB[c] + (o))
#define DMAR(c, o)   R32(DMAB[c] + 0x28 + (o))   /* CR 0, NDTR 4, PAR 8, M0AR 0xC, M1AR 0x10, FCR 0x14 */
#define DMA_LISR(c)  R32(DMAB[c])
#define DMA_LIFCR(c) R32(DMAB[c] + 8)

#define RING_FRAMES  32u
#define SCRAP_SLOT   RING_FRAMES                      /* one extra slot, never sent */
#define RING_BASE    0x30001000u
#define SLOT(i)      (RING_BASE + (i) * FRAME_BYTES)
#define PAYLOAD(i)   (SLOT(i) + FRAME_HDR_BYTES)

/* Measured, not specified (docs/10): at 70 ticks (2.86 Msps) the ADC with these
 * settings takes every second trigger, at 80 (2.5 Msps) every one. */
#define MIN_PERIOD   80u
static uint32_t period = 200;                         /* TIM3 ticks (200 MHz) per sample: 1 Msps */
static uint32_t chmask = 1, nch = 1, spf = FRAME_SAMPLES;   /* channels, samples per channel per frame */
static uint8_t  chidx[2];                             /* hardware channel of the k-th active channel */

static uint8_t  running, ep_busy, lost_since_push;
static uint32_t fin;                                  /* absolute number of the next frame to finish */
static uint32_t lost, xfers, alloc_idx, done_idx, sent_idx, tc_missed, adc_ovr, starts, ct_bad;
static uint32_t buf_slot[2];
static uint32_t slot_seq[RING_FRAMES], slot_ms[RING_FRAMES];
static uint8_t  slot_flag[RING_FRAMES];
static uint32_t tim2_base;

static void fe_shift(uint8_t v)
{
	/* 74HCT595: MSB first, data PG5, shift clock PI9 (rising), latch PI4 (rising) */
	for (int i = 7; i >= 0; i--) {
		R32(GPIOG + 0x18) = (v >> i) & 1 ? 0x20u : 0x200000u;
		R32(GPIOI + 0x18) = 0x02000000u;
		R32(GPIOI + 0x18) = 0x00000200u;
	}
	R32(GPIOI + 0x18) = 0x10u;
	R32(GPIOI + 0x18) = 0x00100000u;
}

static void gpio_out(uint32_t port, unsigned pin)
{
	R32(port + 0x00) = (R32(port + 0x00) & ~(3u << (2 * pin))) | (1u << (2 * pin));
	R32(port + 0x08) = (R32(port + 0x08) & ~(3u << (2 * pin))) | (2u << (2 * pin));   /* speed: high, as stock */
}

/* Experiment knobs (vendor OUT 0x11), applied at every start. Defaults = stock. */
static uint32_t x_smpr = 0, x_cont = 0, x_ckmode = 3, x_presc = 0;
static uint32_t adc_clk_hz;                           /* what the settings should give *(derived)* */

static void adc_power(unsigned c)
{
	ADCR(c, 0x08) &= ~(1u << 29);                         /* leave deep power-down */
	ADCR(c, 0x08) |= 1u << 28;                            /* ADVREGEN */
	for (uint32_t n = 400000; n && !(ADCR(c, 0x00) & (1u << 12)); n--) { }   /* LDORDY */
}

static void adc_init(void)
{
	RCC_AHB4ENR |= (1u << 5) | (1u << 6) | (1u << 24);    /* GPIOF, GPIOG, ADC3 */
	RCC_AHB1ENR |= RCC_AHB1ENR_ADC;
	(void)RCC_AHB1ENR;
	/* front end as stock starts: DC coupling, gain 0 on both channels */
	gpio_out(GPIOG, 5); gpio_out(GPIOI, 9); gpio_out(GPIOI, 4); gpio_out(GPIOG, 2);
	R32(GPIOI + 0x18) = 0x200u; R32(GPIOG + 0x18) = 0x00040000u;   /* SCLK high, PG2 low */
	fe_shift(0x88);
	R32(GPIOF + 0x00) |= 3u << 22;                        /* PF11 analog */
	R32(GPIOC + 0x00) |= 3u << 6;                         /* PC3 analog */
	adc_power(0); adc_power(1);
}

static void adc_configure(unsigned c)
{
	static const uint16_t pdiv[12] = { 1, 2, 4, 6, 8, 10, 12, 16, 32, 64, 128, 256 };
	uint32_t hclk = 200000000u;
	adc_clk_hz = x_ckmode == 3 ? hclk / 4 : x_ckmode == 2 ? hclk / 2 : x_ckmode == 1 ? hclk
	             : 64000000u / pdiv[x_presc % 12];       /* async: per_ck = HSI 64 MHz at reset *(check)* */
	R32(CCRA[c]) = (R32(CCRA[c]) & ~0x003F0000u) | (x_ckmode << 16) | ((x_ckmode ? 0u : x_presc) << 18);
	uint32_t rev = DBGMCU_IDC >> 16, boost;
	if (rev <= 0x1003u) boost = adc_clk_hz > 20000000u ? 1u : 0u;
	else boost = adc_clk_hz <= 12500000u ? 0u : adc_clk_hz <= 25000000u ? 1u : adc_clk_hz <= 50000000u ? 2u : 3u;
	ADCR(c, 0x08) = (ADCR(c, 0x08) & ~0x300u) | (boost << 8);
	ADCR(c, 0x08) |= 1u << 31;                            /* ADCAL: offset, single-ended (as stock) */
	for (uint32_t n = 4000000; n && (ADCR(c, 0x08) & (1u << 31)); n--) { }
	ADCR(c, 0x1C) = 1u << ACH[c];                         /* PCSEL */
	ADCR(c, 0x14) = (x_smpr & 7u) << (3 * ACH[c]);        /* SMPR1 */
	ADCR(c, 0x30) = (uint32_t)ACH[c] << 6;                /* one conversion, SQ1 */
	ADCR(c, 0x0C) = x_cont ? 0x80003003u : 0x80001483u;   /* DMNGT circular, EXTSEL TIM3_TRGO rising, OVRMOD (or CONT) */
	ADCR(c, 0x00) = 1u; ADCR(c, 0x08) |= 1u;              /* clear ADRDY, ADEN */
	for (uint32_t n = 400000; n && !(ADCR(c, 0x00) & 1u); n--) { }
}

/* Give a DMA buffer its next frame's slot: the next ring slot, or scrap if the ring is full. */
static void buffer_assign(unsigned b)
{
	uint32_t slot = SCRAP_SLOT;
	if (alloc_idx - sent_idx < RING_FRAMES) slot = alloc_idx++ % RING_FRAMES;
	buf_slot[b] = slot;
	for (unsigned k = 0; k < nch; k++)
		DMAR(chidx[k], b ? 0x10 : 0x0C) = PAYLOAD(slot) + k * spf * 2u;
}

static void set_channels(uint32_t m)
{
	chmask = m; nch = 0;
	for (unsigned c = 0; c < 2; c++) if (m & (1u << c)) chidx[nch++] = c;
	spf = FRAME_SAMPLES / nch;
}

static void acq_start(void)
{
	fin = 0; lost = 0; xfers = 0; alloc_idx = done_idx = sent_idx = 0; lost_since_push = 0;
	tc_missed = 0; adc_ovr = 0; ct_bad = 0; starts++;
	for (unsigned k = 0; k < nch; k++) {
		unsigned c = chidx[k];
		adc_configure(c);
		ADCR(c, 0x00) = 0x10u;                            /* clear OVR */
		DMA_LIFCR(c) = 0x0F40u;                           /* stream 1 flags */
		R32(MUXC[c]) = MUXREQ[c];
		DMAR(c, 0x08) = ADCB[c] + 0x40;                   /* PAR = ADCx_DR */
		DMAR(c, 0x04) = spf;                              /* NDTR */
		DMAR(c, 0x14) = 0;                                /* direct mode */
	}
	buffer_assign(0); buffer_assign(1);
	for (unsigned k = 0; k < nch; k++) {
		unsigned c = chidx[k];
		DMAR(c, 0x00) = (1u << 18) | (2u << 16) | (1u << 13) | (1u << 11) | (1u << 10) | (1u << 8);   /* DBM, PL high, 16-bit, MINC */
		DMAR(c, 0x00) |= 1u;                              /* EN */
	}
	for (unsigned k = 0; k < nch; k++) ADCR(chidx[k], 0x08) |= 1u << 2;   /* ADSTART: wait for TIM3 */
	tim2_base = TIM(TIM2B, 0x24);
	running = 1;
}

static void acq_stop(void)
{
	running = 0;
	for (unsigned k = 0; k < nch; k++) {
		unsigned c = chidx[k];
		if (ADCR(c, 0x08) & (1u << 2)) {
			ADCR(c, 0x08) |= 1u << 4;                     /* ADSTP */
			for (uint32_t n = 400000; n && (ADCR(c, 0x08) & (1u << 4)); n--) { }
		}
		DMAR(c, 0x00) &= ~1u;
		for (uint32_t n = 400000; n && (DMAR(c, 0x00) & 1u); n--) { }
		ADCR(c, 0x08) |= 1u << 1;                         /* ADDIS */
		for (uint32_t n = 400000; n && (ADCR(c, 0x08) & 1u); n--) { }
	}
	if (DIEPCTL(2) & EPENA) {
		DIEPCTL(2) |= SNAK;
		for (uint32_t n = 0x30D41; n && !(DIEPINT(2) & (1u << 6)); n--) { }
		DIEPCTL(2) |= (1u << 30) | SNAK;                  /* EPDIS */
		for (uint32_t n = 0x30D41; n && !(DIEPINT(2) & 2u); n--) { }
		DIEPINT(2) = 0xFFFFu;
	}
	ep_busy = 0;
	GRSTCTL = (2u << 6) | 0x20u; wait_clear(&GRSTCTL, 0x20);   /* flush TX FIFO 2 */
}

static void ep2_activate(void)
{
	DIEPCTL(2) = 512u | USBAEP | (2u << 18) | (2u << 22) | (1u << 28) | SNAK;
}

static void frame_send(uint32_t slot)
{
	frame_header_t *h = (frame_header_t *)SLOT(slot);
	h->magic[0] = FRAME_MAGIC0; h->magic[1] = FRAME_MAGIC1;
	h->magic[2] = FRAME_MAGIC2; h->magic[3] = FRAME_MAGIC3;
	h->version = FRAME16_VERSION;
	h->flags = slot_flag[slot] ? FRAME_FLAG_OVERRUN : 0;
	h->channel_mask = chmask;
	h->seq = slot_seq[slot];
	h->sample_rate_hz = 200000000u / period;
	h->timestamp_us = slot_ms[slot] * 1000u;
	h->overrun_count = lost;
	h->play_consumed = 0;
	h->header_crc32 = frame_crc32((const uint8_t *)h, 28);
	__asm volatile ("dsb sy" ::: "memory");              /* header stores must reach SRAM before the DMA reads them */
	DIEPDMA(2) = SLOT(slot);
	DIEPTSIZ(2) = ((FRAME_BYTES / 512u) << 19) | FRAME_BYTES;
	DIEPCTL(2) |= EPENA | CNAK;
	ep_busy = 1;
}

static void stream_poll(void)
{
	int want = dtr && config_value == 1;
	if (want && !running) acq_start();
	else if (!want && running) acq_stop();
	if (!running) return;

	for (unsigned k = 0; k < nch; k++)
		if (ADCR(chidx[k], 0x00) & 0x10u) { adc_ovr++; ADCR(chidx[k], 0x00) = 0x10u; }

	unsigned tc = 0;
	for (unsigned k = 0; k < nch; k++) tc += (DMA_LISR(chidx[k]) >> 11) & 1u;
	if (tc == nch) {                                      /* every active plane of one frame is done */
		for (unsigned k = 0; k < nch; k++) {
			DMA_LIFCR(chidx[k]) = 1u << 11;
			if (((DMAR(chidx[k], 0x00) >> 19) & 1u) != ((fin + 1) & 1u)) ct_bad++;
		}
		unsigned b = fin & 1u;
		uint32_t slot = buf_slot[b];
		if (slot == SCRAP_SLOT) { lost++; lost_since_push = 1; }
		else {
			slot_seq[slot] = fin; slot_ms[slot] = ms_now;
			slot_flag[slot] = lost_since_push; lost_since_push = 0;
			done_idx++;
		}
		fin++;
		buffer_assign(b);                                 /* frame fin + 1 goes to the buffer just freed */
		uint32_t exp = (TIM(TIM2B, 0x24) - tim2_base) / spf;
		if (exp > fin + 1) tc_missed += exp - fin - 1;    /* the ADC clock ledger says we fell behind */
	}

	if (ep_busy && (DIEPINT(2) & 1u)) {
		DIEPINT(2) = 1u; ep_busy = 0; sent_idx++; xfers++;
	}
	if (!ep_busy && sent_idx < done_idx) frame_send(sent_idx % RING_FRAMES);
}

/* ---- control requests --------------------------------------------------- */

static void handle_setup(const uint8_t *s)
{
	uint8_t  type = s[0], req = s[1];
	uint16_t val = s[2] | (s[3] << 8), idx = s[4] | (s[5] << 8), len = s[6] | (s[7] << 8);
	uint8_t tmp[64];

	if ((type & 0x60) == 0x00) {                             /* standard */
		switch (req) {
		case 0x06:                                           /* GET_DESCRIPTOR */
			switch (val >> 8) {
			case 1: ep0_send(dev_desc, sizeof dev_desc, len); return;
			case 2: ep0_send(cfg_desc, sizeof cfg_desc, len); return;
			case 6: ep0_send(qual_desc, sizeof qual_desc, len); return;
			case 3: {
				unsigned id = val & 0xFF;
				if (id > 3) break;
				unsigned n = build_string(id);
				ep0_send(strbuf, n, len); return;
			}
			}
			break;
		case 0x05:                                           /* SET_ADDRESS */
			DCFG = (DCFG & ~0x7F0u) | ((uint32_t)(val & 0x7F) << 4);
			ep0_status_in(); return;
		case 0x09:                                           /* SET_CONFIGURATION */
			config_value = val & 0xFF;
			if (config_value == 1) ep2_activate();
			ep0_status_in(); return;
		case 0x08: tmp[0] = config_value; ep0_send(tmp, 1, len); return;
		case 0x00: tmp[0] = tmp[1] = 0; ep0_send(tmp, 2, len); return;
		case 0x0A: tmp[0] = 0; ep0_send(tmp, 1, len); return;
		case 0x01: case 0x03: case 0x0B:                     /* CLEAR/SET_FEATURE, SET_INTERFACE */
			ep0_status_in(); return;
		}
	} else if ((type & 0x60) == 0x20) {                      /* class (CDC) */
		switch (req) {
		case 0x20:                                           /* SET_LINE_CODING */
			if (ep0_recv(tmp) >= 7) for (unsigned i = 0; i < 7; i++) line_coding[i] = tmp[i];
			ep0_status_in(); return;
		case 0x21: ep0_send(line_coding, 7, len); return;    /* GET_LINE_CODING */
		case 0x22:                                           /* SET_CONTROL_LINE_STATE */
			if (idx == 0) dtr = val & 1u;
			ep0_status_in(); return;
		}
	} else if ((type & 0xE0) == 0x40 && req == 0x14) {       /* vendor OUT: SYSCFG PC3 analog switch bit (PMCR bit 27) */
		R32(0x580244F4u) |= 2u; (void)R32(0x580244F4u);       /* SYSCFG clock */
		R32(0x58000404u) = (R32(0x58000404u) & ~(1u << 27)) | ((uint32_t)(val & 1u) << 27);
		ep0_status_in(); return;
	} else if ((type & 0xE0) == 0x40 && req == 0x13) {       /* vendor OUT: channel mask */
		if (!running && val >= 1 && val <= 3) { set_channels(val); ep0_status_in(); return; }
	} else if ((type & 0xE0) == 0x40 && req == 0x12) {       /* vendor OUT: 74HCT595 byte (gain / coupling) */
		fe_shift(val & 0xFF);
		ep0_status_in(); return;
	} else if ((type & 0xE0) == 0x40 && req == 0x11) {       /* vendor OUT: ADC experiment knobs */
		if (!running) {
			x_smpr = val & 7u; x_cont = idx & 1u; x_ckmode = (idx >> 1) & 3u; x_presc = (idx >> 3) & 15u;
			ep0_status_in(); return;
		}
	} else if ((type & 0xE0) == 0x40 && req == 0x10) {       /* vendor OUT: sample period */
		uint32_t p = val | ((uint32_t)idx << 16);
		if (!running && p >= MIN_PERIOD && p < 0x80000000u) {
			period = p; TIM(TIM3B, 0x2C) = p - 1u;
			ep0_status_in(); return;
		}
	} else if ((type & 0x60) == 0x40 && (type & 0x80)) {     /* vendor IN */
		unsigned n = 0;
		if (req == 0x01) {                                   /* core id/config */
			static const uint16_t off[] = { 0x3C, 0x40, 0x44, 0x48, 0x4C, 0x50, 0x54, 0x24, 0x28 };
			for (; n < sizeof off / sizeof off[0]; n++) txbuf[n] = R32(USB + off[n]);
		}
		if (req == 0x03) { for (; n < 8; n++) txbuf[n] = m_res[n]; }
		if (req == 0x04) {                               /* acquisition counters */
			txbuf[n++] = fin; txbuf[n++] = lost; txbuf[n++] = sent_idx; txbuf[n++] = xfers;
			txbuf[n++] = tc_missed; txbuf[n++] = adc_ovr; txbuf[n++] = DBGMCU_IDC >> 16;
			txbuf[n++] = starts; txbuf[n++] = ct_bad; txbuf[n++] = period; txbuf[n++] = adc_clk_hz; txbuf[n++] = chmask;
		}
		if (n) { ep0_send((const uint8_t *)txbuf, n * 4, len); return; }
	}
	ep0_stall();
}


/* ---- clocks and their measurement ------------------------------------- */

#define PWR_D3CR     R32(0x58024818u)
#define FLASH_ACR    R32(0x52002000u)
#define RCC_CR       R32(0x58024400u)
#define RCC_CFGR     R32(0x58024410u)
#define RCC_D1CFGR   R32(0x58024418u)
#define RCC_D2CFGR   R32(0x5802441Cu)
#define RCC_D3CFGR   R32(0x58024420u)
#define RCC_PLLCKSELR R32(0x58024428u)
#define RCC_PLLCFGR  R32(0x5802442Cu)
#define RCC_PLL1DIVR R32(0x58024430u)
#define RCC_APB1LENR R32(0x580244E8u)
#define TIM(b, o)    R32((b) + (o))
#define TIM2B 0x40000000u
#define TIM3B 0x40000400u
#define TIM5B 0x40000C00u
#define DEMCR        R32(0xE000EDFCu)
#define DWT_CTRL     R32(0xE0001000u)
#define DWT_CYCCNT   R32(0xE0001004u)

static uint8_t clock_state;                        /* 0 HSI, 1 PLL1 400 MHz */

static int wait_set(volatile uint32_t *r, uint32_t bits)
{
	for (uint32_t n = 4000000; n; n--)
		if ((*r & bits) == bits) return 1;
	return 0;
}

/* Stock order: VOS1, HSE, PLL1, latency, prescalers, then switch. */
static void clock_init(void)
{
	PWR_D3CR |= 0xC000u;                                  /* VOS1 */
	if (!wait_set(&PWR_D3CR, 1u << 13)) return;           /* VOSRDY */
	RCC_CR |= 1u << 16;                                   /* HSEON */
	if (!wait_set(&RCC_CR, 1u << 17)) return;             /* HSERDY */
	RCC_PLLCKSELR = 2u | (5u << 4);                       /* HSE, M = 5 */
	RCC_PLLCFGR = (2u << 2) | (1u << 16) | (1u << 17) | (1u << 18);   /* RGE 4-8 MHz, wide VCO, P/Q/R on */
	RCC_PLL1DIVR = (159u) | (1u << 9) | (3u << 16) | (1u << 24);      /* N160 P2 Q4 R2 */
	RCC_CR |= 1u << 24;                                   /* PLL1ON */
	if (!wait_set(&RCC_CR, 1u << 25)) { RCC_CR &= ~(1u << 24); return; }
	FLASH_ACR = 4u;                                       /* 4 wait states (stock) */
	RCC_D1CFGR = (8u << 0) | (4u << 4);                   /* HPRE /2, APB3 /2, CPRE /1 */
	RCC_D2CFGR = (4u << 4) | (4u << 8);                   /* APB1, APB2 /2 */
	RCC_D3CFGR = (4u << 4);                               /* APB4 /2 */
	RCC_CFGR = (RCC_CFGR & ~7u) | 3u;                     /* SW = PLL1 */
	for (uint32_t n = 4000000; n; n--)
		if (((RCC_CFGR >> 3) & 7u) == 3u) { cpu_hz = 400000000u; clock_state = 1; return; }
	RCC_CFGR &= ~7u;                                      /* back to HSI */
}

static void meter_init(void)
{
	RCC_APB1LENR |= (1u << 0) | (1u << 1) | (1u << 3);   /* TIM2, TIM3, TIM5 */
	(void)RCC_APB1LENR;
	DEMCR |= 1u << 24;
	DWT_CTRL |= 1u;
	TIM(TIM3B, 0x28) = 0; TIM(TIM3B, 0x2C) = 199;         /* 200 MHz / 200 = 1 MHz; acq_start/requests change it */
	TIM(TIM3B, 0x04) = 2u << 4;                           /* MMS = update -> TRGO */
	TIM(TIM2B, 0x2C) = 0xFFFFFFFFu;
	TIM(TIM2B, 0x08) = 7u | (2u << 4);                    /* external clock mode 1, TS = ITR2 (TIM3) *(check)* */
	TIM(TIM5B, 0x2C) = 0xFFFFFFFFu;
	TIM(TIM2B, 0x00) = 1u; TIM(TIM5B, 0x00) = 1u; TIM(TIM3B, 0x00) = 1u;
}

#define METER_SOFS 8000u
static uint32_t m_n, m_c0, m_t50, m_t20;

static void meter_poll(void)
{
	if (!(GINTSTS & (1u << 3))) return;
	uint32_t c = DWT_CYCCNT, t5 = TIM(TIM5B, 0x24), t2 = TIM(TIM2B, 0x24);
	GINTSTS = 1u << 3;
	if (m_n == 0) { m_c0 = c; m_t50 = t5; m_t20 = t2; }
	if (++m_n > METER_SOFS) {
		m_res[0] = c - m_c0; m_res[1] = t5 - m_t50; m_res[2] = t2 - m_t20;
		m_res[3] = METER_SOFS; m_res[4]++; m_res[5] = cpu_hz;
		m_res[6] = (RCC_CFGR >> 3) & 7u; m_res[7] = clock_state;
		m_n = 1; m_c0 = c; m_t50 = t5; m_t20 = t2;
	}
}

void Reset_Handler(void)
{
	uint32_t *s = &_sidata, *d = &_sdata;
	while (d < &_edata) *d++ = *s++;
	for (d = &_sbss; d < &_ebss; ) *d++ = 0;

	clock_init();
	SYST_RVR = cpu_hz / 1000u - 1u;
	SYST_CSR = 5u;
	meter_init();
	adc_init();

	RCC_AHB2ENR |= 7u << 29;                            /* D2 SRAM1..3 */
	(void)RCC_AHB2ENR;

	/* pins and clocks */
	RCC_AHB4ENR |= 0x187u;                              /* GPIOA, B, C, H, I */
	(void)RCC_AHB4ENR;
	pin_af10(GPIOA, 3); pin_af10(GPIOA, 5);
	pin_af10(GPIOB, 0); pin_af10(GPIOB, 1); pin_af10(GPIOB, 5);
	pin_af10(GPIOB, 10); pin_af10(GPIOB, 11); pin_af10(GPIOB, 12); pin_af10(GPIOB, 13);
	pin_af10(GPIOC, 0); pin_af10(GPIOH, 4); pin_af10(GPIOI, 11);
	RCC_AHB1ENR |= (1u << 26) | (1u << 25);             /* ULPI, OTG_HS */
	(void)RCC_AHB1ENR;

	/* core init (stock HAL_PCD_Init, ULPI branch) */
	GAHBCFG &= ~1u;
	GCCFG &= ~0x00010000u;                              /* PWRDWN = 0 */
	GUSBCFG &= 0xFFBDFFBFu;                             /* TSDPS, ULPIFSLS, PHYSEL = 0 */
	GUSBCFG &= ~0x00300000u;
	for (uint32_t n = 0x30D41; n && !(GRSTCTL & 0x80000000u); n--) { }
	GRSTCTL |= 1u;
	wait_clear(&GRSTCTL, 1u);
	GUSBCFG = (GUSBCFG & ~0x60000000u) | 0x40000000u;   /* force device mode */
	delay_ms(50);

	/* USB_DevInit */
	for (unsigned i = 1; i < 16; i++) DIEPTXF(i) = 0;
	DCTL |= 2u;                                         /* soft disconnect */
	GCCFG &= ~0x00200000u;                              /* VBDEN = 0 */
	GOTGCTL |= 0x40u; GOTGCTL |= 0x80u;                 /* B-session valid override */
	PCGCCTL = 0;
	DCFG &= ~0x3u;                                      /* high speed (DSPD = 0) */
	DCFG &= ~0x1800u;                                   /* PFIVL 80 % */
	flush_fifos();
	DIEPMSK = 0; DOEPMSK = 0; DAINTMSK = 0;
	ep_reset_all();
	DIEPMSK &= ~0x100u;
	GINTMSK = 0; GINTSTS = 0xBFFFFFFFu;

	/* FIFO layout in words, 952 available (GHWCFG3): RX 256; TX0 16, TX1 8,
	 * TX2 (stream) 512, TX3 8, TX4 128; the rest 1-word. */
	GRXFSIZ = 256u;
	DIEPTXF0 = (16u << 16) | 256u;
	DIEPTXF(1) = (8u << 16) | 272u;
	DIEPTXF(2) = (512u << 16) | 280u;
	DIEPTXF(3) = (8u << 16) | 792u;
	DIEPTXF(4) = (128u << 16) | 800u;
	for (unsigned i = 5; i <= 8; i++) DIEPTXF(i) = (1u << 16) | (928u + (i - 5));

	GAHBCFG = (3u << 1) | (1u << 5);                    /* INCR4 *(check)*, DMAEN */
	GAHBCFG |= 1u;                                      /* global interrupt flag (unused) */
	PCGCCTL &= ~3u;
	DCTL &= ~2u;                                        /* connect */

	uint8_t setup[8];
	while (ms_now < RUN_MS) {
		tick();
		uint32_t sts = GINTSTS;
		if (sts & (1u << 12)) {                         /* USBRST */
			if (running) acq_stop();
			running = 0; dtr = 0; config_value = 0;
			DCTL &= ~1u;
			flush_fifos();
			for (unsigned i = 0; i < 8; i++) {
				DIEPINT(i) = 0xFB7F; DOEPINT(i) = 0xFB7F;
				DIEPCTL(i) |= SNAK; DOEPCTL(i) |= SNAK;
			}
			DIEPCTL(2) = 0;
			DAINTMSK |= 0x10001u;
			DOEPMSK |= 0x202Bu; DIEPMSK |= 0x0Bu;
			DCFG &= ~0x7F0u;                            /* address 0 */
			ep0_arm_setup();
			GINTSTS = 0x1000u;
		}
		if (sts & (1u << 13)) {                         /* ENUMDNE */
			DIEPCTL(0) &= ~0x7FFu;                      /* EP0 MPS = 64 */
			DCTL |= 0x100u;
			GUSBCFG = (GUSBCFG & ~0x3C00u) | 0x2400u;   /* TRDT = 9 */
			GINTSTS = 0x2000u;
		}
		uint32_t oi = DOEPINT(0);
		if (oi & 0x8u) {                                /* STUP: setup phase done */
			unsigned cnt = (DOEPTSIZ(0) >> 29) & 3u;
			unsigned o = cnt >= 2 ? 0 : (2u - cnt) * 8u;
			for (unsigned k = 0; k < 8; k++) setup[k] = SETUPBUF[o + k];
			DOEPINT(0) = oi & (0x8u | 0x8000u | 0x20u | 1u);
			handle_setup(setup);
		} else if (oi & (1u | 0x20u)) {                 /* OUT done / status phase received */
			DOEPINT(0) = oi & (1u | 0x20u | 0x8000u);
		}
		if (!(DOEPCTL(0) & EPENA)) ep0_arm_setup();     /* the core disables EP0 OUT after each transfer */
		stream_poll();
		meter_poll();
	}
	if (running) acq_stop();
	return_to_boot_loader();
}

static void default_handler(void) { for (;;) { } }

__attribute__((section(".isr_vector"), used))
void (*const vectors[])(void) = {
	(void (*)(void))&_estack,
	Reset_Handler,
	default_handler, default_handler, default_handler, default_handler,
};
