/* Image 1: boot loader rules in docs/ and ../../scripts/check_image.py.
 * Flash starts at 0x08020000; DTCM word 0x20000000 belongs to the boot
 * request, so RAM starts at 0x20000004. */
MEMORY
{
  FLASH (rx)  : ORIGIN = 0x08020000, LENGTH = 1280K
  DTCM  (rwx) : ORIGIN = 0x20000004, LENGTH = 128K - 4
}
ENTRY(Reset_Handler)
SECTIONS
{
  .isr_vector : { KEEP(*(.isr_vector)) } > FLASH
  .text : { *(.text*) *(.rodata*) } > FLASH
  .data : { *(.data*) } > DTCM AT > FLASH
  .bss  : { *(.bss*) *(COMMON) } > DTCM
  _sidata = LOADADDR(.data); _sdata = ADDR(.data); _edata = ADDR(.data) + SIZEOF(.data);
  _sbss = ADDR(.bss); _ebss = ADDR(.bss) + SIZEOF(.bss);
  _estack = ORIGIN(DTCM) + LENGTH(DTCM);
}
