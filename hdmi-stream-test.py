import sys
import cv2, numpy as np

DEV = "/dev/video2"      # change if the number moved

cap = cv2.VideoCapture(DEV, cv2.CAP_V4L2)
if not cap.isOpened():
    sys.exit(f"Cannot open {DEV}. Close ffplay/guvcview/OBS and check the number.")
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

def measure(f):
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
    H, W = g.shape
    corners = [g[:40, :40], g[:40, -40:], g[-40:, :40], g[-40:, -40:]]
    bg = min(int(np.median(c)) for c in corners)
    thr = bg + 25
    cols = np.where(g.mean(axis=0) > thr)[0]
    print("black level", bg, "threshold", thr)
    if len(cols) == 0:
        print("Frame is black. No signal?"); return
    if len(cols) > 0.6 * W:
        print("Active area > 60% of the frame: test pattern or no signal? Save raw.png and check."); return
    x0, x1 = cols[0], cols[-1]
    rows = np.where(g[:, x0:x1 + 1].mean(axis=1) > thr)[0]
    y0, y1 = rows[0], rows[-1]
    print("frame", W, H, "active", x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    out = f.copy()
    cv2.rectangle(out, (x0, y0), (x1, y1), (0, 0, 255), 2)
    cv2.imwrite("active.png", out)

print("Keys in the preview window: m = measure, s = save raw.png, q = quit")
last = None
while True:
    ok, f = cap.read()
    if not ok:
        continue
    last = f
    cv2.imshow("capture", cv2.resize(f, (960, 540)))
    k = cv2.waitKey(1) & 0xFF
    if k == ord("q"):
        break
    if k == ord("s"):
        cv2.imwrite("raw.png", last); print("saved raw.png")
    if k == ord("m"):
        measure(last)

cap.release()
cv2.destroyAllWindows()


# sudo apt install python3-venv
# cd ~/Documents/work
# python3 -m venv .venv
# source .venv/bin/activate
# pip install opencv-python numpy pyserial
# python3 hdmi-stream-test.py