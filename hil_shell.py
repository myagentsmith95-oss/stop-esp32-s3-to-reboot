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

# ---------- Serial open ----------
def open_esp32(port, baud=115200, timeout=1):
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baud
    ser.timeout = timeout
    ser.dsrdtr = False
    ser.open()
    try:
        attrs = termios.tcgetattr(ser.fileno())
        attrs[2] |= termios.CLOCAL
        attrs[2] &= ~termios.HUPCL
        termios.tcsetattr(ser.fileno(), termios.TCSANOW, attrs)
    except OSError:
        pass
    ser.dtr = False
    ser.rts = False
    return ser

# ---------- Capture helpers ----------
def is_color_bars(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    if float(np.mean(sat > 150)) < 0.35:
        return False
    small = cv2.resize(frame, (64, 36)).astype(np.float32)
    return small.var(axis=0).mean() < 500

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
    return (x0, rows[0], x1, rows[-1])

# ---------- 1. Capture ----------
print("Initializing HDMI capture...")
cap = cv2.VideoCapture(VIDEO_DEV, cv2.CAP_V4L2)
if not cap.isOpened():
    sys.exit(f"Cannot open {VIDEO_DEV}.")
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

print("Waiting for capture card to lock signal...")
time.sleep(2.0)
for _ in range(15):
    cap.read()

area = None
frame = None
for attempt in range(20):
    ret, frame = cap.read()
    if not ret:
        time.sleep(0.2); continue
    if is_color_bars(frame):
        time.sleep(0.5); continue
    area = find_active_area(frame)
    if area is not None:
        break
    time.sleep(0.3)

if area is None:
    sys.exit("ERROR: no valid phone frame (color bars/black). Is the phone on & mirroring?")

x0, y0, x1, y1 = area
screen_w = x1 - x0 + 1
screen_h = y1 - y0 + 1
print(f"Active area: {screen_w}x{screen_h} at offset ({x0},{y0})")

# ---------- 2. Serial (ONE reset happens here, then stays connected) ----------
print(f"\nConnecting to ESP32 on {SERIAL_PORT}...")
print("(The ESP32 may reset ONCE now — this is expected. It stays connected after.)")
try:
    ser = open_esp32(SERIAL_PORT)
except serial.SerialException as e:
    sys.exit(f"ERROR: could not open {SERIAL_PORT}: {e}")
ser.reset_input_buffer()

# Handshake
esp_ready = False
for _ in range(20):
    ser.write(b"PING\n")
    time.sleep(0.5)
    while ser.in_waiting:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line == "READY":
            esp_ready = True
            break
    if esp_ready:
        break
if not esp_ready:
    ser.close(); sys.exit("ERROR: ESP32 never answered PING.")
print("ESP32 is READY and will STAY connected.\n")

# Sync resolution
ser.write(f"RES {screen_w} {screen_h}\n".encode())
deadline = time.time() + 5
while time.time() < deadline:
    if ser.in_waiting:
        if ser.readline().decode('utf-8', errors='ignore').strip() == "OK":
            break
    else:
        time.sleep(0.05)

# ---------- 3. Command helpers ----------
def send_command(cmd):
    ser.write(f"{cmd}\n".encode())
    deadline = time.time() + 15
    while time.time() < deadline:
        if ser.in_waiting:
            resp = ser.readline().decode('utf-8', errors='ignore').strip()
            if resp == "DONE":
                return True
            elif resp.startswith("ERR"):
                print(f"  [esp32] {resp}")
                return False
            elif resp:
                print(f"  [esp32] {resp}")
        else:
            time.sleep(0.02)
    print("  [timeout waiting for DONE]")
    return False

snap_count = 0
def snap(name=None):
    global snap_count
    ret, f = cap.read()
    if not ret:
        print("  (no frame)")
        return
    fn = name if name else f"snap_{snap_count}.png"
    snap_count += 1
    cv2.imwrite(fn, f[y0:y1 + 1, x0:x1 + 1])
    print(f"  saved {fn}")

def show_help():
    print("""
Commands (coordinates are in the phone screen, 0..{w} x 0..{h}):
  tap X Y                 Tap at (X, Y)
  swipe X1 Y1 X2 Y2 [MS]  Swipe between points, MS default 400
  snap [NAME]             Save current screen (cropped) to NAME.png
  res                     Show active area / resolution
  help                    Show this help
  quit                    Exit (disconnects ESP32)
""".format(w=screen_w, h=screen_h))

# ---------- 4. Interactive loop ----------
print("Type 'help' for commands.\n")
try:
    while True:
        try:
            line = input("hil> ").strip()
        except EOFError:
            break
        if not line:
            continue
        parts = line.split()
        cmd = parts[0].lower()

        if cmd in ("quit", "exit", "q"):
            break
        elif cmd == "help":
            show_help()
        elif cmd == "res":
            print(f"  active area: {screen_w}x{screen_h} at offset ({x0},{y0})")
        elif cmd == "tap":
            if len(parts) != 3:
                print("  usage: tap X Y"); continue
            send_command(f"TAP {int(parts[1])} {int(parts[2])}")
        elif cmd == "swipe":
            if len(parts) < 5:
                print("  usage: swipe X1 Y1 X2 Y2 [MS]"); continue
            ms = int(parts[5]) if len(parts) > 5 else 400
            send_command(f"SWIPE {parts[1]} {parts[2]} {parts[3]} {parts[4]} {ms}")
        elif cmd == "snap":
            snap(parts[1] if len(parts) > 1 else None)
        else:
            print(f"  Unknown command '{cmd}'. Type 'help'.")
except KeyboardInterrupt:
    print("\nInterrupted.")

# ---------- 5. Cleanup ----------
print("Disconnecting...")
cap.release()
ser.close()
print("Done.")