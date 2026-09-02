/*
 * The debug console's application layer. See console.h for why it is
 * here and console_port.h for the two functions it needs from a track.
 *
 * Nothing in this file touches a register or names a driver. What it
 * knows is which letters are commands, what arguments they take, what
 * the help says, and what to do with a letter this track has not got.
 */

#include <stddef.h>
#include <stdio.h>

#include "console.h"
#include "console_port.h"
#include "console_out.h"
#include "ctl.h"        /* CTL_VERSION */
#include "frame.h"      /* FRAME_VERSION, FRAME_BYTES/SAMPLES */
#include "fw_git_rev.h" /* FW_GIT_REV */
#include "fw_version.h" /* FW_VERSION_STR */

/*
 * The command surface. One definition, both tracks. Order is the
 * help's order, so this list is also the document; group by what a
 * command is for rather than by letter.
 *
 * `syntax` is the "=" prefix a command takes, or NULL for one that
 * takes none - printed rather than parsed, since the parser accepts up
 * to CONSOLE_NARGS numbers before any letter regardless of which
 * command follows.
 *
 * No number in the help text is computed: the rate a preset asks for
 * is a fact about that track's acq.h, which this file cannot reach, so
 * `5` says "max in-spec" and each track's banner prints the figure
 * next to its own clocks where it can.
 */
struct cmd_entry {
	char        key;
	const char *syntax;
	const char *help;
};

static const struct cmd_entry table[] = {
	/* Identity and cost of the console itself. */
	{ 'h', NULL,        "help - this list" },
	{ 'v', NULL,        "identity line (track, versions, clocks, build)" },
	{ 'p', NULL,        "printf cost per 40-char line" },
	{ 'g', NULL,        "GPIO toggle cost" },
	{ 'f', NULL,        "trigger a fault, to prove the handler" },

	/* One-shot analog measurements. */
	{ 'r', NULL,        "read A0/A1 once" },
	{ 's', NULL,        "DAC sweep into the ADC" },
	{ 'x', "=<n>,<ms>", "multiplexer bleed, n observations, ms settle" },
	{ 'd', NULL,        "DAC max update-rate sweep" },
	{ 'j', NULL,        "DAC 1.5 MHz independent + capture 200k" },
	{ 'k', NULL,        "DAC 3.0 MHz independent + capture 200k" },
	{ 't', "=,,<nch>", "trigger-rate sweep (TC+ADC+PDC)" },

	/* Streaming. */
	{ '1', NULL,        "stream 50k sps" },
	{ '2', NULL,        "stream 100k sps" },
	{ '3', NULL,        "stream 200k sps" },
	{ '4', NULL,        "stream 400k sps" },
	{ '5', NULL,        "stream at the max in-spec rate" },
	{ '0', NULL,        "stop everything" },
	{ '?', NULL,        "stream stats" },
	{ 'w', NULL,        "stream over the UART" },
	{ 'u', NULL,        "USB registers and counters" },
	{ 'E', NULL,        "endpoint state, readable during a stream" },

	/* Transport benchmarks. */
	{ 'F', NULL,        "bench: flood IN" },
	{ 'R', NULL,        "bench: sink OUT" },
	{ 'X', NULL,        "bench: duplex" },
	{ 'G', NULL,        "bench: flood IN via endpoint DMA" },
	{ 'T', NULL,        "bench: sink OUT via endpoint DMA" },
	{ 'Y', NULL,        "bench: duplex via endpoint DMA" },
	{ 'B', NULL,        "bench and playback counters" },

	/* The loop, and the playback ring. */
	{ 'L', "=<dac>,<adc>,<nch>", "full loop HOST->DAC->ADC->HOST" },
	{ 'P', "=<dac>,<adc>,<nch>", "play only" },
	{ 'M', "=<dac>,<adc>",       "mimic loop, no USB in the path" },
	{ 'V', NULL,        "playback ring dump" },
	{ 'D', NULL,        "loop diagnostic" },
	{ 'O', NULL,        "playback ring occupancy histogram" },

	/* The internal generator. */
	{ 'W', "=<shape>,<pts>,<amp>",
	       "waveform: 0 sine 1 square 2 ramp 3 triangle 4 dc;"
	       " pts 2..256; amp 1..256" },
	{ 'J', "=<mode>,<amp>",
	       "sync: 0 off 1 per-cycle 2 per-wrap 3 solo" },
	{ 'N', "=<n>",      "gen layout: 0 normal 1 swapped 2 two-cycle 3 dc" },
	{ 'I', "=<ch>,<core>", "DACC_ACR output bias (2,1 = the Arduino core's)" },

	/* Acquisition settings. */
	{ 'C', "=<n>",      "2ch pair: 1 = A0+A1, 2 = A0+A2" },
	{ 'e', "=<n>",      "on-die temperature sensor, n conversions averaged" },
	{ 'A', "=<tt>,<st>", "ADC track/settling time, at the next stream" },

	/* Instrumentation and recovery. */
	{ 'Q', NULL,        "main-loop profile" },
	{ 'l', "=1",        "main-loop load; =1 reports then clears" },
	{ 'S', "=<ms>",     "stall the loop, to validate l" },
	{ 'K', "=<us>",     "M's ADC-start-to-DAC-start gap" },
	{ 'Z', "=<ms>",     "detach the native port (software unplug)" },
	{ 'z', NULL,        "software reset (leaves USB attached; see Z)" },
	{ 'q', "=<4..6>",   "flash wait states; issue #5's fetch-timing arm" },
};

#define TABLE_N  (sizeof(table) / sizeof(table[0]))

/* ------------------------------------------------------------------ */

/* The table entry for a key, or NULL. One scan answers both "is this a
 * command at all" and "what does it take", which the refusal path needs
 * together. */
static const struct cmd_entry *entry_of(char key)
{
	unsigned i;

	for (i = 0; i < TABLE_N; i++)
		if (table[i].key == key)
			return &table[i];
	return NULL;
}

static console_fn bound(char key)
{
	const console_binding_t *b;

	for (b = console_bindings; b->key; b++)
		if (b->key == key)
			return b->fn;
	return NULL;
}

/* ------------------------------------------------------------------ */

/*
 * One line of help. Written with the pieces rather than snprintf so
 * this file needs no stdio: it is compiled into both a bare-metal image
 * and an Arduino sketch, and the cheapest way to be sure the two agree
 * about formatting is to do no formatting.
 */
static void help_line(const char *syntax, char key, const char *text,
                      bool here)
{
	char k[2];

	k[0] = key;
	k[1] = 0;

	console_write(here ? "#   " : "#   -");
	if (syntax)
		console_write(syntax);
	console_write(k);
	console_write(" = ");
	console_write(text);
	console_write(here ? "\n" : " [not on this track]\n");
}

void console_help(void)
{
	unsigned i;

	for (i = 0; i < TABLE_N; i++) {
		/* A command this track has not got is listed and marked,
		 * not hidden - hiding it would make the two boards answer
		 * `h` with different lists. */
		help_line(table[i].syntax, table[i].key, table[i].help,
		          bound(table[i].key) != NULL);
	}
	/* The parity line closes the list, in a fixed format a host can
	 * parse. */
	console_missing();
}

void console_missing(void)
{
	unsigned i;
	unsigned n = 0;

	console_write("# not implemented on this track:");
	for (i = 0; i < TABLE_N; i++) {
		char k[2];

		if (bound(table[i].key))
			continue;
		k[0] = table[i].key;
		k[1] = 0;
		console_write(" ");
		console_write(k);
		n++;
	}
	if (!n)
		console_write(" none");
	console_write("\n");
	console_flush();
}

/* ------------------------------------------------------------------ */

static uint32_t arg[CONSOLE_NARGS];
static unsigned arg_idx;
static bool     arg_entry;

/*
 * "=<a>[,<b>[,<c>]]" typed before a command letter.
 *
 * The '=' introducer is what keeps bare digits working as the stream
 * presets: while an entry is open, digits and commas are argument text,
 * and the next command letter consumes them and closes it.
 *
 * Digits past CONSOLE_NARGS commas are dropped rather than overflowing
 * the array - invariant 7 wants a bounded worst case that does not
 * depend on what arrives, and a host holding down the comma key is
 * exactly the input that must cost nothing.
 */
void console_feed(int c)
{
	const struct cmd_entry *e;
	console_fn fn;

	/*
	 * A track's "nothing arrived" is a negative value from its UART
	 * read, and it is fed here unconditionally so that the main loop
	 * has one call rather than a test around it. It must not close an
	 * open argument entry: a user types "=200000" and "L" as two
	 * separate keystrokes with thousands of empty polls between them.
	 */
	if (c < 0)
		return;

	if (c == '=') {
		unsigned i;

		for (i = 0; i < CONSOLE_NARGS; i++)
			arg[i] = 0;
		arg_idx = 0;
		arg_entry = true;
		return;
	}
	if (arg_entry && c >= '0' && c <= '9') {
		if (arg_idx < CONSOLE_NARGS)
			arg[arg_idx] = arg[arg_idx] * 10u + (uint32_t)(c - '0');
		return;
	}
	if (arg_entry && c == ',') {
		if (arg_idx < CONSOLE_NARGS)
			arg_idx++;
		return;
	}
	arg_entry = false;

	fn = bound((char)c);
	if (fn) {
		fn(arg);
	} else if ((e = entry_of((char)c)) != NULL) {
		/*
		 * The console's CTL_ERR_OPCODE: a command the track has not
		 * got must say so rather than answer with nothing, since
		 * nothing is indistinguishable from a command that ran and
		 * printed no output. Silence stays the answer for a letter
		 * that is not a command at all, which is what makes stray
		 * CR, LF and spaces free.
		 */
		char k[2];

		k[0] = (char)c;
		k[1] = 0;
		console_write("# ");
		console_write(k);
		console_write(": not implemented on this track (");
		console_write(e->syntax ? e->syntax : "no args");
		console_write(")\n");
		console_flush();
	}

	/* A dispatched command consumes any arguments, and so does a
	 * refused one: leaving them set would apply them to whatever was
	 * typed next. */
	for (arg_idx = 0; arg_idx < CONSOLE_NARGS; arg_idx++)
		arg[arg_idx] = 0;
	arg_idx = 0;
}


void console_identity(char track, unsigned long mck_hz)
{
	/*
	 * The identity line, emitted by the banner and by `v` on both
	 * tracks, in this exact format. One line, key=value, same keys and
	 * same order everywhere, so a host reads one regular expression
	 * instead of matching prose. `build=` is last and is matched to the
	 * end of the line, opaque: what a board puts there is the build
	 * system's business, and a parser that spelled out its shape would
	 * have to be edited on the day that changed. This is what
	 * measure.parse_identity parses and what a host refuses a pairing
	 * on - wire contract, and this function is its only home.
	 *
	 * `build=` is FW_GIT_REV: the commit the image was built from, with
	 * a `+` and the working-tree delta hash when the tree was dirty.
	 * host/provenance.py turns it into a source state; see fw_version.h
	 * for why a wall clock could not.
	 *
	 * The ADC clock is MCK/4 by PRESCAL=1, which is why 78 MHz was
	 * chosen: 19.5 MHz sits inside the datasheet's 20 MHz limit. It is
	 * derived here rather than passed so a track cannot report a
	 * divider it does not use.
	 *
	 * `mck` and `adcclk` are NOMINAL - register-derived, never
	 * measured - and stay that way deliberately: stream_core.c computes
	 * the reported sample rate as integer division on this same figure,
	 * so a host inverting a rate back to an RC must divide by what the
	 * board divided by, not by a measured value, or the round-trip
	 * breaks. The measured clock lives separately, as mck_meas_hz in
	 * the telemetry heartbeat.
	 */
	con_str("# id: track=");   con_ch(track);
	con_str(" fw=");           con_str(FW_VERSION_STR);
	con_str(" ctlver=");       con_u32(CTL_VERSION);
	con_str(" framever=");     con_u32(FRAME_VERSION);
	con_str(" mck=");          con_u32(mck_hz);
	con_str(" adcclk=");       con_u32(mck_hz / 4u);
	con_str(" framebytes=");   con_u32(FRAME_BYTES);
	con_str(" framesamples="); con_u32(FRAME_SAMPLES);
	con_str(" build=" FW_GIT_REV);
	con_nl();
	console_flush();
}
