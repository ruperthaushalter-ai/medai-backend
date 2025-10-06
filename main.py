# main.py
import os
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Header, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session

# -----------------------------
# Konfigurácia a DB
# -----------------------------
API_KEY = os.getenv("MEDAI_API_KEY", "m3dAI_7YtqgY2WJr9vQdXz")
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL chýba – nastav ho v Railway Variables.")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# -----------------------------
# DB modely
# -----------------------------
class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True)
    uid = Column(String(64), unique=True, index=True, nullable=False)
    first_name = Column(String(128), nullable=True)
    last_name = Column(String(128), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    records = relationship("Record", back_populates="patient", cascade="all, delete-orphan")

class Record(Base):
    __tablename__ = "records"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), index=True, nullable=False)
    category = Column(String(32), index=True, nullable=False)  # NOTE/LAB/EKG/RTG/USG/CT/MR/CONSULT/THERAPY/OTHER
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    patient = relationship("Patient", back_populates="records")

Base.metadata.create_all(bind=engine)

# -----------------------------
# Pydantic schémy
# -----------------------------
class PatientIn(BaseModel):
    patient_uid: str = Field(..., examples=["P001"])
    first_name: Optional[str] = Field(None, examples=["Ján"])
    last_name: Optional[str] = Field(None, examples=["Novák"])

class PatientOut(BaseModel):
    id: int
    patient_uid: str
    first_name: Optional[str]
    last_name: Optional[str]

class RecordIn(BaseModel):
    content: str = Field(..., description="Voľný text, čísla, JSON – heuristika určí kategóriu")
    category: Optional[str] = Field(None, description="Ak vyplníš, použije sa. Inak sa určí automaticky.")

class RecordOut(BaseModel):
    id: int
    category: str
    content: str
    created_at: datetime

# -----------------------------
# FastAPI app & security
# -----------------------------
app = FastAPI(title="MedAI Backend (safe)", version="2.3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def require_api_key(x_api_key: Optional[str] = Header(None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

# -----------------------------
# Heuristika kategórií
# -----------------------------
def infer_category(text: str) -> str:
    t = text.strip().lower()

    # JSON so "type"?
    if t.startswith("{") and '"type"' in t:
        try:
            import json
            data = json.loads(t)
            v = str(data.get("type", "")).upper()
            if v:
                return v
        except Exception:
            pass

    lab_kw = ["crp", "hb", "k+", "na+", "leu", "tropon", "gluk", "mg/l", "mmol/l", "µmol/l", "g/l"]
    if any(k in t for k in lab_kw):
        return "LAB"

    if "ekg" in t or "pq" in t or "qrs" in t or "st " in t or "tachykard" in t or "bradykard" in t:
        return "EKG"

    if "rtg" in t or "röntgen" in t:
        return "RTG"
    if "usg" in t or "sono" in t or "ultrazvuk" in t:
        return "USG"
    if "ct " in t or "počítačová tomografia" in t:
        return "CT"
    if "mr " in t or "magnetická rezonancia" in t:
        return "MR"

    if "konzílium" in t or "konzil" in t or "odporúčame" in t or "dop." in t:
        return "CONSULT"

    if "podaná" in t or "dávka" in t or ("mg" in t and "i.v." in t) or "tbl" in t:
        return "THERAPY"

    return "NOTE"

# -----------------------------
# API endpoints
# -----------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

# Patients
@app.post("/patients", dependencies=[Depends(require_api_key)])
def create_patient(p: PatientIn, db: Session = Depends(get_db)):
    exists = db.query(Patient).filter(Patient.uid == p.patient_uid).first()
    if exists:
        return {"id": exists.id, "patient_uid": exists.uid}
    obj = Patient(uid=p.patient_uid, first_name=p.first_name, last_name=p.last_name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return {"id": obj.id, "patient_uid": obj.uid}

@app.get("/patients", dependencies=[Depends(require_api_key)], response_model=List[PatientOut])
def list_patients(db: Session = Depends(get_db)):
    rows = db.query(Patient).order_by(Patient.uid.asc()).all()
    return [
        PatientOut(id=r.id, patient_uid=r.uid, first_name=r.first_name, last_name=r.last_name)
        for r in rows
    ]

# Records
@app.get("/patients/{patient_uid}/records", dependencies=[Depends(require_api_key)], response_model=List[RecordOut])
def list_records(patient_uid: str, db: Session = Depends(get_db)):
    pat = db.query(Patient).filter(Patient.uid == patient_uid).first()
    if not pat:
        raise HTTPException(404, "Patient not found")
    recs = db.query(Record).filter(Record.patient_id == pat.id).order_by(Record.created_at.asc()).all()
    return [RecordOut(id=r.id, category=r.category, content=r.content, created_at=r.created_at) for r in recs]

@app.post("/patients/{patient_uid}/records", dependencies=[Depends(require_api_key)], response_model=RecordOut)
def add_record(patient_uid: str, rec: RecordIn, db: Session = Depends(get_db)):
    pat = db.query(Patient).filter(Patient.uid == patient_uid).first()
    if not pat:
        raise HTTPException(404, "Patient not found")
    category = rec.category or infer_category(rec.content)
    row = Record(patient_id=pat.id, category=category, content=rec.content)
    db.add(row)
    db.commit()
    db.refresh(row)
    return RecordOut(id=row.id, category=row.category, content=row.content, created_at=row.created_at)

# Jednoduchý import riadkov (text/JSON) do záznamov
@app.post("/import", dependencies=[Depends(require_api_key)])
async def import_file(patient_uid: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    pat = db.query(Patient).filter(Patient.uid == patient_uid).first()
    if not pat:
        raise HTTPException(404, "Patient not found")
    data = (await file.read()).decode("utf-8", errors="ignore").splitlines()
    n = 0
    for line in data:
        line = line.strip()
        if not line:
            continue
        cat = infer_category(line)
        db.add(Record(patient_id=pat.id, category=cat, content=line))
        n += 1
    db.commit()
    return {"imported": n}

# -----------------------------
# Mini dashboard (HTML)
# -----------------------------
INDEX_HTML = """
<!doctype html>
<html lang="sk">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>MedAI Dashboard 2.3 (DB)</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;background:#f6f8fb;margin:0}
.header{background:#134a9a;color:#fff;padding:14px 18px;display:flex;gap:12px;align-items:center}
.header input{padding:8px;border:none;border-radius:6px;width:260px}
.badge{background:#e9f6ff;color:#134a9a;border-radius:999px;padding:4px 10px;font-size:12px}
.wrap{padding:16px;max-width:980px;margin:0 auto}
.card{background:#fff;border-radius:12px;box-shadow:0 3px 14px rgba(0,0,0,.06);padding:16px;margin:12px 0}
.btn{background:#134a9a;color:#fff;border:none;border-radius:8px;padding:10px 14px;cursor:pointer}
.row{display:flex;gap:10px;flex-wrap:wrap}
.inp{width:100%;padding:10px;border:1px solid #dfe3ea;border-radius:8px}
.err{color:#c0392b}.ok{color:#16a085}
small{color:#666}
table{width:100%;border-collapse:collapse;margin-top:8px}
th,td{border-bottom:1px solid #eee;text-align:left;padding:8px;font-size:14px}
</style>
</head>
<body>
  <div class="header">
    <b>MedAI Dashboard 2.3 (DB)</b>
    <input id="apiKey" placeholder="API Key" value="__APIKEY__"/>
    <span id="status" class="badge">offline</span>
  </div>

  <div class="wrap">
    <div class="card">
      <h3>Pacient</h3>
      <div class="row">
        <input id="uid" class="inp" placeholder="UID (napr. P001)" style="max-width:200px">
        <input id="first" class="inp" placeholder="Meno" style="max-width:220px">
        <input id="last" class="inp" placeholder="Priezvisko" style="max-width:220px">
      </div>
      <div class="row" style="margin-top:8px">
        <button class="btn" onclick="createPatient()">Vytvoriť</button>
        <button class="btn" onclick="loadPatients()">Načítať pacientov</button>
        <button class="btn" onclick="loadRecords()">Načítať záznamy</button>
      </div>
      <div id="msg" style="margin-top:6px"></div>
      <div id="plist" style="margin-top:10px"></div>
    </div>

    <div class="card">
      <h3>Záznamy</h3>
      <textarea id="content" class="inp" rows="4" placeholder="Obsah (text alebo JSON)"></textarea>
      <div class="row" style="margin-top:8px">
        <button class="btn" onclick="saveRecord()">Uložiť</button>
      </div>
      <small>TIP: „CRP 120 mg/L“ → kategória LAB sa určí automaticky.</small>
      <div id="rlist" style="margin-top:10px"></div>
    </div>
  </div>

<script>
const BASE = location.origin;

function apikey(){ return document.getElementById('apiKey').value.trim(); }
function showStatus(ok){
  const el = document.getElementById('status');
  el.textContent = ok ? 'online' : 'offline';
  el.style.background = ok ? '#e8fff3' : '#ffecec';
  el.style.color = ok ? '#0f7a3a' : '#b10000';
}

async function ping(){
  try{
    const r = await fetch(BASE + '/health');
    showStatus(r.ok);
  }catch(e){ showStatus(false); }
}
setInterval(ping, 4000); ping();

function setMsg(text, good){
  const m = document.getElementById('msg');
  m.className = good ? 'ok' : 'err';
  m.textContent = text || '';
}

async function createPatient(){
  const uid = document.getElementById('uid').value.trim();
  const first = document.getElementById('first').value.trim();
  const last = document.getElementById('last').value.trim();
  if(!uid){ setMsg('Zadaj UID', false); return; }
  try{
    const r = await fetch(BASE + '/patients', {
      method:'POST',
      headers:{'Content-Type':'application/json','x-api-key':apikey()},
      body: JSON.stringify({patient_uid:uid, first_name:first || null, last_name:last || null})
    });
    const js = await r.json();
    if(!r.ok){ throw new Error(js.detail || 'Chyba'); }
    setMsg('Pacient OK ('+ js.patient_uid +')', true);
    loadPatients();
  }catch(e){ setMsg('Chyba: ' + e.message, false); }
}

async function loadPatients(){
  try{
    const r = await fetch(BASE + '/patients', {headers:{'x-api-key':apikey()}});
    const list = await r.json();
    if(!r.ok){ throw new Error(list.detail || 'Chyba'); }
    const html = '<ul>' + list.map(p =>
      `<li><a href="#" onclick="document.getElementById('uid').value='${p.patient_uid}';loadRecords();return false;">${p.patient_uid} — ${p.first_name||''} ${p.last_name||''}</a></li>`
    ).join('') + '</ul>';
    document.getElementById('plist').innerHTML = html;
    setMsg('', true);
  }catch(e){ setMsg('Chyba: ' + e.message, false); }
}

async function loadRecords(){
  const uid = document.getElementById('uid').value.trim();
  if(!uid){ setMsg('Vyber pacienta', false); return; }
  try{
    const r = await fetch(BASE + '/patients/' + encodeURIComponent(uid) + '/records', {headers:{'x-api-key':apikey()}});
    const list = await r.json();
    if(!r.ok){ throw new Error(list.detail || 'Chyba'); }
    const rows = list.map(x => `<tr><td>${new Date(x.created_at).toLocaleString()}</td><td><b>${x.category}</b></td><td>${x.content}</td></tr>`).join('');
    document.getElementById('rlist').innerHTML = `<table><thead><tr><th>Čas</th><th>Kategória</th><th>Obsah</th></tr></thead><tbody>${rows}</tbody></table>`;
    setMsg('', true);
  }catch(e){ setMsg('Chyba: ' + e.message, false); }
}

async function saveRecord(){
  const uid = document.getElementById('uid').value.trim();
  const content = document.getElementById('content').value.trim();
  if(!uid){ setMsg('Vyber pacienta', false); return; }
  if(!content){ setMsg('Zadaj obsah', false); return; }
  try{
    const r = await fetch(BASE + '/patients/' + encodeURIComponent(uid) + '/records', {
      method:'POST',
      headers:{'Content-Type':'application/json','x-api-key':apikey()},
      body: JSON.stringify({content: content})
    });
    const js = await r.json();
    if(!r.ok){ throw new Error(js.detail || 'Chyba'); }
    setMsg('Uložené ('+ js.category +')', true);
    document.getElementById('content').value = '';
    loadRecords();
  }catch(e){ setMsg('Chyba: ' + e.message, false); }
}
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(INDEX_HTML.replace("__APIKEY__", API_KEY))
