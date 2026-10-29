# stop-esp32-s3-to-reboot


✅ Phone mirrors to HDMI → capture card → laptop (vision path)
✅ Laptop → serial → ESP32-S3 → USB HID multitouch → phone (action path)
✅ Single port open = zero resets, HID stays attached the whole session
✅ Coordinate mapping aligned between capture and touch


```
Initializing HDMI capture...
Waiting for capture card to lock HDMI signal...
Acquiring a valid phone frame...
  attempt 1: no active area, retrying...
  attempt 2: no active area, retrying...
  attempt 3: no active area, retrying...
  attempt 4: no active area, retrying...
  attempt 5: no active area, retrying...
  attempt 6: no active area, retrying...
  attempt 7: no active area, retrying...
  attempt 8: no active area, retrying...
  attempt 9: no active area, retrying...
  attempt 10: no active area, retrying...
  attempt 11: no active area, retrying...
Active area: 494x1019 at offset (713,0)
Connecting to ESP32 on /dev/serial/by-id/usb-1a86_USB_Single_Serial_5C63002523-if00...
Waiting for ESP32 to answer PING...
  [esp32] ESP-ROM:esp32s3-20210327
  [esp32] Build:Mar 27 2021
  [esp32] rst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)
  [esp32] SPIWP:0xee
  [esp32] mode:DIO, clock div:1
  [esp32] load:0x3fce2820,len:0x10cc
  [esp32] load:0x403c8700,len:0xc2c
  [esp32] load:0x403cb700,len:0x30b0
  [esp32] entry 0x403c88b8
ESP32 is READY.
Sending resolution: 494x1019
  [esp32] RECV: PING
  [esp32] READY
  [esp32] RECV: PING
  [esp32] READY
  [esp32] RECV: PING
  [esp32] READY
  [esp32] RECV: PING
  [esp32] READY
  [esp32] RECV: PING
  [esp32] READY
  [esp32] RECV: PING
  [esp32] READY
  [esp32] RECV: RES 494 1019
Resolution synced.

===== Closed-Loop Test =====

>>> TAP 247 509
  [esp32] RECV: TAP 247 509
  [esp32] LAPTOP TAP  x=16383 y=16367
<<< DONE
  saved proof_1_tap_center.png

>>> SWIPE 247 764 247 254 500
  [esp32] RECV: SWIPE 247 764 247 254 500
  [esp32] LAPTOP SWIPE
<<< DONE
  saved proof_2_swipe_up.png

Test complete. Check debug_active_area.png and proof_*.png

```