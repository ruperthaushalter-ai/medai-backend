from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
import os

# ================== APP CONFIG ==================
app = FastAPI(title="MedAI 3.5 – Multilayer Timeline")

SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 90

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================== IN-MEMORY DB ==================
users_db = {}
patients_db = []
records_db = []

# ================== MODELS ==================
class User(BaseModel):
    username: str
    hashed_password: str
    role: str = "doctor"

class UserIn(BaseModel):
    username: str
    password: str

class Patient(BaseModel):
    id: int
    first_name: str
    last_name: str
    admission_date: str
    status: str = "hospitalized"
    assigned_to: str | None = None

class Record(BaseModel):
    id: int
    patient_id: int
    timestamp: str
    category: str
    content: str

# ================== AUTH HELPERS ==================
def verify_password(plain, hashed): return pwd_context.verify(plain, hashed)
def get_password_hash(password): return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_user(username: str): return users_db.get(username)

def authenticate_user(username: str, password: str):
    user = get_user(username)
    if not user or not verify_password(password, user.hashed_password):
        return False
    return user

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None: raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = get_user(username)
    if user is None: raise HTTPException(status_code=401, detail="User not found")
    return user

# ================== AUTH ENDPOINTS ==================
@app.post("/register")
def register(user: UserIn):
    if user.username in users_db: raise HTTPException(400, "User already exists")
    users_db[user.username] = User(username=user.username, hashed_password=get_password_hash(user.password))
    return {"status": "registered", "username": user.username}

@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user: raise HTTPException(401, "Incorrect username or password")
    token = create_access_token({"sub": user.username})
    return {"access_token": token, "token_type": "bearer"}

# ================== PATIENTS ==================
@app.get("/patients")
def get_patients(current_user: User = Depends(get_current_user)):
    return [p for p in patients_db if p.assigned_to == current_user.username]

@app.post("/patients")
def add_patient(first_name: str, last_name: str, current_user: User = Depends(get_current_user)):
    new_id = len(patients_db) + 1
    p = Patient(
        id=new_id,
        first_name=first_name,
        last_name=last_name,
        admission_date=datetime.utcnow().strftime("%Y-%m-%d"),
        assigned_to=current_user.username
    )
    patients_db.append(p)
    return {"status": "added", "patient": p}

# ================== IMPORT & CATEGORIZATION ==================
def detect_category(text: str) -> str:
    t = (text or "").lower()
    if any(x in t for x in ["crp", "hb", "leu", "gluk", "k+", "na+", "mmol", "mg/l"]): return "LAB"
    if any(x in t for x in ["ekg", "fibril", "tachy", "brady"]): return "EKG"
    if any(x in t for x in ["rtg", "röntgen", "rentgen", "infiltrát", "pneumon"]): return "RTG"
    if any(x in t for x in ["ceftriax", "amoxicil", "podan", "lieč", "infuz"]): return "THERAPY"
    if any(x in t for x in ["teplota", "tlak", "sat", "frekv"]): return "VITALS"
    return "NOTE"

@app.post("/import")
async def import_data(
    patient_id: int = Form(...),
    text: str = Form(None),
    file: UploadFile = File(None),
    current_user: User = Depends(get_current_user)
):
    patient = next((p for p in patients_db if p.id == patient_id and p.assigned_to == current_user.username), None)
    if not patient: raise HTTPException(404, "Patient not found or not yours")

    if file:
        content = (await file.read()).decode("utf-8", errors="ignore")
    else:
        content = text or ""

    category = detect_category(content)
    rec = Record(
        id=len(records_db) + 1,
        patient_id=patient_id,
        timestamp=datetime.utcnow().isoformat(),
        category=category,
        content=content.strip()
    )
    records_db.append(rec)
    return {"status": "imported", "category": category, "record_id": rec.id}

@app.get("/records/{pid}")
def get_records(pid: int, current_user: User = Depends(get_current_user)):
    patient = next((p for p in patients_db if p.id == pid and p.assigned_to == current_user.username), None)
    if not patient: raise HTTPException(404, "Patient not found or not yours")
    return sorted([r for r in records_db if r.patient_id == pid], key=lambda r: r.timestamp)

# ================== TIMELINE API ==================
@app.get("/timeline/{pid}")
def timeline(pid: int, current_user: User = Depends(get_current_user)):
    patient = next((p for p in patients_db if p.id == pid and p.assigned_to == current_user.username), None)
    if not patient: raise HTTPException(404, "Patient not found or not yours")
    recs = sorted([r for r in records_db if r.patient_id == pid], key=lambda r: r.timestamp)

    # Normalizovaný výstup pre UI
    return {
        "patient": {
            "id": patient.id,
            "name": f"{patient.first_name} {patient.last_name}",
            "admission_date": patient.admission_date,
            "status": patient.status
        },
        "records": [
            {
                "id": r.id,
                "timestamp": r.timestamp,
                "category": r.category,
                "content": r.content
            } for r in recs
        ]
    }

# ================== UI (Dashboard s multilayer timeline) ==================
@app.get("/")
def ui():
    return """
    <html>
    <head>
      <title>MedAI 3.5 – Multivrstvová Timeline</title>
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <style>
        body{font-family:Arial, sans-serif;background:#f4f6fa;color:#111;margin:0;padding:20px;}
        .card{background:#fff;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.08);padding:16px;margin:12px 0;}
        input{padding:8px;border:1px solid #ccc;border-radius:6px;margin:4px 6px 4px 0;}
        button{background:#1e4e9a;color:#fff;border:none;border-radius:6px;padding:8px 12px;cursor:pointer}
        .row{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
        .filters{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
        .legend{display:flex;gap:16px;margin-top:6px;font-size:14px}
        .legend span{display:flex;align-items:center;gap:6px}
        .dot{width:10px;height:10px;border-radius:50%}
        canvas{width:100%;height:320px;border:1px solid #e6e6e6;border-radius:8px;background:#fff}
        #tooltip{position:fixed;background:#111;color:#fff;padding:6px 8px;border-radius:6px;font-size:12px;pointer-events:none;opacity:0;transition:opacity .1s}
        .muted{color:#666}
        .pill{display:inline-block;padding:3px 8px;border-radius:999px;font-size:12px;background:#eef3ff;color:#1e4e9a;margin-left:6px}
      </style>
    </head>
    <body>
      <h2>📊 MedAI 3.5 – Multivrstvová timeline</h2>

      <div class="card">
        <div class="row">
          <div>
            <div><b>Prihlásenie</b></div>
            <input id="user" placeholder="Meno">
            <input id="pass" type="password" placeholder="Heslo">
            <button onclick="login()">Prihlásiť</button>
          </div>
          <div>
            <div><b>Pacient</b></div>
            <input id="pid" placeholder="ID pacienta" style="width:140px;">
            <button onclick="loadTimeline()">Načítať timeline</button>
          </div>
          <div id="pinfo" class="muted"></div>
        </div>
        <div class="filters">
          <label><input type="checkbox" class="flt" value="LAB" checked> LAB</label>
          <label><input type="checkbox" class="flt" value="RTG" checked> RTG</label>
          <label><input type="checkbox" class="flt" value="EKG" checked> EKG</label>
          <label><input type="checkbox" class="flt" value="THERAPY" checked> Liečba</label>
          <label><input type="checkbox" class="flt" value="VITALS" checked> Vitálne</label>
          <label><input type="checkbox" class="flt" value="NOTE" checked> Poznámky</label>
          <button onclick="toggleAll(true)">Všetko</button>
          <button onclick="toggleAll(false)">Nič</button>
        </div>
        <div class="legend">
          <span><span class="dot" style="background:#1e4e9a"></span>LAB</span>
          <span><span class="dot" style="background:#c0392b"></span>RTG</span>
          <span><span class="dot" style="background:#16a085"></span>EKG</span>
          <span><span class="dot" style="background:#f39c12"></span>Liečba</span>
          <span><span class="dot" style="background:#8e44ad"></span>Vitálne</span>
          <span><span class="dot" style="background:#7f8c8d"></span>Poznámky</span>
        </div>
      </div>

      <div class="card">
        <canvas id="timeline"></canvas>
        <div id="tooltip"></div>
      </div>

      <div class="card">
        <b>Posledné záznamy</b><span id="cnt" class="pill">0</span>
        <pre id="log" style="white-space:pre-wrap;background:#fbfbfb;border:1px solid #eee;border-radius:8px;padding:10px;margin-top:8px;max-height:260px;overflow:auto"></pre>
      </div>

      <script>
        // --- State ---
        let token=null, raw=[], filtered=[], patient=null, hitboxes=[];
        const colors={LAB:"#1e4e9a",RTG:"#c0392b",EKG:"#16a085",THERAPY:"#f39c12",VITALS:"#8e44ad",NOTE:"#7f8c8d"};
        const lanes=["LAB","RTG","EKG","THERAPY","VITALS","NOTE"];
        const laneY=(laneIndex,h,topPad=36,bottomPad=24)=> topPad + laneIndex*((h-topPad-bottomPad)/lanes.length) + 10;

        async function login(){
          const fd=new URLSearchParams();
          fd.append('username',document.getElementById('user').value);
          fd.append('password',document.getElementById('pass').value);
          const res=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:fd});
          const data=await res.json(); token=data.access_token;
          alert('✅ Prihlásenie OK');
        }

        function toggleAll(val){
          document.querySelectorAll('.flt').forEach(cb=>cb.checked=val);
          render();
        }

        async function loadTimeline(){
          const pid=document.getElementById('pid').value; if(!token){alert('Najprv sa prihlás');return;}
          const res=await fetch(`/timeline/${pid}`,{headers:{'Authorization':'Bearer '+token}});
          const data=await res.json();
          patient=data.patient; raw=data.records;
          document.getElementById('pinfo').innerHTML = `${patient.name} <span class="pill">${patient.status}</span> <span class="muted">príjem ${patient.admission_date}</span>`;
          render();
        }

        function activeCats(){
          const arr=[]; document.querySelectorAll('.flt:checked').forEach(cb=>arr.push(cb.value)); return arr;
        }

        function render(){
          if(!raw.length){draw([],[]); document.getElementById('log').textContent=''; document.getElementById('cnt').textContent='0'; return;}
          const cats=activeCats();
          filtered = raw.filter(r=>cats.includes(r.category));
          document.getElementById('cnt').textContent = filtered.length;
          document.getElementById('log').textContent = filtered.map(r=>`[${r.timestamp.slice(0,16).replace('T',' ')}] (${r.category}) ${r.content}`).join('\\n');
          draw(filtered, cats);
        }

        function draw(data, cats){
          const c=document.getElementById('timeline'); const ctx=c.getContext('2d');
          const DPR=window.devicePixelRatio||1; const cssW=c.clientWidth, cssH=c.clientHeight;
          c.width=cssW*DPR; c.height=cssH*DPR; ctx.setTransform(DPR,0,0,DPR,0,0); // crisp lines

          // background
          ctx.clearRect(0,0,cssW,cssH);
          ctx.fillStyle="#fff"; ctx.fillRect(0,0,cssW,cssH);

          // time bounds
          const all=(raw.length?raw:[]);
          if(!all.length){return;}
          const tmin=new Date(all[0].timestamp).getTime();
          const tmax=new Date(all[all.length-1].timestamp).getTime() || (tmin+1000);
          const leftPad=60, rightPad=20, topPad=36, bottomPad=24;

          // grid lanes & labels
          ctx.font="12px Arial"; ctx.fillStyle="#666"; ctx.strokeStyle="#eee";
          lanes.forEach((ln,idx)=>{
            const y=laneY(idx,cssH,topPad,bottomPad);
            ctx.beginPath(); ctx.moveTo(leftPad,y); ctx.lineTo(cssW-rightPad,y); ctx.stroke();
            ctx.fillText(ln,10,y+4);
          });

          // time axis ticks (5 ticks)
          const ticks=5;
          ctx.fillStyle="#666"; ctx.strokeStyle="#ddd";
          for(let i=0;i<=ticks;i++){
            const tx=leftPad + (i/ticks)*(cssW-leftPad-rightPad);
            ctx.beginPath(); ctx.moveTo(tx,topPad-8); ctx.lineTo(tx,cssH-bottomPad); ctx.stroke();
            const tt = new Date(tmin + (i/ticks)*(tmax-tmin));
            const label = tt.toISOString().slice(5,16).replace('T',' ');
            ctx.fillText(label, tx-28, topPad-14);
          }

          // plot items
          hitboxes=[];
          data.forEach(rec=>{
            const t=new Date(rec.timestamp).getTime();
            const x= leftPad + ((t - tmin)/(tmax - tmin || 1))*(cssW - leftPad - rightPad);
            const laneIdx = Math.max(0, lanes.indexOf(rec.category));
            const y= laneY(laneIdx,cssH,topPad,bottomPad);

            // point
            const color=colors[rec.category] || "#444";
            ctx.fillStyle=color; ctx.strokeStyle=color;

            // LAB = diamond, RTG = square, EKG = triangle, THERAPY = circle, VITALS = hex, NOTE = small circle
            const r=5;
            ctx.beginPath();
            if(rec.category==="LAB"){
              ctx.moveTo(x, y-r); ctx.lineTo(x+r, y); ctx.lineTo(x, y+r); ctx.lineTo(x-r, y); ctx.closePath(); ctx.fill();
            }else if(rec.category==="RTG"){
              ctx.fillRect(x-r, y-r, 2*r, 2*r);
            }else if(rec.category==="EKG"){
              ctx.moveTo(x, y-r); ctx.lineTo(x+r, y+r); ctx.lineTo(x-r, y+r); ctx.closePath(); ctx.fill();
            }else if(rec.category==="VITALS"){
              // hex
              const a=4; ctx.moveTo(x-a,y-r); ctx.lineTo(x+a,y-r); ctx.lineTo(x+r,y); ctx.lineTo(x+a,y+r); ctx.lineTo(x-a,y+r); ctx.lineTo(x-r,y); ctx.closePath(); ctx.fill();
            }else{
              ctx.arc(x,y,4,0,Math.PI*2); ctx.fill();
            }

            // vertical guide
            ctx.strokeStyle="#eee";
            ctx.beginPath(); ctx.moveTo(x, topPad-6); ctx.lineTo(x, cssH-bottomPad+6); ctx.stroke();

            // save hitbox
            hitboxes.push({x,y,rec,box:[x-8,y-8,16,16]});
          });

          // draw simple line for LAB trend if >1 LAB with numeric
          const labOnly = data.filter(d=>d.category==="LAB");
          const nums = labOnly.map(d=>{
            const m = String(d.content).match(/(\d+(?:\\.\\d+)?)/);
            return m ? parseFloat(m[1]) : null;
          });
          if(labOnly.length>=2 && nums.filter(v=>v!==null).length>=2){
            const ys = [];
            labOnly.forEach((d,i)=>{
              if(nums[i]!==null){
                const t=new Date(d.timestamp).getTime();
                const x= leftPad + ((t - tmin)/(tmax - tmin || 1))*(cssW - leftPad - rightPad);
                // scale numeric y into lane space (slightly above LAB line)
                const laneIdx = lanes.indexOf("LAB");
                const baseY = laneY(laneIdx,cssH,topPad,bottomPad);
                const min = Math.min(...nums.filter(v=>v!==null));
                const max = Math.max(...nums.filter(v=>v!==null));
                const y = baseY - 30 + ((nums[i]-min)/((max-min)||1))*(-40); // 40px range above LAB line
                ys.push({x,y});
              }
            });
            const ctx2 = ctx;
            ctx2.strokeStyle = colors.LAB;
            ctx2.lineWidth = 2;
            ctx2.beginPath();
            ys.forEach((p,i)=>{ if(i===0) ctx2.moveTo(p.x,p.y); else ctx2.lineTo(p.x,p.y); });
            ctx2.stroke();
            ctx2.lineWidth = 1;
          }
        }

        // Tooltip
        const ttip=document.getElementById('tooltip');
        document.getElementById('timeline').addEventListener('mousemove', (e)=>{
          const c=e.target; const rect=c.getBoundingClientRect();
          const x=e.clientX-rect.left, y=e.clientY-rect.top;
          let found=null;
          for(const h of hitboxes){
            const [bx,by,bw,bh]=h.box;
            if(x>=bx && x<=bx+bw && y>=by && y<=by+bh){found=h;break;}
          }
          if(found){
            ttip.style.opacity=1;
            ttip.style.left = (e.clientX+10)+'px';
            ttip.style.top  = (e.clientY+10)+'px';
            ttip.innerText = `[${found.rec.timestamp.slice(0,16).replace('T',' ')}] ${found.rec.category}: ${found.rec.content}`;
          }else{
            ttip.style.opacity=0;
          }
        });
      </script>
    </body>
    </html>
    """
