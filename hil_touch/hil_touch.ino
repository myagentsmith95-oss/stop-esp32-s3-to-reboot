#include "USB.h"
#include "USBHID.h"
#include <string.h>
#include <stdio.h>

#define MAX_FINGERS 2
#define RID_TOUCH   0x02
#define RID_MAXCNT  0x03
#define COORD_MAX   32767

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

void sendReport() {
  report.scan_time = (uint16_t)(millis() * 10);
  touch.send(&report);
  delay(8);
}

void setFinger(uint8_t slot, bool down, uint16_t x, uint16_t y) {
  report.f[slot].tip = down;
  report.f[slot].id  = slot + 1;
  report.f[slot].x   = x;
  report.f[slot].y   = y;
}

void press(const char* name, uint16_t x, uint16_t y, int holdMs) {
  Serial0.printf("%s  x=%u y=%u\n", name, x, y);
  memset(&report, 0, sizeof(report));
  report.contact_count = 1;
  setFinger(0, true, x, y);
  for (int t = 0; t < holdMs; t += 20) {
    sendReport();
    delay(12);
  }
  setFinger(0, false, x, y);
  sendReport();
}

void swipe(const char* name, uint16_t x1, uint16_t y1, uint16_t x2, uint16_t y2, int ms) {
  Serial0.printf("%s\n", name);
  int steps = ms / 8;
  memset(&report, 0, sizeof(report));
  report.contact_count = 1;
  for (int i = 0; i <= steps; i++) {
    setFinger(0, true,
              x1 + (int32_t)(x2 - x1) * i / steps,
              y1 + (int32_t)(y2 - y1) * i / steps);
    sendReport();
  }
  setFinger(0, false, x2, y2);
  sendReport();
}

// ---------- Screen mapping & command handling ----------
uint16_t screenW = 1080;   // defaults; overridden by RES from laptop
uint16_t screenH = 2400;
String cmdBuffer = "";

uint16_t mapX(int x) { return (uint16_t)((uint32_t)x * COORD_MAX / screenW); }
uint16_t mapY(int y) { return (uint16_t)((uint32_t)y * COORD_MAX / screenH); }

void processCommand(const char* c) {
  Serial0.printf("RECV: %s\n", c);

  // Handshake: laptop sends PING, we answer READY
  if (strcmp(c, "PING") == 0) {
    Serial0.println("READY");
    return;
  }

  int w, h, x1, y1, x2, y2, ms;

  if (sscanf(c, "RES %d %d", &w, &h) == 2) {
    if (w > 0 && h > 0) { screenW = w; screenH = h; }
    Serial0.println("OK");
  }
  else if (sscanf(c, "TAP %d %d", &x1, &y1) == 2) {
    press("LAPTOP TAP", mapX(x1), mapY(y1), 200);
    Serial0.println("DONE");
  }
  else if (sscanf(c, "SWIPE %d %d %d %d %d", &x1, &y1, &x2, &y2, &ms) == 5) {
    swipe("LAPTOP SWIPE", mapX(x1), mapY(y1), mapX(x2), mapY(y2), ms);
    Serial0.println("DONE");
  }
  else {
    Serial0.println("ERR unknown command");
  }
}

void setup() {
  Serial0.begin(115200);
  touch.begin();
  USB.productName("Test Touch");
  USB.begin();
  delay(3000);             // give the phone time to enumerate the HID device
  Serial0.println("READY");
}

void loop() {
  while (Serial0.available()) {
    char c = Serial0.read();
    if (c == '\n') {
      processCommand(cmdBuffer.c_str());
      cmdBuffer = "";
    } else if (c != '\r') {
      cmdBuffer += c;
    }
  }
}