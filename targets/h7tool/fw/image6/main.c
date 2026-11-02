/* Image 6 (phase 3): image5's USB stream on the stock clock tree, with the
 * clocks measured against the host's USB SOF. PLL1 400 MHz from the 25 MHz HSE
 * (M5 N160 P2), VOS1, flash latency 4, HCLK 200 MHz, APB 100 MHz (timers 200
 * MHz) - stock V2.33's values (docs/04). If HSE or the PLL does not come up the
 * image stays on HSI and reports it; it never waits unbounded. Each 8000 SOFs
 * (1 s at high speed *(check)*) the CPU cycle counter (DWT), TIM5 (200 MHz
 * timer clock) and TIM2 (counting TIM3's update at a nominal 1 MHz) are
 * differenced; vendor request IN 0x03 returns the last window.
 * See docs/09-phase3-clocks.md. */
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
#define STREAM_BUF0  0x30001000u
#define STREAM_BUF1  (STREAM_BUF0 + STREAM_XFER)
#define FRAMES_PER_XFER 16u
#define STREAM_XFER  (FRAMES_PER_XFER * FRAME_BYTES)   /* 65536 */

#define EPENA 0x80000000u
#define CNAK  0x04000000u
#define SNAK  0x08000000u
#define USBAEP 0x8000u

static uint8_t  config_value;
static uint8_t  dtr;
static uint8_t  line_coding[7] = { 0x00, 0xC2, 0x01, 0x00, 0, 0, 8 };   /* 115200 8N1 */
static uint32_t txbuf[16];
static uint32_t m_res[8];                        /* last clock-meter window */

/* stream state */
static uint8_t  running, cur;
static uint32_t next_seq, xfers, starts;

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

/* ---- the stream --------------------------------------------------------- */

static void stream_prepare(uint32_t buf)
{
	for (unsigned f = 0; f < FRAMES_PER_XFER; f++) {
		frame_header_t *h = (frame_header_t *)(buf + f * FRAME_BYTES);
		h->magic[0] = FRAME_MAGIC0; h->magic[1] = FRAME_MAGIC1;
		h->magic[2] = FRAME_MAGIC2; h->magic[3] = FRAME_MAGIC3;
		h->version = FRAME16_VERSION;
		h->flags = 0;
		h->channel_mask = 1;
#ifdef FAULT_SKIP_SEQ                                    /* positive control for the host checker */
		if (next_seq % 5000u == 4999u) next_seq++;
#endif
		h->seq = next_seq++;
		h->sample_rate_hz = 1000000u;                    /* nominal; a test source */
		h->timestamp_us = ms_now * 1000u;
		h->overrun_count = 0;
		h->play_consumed = 0;
		h->header_crc32 = frame_crc32((const uint8_t *)h, 28);
	}
}

static void stream_arm(uint32_t buf)
{
	DIEPDMA(2) = buf;
	DIEPTSIZ(2) = ((STREAM_XFER / 512u) << 19) | STREAM_XFER;
	DIEPCTL(2) |= EPENA | CNAK;
}

static void stream_init_payload(void)
{
	for (unsigned b = 0; b < 2; b++)
		for (unsigned f = 0; f < FRAMES_PER_XFER; f++) {
			volatile uint16_t *p = (volatile uint16_t *)(STREAM_BUF0 + b * STREAM_XFER
			                                             + f * FRAME_BYTES + FRAME_HDR_BYTES);
			for (unsigned i = 0; i < FRAME_SAMPLES; i++) p[i] = (uint16_t)i;
		}
}

static void ep2_activate(void)
{
	DIEPCTL(2) = 512u | USBAEP | (2u << 18) | (2u << 22) | (1u << 28) | SNAK;
}

static void stream_start(void)
{
	next_seq = 0; cur = 0; starts++;
	stream_prepare(STREAM_BUF0);
	stream_prepare(STREAM_BUF1);
	stream_arm(STREAM_BUF0);
	running = 1;
}

static void stream_stop(void)
{
	running = 0;
	if (DIEPCTL(2) & EPENA) {
		DIEPCTL(2) |= SNAK;
		for (uint32_t n = 0x30D41; n && !(DIEPINT(2) & (1u << 6)); n--) { }
		DIEPCTL(2) |= (1u << 30) | SNAK;                 /* EPDIS */
		for (uint32_t n = 0x30D41; n && !(DIEPINT(2) & 2u); n--) { }
		DIEPINT(2) = 0xFFFFu;
	}
	GRSTCTL = (2u << 6) | 0x20u; wait_clear(&GRSTCTL, 0x20);   /* flush TX FIFO 2 */
}

static void stream_poll(void)
{
	int want = dtr && config_value == 1;
	if (want && !running) stream_start();
	else if (!want && running) stream_stop();
	if (running && (DIEPINT(2) & 1u)) {
		DIEPINT(2) = 1u;
		xfers++;
		cur ^= 1u;
		stream_arm(cur ? STREAM_BUF1 : STREAM_BUF0);
		stream_prepare(cur ? STREAM_BUF0 : STREAM_BUF1);
	}
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
	} else if ((type & 0x60) == 0x40 && (type & 0x80)) {     /* vendor IN */
		unsigned n = 0;
		if (req == 0x01) {                                   /* core id/config */
			static const uint16_t off[] = { 0x3C, 0x40, 0x44, 0x48, 0x4C, 0x50, 0x54, 0x24, 0x28 };
			for (; n < sizeof off / sizeof off[0]; n++) txbuf[n] = R32(USB + off[n]);
		} else if (req == 0x02) {                            /* stream counters */
			txbuf[n++] = next_seq; txbuf[n++] = xfers; txbuf[n++] = running;
			txbuf[n++] = ms_now;   txbuf[n++] = starts; txbuf[n++] = DIEPINT(2);
		}
		if (req == 0x03) { for (; n < 8; n++) txbuf[n] = m_res[n]; }
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
	TIM(TIM3B, 0x28) = 0; TIM(TIM3B, 0x2C) = 199;         /* 200 MHz / 200 = 1 MHz */
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

	RCC_AHB2ENR |= 7u << 29;                            /* D2 SRAM1..3 */
	(void)RCC_AHB2ENR;
	stream_init_payload();

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
			if (running) stream_stop();
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
	if (running) stream_stop();
	return_to_boot_loader();
}

static void default_handler(void) { for (;;) { } }

__attribute__((section(".isr_vector"), used))
void (*const vectors[])(void) = {
	(void (*)(void))&_estack,
	Reset_Handler,
	default_handler, default_handler, default_handler, default_handler,
};
