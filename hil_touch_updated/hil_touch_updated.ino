// touch_fw.ino - ESP32-S3 2-finger USB HID touchscreen driven by the laptop over UART0.
//
// Arduino IDE: Board "ESP32S3 Dev Module", USB Mode "USB-OTG (TinyUSB)",
//              USB CDC On Boot "Disabled", Upload Mode "UART0 / Hardware CDC".
//
// Serial protocol (115200 baud, one command per line, ending with "\n"):
//   PING                              -> READY
//   RES <w> <h>                       -> OK     coordinate space used by TAP/SWIPE.
//                                               "RES 32767 32767" = raw touch units (identity mapping)
//   TAP <x> <y> [hold_ms]             -> DONE | ERR <reason>     (hold default 200, 20..5000)
//   SWIPE <x1> <y1> <x2> <y2> <ms>    -> DONE | ERR <reason>     (ms 16..10000)
// Other lines:
//   BOOT <name>   printed once every time the chip (re)starts - an unexpected BOOT means a reset
//   # ...         log lines, ignore them

#include "USB.h"
#include "USBHID.h"
#include <string.h>
#include <stdio.h>

#define FW_NAME     "touch-fw-2"
#define MAX_FINGERS 2
#define RID_TOUCH   0x02
#define RID_MAXCNT  0x03
#define COORD_MAX   32767
#define MAX_LINE    96

#define HID_FINGER \
  0x05, 0x0D, 0x09, 0x22, 0xA1, 0x02, \
  0x15, 0x00, 0x25, 0x01, 0x09, 0x42, \
  0x75, 0x01, 0x95, 0x01, 0x81, 0x02, \
  0x75, 0x07, 0x95, 0x01, 0x81, 0x03, \
  0x09, 0x51, 0x25, 0x7F, \
  0x75, 0x08, 0x95, 0x01, 0x81, 0x02, \
  0x05, 0x01, 0x09, 0x30, \
  0x55, 0x0F, 0x65, 0x11, \
  0x35, 0x00, 0x46, 0x2C, 0x01, \
  0x16, 0x00, 0x00, 0x26, 0xFF, 0x7F, \
  0x75, 0x10, 0x95, 0x01, 0x81, 0x02, \
  0x09, 0x31, 0x81, 0x02, \
  0xC0

static const uint8_t desc[] = {
  0x05, 0x0D, 0x09, 0x04, 0xA1, 0x01,
  0x85, RID_TOUCH,
  HID_FINGER,
  HID_FINGER,
  0x05, 0x0D,
  0x55, 0x00, 0x65, 0x00, 0x35, 0x00, 0x45, 0x00,
  0x15, 0x00, 0x27, 0xFF, 0xFF, 0x00, 0x00,
  0x75, 0x10, 0x95, 0x01, 0x09, 0x56, 0x81, 0x02,
  0x09, 0x54, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x01, 0x81, 0x02,
  0x85, RID_MAXCNT,
  0x09, 0x55, 0x25, MAX_FINGERS, 0x75, 0x08, 0x95, 0x01, 0xB1, 0x02,
  0xC0
};

typedef struct {
  uint8_t  tip, id;
  uint16_t x, y;
} __attribute__((packed)) finger_t;

typedef struct {
  finger_t f[MAX_FINGERS];
  uint16_t scan_time;
  uint8_t  contact_count;
} __attribute__((packed)) touch_report_t;

class TouchDevice : public USBHIDDevice {
public:
  USBHID hid;
  TouchDevice() { hid.addDevice(this, sizeof(desc)); }
  void begin() { hid.begin(); }
  uint16_t _onGetDescriptor(uint8_t* buffer) {
    memcpy(buffer, desc, sizeof(desc));
    return sizeof(desc);
  }
  uint16_t _onGetFeature(uint8_t report_id, uint8_t* buffer, uint16_t len) {
    if (report_id == RID_MAXCNT) { buffer[0] = MAX_FINGERS; return 1; }
    return 0;
  }
  bool send(touch_report_t* r) {
    return hid.SendReport(RID_TOUCH, r, sizeof(*r));
  }
};

TouchDevice touch;
touch_report_t report;

// Send the current report. A send can fail when the USB endpoint is busy, so retry
// a few times. Returns true if the report went out.
bool sendReport(int tries = 5) {
  report.scan_time = (uint16_t)(millis() * 10);
  bool ok = false;
  for (int i = 0; i < tries && !ok; i++) {
    ok = touch.send(&report);
    if (!ok) delay(2);
  }
  delay(8);
  return ok;
}

void setFinger(uint8_t slot, bool down, uint16_t x, uint16_t y) {
  report.f[slot].tip = down;
  report.f[slot].id  = slot + 1;
  report.f[slot].x   = x;
  report.f[slot].y   = y;
}

// Touch and hold at a point. Returns false if the touch-down could not be sent.
// The lift-off is always attempted (hard) so a finger is never left down.
bool press(const char* name, uint16_t x, uint16_t y, int holdMs) {
  Serial0.printf("# %s x=%u y=%u\n", name, x, y);
  memset(&report, 0, sizeof(report));
  report.contact_count = 1;
  setFinger(0, true, x, y);
  bool ok = true;
  for (int t = 0; t < holdMs; t += 20) {
    if (!sendReport()) { ok = false; break; }
    delay(12);
  }
  report.f[0].tip = 0;      // lift at the last position
  sendReport(25);
  return ok;
}

// Straight-line swipe. Returns false if a report could not be sent.
// The lift-off is always attempted (hard) so a finger is never left down.
bool swipe(const char* name, uint16_t x1, uint16_t y1, uint16_t x2, uint16_t y2, int ms) {
  Serial0.printf("# %s\n", name);
  int steps = ms / 8;
  if (steps < 1) steps = 1;                // ms < 8 used to divide by zero (= chip reset)
  memset(&report, 0, sizeof(report));
  report.contact_count = 1;
  bool ok = true;
  for (int i = 0; i <= steps; i++) {
    setFinger(0, true,
              x1 + (int32_t)(x2 - x1) * i / steps,
              y1 + (int32_t)(y2 - y1) * i / steps);
    if (!sendReport()) { ok = false; break; }
  }
  report.f[0].tip = 0;      // lift at the last position
  sendReport(25);
  return ok;
}

// ---------- Screen mapping & command handling ----------
uint16_t screenW = 720;    // defaults for a 720x1480 phone; overridden by RES from the laptop
uint16_t screenH = 1480;
String cmdBuffer = "";
bool cmdOverflow = false;

static uint16_t clampCoord(int64_t v) {
  return v < 0 ? 0 : (v > COORD_MAX ? COORD_MAX : (uint16_t)v);
}
uint16_t mapX(int x) { return clampCoord((int64_t)x * COORD_MAX / screenW); }
uint16_t mapY(int y) { return clampCoord((int64_t)y * COORD_MAX / screenH); }

bool inRange(int x, int y) {
  return x >= 0 && y >= 0 && x <= (int)screenW && y <= (int)screenH;
}

void processCommand(const char* c) {
  Serial0.printf("# RECV: %s\n", c);

  // Handshake: laptop sends PING, we answer READY
  if (strcmp(c, "PING") == 0) {
    Serial0.println("READY");
    return;
  }

  int w, h, x1, y1, x2, y2, ms, hold;

  if (sscanf(c, "RES %d %d", &w, &h) == 2) {
    if (w < 1 || h < 1 || w > 65535 || h > 65535) {
      Serial0.println("ERR bad resolution");
      return;
    }
    screenW = w;
    screenH = h;
    Serial0.println("OK");
    return;
  }

  if (sscanf(c, "SWIPE %d %d %d %d %d", &x1, &y1, &x2, &y2, &ms) == 5) {
    if (!inRange(x1, y1) || !inRange(x2, y2) || ms < 16 || ms > 10000) {
      Serial0.println("ERR out of range");
      return;
    }
    bool ok = swipe("LAPTOP SWIPE", mapX(x1), mapY(y1), mapX(x2), mapY(y2), ms);
    Serial0.println(ok ? "DONE" : "ERR usb send failed");
    return;
  }

  int n = sscanf(c, "TAP %d %d %d", &x1, &y1, &hold);
  if (n >= 2) {
    if (n < 3) hold = 200;
    if (!inRange(x1, y1) || hold < 20 || hold > 5000) {
      Serial0.println("ERR out of range");
      return;
    }
    bool ok = press("LAPTOP TAP", mapX(x1), mapY(y1), hold);
    Serial0.println(ok ? "DONE" : "ERR usb send failed");
    return;
  }

  Serial0.println("ERR unknown command");
}

void setup() {
  Serial0.begin(115200);
  Serial0.printf("BOOT %s\n", FW_NAME);   // the laptop treats an unexpected BOOT as a reset
  touch.begin();
  USB.productName("Test Touch");
  USB.begin();
  delay(3000);             // give the phone time to enumerate the HID device
}

void loop() {
  while (Serial0.available()) {
    char c = Serial0.read();
    if (c == '\n') {
      if (cmdOverflow) {
        Serial0.println("ERR line too long");
      } else if (cmdBuffer.length() > 0) {
        processCommand(cmdBuffer.c_str());
      }
      cmdBuffer = "";
      cmdOverflow = false;
    } else if (c != '\r') {
      if (cmdBuffer.length() < MAX_LINE) cmdBuffer += c;
      else cmdOverflow = true;
    }
  }
}
