#!/bin/bash
# ================================================================
#  TV DASHBOARD — HAL ambient info display for the living room TV
# ================================================================
#  Flask app on :8085
#    /           - fullscreen kiosk page (cam bg + overlays)
#    /api/data   - weather, alerts, sun/moon, vitals, service status
#
#  Background = live MJPEG from whichever cam service is running
#  (picam-hub :8080, recorder :8090, petcam :8084). Falls back to
#  animated static + NO SIGNAL if none are up. Never touches the
#  camera itself, so no CSI conflicts.
#
#  Weather = NWS api.weather.gov (free, no key). St. Louis.
#  Run with --autostart to also launch on boot.
# ================================================================

set -e

APP_DIR="$HOME/tv-dashboard"

echo "[1/5] Installing deps..."
sudo apt-get install -y -qq python3-flask

echo "[2/5] Writing app..."
mkdir -p "$APP_DIR/templates"

# ---- app.py ----
cat > "$APP_DIR/app.py" << 'PYEOF'
import json, math, os, shutil, socket, time, threading
import urllib.request
from flask import Flask, render_template, jsonify

LAT, LON = 38.627, -90.199   # St. Louis
NWS_UA = {"User-Agent": "jimbo4-tv-dashboard"}
SERVICES = [
    ("CAM", 8080), ("SDR", 8081), ("SYS", 8082), ("PORTAL", 8083),
    ("PETCAM", 8084), ("RTSP", 8554), ("REC", 8090),
]

app = Flask(__name__)

# ---------- weather (cached, survives API outages) ----------
_wx = {"ts": 0, "hourly": None, "alerts": [], "alerts_ts": 0, "urls": None}
_wx_lock = threading.Lock()

def _get_json(url, timeout=8):
    req = urllib.request.Request(url, headers=NWS_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def _refresh_weather():
    now = time.time()
    with _wx_lock:
        need_wx = now - _wx["ts"] > 600
        need_al = now - _wx["alerts_ts"] > 300
    if need_wx:
        try:
            if not _wx["urls"]:
                pt = _get_json(f"https://api.weather.gov/points/{LAT},{LON}")
                _wx["urls"] = pt["properties"]["forecastHourly"]
            data = _get_json(_wx["urls"])
            periods = data["properties"]["periods"][:8]
            hourly = [{
                "t": p["temperature"],
                "txt": p["shortForecast"],
                "pop": (p.get("probabilityOfPrecipitation") or {}).get("value") or 0,
                "time": p["startTime"][11:16],
                "wind": p.get("windSpeed", ""),
            } for p in periods]
            with _wx_lock:
                _wx["hourly"], _wx["ts"] = hourly, now
        except Exception:
            pass
    if need_al:
        try:
            data = _get_json(f"https://api.weather.gov/alerts/active?point={LAT},{LON}")
            alerts = [f["properties"]["event"] for f in data.get("features", [])]
            with _wx_lock:
                _wx["alerts"], _wx["alerts_ts"] = alerts, now
        except Exception:
            pass

# ---------- sun + moon (pure math, works offline) ----------
def _sun_ut(rise, when):
    zenith, lng_hr = 90.833, LON / 15
    t = when.tm_yday + (((6 if rise else 18) - lng_hr) / 24)
    m = (0.9856 * t) - 3.289
    l = (m + 1.916 * math.sin(math.radians(m))
         + 0.020 * math.sin(math.radians(2 * m)) + 282.634) % 360
    ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(l)))) % 360
    ra = (ra + (math.floor(l / 90) * 90 - math.floor(ra / 90) * 90)) / 15
    sin_dec = 0.39782 * math.sin(math.radians(l))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = (math.cos(math.radians(zenith))
             - sin_dec * math.sin(math.radians(LAT))) / (cos_dec * math.cos(math.radians(LAT)))
    if not -1 <= cos_h <= 1:
        return None
    h = (360 - math.degrees(math.acos(cos_h))) if rise else math.degrees(math.acos(cos_h))
    ut = (h / 15 + ra - 0.06571 * t - 6.622 - lng_hr) % 24
    return ut

def _sun_local(rise):
    lt = time.localtime()
    ut = _sun_ut(rise, lt)
    if ut is None:
        return "--:--"
    off = -(time.altzone if lt.tm_isdst else time.timezone) / 3600
    h = (ut + off) % 24
    return f"{int(h):02d}:{int((h % 1) * 60):02d}"

def _moon():
    age = ((time.time() - 947182440) / 86400) % 29.53058867
    illum = round((1 - math.cos(2 * math.pi * age / 29.53058867)) / 2 * 100)
    names = ["NEW", "WAXING CRESCENT", "FIRST QUARTER", "WAXING GIBBOUS",
             "FULL", "WANING GIBBOUS", "LAST QUARTER", "WANING CRESCENT"]
    idx = int(((age + 1.845) % 29.53058867) / 3.691)
    return {"phase": names[min(idx, 7)], "illum": illum}

# ---------- pi vitals ----------
def _vitals():
    v = {}
    try:
        v["cpu"] = round(int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000, 1)
    except Exception:
        v["cpu"] = None
    try:
        mem = {}
        for line in open("/proc/meminfo"):
            k, val = line.split(":")
            mem[k] = int(val.strip().split()[0])
        v["mem"] = round((1 - mem["MemAvailable"] / mem["MemTotal"]) * 100)
    except Exception:
        v["mem"] = None
    try:
        du = shutil.disk_usage("/")
        v["disk"] = round(du.used / du.total * 100)
    except Exception:
        v["disk"] = None
    try:
        v["load"] = open("/proc/loadavg").read().split()[0]
        up = float(open("/proc/uptime").read().split()[0])
        v["up"] = f"{int(up // 86400)}D {int(up % 86400 // 3600)}H {int(up % 3600 // 60)}M"
    except Exception:
        v["load"], v["up"] = None, None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        v["ip"] = s.getsockname()[0]
        s.close()
    except Exception:
        v["ip"] = "OFFLINE"
    try:
        v["wifi"] = None
        for line in open("/proc/net/wireless"):
            if "wlan" in line:
                v["wifi"] = int(float(line.split()[3]))
    except Exception:
        v["wifi"] = None
    return v

def _services():
    out = []
    for name, port in SERVICES:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                out.append({"name": name, "up": True})
        except Exception:
            out.append({"name": name, "up": False})
    return out

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/data")
def data():
    threading.Thread(target=_refresh_weather, daemon=True).start()
    with _wx_lock:
        hourly, alerts = _wx["hourly"], _wx["alerts"]
    return jsonify({
        "hourly": hourly, "alerts": alerts,
        "sunrise": _sun_local(True), "sunset": _sun_local(False),
        "moon": _moon(), "vitals": _vitals(), "services": _services(),
    })

if __name__ == "__main__":
    _refresh_weather()
    app.run(host="0.0.0.0", port=8085, threaded=True)
PYEOF

# ---- index.html ----
cat > "$APP_DIR/templates/index.html" << 'HTMLEOF'
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>JIMBO4 AMBIENT OPS</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=VT323&family=Space+Grotesk:wght@700&display=swap" rel="stylesheet">
<style>
:root{--bg:#0d0803;--hal:#ff1a1a;--amber:#ffb000;--gold:#d4a017;--cream:#f4ddb6;--teal:#2ec4b6;}
*{margin:0;padding:0;box-sizing:border-box;}
body{background:radial-gradient(ellipse at 50% 40%,#160d04,var(--bg) 70%);color:var(--cream);font-family:'IBM Plex Mono',monospace;
  overflow:hidden;width:100vw;height:100vh;cursor:none;transition:filter 2s;}
body.night{filter:brightness(.72);}

/* corner cam — gilded frame */
#campanel{position:fixed;right:2vw;bottom:8vh;z-index:10;width:24vw;background:#000;
  border:1px solid rgba(212,160,23,.65);outline:1px solid rgba(212,160,23,.28);outline-offset:4px;
  box-shadow:0 0 20px rgba(212,160,23,.18);}
#camlabel{display:flex;justify-content:space-between;padding:.4vh .6vw;font-size:1.5vh;
  color:var(--gold);border-bottom:1px solid rgba(212,160,23,.35);letter-spacing:.2em;}
#camlabel .rec{color:var(--hal);animation:blink 1.6s steps(2) infinite;}
#camwrap{position:relative;height:13vw;}
#cam,#noise{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;}
#cam{filter:sepia(.35) saturate(.8) brightness(.95);display:none;}
#noise{filter:brightness(.5) sepia(.6);}
#nosig{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);z-index:1;white-space:nowrap;
  font-family:'VT323',monospace;font-size:1.5vw;color:var(--hal);letter-spacing:.3em;
  text-shadow:0 0 12px var(--hal);animation:blink 1.6s steps(2) infinite;}
@keyframes blink{50%{opacity:.25;}}

/* CRT scanlines */
body::after{content:"";position:fixed;inset:0;z-index:50;pointer-events:none;
  background:repeating-linear-gradient(0deg,rgba(0,0,0,.16) 0 1px,transparent 1px 3px);}

.panel{position:fixed;z-index:10;background:rgba(13,8,3,.62);border:1px solid rgba(212,160,23,.5);
  outline:1px solid rgba(212,160,23,.2);outline-offset:4px;padding:1vh 1.2vw;backdrop-filter:blur(2px);}

/* alert bar */
#alerts{position:fixed;top:0;left:0;right:0;z-index:40;display:none;text-align:center;
  background:rgba(255,26,26,.18);border-bottom:2px solid var(--hal);color:var(--hal);
  font-family:'VT323',monospace;font-size:2.6vh;padding:.6vh;letter-spacing:.25em;
  text-shadow:0 0 10px var(--hal);animation:blink 2s steps(2) infinite;}

/* header */
#hdr{top:2vh;left:2vw;}
#hdr .eye{color:var(--hal);text-shadow:0 0 12px var(--hal);animation:pulse 3s ease-in-out infinite;}
@keyframes pulse{50%{opacity:.45;}}
#hdr .brand{font-family:'Space Grotesk',sans-serif;font-size:2.6vh;letter-spacing:.18em;}
#hdr .sub{color:var(--amber);font-size:1.7vh;margin-top:.4vh;}
#sunmoon{font-size:1.7vh;margin-top:1vh;color:var(--cream);line-height:1.7;}
#sunmoon b{color:var(--amber);font-weight:400;}

/* weather */
#wx{top:2vh;right:2vw;text-align:right;min-width:22vw;}
#wx .temp{font-family:'VT323',monospace;font-size:9vh;color:var(--amber);
  text-shadow:0 0 14px rgba(255,176,0,.6);line-height:1;font-variant-numeric:tabular-nums;}
#wx .cond{font-size:2vh;color:var(--cream);margin:.5vh 0 1.2vh;}
#hours{display:flex;gap:.6vw;justify-content:flex-end;}
#hours .h{border:1px solid rgba(244,221,182,.25);padding:.5vh .5vw;font-size:1.5vh;text-align:center;}
#hours .h .ht{color:var(--amber);font-family:'VT323',monospace;font-size:2.4vh;}
#hours .h .hp{color:var(--teal);}

/* clock */
#clockbox{bottom:9vh;left:2vw;border:none;background:none;}
#clock{font-family:'VT323',monospace;font-size:19vh;line-height:1;color:var(--cream);
  text-shadow:0 0 22px rgba(244,221,182,.35);font-variant-numeric:tabular-nums;}
#clock .sec{font-size:8vh;color:var(--hal);text-shadow:0 0 14px var(--hal);}
#date{font-size:2.4vh;color:var(--amber);letter-spacing:.3em;margin-top:.5vh;}

/* services */
#svc{top:30vh;right:2vw;font-size:1.8vh;line-height:2;}
#svc .dot{display:inline-block;width:1.1vh;height:1.1vh;border-radius:50%;margin-right:.6vw;}
#svc .up{background:var(--teal);box-shadow:0 0 8px var(--teal);}
#svc .dn{background:#511;}

/* vitals bar */
#vitals{position:fixed;bottom:0;left:0;right:0;z-index:20;background:rgba(13,8,3,.85);
  border-top:1px solid rgba(212,160,23,.5);padding:1.1vh 2vw;font-size:1.9vh;
  display:flex;gap:2vw;justify-content:space-between;font-variant-numeric:tabular-nums;
  white-space:nowrap;overflow:hidden;}
#vitals b{color:var(--amber);font-weight:400;}
#vitals .sep{color:var(--hal);opacity:.6;}
</style>
</head>
<body>
<div id="campanel">
  <div id="camlabel"><span>◉ CAM-01 · 160°</span><span class="rec">● LIVE</span></div>
  <div id="camwrap">
    <img id="cam">
    <canvas id="noise"></canvas>
    <div id="nosig">NO SIGNAL</div>
  </div>
</div>
<div id="alerts"></div>

<div class="panel" id="hdr">
  <div class="brand"><span class="eye">◉</span> JIMBO4 // AMBIENT OPS</div>
  <div class="sub">▓▒░ 160° FIELD CAM &nbsp;·&nbsp; ST LOUIS SECTOR</div>
  <div id="sunmoon">—</div>
</div>

<div class="panel" id="wx">
  <div class="temp" id="temp">--°</div>
  <div class="cond" id="cond">AWAITING NWS LINK_</div>
  <div id="hours"></div>
</div>

<div class="panel" id="clockbox">
  <div id="clock">--:--</div>
  <div id="date">—</div>
</div>

<div class="panel" id="svc">—</div>
<div id="vitals">BOOTING_</div>

<script>
// ---- cam stream: probe candidates, fall back to static ----
const HOST = location.hostname;
const CANDIDATES = [
  `http://${HOST}:8080/stream.mjpeg`, `http://${HOST}:8080/stream`,
  `http://${HOST}:8080/video_feed`,  `http://${HOST}:8090/stream.mjpeg`,
  `http://${HOST}:8084/stream.mjpeg`, `http://${HOST}:8084/video_feed`,
];
const cam = document.getElementById('cam');
let camUp = false;
function probe(i){
  if (camUp || i >= CANDIDATES.length) { if(!camUp) setTimeout(()=>probe(0), 30000); return; }
  const test = new Image();
  const t = setTimeout(()=>{ test.src=''; probe(i+1); }, 4000);
  test.onload = ()=>{ clearTimeout(t); camUp = true;
    cam.src = CANDIDATES[i]; cam.style.display='block';
    noise.style.display='none'; nosig.style.display='none';
    cam.onerror = ()=>{ camUp=false; cam.style.display='none';
      noise.style.display='block'; nosig.style.display='block'; probe(0); };
  };
  test.onerror = ()=>{ clearTimeout(t); probe(i+1); };
  test.src = CANDIDATES[i];
}
// static noise fallback
const noise = document.getElementById('noise'), nosig = document.getElementById('nosig');
const nctx = noise.getContext('2d');
noise.width = 320; noise.height = 180;
setInterval(()=>{
  if (camUp) return;
  const d = nctx.createImageData(320,180);
  for (let i=0;i<d.data.length;i+=4){ const v=Math.random()*70|0; d.data[i]=d.data[i+1]=d.data[i+2]=v; d.data[i+3]=255; }
  nctx.putImageData(d,0,0);
}, 120);
probe(0);

// ---- clock ----
const MO=['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
const DY=['SUN','MON','TUE','WED','THU','FRI','SAT'];
function tick(){
  const n = new Date(), p = x=>String(x).padStart(2,'0');
  document.getElementById('clock').innerHTML =
    `${p(n.getHours())}:${p(n.getMinutes())}<span class="sec">:${p(n.getSeconds())}</span>`;
  document.getElementById('date').textContent =
    `${DY[n.getDay()]} · ${p(n.getDate())} ${MO[n.getMonth()]} ${n.getFullYear()}`;
}
setInterval(tick, 250); tick();

// ---- data poll ----
let sunset=null, sunrise=null;
async function poll(){
  try{
    const d = await (await fetch('/api/data')).json();
    // weather
    if (d.hourly && d.hourly.length){
      document.getElementById('temp').textContent = d.hourly[0].t + '°';
      document.getElementById('cond').textContent = d.hourly[0].txt.toUpperCase();
      document.getElementById('hours').innerHTML = d.hourly.slice(1,6).map(h=>
        `<div class="h">${h.time}<div class="ht">${h.t}°</div><div class="hp">${h.pop}%</div></div>`).join('');
    }
    // alerts
    const ab = document.getElementById('alerts');
    if (d.alerts && d.alerts.length){
      ab.style.display='block';
      ab.textContent = '⚠ ' + d.alerts.join(' · ').toUpperCase() + ' ⚠';
    } else ab.style.display='none';
    // sun/moon
    sunrise = d.sunrise; sunset = d.sunset;
    document.getElementById('sunmoon').innerHTML =
      `SUNRISE <b>${d.sunrise}</b> &nbsp;SUNSET <b>${d.sunset}</b><br>` +
      `MOON <b>${d.moon.phase}</b> ${d.moon.illum}%`;
    // services
    document.getElementById('svc').innerHTML = d.services.map(s=>
      `<span class="dot ${s.up?'up':'dn'}"></span>${s.name}`).join('<br>');
    // vitals
    const v = d.vitals, S = ' <span class="sep">▓</span> ';
    document.getElementById('vitals').innerHTML =
      `CPU <b>${v.cpu ?? '--'}°C</b>${S}MEM <b>${v.mem ?? '--'}%</b>${S}` +
      `DISK <b>${v.disk ?? '--'}%</b>${S}LOAD <b>${v.load ?? '--'}</b>${S}` +
      `UP <b>${v.up ?? '--'}</b>${S}NET <b>${v.ip}</b>` +
      (v.wifi ? `${S}WIFI <b>${v.wifi} dBm</b>` : '');
    // night dim
    const n = new Date(), hm = `${String(n.getHours()).padStart(2,'0')}:${String(n.getMinutes()).padStart(2,'0')}`;
    document.body.classList.toggle('night', sunset && (hm >= sunset || hm < sunrise));
  }catch(e){}
}
setInterval(poll, 15000); poll();
</script>
</body>
</html>
HTMLEOF

echo "[3/5] Installing systemd service..."
sudo tee /etc/systemd/system/tv-dashboard.service > /dev/null << EOF
[Unit]
Description=HAL TV Dashboard
After=network.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 $APP_DIR/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now tv-dashboard

echo "[4/5] Creating desktop icon..."
mkdir -p "$HOME/Desktop"
cat > "$HOME/Desktop/tv-dashboard.desktop" << 'EOF'
[Desktop Entry]
Type=Application
Name=TV Dashboard
Comment=HAL ambient ops display
Exec=chromium --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble http://localhost:8085
Icon=video-display
Terminal=false
EOF
chmod +x "$HOME/Desktop/tv-dashboard.desktop"
gio set "$HOME/Desktop/tv-dashboard.desktop" metadata::trusted true 2>/dev/null || true

if [ "$1" = "--autostart" ]; then
  echo "[4b] Enabling kiosk autostart on boot..."
  mkdir -p "$HOME/.config/autostart"
  cp "$HOME/Desktop/tv-dashboard.desktop" "$HOME/.config/autostart/"
fi

echo "[5/5] Done."
echo ""
echo "  ◉ Dashboard:   http://$(hostname -I | awk '{print $1}'):8085"
echo "  ◉ Desktop icon: double-click 'TV Dashboard' (pick Execute if asked)"
echo "  ◉ Kiosk exit:   Alt+F4"
echo "  ◉ Boot kiosk:   rerun with --autostart"
