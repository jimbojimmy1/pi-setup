#!/bin/bash
# ================================================================
#  Exaggerated Fisheye Livestream
# ================================================================
#  Pipeline: rpicam-vid -> ffmpeg (lenscorrection filter)
#            -> mediamtx (RTSP publish) -> browser/OBS
#
#  Tune the look by editing FX_K1 / FX_K2 in /etc/default/picam-fx
#  (negative = more bulge, positive = pincushion)
# ================================================================

set -e

MTX_DIR="$HOME/mediamtx"
FX_CONF="/etc/default/picam-fx"

echo "[1/5] Stopping conflicting services..."
sudo systemctl stop picam-fx 2>/dev/null || true
sudo systemctl stop mediamtx 2>/dev/null || true
sleep 1

# ---- ffmpeg ----
echo "[2/5] Installing ffmpeg..."
which ffmpeg >/dev/null || sudo apt-get install -y -qq ffmpeg

# ---- Reconfigure mediamtx to accept RTSP publish ----
echo "[3/5] Reconfiguring mediamtx (source: publisher)..."
cat > "$MTX_DIR/mediamtx.yml" << 'YMLEOF'
logLevel: info
logDestinations: [stdout]
rtspAddress: :8554
webrtcAddress: :8889
hlsAddress: :8888
rtmp: no
srt: no

paths:
  cam:
    source: publisher
YMLEOF

# ---- FX config ----
echo "[4/5] Writing FX config..."
sudo tee "$FX_CONF" > /dev/null << CONFEOF
# Edit these to tune the fisheye look, then: sudo systemctl restart picam-fx
WIDTH=960
HEIGHT=720
FPS=20
BITRATE=3M
FX_K1=-0.5
FX_K2=-0.2
CONFEOF

# ---- Pipeline script ----
cat > "$HOME/picam-fx.sh" << 'PIPEEOF'
#!/bin/bash
set -e
source /etc/default/picam-fx

# wait for mediamtx to be listening
until ss -tln | grep -q ':8554 '; do sleep 1; done

rpicam-vid \
    -t 0 \
    --width "$WIDTH" --height "$HEIGHT" \
    --framerate "$FPS" \
    --codec yuv420 \
    --nopreview \
    -o - \
  | ffmpeg -loglevel warning \
    -f rawvideo -pix_fmt yuv420p \
    -s "${WIDTH}x${HEIGHT}" -r "$FPS" -i - \
    -vf "lenscorrection=cx=0.5:cy=0.5:k1=${FX_K1}:k2=${FX_K2}" \
    -c:v libx264 -preset ultrafast -tune zerolatency \
    -b:v "$BITRATE" -g $((FPS*2)) \
    -f rtsp -rtsp_transport tcp \
    rtsp://localhost:8554/cam
PIPEEOF
chmod +x "$HOME/picam-fx.sh"

# ---- Systemd service ----
echo "[5/5] Setting up systemd service..."
sudo tee /etc/systemd/system/picam-fx.service > /dev/null << SVCEOF
[Unit]
Description=PiCam fisheye-fx pipeline
After=network.target mediamtx.service
Requires=mediamtx.service

[Service]
Type=simple
User=$USER
EnvironmentFile=$FX_CONF
ExecStart=/bin/bash $HOME/picam-fx.sh
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SVCEOF

sudo systemctl daemon-reload
sudo systemctl restart mediamtx
sleep 2
sudo systemctl enable picam-fx
sudo systemctl restart picam-fx

sleep 3
IP=$(hostname -I | awk '{print $1}')

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   🐠 Exaggerated Fisheye — Online                ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║                                                  ║"
echo "║  Browser: http://$IP:8889/cam"
echo "║  OBS:     rtsp://$IP:8554/cam"
echo "║                                                  ║"
echo "║  Tune the look:                                  ║"
echo "║   sudo nano $FX_CONF"
echo "║   sudo systemctl restart picam-fx                ║"
echo "║                                                  ║"
echo "║  More bulge:    K1=-0.8  K2=-0.4                 ║"
echo "║  Normal:        K1=0     K2=0                    ║"
echo "║  Pincushion:    K1=0.3   K2=0.1                  ║"
echo "║                                                  ║"
echo "╚══════════════════════════════════════════════════╝"
