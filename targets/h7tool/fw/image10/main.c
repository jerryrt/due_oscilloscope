/* Image 10 (phase 6b): image9 plus host-fed playback (vendor OUT 0x23 start with
 * prime units / 0 stop, IN 0x07 counters; the host writes DAC codes to the stream
 * port). Image 9 was: image8's two-channel acquisition plus the DAC1/VOUT
 * generator bring-up, set from the host by vendor requests: OUT 0x20 (wValue =
 * wave 0 off / 1 DC / 2 sine / 3 square / 4 ramp, wIndex = amplitude in DAC
 * codes, capped), OUT 0x21 (TIM6 period ticks, 32 bit), OUT 0x22 (centre code),
 * IN 0x06 generator state. See docs/13-phase6-generator.md. */
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
	RCC_AHB4ENR |= (1u << 5) | (1u << 6) | (1u << 8) | (1u << 24);    /* GPIOF, GPIOG, GPIOI (the 595 clocks), ADC3 */
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

/* ---- the generator: DAC1 channel 1 (PA4) -> +-10 V stage ----------------------
 * Stock sequence (docs/05 section 6): PE3 high enables the TPS65130 +-12.4 V
 * supply, then the DAC is triggered by TIM6's update and fed by DMA1 stream 5
 * (DMAMUX request 67) from a halfword table. The table is built once at start
 * (setup, not streaming); a host-fed ring replaces it in the next stage.
 * SAFETY: the output stage reaches +-10 V and drives whatever is on VOUT. Until
 * the owner raises it, the swing is capped at GEN_LIMIT codes either side of the
 * stock's zero (about 6 mV per code: 330 codes ~ +-2 V). The stock's own
 * calibration pairs (code:mV) 500:-9190, 1500:-3212, 2500:2771, 3500:8755 put
 * 0 V at code ~2036. */
#define GPIOE        0x58021000u
#define RCC_APB1LENR R32(0x580244E8u)
#define DACB         0x40007400u
#define DAC_R(o)     R32(DACB + (o))
#define TIM6B        0x40001000u
#define DMAMUX1_C5CR R32(0x40020814u)
#define DMA1_S5(o)   R32(0x40020088u + (o))        /* CR 0, NDTR 4, PAR 8, M0AR 0xC */
#define GEN_ZERO     2036u
#define GEN_LIMIT    330u
#define GEN_MIN_PERIOD 400u                        /* 500 kS/s update, unproven faster *(check)* */
#define GEN_N        256u
#define GEN_TAB      ((volatile uint16_t *)0x30030000u)

static const int16_t sin_tab[256] = { 0, 804, 1608, 2410, 3212, 4011, 4808, 5602, 6393, 7179, 7962, 8739, 9512, 10278, 11039, 11793, 12539, 13279, 14010, 14732, 15446, 16151, 16846, 17530, 18204, 18868, 19519, 20159, 20787, 21403, 22005, 22594, 23170, 23731, 24279, 24811, 25329, 25832, 26319, 26790, 27245, 27683, 28105, 28510, 28898, 29268, 29621, 29956, 30273, 30571, 30852, 31113, 31356, 31580, 31785, 31971, 32137, 32285, 32412, 32521, 32609, 32678, 32728, 32757, 32767, 32757, 32728, 32678, 32609, 32521, 32412, 32285, 32137, 31971, 31785, 31580, 31356, 31113, 30852, 30571, 30273, 29956, 29621, 29268, 28898, 28510, 28105, 27683, 27245, 26790, 26319, 25832, 25329, 24811, 24279, 23731, 23170, 22594, 22005, 21403, 20787, 20159, 19519, 18868, 18204, 17530, 16846, 16151, 15446, 14732, 14010, 13279, 12539, 11793, 11039, 10278, 9512, 8739, 7962, 7179, 6393, 5602, 4808, 4011, 3212, 2410, 1608, 804, 0, -804, -1608, -2410, -3212, -4011, -4808, -5602, -6393, -7179, -7962, -8739, -9512, -10278, -11039, -11793, -12539, -13279, -14010, -14732, -15446, -16151, -16846, -17530, -18204, -18868, -19519, -20159, -20787, -21403, -22005, -22594, -23170, -23731, -24279, -24811, -25329, -25832, -26319, -26790, -27245, -27683, -28105, -28510, -28898, -29268, -29621, -29956, -30273, -30571, -30852, -31113, -31356, -31580, -31785, -31971, -32137, -32285, -32412, -32521, -32609, -32678, -32728, -32757, -32767, -32757, -32728, -32678, -32609, -32521, -32412, -32285, -32137, -31971, -31785, -31580, -31356, -31113, -30852, -30571, -30273, -29956, -29621, -29268, -28898, -28510, -28105, -27683, -27245, -26790, -26319, -25832, -25329, -24811, -24279, -23731, -23170, -22594, -22005, -21403, -20787, -20159, -19519, -18868, -18204, -17530, -16846, -16151, -15446, -14732, -14010, -13279, -12539, -11793, -11039, -10278, -9512, -8739, -7962, -7179, -6393, -5602, -4808, -4011, -3212, -2410, -1608, -804 };
static uint32_t gen_type, gen_amp, gen_center = GEN_ZERO, gen_period = 800;   /* 800 ticks = 250 kS/s */
static uint8_t  gen_on;

static void gen_init(void)
{
	RCC_AHB4ENR |= 1u << 4;                            /* GPIOE */
	(void)RCC_AHB4ENR;
	R32(GPIOE + 0x18) = 1u << 19;                      /* PE3 low (supply off) before it is an output */
	R32(GPIOE + 0x00) = (R32(GPIOE + 0x00) & ~(3u << 6)) | (1u << 6);
	R32(GPIOA) |= 3u << 8;                             /* PA4 analog (DAC1_OUT1) *(also its reset state)* */
	RCC_APB1LENR |= (1u << 29) | (1u << 4);            /* DAC12, TIM6 */
	(void)RCC_APB1LENR;
}

static void gen_stop(void)
{
	TIM(TIM6B, 0x00) = 0;                              /* CEN off */
	DAC_R(0x00) &= ~(1u << 12);                        /* DMAEN1 off */
	DMA1_S5(0) &= ~1u;
	for (uint32_t n = 400000; n && (DMA1_S5(0) & 1u); n--) { }
	if (gen_on) {
		DAC_R(0x00) &= ~2u;                            /* TEN1 off: software mode */
		DAC_R(0x08) = gen_center;                      /* park at zero ... */
		DAC_R(0x00) &= ~1u;                            /* ... then DAC off */
	}
	R32(GPIOE + 0x18) = 1u << 19;                      /* PE3 low: supply off */
	gen_on = 0;
}

static void gen_start(void)
{
	if (gen_on) gen_stop();
	unsigned n = GEN_N;
	if (gen_type == 1) n = 2;
	for (unsigned i = 0; i < n; i++) {
		int32_t v = 0;
		if (gen_type == 2) v = ((int32_t)sin_tab[i] * (int32_t)gen_amp) >> 15;
		else if (gen_type == 3) v = i < n / 2 ? (int32_t)gen_amp : -(int32_t)gen_amp;
		else if (gen_type == 4) v = ((int32_t)i * 2 * (int32_t)gen_amp) / (int32_t)n - (int32_t)gen_amp;
		GEN_TAB[i] = (uint16_t)((int32_t)gen_center + v);
	}
	if (gen_type == 1) { GEN_TAB[0] = gen_center + gen_amp; GEN_TAB[1] = gen_center + gen_amp; }
	R32(GPIOE + 0x18) = 1u << 3;                       /* PE3 high: stock does this first */
	delay_ms(20);                                      /* supply settle *(check: not measured)* */
	DAC_R(0x00) = 1u;                                  /* EN1 */
	delay_ms(1);
	DAC_R(0x08) = GEN_TAB[0];                          /* first value before the trigger starts */
	DMAMUX1_C5CR = 67u;
	DMA1_S5(8) = DACB + 0x08;                          /* PAR = DHR12R1 */
	DMA1_S5(0xC) = (uint32_t)GEN_TAB;
	DMA1_S5(4) = n;
	DMA1_S5(0) = (1u << 6) | (1u << 8) | (1u << 10) | (1u << 11) | (1u << 13) | (1u << 16);   /* mem->periph, circ, MINC, 16-bit, PL medium */
	DMA1_S5(0) |= 1u;
	DAC_R(0x00) = 1u | 2u | (5u << 2) | (1u << 12);    /* EN1, TEN1, TSEL1 = TIM6_TRGO *(check)*, DMAEN1 */
	TIM(TIM6B, 0x28) = 0; TIM(TIM6B, 0x2C) = gen_period - 1u;
	TIM(TIM6B, 0x04) = 2u << 4;                        /* MMS = update */
	TIM(TIM6B, 0x14) = 1u;                             /* UG: load */
	TIM(TIM6B, 0x00) = 1u;                             /* CEN */
	gen_on = 1;
}

/* ---- host-fed playback: USB OUT (stream function, EP2) -> ring -> DAC -------
 * The host writes DAC codes (halfwords) to the stream port. Each 512-byte
 * packet is one OUT transfer by DMA into the next unit of a 32 KiB ring in D2
 * SRAM; the DAC drains the same ring through TIM6 + DMA1 stream 5, circular.
 * A unit is only armed while the ring has room, so a full ring NAKs the host
 * (back-pressure, nothing is dropped). TIM6 starts only once PLAY_PRIME samples
 * are buffered and is stopped (the DAC holds its last value) when the ring runs
 * dry; each such stop counts one underrun. The DAC runs at gen_period.
 * PLAY_GUARD is a DEBUG-ONLY screen that breaks invariant 1 on purpose: the
 * CPU reads every arriving code and refuses the stream if one is outside the
 * +-GEN_LIMIT swing, because the output stage reaches +-10 V. It goes when
 * the owner raises the limit or the host enforces it. */
#ifndef PLAY_GUARD
#define PLAY_GUARD 1
#endif
#define PLAY_RING    0x30038000u
#define PLAY_UNITS   64u                           /* 512-byte units */
#define PLAY_UNIT_SAMPLES 256u
#define PLAY_N       (PLAY_UNITS * PLAY_UNIT_SAMPLES)   /* ring length in samples */

static uint8_t  play_on, play_timer, play_armed;
static uint32_t play_prime = 4 * PLAY_UNIT_SAMPLES;
static uint32_t play_wr_units, play_consumed, play_last_pos, play_underruns, play_guard_trips, play_min_occ, play_resumes, play_short;

static void play_arm(void)
{
	DOEPTSIZ(2) = (1u << 19) | 512u;
	DOEPDMA(2) = PLAY_RING + (play_wr_units % PLAY_UNITS) * 512u;
	__asm volatile ("dsb sy" ::: "memory");
	DOEPCTL(2) |= EPENA | CNAK;
	play_armed = 1;
}

static void play_stop(void)
{
	TIM(TIM6B, 0x00) = 0;
	DAC_R(0x00) &= ~(1u << 12);
	DMA1_S5(0) &= ~1u;
	for (uint32_t n = 400000; n && (DMA1_S5(0) & 1u); n--) { }
	if (DOEPCTL(2) & EPENA) {                          /* disable an OUT endpoint: global OUT NAK first */
		DCTL |= 1u << 7;                               /* SGONAK */
		for (uint32_t n = 0x30D41; n && !(GINTSTS & (1u << 7)); n--) { }      /* GONAKEFF */
		DOEPCTL(2) |= (1u << 30) | SNAK;                                       /* EPDIS */
		for (uint32_t n = 0x30D41; n && !(DOEPINT(2) & 2u); n--) { }
		DOEPINT(2) = 0xFFFFu;
		DCTL |= 1u << 10;                              /* CGONAK */
	}
	play_armed = 0;
	if (play_on) { DAC_R(0x00) &= ~2u; DAC_R(0x08) = gen_center; DAC_R(0x00) &= ~1u; }
	R32(GPIOE + 0x18) = 1u << 19;                      /* PE3 low */
	play_on = 0; play_timer = 0;
}

static void play_start(uint32_t prime_units)
{
	if (gen_on) gen_stop();
	if (play_on) play_stop();
	play_wr_units = 0; play_consumed = 0; play_last_pos = 0; play_underruns = 0;
	play_guard_trips = 0; play_min_occ = 0xFFFFFFFFu; play_resumes = 0; play_short = 0;
	play_prime = prime_units * PLAY_UNIT_SAMPLES;
	R32(GPIOE + 0x18) = 1u << 3;                       /* PE3 high */
	delay_ms(20);
	TIM(TIM6B, 0x28) = 0; TIM(TIM6B, 0x2C) = gen_period - 1u;
	TIM(TIM6B, 0x04) = 2u << 4; TIM(TIM6B, 0x14) = 1u;          /* UG before the DAC listens to the trigger */
	DAC_R(0x00) = 1u; delay_ms(1);
	DAC_R(0x08) = gen_center;
	DMAMUX1_C5CR = 67u;
	DMA1_S5(8) = DACB + 0x08; DMA1_S5(0xC) = PLAY_RING; DMA1_S5(4) = PLAY_N;
	DMA1_S5(0) = (1u << 6) | (1u << 8) | (1u << 10) | (1u << 11) | (1u << 13) | (1u << 16);
	DMA1_S5(0) |= 1u;
	DAC_R(0x00) = 1u | 2u | (5u << 2) | (1u << 12);
	play_on = 1;
	DOEPCTL(2) = 512u | USBAEP | (2u << 18) | SNAK;            /* EP2 OUT: bulk, 512 */
	play_arm();
}

static void play_poll(void)
{
	if (!play_on) return;
	if (DOEPINT(2) & 1u) {
		DOEPINT(2) = DOEPINT(2) & 0x8001u;
		play_armed = 0;
		if (DOEPTSIZ(2) & 0x7FFFFu) { play_short++; play_arm(); return; }   /* short packet: not a whole unit, drop it */
		uint32_t base = PLAY_RING + (play_wr_units % PLAY_UNITS) * 512u;
#if PLAY_GUARD
		volatile uint16_t *p = (volatile uint16_t *)base;
		for (unsigned i = 0; i < PLAY_UNIT_SAMPLES; i++)
			if ((int)p[i] < (int)(GEN_ZERO - GEN_LIMIT) || (int)p[i] > (int)(GEN_ZERO + GEN_LIMIT)) {
				play_guard_trips++; play_stop(); return;
			}
#endif
		play_wr_units++;
	}
	uint32_t pos = PLAY_N - DMA1_S5(4);
	if (pos >= PLAY_N) pos = 0;
	play_consumed += (pos - play_last_pos) & (PLAY_N - 1u);
	play_last_pos = pos;
	int32_t occ = (int32_t)(play_wr_units * PLAY_UNIT_SAMPLES - play_consumed);
	if (play_timer && (uint32_t)occ < play_min_occ) play_min_occ = (uint32_t)occ;
	if (play_timer && occ < 16) { TIM(TIM6B, 0x00) = 0; play_timer = 0; play_underruns++; }
	else if (!play_timer && occ >= (int32_t)play_prime) { TIM(TIM6B, 0x00) = 1; play_timer = 1; play_resumes++; }
	if (!play_armed && (uint32_t)occ + PLAY_UNIT_SAMPLES < PLAY_N - PLAY_UNIT_SAMPLES) play_arm();
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
	} else if ((type & 0xE0) == 0x40 && req == 0x23) {       /* vendor OUT: playback start (wValue = prime units 1..32) / stop (0) */
		if (val == 0) { if (play_on) play_stop(); ep0_status_in(); return; }
		if (val <= 32 && config_value == 1) { play_start(val); ep0_status_in(); return; }
	} else if ((type & 0xE0) == 0x40 && req == 0x20) {       /* vendor OUT: generator wave and amplitude */
		uint32_t cen = gen_center, amp = idx;
		if (val > 4) { ep0_stall(); return; }
		if (amp > GEN_LIMIT) { ep0_stall(); return; }      /* refuse, do not clamp: a clamped request would look accepted */
		uint32_t dev = cen > GEN_ZERO ? cen - GEN_ZERO : GEN_ZERO - cen;
		if (dev + amp > GEN_LIMIT) { ep0_stall(); return; }
		gen_type = val; gen_amp = amp;
		if (val == 0) gen_stop(); else gen_start();
		ep0_status_in(); return;
	} else if ((type & 0xE0) == 0x40 && req == 0x21) {       /* vendor OUT: TIM6 period (ticks at 200 MHz) */
		uint32_t p = val | ((uint32_t)idx << 16);
		if (p >= GEN_MIN_PERIOD && p < 0x10000000u) { gen_period = p; if (gen_on) TIM(TIM6B, 0x2C) = p - 1u; ep0_status_in(); return; }
	} else if ((type & 0xE0) == 0x40 && req == 0x22) {       /* vendor OUT: centre code (0 V = 2036 per stock calibration) */
		if (!gen_on && val > GEN_ZERO - GEN_LIMIT && val < GEN_ZERO + GEN_LIMIT) { gen_center = val; ep0_status_in(); return; }
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
		if (req == 0x07) {                               /* playback counters */
			txbuf[n++] = play_wr_units; txbuf[n++] = play_consumed; txbuf[n++] = play_underruns; txbuf[n++] = play_guard_trips;
			txbuf[n++] = play_on; txbuf[n++] = play_timer; txbuf[n++] = play_min_occ; txbuf[n++] = play_resumes;
			txbuf[n++] = play_wr_units * PLAY_UNIT_SAMPLES - play_consumed; txbuf[n++] = play_short;
		}
		if (req == 0x06) {                               /* generator state */
			txbuf[n++] = gen_on; txbuf[n++] = (R32(GPIOE + 0x10) >> 3) & 1u; txbuf[n++] = DAC_R(0x00);
			txbuf[n++] = DAC_R(0x2C); txbuf[n++] = DMA1_S5(4); txbuf[n++] = TIM(TIM6B, 0x24);
			txbuf[n++] = gen_period; txbuf[n++] = gen_center; txbuf[n++] = gen_amp; txbuf[n++] = gen_type;
		}
		if (req == 0x05) {                               /* front-end pins: G and I MODER, ODR, IDR, OSPEEDR; RCC AHB4ENR */
			txbuf[n++] = R32(GPIOG); txbuf[n++] = R32(GPIOG + 0x14); txbuf[n++] = R32(GPIOG + 0x10); txbuf[n++] = R32(GPIOG + 0x08);
			txbuf[n++] = R32(GPIOI); txbuf[n++] = R32(GPIOI + 0x14); txbuf[n++] = R32(GPIOI + 0x10); txbuf[n++] = R32(GPIOI + 0x08);
			txbuf[n++] = RCC_AHB4ENR;
		}
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
	gen_init();

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
			if (play_on) play_stop();
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
		play_poll();
		meter_poll();
	}
	if (running) acq_stop();
	if (gen_on) gen_stop();
	if (play_on) play_stop();
	return_to_boot_loader();
}

static void default_handler(void) { for (;;) { } }

__attribute__((section(".isr_vector"), used))
void (*const vectors[])(void) = {
	(void (*)(void))&_estack,
	Reset_Handler,
	default_handler, default_handler, default_handler, default_handler,
};
