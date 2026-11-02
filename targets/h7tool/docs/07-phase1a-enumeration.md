# Phase 1a: enumeration (image4a)

`fw/image4/main.c`, built by `tools/build_image.sh` (host arm-none-eabi-gcc
14.2.1, checked by `check_image.py`, 2127 bytes). Polling, HSI 64 MHz, no PLL.
Two CDC-ACM functions (IAD) on interfaces 0-1 and 2-3, VID/PID `1209:0001`
(the open test pair, not an allocation *(check)*), serial = chip UID bytes as
hex. No data endpoints are configured yet; endpoint 0 only.

## Measured on linux-x1, 2026-11-02
- `lsusb`: High Speed (480 Mbps); descriptors read back as written, config
  total length 141, 4 interfaces. Kernel bound `cdc_acm` twice: `ttyACM3`
  and `ttyACM4`. No `-110` / `-71`, unlike image3a.
- Both nodes open at 115200 and accept a baud change (SET_LINE_CODING,
  SET_CONTROL_LINE_STATE served).
- Serial string `3D0040001851303338393233` is the UID read as bytes at
  0x1FF1E800; the stock firmware prints the same UID as three 32-bit words
  (`0040003D 33305118 33323938`), i.e. each word byte-reversed. Same chip.
- Vendor request IN `0xC0/0x01` (`tools/h7_usb_probe.py`) returns the core
  registers:

  | register | value | reads as |
  |---|---|---|
  | CID | 0x00002300 | |
  | GSNPSID | 0x4F54330A | Synopsys core id, 3.30a *(check)* |
  | GHWCFG2 | 0x229FE190 | OTG_ARCH = 2 (internal DMA); 8 device endpoints besides EP0 |
  | GHWCFG3 | 0x03B8D2E8 | DFIFO depth field = 952 words |
  | GHWCFG4 | 0xE3F00030 | 8 IN endpoints besides EP0; dedicated TX FIFOs |
  | GRXFSIZ / DIEPTXF0 | 0x16B / 0x0010016B | stock layout, as programmed |

  So the core supports internal DMA, which Phase 2 needs, and has 9
  endpoints in total. The depth field says 952 where the stock layout runs
  to word 1024; why they differ is not established *(check)* - size the
  Phase 2 FIFO layout against 952 until it is.

## Not covered
Data endpoints, DMA, any interrupt-driven operation, enumeration after a
host-side reset or suspend, and Windows/macOS hosts.
