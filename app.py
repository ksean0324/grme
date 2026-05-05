from flask import Flask, request, session, redirect, jsonify
import math, time, os, random

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "gps-game")

# =====================
# 데이터
# =====================
users = {}
money = {}
last_gps = {}
gps_success = {}

items = {}           # 개인 아이템
world_items = {}     # 지도 아이템
alliances = {}
pending_attacks = {}
ally_requests = {}

# 에어드랍
airdrop = {"active": False, "lat":0, "lon":0, "target_lat":0, "target_lon":0}

ADMIN_PW = "0808"

# 위치 (가곡로 70)
TARGET_LAT = 37.2756
TARGET_LON = 127.9025
RADIUS_M = 120

ATTACK_RANGE = 30
DELAY = 5

# =====================
def distance_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2-lat1)
    dlon = math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))

def in_safezone(lat, lon):
    return distance_m(lat, lon, TARGET_LAT, TARGET_LON) <= RADIUS_M

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

    if users.get(n) == "dead":
        return "💀 죽음"

    return f"""
<!doctype html>
<meta name=viewport content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>

<style>
body {{margin:0;background:#0f172a;color:white}}
#map {{height:60vh}}
.btn {{width:100%;padding:15px;margin-top:10px}}
</style>

<h2>{n} / 💰 {money[n]}</h2>
<div id="dist"></div>

<button class="btn" onclick="sendGPS()">📡 GPS</button>
<button class="btn" onclick="attack()">⚔️ 공격</button>
<button class="btn" onclick="gacha()">🎁 뽑기</button>

<div id="map"></div>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
<script>

let map = L.map('map').setView([{TARGET_LAT},{TARGET_LON}],17);

L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);

// 안전구역
L.circle([{TARGET_LAT},{TARGET_LON}], {{
 radius:{RADIUS_M},
 color:"green"
}}).addTo(map);

// 내 위치
let me=null;

function updatePosition(p){{
 let lat=p.coords.latitude;
 let lon=p.coords.longitude;

 if(me) map.removeLayer(me);
 me=L.marker([lat,lon]).addTo(map);

 map.setView([lat,lon],17);

 fetch("/gps", {{
  method:"POST",
  headers:{{"Content-Type":"application/json"}},
  body:JSON.stringify({{lat:lat, lon:lon}})
 }});
}}

navigator.geolocation.watchPosition(updatePosition);

// 공격
function attack(){{
 fetch("/attack",{{method:"POST"}})
 .then(r=>r.text()).then(alert);
}}

// 뽑기
function gacha(){{
 fetch("/gacha",{{method:"POST"}})
 .then(r=>r.text()).then(alert);
}}

// GPS 체크
function sendGPS(){{
 fetch("/gps",{{method:"POST"}})
 .then(r=>r.text()).then(alert);
}}

</script>
"""

# =====================
@app.route("/gps", methods=["POST"])
def gps():
    n = session.get("name")
    data = request.get_json() or {}

    lat = data.get("lat", TARGET_LAT+1)
    lon = data.get("lon", TARGET_LON+1)

    last_gps[n] = (lat, lon, time.time())

    # 미션
    if distance_m(lat, lon, TARGET_LAT, TARGET_LON) <= RADIUS_M:
        if not gps_success[n]:
            money[n] += 100
            gps_success[n] = True
            return "✅ 미션 성공 +100"

    return "📍 위치 업데이트"

# =====================
@app.route("/attack", methods=["POST"])
def attack():
    me = session.get("name")

    if me not in last_gps:
        return "위치 없음"

    alat, alon, _ = last_gps[me]

    if in_safezone(alat, alon):
        return "🛡️ 안전구역 공격 불가"

    for t in users:
        if t == me or users[t]=="dead":
            continue
        if t not in last_gps:
            continue

        # 동맹
        if me in alliances and t in alliances[me]:
            continue

        tlat, tlon, _ = last_gps[t]

        if in_safezone(tlat, tlon):
            continue

        if distance_m(alat, alon, tlat, tlon) <= ATTACK_RANGE:
            pending_attacks[t] = (me, time.time()+DELAY)
            return f"{t} 공격 예약!"

    return "대상 없음"

# =====================
@app.route("/gacha", methods=["POST"])
def gacha():
    n = session.get("name")

    r = random.random()

    if r < 0.1:
        users[n] = "dead"
        return "💀 즉사"

    elif r < 0.4:
        money[n]+=50
        return "💰 +50"

    elif r < 0.7:
        items[n]="shield"
        return "🛡️ 보호막"

    else:
        return "꽝"

# =====================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))