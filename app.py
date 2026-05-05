from flask import Flask, request, session, redirect, jsonify
import math, time, os, json, random

app = Flask(__name__)
app.secret_key = "gps-game"

# =====================
# 데이터
# =====================
users = {}
money = {}
last_gps = {}

airdrops = []  # [{lat, lon, active}]

DATA_FILE = "target.json"

# =====================
# 좌표 로드/저장
# =====================
def load_target():
    global TARGET_LAT, TARGET_LON
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            data = json.load(f)
            TARGET_LAT = data["lat"]
            TARGET_LON = data["lon"]
    else:
        TARGET_LAT = 37.2756
        TARGET_LON = 127.9025

def save_target(lat, lon):
    with open(DATA_FILE, "w") as f:
        json.dump({"lat": lat, "lon": lon}, f)

load_target()

RADIUS_M = 120
ADMIN_PW = "0808"

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
        session["name"] = name

        users.setdefault(name, "alive")
        money.setdefault(name, 0)

        return redirect("/game")

    return """
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
body {{margin:0;background:#0f172a;color:white}}
#map {{height:60vh}}
.btn {{width:100%;padding:12px;margin-top:5px}}
</style>

<h3>👤 {n}</h3>
💰 {money[n]}원<br>

<a href="/admin">👑 관리자</a>

<div id="map"></div>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
<script>

let map = L.map('map').setView([{TARGET_LAT},{TARGET_LON}],17);

L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);

// 🎯 목표
L.circle([{TARGET_LAT},{TARGET_LON}], {{
    radius:{RADIUS_M},
    color:"green"
}}).addTo(map);

// 📍 내 위치
let me=null;

function update(p){{
    let lat=p.coords.latitude;
    let lon=p.coords.longitude;

    if(me) map.removeLayer(me);
    me = L.marker([lat,lon]).addTo(map);

    map.setView([lat,lon],17);

    fetch("/gps", {{
        method:"POST",
        headers:{{"Content-Type":"application/json"}},
        body:JSON.stringify({{lat:lat, lon:lon}})
    }});
}}

navigator.geolocation.watchPosition(update);

// 🪂 에어드랍 표시
let drops=[];

function loadDrops(){{
    fetch("/airdrops")
    .then(r=>r.json())
    .then(data=>{{
        drops.forEach(d=>map.removeLayer(d));
        drops=[];

        data.forEach(p=>{{
            let m = L.marker([p.lat,p.lon]).addTo(map)
                .bindPopup("🪂 에어드랍");
            drops.push(m);
        }});
    }});
}}

setInterval(loadDrops, 3000);

</script>
"""

# =====================
@app.route("/gps", methods=["POST"])
def gps():
    n = session.get("name")
    data = request.get_json()

    last_gps[n] = (data["lat"], data["lon"], time.time())
    return "ok"

# =====================
@app.route("/airdrops")
def get_drops():
    return jsonify(airdrops)

# =====================
@app.route("/admin", methods=["GET","POST"])
def admin():
    if request.method == "POST":
        if request.form.get("pw") == ADMIN_PW:
            session["admin"] = True

        elif request.form.get("action") == "drop" and session.get("admin"):
            # 🪂 대한민국 랜덤 위치
            lat = random.uniform(33.0, 38.5)
            lon = random.uniform(125.0, 129.5)

            airdrops.append({"lat":lat,"lon":lon})
    
    if not session.get("admin"):
        return """
        <form method=post>
        비번:<input name=pw>
        <button>접속</button>
        </form>
        """

    return f"""
    <h2>관리자</h2>

    <form method=post>
    <button name=action value=drop>🪂 에어드랍 생성</button>
    </form>

    <h3>📍 목표 위치 설정</h3>
    <div id="map" style="height:50vh"></div>
    <p id="coords"></p>
    <button onclick="save()">저장</button>

    <script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
    <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>

    <script>
    let selected=null;

    let map = L.map('map').setView([{TARGET_LAT},{TARGET_LON}],17);
    L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);

    map.on('click', e=>{{
        selected={{lat:e.latlng.lat, lon:e.latlng.lng}};
        document.getElementById("coords").innerText =
            selected.lat + "," + selected.lon;
    }});

    function save(){{
        fetch("/set_target", {{
            method:"POST",
            headers:{{"Content-Type":"application/json"}},
            body:JSON.stringify(selected)
        }})
        .then(r=>r.text())
        .then(alert);
    }}
    </script>
    """

# =====================
@app.route("/set_target", methods=["POST"])
def set_target():
    if not session.get("admin"):
        return "권한 없음"

    global TARGET_LAT, TARGET_LON

    data = request.get_json()
    TARGET_LAT = data["lat"]
    TARGET_LON = data["lon"]

    save_target(TARGET_LAT, TARGET_LON)

    return "저장 완료"

# =====================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))