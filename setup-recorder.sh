#!/bin/bash
# ================================================================
#  Browser Recorder Page
# ================================================================
#  Serves a webpage at :8090 that:
#   - Plays the WebRTC stream from mediamtx
#   - Records to webm via MediaRecorder API
#   - Downloads the file to your PC when you stop
# ================================================================

set -e

REC_DIR="$HOME/picam-recorder"
mkdir -p "$REC_DIR"

# ---- record page ----
cat > "$REC_DIR/index.html" << 'HTMLEOF'
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>PiCam Recorder</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Courier New', monospace; }
  body { background: #0a0606; color: #f4ddb6; min-height: 100vh; padding: 20px; }
  h1 { color: #ff1a1a; font-size: 18px; text-transform: uppercase; letter-spacing: 3px; margin-bottom: 12px; }
  .meta { font-size: 11px; color: #888; margin-bottom: 14px; }
  video { width: 100%; max-width: 1280px; background: #000; border: 1px solid #ff1a1a; box-shadow: 0 0 20px rgba(255,26,26,0.3); }
  .row { display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
  button {
    padding: 12px 24px; background: #1a0a0a; color: #f4ddb6;
    border: 1px solid #ff1a1a; font-family: inherit; font-size: 13px;
    text-transform: uppercase; letter-spacing: 2px; cursor: pointer;
  }
  button:hover { background: #ff1a1a; color: #000; }
  button.rec { background: #ff1a1a; color: #000; font-weight: bold; }
  button.rec.active { animation: pulse 1s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1 } 50% { opacity: 0.5 } }
  button:disabled { opacity: 0.3; cursor: not-allowed; }
  .status { margin-top: 10px; font-size: 11px; color: #ffb000; }
  .log { margin-top: 14px; padding: 8px; background: #1a0606; font-size: 10px; color: #888; max-height: 100px; overflow-y: auto; border: 1px solid #2a1010; }
</style>
</head>
<body>
<h1>◉ PiCam Recorder</h1>
<div class="meta" id="meta">Source: rtsp / webrtc · waiting for stream...</div>

<video id="v" autoplay playsinline muted></video>

<div class="row">
  <button id="play">▶ Connect</button>
  <button class="rec" id="rec" disabled>● Record</button>
  <button id="snap" disabled>📷 Snapshot</button>
</div>

<div class="status" id="status">idle</div>
<div class="log" id="log"></div>

<script>
const PI_HOST = location.hostname;
const WHEP_URL = `http://${PI_HOST}:8889/cam/whep`;
const v = document.getElementById('v');
const log = m => { const l = document.getElementById('log'); l.innerHTML += m + '<br>'; l.scrollTop = l.scrollHeight; };
const setStatus = m => document.getElementById('status').textContent = m;

let pc, recorder, chunks = [], stream;

async function connect() {
  log('Connecting WHEP → ' + WHEP_URL);
  pc = new RTCPeerConnection({ iceServers: [{urls:'stun:stun.l.google.com:19302'}] });
  pc.addTransceiver('video', { direction: 'recvonly' });
  pc.addTransceiver('audio', { direction: 'recvonly' });

  pc.ontrack = e => {
    log('Track: ' + e.track.kind);
    if (!stream) stream = new MediaStream();
    stream.addTrack(e.track);
    v.srcObject = stream;
    document.getElementById('rec').disabled = false;
    document.getElementById('snap').disabled = false;
    setStatus('streaming');
  };

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  const res = await fetch(WHEP_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/sdp' },
    body: offer.sdp
  });
  if (!res.ok) { log('WHEP failed: ' + res.status); setStatus('error'); return; }
  const answer = await res.text();
  await pc.setRemoteDescription({ type: 'answer', sdp: answer });
  log('Connected');
}

function toggleRecord() {
  const btn = document.getElementById('rec');
  if (!recorder || recorder.state === 'inactive') {
    chunks = [];
    const mime = MediaRecorder.isTypeSupported('video/webm;codecs=vp9')
      ? 'video/webm;codecs=vp9' : 'video/webm';
    recorder = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 4_000_000 });
    recorder.ondataavailable = e => { if (e.data.size > 0) chunks.push(e.data); };
    recorder.onstop = () => {
      const blob = new Blob(chunks, { type: mime });
      const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0,19);
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `picam_${ts}.webm`;
      a.click();
      log('Saved ' + (blob.size/1024/1024).toFixed(2) + ' MB → ' + a.download);
    };
    recorder.start(1000);
    btn.textContent = '■ Stop';
    btn.classList.add('active');
    setStatus('recording');
  } else {
    recorder.stop();
    btn.textContent = '● Record';
    btn.classList.remove('active');
    setStatus('streaming');
  }
}

function snapshot() {
  const c = document.createElement('canvas');
  c.width = v.videoWidth; c.height = v.videoHeight;
  c.getContext('2d').drawImage(v, 0, 0);
  c.toBlob(b => {
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0,19);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b);
    a.download = `picam_${ts}.png`;
    a.click();
  }, 'image/png');
}

document.getElementById('play').onclick = connect;
document.getElementById('rec').onclick = toggleRecord;
document.getElementById('snap').onclick = snapshot;
// auto-connect
connect();
</script>
</body>
</html>
HTMLEOF

# ---- systemd service ----
sudo tee /etc/systemd/system/picam-recorder.service > /dev/null << SVCEOF
[Unit]
Description=PiCam recorder static page
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$REC_DIR
ExecStart=/usr/bin/python3 -m http.server 8090
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SVCEOF

sudo systemctl daemon-reload
sudo systemctl enable picam-recorder
sudo systemctl restart picam-recorder

sleep 1
IP=$(hostname -I | awk '{print $1}')

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   🎬 PiCam Recorder Page                          ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║                                                  ║"
echo "║  Open in your PC browser:                        ║"
echo "║   http://$IP:8090"
echo "║                                                  ║"
echo "║  ▶ Connect = subscribe to WebRTC stream          ║"
echo "║  ● Record  = saves .webm to your PC Downloads    ║"
echo "║  📷 Snapshot = saves .png                         ║"
echo "║                                                  ║"
echo "╚══════════════════════════════════════════════════╝"
