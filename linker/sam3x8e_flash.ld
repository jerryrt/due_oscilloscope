/*
 * SAM3X8E flash link map for due_oscilloscope.
 *
 * Derived from Atmel's flash.ld shipped with arduino:sam 1.6.12.
 *
 * The 96 KB of SRAM is two physical banks. The part exposes a
 * contiguous alias starting at 0x20070000, which is what makes a single
 * 96 KB view possible:
 *
 *   0x20070000 .. 0x20080000   64 KB, bank 0 (also aliased at 0x20000000)
 *   0x20080000 .. 0x20088000   32 KB, bank 1
 *
 * They are kept as separate regions here rather than merged into one, so
 * that DMA buffers can be pinned to a chosen bank. Placing the ADC
 * capture ring in one bank and the USB/DAC buffers in the other lets PDC
 * writes and USB DMA reads avoid arbitrating for the same bus matrix
 * slave. Use __attribute__((section(".sram1"))) to place into bank 1.
 *
 * Note the alias: bank 0 is reachable at both 0x20000000 and 0x20070000.
 * Only the 0x20070000 view is used here, to keep one address per byte.
 */

OUTPUT_FORMAT("elf32-littlearm", "elf32-littlearm", "elf32-littlearm")
OUTPUT_ARCH(arm)
SEARCH_DIR(.)
ENTRY(Reset_Handler)

MEMORY
{
	rom  (rx)  : ORIGIN = 0x00080000, LENGTH = 0x00080000  /* flash  512K */
	ram0 (rwx) : ORIGIN = 0x20070000, LENGTH = 0x00010000  /* bank 0  64K */
	ram1 (rwx) : ORIGIN = 0x20080000, LENGTH = 0x00008000  /* bank 1  32K */
}

_estack = ORIGIN(ram0) + LENGTH(ram0);   /* stack grows down from bank 0 top */

SECTIONS
{
	.text :
	{
		. = ALIGN(4);
		_sfixed = .;
		KEEP(*(.vectors .vectors.*))
		*(.text .text.* .gnu.linkonce.t.*)
		*(.glue_7t) *(.glue_7)
		*(.rodata .rodata* .gnu.linkonce.r.*)
		*(.ARM.extab* .gnu.linkonce.armextab.*)

		. = ALIGN(4);
		KEEP(*(.init))
		. = ALIGN(4);
		__preinit_array_start = .;
		KEEP(*(.preinit_array))
		__preinit_array_end = .;

		. = ALIGN(4);
		__init_array_start = .;
		KEEP(*(SORT(.init_array.*)))
		KEEP(*(.init_array))
		__init_array_end = .;

		. = ALIGN(4);
		KEEP(*(.fini))
		. = ALIGN(4);
		__fini_array_start = .;
		KEEP(*(.fini_array))
		KEEP(*(SORT(.fini_array.*)))
		__fini_array_end = .;

		. = ALIGN(4);
		_efixed = .;
	} > rom

	PROVIDE_HIDDEN(__exidx_start = .);
	.ARM.exidx : { *(.ARM.exidx* .gnu.linkonce.armexidx.*) } > rom
	PROVIDE_HIDDEN(__exidx_end = .);

	. = ALIGN(4);
	_etext = .;

	/* Initialised data: stored in flash after .text, copied to RAM at
	 * reset by Reset_Handler. */
	.data : AT (_etext)
	{
		. = ALIGN(4);
		_sdata = .;
		*(.ramfunc .ramfunc.*)
		*(.data .data.*)
		. = ALIGN(4);
		_edata = .;
	} > ram0

	.bss (NOLOAD) :
	{
		. = ALIGN(4);
		_sbss = .;
		*(.bss .bss.*)
		*(COMMON)
		. = ALIGN(4);
		_ebss = .;
	} > ram0

	/* Bank 1: nothing lands here unless explicitly placed. Reserved for
	 * DMA buffers that must not contend with bank 0 traffic. */
	.sram1 (NOLOAD) :
	{
		. = ALIGN(4);
		_ssram1 = .;
		*(.sram1 .sram1.*)
		. = ALIGN(4);
		_esram1 = .;
	} > ram1

	. = ALIGN(4);
	_end = .;
	PROVIDE(end = .);
	_heap_start = .;
	_heap_end = _estack - 0x2000;   /* leave 8K for the stack */
}
