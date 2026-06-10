#!/bin/bash
# ================================================================
#  PiCam Recorder v2 — Mobile-first webapp
# ================================================================
#  Single Flask app on :8090
#    /          - MJPEG viewer + record button (works on any phone)
#    /live      - WebRTC viewer (lowest latency for PC)
#    /gallery   - list/download/delete clips
#    /record/{start,stop,status}
#    /stream.mjpeg, /clips/<file>, etc.
# ================================================================

set -e

APP_DIR="$HOME/picam-recorder"
REC_DIR="$HOME/recordings"

echo "[1/6] Stopping old recorder..."
sudo systemctl stop picam-recorder 2>/dev/null || true

echo "[2/6] Installing deps..."
sudo apt-get install -y -qq python3-flask ffmpeg avahi-daemon

mkdir -p "$APP_DIR/templates" "$APP_DIR/static" "$REC_DIR"

# ---- app.py ----
cat > "$APP_DIR/app.py" << 'PYEOF'
import os, subprocess, signal, time, json
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, Response, jsonify, send_from_directory, request, abort

RTSP_URL = "rtsp://localhost:8554/cam"
REC_DIR = Path(os.path.expanduser("~/recordings"))
REC_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
_recorder = {"proc": None, "file": None, "started": None}


def is_mobile(ua: str) -> bool:
    ua = (ua or "").lower()
    return any(k in ua for k in ("iphone", "android", "ipad", "ipod", "mobile"))


@app.route("/")
def index():
    # mobile default = MJPEG (works everywhere). PC default = WebRTC.
    mode = request.args.get("mode")
    if not mode:
        mode = "mjpeg" if is_mobile(request.headers.get("User-Agent", "")) else "webrtc"
    return render_template("index.html", mode=mode, host=request.host.split(":")[0])


@app.route("/stream.mjpeg")
def stream():
    """Pipe RTSP -> MJPEG via ffmpeg's mpjpeg muxer (already multipart)."""
    def gen():
        cmd = [
            "ffmpeg", "-loglevel", "quiet",
            "-rtsp_transport", "tcp", "-i", RTSP_URL,
            "-f", "mpjpeg", "-q:v", "6", "-r", "15", "-",
        ]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while True:
                chunk = p.stdout.read(8192)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                p.terminate(); p.wait(timeout=2)
            except Exception:
                p.kill()
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=ffmpeg")


@app.route("/record/start", methods=["POST"])
def record_start():
    if _recorder["proc"] and _recorder["proc"].poll() is None:
        return jsonify(ok=False, error="already recording", file=_recorder["file"])
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"clip_{ts}.mp4"
    fpath = REC_DIR / fname
    cmd = [
        "ffmpeg", "-loglevel", "quiet", "-y",
        "-rtsp_transport", "tcp", "-i", RTSP_URL,
        "-c", "copy", "-movflags", "+faststart",
        "-f", "mp4", str(fpath),
    ]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    _recorder.update(proc=p, file=fname, started=time.time())
    return jsonify(ok=True, file=fname)


@app.route("/record/stop", methods=["POST"])
def record_stop():
    p = _recorder["proc"]
    if not p or p.poll() is not None:
        return jsonify(ok=False, error="not recording")
    # ffmpeg needs 'q' or SIGINT to finalize MP4 cleanly
    try:
        p.send_signal(signal.SIGINT)
        p.wait(timeout=5)
    except Exception:
        p.terminate(); p.wait()
    fname = _recorder["file"]
    _recorder.update(proc=None, file=None, started=None)
    return jsonify(ok=True, file=fname)


@app.route("/record/status")
def record_status():
    p = _recorder["proc"]
    active = bool(p and p.poll() is None)
    elapsed = int(time.time() - _recorder["started"]) if active else 0
    return jsonify(active=active, file=_recorder["file"], elapsed=elapsed)


@app.route("/gallery")
def gallery():
    clips = []
    for f in sorted(REC_DIR.glob("*.mp4"), reverse=True):
        st = f.stat()
        clips.append({
            "name": f.name,
            "size_mb": round(st.st_size / 1024 / 1024, 1),
            "when": datetime.fromtimestamp(st.st_mtime).strftime("%b %d %H:%M"),
        })
    return render_template("gallery.html", clips=clips)


@app.route("/clips/<path:fname>")
def clip(fname):
    return send_from_directory(REC_DIR, fname, conditional=True)


@app.route("/clips/<path:fname>", methods=["DELETE"])
def clip_delete(fname):
    f = REC_DIR / fname
    if not f.is_file() or ".." in fname:
        abort(404)
    f.unlink()
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8090, threaded=True)
PYEOF

# ---- index.html ----
cat > "$APP_DIR/templates/index.html" << 'HTMLEOF'
<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>PiCam</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body class="viewer">

<div class="stage" id="stage">
  {% if mode == 'webrtc' %}
    <video id="v" autoplay playsinline muted></video>
  {% else %}
    <img id="v" src="/stream.mjpeg" alt="stream">
  {% endif %}
</div>

<div class="hud" id="hud">
  <div class="top">
    <a class="chip" href="/gallery">▦ Clips</a>
    <span class="mode">{{ mode|upper }}</span>
    <a class="chip" href="/?mode={{ 'webrtc' if mode=='mjpeg' else 'mjpeg' }}">↻ {{ 'WebRTC' if mode=='mjpeg' else 'MJPEG' }}</a>
  </div>
  <div class="bottom">
    <div class="timer" id="timer">00:00</div>
    <button class="rec" id="rec">●</button>
    <button class="fs" id="fs">⛶</button>
  </div>
</div>

<script>
const MODE = "{{ mode }}";
const HOST = "{{ host }}";

// auto-hide HUD after 3s of no touch
const hud = document.getElementById('hud');
let hideT;
function pokeHud() {
  hud.classList.remove('hidden');
  clearTimeout(hideT);
  hideT = setTimeout(() => hud.classList.add('hidden'), 3000);
}
document.body.addEventListener('click', pokeHud);
document.body.addEventListener('touchstart', pokeHud);
pokeHud();

// fullscreen
document.getElementById('fs').onclick = (e) => {
  e.stopPropagation();
  if (!document.fullscreenElement) document.documentElement.requestFullscreen?.();
  else document.exitFullscreen?.();
};

// recording
const recBtn = document.getElementById('rec');
const timer = document.getElementById('timer');
let recActive = false, t0 = 0, tickT;
function fmt(s) { const m=Math.floor(s/60), x=s%60; return String(m).padStart(2,'0')+':'+String(x).padStart(2,'0'); }
function startTick() { t0 = Date.now(); tickT = setInterval(()=>{ timer.textContent = fmt(Math.floor((Date.now()-t0)/1000)); }, 500); }
function stopTick() { clearInterval(tickT); timer.textContent = '00:00'; }

async function syncStatus() {
  try {
    const r = await fetch('/record/status').then(r=>r.json());
    if (r.active && !recActive) { recActive = true; recBtn.classList.add('on'); t0 = Date.now() - r.elapsed*1000; startTick(); }
    else if (!r.active && recActive) { recActive = false; recBtn.classList.remove('on'); stopTick(); }
  } catch(e){}
}
syncStatus(); setInterval(syncStatus, 3000);

recBtn.onclick = async (e) => {
  e.stopPropagation();
  const url = recActive ? '/record/stop' : '/record/start';
  const r = await fetch(url, {method:'POST'}).then(r=>r.json());
  if (r.ok) {
    recActive = !recActive;
    recBtn.classList.toggle('on', recActive);
    if (recActive) startTick(); else stopTick();
  }
};

// WebRTC mode
if (MODE === 'webrtc') {
  (async () => {
    const v = document.getElementById('v');
    const pc = new RTCPeerConnection({iceServers:[{urls:'stun:stun.l.google.com:19302'}]});
    pc.addTransceiver('video', {direction:'recvonly'});
    let stream = new MediaStream();
    pc.ontrack = e => { stream.addTrack(e.track); v.srcObject = stream; };
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    const res = await fetch(`http://${HOST}:8889/cam/whep`, {
      method:'POST', headers:{'Content-Type':'application/sdp'}, body: offer.sdp
    });
    if (res.ok) await pc.setRemoteDescription({type:'answer', sdp: await res.text()});
  })();
}
</script>
</body></html>
HTMLEOF

# ---- gallery.html ----
cat > "$APP_DIR/templates/gallery.html" << 'HTMLEOF'
<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>PiCam Clips</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body class="gallery">
<header><a href="/" class="chip">← Live</a><h1>◉ CLIPS</h1><span></span></header>

<main>
{% if not clips %}<p class="empty">No clips yet. Hit record on the live view.</p>{% endif %}
{% for c in clips %}
<div class="clip">
  <video src="/clips/{{ c.name }}" preload="metadata" controls playsinline></video>
  <div class="meta">
    <div class="name">{{ c.name }}</div>
    <div class="sub">{{ c.when }} · {{ c.size_mb }} MB</div>
    <div class="row">
      <a href="/clips/{{ c.name }}" download class="btn">⇩ Save</a>
      <button class="btn del" data-f="{{ c.name }}">🗑</button>
    </div>
  </div>
</div>
{% endfor %}
</main>

<script>
document.querySelectorAll('.del').forEach(b => b.onclick = async () => {
  if (!confirm('Delete '+b.dataset.f+'?')) return;
  await fetch('/clips/'+b.dataset.f, {method:'DELETE'});
  b.closest('.clip').remove();
});
</script>
</body></html>
HTMLEOF

# ---- style.css (HAL theme, mobile-first) ----
cat > "$APP_DIR/static/style.css" << 'CSSEOF'
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
:root {
  --bg:#0a0606; --hal:#ff1a1a; --amber:#ffb000; --cream:#f4ddb6; --dim:#2a1010;
}
html,body { background:var(--bg); color:var(--cream); font-family:'Courier New',monospace; min-height:100vh; overflow-x:hidden; }

/* ---- VIEWER ---- */
body.viewer { overflow:hidden; height:100vh; height:100dvh; }
.stage { position:fixed; inset:0; display:flex; align-items:center; justify-content:center; background:#000; }
.stage > * { width:100%; height:100%; object-fit:contain; }

.hud { position:fixed; inset:0; pointer-events:none; transition:opacity .3s; display:flex; flex-direction:column; justify-content:space-between; }
.hud.hidden { opacity:0; }
.hud > * { pointer-events:auto; }

.top {
  display:flex; justify-content:space-between; align-items:center;
  padding:max(env(safe-area-inset-top),12px) 14px 8px;
  background:linear-gradient(to bottom, rgba(0,0,0,.7), transparent);
}
.bottom {
  display:flex; justify-content:space-between; align-items:center;
  padding:8px 18px max(env(safe-area-inset-bottom),18px);
  background:linear-gradient(to top, rgba(0,0,0,.7), transparent);
}

.chip {
  display:inline-block; padding:8px 12px; background:rgba(20,8,8,.85);
  border:1px solid var(--hal); color:var(--cream); font-size:12px;
  text-transform:uppercase; letter-spacing:2px; text-decoration:none;
}
.mode { font-size:10px; color:var(--amber); letter-spacing:3px; }

.timer {
  font-family:'Courier New',monospace; font-size:18px; color:var(--amber);
  background:rgba(20,8,8,.85); padding:8px 12px; border:1px solid var(--dim);
  min-width:78px; text-align:center; font-variant-numeric:tabular-nums;
}

.rec {
  width:78px; height:78px; border-radius:50%; border:3px solid var(--hal);
  background:rgba(20,8,8,.85); color:var(--hal); font-size:36px; line-height:1;
  cursor:pointer; box-shadow:0 0 24px rgba(255,26,26,.4); transition:all .15s;
}
.rec.on {
  background:var(--hal); color:#000;
  animation:pulse 1.2s infinite; box-shadow:0 0 40px rgba(255,26,26,.8);
}
@keyframes pulse { 0%,100%{transform:scale(1)} 50%{transform:scale(1.06)} }

.fs {
  width:48px; height:48px; background:rgba(20,8,8,.85); border:1px solid var(--hal);
  color:var(--cream); font-size:20px; cursor:pointer;
}

/* ---- GALLERY ---- */
body.gallery { padding-bottom:40px; }
header {
  display:flex; align-items:center; justify-content:space-between;
  padding:max(env(safe-area-inset-top),14px) 14px 14px;
  border-bottom:1px solid var(--dim); position:sticky; top:0; background:var(--bg); z-index:10;
}
header h1 { color:var(--hal); font-size:15px; letter-spacing:4px; }
main { padding:14px; display:grid; grid-template-columns:1fr; gap:14px; }
@media(min-width:700px){ main{ grid-template-columns:repeat(2,1fr);} }
@media(min-width:1100px){ main{ grid-template-columns:repeat(3,1fr);} }

.clip { background:#120808; border:1px solid var(--dim); }
.clip video { width:100%; display:block; background:#000; aspect-ratio:16/9; object-fit:cover; }
.meta { padding:10px 12px; }
.name { color:var(--amber); font-size:13px; word-break:break-all; }
.sub { color:#888; font-size:11px; margin-top:2px; }
.row { display:flex; gap:8px; margin-top:10px; }
.btn {
  flex:1; padding:10px; background:#1a0a0a; color:var(--cream);
  border:1px solid var(--hal); text-align:center; font-family:inherit;
  font-size:12px; letter-spacing:1px; text-transform:uppercase; cursor:pointer; text-decoration:none;
}
.btn.del { flex:0 0 60px; }
.btn:hover { background:var(--hal); color:#000; }
.empty { text-align:center; padding:60px 20px; color:#666; }
CSSEOF

# ---- systemd ----
echo "[3/6] Writing systemd service..."
sudo tee /etc/systemd/system/picam-recorder.service > /dev/null << SVCEOF
[Unit]
Description=PiCam Recorder v2
After=network.target mediamtx.service
Wants=mediamtx.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 $APP_DIR/app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SVCEOF

# ---- avahi alias for picam.local ----
echo "[4/6] Setting up picam.local mDNS alias..."
sudo tee /etc/avahi/services/picam.service > /dev/null << AVAHIEOF
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi.dtd">
<service-group>
  <name replace-wildcards="yes">picam</name>
  <service>
    <type>_http._tcp</type>
    <port>8090</port>
  </service>
</service-group>
AVAHIEOF
sudo systemctl restart avahi-daemon

echo "[5/6] Starting service..."
sudo systemctl daemon-reload
sudo systemctl enable picam-recorder
sudo systemctl restart picam-recorder

sleep 2
IP=$(hostname -I | awk '{print $1}')

echo "[6/6] Status:"
sudo systemctl status picam-recorder --no-pager | head -8

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   📱 PiCam Recorder v2 — Live                     ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║  Phone (any browser):                            ║"
echo "║   http://$IP:8090"
echo "║   http://$(hostname).local:8090"
echo "║                                                  ║"
echo "║  Tap big red ● to record. Tap ⛶ for fullscreen.  ║"
echo "║  Clips saved in: ~/recordings/                   ║"
echo "║  Gallery → tap Save → phone gets the .mp4        ║"
echo "║                                                  ║"
echo "║  PC: same URL — auto-switches to WebRTC          ║"
echo "╚══════════════════════════════════════════════════╝"
