from flask import Flask, request, session, redirect, jsonify
import math, time, os, threading, html

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "gps-game")

# 데이터
users = {}
money = {}
last_gps = {}
gps_success = {}
tracks = {}
frozen = {}
airdrops = []
events = []
damage_zone = None

ADMIN_PW = os.environ.get("ADMIN_PW", "0808")

TARGET_LAT = 37.377971
TARGET_LON = 127.877029
RADIUS_M = 120

# 거리 계산
def distance_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

# 이벤트 루프
def event_loop():
    while True:
        now = time.time()
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

threading.Thread(target=event_loop, daemon=True).start()

# 로그인
@app.route("/", methods=["GET","POST"])
def index():
    if request.method == "POST":
        n = request.form.get("name")

        session["name"] = n
        users.setdefault(n, "alive")
        money.setdefault(n, 0)
        gps_success.setdefault(n, False)

        return redirect("/game")

    return """
    <form method=post>
    <input name=name placeholder=닉네임>
    <button>입장</button>
    </form>
    """

# 게임 화면
@app.route("/game")
def game():
    n = session.get("name")
    if not n:
        return redirect("/")

    safe_name = html.escape(n)

    return f"""
<!doctype html>
<meta name=viewport content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>

<style>
body{{margin:0;background:#0f172a;color:white;font-family:system-ui}}
#map{{height:65vh}}
.card{{padding:10px}}
</style>

<div class=card>
<h3>{safe_name} 💰{money[n]}</h3>
<div id=dist>거리 계산중...</div>
<button onclick="sendGPS()">📡 체크</button>
</div>

<div id="map"></div>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
<script>
let map = L.map('map').setView([{TARGET_LAT},{TARGET_LON}],17);
L.tileLayer('https://tile.openstreetmap.org/{{{{z}}}}/{{{{x}}}}/{{{{y}}}}.png').addTo(map);

setTimeout(()=>map.invalidateSize(),300);

let me=null;
let dangerCircle=null;

function updatePosition(p){{
    let lat=p.coords.latitude;
    let lon=p.coords.longitude;

    if(me) map.removeLayer(me);
    me=L.marker([lat,lon]).addTo(map);

    map.setView([lat,lon],17);

    let d=getDistance(lat,lon,{TARGET_LAT},{TARGET_LON});
    document.getElementById("dist").innerText="📏 "+Math.floor(d)+"m";
}}

function getDistance(a,b,c,d){{
    const R=6371000;
    let x=(c-a)*Math.PI/180;
    let y=(d-b)*Math.PI/180;
    let A=Math.sin(x/2)**2+Math.cos(a*Math.PI/180)*Math.cos(c*Math.PI/180)*Math.sin(y/2)**2;
    return 2*R*Math.atan2(Math.sqrt(A),Math.sqrt(1-A));
}}

function sendGPS(){{
    navigator.geolocation.getCurrentPosition(p=>{{
        fetch("/gps", {{{{
            method:"POST",
            headers:{{{{"Content-Type":"application/json"}}}},
            body:JSON.stringify({{{{
                lat:p.coords.latitude,
                lon:p.coords.longitude
            }}}})
        }}}})
        .then(r=>r.text())
        .then(alert);
    }});
}}

function updateDanger(){{
    fetch("/get_danger")
    .then(r=>r.json())
    .then(d=>{{
        if(d.lat){{
            if(dangerCircle) map.removeLayer(dangerCircle);
            dangerCircle=L.circle([d.lat,d.lon],{{{{radius:d.r,color:"red"}}}}).addTo(map);
        }}
    }});
}}

setInterval(updateDanger,3000);
navigator.geolocation.watchPosition(updatePosition);
</script>
"""

# GPS
@app.route("/gps", methods=["POST"])
def gps():
    n = session.get("name")
    data = request.get_json()

    if frozen.get(n):
        return "🧊 이동 불가"

    lat = data["lat"]
    lon = data["lon"]

    last_gps[n] = (lat, lon, time.time())

    tracks.setdefault(n, []).append((lat, lon))
    if len(tracks[n]) > 200:
        tracks[n].pop(0)

    if damage_zone:
        lat0, lon0, r = damage_zone
        if distance_m(lat, lon, lat0, lon0) < r:
            users[n] = "dead"
            return "☠️ 위험구역 사망"

    if distance_m(lat, lon, TARGET_LAT, TARGET_LON) < RADIUS_M:
        if not gps_success[n]:
            money[n]+=100
            gps_success[n]=True
            return "성공 +100"

    return "OK"

# 관리자
@app.route("/admin", methods=["GET","POST"])
def admin():
    if request.method=="POST":
        if request.form.get("pw")==ADMIN_PW:
            session["admin"]=True

    if not session.get("admin"):
        return "<form method=post><input name=pw><button>login</button></form>"

    return """
<h2>관리자</h2>

<input id=user placeholder=유저>
<button onclick="freeze()">얼리기</button>
<button onclick="unfreeze()">해제</button>
<button onclick="kill()">즉사</button>

<script>
function freeze(){fetch("/freeze",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({user:document.getElementById("user").value})})}
function unfreeze(){fetch("/unfreeze",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({user:document.getElementById("user").value})})}
function kill(){fetch("/kill",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({target:document.getElementById("user").value})})}
</script>
"""

# 관리자 API
@app.route("/freeze", methods=["POST"])
def freeze():
    frozen[request.get_json()["user"]] = True
    return "ok"

@app.route("/unfreeze", methods=["POST"])
def unfreeze():
    u = request.get_json()["user"]
    if u in frozen:
        del frozen[u]
    return "ok"

@app.route("/kill", methods=["POST"])
def kill():
    users[request.get_json()["target"]] = "dead"
    return "ok"

@app.route("/get_danger")
def get_danger():
    if damage_zone:
        lat, lon, r = damage_zone
        return jsonify({"lat":lat,"lon":lon,"r":r})
    return jsonify({})

# 실행
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))