from flask import Flask, request, session, redirect, jsonify
import math, time, os, traceback, random

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "gps-game")

# =====================
# 데이터
# =====================
users = {}
money = {}
last_gps = {}
gps_success = {}

# 에어드랍
airdrops = []
drop_id = 0

# 현상금
bounty_target = None
BOUNTY_REWARD = 500

# 공지
broadcast_msg = ""
broadcast_time = 0
broadcast_type = "normal"

ADMIN_PW = "0808"

TARGET_LAT = 37.377971
TARGET_LON = 127.877029
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
@app.route("/", methods=["GET","POST"])
def index():
    if request.method == "POST":
        n = request.form.get("name")
        session["name"] = n

        if n not in users:
            users[n] = "alive"
            money[n] = 0
            gps_success[n] = False

        return redirect("/game")

    return """
    <form method=post>
    <h2>이름 입력</h2>
    <input name=name>
    <button>입장</button>
    </form>
    """

# =====================
# 게임 화면
# =====================
@app.route("/game")
def game():
    n = session.get("name")
    if not n: return redirect("/")

    return f"""
<!doctype html>
<meta name=viewport content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>

<style>
body{{margin:0;background:#0f172a;color:white}}
#map{{height:60vh}}
#notice{{position:fixed;top:0;width:100%;padding:10px;display:none}}
</style>

<div>
<h3>{n} 💰{money[n]}</h3>
<div id="status"></div>
</div>

<div id="map"></div>

<div id="notice"><span id="noticeText"></span></div>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>

<script>
let map = L.map('map').setView([{TARGET_LAT},{TARGET_LON}],17);

L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);

let me;

// 내 위치
navigator.geolocation.watchPosition(p=>{{
 let lat=p.coords.latitude;
 let lon=p.coords.longitude;

 if(me) map.removeLayer(me);
 me=L.marker([lat,lon]).addTo(map);

 fetch("/gps",{{
  method:"POST",
  headers:{{"Content-Type":"application/json"}},
  body:JSON.stringify({{lat:lat,lon:lon}})
 }});
}});

// 에어드랍
let drops=[]
function loadDrops(){{
 fetch("/airdrops").then(r=>r.json()).then(data=>{{
  drops.forEach(d=>map.removeLayer(d));
  drops=[];

  data.forEach(d=>{{
   let m=L.marker([d.lat,d.lon]).addTo(map)
    .bindPopup("🪂<br><button onclick='pickup("+d.id+")'>줍줍</button>");
   drops.push(m);
  }});
 }});
}}

function pickup(id){{
 fetch("/pickup",{{
  method:"POST",
  headers:{{"Content-Type":"application/json"}},
  body:JSON.stringify({{id:id}})
 }}).then(r=>r.text()).then(alert);
}}

setInterval(loadDrops,3000);

// 공지
let last=0;
function notice(){{
 fetch("/get_broadcast").then(r=>r.json()).then(d=>{{
  if(d.time>last){{
   last=d.time;
   let box=document.getElementById("notice");
   let t=document.getElementById("noticeText");

   t.innerText=d.msg;

   if(d.type=="danger"){{
    box.style.background="red";
    box.style.color="white";
   }}else{{
    box.style.background="black";
    box.style.color="yellow";
   }}

   box.style.display="block";
   setTimeout(()=>box.style.display="none",8000);
  }}
 }});
}}

setInterval(notice,2000);

// 현상금 표시
function bounty(){{
 fetch("/bounty").then(r=>r.json()).then(d=>{{
  if(d.target){{
   document.getElementById("status").innerText=
    "🎯 현상금: "+d.target+" ("+d.reward+"원)";
  }}
 }});
}}

setInterval(bounty,3000);
</script>
"""

# =====================
# GPS
# =====================
@app.route("/gps", methods=["POST"])
def gps():
    n=session.get("name")
    data=request.get_json()

    lat=data["lat"]
    lon=data["lon"]

    last_gps[n]=(lat,lon,time.time())
    return "ok"

# =====================
# 에어드랍
# =====================
@app.route("/airdrops")
def get_drops():
    return jsonify(airdrops)

@app.route("/add_drop", methods=["POST"])
def add_drop():
    global drop_id
    if not session.get("admin"): return "권한 없음"

    data=request.get_json()
    drop_id+=1
    airdrops.append({"id":drop_id,"lat":data["lat"],"lon":data["lon"]})
    return "ok"

@app.route("/remove_drop", methods=["POST"])
def remove_drop():
    if not session.get("admin"): return "권한 없음"
    did=request.get_json()["id"]

    global airdrops
    airdrops=[d for d in airdrops if d["id"]!=did]
    return "ok"

@app.route("/pickup", methods=["POST"])
def pickup():
    n=session.get("name")
    did=request.get_json()["id"]

    drop=next((d for d in airdrops if d["id"]==did),None)
    if not drop: return "없음"

    lat,lon,_=last_gps.get(n,(0,0,0))
    dist=distance_m(lat,lon,drop["lat"],drop["lon"])

    if dist>30: return "❌ 멀다"

    if random.random()<0.2:
        users[n]="dead"
        msg="💀 함정"
    else:
        money[n]+=50
        msg="🎁 +50원"

    airdrops.remove(drop)
    return msg

# =====================
# 현상금
# =====================
@app.route("/set_bounty", methods=["POST"])
def set_bounty():
    global bounty_target, broadcast_msg, broadcast_time, broadcast_type

    if not session.get("admin"): return "권한 없음"

    target=request.get_json()["target"]
    bounty_target=target

    broadcast_msg=f"🚨 현상금 수배: [{target}]을 생포하세요!"
    broadcast_type="danger"
    broadcast_time=time.time()

    return "ok"

@app.route("/bounty")
def bounty():
    return {"target":bounty_target,"reward":BOUNTY_REWARD}

# =====================
# 공지
# =====================
@app.route("/broadcast", methods=["POST"])
def broadcast():
    global broadcast_msg,broadcast_time,broadcast_type

    if not session.get("admin"): return "권한 없음"

    d=request.get_json()
    broadcast_msg=d["msg"]
    broadcast_type=d.get("type","normal")
    broadcast_time=time.time()

    return "ok"

@app.route("/get_broadcast")
def get_broadcast():
    return {
        "msg":broadcast_msg,
        "time":broadcast_time,
        "type":broadcast_type
    }

# =====================
# 관리자
# =====================
@app.route("/admin", methods=["GET","POST"])
def admin():
    if request.method=="POST":
        if request.form.get("pw")==ADMIN_PW:
            session["admin"]=True

    if not session.get("admin"):
        return """
        <form method=post>
        비번:<input name=pw>
        <button>로그인</button>
        </form>
        """

    return """
<h2>관리자</h2>

<h3>현상금</h3>
<input id="target">
<button onclick="b()">지정</button>

<h3>공지</h3>
<input id="msg">
<button onclick="send()">전송</button>

<h3>에어드랍</h3>
<div id="map" style="height:400px"></div>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>

<script>
let map=L.map('map').setView([37.377971,127.877029],17);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

map.on("click",e=>{
 fetch("/add_drop",{
  method:"POST",
  headers:{"Content-Type":"application/json"},
  body:JSON.stringify({lat:e.latlng.lat,lon:e.latlng.lng})
 });
});

function b(){
 fetch("/set_bounty",{
  method:"POST",
  headers:{"Content-Type":"application/json"},
  body:JSON.stringify({target:document.getElementById("target").value})
 });
}

function send(){
 fetch("/broadcast",{
  method:"POST",
  headers:{"Content-Type":"application/json"},
  body:JSON.stringify({msg:document.getElementById("msg").value,type:"danger"})
 });
}
</script>
"""

# =====================
if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))