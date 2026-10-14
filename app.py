from flask import Flask, request, session, redirect, jsonify
import math, time, os, threading, html, json
from threading import RLock

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "gps-game-secure-2026-v4")

# pyright: reportUndefinedVariable=false
# pylint: disable=undefined-variable

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

data_lock = RLock()
SAVE_FILE = "game_save.json"
ADMIN_PW = os.environ.get("ADMIN_PW", "0808")
TARGET_LAT = 37.377971
TARGET_LON = 127.877029
RADIUS_M = 120
MAX_SPEED_KMH = 120

def distance_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

def load_data():
    global users, money, last_gps, gps_success, tracks, frozen, damage_zone, broadcasts, bounties, airdrops
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
            airdrops = data.get("airdrops", [])
            print(f"[OK] save.json 로드 완료 ({len(users)}명 플레이어)")
        except Exception as e:
            print("[WARN] save.json 로드 실패:", e)

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
            "airdrops": list(airdrops),
        }
    try:
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[WARN] save 실패:", e)

def auto_save_loop():
    while True:
        save_data()
        time.sleep(30)

def event_loop():
    while True:
        now = time.time()
        with data_lock:
            for e in events[:]:
                if now >= e["time"]:
                    if e["type"] == "airdrop":
                        airdrops.append({"lat": TARGET_LAT, "lon": TARGET_LON, "id": int(time.time() * 1000)})
                    events.remove(e)
                    save_data()
        time.sleep(1)

load_data()
threading.Thread(target=event_loop, daemon=True).start()
threading.Thread(target=auto_save_loop, daemon=True).start()

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        n = request.form.get("name", "").strip()
        if not n:
            return "닉네임을 입력해주세요!"
        if len(n) > 20:
            return "닉네임은 20자 이하로 입력해주세요!"
        session["name"] = n
        with data_lock:
            users.setdefault(n, "alive")
            money.setdefault(n, 0)
            gps_success.setdefault(n, False)
        return redirect("/game")
    return """
    <form method=post style="text-align:center;margin-top:100px;font-family:system-ui">
        <h1>📍 GPS 게임</h1>
        <p style="color:#94a3b8;font-size:14px">📱폰·태블릿=플레이 · 💻컴퓨터=관전</p>
        <input name=name placeholder="닉네임" style="padding:12px;font-size:18px;width:280px"><br><br>
        <button style="padding:12px 30px;font-size:18px">입장하기</button>
    </form>
    """

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
    <h3>{safe_name} 💰 <span id=money>{money.get(n, 0)}</span> <span id=modeBadge style="font-size:0.7em"></span></h3>
    <div id=dist class=info>⏳ 확인 중...</div>
    <div id=status class=info style="color:#93c5fd;margin-top:6px">목표 지점 체크인 +100 · 에어드롭 +250</div>
    <div id=playControls>
      <button onclick="sendGPS()">📡 위치 체크</button>
      <button onclick="location.reload()" style="background:#64748b">새로고침</button>
    </div>
    <div id=specControls style="display:none">
      <button onclick="location.reload()" style="background:#64748b">새로고침</button>
      <span style="color:#fca5a5;margin-left:6px">👁 관전자 · 빨간 핀 = 플레이어</span>
    </div>
</div>
<div id="map"></div>
<div id="broadcast"></div>
<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
<script>
const TLAT={TARGET_LAT}, TLON={TARGET_LON};
function isPhoneOrTablet(){{
  const ua=navigator.userAgent||"";
  if(/Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(ua)) return true;
  if(navigator.platform==="MacIntel"&&navigator.maxTouchPoints>1) return true;
  return false;
}}
const isPlayer=isPhoneOrTablet();
let map=L.map('map').setView([TLAT,TLON],16);
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);
setTimeout(()=>map.invalidateSize(),300);
let me=null,dangerCircle=null,airdropMarkers=[],playerMarkers={{}},lastBroadcastTime=0;
const redIcon=L.divIcon({{className:'pin',html:'<div style="width:16px;height:16px;background:#ef4444;border:2px solid #fff;border-radius:50%"></div>',iconSize:[16,16],iconAnchor:[8,8]}});
function getDistance(a,b,c,d){{const R=6371000;let x=(c-a)*Math.PI/180,y=(d-b)*Math.PI/180;let A=Math.sin(x/2)**2+Math.cos(a*Math.PI/180)*Math.cos(c*Math.PI/180)*Math.sin(y/2)**2;return 2*R*Math.atan2(Math.sqrt(A),Math.sqrt(1-A));}}
function updatePosition(p){{let lat=p.coords.latitude,lon=p.coords.longitude;if(me)map.removeLayer(me);me=L.marker([lat,lon]).addTo(map);map.setView([lat,lon],17);document.getElementById("dist").innerText=`📏 ${{Math.floor(getDistance(lat,lon,TLAT,TLON))}}m`;}}
function sendGPS(){{document.getElementById("status").innerText="📡 위치 확인 중...";navigator.geolocation.getCurrentPosition(p=>{{fetch("/gps",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{lat:p.coords.latitude,lon:p.coords.longitude,accuracy:p.coords.accuracy}})}}).then(r=>r.text()).then(msg=>{{document.getElementById("status").innerText=msg;if(msg.includes("+100")||msg.includes("+250"))setTimeout(()=>location.reload(),900);}});}},()=>document.getElementById("status").innerText="GPS 권한이 필요합니다!",{{enableHighAccuracy:true,timeout:10000}});}}
function updateDanger(){{fetch("/get_danger").then(r=>r.json()).then(d=>{{if(d.lat){{if(dangerCircle)map.removeLayer(dangerCircle);dangerCircle=L.circle([d.lat,d.lon],{{radius:d.r,color:"red",fillOpacity:0.15}}).addTo(map);}}else if(dangerCircle){{map.removeLayer(dangerCircle);dangerCircle=null;}}}});}}
async function updateAirdrops(){{airdropMarkers.forEach(m=>map.removeLayer(m));airdropMarkers=[];let data=await(await fetch("/get_airdrops")).json();data.forEach(a=>{{airdropMarkers.push(L.marker([a.lat,a.lon],{{icon:L.divIcon({{className:'airdrop',html:'🎁',iconSize:[30,30]}})}}).addTo(map).bindPopup("🎁 에어드랍"));}});}}
async function checkBroadcast(){{let b=await(await fetch("/get_broadcast")).json();if(b.time>lastBroadcastTime){{lastBroadcastTime=b.time;let div=document.getElementById("broadcast");div.textContent=`📢 GM 방송\n${{b.msg}}`;div.style.whiteSpace="pre-line";div.style.display="block";setTimeout(()=>{{div.style.display="none";}},8000);}}}}
async function updateSpectatorPlayers(){{let data=await(await fetch("/get_players")).json();let seen=new Set(),n=0;data.forEach(p=>{{if(p.lat==null||p.lon==null)return;n++;seen.add(p.name);let pop=`<b>${{p.name}}</b><br>💰 ${{p.money}}<br>${{p.state}}`;if(p.bounty>0)pop+=`<br>🎯 ${{p.bounty}}원`;if(playerMarkers[p.name]){{playerMarkers[p.name].setLatLng([p.lat,p.lon]);playerMarkers[p.name].setPopupContent(pop);}}else{{playerMarkers[p.name]=L.marker([p.lat,p.lon],{{icon:redIcon}}).addTo(map).bindPopup(pop);}}}});for(let name in playerMarkers){{if(!seen.has(name)){{map.removeLayer(playerMarkers[name]);delete playerMarkers[name];}}}}document.getElementById("dist").innerText=`👁 관전 · 플레이어 ${{n}}명`;}}
if(isPlayer){{document.getElementById("modeBadge").innerText="📱 플레이어";document.getElementById("dist").innerText="📡 GPS 대기중...";document.getElementById("playControls").style.display="block";document.getElementById("specControls").style.display="none";if(navigator.geolocation)navigator.geolocation.watchPosition(updatePosition,()=>{{}},{{enableHighAccuracy:true}});}}
else{{document.getElementById("modeBadge").innerText="💻 관전자";document.getElementById("status").innerText="컴퓨터 관전자 · GPS 없음 · 빨간 핀 = 모든 사람";document.getElementById("playControls").style.display="none";document.getElementById("specControls").style.display="block";updateSpectatorPlayers();setInterval(updateSpectatorPlayers,2000);}}
setInterval(updateDanger,2000);setInterval(updateAirdrops,4000);setInterval(checkBroadcast,3000);
</script>
</body>
</html>
"""

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
        accuracy = float(data.get("accuracy", 0))
    except (TypeError, ValueError):
        return "🚫 좌표 형식이 잘못되었습니다"
    if not (math.isfinite(lat) and math.isfinite(lon)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return "🚫 올바르지 않은 좌표입니다"
    if not math.isfinite(accuracy) or accuracy < 0:
        return "🚫 GPS 정확도 정보가 잘못되었습니다"
    if accuracy > 100:
        return f"📡 GPS 오차가 너무 큽니다 ({accuracy:.0f}m). 하늘이 보이는 곳에서 다시 시도하세요"
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
                save_data()
                return "☠️ 위험구역에 들어와 사망했습니다"
        for drop in airdrops[:]:
            if distance_m(lat, lon, drop["lat"], drop["lon"]) <= 30:
                airdrops.remove(drop)
                money[n] = money.get(n, 0) + 250
                save_data()
                return "🎁 에어드롭 획득! +250"
        if distance_m(lat, lon, TARGET_LAT, TARGET_LON) < RADIUS_M:
            if not gps_success.get(n, False):
                money[n] = money.get(n, 0) + 100
                gps_success[n] = True
                save_data()
                return "🎉 목표 지점 체크인 성공! +100"
    return "✅ 위치가 기록되었습니다"

@app.route("/get_airdrops")
def get_airdrops():
    with data_lock:
        return jsonify(list(airdrops))

@app.route("/spawn_airdrop", methods=["POST"])
def spawn_airdrop():
    if not session.get("admin"):
        return "권한 없음", 403
    data = request.get_json(silent=True) or {}
    try:
        lat = float(data["lat"])
        lon = float(data["lon"])
    except (KeyError, TypeError, ValueError):
        return "좌표가 잘못되었습니다", 400
    if not (math.isfinite(lat) and math.isfinite(lon)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return "좌표가 잘못되었습니다", 400
    with data_lock:
        airdrops.append({"lat": lat, "lon": lon, "id": int(time.time() * 1000)})
        save_data()
    return "ok"

@app.route("/broadcast", methods=["POST"])
def broadcast():
    if not session.get("admin"):
        return "권한 없음", 403
    data = request.get_json(silent=True) or {}
    msg = str(data.get("msg", "")).strip()
    if not msg:
        return "메시지를 입력하세요", 400
    with data_lock:
        broadcasts.append({"time": time.time(), "msg": msg})
        if len(broadcasts) > 20:
            broadcasts.pop(0)
    save_data()
    return "ok"

@app.route("/get_broadcast")
def get_broadcast():
    with data_lock:
        if broadcasts:
            latest = broadcasts[-1]
            return jsonify({"time": latest["time"], "msg": latest["msg"]})
        return jsonify({"time": 0, "msg": ""})

@app.route("/set_bounty", methods=["POST"])
def set_bounty():
    if not session.get("admin"):
        return "권한 없음", 403
    data = request.get_json(silent=True) or {}
    target = str(data.get("target", "")).strip()
    try:
        amount = int(data.get("amount", 0))
    except (TypeError, ValueError):
        return "잘못된 입력", 400
    if not target or amount <= 0:
        return "잘못된 입력", 400
    with data_lock:
        bounties[target] = amount
    save_data()
    return "ok"

@app.route("/clear_bounty", methods=["POST"])
def clear_bounty():
    if not session.get("admin"):
        return "권한 없음", 403
    data = request.get_json(silent=True) or {}
    target = str(data.get("target", "")).strip()
    if not target:
        return "유저 닉네임을 선택하세요", 400
    with data_lock:
        bounties.pop(target, None)
    save_data()
    return "ok"

@app.route("/get_players")
def get_players():
    arr = []
    with data_lock:
        seen = set()
        for n, pos in last_gps.items():
            seen.add(n)
            arr.append({"name": n, "lat": pos[0], "lon": pos[1], "money": money.get(n, 0), "state": users.get(n, "alive"), "bounty": bounties.get(n, 0)})
        for n in users:
            if n not in seen:
                arr.append({"name": n, "lat": None, "lon": None, "money": money.get(n, 0), "state": users.get(n, "alive"), "bounty": bounties.get(n, 0)})
    return jsonify(arr)

@app.route("/get_tracks")
def get_tracks():
    with data_lock:
        return jsonify({k: list(v) for k, v in tracks.items()})

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
        body {{margin:0; background:#0f172a; color:white; font-family:system-ui; padding:10px;}}
        h2,h3 {{margin:10px 0;}}
        input, button, select {{padding:8px; margin:3px; font-size:1em;}}
        select {{background:#0f172a; color:white; border:1px solid #475569; border-radius:6px;}}
        button {{background:#3b82f6; color:white; border:none; border-radius:6px; cursor:pointer;}}
        .map-container {{height:65vh; margin-top:15px; border:3px solid #334155; border-radius:8px;}}
        .section {{background:#1e2937; padding:15px; border-radius:8px; margin-bottom:15px;}}
    </style>
</head>
<body>
<h2>🛠 GM 콘솔</h2>
<div class="section">
    <h3>👤 플레이어 선택</h3>
    <select id=user style="width:220px;padding:8px;font-size:1em"><option value="">-- 유저 선택 --</option></select>
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
    <button onclick="spawnAirdrop()" style="background:#16a34a">🎁 에어드롭</button>
</div>
<div class="section">
    <h3>📢 방송</h3>
    <input id=broadcastMsg placeholder="메시지" style="width:380px">
    <button onclick="sendBroadcast()">보내기</button>
</div>
<div class="section">
    <h3>🎯 현상금</h3>
    <select id=bountyTarget style="width:220px;padding:8px;font-size:1em"><option value="">-- 유저 선택 --</option></select>
    <input id=bountyAmount type="number" value="500" style="width:100px">
    <button onclick="setBounty()">걸기</button>
    <button onclick="clearBounty()" style="background:#dc2626">제거</button>
</div>
<div id="map" class="map-container"></div>
<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
<script>
let map=L.map('map').setView([37.377971,127.877029],16);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
let markers={{}},lines=[],dangerCircleGM=null,airdropMarkersGM=[];
function escapeHtml(v){{return String(v).replace(/[&<>"']/g,c=>({{'&':'&','<':'<','>':'>','"':'"',"'":'&#39;'}}[c]));}}
map.on('click',e=>{{document.getElementById('lat').value=e.latlng.lat.toFixed(6);document.getElementById('lon').value=e.latlng.lng.toFixed(6);}});
async function updatePlayers(){{
  let data=await(await fetch('/get_players')).json();
  let current=new Set(),names=[];
  data.forEach(p=>{{current.add(p.name);names.push(p.name);if(p.lat==null||p.lon==null)return;let pop=`<b>${{escapeHtml(p.name)}}</b><br>💰 ${{p.money}}<br>${{escapeHtml(p.state)}}`;if(p.bounty>0)pop+=`<br>🎯 ${{p.bounty}}원`;if(markers[p.name]){{markers[p.name].setLatLng([p.lat,p.lon]);markers[p.name].setPopupContent(pop);}}else{{markers[p.name]=L.marker([p.lat,p.lon]).addTo(map).bindPopup(pop);}}}});
  for(let name in markers){{if(!current.has(name)){{map.removeLayer(markers[name]);delete markers[name];}}}}
  fillUserSelect('user',names);fillUserSelect('bountyTarget',names);
}}
function fillUserSelect(id,names){{let sel=document.getElementById(id);if(!sel)return;let prev=sel.value;let opts='<option value="">-- 유저 선택 --</option>';names.sort().forEach(n=>{{opts+=`<option value="${{escapeHtml(n)}}">${{escapeHtml(n)}}</option>`;}});sel.innerHTML=opts;if(prev&&names.includes(prev))sel.value=prev;}}
async function updateTracks(){{lines.forEach(l=>map.removeLayer(l));lines=[];let data=await(await fetch('/get_tracks')).json();for(let u in data){{if(data[u].length>1)lines.push(L.polyline(data[u],{{color:'#f43f5e',weight:4,opacity:0.7}}).addTo(map));}}}}
async function updateDangerGM(){{let d=await(await fetch('/get_danger')).json();if(d.lat){{if(dangerCircleGM)map.removeLayer(dangerCircleGM);dangerCircleGM=L.circle([d.lat,d.lon],{{radius:d.r,color:'red',fillOpacity:0.15}}).addTo(map);}}else if(dangerCircleGM){{map.removeLayer(dangerCircleGM);dangerCircleGM=null;}}}}
async function updateAirdropsGM(){{airdropMarkersGM.forEach(m=>map.removeLayer(m));airdropMarkersGM=[];let data=await(await fetch('/get_airdrops')).json();data.forEach(a=>{{airdropMarkersGM.push(L.marker([a.lat,a.lon],{{icon:L.divIcon({{className:'a',html:'🎁',iconSize:[30,30]}})}}).addTo(map));}});}}
function post(url,body){{fetch(url,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}}).then(async r=>{{let m=await r.text();if(!r.ok)throw new Error(m||('HTTP '+r.status));alert('✅ 실행 완료');updatePlayers();updateAirdropsGM();}}).catch(e=>alert('❌ '+e.message));}}
function freeze(){{post('/freeze',{{user:document.getElementById('user').value}});}}
function unfreeze(){{post('/unfreeze',{{user:document.getElementById('user').value}});}}
function kill(){{post('/kill',{{target:document.getElementById('user').value}});}}
function setDanger(){{post('/set_danger',{{lat:parseFloat(document.getElementById('lat').value),lon:parseFloat(document.getElementById('lon').value),r:parseFloat(document.getElementById('r').value)}});}}
function clearDanger(){{post('/clear_danger',{{}});}}
function spawnAirdrop(){{post('/spawn_airdrop',{{lat:parseFloat(document.getElementById('lat').value),lon:parseFloat(document.getElementById('lon').value)}});}}
function sendBroadcast(){{let m=document.getElementById('broadcastMsg').value.trim();if(m)post('/broadcast',{{msg:m}});}}
function setBounty(){{post('/set_bounty',{{target:document.getElementById('bountyTarget').value.trim(),amount:parseInt(document.getElementById('bountyAmount').value)}});}}
function clearBounty(){{post('/clear_bounty',{{target:document.getElementById('bountyTarget').value.trim()}});}}
setInterval(updatePlayers,1000);setInterval(updateTracks,2500);setInterval(updateDangerGM,2000);setInterval(updateAirdropsGM,4000);
updatePlayers();updateTracks();updateDangerGM();updateAirdropsGM();
</script>
</body>
</html>
"""

@app.route("/freeze", methods=["POST"])
def freeze():
    if not session.get("admin"): return "권한 없음", 403
    data = request.get_json(silent=True) or {}
    user = str(data.get("user", "")).strip()
    if not user: return "유저 닉네임을 입력하세요", 400
    with data_lock: frozen[user] = True
    return "ok"

@app.route("/unfreeze", methods=["POST"])
def unfreeze():
    if not session.get("admin"): return "권한 없음", 403
    data = request.get_json(silent=True) or {}
    user = str(data.get("user", "")).strip()
    if not user: return "유저 닉네임을 입력하세요", 400
    with data_lock: frozen.pop(user, None)
    return "ok"

@app.route("/kill", methods=["POST"])
def kill():
    if not session.get("admin"): return "권한 없음", 403
    data = request.get_json(silent=True) or {}
    target = str(data.get("target", "")).strip()
    if not target: return "유저 닉네임을 입력하세요", 400
    with data_lock: users[target] = "dead"
    save_data()
    return "ok"

@app.route("/set_danger", methods=["POST"])
def set_danger():
    if not session.get("admin"): return "권한 없음", 403
    d = request.get_json(silent=True) or {}
    try:
        lat, lon, r = float(d["lat"]), float(d["lon"]), float(d["r"])
    except (KeyError, TypeError, ValueError):
        return "좌표 또는 반경이 잘못되었습니다", 400
    if not (math.isfinite(lat) and math.isfinite(lon) and math.isfinite(r)) or r <= 0:
        return "좌표 또는 반경이 잘못되었습니다", 400
    with data_lock:
        global damage_zone
        damage_zone = (lat, lon, r)
    save_data()
    return "ok"

@app.route("/clear_danger", methods=["POST"])
def clear_danger():
    if not session.get("admin"): return "권한 없음", 403
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

if __name__ == "__main__":
    print("[START] GPS 게임 서버 v5")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
