/* Image 28: image 17 (scope, generator, control function) with the H7-TOOL's display: a scope and generator monitor on the LCD
 * (fw/ui/h7_mon.c), the RUN LED, and screen capture over the control function (H7_OP_SCREEN, tools/h7_screen.py).
 * Build: tools/build_image.sh fw/image28 image28a fw/ui/h7_ui.c fw/ui/h7_mon.c fw/ui/h7_font.c fw/ctl_h7.c fw/mem.c
 *        ../../lib/due_shared/src/crc32.c -Ifw/ui -Ifw -I../../lib/due_shared/src -I../../lib/wire -DBUILD_ID=28 -DBL_PERCENT=0
 * The rest of this file is image 17's header and code, with ui_start() before the USB core comes up and ui_poll() last in the main loop. */
/* Image 17 also keeps bulk OUT drained when no playback runs (the Due's rule) and disables the OUT endpoint by the same procedure. Image 17: image14 with the IN endpoint disabled by the core's documented procedure (Global IN NAK, EPDIS, EPDISD). Image 14: image13 with the stream's IN endpoint stopped and re-armed reliably. Image 13 left a run ending with the endpoint's disable
 * possibly still pending (the wait was an iteration count that gave up silently); the late disable then killed the next run's first
 * transfer, ep_busy stayed set, and the unit acquired for ever with sent = 0 (seen on the bench in about 1 of 20 start/stop cycles).
 * Now the endpoint is quiesced against the clock at the end of a run and at the start of the next, and a transfer that was disabled
 * instead of completing is sent again.
 * Image 13: image12 with NO self-timed return to the boot loader (RUN_MS defaults to 0 = never; build with -DRUN_MS=n for the old
 * behaviour) and a control opcode that does the return instead (H7_OP_BOOTLOADER, body "BOOT"; reply first, restart a few ms later).
 * The vendor request OUT 0x7F remains. A hung image is recovered with the stock boot-loader enable sequence, as before.
 * Image 12 (phase 7a): image11 plus the CONTROL function on the second CDC function (EP3 interrupt, EP4 bulk,
 * DMA): the project's control frames (ctl_wire.h) served by fw/ctl_h7.c, so a host can identify the unit, configure it,
 * start and stop acquisition and playback and read every counter without the vendor requests or a DTR toggle. Acquisition
 * now runs while DTR is up OR a control RUN is set. Image 11 was: image10 with the playback guard OFF (the host enforces the swing
 * cap now, tools/h7_awg.py), 2048-byte OUT units (4 packets), an update-rate floor of 40
 * ticks (5 MS/s, the vendor's figure, unproven) and a rate-aware underrun threshold.
 * Image 10 was: image9 plus host-fed playback (vendor OUT 0x23 start with
 * prime units / 0 stop, IN 0x07 counters; the host writes DAC codes to the stream
 * port). Image 9 was: image8's two-channel acquisition plus the DAC1/VOUT
 * generator bring-up, set from the host by vendor requests: OUT 0x20 (wValue =
 * wave 0 off / 1 DC / 2 sine / 3 square / 4 ramp, wIndex = amplitude in DAC
 * codes, capped), OUT 0x21 (TIM6 period ticks, 32 bit), OUT 0x22 (centre code),
 * IN 0x06 generator state. See docs/13-phase6-generator.md. */
#include <stdint.h>
#include "frame16.h"
#include "ctl_h7.h"
#include "h7_ui.h"
#include "h7_mon.h"

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
#define RUN_MS 0u                  /* 0: no self-timed return; the host asks for the boot loader (control H7_OP_BOOTLOADER, vendor 0x7F) */
#endif
#if RUN_MS == 0
#define RUN_WINDOW_OPEN() 1
#else
#define RUN_WINDOW_OPEN() (ms_now < RUN_MS)
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
static uint32_t txbuf[32];
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

static uint32_t stall_count, stall_w0, stall_w1, last_w0, last_w1;
static void ep0_stall(void)
{
	stall_count++; stall_w0 = last_w0; stall_w1 = last_w1;
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
static uint32_t ep_q_timeouts, ep_q_gin_stop, ep_q_gin_start, ep_q_dis_stop, ep_q_dis_start, ep_q_enA_stop, ep_q_enA_start, ep_q_done_stop, ep_q_done_start;                       /* quiesce waits that expired (should stay 0) */
static uint32_t ep_aborts;                           /* transfers disabled before they completed and sent again */
static uint8_t  ctl_run;                              /* acquisition requested by a control RUN (as DTR is by the port) */
static uint32_t fin;                                  /* absolute number of the next frame to finish */
static uint32_t lost, xfers, alloc_idx, done_idx, sent_idx, tc_missed, adc_ovr, starts, ct_bad;
static uint32_t buf_slot[2];
static uint32_t slot_seq[RING_FRAMES], slot_ms[RING_FRAMES];
static uint8_t  slot_flag[RING_FRAMES];
static uint32_t tim2_base;
static uint32_t dma_err_flags, dma_err_frame, stall_seen, stall_lisr, stall_cr, stall_ndtr, stall_isr, stall_adccr, last_frame_ms;

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

static void ep2_quiesce(int at_start);
static void acq_start(void)
{
	ep2_quiesce(1);                                       /* a disable left over from the last run must not land on this run's first transfer */
	fin = 0; lost = 0; xfers = 0; alloc_idx = done_idx = sent_idx = 0; lost_since_push = 0;
	tc_missed = 0; adc_ovr = 0; ct_bad = 0; starts++;
	dma_err_flags = 0; stall_seen = 0; last_frame_ms = ms_now;
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
	/* Start every ADC inside ONE trigger period: wait until TIM3 has just wrapped, then write the ADSTARTs back to back.
	 * Two writes a microsecond apart can straddle a trigger and leave the planes one sample out of step (seen on the
	 * bench as a skew of exactly one ADC period); there is then no fixed pairing of CH1's sample j with CH2's. */
	if (nch > 1) { uint32_t quarter = period / 4u; while (TIM(TIM3B, 0x24) > quarter) { } }
	for (unsigned k = 0; k < nch; k++) ADCR(chidx[k], 0x08) |= 1u << 2;   /* ADSTART: wait for TIM3 */
	tim2_base = TIM(TIM2B, 0x24);
	running = 1;
}

/* Take the stream's IN endpoint to a known idle state, by the core's own procedure for disabling an IN endpoint: Global IN NAK first (so the
 * disable can complete whatever the host is doing), then EPDIS, then wait for EPDISD - the interrupt, not EPENA clearing - then release the
 * global NAK. Every wait is against the clock; a wait that expires is counted (ep_q_timeouts), never silent. Image 14 set SNAK and EPDIS on the endpoint
 * alone and waited for EPENA to clear: seen on the bench with EPENA and EPDIS both still set, IN tokens arriving into an empty FIFO, and the next
 * transfer armed on top of the pending disable - the unit then acquired for ever with sent = 0 (about 1 start in 100). */
static void ep2_quiesce(int at_start)
{
	if (DIEPCTL(2) & EPENA) {
		if (at_start) ep_q_enA_start++; else ep_q_enA_stop++;
		uint32_t t = ms_now;
		DCTL |= 1u << 7;                                                      /* SGINAK */
		while (!(GINTSTS & (1u << 6)) && ms_now - t < 5u) tick();             /* GINAKEFF */
		if (!(GINTSTS & (1u << 6))) { ep_q_timeouts++; if (at_start) ep_q_gin_start++; else ep_q_gin_stop++; }
		/* With the global NAK in effect no packet can complete, so EPENA is stable from here. Check it NOW, not before: a transfer that completed
		 * on its own while we waited has already cleared EPENA, and EPDIS written to an idle endpoint is never cleared by the core - it stays
		 * latched, and the next transfer is armed with EPENA and EPDIS both set (seen on the bench: tokens arriving into an empty FIFO,
		 * sent 0, for ever). */
		if (DIEPCTL(2) & EPENA) {
			DIEPCTL(2) |= (1u << 30) | SNAK;                                  /* EPDIS */
			t = ms_now;
			while (!(DIEPINT(2) & 2u) && ms_now - t < 20u) tick();            /* EPDISD */
			if (!(DIEPINT(2) & 2u)) { ep_q_timeouts++; if (at_start) ep_q_dis_start++; else ep_q_dis_stop++; }
		} else {
			if (at_start) ep_q_done_start++; else ep_q_done_stop++;           /* it finished by itself: nothing to disable */
		}
		DCTL |= 1u << 8;                                                      /* CGINAK */
	}
	DIEPINT(2) = 0xFFFFu;
	ep_busy = 0;
	GRSTCTL = (2u << 6) | 0x20u; wait_clear(&GRSTCTL, 0x20);   /* flush TX FIFO 2: nothing of the last run may be left to send */
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
	ep2_quiesce(0);
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
	int want = (dtr || ctl_run) && config_value == 1;
	if (want && !running) acq_start();
	else if (!want && running) acq_stop();
	if (!running) return;

	for (unsigned k = 0; k < nch; k++)
		if (ADCR(chidx[k], 0x00) & 0x10u) { adc_ovr++; ADCR(chidx[k], 0x00) = 0x10u; }

	for (unsigned k = 0; k < nch; k++) {
		uint32_t l = DMA_LISR(chidx[k]);
		if ((l & 0x340u) && !dma_err_flags) { dma_err_flags = l; dma_err_frame = fin; }          /* FEIF, DMEIF, TEIF of stream 1 */
	}
	if (!stall_seen && ms_now - last_frame_ms > 100u) {                                          /* no frame for 100 ms: freeze the evidence */
		stall_seen = 1; stall_lisr = DMA_LISR(chidx[0]); stall_cr = DMAR(chidx[0], 0); stall_ndtr = DMAR(chidx[0], 4);
		stall_isr = ADCR(chidx[0], 0); stall_adccr = ADCR(chidx[0], 8);
	}
	unsigned tc = 0;
	for (unsigned k = 0; k < nch; k++) tc += (DMA_LISR(chidx[k]) >> 11) & 1u;
	if (tc == nch) {                                      /* every active plane has finished a buffer */
		/* The idle buffer is the one the DMA is NOT on (CT), never a function of the frame count: if the
		 * main loop was blocked for several frames (a settle delay), parity is wrong and writing the
		 * active buffer's address makes the stream flag a transfer error and shut itself off. */
		unsigned ct = (DMAR(chidx[0], 0x00) >> 19) & 1u, b = ct ^ 1u;
		for (unsigned k = 0; k < nch; k++) DMA_LIFCR(chidx[k]) = 1u << 11;
		/* The sample ledger (TIM3 updates counted since the start) says how many frames have really
		 * completed; any beyond the one we are about to record were overwritten unseen: lost, flagged. */
		uint32_t done_by_clock = (TIM(TIM2B, 0x24) - tim2_base) / spf;
		uint32_t skipped = done_by_clock > fin + 1u ? done_by_clock - fin - 1u : 0u;
		if (skipped) { fin += skipped; lost += skipped; tc_missed += skipped; lost_since_push = 1; }
		uint32_t slot = buf_slot[b];
		if (slot == SCRAP_SLOT) { lost++; lost_since_push = 1; }
		else {
			slot_seq[slot] = fin; slot_ms[slot] = ms_now;
			slot_flag[slot] = lost_since_push; lost_since_push = 0;
			done_idx++;
		}
		fin++; last_frame_ms = ms_now;
		buffer_assign(b);                                 /* the next frame for the buffer just freed */
		if (((DMAR(chidx[0], 0x00) >> 19) & 1u) == b) ct_bad++;   /* the DMA moved onto it while we wrote: recorded, never silent */
	}

	if (ep_busy && (DIEPINT(2) & 1u)) {
		DIEPINT(2) = 1u; ep_busy = 0; sent_idx++; xfers++;
	} else if (ep_busy && (DIEPINT(2) & 2u)) {            /* EPDISD: disabled, not completed - the frame was not sent, send it again */
		DIEPINT(2) = 2u; ep_busy = 0; ep_aborts++;
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
#define GEN_MIN_PERIOD 40u                         /* 5 MS/s: the vendor's figure, being tested (docs/15) */
#define GEN_N        256u
#define GEN_TAB      ((volatile uint16_t *)0x30030000u)

static const int16_t sin_tab[256] = { 0, 804, 1608, 2410, 3212, 4011, 4808, 5602, 6393, 7179, 7962, 8739, 9512, 10278, 11039, 11793, 12539, 13279, 14010, 14732, 15446, 16151, 16846, 17530, 18204, 18868, 19519, 20159, 20787, 21403, 22005, 22594, 23170, 23731, 24279, 24811, 25329, 25832, 26319, 26790, 27245, 27683, 28105, 28510, 28898, 29268, 29621, 29956, 30273, 30571, 30852, 31113, 31356, 31580, 31785, 31971, 32137, 32285, 32412, 32521, 32609, 32678, 32728, 32757, 32767, 32757, 32728, 32678, 32609, 32521, 32412, 32285, 32137, 31971, 31785, 31580, 31356, 31113, 30852, 30571, 30273, 29956, 29621, 29268, 28898, 28510, 28105, 27683, 27245, 26790, 26319, 25832, 25329, 24811, 24279, 23731, 23170, 22594, 22005, 21403, 20787, 20159, 19519, 18868, 18204, 17530, 16846, 16151, 15446, 14732, 14010, 13279, 12539, 11793, 11039, 10278, 9512, 8739, 7962, 7179, 6393, 5602, 4808, 4011, 3212, 2410, 1608, 804, 0, -804, -1608, -2410, -3212, -4011, -4808, -5602, -6393, -7179, -7962, -8739, -9512, -10278, -11039, -11793, -12539, -13279, -14010, -14732, -15446, -16151, -16846, -17530, -18204, -18868, -19519, -20159, -20787, -21403, -22005, -22594, -23170, -23731, -24279, -24811, -25329, -25832, -26319, -26790, -27245, -27683, -28105, -28510, -28898, -29268, -29621, -29956, -30273, -30571, -30852, -31113, -31356, -31580, -31785, -31971, -32137, -32285, -32412, -32521, -32609, -32678, -32728, -32757, -32767, -32757, -32728, -32678, -32609, -32521, -32412, -32285, -32137, -31971, -31785, -31580, -31356, -31113, -30852, -30571, -30273, -29956, -29621, -29268, -28898, -28510, -28105, -27683, -27245, -26790, -26319, -25832, -25329, -24811, -24279, -23731, -23170, -22594, -22005, -21403, -20787, -20159, -19519, -18868, -18204, -17530, -16846, -16151, -15446, -14732, -14010, -13279, -12539, -11793, -11039, -10278, -9512, -8739, -7962, -7179, -6393, -5602, -4808, -4011, -3212, -2410, -1608, -804 };
static uint32_t gen_type, gen_amp, gen_center = GEN_ZERO, gen_period = 800;   /* 800 ticks = 250 kS/s */
static uint8_t  gen_on;
static uint8_t  gen_pe3 = 1;                         /* bench: 0 runs the whole chain with the supply off */

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
	if (gen_pe3) R32(GPIOE + 0x18) = 1u << 3;          /* PE3 high: stock does this first */
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
#ifndef BUILD_ID
#define BUILD_ID 0
#endif
#ifndef PLAY_GUARD
#define PLAY_GUARD 0
#endif
#define PLAY_RING    0x30038000u
#define PLAY_UNIT_BYTES 2048u                      /* 4 packets: the host must write multiples of this */
#define PLAY_UNITS   16u
#define PLAY_UNIT_SAMPLES (PLAY_UNIT_BYTES / 2u)
#define PLAY_N       (PLAY_UNITS * PLAY_UNIT_SAMPLES)   /* ring length in samples */

static uint8_t  play_on, play_timer, play_armed;
static uint32_t out_q_timeouts, out_idle_units;       /* OUT quiesce waits that expired (should stay 0); units discarded while no playback owned the endpoint */
static uint32_t play_prime = 2 * PLAY_UNIT_SAMPLES;
static uint32_t play_wr_units, play_consumed, play_last_pos, play_underruns, play_guard_trips, play_min_occ, play_resumes, play_short;

static void play_arm(void)
{
	DOEPTSIZ(2) = ((PLAY_UNIT_BYTES / 512u) << 19) | PLAY_UNIT_BYTES;
	DOEPDMA(2) = PLAY_RING + (play_wr_units % PLAY_UNITS) * PLAY_UNIT_BYTES;
	__asm volatile ("dsb sy" ::: "memory");
	DOEPCTL(2) |= EPENA | CNAK;
	play_armed = 1;
}

/* Take the bulk OUT endpoint (EP2) to a known idle state by the core's procedure, as ep2_quiesce does for the IN side: global OUT NAK, wait for it to take
 * effect, look at EPENA AGAIN (nothing can complete now), EPDIS only if still set, wait for EPDISD, release. Every wait is against the clock, every expiry
 * counted. The count-based version this replaces wrote EPDIS after one early EPENA check, which latches on an endpoint whose transfer finished meanwhile. */
static void out_quiesce(void)
{
	if (DOEPCTL(2) & EPENA) {
		uint32_t t = ms_now;
		DCTL |= 1u << 9;                                                      /* SGONAK (bit 7 is SGINAK: it NAKs every IN endpoint, EP0 included) */
		while (!(GINTSTS & (1u << 7)) && ms_now - t < 5u) tick();             /* GONAKEFF */
		if (!(GINTSTS & (1u << 7))) out_q_timeouts++;
		if (DOEPCTL(2) & EPENA) {
			DOEPCTL(2) |= (1u << 30) | SNAK;                                  /* EPDIS */
			t = ms_now;
			while (!(DOEPINT(2) & 2u) && ms_now - t < 20u) tick();            /* EPDISD */
			if (!(DOEPINT(2) & 2u)) out_q_timeouts++;
		}
		DCTL |= 1u << 10;                                                     /* CGONAK */
	}
	DOEPINT(2) = 0xFFFFu;
}

static void play_stop(void)
{
	TIM(TIM6B, 0x00) = 0;
	DAC_R(0x00) &= ~(1u << 12);
	DMA1_S5(0) &= ~1u;
	for (uint32_t n = 400000; n && (DMA1_S5(0) & 1u); n--) { }
	out_quiesce();
	play_armed = 0;
	if (play_on) { DAC_R(0x00) &= ~2u; DAC_R(0x08) = gen_center; DAC_R(0x00) &= ~1u; }
	R32(GPIOE + 0x18) = 1u << 19;                      /* PE3 low */
	play_on = 0; play_timer = 0;
}

static void play_start(uint32_t prime_units)
{
	if (gen_on) gen_stop();
	if (play_on) play_stop();
	out_quiesce();                                     /* an idle-drain transfer may be armed: take the endpoint cleanly */
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

/* The Due's rule (CLAUDE.md): a CDC device keeps draining bulk OUT when nothing owns it. Bytes the host wrote for a playback that has stopped otherwise sit in
 * its write queue, and closing the port then waits for them for ever (seen as a start that never returned: the daemon closes the stream port at every run).
 * Constant work per pass: one flag test, and when a unit has arrived one re-arm. The play ring is unused while no playback runs, so it is the scratch. */
static void out_idle_poll(void)
{
	if (play_on || config_value != 1) return;
	if (!(DOEPCTL(2) & USBAEP)) DOEPCTL(2) = 512u | USBAEP | (2u << 18) | SNAK;      /* EP2 OUT: bulk, 512 */
	if (DOEPCTL(2) & EPENA) {
		if (!(DOEPINT(2) & 1u)) return;                                               /* armed, nothing finished yet */
		DOEPINT(2) = DOEPINT(2) & 0x8001u;
		out_idle_units++;
	}
	DOEPTSIZ(2) = ((PLAY_UNIT_BYTES / 512u) << 19) | PLAY_UNIT_BYTES;
	DOEPDMA(2) = PLAY_RING;
	__asm volatile ("dsb sy" ::: "memory");
	DOEPCTL(2) |= EPENA | CNAK;
}

static void play_poll(void)
{
	if (!play_on) return;
	if (DOEPINT(2) & 1u) {
		DOEPINT(2) = DOEPINT(2) & 0x8001u;
		play_armed = 0;
		if (DOEPTSIZ(2) & 0x7FFFFu) { play_short++; play_arm(); return; }   /* short packet: not a whole unit, drop it */
		uint32_t base = PLAY_RING + (play_wr_units % PLAY_UNITS) * PLAY_UNIT_BYTES;
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
	if (play_timer && occ < 64) { TIM(TIM6B, 0x00) = 0; play_timer = 0; play_underruns++; }
	else if (!play_timer && occ >= (int32_t)play_prime) { TIM(TIM6B, 0x00) = 1; play_timer = 1; play_resumes++; }
	if (!play_armed && (uint32_t)occ + PLAY_UNIT_SAMPLES < PLAY_N - PLAY_UNIT_SAMPLES) play_arm();
}

/* ---- the control function: EP3 (interrupt, kept NAKing) and EP4 (bulk 512) -------------------------------- */
#define CTL_RX_BUF   ((volatile uint8_t *)0x30030400u)    /* 512 B, DMA target of EP4 OUT */
#define CTL_TX_BUF   ((uint8_t *)0x30030600u)             /* 512 B, DMA source of EP4 IN */
static uint8_t  ctl_tx_busy, ctl_rx_armed;
static uint32_t ctl_frames_in, ctl_frames_out, ctl_ignored;
static uint8_t  cfg_gain1, cfg_gain2, cfg_coupling = 3;

static void ctl_arm_rx(void)
{
	DOEPTSIZ(4) = (1u << 19) | 512u;
	DOEPDMA(4) = (uint32_t)CTL_RX_BUF;
	__asm volatile ("dsb sy" ::: "memory");
	DOEPCTL(4) |= EPENA | CNAK;
	ctl_rx_armed = 1;
}

static void ctl_activate(void)
{
	DIEPCTL(3) = 16u | USBAEP | (3u << 18) | (3u << 22) | SNAK;                   /* interrupt IN: present, never offered data */
	DIEPCTL(4) = 512u | USBAEP | (2u << 18) | (4u << 22) | (1u << 28) | SNAK;     /* bulk IN */
	DOEPCTL(4) = 512u | USBAEP | (2u << 18) | SNAK;                               /* bulk OUT */
	ctl_tx_busy = 0; ctl_arm_rx();
}

static void ctl_reset(void)
{
	ctl_run = 0; ctl_tx_busy = 0; ctl_rx_armed = 0;
	DIEPCTL(3) = 0; DIEPCTL(4) = 0; DOEPCTL(4) = 0;
}

static void ctl_poll(void)
{
	if (config_value != 1) return;
	if (ctl_tx_busy && (DIEPINT(4) & 1u)) { DIEPINT(4) = 1u; ctl_tx_busy = 0; }
	if (ctl_rx_armed && (DOEPINT(4) & 1u) && !ctl_tx_busy) {
		DOEPINT(4) = DOEPINT(4) & 0x8001u; ctl_rx_armed = 0;
		unsigned n = 512u - (DOEPTSIZ(4) & 0x7FFFFu);
		uint8_t rx[512];                                    /* copied out: the DMA buffer is re-armed straight away */
		for (unsigned i = 0; i < n; i++) rx[i] = CTL_RX_BUF[i];
		ctl_frames_in++;
		size_t len = ctl_h7_handle(rx, n, CTL_TX_BUF);
		if (len) {
			__asm volatile ("dsb sy" ::: "memory");
			DIEPDMA(4) = (uint32_t)CTL_TX_BUF; DIEPTSIZ(4) = (1u << 19) | (uint32_t)len;
			DIEPCTL(4) |= EPENA | CNAK; ctl_tx_busy = 1; ctl_frames_out++;
		} else ctl_ignored++;
		ctl_arm_rx();
	}
}

/* hooks for fw/ctl_h7.c */
uint32_t h7_ms(void) { return ms_now; }
uint32_t h7_us(void) { return ms_now * 1000u + ((SYST_RVR - SYST_CVR) & 0xFFFFFFu) / (cpu_hz / 1000000u); }
uint32_t h7_build_id(void) { return BUILD_ID; }
static uint8_t fe_byte(void) { return (uint8_t)((cfg_gain1 & 7u) | ((cfg_coupling & 1u) << 3) | ((cfg_gain2 & 7u) << 4) | (((cfg_coupling >> 1) & 1u) << 7)); }
void h7_get_config(h7_config_t *c)
{
	c->adc_period = period; c->dac_period = gen_period; c->chmask = (uint8_t)chmask;
	c->gain1 = cfg_gain1; c->gain2 = cfg_gain2; c->coupling = cfg_coupling; c->gen_center = (uint16_t)gen_center; c->reserved = 0;
}
int h7_set_config(const h7_config_t *c)
{
	if (running || play_on || gen_on) return -1;
	if (c->adc_period < MIN_PERIOD || c->adc_period >= 0x80000000u || c->dac_period < GEN_MIN_PERIOD || c->dac_period >= 0x10000000u ||
	    c->chmask < 1 || c->chmask > 3 || c->gain1 > 7 || c->gain2 > 7 || c->coupling > 3 ||
	    c->gen_center + GEN_LIMIT < GEN_ZERO || c->gen_center > GEN_ZERO + GEN_LIMIT) return -2;
	period = c->adc_period; TIM(TIM3B, 0x2C) = period - 1u; gen_period = c->dac_period; set_channels(c->chmask);
	cfg_gain1 = c->gain1; cfg_gain2 = c->gain2; cfg_coupling = c->coupling; gen_center = c->gen_center;
	fe_shift(fe_byte());
	return 0;
}
static uint8_t  boot_pending;
static uint32_t boot_at;
int h7_request_bootloader(void) { boot_at = ms_now + 20u; boot_pending = 1; return 1; }
int h7_run(int on) { ctl_run = (uint8_t)on; return ctl_run && config_value == 1; }
int h7_play(int cmd, unsigned prime)
{
	if (!cmd) { if (play_on) play_stop(); return 0; }
	if (config_value != 1 || prime < 1 || prime > 8) return -1;
	play_start(prime); return play_on;
}
void h7_get_status(h7_status_t *s)
{
	s->running = running; s->playing = play_on; s->play_timer = play_timer; s->chmask = (uint8_t)chmask;
	s->adc_period = period; s->dac_period = gen_period; s->frames = fin; s->lost = lost; s->sent = sent_idx; s->tc_missed = tc_missed;
	s->ct_bad = ct_bad; s->adc_ovr = adc_ovr; s->play_units = play_wr_units; s->play_consumed = play_consumed;
	s->play_underruns = play_underruns; s->play_short = play_short; s->play_min_occ = play_min_occ == 0xFFFFFFFFu ? 0 : play_min_occ;
	s->play_resumes = play_resumes; s->starts = starts; s->dma_err = dma_err_flags; s->build = BUILD_ID;
}

/* ---- control requests --------------------------------------------------- */

static void handle_setup(const uint8_t *s)
{
	last_w0 = s[0] | (s[1] << 8) | (s[2] << 16) | ((uint32_t)s[3] << 24); last_w1 = s[4] | (s[5] << 8) | (s[6] << 16) | ((uint32_t)s[7] << 24);
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
			if (config_value == 1) { ep2_activate(); ctl_activate(); }
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
	} else if ((type & 0xE0) == 0x40 && req == 0x30) {       /* vendor OUT bench: PE3 alone (1 high, 0 low) */
		R32(GPIOE + 0x18) = val & 1u ? (1u << 3) : (1u << 19);
		ep0_status_in(); return;
	} else if ((type & 0xE0) == 0x40 && req == 0x33) {       /* vendor OUT bench: generator uses PE3 (1) or not (0) */
		gen_pe3 = val & 1u; ep0_status_in(); return;
	} else if ((type & 0xE0) == 0x40 && req == 0x7F && val == 0x5AA5) {   /* vendor OUT: return to the boot loader now (bench convenience) */
		if (running) acq_stop();
		if (gen_on) gen_stop();
		if (play_on) play_stop();
		ep0_status_in();
		delay_ms(5);
		return_to_boot_loader();
	} else if ((type & 0xE0) == 0x40 && req == 0x23) {       /* vendor OUT: playback start (wValue = prime units 1..8) / stop (0) */
		if (val == 0) { if (play_on) play_stop(); ep0_status_in(); return; }
		if (val <= 8 && config_value == 1) { play_start(val); ep0_status_in(); return; }
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
		if (req == 0x08) {                               /* USB/stream debug */
			txbuf[n++] = ep_busy; txbuf[n++] = done_idx; txbuf[n++] = sent_idx; txbuf[n++] = DIEPCTL(2);
			txbuf[n++] = DIEPTSIZ(2); txbuf[n++] = DIEPINT(2); txbuf[n++] = GINTSTS; txbuf[n++] = DOEPCTL(2);
			txbuf[n++] = DOEPINT(2); txbuf[n++] = R32(USB + 0x1C); txbuf[n++] = R32(USB + 0x818);   /* GRXSTSR, DAINT */
			txbuf[n++] = DMA_LISR(1); txbuf[n++] = DMAR(1, 0); txbuf[n++] = DMAR(1, 4); txbuf[n++] = ADCR(1, 0); txbuf[n++] = ADCR(1, 8);
			txbuf[n++] = fin; txbuf[n++] = alloc_idx;
			txbuf[n++] = ms_now; txbuf[n++] = last_frame_ms; txbuf[n++] = running; txbuf[n++] = dtr; txbuf[n++] = SYST_CSR; txbuf[n++] = stall_seen;
			txbuf[n++] = DMAR(1, 8); txbuf[n++] = DMAR(1, 0xC); txbuf[n++] = DMAR(1, 0x10); txbuf[n++] = buf_slot[0]; txbuf[n++] = buf_slot[1]; txbuf[n++] = BUILD_ID; txbuf[n++] = ep_q_timeouts; txbuf[n++] = ep_aborts; txbuf[n++] = ep_q_gin_stop; txbuf[n++] = ep_q_gin_start; txbuf[n++] = ep_q_dis_stop; txbuf[n++] = ep_q_dis_start; txbuf[n++] = ep_q_enA_stop; txbuf[n++] = ep_q_enA_start; txbuf[n++] = ep_q_done_stop; txbuf[n++] = ep_q_done_start; txbuf[n++] = out_q_timeouts; txbuf[n++] = out_idle_units;
		}
		if (req == 0x07) {                               /* playback counters */
			txbuf[n++] = play_wr_units; txbuf[n++] = play_consumed; txbuf[n++] = play_underruns; txbuf[n++] = play_guard_trips;
			txbuf[n++] = play_on; txbuf[n++] = play_timer; txbuf[n++] = play_min_occ; txbuf[n++] = play_resumes;
			txbuf[n++] = play_wr_units * PLAY_UNIT_SAMPLES - play_consumed; txbuf[n++] = play_short;
			txbuf[n++] = stall_count; txbuf[n++] = stall_w0; txbuf[n++] = stall_w1;
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
			txbuf[n++] = dma_err_flags; txbuf[n++] = dma_err_frame; txbuf[n++] = stall_seen; txbuf[n++] = stall_lisr; txbuf[n++] = stall_cr; txbuf[n++] = stall_ndtr; txbuf[n++] = stall_isr; txbuf[n++] = stall_adccr;
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

/* ---- the display (image 28): scope and generator monitor, screen capture, RUN LED ----------------------------------------------
 * The monitor reads counters and configuration through h7_get_status()/h7_get_config(), never the sample stream. One step of a few tens of
 * microseconds per main-loop pass (fw/ui/h7_mon.h), and the RUN LED written one bus edge per pass (h7ui_led_async), because a blocking
 * LED write or a whole row at once costs frames at the top sample rate; the blit runs on DMA2 stream 3, which neither the ADCs (DMA1 stream 1, DMA2 stream 1) nor the generator
 * (DMA1 stream 5) use. Memory: the line buffer and the pixel scratch in SRAM3, the capture shadow in AXI SRAM. */
#define UI_LINEBUF   ((uint8_t *)0x30040000u)               /* H7MON_LINE_BYTES (7680) */
#define UI_SCRATCH   ((uint8_t *)0x30042000u)               /* 2 bytes */
#define UI_SHADOW    ((uint8_t *)0x24010000u)               /* H7LCD_W * H7LCD_H * 2 = 153,600 */
#define UI_RUN_LEVEL 0x20u

static void ui_delay_us(uint32_t us)
{
	uint32_t start = DWT_CYCCNT, n = us * (cpu_hz / 1000000u);
	while (DWT_CYCCNT - start < n) { }
}

const uint8_t *h7_screen(uint16_t *w, uint16_t *h, uint32_t *d)
{
	if (!h7ui_shadow()) return 0;
	*w = H7LCD_W; *h = H7LCD_H; *d = h7ui_draw_count();
	return h7ui_shadow();
}

static uint8_t ui_run_led = 0xFF;                           /* what the LED was last told; 0xFF = not yet */

static uint32_t ui_now_us(void) { return DWT_CYCCNT / (cpu_hz / 1000000u); }

static void ui_start(void)
{
	h7ui_set_delay(ui_delay_us);
	h7ui_set_clock(ui_now_us);
	h7ui_set_shadow(UI_SHADOW);
	h7ui_set_dma_scratch(UI_SCRATCH);
	if (h7ui_expander_init()) h7ui_backlight(0xFF);
	h7lcd_init();
	h7lcd_fill_dma(0, 0, H7LCD_W, H7LCD_H, 0);              /* the shadow matches the glass from here on */
	h7mon_init(UI_LINEBUF);
}


static void ui_poll(void)
{
	h7_status_t s; h7_config_t c; h7mon_info_t i;
	h7_get_status(&s); h7_get_config(&c);
	i.running = s.running; i.playing = s.playing; i.chmask = c.chmask; i.gain1 = c.gain1; i.gain2 = c.gain2; i.coupling = c.coupling;
	i.adc_period = s.adc_period; i.dac_period = s.dac_period;
	i.frames = s.frames; i.lost = s.lost; i.sent = s.sent; i.tc_missed = s.tc_missed; i.ct_bad = s.ct_bad; i.adc_ovr = s.adc_ovr;
	i.play_units = s.play_units; i.play_consumed = s.play_consumed; i.play_underruns = s.play_underruns; i.play_short = s.play_short;
	i.play_min_occ = s.play_min_occ; i.play_resumes = s.play_resumes; i.uptime_ms = ms_now; i.build = BUILD_ID;
	h7mon_poll(&i);
	uint8_t want = (s.running || s.playing) ? UI_RUN_LEVEL : 0;
	if (want != ui_run_led && h7ui_led_async(H7UI_LED_RUN, want)) ui_run_led = want;   /* queued; one bus edge per pass below */
	h7ui_i2c_poll();
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

	ui_start();                                          /* about 0.35 s; before the USB core is up, so enumeration waits for it instead of being stalled by it */

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
	while (RUN_WINDOW_OPEN()) {
		tick();
		if (boot_pending && (int32_t)(ms_now - boot_at) >= 0) break;     /* the reply to H7_OP_BOOTLOADER has had its time to leave */
		uint32_t sts = GINTSTS;
		if (sts & (1u << 12)) {                         /* USBRST */
			if (running) acq_stop();
			if (play_on) play_stop();
			ctl_reset();
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
		out_idle_poll();
		ctl_poll();
		meter_poll();
		ui_poll();
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
