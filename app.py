from flask import Flask, request, session, redirect
import math, time, os, traceback

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "gps-game")  # 배포용 안전

# =====================
# 데이터
# =====================
users = {}        # alive / dead
money = {}
last_gps = {}     # name: (lat, lon, time)
gps_success = {}  # name: True

ADMIN_PW = "0808"

# 기준 위치 (원주시 지정면 가곡로 70 근처)
TARGET_LAT = 37.2756
TARGET_LON = 127.9025
RADIUS_M = 120

# =====================
# 거리 계산
# =====================
def distance_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

# =====================
# 로그인
# =====================
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        name = request.form.get("name")
        if not name:
            return "이름 없음"
        session.clear()
        session["name"] = name
        users.setdefault(name, "alive")
        money.setdefault(name, 0)
        gps_success.setdefault(name, False)
        return redirect("/game")

    return """
    <meta name=viewport content="width=device-width,initial-scale=1">
    <style>
    body{{font-family:system-ui;background:#020617;color:white;text-align:center;padding-top:40px}}
    input,button{{font-size:18px;padding:12px;border-radius:10px;border:none}}
    button{{background:#22c55e;font-weight:800}}
    </style>
    <form method=post>
        <h2>이름 입력</h2>
        <input name=name placeholder="닉네임"><br><br>
        <button>입장</button>
    </form>
    """

# =====================
# JS (GPS)
# =====================
def js():
    return """
<script>
function gps(){{
  const s=document.getElementById("status");
  s.innerText="📡 GPS 확인 중...";

  navigator.geolocation.getCurrentPosition(p=>{{
    fetch("/earn/gps_check",{{
      method:"POST",
      headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{
        lat:p.coords.latitude,
        lon:p.coords.longitude
      }})
    }}).then(r=>r.text()).then(t=>s.innerText=t)
  }},()=>{{
    fetch("/earn/gps_check",{{method:"POST"}})
      .then(r=>r.text()).then(t=>s.innerText=t)
  }})
}}
</script>
"""

# =====================
# 게임 화면
# =====================
@app.route("/game")
def game():
    n = session.get("name")
    if not n or n not in users:
        return redirect("/")

    if users.get(n) == "dead":
        return "<h1 style='text-align:center'>💀 즉사</h1>"

    return f"""
<!doctype html>
<meta name=viewport content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>
<style>
body{{margin:0;background:#0f172a;color:white;font-family:system-ui}}
#map{{height:60vh;border-radius:20px;margin-bottom:10px}}
.card{{padding:15px}}
.btn{{width:100%;padding:15px;font-size:18px;border:none;border-radius:12px;
background:#22c55e;color:black;font-weight:900;margin-top:10px}}
</style>

<div class=card>
<h2>👤 {n}</h2>
💰 돈: {money[n]}<br>
<div id="dist">📏 거리 계산 중...</div>
<button class=btn onclick="sendGPS()">📡 미션 체크</button>
</div>

<div id="map"></div>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
<script>
let map = L.map('map').setView([{TARGET_LAT}, {TARGET_LON}], 17);

L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 19
}}).addTo(map);

// 🎯 목표 위치
let target = L.marker([{TARGET_LAT}, {TARGET_LON}]).addTo(map)
.bindPopup("🎯 목표").openPopup();

// 📍 내 위치
let me = null;

function updatePosition(pos){{
    let lat = pos.coords.latitude;
    let lon = pos.coords.longitude;

    if(me) map.removeLayer(me);

    me = L.marker([lat, lon]).addTo(map)
        .bindPopup("📍 나");

    map.setView([lat, lon], 17);

    // 거리 계산
    let dist = getDistance(lat, lon, {TARGET_LAT}, {TARGET_LON});
    document.getElementById("dist").innerText = "📏 거리: " + Math.floor(dist) + "m";

    // 가까우면 색 바꾸기
    if(dist < {RADIUS_M}){{
        document.body.style.background = "#022c22";
    }}
}}

// 거리 계산 (JS)
function getDistance(lat1, lon1, lat2, lon2){{
    const R = 6371000;
    let dLat = (lat2-lat1)*Math.PI/180;
    let dLon = (lon2-lon1)*Math.PI/180;
    let a =
        Math.sin(dLat/2)*Math.sin(dLat/2) +
        Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180) *
        Math.sin(dLon/2)*Math.sin(dLon/2);
    let c = 2*Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    return R*c;
}}

// 서버로 보내기
function sendGPS(){{
    navigator.geolocation.getCurrentPosition(p=>{{
        fetch("/earn/gps_check",{{
            method:"POST",
            headers:{{"Content-Type":"application/json"}},
            body:JSON.stringify({{
                lat:p.coords.latitude,
                lon:p.coords.longitude
            }})
        }})
        .then(r=>r.text())
        .then(t=>alert(t));
    }});
}}

// 🔄 실시간 위치 추적
navigator.geolocation.watchPosition(updatePosition);
</script>
"""
# =====================
# GPS 체크
# =====================
@app.route("/earn/gps_check", methods=["POST"])
def gps_check():
    try:
        n = session.get("name")
        if not n or n not in users:
            return "로그인 필요"

        if users.get(n) == "dead":
            return "💀 이미 탈락"

        now = time.time()

        if request.is_json:
            data = request.get_json(silent=True)
            lat = data.get("lat", TARGET_LAT + 1)
            lon = data.get("lon", TARGET_LON + 1)
        else:
            lat = TARGET_LAT + 1
            lon = TARGET_LON + 1

        # 순간이동 감지
        if n in last_gps:
            plat, plon, pt = last_gps[n]
            d = distance_m(plat, plon, lat, lon)
            if d > 700 and now - pt < 3:
                users[n] = "dead"
                return "🚨 순간이동 감지 → 즉사"

        last_gps[n] = (lat, lon, now)

        # 거리 계산
        dist = distance_m(lat, lon, TARGET_LAT, TARGET_LON)

        # 미션 결과
        if dist <= RADIUS_M:
            if not gps_success.get(n):
                money[n] += 100
                gps_success[n] = True
                return "✅ 미션 성공! +100원"
            else:
                return "⚠️ 이미 완료한 미션"
        else:
            return f"❌ 실패 (약 {int(dist)}m 남음)"
    except Exception:
        traceback.print_exc()
        return "서버 오류 발생 😢", 500

# =====================
# 관리자 화면 + GPS 시작
# =====================
@app.route("/admin", methods=["GET","POST"])
def admin():
    out = ""
    if request.method == "POST":
        if request.form.get("pw") == ADMIN_PW:
            session["admin"] = True
        elif request.form.get("action") == "start_gps" and session.get("admin"):
            # 모든 유저 GPS 미션 초기화
            for u in users:
                gps_success[u] = False
            out += "<p>📡 모든 유저 GPS 미션 시작!</p>"

    if not session.get("admin"):
        return """
        <form method=post>
        관리자 비번:<input name=pw>
        <button>접속</button>
        </form>
        """

    # 관리자 화면
    out += "<h2>관리자</h2>"
    out += "<form method=post><button name=action value=start_gps>📡 GPS 미션 시작</button></form><br>"

    for u in users:
        out += f"{u}: {users[u]} / {users[u]} / 돈 {money[u]} / GPS 완료: {gps_success.get(u, False)}<br>"

    return out

# =====================
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
