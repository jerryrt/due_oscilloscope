#include "ctlusb.h"

#include "Arduino.h"
#include "USB/USBAPI.h"
#include "USB/PluggableUSB.h"
#include "USB/USBDesc.h"
#include "chip.h"

#if !defined(PLUGGABLE_USB_ENABLED)
#error "the sam core was built without PluggableUSB; the second CDC function needs it"
#endif

/*
 * Single-bank, and that is a requirement rather than a preference.
 *
 * The core's EP_TYPE_BULK_IN/OUT are 512 bytes double-banked, which is
 * right for the sample endpoints and wrong here: docs/control-protocol.md
 * budgets the DPRAM and finds that 512-byte control endpoints are
 * affordable only single-banked. High speed leaves no choice about the
 * 512 itself - the USB 2.0 spec fixes high-speed bulk at 512 - so the
 * bank is the only variable, and one bank costs throughput on a channel
 * that carries a few dozen bytes a second.
 *
 * These words are the same configuration drivers/usb_cdc.c writes:
 *   ep_configure(EP_CACM, 3, 1, 64,  1)
 *   ep_configure(EP_COUT, 2, 0, 512, 1)
 *   ep_configure(EP_CIN,  2, 1, 512, 1)
 */
#define CTL_EP_TYPE_NOTIFY  (UOTGHS_DEVEPTCFG_EPSIZE_64_BYTE  | \
                             UOTGHS_DEVEPTCFG_EPDIR_IN        | \
                             UOTGHS_DEVEPTCFG_EPTYPE_INTRPT   | \
                             UOTGHS_DEVEPTCFG_EPBK_1_BANK     | \
                             UOTGHS_DEVEPTCFG_NBTRANS_1_TRANS | \
                             UOTGHS_DEVEPTCFG_ALLOC)

#define CTL_EP_TYPE_OUT     (UOTGHS_DEVEPTCFG_EPSIZE_512_BYTE | \
                             UOTGHS_DEVEPTCFG_EPTYPE_BLK      | \
                             UOTGHS_DEVEPTCFG_EPBK_1_BANK     | \
                             UOTGHS_DEVEPTCFG_NBTRANS_1_TRANS | \
                             UOTGHS_DEVEPTCFG_ALLOC)

#define CTL_EP_TYPE_IN      (UOTGHS_DEVEPTCFG_EPSIZE_512_BYTE | \
                             UOTGHS_DEVEPTCFG_EPDIR_IN        | \
                             UOTGHS_DEVEPTCFG_EPTYPE_BLK      | \
                             UOTGHS_DEVEPTCFG_EPBK_1_BANK     | \
                             UOTGHS_DEVEPTCFG_NBTRANS_1_TRANS | \
                             UOTGHS_DEVEPTCFG_ALLOC)

/*
 * The bytes, and they are a transcription rather than a construction.
 *
 * This is the second half of desc_config[] in drivers/usb_cdc.c, field
 * for field: the IAD that ties the two interfaces into one function,
 * the communication interface with its four CDC class descriptors and
 * the notify endpoint, and the data interface with bulk OUT and bulk
 * IN. docs/control-protocol.md requires the two tracks to present
 * identical descriptors, so anything computed here that is hardcoded
 * there is a divergence waiting to happen; the interface and endpoint
 * numbers are checked against the contract at registration instead.
 *
 * iFunction is 5, the same string index Track B uses, so the two
 * functions can be told apart in ioreg and Device Manager.
 */
static const uint8_t ctl_desc[] = {
	/* interface association: control comm + data */
	8, 11, 2, 2, 0x02, 0x02, 0x01, 5,

	/* CDC communication interface */
	9, 4, 2, 0, 1, 0x02, 0x02, 0x01, 0,
	5, 0x24, 0x00, 0x10, 0x01,          /* header */
	5, 0x24, 0x01, 0x01, 3,             /* call management */
	4, 0x24, 0x02, 0x06,                /* ACM */
	5, 0x24, 0x06, 2, 3,                /* union */
	7, 5, 0x80 | CTL_EP_ACM, 0x03, 0x10, 0x00, 0x10,

	/* CDC data interface */
	9, 4, 3, 0, 2, 0x0a, 0, 0, 0,
	7, 5, CTL_EP_OUT,       0x02, CTL_EP_SIZE & 0xff, CTL_EP_SIZE >> 8, 0,
	7, 5, 0x80 | CTL_EP_IN, 0x02, CTL_EP_SIZE & 0xff, CTL_EP_SIZE >> 8, 0
};

/* The interface and endpoint the contract says we must be given. */
#define CTL_FIRST_INTERFACE  2u
#define CTL_FIRST_ENDPOINT   CTL_EP_ACM

/*
 * Make the core report the IAD-composite device class.
 *
 * Track B's device descriptor is 0xEF/0x02/0x01 - misc, common class,
 * interface association - because a device carrying two CDC functions
 * has to say so before a host will honour its IADs. The core has that
 * descriptor as USB_DeviceDescriptorA and picks it only when
 * _cdcComposite is set, which USBCore does when a device-descriptor
 * request arrives with wLength == 8. That heuristic is for the
 * short-probe-then-full-read order; it is not a promise, and Windows
 * cached this board's compatible IDs as DevClass_00 - the single-CDC
 * class - which is what a second function must not enumerate under.
 *
 * The symptom was not a refused enumeration. Both nodes appeared, both
 * bound usbser, both reported Status OK - and opening the *sample* node
 * blocked for ever, because the function boundaries the host had were
 * not the ones the device meant. Track B, with the same two functions
 * and the right device class, opens both.
 *
 * Set it here rather than waiting to be asked, since by the time the
 * question is asked the answer has to be right already.
 */
extern "C" uint32_t _cdcComposite;

static bool registered;
volatile uint32_t ctlusb_reallocs;
volatile uint32_t ctlusb_cfg_fail;

class CtlUSB : public PluggableUSBModule {
public:
	CtlUSB();
	bool contracted() const;

protected:
	bool setup(USBSetup &setup);
	bool setup_inner(USBSetup &setup);
	int  getInterface(uint8_t *interfaceCount);
	int  getDescriptor(USBSetup &setup);

private:
	uint32_t eps[3];
	/* Line coding the host sets and we never act on. A CDC-ACM host
	 * expects the requests to be answered; nothing about a framed
	 * command channel depends on a baud rate. */
	uint8_t line_coding[7];
};

/*
 * Plugged from the constructor, and it has to be.
 *
 * The core's main() calls USBDevice.attach() before setup(), so a
 * module registered from the sketch is registered after the host has
 * already been told what this device is. Global constructors run from
 * __libc_init_array before main(), which is early enough, and it is
 * what the core's own HID_ does for the same reason. PluggableUSB() is
 * a function-local static, so calling it from another global's
 * constructor is ordered rather than a race.
 */
CtlUSB::CtlUSB() : PluggableUSBModule(3, 2, eps)
{
	eps[0] = CTL_EP_TYPE_NOTIFY;
	eps[1] = CTL_EP_TYPE_OUT;
	eps[2] = CTL_EP_TYPE_IN;
	line_coding[0] = 0x00; line_coding[1] = 0xc2; line_coding[2] = 0x01;
	line_coding[3] = 0x00;                      /* 115200 */
	line_coding[4] = 0; line_coding[5] = 0; line_coding[6] = 8;

	registered = PluggableUSB().plug(this) && contracted();
	if (registered)
		_cdcComposite = 1;
}

bool CtlUSB::contracted() const
{
	return pluggedInterface == CTL_FIRST_INTERFACE &&
	       pluggedEndpoint  == CTL_FIRST_ENDPOINT;
}

int CtlUSB::getInterface(uint8_t *interfaceCount)
{
	*interfaceCount += numInterfaces;
	return USBD_SendControl(0, ctl_desc, sizeof(ctl_desc));
}

/*
 * String 5, and it is not cosmetic.
 *
 * ctl_desc's IAD carries iFunction = 5, matching drivers/usb_cdc.c so
 * the two functions can be told apart in Device Manager and ioreg. On
 * Track B that string is in the device's own descriptor table. Here the
 * core owns strings, and USBD_SendDescriptor answers exactly four
 * indices - 0, IPRODUCT, IMANUFACTURER and ISERIAL - and returns false
 * for everything else.
 *
 * False is not a benign refusal on this core: USBCore answers it with
 * UDD_Stall(), which disables every other endpoint on the device (see
 * the note on ctlusb_setups below). Windows asks for string 5 about
 * 2.4 ms after configuring, so an unclaimed request here made EP1-6
 * go away with the address and _usbConfiguration untouched - which is
 * why it never looked like a bus reset.
 *
 * PluggableUSB is asked first (USBCore.cpp:397), before the core's own
 * string handling, and a positive return claims the request. So the
 * string this descriptor promises is supplied by the module that
 * promised it, and nothing stalls.
 */
static const uint8_t ctl_string5[] = {
	2 + 2 * 15, 3,
	'C',0, 'o',0, 'n',0, 't',0, 'r',0, 'o',0, 'l',0, ' ',0,
	'c',0, 'h',0, 'a',0, 'n',0, 'n',0, 'e',0, 'l',0
};

#define CTL_ISTR_FUNCTION 5u

int CtlUSB::getDescriptor(USBSetup &setup)
{
	if (setup.wValueH != 3u)                    /* STRING */
		return 0;
	if (setup.wValueL != CTL_ISTR_FUNCTION)
		return 0;

	uint32_t len = sizeof(ctl_string5);
	if (setup.wLength && len > setup.wLength)
		len = setup.wLength;
	USBD_SendControl(0, ctl_string5, len);
	return 1;
}

/*
 * Every setup packet PluggableUSB offers us, and whether we claimed it.
 *
 * USBCore answers an unclaimed class-interface request with
 * UDD_Stall(), which on this core is
 *
 *     UOTGHS->UOTGHS_DEVEPT = (UOTGHS_DEVEPT_EPEN0 << EP0);
 *
 * an assignment, not a set - so a protocol stall on EP0 disables every
 * other endpoint on the device. With one CDC function nothing ever
 * stalled and the bug was invisible. The question this ring answers is
 * which request arrives that nobody claims.
 */
volatile struct ctlusb_setup_e ctlusb_setups[CTLUSB_SETUP_N];
volatile uint32_t ctlusb_setup_n;
volatile uint32_t ctlusb_setup_drop;

static void setup_log(const USBSetup &s, uint8_t claimed)
{
	if (ctlusb_setup_n >= CTLUSB_SETUP_N) {
		ctlusb_setup_drop++;
		return;
	}
	volatile struct ctlusb_setup_e *e = &ctlusb_setups[ctlusb_setup_n];
	e->bmRequestType = s.bmRequestType;
	e->bRequest      = s.bRequest;
	e->wValue        = (uint16_t)(s.wValueL | (s.wValueH << 8));
	e->wIndex        = s.wIndex;
	e->wLength       = s.wLength;
	e->claimed       = claimed;
	ctlusb_setup_n++;
}

bool CtlUSB::setup(USBSetup &setup)
{
	bool claimed = setup_inner(setup);
	setup_log(setup, claimed ? 1 : 0);
	return claimed;
}

bool CtlUSB::setup_inner(USBSetup &setup)
{
	/*
	 * Only our own interfaces, and only class requests.
	 *
	 * PluggableUSB offers every module every setup packet until one
	 * claims it, so a module that answers on somebody else's interface
	 * silently breaks the function it stole from - here that would be
	 * the sample port, which is the one thing on this board that must
	 * not become unreliable.
	 */
	if (setup.wIndex != CTL_FIRST_INTERFACE &&
	    setup.wIndex != CTL_FIRST_INTERFACE + 1u)
		return false;
	if ((setup.bmRequestType & 0x60) != 0x20)     /* class */
		return false;

	switch (setup.bRequest) {
	case 0x21:                                    /* GET_LINE_CODING */
		USBD_SendControl(0, line_coding, sizeof(line_coding));
		return true;
	case 0x20:                                    /* SET_LINE_CODING */
		/*
		 * Read the data stage, then answer. Discarding the value is
		 * fine; skipping the transfer is not: SET_LINE_CODING carries
		 * seven bytes host-to-device, and returning true without
		 * collecting them leaves the control transfer unfinished, so
		 * the host retries the whole thing until it gives up -
		 * measured here at 60.0 s to open the command node, against
		 * milliseconds once this line existed. docs/testing.md
		 * records the same defect on the first CDC function's native
		 * port, at 51 s; it came back here because this function
		 * answers its own class requests, written from the shape of
		 * SET_CONTROL_LINE_STATE (no data stage) rather than from the
		 * core's own CDC_Setup, which does exactly this at CDC.cpp:127.
		 */
		USBD_RecvControl(line_coding, sizeof(line_coding));
		return true;
	case 0x22:                                    /* SET_CONTROL_LINE_STATE */
		return true;
	default:
		return false;
	}
}

/*
 * Put the control endpoints back after something below them moved.
 *
 * Any DEVEPTCFG write with ALLOC set re-allocates that endpoint, and
 * 40.5.1.6 says the x+1 window then slides up and loses its data while
 * x+2 and above stay put - exactly what an in-use control channel
 * cannot survive. drivers/usb_cdc.c's ep_configure_control() is the
 * model, down to which endpoints are restored: EP3 is also above EP2
 * and always exposed, but it carries frames on DMA and re-establishing
 * it would disturb an armed transfer, so only these three - always
 * manual FIFO - are restored.
 */

/*
 * Keep the control endpoints out of the core's interrupt handler.
 *
 * PluggableUSB hands the core three more endpoints and it enables their
 * interrupts with everyone else's, but USBCore's ISR has a case for
 * CDC_RX and nothing else. An OUT packet on EP5 then raises an
 * interrupt no one acknowledges: the controller holds it asserted, the
 * ISR re-enters forever, and the main loop stops running. The board
 * still enumerates, because that is all the ISR is doing, and answers
 * nothing.
 *
 * These endpoints are polled from the main loop, as drivers/usb_cdc.c
 * polls Track B's, so the interrupt is not wanted at all. The core
 * re-enables on bus reset and SET_CONFIGURATION, so this is re-applied
 * rather than done once - usbdma.cpp's keepalive has the same shape.
 */

/*
 * Superseded and uncalled. ctl_port.cpp reads this endpoint for the
 * control protocol and counts through the two variables below;
 * --gc-sections drops ctlusb_drain_out() from the image.
 *
 * It is kept because what it documents is still true of whatever drains
 * this endpoint: an allocated bulk OUT that nobody drains NAKs forever,
 * which is objective 0c's shape, and one bank per call is what keeps
 * invariant 7 - a 512-byte bank per main-loop pass is ~115 MB/s against
 * a 1.8 MB/s wire, where "drain everything that arrived" is a pass
 * whose length the peer chooses.
 */
volatile uint32_t ctlusb_out_bytes;
volatile uint32_t ctlusb_out_banks;

void ctlusb_drain_out(void)
{
	if (!registered)
		return;

	uint32_t st = UOTGHS->UOTGHS_DEVEPTISR[CTL_EP_OUT];
	if (!(st & UOTGHS_DEVEPTISR_RXOUTI))
		return;

	ctlusb_out_bytes += (st & UOTGHS_DEVEPTISR_BYCT_Msk)
	                  >> UOTGHS_DEVEPTISR_BYCT_Pos;
	ctlusb_out_banks++;

	/* Acknowledge the packet, then hand the bank back. Both, and in
	 * this order: clearing RXOUTI alone leaves the bank held. */
	UOTGHS->UOTGHS_DEVEPTICR[CTL_EP_OUT] = UOTGHS_DEVEPTICR_RXOUTIC;
	UOTGHS->UOTGHS_DEVEPTIDR[CTL_EP_OUT] = UOTGHS_DEVEPTIDR_FIFOCONC;
}

void ctlusb_quiesce_interrupts(void)
{
	if (!registered)
		return;
	UOTGHS->UOTGHS_DEVIDR = UOTGHS_DEVIDR_PEP_4
	                      | UOTGHS_DEVIDR_PEP_5
	                      | UOTGHS_DEVIDR_PEP_6;
}

void ctlusb_realloc_endpoints(void)
{
	static const struct { uint8_t ep; uint32_t cfg; } eps[] = {
		{ CTL_EP_ACM, CTL_EP_TYPE_NOTIFY },
		{ CTL_EP_OUT, CTL_EP_TYPE_OUT },
		{ CTL_EP_IN,  CTL_EP_TYPE_IN },
	};

	if (!registered)
		return;
	/* Ascending, because that is the order the controller allocates
	 * in and the only order in which this converges. */
	for (unsigned i = 0; i < sizeof(eps) / sizeof(eps[0]); i++) {
		UOTGHS->UOTGHS_DEVEPTCFG[eps[i].ep] = eps[i].cfg;
		if (!(UOTGHS->UOTGHS_DEVEPTISR[eps[i].ep] & UOTGHS_DEVEPTISR_CFGOK))
			ctlusb_cfg_fail++;
	}
	ctlusb_reallocs++;
	ctlusb_quiesce_interrupts();
}

static CtlUSB ctlusb_module;

bool ctlusb_ok(void)
{
	return registered;
}
