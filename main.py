# main.py — MedAI Backend v2.3.2 (restore v2.2 UI + auto category)

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship
from datetime import datetime
import os, json

APP_TITLE = "MedAI Backend (safe)"
API_KEY = os.getenv("API_KEY", "m3dAI_7YtqgY2WJr9vQdXz")  # tvoj aktuálny kľúč
DATABASE_URL = os.getenv("DATABASE_URL")

# --- DB ---
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True)
    uid = Column(String(64), unique=True, index=True, nullable=False)
    first_name = Column(String(120))
    last_name = Column(String(120))
    created_at = Column(DateTime, default=datetime.utcnow)
    records = relationship("Record", back_populates="patient", cascade="all,delete")

class Record(Base):
    __tablename__ = "records"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), index=True, nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(32), default="NOTE")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    patient = relationship("Patient", back_populates="records")

Base.metadata.create_all(engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- app ---
app = FastAPI(title=APP_TITLE)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# ---- API KEY guard ----
def require_api_key(req: Request):
    k = req.headers.get("x-api-key") or req.query_params.get("api_key")
    if not k or k != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

# ---- utils ----
def guess_category(text: str) -> str:
    t = (text or "").lower()
    if "crp" in t or "mg/l" in t or "k+" in t or "na+" in t or "hb" in t or "lab" in t:
        return "LAB"
    if "ekg" in t or "sinus" in t or "tachy" in t or "brady" in t or "fibril" in t:
        return "EKG"
    if "rtg" in t or "röntgen" in t or "x-ray" in t or "hrudníka" in t:
        return "RTG"
    return "NOTE"

# ---- HEALTH ----
@app.get("/health")
def health(): return {"status":"ok"}

# ---- PATIENTS ----
class PatientIn(BaseModel):
    patient_uid: str
    first_name: str | None = None
    last_name: str | None = None

@app.get("/patients", dependencies=[Depends(require_api_key)])
def list_patients(db: Session = Depends(get_db)):
    pts = db.query(Patient).order_by(Patient.created_at.desc(), Patient.id.desc()).all()
    return [{"uid":p.uid, "first_name":p.first_name, "last_name":p.last_name} for p in pts]

@app.post("/patients", dependencies=[Depends(require_api_key)])
def create_patient(p: PatientIn, db: Session = Depends(get_db)):
    existing = db.query(Patient).filter(Patient.uid==p.patient_uid).first()
    if existing:
        return {"id": existing.id, "patient_uid": existing.uid}
    obj = Patient(uid=p.patient_uid, first_name=p.first_name, last_name=p.last_name)
    db.add(obj); db.commit(); db.refresh(obj)
    return {"id": obj.id, "patient_uid": obj.uid}

# ---- RECORDS ----
@app.get("/patients/{patient_uid}/records", dependencies=[Depends(require_api_key)])
def get_records(patient_uid: str, db: Session = Depends(get_db)):
    try:
        patient = db.query(Patient).filter(Patient.uid==patient_uid).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        recs = (db.query(Record)
                .filter(Record.patient_id==patient.id)
                .order_by(Record.created_at.asc(), Record.id.asc())
                .all())
        return [{"id":r.id,"content":r.content,"category":r.category,
                 "created_at": r.created_at.isoformat()} for r in recs]
    except HTTPException: raise
    except Exception as e:
        print(f"⚠️ get_records error for {patient_uid}: {e}")
        return []  # UI nespadne

@app.post("/patients/{patient_uid}/records", dependencies=[Depends(require_api_key)])
async def add_record(patient_uid: str, request: Request, db: Session = Depends(get_db)):
    try:
        raw = await request.body()
        if not raw: raise HTTPException(status_code=422, detail="Empty body")
        content, category, ts = None, None, None
        try:
            data = json.loads(raw)
            if isinstance(data, str):
                content = data.strip()
            else:
                content = (data.get("content") or "").strip()
                category = data.get("category") or None
                ts_str = data.get("ts")
                if ts_str: ts = datetime.fromisoformat(ts_str.replace("Z","+00:00"))
        except Exception:
            content = raw.decode("utf-8").strip()
        if not content: raise HTTPException(status_code=422, detail="Missing 'content'")
        if not category: category = guess_category(content)

        patient = db.query(Patient).filter(Patient.uid==patient_uid).first()
        if not patient: raise HTTPException(status_code=404, detail="Patient not found")

        rec = Record(patient_id=patient.id, content=content,
                     category=category, created_at=ts or datetime.utcnow())
        db.add(rec); db.commit(); db.refresh(rec)
        return {"id":rec.id,"patient_uid":patient_uid,"category":rec.category,
                "created_at":rec.created_at.isoformat()}
    except HTTPException: raise
    except Exception as e:
        db.rollback(); print(f"❌ add_record error for {patient_uid}: {e}")
        raise HTTPException(status_code=500, detail="save_failed")

# ---- HEURISTIC SUMMARY (Epikríza draft) ----
@app.get("/summary/{patient_uid}", dependencies=[Depends(require_api_key)])
def summary(patient_uid: str, db: Session = Depends(get_db)):
    p = db.query(Patient).filter(Patient.uid==patient_uid).first()
    if not p: raise HTTPException(status_code=404, detail="Patient not found")
    recs = (db.query(Record).filter(Record.patient_id==p.id)
            .order_by(Record.created_at.asc()).all())
    by = {"LAB":[],"EKG":[],"RTG":[],"NOTE":[]}
    for r in recs: by.get(r.category,"NOTE").append(r)

    def lines(cat): 
        return "\n".join([f"- {r.created_at.date()}: {r.content}" for r in cat])

    text = f"""EPIKRÍZA – draft (heuristická)
Pacient: {p.first_name or ''} {p.last_name or ''} (UID {p.uid})
Hospitalizačný priebeh:
{lines(by["NOTE"]) or "- bez slovných záznamov"}

Laboratórne:
{lines(by["LAB"]) or "- bez záznamov"}

EKG:
{lines(by["EKG"]) or "- bez záznamov"}

RTG/USG:
{lines(by["RTG"]) or "- bez záznamov"}

Záver:
- (doplní lekár)
Odporúčania pri prepustení:
- (doplní lekár)
"""
    return {"epikriza": text}

# ---- UI (v2.2 štýl + filtre) ----
INDEX_HTML = f"""
<!doctype html>
<html lang="sk">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>MedAI Dashboard 2.3 (DB)</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;background:#f6f8fb;margin:0}}
.header{{background:#134a9a;color:#fff;padding:14px 18px;display:flex;gap:12px;align-items:center}}
.header input{{padding:8px;border:none;border-radius:6px;width:260px}}
.badge{{background:#e6f5ff;color:#134a9a;border-radius:999px;padding:4px 10px;font-size:12px}}
.wrap{{max-width:1100px;margin:14px auto;padding:0 10px}}
.row{{display:flex;gap:16px;align-items:flex-start}}
.col{{flex:1}}
.card{{background:#fff;border-radius:12px;box-shadow:0 3px 14px rgba(0,0,0,.06);padding:16px}}
.btn{{background:#134a9a;color:#fff;border:none;border-radius:8px;padding:10px 14px;cursor:pointer}}
.btn.ghost{{background:#e9eef8;color:#134a9a}}
input,textarea,select{{width:100%;padding:10px;border:1px solid #dce4ef;border-radius:8px;margin:6px 0}}
h2{{margin:8px 0 6px 0}}
ul.list{{list-style:none;padding:0;margin:0;max-height:300px;overflow:auto}}
ul.list li{{padding:8px;border-bottom:1px solid #eee;cursor:pointer}}
ul.list li.active{{
  background:#eef5ff
}}
.tag{{display:inline-block;background:#eef5ff;color:#134a9a;border-radius:999px;padding:2px 8px;font-size:12px;margin-left:6px}}
.filters .btn{{padding:6px 10px}}
pre{{white-space:pre-wrap;background:#0f172a;color:#e2e8f0;padding:12px;border-radius:10px}}
.small{{color:#666;font-size:12px}}
</style>
</head>
<body>
  <div class="header">
    <b>MedAI Dashboard 2.3</b>
    <input id="apiKey" placeholder="API Key" value="{API_KEY}"/>
    <span id="status" class="badge">offline</span>
  </div>

  <div class="wrap">
    <div class="row">
      <!-- ľavý panel: pacienti -->
      <div class="col" style="max-width:320px">
        <div class="card">
          <h2>Pacienti</h2>
          <div class="row" style="gap:8px">
            <input id="uid" placeholder="UID (napr. P001)"/>
            <input id="first" placeholder="Meno"/>
            <input id="last" placeholder="Priezvisko"/>
            <button class="btn" onclick="createPatient()">Vytvoriť</button>
          </div>
          <div class="row" style="gap:8px;margin-top:6px">
            <button class="btn ghost" onclick="loadPatients()">Načítať pacientov</button>
          </div>
          <div id="pErr" class="small" style="color:#c0392b;margin-top:6px"></div>
          <ul id="plist" class="list" style="margin-top:8px"></ul>
        </div>
      </div>

      <!-- pravý panel: záznamy a epikríza -->
      <div class="col">
        <div class="card">
          <h2>Záznamy</h2>
          <div class="filters" style="margin-bottom:6px">
            <button class="btn ghost" onclick="setFilter('ALL')">Všetko</button>
            <button class="btn ghost" onclick="setFilter('LAB')">LAB</button>
            <button class="btn ghost" onclick="setFilter('EKG')">EKG</button>
            <button class="btn ghost" onclick="setFilter('RTG')">RTG</button>
            <button class="btn ghost" onclick="setFilter('NOTE')">Poznámky</button>
            <span id="count" class="small" style="margin-left:8px"></span>
          </div>
          <textarea id="content" rows="3" placeholder='Obsah (text alebo JSON)'></textarea>
          <div class="row" style="gap:8px">
            <button class="btn" onclick="saveRecord()">Uložiť</button>
            <button class="btn ghost" onclick="loadRecords()">Načítať záznamy</button>
            <button class="btn" onclick="makeSummary()">Vytvoriť epikrízu</button>
          </div>
          <div id="rErr" class="small" style="color:#c0392b;margin-top:6px"></div>
          <div id="records" style="margin-top:8px"></div>
        </div>

        <div class="card" style="margin-top:12px">
          <h2>Epikríza (náhľad)</h2>
          <pre id="summaryBox" class="small">—</pre>
        </div>
      </div>
    </div>
  </div>

<script>
let currentUID = null;
let allRecords = [];
let filterCat = "ALL";

function api(){ return document.getElementById('apiKey').value.trim(); }
function headers(){ return {'x-api-key': api(), 'Content-Type':'application/json'}; }
function setOnline(ok){ 
  const s=document.getElementById('status'); 
  s.textContent = ok? 'online':'offline';
  s.style.background = ok? '#e6ffed':'#ffe6e6';
  s.style.color = ok? '#137333':'#8a1d1d';
}

async function ping(){
  try{
    const r = await fetch('/health');
    setOnline(r.ok);
  }catch(e){ setOnline(false); }
}
ping();

function setFilter(cat){ filterCat = cat; renderRecords(); }

function renderPatients(items){
  const ul = document.getElementById('plist'); ul.innerHTML='';
  items.forEach(p=>{
    const li = document.createElement('li');
    li.textContent = `${p.uid} — ${p.first_name||''} ${p.last_name||''}`.trim();
    li.onclick = ()=>{ 
      currentUID = p.uid; 
      [...ul.children].forEach(n=>n.classList.remove('active'));
      li.classList.add('active');
      loadRecords();
    };
    ul.appendChild(li);
  });
}

function renderRecords(){
  const box = document.getElementById('records'); box.innerHTML='';
  const show = allRecords.filter(r => filterCat==='ALL' || r.category===filterCat);
  document.getElementById('count').textContent = `Zobrazené: ${show.length} / ${allRecords.length}`;
  if(show.length===0){ box.innerHTML = '<div class="small">Žiadne záznamy</div>'; return; }
  show.forEach(r=>{
    const div = document.createElement('div');
    div.style.borderBottom='1px solid #eee'; div.style.padding='8px 0';
    div.innerHTML = `<div class="small">${r.created_at}</div>
      <div>${r.content} <span class="tag">${r.category}</span></div>`;
    box.appendChild(div);
  });
}

async function loadPatients(){
  document.getElementById('pErr').textContent='';
  try{
    const r = await fetch(`/patients?api_key=${encodeURIComponent(api())}`);
    if(!r.ok) throw new Error(await r.text());
    const data = await r.json();
    renderPatients(data);
  }catch(e){ document.getElementById('pErr').textContent='Chyba: '+(e.message||e); }
}

async function createPatient(){
  document.getElementById('pErr').textContent='';
  const uid=document.getElementById('uid').value.trim();
  const first=document.getElementById('first').value.trim();
  const last=document.getElementById('last').value.trim();
  if(!uid){ document.getElementById('pErr').textContent='Zadaj UID'; return; }
  try{
    const r = await fetch('/patients', {method:'POST', headers:headers(),
      body: JSON.stringify({patient_uid:uid, first_name:first, last_name:last})});
    if(!r.ok) throw new Error(await r.text());
    await loadPatients();
  }catch(e){ document.getElementById('pErr').textContent='Chyba: '+(e.message||e); }
}

async function loadRecords(){
  document.getElementById('rErr').textContent='';
  if(!currentUID){ document.getElementById('rErr').textContent='Vyber pacienta'; return; }
  try{
    const r = await fetch(`/patients/${encodeURIComponent(currentUID)}/records?api_key=${encodeURIComponent(api())}`);
    if(!r.ok) throw new Error(await r.text());
    allRecords = await r.json();
    renderRecords();
  }catch(e){ document.getElementById('rErr').textContent='Chyba: '+(e.message||e); }
}

async function saveRecord(){
  document.getElementById('rErr').textContent='';
  if(!currentUID){ document.getElementById('rErr').textContent='Vyber pacienta'; return; }
  let text = document.getElementById('content').value.trim();
  if(!text){ document.getElementById('rErr').textContent='Prázdny obsah'; return; }
  // odosielame buď JSON alebo text – backend vie oboje
  let body = text;
  try{ const parsed = JSON.parse(text); body = JSON.stringify(parsed); }catch(_){ body = JSON.stringify({"content":text}); }
  try{
    const r = await fetch(`/patients/${encodeURIComponent(currentUID)}/records`, {
      method:'POST', headers: {'x-api-key': api(), 'Content-Type':'application/json'}, body});
    if(!r.ok) throw new Error(await r.text());
    document.getElementById('content').value='';
    await loadRecords();
  }catch(e){ document.getElementById('rErr').textContent='Chyba: '+(e.message||e); }
}

async function makeSummary(){
  document.getElementById('rErr').textContent='';
  if(!currentUID){ document.getElementById('rErr').textContent='Vyber pacienta'; return; }
  try{
    const r = await fetch(`/summary/${encodeURIComponent(currentUID)}?api_key=${encodeURIComponent(api())}`);
    if(!r.ok) throw new Error(await r.text());
    const data = await r.json();
    document.getElementById('summaryBox').textContent = data.epikriza || '—';
  }catch(e){ document.getElementById('rErr').textContent='Chyba: '+(e.message||e); }
}
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index(): return HTMLResponse(INDEX_HTML)
