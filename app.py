from flask import Flask, request, session, redirect, jsonify
import math, time, os, threading, html, json
from threading import RLock

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

# 저장 도중에도 같은 요청이 안전하게 잠금을 다시 사용할 수 있게 한다.
data_lock = RLock()
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
                            "id": int(time.time() * 1000)
                        })
                    events.remove(e)
                    save_data()
        time.sleep(1)


# ====================== 시작 ======================
# 기존 데이터를 먼저 읽어야 빈 초기 상태가 저장 파일을 덮어쓰지 않는다.
load_data()
threading.Thread(target=event_loop, daemon=True).start()
threading.Thread(target=auto_save_loop, daemon=True).start()


# ====================== 로그인 ======================
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
        <input name=name placeholder="닉네임" style="padding:12px;font-size:18px;width:280px"><br><br>
        <button style="padding:12px 30px;font-size:18px">입장하기</button>
    </form>
    """
