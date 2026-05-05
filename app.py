from flask import Flask, request, session, redirect, jsonify
import math, time, os

app = Flask(__name__)
app.secret_key = "gps-game"

# =====================
# 데이터
# =====================
users = {}
money = {}
last_gps = {}
gps_success = {}

# 부활 시스템
reviving = {}  # target: (reviver, end_time)

# 위치 (관리자에서 바꿀 수 있음)
TARGET_LAT = 37.2756
TARGET_LON = 127.9025
RADIUS_M = 120

REVIVE_RANGE = 20
REVIVE_TIME = 5

# =====================
def distance_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2-lat1)
    dlon = math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))

# =====================
@app.route("/", methods=["GET","POST"])
def index():
    if request.method == "POST":
        name = request.form.get("name")
        if not name:
            return "이름 없음"

        session["name"] = name

        users.setdefault(name, "alive")
        money.setdefault(name, 0)
        gps_success.setdefault(name, False)

        return redirect("/game")

    return """
    <meta name=viewport content="width=device-width,initial-scale=1">
    <form method=post>
    <h2>닉네임</h2>
    <input name=name>
    <button>입장</button>
    </form>
    """

# =====================
@app.route("/game")
def game():
    n = session.get("name")
    if not n:
        return redirect("/")

    return f"""
<!doctype html>
<meta name=viewport content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>

<style>
body {{margin:0;background:#0f172a;color:white;font-family:system-ui}}
#map {{height:60vh}}
.btn {{width:100%;padding:15px;margin-top:10px;border:none;border-radius:10px}}
</style>

<h2>👤 {n}</h2>
💰 돈: {money[n]}<br>
<div id="status">📡 위치 확인중...</div>

<button class="btn" onclick="revive()">❤️ 부활</button>

<div id="map"></div>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
<script>

let map = L.map('map').setView([{TARGET_LAT},{TARGET_LON}],17);

L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);

// 내 위치
let me=null;

function sendGPS(lat, lon){{
    fetch("/gps", {{
        method:"POST",
        headers:{{"Content-Type":"application/json"}},
        body:JSON.stringify({{lat:lat, lon:lon}})
    }})
    .then(r=>r.text())
    .then(t=>document.getElementById("status").innerText = t);
}}

function updatePosition(p){{
    let lat=p.coords.latitude;
    let lon=p.coords.longitude;

    if(me) map.removeLayer(me);
    me = L.marker([lat,lon]).addTo(map).bindPopup("📍 나");

    map.setView([lat,lon],17);

    sendGPS(lat, lon);
}}

navigator.geolocation.watchPosition(updatePosition);

// 부활 버튼
function revive(){{
    let target = prompt("살릴 사람 이름");

    fetch("/revive", {{
        method:"POST",
        headers:{{"Content-Type":"application/json"}},
        body:JSON.stringify({{target:target}})
    }})
    .then(r=>r.text())
    .then(alert);
}}

</script>
"""

# =====================
@app.route("/gps", methods=["POST"])
def gps():
    n = session.get("name")
    data = request.get_json(silent=True) or {}

    lat = data.get("lat")
    lon = data.get("lon")

    if lat is None or lon is None:
        return "GPS 없음"

    last_gps[n] = (lat, lon, time.time())

    # 🔥 부활 판정
    for target in list(reviving):
        reviver, end = reviving[target]

        if time.time() >= end:
            if target in users:
                users[target] = "alive"
                del reviving[target]

    return "📍 위치 업데이트"

# =====================
@app.route("/players")
def players():
    result = {}

    for name in last_gps:
        lat, lon, _ = last_gps[name]
        result[name] = {
            "lat": lat,
            "lon": lon,
            "alive": users.get(name) == "alive"
        }

    return jsonify(result)

# =====================
@app.route("/revive", methods=["POST"])
def revive_api():
    me = session.get("name")
    data = request.get_json()

    target = data.get("target")

    if not me or target not in users:
        return "오류"

    if users.get(target) != "dead":
        return "살아있음"

    if me not in last_gps or target not in last_gps:
        return "위치 없음"

    mlat, mlon, _ = last_gps[me]
    tlat, tlon, _ = last_gps[target]

    dist = distance_m(mlat, mlon, tlat, tlon)

    if dist > REVIVE_RANGE:
        return "❌ 너무 멀다"

    reviving[target] = (me, time.time() + REVIVE_TIME)

    return f"❤️ {target} 살리는 중 (5초)"

# =====================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))