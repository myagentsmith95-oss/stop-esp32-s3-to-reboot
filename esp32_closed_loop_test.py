#!/usr/bin/env python3
"""Closed-loop test: ESP32 touches the phone, the HDMI capture card shows the result.

Flow:
  1. Grab frames from the HDMI capture card and find where the phone screen is.
  2. Open the ESP32 serial port WITHOUT rebooting the ESP32.
  3. Handshake (PING -> READY), then tell the ESP32 the phone screen size.
  4. Send a TAP and a SWIPE, and save a cropped screenshot after each one,
     so you can see that the phone actually reacted.

Serial protocol (one text line per message, ending with "\n"):
  PC -> ESP32: PING | RES <w> <h> | TAP <x> <y> | SWIPE <x1> <y1> <x2> <y2> <ms>
  ESP32 -> PC: READY | OK | DONE | ERR <reason> | any other line is a log message
"""
import sys
import time

import cv2
import numpy as np
import serial

# ============ CONFIGURATION ============
# Use the /dev/serial/by-id/ path: unlike /dev/ttyUSB0 or /dev/ttyACM0,
# it doesn't change when you replug the board or plug in other USB devices.
SERIAL_PORT = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5C63002523-if00"
# The capture card's video device. List them with: v4l2-ctl --list-devices
VIDEO_DEV   = "/dev/video2"
# =======================================


# ---------- Serial: open without triggering ESP32 auto-reset ----------
def open_esp32_no_reset(port, baud=115200, timeout=1):
    """Open the ESP32 serial port WITHOUT rebooting the ESP32.

    Why the ESP32 rebooted before:
      Dev boards have an "auto-reset" circuit (2 transistors) so flashing
      tools can reboot the chip through the USB-serial chip's DTR and RTS
      lines. It reacts to the two lines like this:

          DTR  RTS   effect on the ESP32
          ---  ---   ------------------------------------------------
           0    0    nothing (idle)
           1    1    nothing (the circuit ignores "both on")
           1    0    holds GPIO0 low (boot-mode pin; harmless while
                     the chip is running)
           0    1    holds EN low = the chip is RESET

      Linux turns BOTH lines on when the port opens: (1,1), which is safe.
      The old code then turned DTR off first, leaving (0,1) for a moment.
      That held EN low, so when RTS went off too the chip booted again.
      That is the "rst:0x1 (POWERON)" in the log.

    The fix: turn RTS off FIRST. The lines go (1,1) -> (1,0) -> (0,0), and
    none of those steps ever touches EN.
    """
    # Opening the port sets DTR=1, RTS=1 together: no reset.
    ser = serial.Serial(port, baud, timeout=timeout)
    # Order matters, see above: RTS first, then DTR.
    ser.rts = False
    ser.dtr = False
    return ser


# ---------- Capture helpers ----------
def is_color_bars(frame):
    """Return True when the frame is the capture card's 'no signal' picture.

    Without an HDMI signal, many capture cards output colour bars or one solid
    colour. Both are very saturated (strong colours) and barely change from
    top to bottom, so we test for exactly that.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    # Share of pixels with strong colour. A real phone screen rarely
    # reaches 35%; test patterns are almost 100%.
    frac_high_sat = float(np.mean(sat > 150))
    if frac_high_sat < 0.35:
        return False
    # Shrink the frame, then measure how much each column changes from top
    # to bottom. Colour bars are vertical stripes, so this is very low.
    small = cv2.resize(frame, (64, 36)).astype(np.float32)
    col_var = small.var(axis=0).mean()
    return col_var < 500


def find_active_area(frame):
    """Find the phone screen inside the 1920x1080 frame.

    A portrait phone mirrored over HDMI is shown in the middle with black
    bars on the left and right. We take the background brightness from the
    four corners, then look for the columns and rows that are brighter
    than it.

    Returns (x0, y0, x1, y1), the inclusive pixel corners of the phone
    screen, or None when it can't be found.
    """
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    H, W = g.shape
    # The corners are always background (black bars), so they give the
    # background brightness. Use the darkest corner in case one is noisy.
    corners = [g[:40, :40], g[:40, -40:], g[-40:, :40], g[-40:, -40:]]
    bg = min(int(np.median(c)) for c in corners)
    # Anything 25 brightness levels above the background counts as screen.
    thr = bg + 25
    # Columns whose average is above the threshold belong to the screen.
    cols = np.where(g.mean(axis=0) > thr)[0]
    # None found: the screen is black (off or locked).
    # More than 60% of the width: probably not a portrait phone picture
    # (e.g. a test pattern), so don't trust it.
    if len(cols) == 0 or len(cols) > 0.6 * W:
        return None
    x0, x1 = cols[0], cols[-1]
    # Same for rows, but only inside the columns found above.
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

# MJPG lets USB capture cards deliver 1080p at full frame rate;
# raw YUYV at 1080p is often limited to a few frames per second.
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

# The card needs a moment to lock onto the HDMI signal. The first frames
# are often black or stale, so read and throw away a few.
print("Waiting for capture card to lock HDMI signal...")
time.sleep(2.0)
for _ in range(15):
    cap.read()

# Keep reading until a frame shows the phone screen (not the 'no signal'
# picture and not all black). Give up after 20 tries.
print("Acquiring a valid phone frame...")
area = None
frame = None
for attempt in range(20):
    ret, frame = cap.read()
    if not ret:
        time.sleep(0.2)
        continue
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
    # Save the last frame so you can see what the card actually outputs.
    if frame is not None:
        cv2.imwrite("debug_frame.png", frame)
    sys.exit("ERROR: Could not get a valid phone frame (still color bars or black).\n"
             "Saved debug_frame.png — open it to see what the card is outputting.\n"
             "Check: phone is ON, UNLOCKED, and mirroring over HDMI.")

# Size of the phone screen as seen in the capture. TAP/SWIPE coordinates
# are in this space: (0,0) is the top-left of the phone screen, not of
# the 1920x1080 frame.
x0, y0, x1, y1 = area
screen_w = x1 - x0 + 1
screen_h = y1 - y0 + 1
print(f"Active area: {screen_w}x{screen_h} at offset ({x0},{y0})")
# Save the crop so you can check the screen was found correctly.
cv2.imwrite("debug_active_area.png", frame[y0:y1 + 1, x0:x1 + 1])

# ---------- 2. Open serial to ESP32 (no reset) ----------
print(f"Connecting to ESP32 on {SERIAL_PORT}...")
try:
    ser = open_esp32_no_reset(SERIAL_PORT)
except serial.SerialException as e:
    sys.exit(f"ERROR: Could not open {SERIAL_PORT}: {e}")

# Drop anything the ESP32 sent before we connected (old log lines),
# so the handshake below only sees fresh replies.
ser.reset_input_buffer()

# ---------- 3. Handshake: ping until READY ----------
# Send PING every 0.5 s until the ESP32 answers READY (max 20 tries = ~10 s).
# This also covers the case where the ESP32 is still booting.
# Any other line from the ESP32 is printed as a log message.
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
# Tell the ESP32 the phone screen size seen in the capture, so it can map
# our TAP/SWIPE coordinates onto the phone's touch area. Wait up to 5 s
# for OK; without it, carry on, since the ESP32 may use its default size.
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
    """Send one command and wait (max 15 s) until the ESP32 has finished it.

    Returns True on DONE, False on ERR or timeout. Other lines from the
    ESP32 are printed as log messages.
    """
    print(f"\n>>> {cmd}")
    ser.write(f"{cmd}\n".encode())
    deadline = time.time() + 15
    while time.time() < deadline:
        if ser.in_waiting:
            resp = ser.readline().decode('utf-8', errors='ignore').strip()
            if resp == "DONE":
                print("<<< DONE")
                # Give the phone a moment to finish its own animation.
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
    """Save the current phone screen (cropped to the active area) as proof."""
    ret, f = cap.read()
    if not ret:
        print(f"  (no frame for {filename})")
        return
    cropped = f[y0:y1 + 1, x0:x1 + 1]
    cv2.imwrite(filename, cropped)
    print(f"  saved {filename}")


# ---------- 6. Test sequence ----------
print("\n===== Closed-Loop Test =====")

# Tap the centre of the screen.
send_command(f"TAP {screen_w // 2} {screen_h // 2}")
time.sleep(1.0)
capture_and_save("proof_1_tap_center.png")

# Swipe up from 3/4 of the height to 1/4 of the height, taking 500 ms.
send_command(f"SWIPE {screen_w // 2} {screen_h * 3 // 4} {screen_w // 2} {screen_h // 4} 500")
time.sleep(1.0)
capture_and_save("proof_2_swipe_up.png")

# ---------- 7. Cleanup ----------
# Closing the port drops DTR and RTS together, which doesn't reset the ESP32.
cap.release()
ser.close()
print("\nTest complete. Check debug_active_area.png and proof_*.png")
