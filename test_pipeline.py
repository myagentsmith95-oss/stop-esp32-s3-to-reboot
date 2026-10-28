#!/usr/bin/env python3
import sys
import os
import time
import serial
import termios
import cv2
import numpy as np

# ============ CONFIGURATION ============
SERIAL_PORT = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5C63002523-if00"
VIDEO_DEV   = "/dev/video2"
# =======================================

# ---------- Serial: open without triggering ESP32 auto-reset ----------
def open_esp32_no_reset(port, baud=115200, timeout=1):
    """Open the ESP32 serial port WITHOUT triggering the hardware auto-reset.

    The reset is normally caused by the kernel raising DTR the instant the tty
    is opened. To prevent that, we first open the port at the OS level with
    O_NONBLOCK, set CLOCAL (ignore modem control lines) and clear HUPCL, and
    only THEN let pyserial open it. With CLOCAL set, the open no longer toggles
    DTR, so the auto-reset transistor never fires.
    """
    # Phase 1: OS-level pre-configuration (before pyserial touches the port).
    try:
        fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            attrs = termios.tcgetattr(fd)
            attrs[2] |= termios.CLOCAL    # ignore modem status/control lines
            attrs[2] &= ~termios.HUPCL    # don't drop DTR on close
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
        finally:
            os.close(fd)
        time.sleep(0.05)
    except OSError as e:
        print(f"  (pre-configure warning: {e})")

    # Phase 2: real open via pyserial (port is already reset-safe).
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baud
    ser.timeout = timeout
    ser.dsrdtr = False          # don't let pyserial manage DTR from RTS
    ser.open()
    ser.dtr = False
    ser.rts = False
    return ser

# ---------- Capture helpers ----------
def is_color_bars(frame):
    """Detect the capture card's 'no signal' test pattern (color bars / solid color)."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    frac_high_sat = float(np.mean(sat > 150))
    if frac_high_sat < 0.35:
        return False
    small = cv2.resize(frame, (64, 36)).astype(np.float32)
    col_var = small.var(axis=0).mean()
    return col_var < 500

def find_active_area(frame):
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    H, W = g.shape
    corners = [g[:40, :40], g[:40, -40:], g[-40:, :40], g[-40:, -40:]]
    bg = min(int(np.median(c)) for c in corners)
    thr = bg + 25
    cols = np.where(g.mean(axis=0) > thr)[0]
    if len(cols) == 0 or len(cols) > 0.6 * W:
        return None
    x0, x1 = cols[0], cols[-1]
    rows = np.where(g[:, x0:x1 + 1].mean(axis=1) > thr)[0]
    if len(rows) == 0:
        return None
    y0, y1 = rows[0], rows[-1]
    return (x0, y0, x1, y1)

# ---------- 1. Open HDMI capture ----------
print("Initializing HDMI capture...")
cap = cv2.VideoCapture(VIDEO_DEV, cv2.CAP_V4L2)
if not cap.isOpened():
    sys.exit(f"Cannot open {VIDEO_DEV}. Close other apps and check the number.")

cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

print("Waiting for capture card to lock HDMI signal...")
time.sleep(2.0)
for _ in range(15):
    cap.read()

print("Acquiring a valid phone frame...")
area = None
frame = None
for attempt in range(20):
    ret, frame = cap.read()
    if not ret:
        time.sleep(0.2); continue
    if is_color_bars(frame):
        print(f"  attempt {attempt+1}: color bars (no signal yet), waiting...")
        time.sleep(0.5)
        continue
    area = find_active_area(frame)
    if area is not None:
        break
    print(f"  attempt {attempt+1}: no active area, retrying...")
    time.sleep(0.3)

if area is None:
    if frame is not None:
        cv2.imwrite("debug_frame.png", frame)
    sys.exit("ERROR: Could not get a valid phone frame (still color bars or black).\n"
             "Saved debug_frame.png — open it to see what the card is outputting.\n"
             "Check: phone is ON, UNLOCKED, and mirroring over HDMI.")

x0, y0, x1, y1 = area
screen_w = x1 - x0 + 1
screen_h = y1 - y0 + 1
print(f"Active area: {screen_w}x{screen_h} at offset ({x0},{y0})")
cv2.imwrite("debug_active_area.png", frame[y0:y1 + 1, x0:x1 + 1])

# ---------- 2. Open serial to ESP32 (no reset) ----------
print(f"Connecting to ESP32 on {SERIAL_PORT}...")
try:
    ser = open_esp32_no_reset(SERIAL_PORT)
except serial.SerialException as e:
    sys.exit(f"ERROR: Could not open {SERIAL_PORT}: {e}")

ser.reset_input_buffer()

# ---------- 3. Handshake: ping until READY ----------
print("Waiting for ESP32 to answer PING...")
esp_ready = False
for attempt in range(20):
    ser.write(b"PING\n")
    time.sleep(0.5)
    while ser.in_waiting:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line == "READY":
            print("ESP32 is READY.")
            esp_ready = True
            break
        elif line:
            print(f"  [esp32] {line}")
    if esp_ready:
        break

if not esp_ready:
    ser.close()
    sys.exit("ERROR: ESP32 never answered PING.")

# ---------- 4. Sync resolution ----------
print(f"Sending resolution: {screen_w}x{screen_h}")
ser.write(f"RES {screen_w} {screen_h}\n".encode())
res_ok = False
deadline = time.time() + 5
while time.time() < deadline:
    if ser.in_waiting:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line == "OK":
            print("Resolution synced.")
            res_ok = True
            break
        elif line:
            print(f"  [esp32] {line}")
    else:
        time.sleep(0.05)
if not res_ok:
    print("WARNING: no OK to RES, continuing anyway.")

# ---------- 5. Command helper ----------
def send_command(cmd):
    print(f"\n>>> {cmd}")
    ser.write(f"{cmd}\n".encode())
    deadline = time.time() + 15
    while time.time() < deadline:
        if ser.in_waiting:
            resp = ser.readline().decode('utf-8', errors='ignore').strip()
            if resp == "DONE":
                print("<<< DONE")
                time.sleep(0.5)
                return True
            elif resp.startswith("ERR"):
                print(f"<<< {resp}")
                return False
            elif resp:
                print(f"  [esp32] {resp}")
        else:
            time.sleep(0.02)
    print("<<< TIMEOUT waiting for DONE")
    return False

def capture_and_save(filename):
    ret, f = cap.read()
    if not ret:
        print(f"  (no frame for {filename})")
        return
    cropped = f[y0:y1 + 1, x0:x1 + 1]
    cv2.imwrite(filename, cropped)
    print(f"  saved {filename}")

# ---------- 6. Test sequence ----------
print("\n===== Closed-Loop Test =====")

send_command(f"TAP {screen_w // 2} {screen_h // 2}")
time.sleep(1.0)
capture_and_save("proof_1_tap_center.png")

send_command(f"SWIPE {screen_w // 2} {screen_h * 3 // 4} {screen_w // 2} {screen_h // 4} 500")
time.sleep(1.0)
capture_and_save("proof_2_swipe_up.png")

# ---------- 7. Cleanup ----------
cap.release()
ser.close()
print("\nTest complete. Check debug_active_area.png and proof_*.png")