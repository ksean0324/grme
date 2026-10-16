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

DATA_FILE = "data.json"
TARGET_LAT, TARGET_LON = 37.377971, 127.877029

def load_data():
    global users, money, last_gps, gps_success, tracks, frozen, damage_zone, broadcasts, bounties, airdrops
    if not os.path.exists(DATA_FILE):
        return
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            users = data.get("users", {})
            money = data.get("money", {})
            last_gps = data.get("last_gps", {})
            gps_success = data.get("gps_success", {})
            tracks = data.get("tracks", {})
            frozen = data.get("frozen", {})
            damage_zone = data.get("damage_zone")
            broadcasts = data.get("broadcasts", [])
            bounties = data.get("bounties", {})
            airdrops = data.get("airdrops", [])
    except Exception as e:
        print("load error", e)

def save_data():
    with data_lock:
        data = {
            "users": users,
            "money": money,
            "last_gps": last_gps,
            "gps_success": gps_success,
            "tracks": tracks,
            "frozen": frozen,
            "damage_zone": damage_zone,
            "broadcasts": broadcasts,
            "bounties": bounties,
            "airdrops": list(airdrops),
        }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

load_data()

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))

@app.route("/")
def index():
    return """<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content=\"width=device-width,initial-scale=1\"><title>GPS Game</title>
<style>body{font-family:system-ui;background:#0f172a;color:#e2e8f0;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;margin:0}
input,button{padding:12px;font-size:1.1em;margin:6px;border-radius:8px;border:none}button{background:#3b82f6;color:white;cursor:pointer}a{color:#93c5fd}</style></head>
<body><h1>🎮 GPS 게임</h1><form action=/login method=post><input name=name placeholder=\"닉네임\" required autofocus><button>입장</button></form><p><a href=/admin>관리자</a></p></body></html>"""

@app.route("/login", methods=["POST"])
def login():
    name = request.form.get("name", "").strip()
    if not name: return redirect("/")
    with data_lock:
        if name not in users:
            users[name] = "alive"
            money[name] = 0
        session["name"] = name
        save_data()
    return redirect("/game")

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        if request.form.get("pw") == os.environ.get("ADMIN_PW", "admin123"):
            session["admin"] = True
            return redirect("/gm")
        return "비밀번호 틀림"
    return """<!DOCTYPE html><html><head><meta charset=utf-8><title>Admin</title></head>
<body style=\"background:#0f172a;color:white;font-family:system-ui;padding:40px\"><form method=post><input name=pw type=password placeholder=비밀번호><button>로그인</button></form></body></html>"""

@app.route("/game")
def game():
    if not session.get("name"): return redirect("/")
    name = session["name"]
    return f"""<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content=\"width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no\">
<title>게임 - {html.escape(name)}</title><link rel=stylesheet href=https://unpkg.com/leaflet/dist/leaflet.css>
<style>body{{margin:0;background:#0f172a;color:white;font-family:system-ui}}#map{{height:70vh;width:100%}}.bar{{padding:10px;background:#1e2937;display:flex;flex-wrap:wrap;gap:8px;align-items:center}}button{{padding:8px 14px;background:#3b82f6;color:white;border:none;border-radius:6px;font-size:1em}}.airdrop{{background:transparent!important;border:none!important}}</style></head>
<body><div class=bar><b id=meName>{html.escape(name)}</b><span id=money>💰 0</span><span id=status></span>
<div id=playControls style=display:none><button onclick=sendGPS()>📍 위치 전송</button></div>
<div id=specControls style=display:none><span style=color:#fbbf24>👁 관전자 모드 (PC)</span></div></div>
<div id=map></div><script src=https://unpkg.com/leaflet/dist/leaflet.js></script><script>
const NAME={json.dumps(name)};
function isPhoneOrTablet(){{const ua=navigator.userAgent||'';if(/Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(ua))return true;if(navigator.maxTouchPoints>1)return true;return false;}}
const isPlayer=isPhoneOrTablet();document.getElementById(isPlayer?'playControls':'specControls').style.display='block';
let map=L.map('map').setView([37.377971,127.877029],16);L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);
let me=null,dangerCircle=null,airdropMarkers=[],playerMarkers={{}},lastBroadcastTime=0;
const redIcon=L.divIcon({{className:'',html:'<div style=\"background:#ef4444;width:14px;height:14px;border-radius:50%;border:2px solid white;box-shadow:0 0 4px #000\"></div>',iconSize:[18,18],iconAnchor:[9,9]}});
function escapeHtml(v){{return String(v).replace(/[&<>\"']/g,c=>({{'&':'&','<':'<','>':'>','\"':'"',"'":'&#39;'}}[c]));}}
async function sendGPS(){{if(!navigator.geolocation){{alert('GPS 없음');return;}}navigator.geolocation.getCurrentPosition(async p=>{{let r=await fetch('/gps',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{lat:p.coords.latitude,lon:p.coords.longitude}})}});let t=await r.text();document.getElementById('status').textContent=t;if(me)me.setLatLng([p.coords.latitude,p.coords.longitude]);else me=L.marker([p.coords.latitude,p.coords.longitude]).addTo(map).bindPopup('나');map.setView([p.coords.latitude,p.coords.longitude]);}},e=>alert('GPS 오류: '+e.message),{{enableHighAccuracy:true,timeout:10000}});}}
async function updateDanger(){{let d=await(await fetch('/get_danger')).json();if(d.lat){{if(dangerCircle)map.removeLayer(dangerCircle);dangerCircle=L.circle([d.lat,d.lon],{{radius:d.r,color:'red',fillOpacity:0.15}}).addTo(map);}}else if(dangerCircle){{map.removeLayer(dangerCircle);dangerCircle=null;}}}}
async function updateAirdrops(){{airdropMarkers.forEach(m=>map.removeLayer(m));airdropMarkers=[];let data=await(await fetch('/get_airdrops')).json();data.forEach(a=>{{airdropMarkers.push(L.marker([a.lat,a.lon],{{icon:L.divIcon({{className:'airdrop',html:'🎁',iconSize:[30,30]}})}}).addTo(map).bindPopup('🎁 에어드랍'));}});}}
async function checkBroadcast(){{let d=await(await fetch('/get_broadcast')).json();if(d.time>lastBroadcastTime){{lastBroadcastTime=d.time;if(d.msg)alert('📢 '+d.msg);}}}}
async function updateSpectatorPlayers(){{if(isPlayer)return;let data=await(await fetch('/get_players')).json();let current=new Set();data.forEach(p=>{{if(p.lat==null||p.lon==null)return;current.add(p.name);let pop=`<b>${{escapeHtml(p.name)}}</b><br>💰 ${{p.money}}<br>${{escapeHtml(p.state)}}`;if(p.bounty>0)pop+=`<br>🎯 ${{p.bounty}}원`;if(playerMarkers[p.name]){{playerMarkers[p.name].setLatLng([p.lat,p.lon]);playerMarkers[p.name].setPopupContent(pop);}}else playerMarkers[p.name]=L.marker([p.lat,p.lon],{{icon:redIcon}}).addTo(map).bindPopup(pop);}});for(let n in playerMarkers){{if(!current.has(n)){{map.removeLayer(playerMarkers[n]);delete playerMarkers[n];}}}}}}
setInterval(updateDanger,2000);setInterval(updateAirdrops,4000);setInterval(checkBroadcast,3000);if(!isPlayer)setInterval(updateSpectatorPlayers,1500);updateDanger();updateAirdrops();if(!isPlayer)updateSpectatorPlayers();
</script></body></html>"""

@app.route("/gps", methods=["POST"])
def gps():
    name = session.get("name")
    if not name: return "로그인 필요", 401
    data = request.get_json(silent=True) or {}
    try:
        lat = float(data["lat"]); lon = float(data["lon"])
    except (KeyError, TypeError, ValueError):
        return "좌표 오류", 400
    if not (math.isfinite(lat) and math.isfinite(lon)): return "좌표 오류", 400
    with data_lock:
        if frozen.get(name): return "🧊 얼어있습니다"
        if users.get(name) == "dead": return "☠ 사망 상태"
        last = last_gps.get(name)
        if last:
            dist = haversine(last[0], last[1], lat, lon)
            dt = time.time() - last[2] if len(last) > 2 else 999
            if dt > 0 and dist / max(dt, 0.1) > 30: return "⚡ 속도 이상 (치트 의심)"
        last_gps[name] = (lat, lon, time.time())
        if name not in tracks: tracks[name] = []
        tracks[name].append([lat, lon])
        if len(tracks[name]) > 200: tracks[name] = tracks[name][-200:]
        in_danger = False
        if damage_zone:
            dlat, dlon, r = damage_zone
            if haversine(lat, lon, dlat, dlon) <= r:
                in_danger = True
        events_msg = []
        for drop in airdrops[:]:
            if haversine(lat, lon, drop["lat"], drop["lon"]) < 15:
                airdrops.remove(drop)
                money[name] = money.get(name, 0) + 200
                events_msg.append("🎁 에어드롭 +200")
                break
        if haversine(lat, lon, TARGET_LAT, TARGET_LON) < 20:
            if not gps_success.get(name, False):
                money[name] = money.get(name, 0) + 100
                gps_success[name] = True
                events_msg.append("🎉 체크인 +100")
        if in_danger:
            taken = money.get(name, 0)
            if taken > 0:
                money[name] = 0
                candidates = [n for n, st in users.items() if st != "dead" and n != name]
                if candidates:
                    poorest = min(candidates, key=lambda n: money.get(n, 0))
                    money[poorest] = money.get(poorest, 0) + taken
                    conf = f"⚠ 위험구역 재산 {taken}원 몰수 → {poorest}"
                else:
                    conf = f"⚠ 위험구역 재산 {taken}원 몰수 (수령자 없음)"
                events_msg.append(conf)
            else:
                events_msg.append("⚠ 위험구역 (재산 없음)")
            save_data()
            return " | ".join(events_msg) if events_msg else "⚠ 위험구역"
        if events_msg:
            save_data()
            return " | ".join(events_msg)
    return "✅ 위치가 기록되었습니다"

@app.route("/get_airdrops")
def get_airdrops():
    with data_lock: return jsonify(list(airdrops))

@app.route("/spawn_airdrop", methods=["POST"])
def spawn_airdrop():
    if not session.get("admin"): return "권한 없음", 403
    data = request.get_json(silent=True) or {}
    try: lat = float(data["lat"]); lon = float(data["lon"])
    except (KeyError, TypeError, ValueError): return "좌표가 잘못되었습니다", 400
    if not (math.isfinite(lat) and math.isfinite(lon)) or not (-90 <= lat <= 90 and -180 <= lon <= 180): return "좌표가 잘못되었습니다", 400
    with data_lock:
        airdrops.append({"lat": lat, "lon": lon, "id": int(time.time() * 1000)})
        save_data()
    return "ok"

@app.route("/delete_airdrop", methods=["POST"])
def delete_airdrop():
    if not session.get("admin"): return "권한 없음", 403
    data = request.get_json(silent=True) or {}
    try: drop_id = int(data["id"])
    except (KeyError, TypeError, ValueError): return "에어드롭을 선택하세요", 400
    with data_lock:
        before = len(airdrops)
        airdrops[:] = [a for a in airdrops if a.get("id") != drop_id]
        if len(airdrops) == before: return "해당 에어드롭이 없습니다", 404
        save_data()
    return "ok"

@app.route("/broadcast", methods=["POST"])
def broadcast():
    if not session.get("admin"): return "권한 없음", 403
    data = request.get_json(silent=True) or {}
    msg = str(data.get("msg", "")).strip()
    if not msg: return "메시지를 입력하세요", 400
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

@app.route("/set_bounty", methods=["POST"])
def set_bounty():
    if not session.get("admin"): return "권한 없음", 403
    data = request.get_json(silent=True) or {}
    target = str(data.get("target", "")).strip()
    try: amount = int(data.get("amount", 0))
    except (TypeError, ValueError): return "잘못된 입력", 400
    if not target or amount <= 0: return "잘못된 입력", 400
    with data_lock: bounties[target] = amount
    save_data()
    return "ok"

@app.route("/clear_bounty", methods=["POST"])
def clear_bounty():
    if not session.get("admin"): return "권한 없음", 403
    data = request.get_json(silent=True) or {}
    target = str(data.get("target", "")).strip()
    if not target: return "유저 닉네임을 선택하세요", 400
    with data_lock: bounties.pop(target, None)
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
    with data_lock: return jsonify({k: list(v) for k, v in tracks.items()})

@app.route("/gm")
def gm():
    if not session.get("admin"): return redirect("/admin")
    return """<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content=\"width=device-width,initial-scale=1\"><title>GM 콘솔</title>
<link rel=stylesheet href=https://unpkg.com/leaflet/dist/leaflet.css>
<style>body{margin:0;background:#0f172a;color:white;font-family:system-ui;padding:10px}h2,h3{margin:10px 0}input,button,select{padding:8px;margin:3px;font-size:1em}select{background:#0f172a;color:white;border:1px solid #475569;border-radius:6px}button{background:#3b82f6;color:white;border:none;border-radius:6px;cursor:pointer}.map-container{height:65vh;margin-top:15px;border:3px solid #334155;border-radius:8px}.section{background:#1e2937;padding:15px;border-radius:8px;margin-bottom:15px}</style></head>
<body><h2>🛠 GM 콘솔</h2>
<div class=\"section\"><h3>👤 플레이어 선택</h3>
<select id=user style=\"width:220px;padding:8px;font-size:1em\"><option value=\"\">-- 유저 선택 --</option></select>
<button onclick=\"freeze()\">🧊 얼리기</button><button onclick=\"unfreeze()\">🔥 해제</button><button onclick=\"kill()\">☠ 즉사</button></div>
<div class=\"section\"><h3>🚨 위험 구역 / 에어드롭</h3>
<input id=lat placeholder=\"위도\" style=\"width:140px\"><input id=lon placeholder=\"경도\" style=\"width:140px\"><input id=r placeholder=\"반경(m)\" value=\"50\" style=\"width:80px\">
<button onclick=\"setDanger()\">설정</button><button onclick=\"clearDanger()\">해제</button>
<button onclick=\"spawnAirdrop()\" style=\"background:#16a34a\">🎁 에어드롭 생성</button><br style=\"margin:8px 0\">
<select id=airdropSelect style=\"width:280px;padding:8px;font-size:1em\"><option value=\"\">-- 에어드롭 선택 --</option></select>
<button onclick=\"deleteAirdrop()\" style=\"background:#dc2626\">🗑 삭제</button></div>
<div class=\"section\"><h3>📢 방송</h3><input id=broadcastMsg placeholder=\"메시지\" style=\"width:380px\"><button onclick=\"sendBroadcast()\">보내기</button></div>
<div class=\"section\"><h3>🎯 현상금</h3>
<select id=bountyTarget style=\"width:220px;padding:8px;font-size:1em\"><option value=\"\">-- 유저 선택 --</option></select>
<input id=bountyAmount type=number value=500 style=\"width:100px\"><button onclick=\"setBounty()\">걸기</button>
<button onclick=\"clearBounty()\" style=\"background:#dc2626\">제거</button></div>
<div id=map class=map-container></div>
<script src=https://unpkg.com/leaflet/dist/leaflet.js></script><script>
let map=L.map('map').setView([37.377971,127.877029],16);L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
let markers={},lines=[],dangerCircleGM=null,airdropMarkersGM=[],selectedAirdropId=null,selectedAirdropMarker=null;
function escapeHtml(v){return String(v).replace(/[&<>\"']/g,c=>({'&':'&','<':'<','>':'>','\"':'"',"'":'&#39;'}[c]));}
map.on('click',e=>{document.getElementById('lat').value=e.latlng.lat.toFixed(6);document.getElementById('lon').value=e.latlng.lng.toFixed(6);});
async function updatePlayers(){let data=await(await fetch('/get_players')).json();let current=new Set(),names=[];data.forEach(p=>{current.add(p.name);names.push(p.name);if(p.lat==null||p.lon==null)return;let pop=`<b>${escapeHtml(p.name)}</b><br>💰 ${p.money}<br>${escapeHtml(p.state)}`;if(p.bounty>0)pop+=`<br>🎯 ${p.bounty}원`;if(markers[p.name]){markers[p.name].setLatLng([p.lat,p.lon]);markers[p.name].setPopupContent(pop);}else{markers[p.name]=L.marker([p.lat,p.lon]).addTo(map).bindPopup(pop);}});for(let name in markers){if(!current.has(name)){map.removeLayer(markers[name]);delete markers[name];}}fillUserSelect('user',names);fillUserSelect('bountyTarget',names);}
function fillUserSelect(id,names){let sel=document.getElementById(id);if(!sel)return;let prev=sel.value;let opts='<option value=\"\">-- 유저 선택 --</option>';names.sort().forEach(n=>{opts+=`<option value=\"${escapeHtml(n)}\">${escapeHtml(n)}</option>`;});sel.innerHTML=opts;if(prev&&names.includes(prev))sel.value=prev;}
async function updateTracks(){lines.forEach(l=>map.removeLayer(l));lines=[];let data=await(await fetch('/get_tracks')).json();for(let u in data){if(data[u].length>1)lines.push(L.polyline(data[u],{color:'#f43f5e',weight:4,opacity:0.7}).addTo(map));}}
async function updateDangerGM(){let d=await(await fetch('/get_danger')).json();if(d.lat){if(dangerCircleGM)map.removeLayer(dangerCircleGM);dangerCircleGM=L.circle([d.lat,d.lon],{radius:d.r,color:'red',fillOpacity:0.15}).addTo(map);}else if(dangerCircleGM){map.removeLayer(dangerCircleGM);dangerCircleGM=null;}}
async function updateAirdropsGM(){airdropMarkersGM.forEach(m=>map.removeLayer(m));airdropMarkersGM=[];if(selectedAirdropMarker){map.removeLayer(selectedAirdropMarker);selectedAirdropMarker=null;}let data=await(await fetch('/get_airdrops')).json();let sel=document.getElementById('airdropSelect');let prev=sel?sel.value:'';let opts='<option value=\"\">-- 에어드롭 선택 --</option>';data.forEach(a=>{let label=a.lat.toFixed(5)+', '+a.lon.toFixed(5)+' (#'+a.id+')';opts+='<option value=\"'+a.id+'\">'+label+'</option>';let isSel=String(a.id)===String(selectedAirdropId);let icon=L.divIcon({className:'a',html:isSel?'🔴🎁':'🎁',iconSize:[30,30]});let m=L.marker([a.lat,a.lon],{icon:icon}).addTo(map);m.on('click',()=>{selectedAirdropId=a.id;if(sel)sel.value=String(a.id);updateAirdropsGM();});airdropMarkersGM.push(m);if(isSel){selectedAirdropMarker=L.circle([a.lat,a.lon],{radius:20,color:'#ef4444',fillOpacity:0.2}).addTo(map);}});if(sel){sel.innerHTML=opts;if(prev&&[...sel.options].some(o=>o.value===prev))sel.value=prev;else selectedAirdropId=null;}}
document.getElementById('airdropSelect').addEventListener('change',function(){selectedAirdropId=this.value?parseInt(this.value):null;updateAirdropsGM();});
function post(url,body){fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(async r=>{let m=await r.text();if(!r.ok)throw new Error(m||('HTTP '+r.status));alert('✅ 실행 완료');updatePlayers();updateAirdropsGM();}).catch(e=>alert('❌ '+e.message));}
function freeze(){post('/freeze',{user:document.getElementById('user').value});}
function unfreeze(){post('/unfreeze',{user:document.getElementById('user').value});}
function kill(){post('/kill',{target:document.getElementById('user').value});}
function setDanger(){post('/set_danger',{lat:parseFloat(document.getElementById('lat').value),lon:parseFloat(document.getElementById('lon').value),r:parseFloat(document.getElementById('r').value)});}
function clearDanger(){post('/clear_danger',{});}
function spawnAirdrop(){post('/spawn_airdrop',{lat:parseFloat(document.getElementById('lat').value),lon:parseFloat(document.getElementById('lon').value)});}
function deleteAirdrop(){let id=document.getElementById('airdropSelect').value;if(!id){alert('에어드롭을 선택하세요');return;}selectedAirdropId=null;post('/delete_airdrop',{id:parseInt(id)});}
function sendBroadcast(){let m=document.getElementById('broadcastMsg').value.trim();if(m)post('/broadcast',{msg:m});}
function setBounty(){post('/set_bounty',{target:document.getElementById('bountyTarget').value.trim(),amount:parseInt(document.getElementById('bountyAmount').value)});}
function clearBounty(){post('/clear_bounty',{target:document.getElementById('bountyTarget').value.trim()});}
setInterval(updatePlayers,1000);setInterval(updateTracks,2500);setInterval(updateDangerGM,2000);setInterval(updateAirdropsGM,4000);
updatePlayers();updateTracks();updateDangerGM();updateAirdropsGM();
</script></body></html>"""

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
