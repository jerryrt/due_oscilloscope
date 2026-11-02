/* Image 4 (USB phase 1a): enumerate as a composite device of two CDC-ACM
 * functions (stream, control), serving endpoint 0 by polling. No data
 * endpoints yet. VID/PID is the bench test pair; the serial is the chip UID.
 * Vendor request IN 0xC0/0x01 returns the OTG_HS id/config registers (phase 1
 * gate: sizing from the chip). Clocks stay at reset (HSI 64 MHz); returns to
 * the boot loader after RUN_MS. Register sequence is stock V2.33's (docs/04). */
#include <stdint.h>

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
#define CPU_HZ       64000000u

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

/* ---- endpoint 0 ------------------------------------------------------- */

static uint8_t  config_value;
static uint8_t  line_coding[7] = { 0x00, 0xC2, 0x01, 0x00, 0, 0, 8 };   /* 115200 8N1 */
static uint32_t txbuf[16];                                              /* vendor reply */

static void ep0_arm_out(unsigned len)
{
	DOEPTSIZ(0) = (3u << 29) | (1u << 19) | len;
	DOEPCTL(0) |= 0x80000000u | 0x04000000u;                 /* EPENA | CNAK */
}

static void tick(void)
{
	if (SYST_CSR & 0x10000u) ms_now++;                       /* COUNTFLAG */
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
	DIEPTSIZ(0) = (1u << 19) | n;
	DIEPCTL(0) |= 0x80000000u | 0x04000000u;
	for (unsigned i = 0; i < n; i += 4) {
		uint32_t w = 0;
		for (unsigned k = 0; k < 4 && i + k < n; k++) w |= (uint32_t)p[i + k] << (8 * k);
		R32(USB + 0x1000) = w;
	}
	ep0_wait_in_done();
}

/* Data stage IN: at most `want` bytes, then a short packet or ZLP as needed. */
static void ep0_send(const uint8_t *p, unsigned len, unsigned want)
{
	unsigned total = len < want ? len : want;
	unsigned off = 0;
	ep0_arm_out(64);                                         /* for the status OUT */
	do {
		unsigned n = total - off > 64 ? 64 : total - off;
		ep0_send_packet(p + off, n);
		off += n;
		if (n < 64) return;
	} while (off < total);
	if (total < want) ep0_send_packet(p, 0);                 /* exact multiple of 64 */
}

static void ep0_status_in(void)
{
	ep0_send_packet(0, 0);
}

static void ep0_stall(void)
{
	DIEPCTL(0) |= 1u << 21; DOEPCTL(0) |= 1u << 21;
}

/* Pop the OUT data stage of a control-OUT request (<= 64 bytes). */
static unsigned ep0_recv(uint8_t *out)
{
	unsigned got = 0;
	uint32_t t = ms_now;
	ep0_arm_out(64);
	while (ms_now - t < 100u) {
		tick();
		if (GINTSTS & (1u << 4)) {
			uint32_t v = R32(USB + 0x20);
			unsigned bcnt = (v >> 4) & 0x7FF, st = (v >> 17) & 0xF;
			if (st == 2) {
				for (unsigned i = 0; i < bcnt; i += 4) {
					uint32_t w = R32(USB + 0x1000);
					for (unsigned k = 0; k < 4 && i + k < bcnt && got + i + k < 64; k++)
						out[got + i + k] = (uint8_t)(w >> (8 * k));
				}
				got += bcnt;
			}
			if (st == 3) break;
		}
	}
	return got;
}

static void handle_setup(const uint8_t *s)
{
	uint8_t  type = s[0], req = s[1];
	uint16_t val = s[2] | (s[3] << 8), idx = s[4] | (s[5] << 8), len = s[6] | (s[7] << 8);
	(void)idx;
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
			ep0_status_in(); ep0_arm_out(24); return;
		case 0x09:                                           /* SET_CONFIGURATION */
			config_value = val & 0xFF;
			ep0_status_in(); ep0_arm_out(24); return;
		case 0x08: tmp[0] = config_value; ep0_send(tmp, 1, len); return;
		case 0x00: tmp[0] = tmp[1] = 0; ep0_send(tmp, 2, len); return;
		case 0x0A: tmp[0] = 0; ep0_send(tmp, 1, len); return;
		case 0x01: case 0x03: case 0x0B:                     /* CLEAR/SET_FEATURE, SET_INTERFACE */
			ep0_status_in(); ep0_arm_out(24); return;
		}
	} else if ((type & 0x60) == 0x20) {                      /* class (CDC) */
		switch (req) {
		case 0x20:                                           /* SET_LINE_CODING */
			if (ep0_recv(tmp) >= 7) for (unsigned i = 0; i < 7; i++) line_coding[i] = tmp[i];
			ep0_status_in(); ep0_arm_out(24); return;
		case 0x21: ep0_send(line_coding, 7, len); return;    /* GET_LINE_CODING */
		case 0x22: ep0_status_in(); ep0_arm_out(24); return; /* SET_CONTROL_LINE_STATE */
		}
	} else if ((type & 0x60) == 0x40 && req == 0x01 && (type & 0x80)) {   /* vendor: core id/config */
		static const uint16_t off[] = { 0x3C, 0x40, 0x44, 0x48, 0x4C, 0x50, 0x54, 0x24, 0x28 };
		for (unsigned i = 0; i < sizeof off / sizeof off[0]; i++) txbuf[i] = R32(USB + off[i]);
		ep0_send((const uint8_t *)txbuf, sizeof off / sizeof off[0] * 4, len); return;
	}
	ep0_stall();
	ep0_arm_out(24);
}

void Reset_Handler(void)
{
	uint32_t *s = &_sidata, *d = &_sdata;
	while (d < &_edata) *d++ = *s++;
	for (d = &_sbss; d < &_ebss; ) *d++ = 0;

	SYST_RVR = CPU_HZ / 1000u - 1u;
	SYST_CSR = 5u;

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

	/* FIFO layout (stock: RX 363 words; TX 16/256/128/256 words, then 1-word FIFOs) */
	GRXFSIZ = 0x0000016Bu;
	DIEPTXF0 = 0x0010016Bu;
	DIEPTXF(1) = 0x0100017Bu; DIEPTXF(2) = 0x0080027Bu; DIEPTXF(3) = 0x010002FBu;
	for (unsigned i = 4; i <= 8; i++) DIEPTXF(i) = 0x00010000u | (0x3FBu + (i - 4));

	/* HAL_PCD_Start: connect (polling: GINTMSK stays 0, GINTSTS is read directly) */
	GAHBCFG |= 1u;
	PCGCCTL &= ~3u;
	DCTL &= ~2u;

	uint8_t setup[8];
	int have_setup = 0;
	while (ms_now < RUN_MS) {
		tick();
		uint32_t sts = GINTSTS;
		if (sts & (1u << 12)) {                         /* USBRST */
			DCTL &= ~1u;
			flush_fifos();
			for (unsigned i = 0; i < 8; i++) {
				DIEPINT(i) = 0xFB7F; DOEPINT(i) = 0xFB7F;
				DIEPCTL(i) |= 0x08000000u; DOEPCTL(i) |= 0x08000000u;
			}
			DCFG &= ~0x7F0u;                            /* address 0 */
			config_value = 0;
			ep0_arm_out(24);
			GINTSTS = 0x1000u;
		}
		if (sts & (1u << 13)) {                         /* ENUMDNE */
			DIEPCTL(0) &= ~0x7FFu;                      /* EP0 MPS = 64 */
			DCTL |= 0x100u;
			GUSBCFG = (GUSBCFG & ~0x3C00u) | 0x2400u;   /* TRDT = 9 */
			GINTSTS = 0x2000u;
		}
		if (sts & (1u << 4)) {                          /* RXFLVL */
			uint32_t v = R32(USB + 0x20);
			unsigned bcnt = (v >> 4) & 0x7FF, st = (v >> 17) & 0xF;
			if (st == 6) {                              /* SETUP packet received */
				uint32_t w0 = R32(USB + 0x1000), w1 = R32(USB + 0x1000);
				for (unsigned k = 0; k < 4; k++) {
					setup[k] = (uint8_t)(w0 >> (8 * k)); setup[4 + k] = (uint8_t)(w1 >> (8 * k));
				}
			} else if (st == 2) {                       /* stray OUT data: drop */
				for (unsigned i = 0; i < bcnt; i += 4) (void)R32(USB + 0x1000);
			} else if (st == 4) {                       /* SETUP stage done */
				have_setup = 1;
			}
		}
		if (have_setup) {
			have_setup = 0;
			DOEPINT(0) = 0x8u;                          /* STUP */
			handle_setup(setup);
		}
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
