from flask import Flask, request, session, redirect, jsonify
import math, time, os, threading, html, json
from threading import Lock

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "gps-game-secure-2026-v4")

# ====================== Pylance / VS Code 경고 억제 ======================
# Embedded JavaScript 때문에 발생하는 false positive 무시
# pyright: reportUndefinedVariable=false
# pylint: disable=undefined-variable

# ====================== 데이터 ======================
users = {}
money = {}
last_gps = {}
gps_success = {}
tracks = {}
frozen = {}
airdrops = []
events = []
damage_zone = None
broadcasts = []
bounties = {}

data_lock = Lock()
SAVE_FILE = "game_save.json"

ADMIN_PW = os.environ.get("ADMIN_PW", "0808")

TARGET_LAT = 37.377971
TARGET_LON = 127.877029
RADIUS_M = 120
MAX_SPEED_KMH = 120


# ====================== 거리 계산 ======================
def distance_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))


# ====================== 데이터 저장/로드 ======================
def load_data():
    global users, money, last_gps, gps_success, tracks, frozen, damage_zone, broadcasts, bounties
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            users.update(data.get("users", {}))
            money.update(data.get("money", {}))
            last_gps.update(data.get("last_gps", {}))
            gps_success.update(data.get("gps_success", {}))
            tracks.update(data.get("tracks", {}))
            frozen.update(data.get("frozen", {}))
            damage_zone = data.get("damage_zone")
            broadcasts = data.get("broadcasts", [])
            bounties = data.get("bounties", {})
            print(f"✅ save.json 로드 완료 ({len(users)}명 플레이어)")
        except Exception as e:
            print("⚠️ save.json 로드 실패:", e)

def save_data():
    with data_lock:
        data = {
            "users": dict(users),
            "money": dict(money),
            "last_gps": dict(last_gps),
            "gps_success": dict(gps_success),
            "tracks": dict(tracks),
            "frozen": dict(frozen),
            "damage_zone": damage_zone,
            "broadcasts": broadcasts,
            "bounties": dict(bounties),
        }
    try:
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("⚠️ save 실패:", e)

def auto_save_loop():
    while True:
        save_data()
        time.sleep(30)          # 30초마다 자동 저장


# ====================== 이벤트 루프 ======================
def event_loop():
    while True:
        now = time.time()
        with data_lock:
            for e in events[:]:
                if now >= e["time"]:
                    if e["type"] == "airdrop":
                        airdrops.append({
                            "lat": TARGET_LAT,
                            "lon": TARGET_LON,
                            "id": int(time.time())
                        })
                    events.remove(e)
        time.sleep(1)


# ====================== 시작 ======================
threading.Thread(target=event_loop, daemon=True).start()
threading.Thread(target=auto_save_loop, daemon=True).start()
load_data()


# ====================== 로그인 ======================
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        n = request.form.get("name", "").strip()
        if not n:
            return "닉네임을 입력해주세요!"

        session["name"] = n
        users.setdefault(n, "alive")
        money.setdefault(n, 0)
        gps_success.setdefault(n, False)

        return redirect("/game")

    return """
    <form method=post style="text-align:center;margin-top:100px;font-family:system-ui">
        <h1>📍 GPS 게임</h1>
        <input name=name placeholder="닉네임" style="padding:12px;font-size:18px;width:280px"><br><br>
        <button style="padding:12px 30px;font-size:18px">입장하기</button>
    </form>
    """


# ====================== 게임 화면 (에어드랍 + 방송) ======================
@app.route("/game")
def game():
    n = session.get("name")
    if not n:
        return redirect("/")

    safe_name = html.escape(n)

    return f"""
<!doctype html>
<html>
<head>
    <meta name=viewport content="width=device-width,initial-scale=1">
    <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>
    <style>
        body{{margin:0;background:#0f172a;color:white;font-family:system-ui}}
        #map{{height:65vh}}
        .card{{padding:15px;background:#1e2937}}
        .info{{font-size:1.1em}}
        button{{padding:12px 20px;font-size:1.1em;background:#3b82f6;color:white;border:none;border-radius:8px;margin:3px}}
        #broadcast{{position:fixed;bottom:10px;left:10px;right:10px;background:#f59e0b;color:#111;padding:15px;border-radius:8px;display:none;font-weight:bold}}
    </style>
</head>
<body>

<div class="card">
    <h3>{safe_name} 💰 <span id=money>{money.get(n, 0)}</span></h3>
    <div id=dist class=info>📡 GPS 대기중...</div>
    <button onclick="sendGPS()">📡 위치 체크</button>
    <button onclick="location.reload()" style="background:#64748b">새로고침</button>
</div>

<div id="map"></div>
<div id="broadcast"></div>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
<script>
let map = L.map('map').setView([{TARGET_LAT}, {TARGET_LON}], 17);
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);
setTimeout(()=>map.invalidateSize(), 300);

let me = null;
let dangerCircle = null;
let airdropMarkers = [];
let lastBroadcastTime = 0;

function updatePosition(p){{
    let lat = p.coords.latitude;
    let lon = p.coords.longitude;
    if(me) map.removeLayer(me);
    me = L.marker([lat, lon]).addTo(map);
    map.setView([lat, lon], 17);
    let d = getDistance(lat, lon, {TARGET_LAT}, {TARGET_LON});
    document.getElementById("dist").innerText = `📏 ${{Math.floor(d)}}m`;
}}

function getDistance(a,b,c,d){{
    const R=6371000;
    let x=(c-a)*Math.PI/180;
    let y=(d-b)*Math.PI/180;
    let A=Math.sin(x/2)**2 + Math.cos(a*Math.PI/180)*Math.cos(c*Math.PI/180)*Math.sin(y/2)**2;
    return 2*R*Math.atan2(Math.sqrt(A), Math.sqrt(1-A));
}}

function sendGPS(){{
    navigator.geolocation.getCurrentPosition(p => {{
        fetch("/gps", {{
            method:"POST",
            headers:{{"Content-Type":"application/json"}},
            body:JSON.stringify({{lat:p.coords.latitude, lon:p.coords.longitude}})
        }})
        .then(r => r.text())
        .then(msg => {{
            alert(msg);
            if(msg.includes("+100") || msg.includes("성공")) location.reload();
        }});
    }}, () => alert("GPS 권한이 필요합니다!"), {{enableHighAccuracy:true}});
}}

function updateDanger(){{
    fetch("/get_danger")
    .then(r=>r.json())
    .then(d=>{{
        if(d.lat){{
            if(dangerCircle) map.removeLayer(dangerCircle);
            dangerCircle = L.circle([d.lat, d.lon], {{radius: d.r, color:"red", fillOpacity:0.15}}).addTo(map);
        }} else if(dangerCircle){{
            map.removeLayer(dangerCircle);
            dangerCircle = null;
        }}
    }});
}}

async function updateAirdrops(){{
    airdropMarkers.forEach(m => map.removeLayer(m));
    airdropMarkers = [];
    let r = await fetch("/get_airdrops");
    let data = await r.json();
    data.forEach(a => {{
        let m = L.marker([a.lat, a.lon], {{icon: L.divIcon({{className:'airdrop', html:'🎁', iconSize:[30,30]}})}})
            .addTo(map)
            .bindPopup("🎁 에어드랍");
        airdropMarkers.push(m);
    }});
}}

async function checkBroadcast(){{
    let r = await fetch("/get_broadcast");
    let b = await r.json();
    if (b.time > lastBroadcastTime) {{
        lastBroadcastTime = b.time;
        let div = document.getElementById("broadcast");
        div.innerHTML = `📢 <b>GM 방송</b><br>${{b.msg}}`;
        div.style.display = "block";
        setTimeout(() => {{ div.style.display = "none"; }}, 8000);
    }}
}}

setInterval(updateDanger, 2000);
setInterval(updateAirdrops, 4000);
setInterval(checkBroadcast, 3000);
navigator.geolocation.watchPosition(updatePosition);
</script>
</body>
</html>
"""


# ====================== GPS (요청 검증 강화) ======================
@app.route("/gps", methods=["POST"])
def gps():
    n = session.get("name")
    if not n or users.get(n) == "dead":
        return "❌ 게임 오버"

    data = request.get_json()
    if not data or "lat" not in data or "lon" not in data:
        return "🚫 잘못된 요청"

    try:
        lat = float(data["lat"])
        lon = float(data["lon"])
    except:
        return "🚫 좌표 형식이 잘못되었습니다"

    with data_lock:
        if frozen.get(n):
            return "🧊 이동이 얼려져 있습니다"

        last = last_gps.get(n)
        if last:
            prev_lat, prev_lon, prev_time = last
            time_diff = time.time() - prev_time
            if time_diff > 0:
                dist_moved = distance_m(prev_lat, prev_lon, lat, lon)
                speed_kmh = (dist_moved / time_diff) * 3.6
                if speed_kmh > MAX_SPEED_KMH or (dist_moved > 300 and time_diff < 2):
                    return f"🚫 치트 의심 이동 ({speed_kmh:.1f} km/h)"

        last_gps[n] = (lat, lon, time.time())
        tracks.setdefault(n, []).append((lat, lon))
        if len(tracks[n]) > 200:
            tracks[n].pop(0)

        if damage_zone:
            lat0, lon0, r = damage_zone
            if distance_m(lat, lon, lat0, lon0) < r:
                users[n] = "dead"
                save_data()               # 사망은 중요 → 즉시 저장
                return "☠️ 위험구역에 들어와 사망했습니다"

        if distance_m(lat, lon, TARGET_LAT, TARGET_LON) < RADIUS_M:
            if not gps_success.get(n, False):
                money[n] = money.get(n, 0) + 100
                gps_success[n] = True
                save_data()               # 체크인 성공 → 즉시 저장
                return "🎉 목표 지점 체크인 성공! +100"

    return "✅ 위치가 기록되었습니다"


# ====================== 에어드랍 API ======================
@app.route("/get_airdrops")
def get_airdrops():
    with data_lock:
        return jsonify(airdrops)


# ====================== 방송 API ======================
@app.route("/broadcast", methods=["POST"])
def broadcast():
    if not session.get("admin"): return "권한 없음"
    msg = request.get_json().get("msg", "").strip()
    if not msg: return "메시지를 입력하세요"
    with data_lock:
        broadcasts.append({"time": time.time(), "msg": msg})
        if len(broadcasts) > 20: broadcasts.pop(0)
    save_data()
    return "ok"

@app.route("/get_broadcast")
def get_broadcast():
    with data_lock:
        if broadcasts:
            latest = broadcasts[-1]
            return jsonify({"time": latest["time"], "msg": latest["msg"]})
    return jsonify({"time": 0, "msg": ""})


# ====================== 현상금 API ======================
@app.route("/set_bounty", methods=["POST"])
def set_bounty():
    if not session.get("admin"): return "권한 없음"
    data = request.get_json()
    target = data.get("target", "").strip()
    amount = int(data.get("amount", 0))
    if not target or amount <= 0: return "잘못된 입력"
    with data_lock:
        bounties[target] = amount
    save_data()
    return "ok"


# ====================== 플레이어 위치 API ======================
@app.route("/get_players")
def get_players():
    arr = []
    with data_lock:
        for n, pos in last_gps.items():
            arr.append({
                "name": n,
                "lat": pos[0],
                "lon": pos[1],
                "money": money.get(n, 0),
                "state": users.get(n, "alive"),
                "bounty": bounties.get(n, 0)
            })
    return jsonify(arr)


@app.route("/get_tracks")
def get_tracks():
    with data_lock:
        return jsonify(tracks)


# ====================== 관리자 GM 콘솔 (마커 정리 + danger + 에어드랍) ======================
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        if request.form.get("pw") == ADMIN_PW:
            session["admin"] = True

    if not session.get("admin"):
        return """
        <form method=post style="text-align:center;margin-top:100px">
            <h2>관리자 로그인</h2>
            <input name=pw type=password placeholder="관리자 비밀번호"><br><br>
            <button>로그인</button>
        </form>
        """

    return """
<!doctype html>
<html>
<head>
    <meta charset=utf-8>
    <title>GM 콘솔</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>
    <style>
        body {margin:0; background:#0f172a; color:white; font-family:system-ui; padding:10px;}
        h2,h3 {margin:10px 0;}
        input, button {padding:8px; margin:3px; font-size:1em;}
        button {background:#3b82f6; color:white; border:none; border-radius:6px; cursor:pointer;}
        .map-container {height:65vh; margin-top:15px; border:3px solid #334155; border-radius:8px;}
        .section {background:#1e2937; padding:15px; border-radius:8px; margin-bottom:15px;}
    </style>
</head>
<body>
<h2>🛠 GM 콘솔 (실시간 지도)</h2>

<div class="section">
    <input id=user placeholder="유저 닉네임" style="width:200px">
    <button onclick="freeze()">🧊 얼리기</button>
    <button onclick="unfreeze()">🔥 해제</button>
    <button onclick="kill()">☠ 즉사</button>
</div>

<div class="section">
    <h3>🚨 위험 구역</h3>
    <input id=lat placeholder="위도" style="width:140px">
    <input id=lon placeholder="경도" style="width:140px">
    <input id=r placeholder="반경(m)" value="50" style="width:80px">
    <button onclick="setDanger()">설정</button>
    <button onclick="clearDanger()">해제</button>
</div>

<div class="section">
    <h3>📢 전역 방송</h3>
    <input id=broadcastMsg placeholder="방송할 메시지" style="width:380px">
    <button onclick="sendBroadcast()">방송 보내기</button>
</div>

<div class="section">
    <h3>🎯 현상금 설정</h3>
    <input id=bountyTarget placeholder="유저 닉네임" style="width:200px">
    <input id=bountyAmount placeholder="현상금액" type="number" value="500" style="width:100px">
    <button onclick="setBounty()">현상금 걸기</button>
</div>

<div id="map" class="map-container"></div>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
<script>
let map = L.map('map').setView([37.377971, 127.877029], 16);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

let markers = {};
let lines = [];
let dangerCircleGM = null;
let airdropMarkersGM = [];

// 지도 클릭 → 위험구역 좌표 자동 입력
map.on('click', function(e) {
    document.getElementById('lat').value = e.latlng.lat.toFixed(6);
    document.getElementById('lon').value = e.latlng.lng.toFixed(6);
});

async function updatePlayers() {
    let r = await fetch("/get_players");
    let data = await r.json();

    let currentPlayers = new Set();

    data.forEach(p => {
        currentPlayers.add(p.name);
        if (markers[p.name]) {
            markers[p.name].setLatLng([p.lat, p.lon]);
        } else {
            let popupText = `<b>${p.name}</b><br>💰 ${p.money}<br>${p.state}`;
            if (p.bounty > 0) popupText += `<br>🎯 현상금: ${p.bounty}원`;
            markers[p.name] = L.marker([p.lat, p.lon])
                .addTo(map)
                .bindPopup(popupText);
        }
    });

    // 사라진 플레이어 마커 정리 (무한 생성 방지)
    for (let name in markers) {
        if (!currentPlayers.has(name)) {
            map.removeLayer(markers[name]);
            delete markers[name];
        }
    }
}

async function updateTracks() {
    lines.forEach(l => map.removeLayer(l));
    lines = [];
    let r = await fetch("/get_tracks");
    let data = await r.json();
    for (let user in data) {
        if (data[user].length > 1) {
            let line = L.polyline(data[user], {color: '#f43f5e', weight: 4, opacity: 0.7}).addTo(map);
            lines.push(line);
        }
    }
}

async function updateDangerGM() {
    let r = await fetch("/get_danger");
    let d = await r.json();
    if (d.lat) {
        if (dangerCircleGM) map.removeLayer(dangerCircleGM);
        dangerCircleGM = L.circle([d.lat, d.lon], {radius: d.r, color:"red", fillOpacity:0.15}).addTo(map);
    } else if (dangerCircleGM) {
        map.removeLayer(dangerCircleGM);
        dangerCircleGM = null;
    }
}

async function updateAirdropsGM() {
    airdropMarkersGM.forEach(m => map.removeLayer(m));
    airdropMarkersGM = [];
    let r = await fetch("/get_airdrops");
    let data = await r.json();
    data.forEach(a => {
        let m = L.marker([a.lat, a.lon], {icon: L.divIcon({className:'airdrop', html:'🎁', iconSize:[30,30]})})
            .addTo(map)
            .bindPopup("🎁 에어드랍");
        airdropMarkersGM.push(m);
    });
}

function post(url, body) {
    fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)})
    .then(() => { alert("✅ 실행 완료"); updatePlayers(); });
}

function freeze(){ post("/freeze", {user:document.getElementById("user").value}); }
function unfreeze(){ post("/unfreeze", {user:document.getElementById("user").value}); }
function kill(){ post("/kill", {target:document.getElementById("user").value}); }

function setDanger(){
    post("/set_danger", {
        lat: parseFloat(document.getElementById("lat").value),
        lon: parseFloat(document.getElementById("lon").value),
        r: parseFloat(document.getElementById("r").value)
    });
}
function clearDanger(){ post("/clear_danger", {}); }

function sendBroadcast(){
    let msg = document.getElementById("broadcastMsg").value.trim();
    if(msg) post("/broadcast", {msg: msg});
}

function setBounty(){
    post("/set_bounty", {
        target: document.getElementById("bountyTarget").value.trim(),
        amount: parseInt(document.getElementById("bountyAmount").value)
    });
}

// 실시간 업데이트
setInterval(updatePlayers, 1000);
setInterval(updateTracks, 2500);
setInterval(updateDangerGM, 2000);
setInterval(updateAirdropsGM, 4000);
updatePlayers();
updateTracks();
updateDangerGM();
updateAirdropsGM();
</script>
</body>
</html>
"""


# ====================== 관리자 API ======================
@app.route("/freeze", methods=["POST"])
def freeze():
    if not session.get("admin"): return "권한 없음"
    with data_lock:
        frozen[request.get_json()["user"]] = True
    return "ok"

@app.route("/unfreeze", methods=["POST"])
def unfreeze():
    if not session.get("admin"): return "권한 없음"
    with data_lock:
        frozen.pop(request.get_json()["user"], None)
    return "ok"

@app.route("/kill", methods=["POST"])
def kill():
    if not session.get("admin"): return "권한 없음"
    with data_lock:
        target = request.get_json()["target"]
        users[target] = "dead"
    save_data()                     # 즉사 → 중요 이벤트
    return "ok"

@app.route("/set_danger", methods=["POST"])
def set_danger():
    if not session.get("admin"): return "권한 없음"
    d = request.get_json()
    with data_lock:
        global damage_zone
        damage_zone = (float(d["lat"]), float(d["lon"]), float(d["r"]))
    save_data()
    return "ok"

@app.route("/clear_danger", methods=["POST"])
def clear_danger():
    if not session.get("admin"): return "권한 없음"
    with data_lock:
        global damage_zone
        damage_zone = None
    save_data()
    return "ok"

@app.route("/get_danger")
def get_danger():
    if damage_zone:
        lat, lon, r = damage_zone
        return jsonify({"lat": lat, "lon": lon, "r": r})
    return jsonify({})


# ====================== 실행 ======================
if __name__ == "__main__":
    print("🚀 GPS 게임 서버 v4 시작 (마커 정리 + danger GM 표시 + 에어드랍 시각화 + 요청 검증)")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)