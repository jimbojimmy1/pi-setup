#!/bin/bash
# ================================================================
#  Low-Latency Livestream — mediamtx + rpicam
# ================================================================
#  WebRTC (browser): http://<pi>:8889/cam   (~150ms)
#  RTSP (OBS):       rtsp://<pi>:8554/cam   (~250ms)
#
#  Stops picam-hub so we own the camera. Run with:
#    chmod +x setup-livestream.sh && ./setup-livestream.sh
# ================================================================

set -e

MTX_DIR="$HOME/mediamtx"
ARCH="armv7"  # Pi 3 is 32-bit armv7. For 64-bit Pi 4 swap to arm64v8.
MTX_VERSION="v1.9.3"

echo "╔══════════════════════════════════════════╗"
echo "║   Low-Latency Livestream Setup           ║"
echo "╚══════════════════════════════════════════╝"

# ---- Stop conflicting services ----
echo "[1/5] Stopping camera consumers..."
sudo systemctl stop picam-hub 2>/dev/null || true
sudo systemctl stop birdcam birdcam-web 2>/dev/null || true
sudo pkill -f rpicam 2>/dev/null || true
sleep 1

# ---- Detect arch ----
if [ "$(uname -m)" = "aarch64" ]; then
    ARCH="arm64v8"
fi

# ---- Download mediamtx ----
echo "[2/5] Installing mediamtx ($ARCH)..."
mkdir -p "$MTX_DIR"
cd "$MTX_DIR"
if [ ! -f mediamtx ]; then
    URL="https://github.com/bluenviron/mediamtx/releases/download/${MTX_VERSION}/mediamtx_${MTX_VERSION}_linux_${ARCH}.tar.gz"
    curl -fsSL "$URL" -o mtx.tar.gz
    tar -xzf mtx.tar.gz
    rm mtx.tar.gz
fi
chmod +x mediamtx

# ---- Config ----
echo "[3/5] Writing mediamtx config..."
cat > "$MTX_DIR/mediamtx.yml" << 'YMLEOF'
# Low-latency streaming config
logLevel: info
logDestinations: [stdout]

# RTSP for OBS / VLC
rtspAddress: :8554
# WebRTC for browser (lowest latency)
webrtcAddress: :8889
# HLS as a fallback (works on iOS)
hlsAddress: :8888
# Disable RTMP / SRT (don't need them)
rtmp: no
srt: no

paths:
  cam:
    source: rpiCamera
    rpiCameraWidth: 1280
    rpiCameraHeight: 720
    rpiCameraFPS: 30
    rpiCameraBitrate: 4000000
    rpiCameraProfile: baseline
    rpiCameraLevel: '4.1'
    rpiCameraIDRPeriod: 30
YMLEOF

# ---- Systemd service ----
echo "[4/5] Setting up systemd service..."
sudo tee /etc/systemd/system/mediamtx.service > /dev/null << SVCEOF
[Unit]
Description=mediamtx low-latency stream server
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$MTX_DIR
ExecStart=$MTX_DIR/mediamtx $MTX_DIR/mediamtx.yml
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SVCEOF

sudo systemctl daemon-reload
sudo systemctl enable mediamtx.service
sudo systemctl restart mediamtx.service

# ---- Done ----
sleep 2
IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "YOUR_PI_IP")

echo ""
echo "[5/5] Status:"
sudo systemctl status mediamtx --no-pager | head -8

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   ✅ Livestream Online                            ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║                                                  ║"
echo "║  Browser (lowest latency, ~150ms):               ║"
echo "║   http://$IP:8889/cam"
echo "║                                                  ║"
echo "║  OBS — Sources → Media Source → uncheck local    ║"
echo "║   rtsp://$IP:8554/cam"
echo "║   (then enable Virtual Camera in OBS to use      ║"
echo "║    it in games / Discord / Zoom)                 ║"
echo "║                                                  ║"
echo "║  NOTE: picam-hub is stopped (camera conflict).   ║"
echo "║  To swap back: sudo systemctl stop mediamtx &&   ║"
echo "║                sudo systemctl start picam-hub    ║"
echo "║                                                  ║"
echo "╚══════════════════════════════════════════════════╝"
