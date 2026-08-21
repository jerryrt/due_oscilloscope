/*
 * Bare-metal CDC-ACM on UOTGHS.
 *
 * Endpoint layout matches the Arduino core so the host sees an identical
 * device:
 *   EP0  control, 64 B
 *   EP1  interrupt IN, 64 B   (ACM notification, never used)
 *   EP2  bulk OUT, 512 B, 2 banks
 *   EP3  bulk IN,  512 B, 2 banks
 *
 * The device enumerates at High Speed, so bulk endpoints are 512 bytes.
 */

#include "sam.h"
#include "usb_cdc.h"
#include "bsp.h"
#include <stdio.h>

#define EP_CTRL   0u
#define EP_ACM    1u
#define EP_OUT    2u
#define EP_IN     3u

/*
 * USB_FORCE_FS exists as a bisection aid. High Speed needs a successful
 * chirp handshake during reset; Full Speed does not. If the device
 * enumerates at FS but not at HS, the fault is in the clock or PHY setup
 * rather than in the descriptors or the control endpoint logic.
 *
 * Bulk endpoints must be 64 bytes at Full Speed and may be 512 at High
 * Speed, and the descriptors have to agree with the hardware.
 */
#ifndef USB_FORCE_FS
#define USB_FORCE_FS 0
#endif

#define EP0_SIZE  64u
#if USB_FORCE_FS
#define EPX_SIZE  64u
#else
#define EPX_SIZE  512u
#endif

#define FIFO(ep)  (((volatile uint8_t (*)[0x8000])UOTGHS_RAM_ADDR)[(ep)])

volatile uint32_t usb_reset_count;
volatile uint32_t usb_setup_count;
volatile uint32_t usb_stall_count;
volatile uint32_t usb_configured;
volatile uint32_t usb_line_state;
volatile uint32_t usb_cfg_fail;
volatile uint32_t usb_isr_count;
volatile uint32_t usb_last_devisr;
volatile uint32_t usb_last_ep0isr;
volatile uint32_t usb_devier_snap;

static uint8_t  pending_address;
static const uint8_t *ctrl_src;
static uint32_t ctrl_remaining;
static bool ctrl_active;

/* CDC line coding: 115200 8N1. Content is irrelevant to a CDC data path
 * but the host asks for it and expects seven sane bytes back. */
static uint8_t line_coding[7] = { 0x00, 0xc2, 0x01, 0x00, 0x00, 0x00, 0x08 };

/* ------------------------------------------------------------------ */
/* Descriptors                                                         */
/* ------------------------------------------------------------------ */

static const uint8_t desc_device[18] = {
	18, 1,
	0x00, 0x02,          /* USB 2.00 */
	0xef, 0x02, 0x01,    /* misc / common / IAD */
	EP0_SIZE,
	0x41, 0x23,          /* VID 0x2341, same board */
	0x3e, 0x00,          /* PID 0x003e, native port */
	0x00, 0x01,
	1, 2, 3,             /* manufacturer, product, serial */
	1
};

#define CONF_LEN 75

static const uint8_t desc_config[CONF_LEN] = {
	/* configuration */
	9, 2, CONF_LEN & 0xff, CONF_LEN >> 8, 2, 1, 0, 0xc0, 50,

	/* interface association: comm + data */
	8, 11, 0, 2, 0x02, 0x02, 0x01, 0,

	/* CDC communication interface */
	9, 4, 0, 0, 1, 0x02, 0x02, 0x01, 0,
	5, 0x24, 0x00, 0x10, 0x01,          /* header */
	5, 0x24, 0x01, 0x01, 1,             /* call management */
	4, 0x24, 0x02, 0x06,                /* ACM */
	5, 0x24, 0x06, 0, 1,                /* union */
	7, 5, 0x80 | EP_ACM, 0x03, 0x10, 0x00, 0x10,

	/* CDC data interface */
	9, 4, 1, 0, 2, 0x0a, 0, 0, 0,
	7, 5, EP_OUT,        0x02, EPX_SIZE & 0xff, EPX_SIZE >> 8, 0,
	7, 5, 0x80 | EP_IN,  0x02, EPX_SIZE & 0xff, EPX_SIZE >> 8, 0
};

static const uint8_t desc_lang[4]  = { 4, 3, 0x09, 0x04 };
static const uint8_t desc_manu[18] = { 18, 3, 'A',0,'r',0,'d',0,'u',0,'i',0,'n',0,'o',0,' ',0 };
static const uint8_t desc_prod[24] = { 24, 3, 'D',0,'u',0,'e',0,' ',0,'S',0,'c',0,'o',0,'p',0,'e',0,' ',0,'B',0 };
static const uint8_t desc_serial[10] = { 10, 3, 'B',0,'-',0,'0',0,'1',0 };

/* ------------------------------------------------------------------ */
/* EP0 helpers                                                         */
/* ------------------------------------------------------------------ */

static void ctrl_stall(void)
{
	UOTGHS->UOTGHS_DEVEPTIER[EP_CTRL] = UOTGHS_DEVEPTIER_STALLRQS;
	usb_stall_count++;
}

static void ctrl_send_chunk(void)
{
	uint32_t n = ctrl_remaining < EP0_SIZE ? ctrl_remaining : EP0_SIZE;
	volatile uint8_t *fifo = FIFO(EP_CTRL);

	for (uint32_t i = 0; i < n; i++)
		fifo[i] = ctrl_src[i];

	ctrl_src += n;
	ctrl_remaining -= n;

	UOTGHS->UOTGHS_DEVEPTICR[EP_CTRL] = UOTGHS_DEVEPTICR_TXINIC;
}

static void ctrl_send(const uint8_t *data, uint32_t len, uint32_t wlen)
{
	ctrl_src = data;
	ctrl_remaining = len < wlen ? len : wlen;
	ctrl_active = true;
	ctrl_send_chunk();
}

static void ctrl_send_zlp(void)
{
	ctrl_src = 0;
	ctrl_remaining = 0;
	ctrl_active = true;
	UOTGHS->UOTGHS_DEVEPTICR[EP_CTRL] = UOTGHS_DEVEPTICR_TXINIC;
}

/* ------------------------------------------------------------------ */
/* Endpoint configuration                                              */
/* ------------------------------------------------------------------ */

static uint32_t ep_size_field(uint32_t bytes)
{
	/* 8 -> 0, 16 -> 1, ... 512 -> 6 */
	uint32_t f = 0;
	while ((8u << f) < bytes)
		f++;
	return f;
}

static bool ep_configure(uint32_t ep, uint32_t type, uint32_t dir_in,
                         uint32_t size, uint32_t banks)
{
	UOTGHS->UOTGHS_DEVEPTCFG[ep] =
		  (ep_size_field(size) << UOTGHS_DEVEPTCFG_EPSIZE_Pos)
		| (dir_in ? UOTGHS_DEVEPTCFG_EPDIR : 0u)
		| (type << UOTGHS_DEVEPTCFG_EPTYPE_Pos)
		| ((banks - 1u) << UOTGHS_DEVEPTCFG_EPBK_Pos)
		/* NBTRANS must be at least 1 or the controller reports the
		 * configuration invalid and CFGOK never sets. */
		| (1u << UOTGHS_DEVEPTCFG_NBTRANS_Pos)
		| UOTGHS_DEVEPTCFG_ALLOC;

	/* OR, never assign: a plain write would disable every endpoint
	 * configured before this one. */
	UOTGHS->UOTGHS_DEVEPT |= UOTGHS_DEVEPT_EPEN0 << ep;

	if (!(UOTGHS->UOTGHS_DEVEPTISR[ep] & UOTGHS_DEVEPTISR_CFGOK)) {
		usb_cfg_fail++;
		return false;
	}
	return true;
}

static void configure_data_endpoints(void)
{
	/* type: 0 control, 1 isochronous, 2 bulk, 3 interrupt */
	ep_configure(EP_ACM, 3u, 1u, 64u,      2u);
	ep_configure(EP_OUT, 2u, 0u, EPX_SIZE, 2u);
	ep_configure(EP_IN,  2u, 1u, EPX_SIZE, 2u);
}

/* ------------------------------------------------------------------ */
/* Setup handling                                                      */
/* ------------------------------------------------------------------ */

static void handle_setup(void)
{
	volatile uint8_t *fifo = FIFO(EP_CTRL);
	uint8_t bmRequestType = fifo[0];
	uint8_t bRequest      = fifo[1];
	uint16_t wValue       = (uint16_t)(fifo[2] | (fifo[3] << 8));
	uint16_t wIndex       = (uint16_t)(fifo[4] | (fifo[5] << 8));
	uint16_t wLength      = (uint16_t)(fifo[6] | (fifo[7] << 8));

	(void)wIndex;
	usb_setup_count++;
	UOTGHS->UOTGHS_DEVEPTICR[EP_CTRL] = UOTGHS_DEVEPTICR_RXSTPIC;

	/* Standard device requests */
	if ((bmRequestType & 0x60) == 0x00) {
		switch (bRequest) {
		case 6: {   /* GET_DESCRIPTOR */
			uint8_t type = (uint8_t)(wValue >> 8);
			uint8_t idx  = (uint8_t)(wValue & 0xff);

			if (type == 1) {
				ctrl_send(desc_device, sizeof(desc_device), wLength);
				return;
			}
			if (type == 2) {
				ctrl_send(desc_config, sizeof(desc_config), wLength);
				return;
			}
			if (type == 3) {
				const uint8_t *s = 0;
				uint32_t n = 0;

				switch (idx) {
				case 0: s = desc_lang;   n = sizeof(desc_lang);   break;
				case 1: s = desc_manu;   n = sizeof(desc_manu);   break;
				case 2: s = desc_prod;   n = sizeof(desc_prod);   break;
				case 3: s = desc_serial; n = sizeof(desc_serial); break;
				default: break;
				}
				if (s) {
					ctrl_send(s, n, wLength);
					return;
				}
			}
			/* Device qualifier and anything else: not supported. */
			ctrl_stall();
			return;
		}
		case 5:     /* SET_ADDRESS: apply only after the status stage */
			pending_address = (uint8_t)(wValue & 0x7f);
			ctrl_send_zlp();
			return;

		case 9:     /* SET_CONFIGURATION */
			usb_configured = wValue;
			if (wValue)
				configure_data_endpoints();
			ctrl_send_zlp();
			return;

		case 8: {   /* GET_CONFIGURATION */
			static uint8_t cfg;
			cfg = (uint8_t)usb_configured;
			ctrl_send(&cfg, 1, wLength);
			return;
		}
		case 0: {   /* GET_STATUS */
			static const uint8_t st[2] = { 0, 0 };
			ctrl_send(st, 2, wLength);
			return;
		}
		default:
			break;
		}
	}

	/* CDC class requests on the communication interface */
	if ((bmRequestType & 0x60) == 0x20) {
		switch (bRequest) {
		case 0x20:  /* SET_LINE_CODING: accept the OUT data stage */
			ctrl_send_zlp();
			return;
		case 0x21:  /* GET_LINE_CODING */
			ctrl_send(line_coding, sizeof(line_coding), wLength);
			return;
		case 0x22:  /* SET_CONTROL_LINE_STATE */
			usb_line_state = wValue;
			ctrl_send_zlp();
			return;
		case 0x23:  /* SEND_BREAK */
			ctrl_send_zlp();
			return;
		default:
			break;
		}
	}

	ctrl_stall();
}

/* ------------------------------------------------------------------ */
/* Bulk IN                                                             */
/* ------------------------------------------------------------------ */

size_t usb_cdc_write(const uint8_t *data, size_t len)
{
	size_t done = 0;

	if (!usb_cdc_ready())
		return 0;

	while (done < len) {
		volatile uint8_t *fifo;
		uint32_t n;

		/*
		 * No spinning. If neither bank is free the host is not
		 * draining, and blocking here is precisely the failure that
		 * wedges the Arduino CDC path.
		 */
		if (!(UOTGHS->UOTGHS_DEVEPTISR[EP_IN] & UOTGHS_DEVEPTISR_TXINI))
			break;

		n = len - done;
		if (n > EPX_SIZE)
			n = EPX_SIZE;

		fifo = FIFO(EP_IN);
		for (uint32_t i = 0; i < n; i++)
			fifo[i] = data[done + i];

		UOTGHS->UOTGHS_DEVEPTICR[EP_IN] = UOTGHS_DEVEPTICR_TXINIC;
		UOTGHS->UOTGHS_DEVEPTIDR[EP_IN] = UOTGHS_DEVEPTIDR_FIFOCONC;

		done += n;
	}
	return done;
}

bool usb_cdc_ready(void)
{
	return usb_configured != 0 && (usb_line_state & 0x01) != 0;
}

/* ------------------------------------------------------------------ */
/* Interrupt and init                                                  */
/* ------------------------------------------------------------------ */

/*
 * Poll the same events the interrupt handles.
 *
 * Diagnostic first: if enumeration succeeds when polled but not when
 * interrupt-driven, then SETUP packets are arriving and the NVIC path is
 * at fault, which is a completely different bug from the device never
 * being addressed at all.
 *
 * It is also a legitimate implementation. Control transfers happen a few
 * dozen times at enumeration and essentially never afterwards, so
 * servicing them from the main loop costs nothing. Only the bulk path
 * needs to be fast.
 */
void usb_cdc_poll(void)
{
	uint32_t isr = UOTGHS->UOTGHS_DEVISR;

	if (isr & UOTGHS_DEVISR_EORST) {
		UOTGHS->UOTGHS_DEVICR = UOTGHS_DEVICR_EORSTC;
		usb_reset_count++;
		usb_configured = 0;
		usb_line_state = 0;
		pending_address = 0;

		/* A bus reset clears the endpoint configuration, so EP0 has to
		 * be rebuilt every time rather than only once. */
		ep_configure(EP_CTRL, 0u, 0u, EP0_SIZE, 1u);
	}

	if (!(UOTGHS->UOTGHS_DEVEPT & UOTGHS_DEVEPT_EPEN0))
		return;

	{
		uint32_t st = UOTGHS->UOTGHS_DEVEPTISR[EP_CTRL];

		if (st & UOTGHS_DEVEPTISR_RXSTPI) {
			handle_setup();
			return;
		}
		if ((st & UOTGHS_DEVEPTISR_TXINI) && ctrl_active) {
			if (ctrl_remaining) {
				ctrl_send_chunk();
			} else {
				ctrl_active = false;
				UOTGHS->UOTGHS_DEVEPTICR[EP_CTRL] =
					UOTGHS_DEVEPTICR_TXINIC;
				if (pending_address) {
					UOTGHS->UOTGHS_DEVCTRL =
						(UOTGHS->UOTGHS_DEVCTRL &
						 ~UOTGHS_DEVCTRL_UADD_Msk) |
						UOTGHS_DEVCTRL_UADD(pending_address) |
						UOTGHS_DEVCTRL_ADDEN;
					pending_address = 0;
				}
			}
			return;
		}
		if (st & UOTGHS_DEVEPTISR_RXOUTI) {
			UOTGHS->UOTGHS_DEVEPTICR[EP_CTRL] =
				UOTGHS_DEVEPTICR_RXOUTIC;
			UOTGHS->UOTGHS_DEVEPTIDR[EP_CTRL] =
				UOTGHS_DEVEPTIDR_FIFOCONC;
		}
	}
}

void UOTGHS_Handler(void)
{
	uint32_t isr = UOTGHS->UOTGHS_DEVISR;

	usb_isr_count++;
	usb_last_devisr = isr;
	usb_last_ep0isr = UOTGHS->UOTGHS_DEVEPTISR[EP_CTRL];

	if (isr & UOTGHS_DEVISR_EORST) {
		UOTGHS->UOTGHS_DEVICR = UOTGHS_DEVICR_EORSTC;
		usb_reset_count++;
		usb_configured = 0;
		usb_line_state = 0;
		pending_address = 0;

		/* EP0 must be reconfigured after every bus reset. */
		ep_configure(EP_CTRL, 0u, 0u, EP0_SIZE, 1u);
		UOTGHS->UOTGHS_DEVEPTIER[EP_CTRL] = UOTGHS_DEVEPTIER_RXSTPES;
		UOTGHS->UOTGHS_DEVIER = UOTGHS_DEVIER_PEP_0;
		usb_devier_snap = UOTGHS->UOTGHS_DEVIMR;
		/* fall through: a SETUP may already be pending */
	}

	if (isr & UOTGHS_DEVISR_PEP_0) {
		uint32_t st = UOTGHS->UOTGHS_DEVEPTISR[EP_CTRL];

		if (st & UOTGHS_DEVEPTISR_RXSTPI) {
			handle_setup();
			return;
		}
		if (st & UOTGHS_DEVEPTISR_TXINI) {
			if (ctrl_remaining) {
				ctrl_send_chunk();
			} else {
				UOTGHS->UOTGHS_DEVEPTICR[EP_CTRL] =
					UOTGHS_DEVEPTICR_TXINIC;
				UOTGHS->UOTGHS_DEVEPTIDR[EP_CTRL] =
					UOTGHS_DEVEPTIDR_TXINEC;

				/* SET_ADDRESS takes effect only now. */
				if (pending_address) {
					UOTGHS->UOTGHS_DEVCTRL =
						(UOTGHS->UOTGHS_DEVCTRL &
						 ~UOTGHS_DEVCTRL_UADD_Msk) |
						UOTGHS_DEVCTRL_UADD(pending_address) |
						UOTGHS_DEVCTRL_ADDEN;
					pending_address = 0;
				}
			}
			return;
		}
		if (st & UOTGHS_DEVEPTISR_RXOUTI) {
			/* Status stage or SET_LINE_CODING payload; discard. */
			UOTGHS->UOTGHS_DEVEPTICR[EP_CTRL] =
				UOTGHS_DEVEPTICR_RXOUTIC;
			UOTGHS->UOTGHS_DEVEPTIDR[EP_CTRL] =
				UOTGHS_DEVEPTIDR_FIFOCONC;
			return;
		}
	}
}

void usb_cdc_init(void)
{
	/* Peripheral clock, then the 480 MHz UTMI PLL that feeds the PHY. */
	PMC->PMC_PCER1 = (1u << (ID_UOTGHS - 32));

	PMC->CKGR_UCKR = CKGR_UCKR_UPLLCOUNT(3) | CKGR_UCKR_UPLLEN;
	while (!(PMC->PMC_SR & PMC_SR_LOCKU))
		{ }
	/* USBS selects the UTMI PLL rather than PLLA as the USB clock
	 * source. Without it the PHY runs off the wrong clock, the
	 * high-speed chirp fails, and the host resets the port once and
	 * then abandons it - with no error visible on the device side. */
	PMC->PMC_USB = PMC_USB_USBS | PMC_USB_USBDIV(0);
	PMC->PMC_SCER = PMC_SCER_UOTGCLK;

	/* No ID pin on this board: force device mode. */
	UOTGHS->UOTGHS_CTRL &= ~UOTGHS_CTRL_UIDE;
	UOTGHS->UOTGHS_CTRL |= UOTGHS_CTRL_UIMOD;

	UOTGHS->UOTGHS_CTRL &= ~UOTGHS_CTRL_OTGPADE;
	UOTGHS->UOTGHS_CTRL |= UOTGHS_CTRL_OTGPADE;
	UOTGHS->UOTGHS_CTRL |= UOTGHS_CTRL_USBE;
	UOTGHS->UOTGHS_CTRL &= ~UOTGHS_CTRL_FRZCLK;

	UOTGHS->UOTGHS_DEVCTRL &= ~UOTGHS_DEVCTRL_LS;
	UOTGHS->UOTGHS_DEVCTRL =
		(UOTGHS->UOTGHS_DEVCTRL & ~UOTGHS_DEVCTRL_SPDCONF_Msk)
#if USB_FORCE_FS
		| UOTGHS_DEVCTRL_SPDCONF_FORCED_FS;
#else
		| UOTGHS_DEVCTRL_SPDCONF_NORMAL;
#endif

	/* Polled for now; see usb_cdc_poll. */

	while (!(UOTGHS->UOTGHS_SR & UOTGHS_SR_CLKUSABLE))
		{ }

	UOTGHS->UOTGHS_DEVCTRL &= ~UOTGHS_DEVCTRL_DETACH;   /* attach */
}

/*
 * Live register dump. Inferring USB state from counters was a mistake:
 * a counter that stays zero cannot distinguish "not attached" from
 * "attached but silent". These are the registers that actually say.
 */
void usb_cdc_dump(void)
{
	uint32_t ctrl = UOTGHS->UOTGHS_CTRL;
	uint32_t dctl = UOTGHS->UOTGHS_DEVCTRL;
	uint32_t sr   = UOTGHS->UOTGHS_SR;

	printf("# usb CTRL=%08lx USBE=%d OTGPADE=%d FRZCLK=%d UIMOD=%d UIDE=%d\n",
	       (unsigned long)ctrl,
	       (int)!!(ctrl & UOTGHS_CTRL_USBE),
	       (int)!!(ctrl & UOTGHS_CTRL_OTGPADE),
	       (int)!!(ctrl & UOTGHS_CTRL_FRZCLK),
	       (int)!!(ctrl & UOTGHS_CTRL_UIMOD),
	       (int)!!(ctrl & UOTGHS_CTRL_UIDE));
	printf("# usb DEVCTRL=%08lx DETACH=%d SPDCONF=%lu  SR=%08lx CLKUSABLE=%d\n",
	       (unsigned long)dctl,
	       (int)!!(dctl & UOTGHS_DEVCTRL_DETACH),
	       (unsigned long)((dctl & UOTGHS_DEVCTRL_SPDCONF_Msk) >>
	                       UOTGHS_DEVCTRL_SPDCONF_Pos),
	       (unsigned long)sr,
	       (int)!!(sr & UOTGHS_SR_CLKUSABLE));
	printf("# usb DEVIMR=%08lx DEVISR=%08lx EPT=%08lx EP0CFG=%08lx EP0ISR=%08lx\n",
	       (unsigned long)UOTGHS->UOTGHS_DEVIMR,
	       (unsigned long)UOTGHS->UOTGHS_DEVISR,
	       (unsigned long)UOTGHS->UOTGHS_DEVEPT,
	       (unsigned long)UOTGHS->UOTGHS_DEVEPTCFG[0],
	       (unsigned long)UOTGHS->UOTGHS_DEVEPTISR[0]);
	printf("# pmc PMC_USB=%08lx SR_LOCKU=%d SCSR=%08lx\n",
	       (unsigned long)PMC->PMC_USB,
	       (int)!!(PMC->PMC_SR & PMC_SR_LOCKU),
	       (unsigned long)PMC->PMC_SCSR);
	uart_flush();
}
