#!/bin/bash
# ================================================================
#  PiCam Hub — Setup Script
# ================================================================
#  Turns your Raspberry Pi into a camera hub with:
#    - Live MJPEG stream (port 8080)
#    - Web dashboard with photo/video controls
#    - Auto-download gallery for your phone
#    - Runs on boot via systemd
#
#  Run: chmod +x picam-hub-setup.sh && ./picam-hub-setup.sh
# ================================================================

set -e

HOME_DIR="$HOME"
HUB_DIR="$HOME/picam-hub"
CAPTURES_DIR="$HUB_DIR/captures"

echo "╔══════════════════════════════════════════╗"
echo "║   PiCam Hub — Setup                      ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ---- Directories ----
mkdir -p "$HUB_DIR" "$CAPTURES_DIR"

# ---- Install packages ----
echo "[1/4] Installing packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3-flask \
    python3-picamera2 \
    python3-opencv \
    python3-numpy \
    ffmpeg \
    2>/dev/null || true

# ---- Lens config (160° wide-angle defaults) ----
cat > "$HUB_DIR/lens.json" << 'LENSEOF'
{
  "mode": "corrected",
  "stream_w": 1280,
  "stream_h": 720,
  "fx": 480.0,
  "fy": 480.0,
  "cx": 640.0,
  "cy": 360.0,
  "k1": -0.32,
  "k2": 0.10,
  "k3": -0.02,
  "k4": 0.0,
  "balance": 0.5,
  "crop_zoom": 1.0
}
LENSEOF

# ---- Camera server ----
echo "[2/4] Writing camera server..."
cat > "$HUB_DIR/server.py" << 'PYEOF'
#!/usr/bin/env python3
"""
PiCam Hub — Camera server
MJPEG stream + web dashboard + capture gallery
"""

import io
import os
import json
import time
import threading
from datetime import datetime
from pathlib import Path
from flask import Flask, Response, send_file, jsonify, request, send_from_directory

import numpy as np
import cv2

try:
    from picamera2 import Picamera2
    from picamera2.encoders import H264Encoder
    from picamera2.outputs import FileOutput
    HAS_CAMERA = True
except ImportError:
    HAS_CAMERA = False
    print("[WARN] picamera2 not available — running in demo mode")

app = Flask(__name__)
BASE_DIR = Path(__file__).parent
CAPTURES_DIR = BASE_DIR / "captures"
CAPTURES_DIR.mkdir(exist_ok=True)
LENS_FILE = BASE_DIR / "lens.json"

# --- Camera state ---
camera = None
camera_lock = threading.Lock()
recording = False
recording_file = None

# --- Lens / fisheye state ---
lens_lock = threading.Lock()
lens_cfg = {}
remap_x = None
remap_y = None

def load_lens():
    global lens_cfg
    with open(LENS_FILE) as f:
        lens_cfg = json.load(f)
    rebuild_maps()

def save_lens():
    with open(LENS_FILE, "w") as f:
        json.dump(lens_cfg, f, indent=2)

def rebuild_maps():
    """Precompute fisheye undistort maps. Called once per config change."""
    global remap_x, remap_y
    w = int(lens_cfg["stream_w"])
    h = int(lens_cfg["stream_h"])
    K = np.array([
        [lens_cfg["fx"], 0, lens_cfg["cx"]],
        [0, lens_cfg["fy"], lens_cfg["cy"]],
        [0, 0, 1]
    ], dtype=np.float64)
    D = np.array([
        lens_cfg["k1"], lens_cfg["k2"],
        lens_cfg["k3"], lens_cfg["k4"]
    ], dtype=np.float64)
    new_K = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(
        K, D, (w, h), np.eye(3), balance=float(lens_cfg.get("balance", 0.5))
    )
    z = float(lens_cfg.get("crop_zoom", 1.0))
    if z != 1.0:
        new_K[0, 0] *= z
        new_K[1, 1] *= z
    remap_x, remap_y = cv2.fisheye.initUndistortRectifyMap(
        K, D, np.eye(3), new_K, (w, h), cv2.CV_16SC2
    )

load_lens()

def get_camera():
    """Init Pi camera at the configured stream resolution (RGB for OpenCV)."""
    global camera
    if camera is None and HAS_CAMERA:
        camera = Picamera2()
        w = int(lens_cfg["stream_w"])
        h = int(lens_cfg["stream_h"])
        config = camera.create_video_configuration(
            main={"size": (w, h), "format": "RGB888"}
        )
        camera.configure(config)
        camera.start()
        time.sleep(0.5)
    return camera

def process_frame(rgb):
    """Apply fisheye correction based on lens_cfg.mode. Returns JPEG bytes."""
    with lens_lock:
        mode = lens_cfg.get("mode", "corrected")
        rx, ry = remap_x, remap_y
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    if mode == "corrected" and rx is not None:
        bgr = cv2.remap(bgr, rx, ry, interpolation=cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_CONSTANT)
    elif mode == "cropped" and rx is not None:
        bgr = cv2.remap(bgr, rx, ry, interpolation=cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_CONSTANT)
        h, w = bgr.shape[:2]
        margin_x, margin_y = int(w * 0.08), int(h * 0.08)
        bgr = bgr[margin_y:h - margin_y, margin_x:w - margin_x]
    ok, jpg = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return jpg.tobytes() if ok else None

def generate_frames():
    get_camera()
    placeholder = BASE_DIR / "static" / "no_camera.jpg"
    while True:
        if HAS_CAMERA and camera:
            rgb = camera.capture_array("main")
            frame = process_frame(rgb)
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        else:
            time.sleep(0.1)
            if placeholder.exists():
                with open(placeholder, "rb") as f:
                    frame = f.read()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/stream')
def stream():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/photo', methods=['POST'])
def take_photo():
    """Capture full-res frame, apply fisheye correction, save JPEG."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = CAPTURES_DIR / f"photo_{ts}.jpg"
    if HAS_CAMERA and camera:
        rgb = camera.capture_array("main")
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        with lens_lock:
            mode = lens_cfg.get("mode", "corrected")
            rx, ry = remap_x, remap_y
        if mode != "raw" and rx is not None:
            bgr = cv2.remap(bgr, rx, ry, interpolation=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_CONSTANT)
        cv2.imwrite(str(path), bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return jsonify({"ok": True, "file": path.name})

@app.route('/record/start', methods=['POST'])
def start_recording():
    global recording, recording_file
    if recording:
        return jsonify({"error": "Already recording"})
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    recording_file = str(CAPTURES_DIR / f"video_{ts}.h264")
    if HAS_CAMERA and camera:
        camera.start_encoder(H264Encoder(), recording_file)
    recording = True
    return jsonify({"ok": True, "file": Path(recording_file).name})

@app.route('/record/stop', methods=['POST'])
def stop_recording():
    global recording, recording_file
    if not recording:
        return jsonify({"error": "Not recording"})
    if HAS_CAMERA and camera:
        camera.stop_encoder()
    recording = False
    f = recording_file
    recording_file = None
    return jsonify({"ok": True, "file": Path(f).name if f else None})

@app.route('/lens', methods=['GET'])
def get_lens():
    return jsonify(lens_cfg)

@app.route('/lens', methods=['POST'])
def update_lens():
    """Live-tune lens params. Body: JSON with any subset of lens_cfg keys."""
    data = request.get_json(force=True) or {}
    with lens_lock:
        for k, v in data.items():
            if k in lens_cfg:
                lens_cfg[k] = v
        rebuild_maps()
        save_lens()
    return jsonify({"ok": True, "lens": lens_cfg})

@app.route('/gallery')
def gallery():
    files = []
    for f in sorted(CAPTURES_DIR.iterdir(), reverse=True):
        if f.suffix in ('.jpg', '.h264', '.mp4'):
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "type": "photo" if f.suffix == ".jpg" else "video",
                "ts": f.stat().st_mtime
            })
    return jsonify(files)

@app.route('/captures/<path:filename>')
def download(filename):
    return send_from_directory(CAPTURES_DIR, filename, as_attachment=True)

@app.route('/')
def index():
    return send_file(Path(__file__).parent / "ui.html")

if __name__ == '__main__':
    print("[PiCam Hub] Starting on port 8080...")
    app.run(host='0.0.0.0', port=8080, threaded=True)
PYEOF

chmod +x "$HUB_DIR/server.py"

# ---- Web UI ----
echo "[3/4] Writing web UI..."
mkdir -p "$HUB_DIR/static"
cat > "$HUB_DIR/ui.html" << 'HTMLEOF'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>PiCam Hub</title>
<style>
  :root {
    --bg: #0a0a0c; --s1: #141418; --s2: #1c1c22;
    --bdr: #2a2a35; --txt: #e8e8ed; --dim: #666680;
    --red: #ff3b5c; --grn: #00e676; --blu: #4dabf7;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: var(--bg); color: var(--txt); font-family: 'Courier New', monospace; }

  .viewfinder {
    width: 100%;
    aspect-ratio: 16/9;
    background: #000;
    position: relative;
    overflow: hidden;
  }
  .viewfinder img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .rec-badge {
    position: absolute;
    top: 10px;
    left: 10px;
    background: var(--red);
    color: #fff;
    font-size: 11px;
    padding: 3px 10px;
    border-radius: 10px;
    display: none;
    animation: blink 1s infinite;
  }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }
  .rec-badge.active { display: block; }

  .controls {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    padding: 12px;
  }
  .btn {
    padding: 16px;
    border: none;
    border-radius: 10px;
    font-family: inherit;
    font-size: 13px;
    font-weight: bold;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
  }
  .btn-photo { background: var(--s1); border: 1px solid var(--bdr); color: var(--txt); }
  .btn-photo:active { background: var(--s2); }
  .btn-rec { background: var(--red); color: #fff; }
  .btn-rec.recording { background: #333; border: 1px solid var(--red); color: var(--red); }

  .section { padding: 0 12px 12px; }
  .section-title {
    font-size: 10px;
    color: var(--dim);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 8px;
  }
  .gallery-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 12px;
    background: var(--s1);
    border: 1px solid var(--bdr);
    border-radius: 8px;
    margin-bottom: 4px;
  }
  .gallery-item .name { font-size: 11px; }
  .gallery-item .size { font-size: 10px; color: var(--dim); }
  .dl-btn {
    padding: 6px 12px;
    background: var(--blu);
    color: var(--bg);
    border: none;
    border-radius: 6px;
    font-weight: bold;
    cursor: pointer;
    font-size: 12px;
    text-decoration: none;
  }
  .toast {
    position: fixed;
    bottom: 20px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--grn);
    color: var(--bg);
    padding: 10px 20px;
    border-radius: 20px;
    font-weight: bold;
    font-size: 13px;
    opacity: 0;
    transition: opacity 0.3s;
    pointer-events: none;
  }
  .toast.show { opacity: 1; }

  .mode-row {
    display: flex;
    gap: 6px;
    padding: 0 12px 8px;
  }
  .mode-btn {
    flex: 1;
    padding: 8px;
    background: var(--s1);
    border: 1px solid var(--bdr);
    border-radius: 6px;
    color: var(--dim);
    font-family: inherit;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    cursor: pointer;
  }
  .mode-btn.active { background: var(--red); color: #fff; border-color: var(--red); }

  details.cal {
    margin: 0 12px 12px;
    background: var(--s1);
    border: 1px solid var(--bdr);
    border-radius: 8px;
  }
  details.cal summary {
    padding: 10px 12px;
    cursor: pointer;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--dim);
  }
  .slider-row {
    display: grid;
    grid-template-columns: 50px 1fr 60px;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    font-size: 11px;
  }
  .slider-row input[type=range] { width: 100%; }
  .slider-row .val { text-align: right; color: var(--blu); font-family: monospace; }
  .cal-reset {
    width: calc(100% - 24px);
    margin: 8px 12px 12px;
    padding: 8px;
    background: var(--s2);
    border: 1px solid var(--bdr);
    border-radius: 6px;
    color: var(--txt);
    font-family: inherit;
    cursor: pointer;
  }
</style>
</head>
<body>

<div class="viewfinder">
  <img id="stream" src="/stream" alt="Camera Stream">
  <div class="rec-badge" id="recBadge">● REC</div>
</div>

<div class="controls">
  <button class="btn btn-photo" onclick="takePhoto()">📷 Photo</button>
  <button class="btn btn-rec" id="recBtn" onclick="toggleRecord()">⏺ Record</button>
</div>

<div class="mode-row">
  <button class="mode-btn" data-mode="raw" onclick="setMode('raw')">Raw 160°</button>
  <button class="mode-btn active" data-mode="corrected" onclick="setMode('corrected')">Corrected</button>
  <button class="mode-btn" data-mode="cropped" onclick="setMode('cropped')">Cropped</button>
</div>

<details class="cal">
  <summary>⚙ Lens Calibration</summary>
  <div id="sliders"></div>
  <button class="cal-reset" onclick="resetLens()">Reset to 160° Defaults</button>
</details>

<div class="section">
  <div class="section-title">Gallery</div>
  <div id="gallery"></div>
</div>

<div class="toast" id="toast"></div>

<script>
let recording = false;

async function takePhoto() {
  const res = await fetch('/photo', {method: 'POST'});
  const d = await res.json();
  if (d.ok) { showToast('Photo saved: ' + d.file); loadGallery(); }
}

async function toggleRecord() {
  if (!recording) {
    const res = await fetch('/record/start', {method: 'POST'});
    const d = await res.json();
    if (d.ok) {
      recording = true;
      document.getElementById('recBtn').textContent = '⏹ Stop';
      document.getElementById('recBtn').classList.add('recording');
      document.getElementById('recBadge').classList.add('active');
      showToast('Recording started');
    }
  } else {
    const res = await fetch('/record/stop', {method: 'POST'});
    const d = await res.json();
    if (d.ok) {
      recording = false;
      document.getElementById('recBtn').textContent = '⏺ Record';
      document.getElementById('recBtn').classList.remove('recording');
      document.getElementById('recBadge').classList.remove('active');
      showToast('Saved: ' + d.file);
      loadGallery();
    }
  }
}

async function loadGallery() {
  const res = await fetch('/gallery');
  const files = await res.json();
  const el = document.getElementById('gallery');
  if (!files.length) {
    el.innerHTML = '<div style="color:var(--dim);font-size:12px;padding:10px 0">No captures yet</div>';
    return;
  }
  el.innerHTML = files.map(f => `
    <div class="gallery-item">
      <div>
        <div class="name">${f.type === 'photo' ? '📷' : '🎥'} ${f.name}</div>
        <div class="size">${(f.size / 1024).toFixed(1)} KB</div>
      </div>
      <a class="dl-btn" href="/captures/${f.name}" download="${f.name}">↓</a>
    </div>
  `).join('');
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2500);
}

// --- Lens calibration ---
const SLIDERS = [
  ['fx',      'fx',    100,  2000, 1],
  ['fy',      'fy',    100,  2000, 1],
  ['cx',      'cx',    0,    1280, 1],
  ['cy',      'cy',    0,    720,  1],
  ['k1',      'k1',    -1,   1,    0.01],
  ['k2',      'k2',    -1,   1,    0.01],
  ['k3',      'k3',    -1,   1,    0.01],
  ['k4',      'k4',    -1,   1,    0.01],
  ['balance', 'bal',   0,    1,    0.05],
  ['crop_zoom','zoom', 0.5,  2.0,  0.05],
];
const DEFAULTS = {
  mode: 'corrected', stream_w: 1280, stream_h: 720,
  fx: 480, fy: 480, cx: 640, cy: 360,
  k1: -0.32, k2: 0.10, k3: -0.02, k4: 0.0,
  balance: 0.5, crop_zoom: 1.0
};
let debounceTimer = null;

function buildSliders(cfg) {
  const el = document.getElementById('sliders');
  el.innerHTML = SLIDERS.map(([k, label, min, max, step]) => `
    <div class="slider-row">
      <div>${label}</div>
      <input type="range" min="${min}" max="${max}" step="${step}" value="${cfg[k]}"
             oninput="onSlide('${k}', this.value)">
      <div class="val" id="val-${k}">${(+cfg[k]).toFixed(2)}</div>
    </div>
  `).join('');
}

function onSlide(key, value) {
  document.getElementById('val-' + key).textContent = (+value).toFixed(2);
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => pushLens({[key]: parseFloat(value)}), 150);
}

async function pushLens(patch) {
  await fetch('/lens', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(patch)
  });
}

function setMode(mode) {
  document.querySelectorAll('.mode-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.mode === mode);
  });
  pushLens({mode});
}

async function resetLens() {
  await pushLens(DEFAULTS);
  loadLens();
  showToast('Lens reset');
}

async function loadLens() {
  const res = await fetch('/lens');
  const cfg = await res.json();
  buildSliders(cfg);
  document.querySelectorAll('.mode-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.mode === cfg.mode);
  });
}

loadLens();
loadGallery();
setInterval(loadGallery, 10000);
</script>
</body>
</html>
HTMLEOF

# ---- Systemd service ----
echo "[4/4] Setting up systemd service..."
sudo tee /etc/systemd/system/picam-hub.service > /dev/null << SVCEOF
[Unit]
Description=PiCam Hub
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$HUB_DIR
ExecStart=/usr/bin/python3 $HUB_DIR/server.py
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SVCEOF

sudo systemctl daemon-reload
sudo systemctl enable picam-hub.service
sudo systemctl start picam-hub.service

IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "YOUR_PI_IP")

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   ✅ PiCam Hub — Installed!              ║"
echo "╠══════════════════════════════════════════╣"
echo "║                                          ║"
echo "║  Open on your phone:                     ║"
echo "║  http://$IP:8080               ║"
echo "║                                          ║"
echo "║  Features:                               ║"
echo "║   • Live stream (MJPEG)                  ║"
echo "║   • Photo capture                        ║"
echo "║   • Video recording (H264)               ║"
echo "║   • Gallery + download to phone          ║"
echo "║                                          ║"
echo "╚══════════════════════════════════════════╝"
