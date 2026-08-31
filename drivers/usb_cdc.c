/*
 * Bare-metal CDC-ACM on UOTGHS.
 *
 * Two CDC-ACM functions on one cable, so the deployed board needs only
 * the native port:
 *   EP0  control, 64 B
 *   EP1  interrupt IN, 64 B   (ACM notification, never used)
 *   EP2  bulk OUT, 512 B, 2 banks   samples: host -> DAC
 *   EP3  bulk IN,  512 B, 2 banks   samples: ADC -> host
 *   EP4  interrupt IN, 64 B   (ACM notification, never used)
 *   EP5  bulk OUT, 512 B, 1 bank    commands
 *   EP6  bulk IN,  512 B, 1 bank    responses and notifications
 *
 * The first function's endpoint layout matches the Arduino core, so a
 * host that only opens the first CDC function sees the same device it
 * always did.
 *
 * The device enumerates at High Speed, so every bulk endpoint is 512
 * bytes - the USB 2.0 spec allows no other size, which is why the
 * command endpoints are not the 64 bytes their traffic would suggest.
 * They are single-banked instead: two 512-byte double-banked pairs do
 * not fit the 4096-byte DPRAM. See docs/control-protocol.md.
 */

#include "sam.h"
#include "usb_cdc.h"
#include "bsp.h"
#include "console_out.h"

#define EP_CTRL   0u
#define EP_ACM    1u
#define EP_OUT    2u
#define EP_IN     3u
#define EP_CACM   4u
#define EP_COUT   5u
#define EP_CIN    6u

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

/* The command endpoints are bulk too, so they are the same size for the
 * same reason. Only the bank count differs. */
#define EPC_SIZE  EPX_SIZE

#define FIFO(ep)  (((volatile uint8_t (*)[0x8000])UOTGHS_RAM_ADDR)[(ep)])

/* Activity counters for the front-panel LEDs: any byte moved or DMA
 * started bumps these; the main loop turns deltas into blinks. */
volatile uint32_t usb_in_activity;
volatile uint32_t usb_out_activity;
volatile uint32_t usb_out_drain_polls;

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

/*
 * The last few SETUP packets, for `u`.
 *
 * Opening this port from macOS costs about 25 s in open() and another
 * 25 s in tcsetattr(), during which the host issues SETUP after SETUP
 * and the device answers every one without stalling. Track A does not
 * do this on the same cable and the same host, so it is this stack.
 * Counting SETUPs was not enough to say which request is being retried,
 * and instrumenting the suspect region beats reasoning about it.
 */
#define SETUP_LOG_N 16u
static struct {
	uint8_t  bm, req;
	uint16_t val, idx, len;
} setup_log[SETUP_LOG_N];
static uint32_t setup_log_at;

static uint8_t  pending_address;
/*
 * Bytes of a control-OUT data stage still owed by the host.
 *
 * A control write is SETUP, then the host's data, then a zero-length IN
 * from the device as the status stage - in that order. Answering the
 * SETUP with the status ZLP straight away leaves the data stage
 * unaccepted, the transfer never completes, and the host retries.
 */
static uint32_t ctrl_out_expect;
static const uint8_t *ctrl_src;
static uint32_t ctrl_remaining;
static bool ctrl_active;

/*
 * CDC line coding: 115200 8N1, one set per function. Content is
 * irrelevant to a CDC data path but the host asks for it and expects
 * seven sane bytes back - and it asks per interface, so answering both
 * functions out of one buffer would let a tcsetattr on one port be
 * read back on the other.
 */
static uint8_t line_coding[2][7] = {
	{ 0x00, 0xc2, 0x01, 0x00, 0x00, 0x00, 0x08 },
	{ 0x00, 0xc2, 0x01, 0x00, 0x00, 0x00, 0x08 },
};

/* Which function the pending SET_LINE_CODING data stage belongs to. */
static unsigned ctrl_out_fn;

/*
 * Bytes already taken from the command endpoint's held bank. Declared
 * here rather than beside its sample-path twin because rebuilding the
 * endpoints resets it, and that happens further up the file.
 */
static uint32_t ctl_out_rd_off;

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

/*
 * Two CDC functions, four interfaces. The numbering is a contract
 * shared with Track A and pinned in docs/control-protocol.md, not an
 * implementation detail: interfaces 0 and 1 keep the numbers they have
 * always had, so a host that opens the first CDC function does not
 * notice the second one appearing.
 */
#define CONF_LEN 141

static const uint8_t desc_config[CONF_LEN] = {
	/* configuration */
	9, 2, CONF_LEN & 0xff, CONF_LEN >> 8, 4, 1, 0, 0xc0, 50,

	/* interface association: sample comm + data */
	8, 11, 0, 2, 0x02, 0x02, 0x01, 4,

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
	7, 5, 0x80 | EP_IN,  0x02, EPX_SIZE & 0xff, EPX_SIZE >> 8, 0,

	/* interface association: control comm + data */
	8, 11, 2, 2, 0x02, 0x02, 0x01, 5,

	/* CDC communication interface */
	9, 4, 2, 0, 1, 0x02, 0x02, 0x01, 0,
	5, 0x24, 0x00, 0x10, 0x01,          /* header */
	5, 0x24, 0x01, 0x01, 3,             /* call management */
	4, 0x24, 0x02, 0x06,                /* ACM */
	5, 0x24, 0x06, 2, 3,                /* union */
	7, 5, 0x80 | EP_CACM, 0x03, 0x10, 0x00, 0x10,

	/* CDC data interface */
	9, 4, 3, 0, 2, 0x0a, 0, 0, 0,
	7, 5, EP_COUT,        0x02, EPC_SIZE & 0xff, EPC_SIZE >> 8, 0,
	7, 5, 0x80 | EP_CIN,  0x02, EPC_SIZE & 0xff, EPC_SIZE >> 8, 0
};

static const uint8_t desc_lang[4]  = { 4, 3, 0x09, 0x04 };
static const uint8_t desc_manu[18] = { 18, 3, 'A',0,'r',0,'d',0,'u',0,'i',0,'n',0,'o',0,' ',0 };
static const uint8_t desc_prod[24] = { 24, 3, 'D',0,'u',0,'e',0,' ',0,'S',0,'c',0,'o',0,'p',0,'e',0,' ',0,'B',0 };
static const uint8_t desc_serial[10] = { 10, 3, 'B',0,'-',0,'0',0,'1',0 };

/*
 * iFunction on each IAD. macOS names the serial nodes from the
 * interface number rather than from these, but they are what shows the
 * two functions apart in ioreg and system_profiler, and a device that
 * cannot say which of its two ports is which is a device someone will
 * eventually open the wrong one of.
 */
static const uint8_t desc_fn_data[16] = { 16, 3, 'S',0,'a',0,'m',0,'p',0,'l',0,'e',0,'s',0 };
static const uint8_t desc_fn_ctl[16]  = { 16, 3, 'C',0,'o',0,'n',0,'t',0,'r',0,'o',0,'l',0 };

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

static void ctrl_send_zlp(void);

/*
 * EP0 OUT: either the data stage of a control write, or the status
 * stage of a control read. Only the first has anything to keep.
 */
static void ctrl_handle_out(void)
{
	volatile uint8_t *fifo = FIFO(EP_CTRL);
	bool was_data = ctrl_out_expect != 0;

	if (was_data) {
		uint32_t n = (UOTGHS->UOTGHS_DEVEPTISR[EP_CTRL] &
		              UOTGHS_DEVEPTISR_BYCT_Msk)
		           >> UOTGHS_DEVEPTISR_BYCT_Pos;

		if (n > sizeof(line_coding[0]))
			n = sizeof(line_coding[0]);
		for (uint32_t i = 0; i < n; i++)
			line_coding[ctrl_out_fn][i] = fifo[i];
		ctrl_out_expect = 0;
	}

	UOTGHS->UOTGHS_DEVEPTICR[EP_CTRL] = UOTGHS_DEVEPTICR_RXOUTIC;
	UOTGHS->UOTGHS_DEVEPTIDR[EP_CTRL] = UOTGHS_DEVEPTIDR_FIFOCONC;

	if (was_data)
		ctrl_send_zlp();
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

/*
 * Whether each bulk endpoint runs in DMA (AUTOSW) or manual-FIFO mode.
 * Owned here rather than in the caller because endpoint configuration
 * is rebuilt on every bus reset and SET_CONFIGURATION, and a rebuild
 * that forgot the mode would silently recreate the one-transfer DMA
 * stall this flag exists to prevent.
 */
/*
 * UOTGHS_DEVDMA is indexed from endpoint 1, so endpoint n uses index
 * n-1. Endpoint 0 has no DMA channel, which is fine: control transfers
 * are tiny and rare.
 */
#define DMA_IN_CH   (EP_IN  - 1u)
#define DMA_OUT_CH  (EP_OUT - 1u)

static bool dma_mode_in, dma_mode_out;

static void ep_apply_autosw(uint32_t ep, bool on);
static void ep_configure_control(void);

static void dma_channel_stop(uint32_t ch);

static void configure_data_endpoints(void)
{
	/*
	 * A transfer that was in flight when the endpoint got rebuilt is
	 * stalled for good: the bank switch it is waiting for cannot
	 * happen across a reconfiguration, and every caller here polls
	 * "is the channel still busy" before re-arming, so a stalled
	 * channel wedges that direction permanently. Stop both first and
	 * let the callers re-arm from a known state.
	 */
	dma_channel_stop(DMA_IN_CH);
	dma_channel_stop(DMA_OUT_CH);

	/* type: 0 control, 1 isochronous, 2 bulk, 3 interrupt */
	ep_configure(EP_ACM, 3u, 1u, 64u,      2u);
	ep_configure(EP_OUT, 2u, 0u, EPX_SIZE, 2u);
	ep_configure(EP_IN,  2u, 1u, EPX_SIZE, 2u);

	/*
	 * The control function, and the order matters. DPRAM is allocated
	 * in ascending endpoint order, and re-allocating one endpoint
	 * slides the next one's window up while leaving the one after it
	 * where it was - so configuring these before the sample endpoints
	 * would corrupt the sample endpoints rather than fail visibly.
	 *
	 * Sizes live in ep_configure_control() and nowhere else: the same
	 * three calls run again whenever a sample endpoint is rewritten
	 * underneath them, and two copies of a bank count would eventually
	 * disagree.
	 */
	ep_configure_control();

	ep_apply_autosw(EP_OUT, dma_mode_out);
	ep_apply_autosw(EP_IN, dma_mode_in);
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

	usb_setup_count++;
	{
		unsigned i = setup_log_at++ % SETUP_LOG_N;

		setup_log[i].bm  = bmRequestType;
		setup_log[i].req = bRequest;
		setup_log[i].val = wValue;
		setup_log[i].idx = wIndex;
		setup_log[i].len = wLength;
	}
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
				case 4: s = desc_fn_data; n = sizeof(desc_fn_data); break;
				case 5: s = desc_fn_ctl;  n = sizeof(desc_fn_ctl);  break;
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
		/*
		 * wIndex is the interface the request is aimed at, and with
		 * two functions it finally means something: 0 and 1 are the
		 * sample function, 2 and 3 the control function. Ignoring it
		 * would let opening either port raise DTR on both, and
		 * usb_cdc_ready() gates the whole sample path on that bit.
		 */
		unsigned fn = wIndex >= 2u ? 1u : 0u;

		switch (bRequest) {
		case 0x20:  /* SET_LINE_CODING: the data stage comes next */
			ctrl_out_fn = fn;
			ctrl_out_expect = wLength;
			if (!ctrl_out_expect)
				ctrl_send_zlp();
			return;
		case 0x21:  /* GET_LINE_CODING */
			ctrl_send(line_coding[fn], sizeof(line_coding[fn]),
			          wLength);
			return;
		case 0x22:  /* SET_CONTROL_LINE_STATE */
			if (fn)
				usb_ctl_line_state = wValue;
			else
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

static size_t ep_fifo_write(uint32_t ep, uint32_t epsize,
                            const uint8_t *data, size_t len)
{
	size_t done = 0;

	while (done < len) {
		volatile uint8_t *fifo;
		uint32_t n;

		/*
		 * No spinning. If no bank is free the host is not draining,
		 * and blocking here is precisely the failure that wedges the
		 * Arduino CDC path.
		 */
		if (!(UOTGHS->UOTGHS_DEVEPTISR[ep] & UOTGHS_DEVEPTISR_TXINI))
			break;

		n = len - done;
		if (n > epsize)
			n = epsize;

		fifo = FIFO(ep);
		for (uint32_t i = 0; i < n; i++)
			fifo[i] = data[done + i];

		UOTGHS->UOTGHS_DEVEPTICR[ep] = UOTGHS_DEVEPTICR_TXINIC;
		UOTGHS->UOTGHS_DEVEPTIDR[ep] = UOTGHS_DEVEPTIDR_FIFOCONC;

		done += n;
	}
	return done;
}

size_t usb_cdc_write(const uint8_t *data, size_t len)
{
	size_t done;

	if (!usb_cdc_ready())
		return 0;

	done = ep_fifo_write(EP_IN, EPX_SIZE, data, len);
	if (done)
		usb_in_activity += (uint32_t)done;
	return done;
}

/*
 * Bytes already taken from the bank currently held. The bank is a RAM
 * window, not a popping FIFO, and BYCT is fixed while the bank is held,
 * so a partial read can resume at an offset. Releasing the bank on a
 * partial read - as an earlier version did - silently discards the tail,
 * and one short packet from the host then shifts every later sample by
 * an odd byte count, which scrambles the playback channel tags.
 */
static uint32_t out_rd_off;

static size_t ep_fifo_read(uint32_t ep, uint32_t *rd_off,
                           uint8_t *dst, size_t max)
{
	uint32_t st = UOTGHS->UOTGHS_DEVEPTISR[ep];
	uint32_t byct, n;
	volatile uint8_t *fifo;

	if (!(st & UOTGHS_DEVEPTISR_RXOUTI))
		return 0;

	byct = (st & UOTGHS_DEVEPTISR_BYCT_Msk) >> UOTGHS_DEVEPTISR_BYCT_Pos;
	if (byct <= *rd_off) {
		/* Zero-length packet, or a bank already fully drained:
		 * release it and move on. */
		*rd_off = 0;
		UOTGHS->UOTGHS_DEVEPTICR[ep] = UOTGHS_DEVEPTICR_RXOUTIC;
		UOTGHS->UOTGHS_DEVEPTIDR[ep] = UOTGHS_DEVEPTIDR_FIFOCONC;
		return 0;
	}

	n = byct - *rd_off;
	if (n > max)
		n = max;

	fifo = FIFO(ep);
	for (uint32_t i = 0; i < n; i++)
		dst[i] = fifo[*rd_off + i];
	*rd_off += n;

	/* Hand the bank back only once every byte in it has been taken. */
	if (*rd_off >= byct) {
		*rd_off = 0;
		UOTGHS->UOTGHS_DEVEPTICR[ep] = UOTGHS_DEVEPTICR_RXOUTIC;
		UOTGHS->UOTGHS_DEVEPTIDR[ep] = UOTGHS_DEVEPTIDR_FIFOCONC;
	}
	return n;
}

size_t usb_cdc_read(uint8_t *dst, size_t max)
{
	size_t n = ep_fifo_read(EP_OUT, &out_rd_off, dst, max);

	usb_out_activity += (uint32_t)n;
	return n;
}

/* ------------------------------------------------------------------ */
/* Control channel                                                     */
/* ------------------------------------------------------------------ */

/*
 * The command endpoints, always manual FIFO.
 *
 * They are deliberately not on the LED activity counters: those exist to
 * show sample traffic, and a 1 Hz heartbeat blinking the same lights
 * would turn a useful indicator into a clock. Their own counters are
 * for diagnostics.
 */
volatile uint32_t usb_ctl_reallocs;
volatile uint32_t usb_ctl_in_activity;
volatile uint32_t usb_ctl_out_activity;
volatile uint32_t usb_ctl_line_state;

bool usb_ctl_ready(void)
{
	return usb_configured != 0 && (usb_ctl_line_state & 0x01) != 0;
}

size_t usb_ctl_read(uint8_t *dst, size_t max)
{
	size_t n = ep_fifo_read(EP_COUT, &ctl_out_rd_off, dst, max);

	/* Only when there is something to count. This runs on the empty
	 * path far more often than the full one, and a volatile
	 * read-modify-write is not free on a counter nobody read. */
	if (n)
		usb_ctl_out_activity += (uint32_t)n;
	return n;
}

size_t usb_ctl_write(const uint8_t *data, size_t len)
{
	size_t done;

	if (!usb_ctl_ready())
		return 0;

	done = ep_fifo_write(EP_CIN, EPC_SIZE, data, len);
	usb_ctl_in_activity += (uint32_t)done;
	return done;
}

/* ------------------------------------------------------------------ */
/* Endpoint DMA                                                        */
/* ------------------------------------------------------------------ */

/*
 * DMA needs AUTOSW: with it, the controller validates a filled IN bank
 * (and frees a drained OUT bank) by itself, which is what lets one DMA
 * transfer span many packets. Without it the DMA fills or drains the
 * first bank and then waits forever for a bank switch that never
 * comes - the exact one-transfer stall the primitives used to exhibit.
 * The manual FIFO path needs the opposite: AUTOSW off and explicit
 * FIFOCON handling. The two are per-endpoint modes, so switch
 * explicitly and never mix them on the same endpoint at the same time.
 */
/*
 * Put the control endpoints back where they belong.
 *
 * Any write to DEVEPTCFG with ALLOC set re-allocates that endpoint, and
 * the datasheet is explicit about the consequence (40.5.1.6): the x+1
 * window slides up and loses its data, while x+2 and above stay where
 * they are. Note 3 adds that re-allocating the *same* configuration is
 * harmless "as far as nothing has been written or received into" the
 * higher endpoints while it happens - which is precisely the condition
 * a control channel in use violates.
 *
 * Until this file grew a second CDC function, EP3 was the last endpoint
 * and the hazard was inert. It is not inert now, and the fix is what the
 * hardware asks for: allocate in ascending order, so re-establish
 * everything above the endpoint that moved.
 *
 * Only the control endpoints, deliberately. EP3 is also above EP2 and
 * has always been exposed to this, but it carries frames on DMA and
 * re-allocating it would disturb an armed transfer - a bigger change
 * than the defect being fixed, and one with its own history. These
 * three are manual-FIFO always, so restoring them costs nothing but a
 * frame in flight, which the parser's idle timeout already recovers.
 */
static void ep_configure_control(void)
{
	ep_configure(EP_CACM, 3u, 1u, 64u,      1u);
	ep_configure(EP_COUT, 2u, 0u, EPC_SIZE, 1u);
	ep_configure(EP_CIN,  2u, 1u, EPC_SIZE, 1u);

	/* A partly-read bank did not survive the move. */
	ctl_out_rd_off = 0;
}

static void ep_realloc_control(void)
{
	ep_configure_control();
	usb_ctl_reallocs++;
}

static void ep_apply_autosw(uint32_t ep, bool on)
{
	uint32_t cfg = UOTGHS->UOTGHS_DEVEPTCFG[ep];

	/*
	 * A write that changes nothing must not happen at all, because on
	 * this controller there is no such thing: every DEVEPTCFG write
	 * carries ALLOC and re-allocates. Most calls here are redundant -
	 * usb_dma_mode(false, false) on a stop that was already
	 * stopped - and they were paying full price for it.
	 */
	if (!!(cfg & UOTGHS_DEVEPTCFG_AUTOSW) == on)
		return;

	if (on)
		cfg |= UOTGHS_DEVEPTCFG_AUTOSW;
	else
		cfg &= ~UOTGHS_DEVEPTCFG_AUTOSW;

	/*
	 * Write with the endpoint ENABLED. Measured on this part: a
	 * DEVEPTCFG write while EPEN is clear is silently ignored - a
	 * disable-write-enable sequence read back without AUTOSW and
	 * recreated the one-transfer stall. The live write sticks and
	 * CFGOK stays set.
	 */
	UOTGHS->UOTGHS_DEVEPTCFG[ep] = cfg;
	if (!(UOTGHS->UOTGHS_DEVEPTISR[ep] & UOTGHS_DEVEPTISR_CFGOK))
		usb_cfg_fail++;

	ep_realloc_control();
}

static void dma_channel_stop(uint32_t ch)
{
	if (!(UOTGHS->UOTGHS_DEVDMA[ch].UOTGHS_DEVDMASTATUS
	      & UOTGHS_DEVDMASTATUS_CHANN_ENB))
		return;
	UOTGHS->UOTGHS_DEVDMA[ch].UOTGHS_DEVDMACONTROL = 0;
	/* The controller stops at the next packet boundary. */
	for (uint32_t spin = 0; spin < 100000u; spin++)
		if (!(UOTGHS->UOTGHS_DEVDMA[ch].UOTGHS_DEVDMASTATUS
		      & UOTGHS_DEVDMASTATUS_CHANN_ENB))
			break;
}

void usb_dma_mode_in(bool on)
{
	dma_channel_stop(DMA_IN_CH);
	dma_mode_in = on;
	ep_apply_autosw(EP_IN, on);
}

void usb_dma_mode_out(bool on)
{
	dma_channel_stop(DMA_OUT_CH);
	dma_mode_out = on;
	ep_apply_autosw(EP_OUT, on);
}

void usb_dma_mode(bool in_dma, bool out_dma)
{
	usb_dma_mode_in(in_dma);
	usb_dma_mode_out(out_dma);
}

bool usb_dma_in_busy(void)
{
	return (UOTGHS->UOTGHS_DEVDMA[DMA_IN_CH].UOTGHS_DEVDMASTATUS
	        & UOTGHS_DEVDMASTATUS_CHANN_ENB) != 0;
}

uint32_t usb_dma_in_residue(void)
{
	return (UOTGHS->UOTGHS_DEVDMA[DMA_IN_CH].UOTGHS_DEVDMASTATUS
	        & UOTGHS_DEVDMASTATUS_BUFF_COUNT_Msk)
	       >> UOTGHS_DEVDMASTATUS_BUFF_COUNT_Pos;
}

bool usb_dma_in_start(const void *buf, uint32_t len)
{
	if (!usb_cdc_ready() || len == 0)
		return false;
	if (usb_dma_in_busy())
		return false;

	UOTGHS->UOTGHS_DEVDMA[DMA_IN_CH].UOTGHS_DEVDMAADDRESS = (uint32_t)buf;
	UOTGHS->UOTGHS_DEVDMA[DMA_IN_CH].UOTGHS_DEVDMACONTROL =
		  UOTGHS_DEVDMACONTROL_BUFF_LENGTH(len)
		/* END_B_EN releases the final, possibly short, packet rather
		 * than leaving it sitting in a bank. */
		| UOTGHS_DEVDMACONTROL_END_B_EN
		| UOTGHS_DEVDMACONTROL_END_BUFFIT
		| UOTGHS_DEVDMACONTROL_CHANN_ENB;
	return true;
}

bool usb_dma_out_busy(void)
{
	return (UOTGHS->UOTGHS_DEVDMA[DMA_OUT_CH].UOTGHS_DEVDMASTATUS
	        & UOTGHS_DEVDMASTATUS_CHANN_ENB) != 0;
}

/*
 * One read of DEVDMASTATUS, decoded by the caller.
 *
 * Byte count and channel-enabled live in the same register, and reading
 * it twice asks two different instants whether the transfer finished
 * and how far it got. The answers disagree exactly when the transfer
 * ends between them, which is the moment the caller most needs them to
 * agree.
 */
uint32_t usb_dma_out_status(void)
{
	return UOTGHS->UOTGHS_DEVDMA[DMA_OUT_CH].UOTGHS_DEVDMASTATUS;
}

static bool dma_out_start_ctl(void *buf, uint32_t len, uint32_t extra)
{
	if (!usb_cdc_ready() || len == 0)
		return false;
	if (usb_dma_out_busy())
		return false;

	UOTGHS->UOTGHS_DEVDMA[DMA_OUT_CH].UOTGHS_DEVDMAADDRESS = (uint32_t)buf;
	UOTGHS->UOTGHS_DEVDMA[DMA_OUT_CH].UOTGHS_DEVDMACONTROL =
		  UOTGHS_DEVDMACONTROL_BUFF_LENGTH(len)
		| extra
		| UOTGHS_DEVDMACONTROL_END_B_EN
		| UOTGHS_DEVDMACONTROL_END_BUFFIT
		| UOTGHS_DEVDMACONTROL_CHANN_ENB;
	usb_out_activity++;
	return true;
}

bool usb_dma_out_start(void *buf, uint32_t len)
{
	/* END_TR_EN stops on a short packet, which is how a host signals
	 * the end of a transfer smaller than the buffer. Right for
	 * request/response traffic like the benches. */
	return dma_out_start_ctl(buf, len, UOTGHS_DEVDMACONTROL_END_TR_EN);
}

bool usb_dma_out_start_stream(void *buf, uint32_t len)
{
	/*
	 * No END_TR_EN: a continuous sample stream never legitimately
	 * ends, and a short packet - which host-side pacing produces
	 * whenever a write is not a multiple of 512 - must not terminate
	 * the transfer. Ending it there forced a re-arm through the main
	 * loop every couple of kilobytes, and the re-arm latency was a
	 * measured throughput ceiling. The DMA just keeps filling; the
	 * caller tracks progress through BUFF_COUNT.
	 */
	return dma_out_start_ctl(buf, len, 0);
}

void usb_cdc_detach_cycle(uint32_t ms)
{
	/*
	 * Drop the pull-up, wait, put it back: a disconnect and reconnect
	 * the host cannot tell from someone pulling the cable.
	 *
	 * This exists to answer one question about objective 0c. The host
	 * hangs in close() while this device is demonstrably draining -
	 * 145 k main-loop passes a second, a drain on every one - so it is
	 * not waiting for the device to accept data. The recorded recovery
	 * is physical: unplug and replug. If a software detach does the
	 * same, the host is waiting on the USB pipe and a wedge is
	 * recoverable without touching the cable; if it does not, the host
	 * is stuck on something no device action can reach.
	 *
	 * Commanded from the *programming* port, necessarily: detaching
	 * takes the control channel down with it, since both CDC functions
	 * are on this one device.
	 */
	uint32_t until;

	UOTGHS->UOTGHS_DEVCTRL |= UOTGHS_DEVCTRL_DETACH;
	usb_configured = 0;
	usb_line_state = 0;
	usb_ctl_line_state = 0;

	until = millis() + (ms ? ms : 250u);
	while ((int32_t)(millis() - until) < 0)
		;

	UOTGHS->UOTGHS_DEVCTRL &= ~UOTGHS_DEVCTRL_DETACH;
}

bool usb_cdc_ready(void)
{
	return usb_configured != 0 && (usb_line_state & 0x01) != 0;
}

bool usb_cdc_configured(void)
{
	return usb_configured != 0;
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
		usb_ctl_line_state = 0;
		pending_address = 0;
		out_rd_off = 0;
		ctl_out_rd_off = 0;

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
		if (st & UOTGHS_DEVEPTISR_RXOUTI)
			ctrl_handle_out();
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
		out_rd_off = 0;

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
			/* Data stage of a control write, or the status
			 * stage of a control read. */
			ctrl_handle_out();
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
	{
		unsigned n = setup_log_at < SETUP_LOG_N
		           ? setup_log_at : SETUP_LOG_N;

		con_str("# setup log, oldest first (");
		con_u32(setup_log_at); con_str(" total)"); con_nl();
		for (unsigned k = 0; k < n; k++) {
			unsigned i = (setup_log_at - n + k) % SETUP_LOG_N;

			con_str("#   bm="); con_hex32(setup_log[i].bm, 2);
			con_str(" req=");   con_hex32(setup_log[i].req, 2);
			con_str(" val=");   con_hex32(setup_log[i].val, 4);
			con_str(" idx=");   con_hex32(setup_log[i].idx, 4);
			con_str(" len=");   con_u32(setup_log[i].len);
			con_nl();
		}
		uart_flush();
	}

	uint32_t ctrl = UOTGHS->UOTGHS_CTRL;
	uint32_t dctl = UOTGHS->UOTGHS_DEVCTRL;
	uint32_t sr   = UOTGHS->UOTGHS_SR;

	con_str("# usb CTRL=");  con_hex32(ctrl, 8);
	con_str(" USBE=");       con_u32(!!(ctrl & UOTGHS_CTRL_USBE));
	con_str(" OTGPADE=");    con_u32(!!(ctrl & UOTGHS_CTRL_OTGPADE));
	con_str(" FRZCLK=");     con_u32(!!(ctrl & UOTGHS_CTRL_FRZCLK));
	con_str(" UIMOD=");      con_u32(!!(ctrl & UOTGHS_CTRL_UIMOD));
	con_str(" UIDE=");       con_u32(!!(ctrl & UOTGHS_CTRL_UIDE));
	con_nl();
	con_str("# usb DEVCTRL="); con_hex32(dctl, 8);
	con_str(" DETACH=");       con_u32(!!(dctl & UOTGHS_DEVCTRL_DETACH));
	con_str(" SPDCONF=");
	con_u32((dctl & UOTGHS_DEVCTRL_SPDCONF_Msk) >>
	        UOTGHS_DEVCTRL_SPDCONF_Pos);
	con_str("  SR=");          con_hex32(sr, 8);
	con_str(" CLKUSABLE=");    con_u32(!!(sr & UOTGHS_SR_CLKUSABLE));
	con_nl();
	con_str("# usb DEVIMR="); con_hex32(UOTGHS->UOTGHS_DEVIMR, 8);
	con_str(" DEVISR=");      con_hex32(UOTGHS->UOTGHS_DEVISR, 8);
	con_str(" EPT=");         con_hex32(UOTGHS->UOTGHS_DEVEPT, 8);
	con_str(" EP0CFG=");      con_hex32(UOTGHS->UOTGHS_DEVEPTCFG[0], 8);
	con_str(" EP0ISR=");      con_hex32(UOTGHS->UOTGHS_DEVEPTISR[0], 8);
	con_nl();
	con_str("# pmc PMC_USB="); con_hex32(PMC->PMC_USB, 8);
	con_str(" SR_LOCKU=");     con_u32(!!(PMC->PMC_SR & PMC_SR_LOCKU));
	con_str(" SCSR=");         con_hex32(PMC->PMC_SCSR, 8);
	con_nl();
	con_str("# ep2(OUT) CFG="); con_hex32(UOTGHS->UOTGHS_DEVEPTCFG[2], 8);
	con_str(" ISR=");           con_hex32(UOTGHS->UOTGHS_DEVEPTISR[2], 8);
	con_str("  ep3(IN) CFG=");  con_hex32(UOTGHS->UOTGHS_DEVEPTCFG[3], 8);
	con_str(" ISR=");           con_hex32(UOTGHS->UOTGHS_DEVEPTISR[3], 8);
	con_nl();
	/*
	 * The control function. CFGOK is the whole verification for the
	 * DPRAM budget: the controller sets it only if the requested size
	 * and bank count fit both the endpoint's maximum and the remaining
	 * DPRAM, so three ones here is the hardware agreeing that the
	 * layout in docs/control-protocol.md is affordable.
	 */
	con_str("# ep4(cACM) ok=");
	con_u32(!!(UOTGHS->UOTGHS_DEVEPTISR[EP_CACM] & UOTGHS_DEVEPTISR_CFGOK));
	con_str("  ep5(cOUT) CFG=");
	con_hex32(UOTGHS->UOTGHS_DEVEPTCFG[EP_COUT], 8);
	con_str(" ok=");
	con_u32(!!(UOTGHS->UOTGHS_DEVEPTISR[EP_COUT] & UOTGHS_DEVEPTISR_CFGOK));
	con_str("  ep6(cIN) CFG=");
	con_hex32(UOTGHS->UOTGHS_DEVEPTCFG[EP_CIN], 8);
	con_str(" ok=");
	con_u32(!!(UOTGHS->UOTGHS_DEVEPTISR[EP_CIN] & UOTGHS_DEVEPTISR_CFGOK));
	con_nl();
	con_str("# ctl ");
	con_kv_u32("dtr", !!(usb_ctl_line_state & 0x01));  con_ch(' ');
	con_kv_u32("cfgfail", usb_cfg_fail);               con_ch(' ');
	con_kv_u32("realloc", usb_ctl_reallocs);           con_ch(' ');
	con_kv_u32("in", usb_ctl_in_activity);             con_ch(' ');
	con_kv_u32("out", usb_ctl_out_activity);           con_nl();
	con_str("# dma ch1(OUT) ADDR=");
	con_hex32(UOTGHS->UOTGHS_DEVDMA[1].UOTGHS_DEVDMAADDRESS, 8);
	con_str(" CTRL=");
	con_hex32(UOTGHS->UOTGHS_DEVDMA[1].UOTGHS_DEVDMACONTROL, 8);
	con_str(" ST=");
	con_hex32(UOTGHS->UOTGHS_DEVDMA[1].UOTGHS_DEVDMASTATUS, 8);
	con_str("  ch2(IN) ADDR=");
	con_hex32(UOTGHS->UOTGHS_DEVDMA[2].UOTGHS_DEVDMAADDRESS, 8);
	con_str(" CTRL=");
	con_hex32(UOTGHS->UOTGHS_DEVDMA[2].UOTGHS_DEVDMACONTROL, 8);
	con_str(" ST=");
	con_hex32(UOTGHS->UOTGHS_DEVDMA[2].UOTGHS_DEVDMASTATUS, 8);
	con_nl();
	uart_flush();
}
