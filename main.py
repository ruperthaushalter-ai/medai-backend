# main.py
from __future__ import annotations
import os
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, Header, HTTPException, Depends, Query, Body, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, ForeignKey, func
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session

# -------------------------------------------------------------------
# Konfigurácia
# -------------------------------------------------------------------
API_KEY = os.getenv("API_KEY", "m3dAI_7YtqgY2WJr9vQdXz")

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("PGDATABASE_URL")
if not DATABASE_URL:
    # bezpečná lokálna fallback DB (napr. pri development-e)
    DATABASE_URL = "sqlite:///./medai.db"

# Railway/Heroku štýl: postgres:// -> postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# -------------------------------------------------------------------
# DB modely
# -------------------------------------------------------------------
class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True)
    patient_uid = Column(String(64), unique=True, index=True, nullable=False)
    first_name = Column(String(120))
    last_name = Column(String(120))
    created_at = Column(DateTime, server_default=func.now())

    records = relationship("Record", back_populates="patient", cascade="all, delete-orphan")


class Record(Base):
    __tablename__ = "records"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), index=True, nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(32))  # LAB, EKG, RTG, NOTE, USG, TXT…
    created_at = Column(DateTime, server_default=func.now())

    patient = relationship("Patient", back_populates="records")


Base.metadata.create_all(bind=engine)

# -------------------------------------------------------------------
# Schémy (Pydantic)
# -------------------------------------------------------------------
class PatientIn(BaseModel):
    patient_uid: str = Field(..., description="Externé UID, napr. P001")
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class PatientOut(BaseModel):
    id: int
    patient_uid: str
    first_name: Optional[str]
    last_name: Optional[str]

    class Config:
        from_attributes = True


class RecordIn(BaseModel):
    content: str = Field(..., description="Voľný text alebo JSON text")
    category: Optional[str] = Field(None, description="Ak nie je, auto-detekcia")


class RecordOut(BaseModel):
    id: int
    content: str
    category: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# -------------------------------------------------------------------
# Pomocné funkcie
# -------------------------------------------------------------------
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_api_key(
    x_api_key: Optional[str] = Header(None),
    api_key: Optional[str] = Query(None)
):
    """Akceptuje API kľúč buď z hlavičky `x-api-key`, alebo z query param `api_key`."""
    key = x_api_key or api_key
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


def guess_category(text: str) -> str:
    """Úplne jednoduchá heuristika – stačí na MVP."""
    t = text.lower()

    # laboratórne
    lab_markers = ["mg/l", "mmol/l", "μmol/l", "g/l", "crp", "k+", "na+", "hemoglobin", "glukóza"]
    if any(k in t for k in lab_markers):
        return "LAB"

    # EKG
    if "ekg" in t or "qrs" in t or "st elev" in t or "st deprim" in t:
        return "EKG"

    # RTG / zobrazovanie
    if "rtg" in t or "röntgen" in t or "rentgen" in t or "x-ray" in t:
        return "RTG"

    if "usg" in t or "sono" in t or "ultrazvuk" in t:
        return "USG"

    # inak poznámka
    return "NOTE"


# -------------------------------------------------------------------
# FastAPI app
# -------------------------------------------------------------------
app = FastAPI(title="MedAI Backend (safe)", version="2.2-stable")

# -------------------- Health --------------------
@app.get("/health")
def health():
    return {"status": "ok"}

# -------------------- Patients ------------------
@app.get("/patients", dependencies=[Depends(require_api_key)], response_model=List[PatientOut])
def list_patients(db: Session = Depends(get_db)):
    items = db.query(Patient).order_by(Patient.created_at.desc()).all()
    return items

@app.post("/patients", dependencies=[Depends(require_api_key)], response_model=PatientOut)
def create_patient(payload: PatientIn, db: Session = Depends(get_db)):
    existing = db.query(Patient).filter(Patient.patient_uid == payload.patient_uid).first()
    if existing:
        # idempotentne vrátime už existujúceho
        return existing
    p = Patient(
        patient_uid=payload.patient_uid.strip(),
        first_name=(payload.first_name or None),
        last_name=(payload.last_name or None),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p

# -------------------- Records -------------------
@app.get(
    "/patients/{patient_uid}/records",
    dependencies=[Depends(require_api_key)],
    response_model=List[RecordOut]
)
def list_records(patient_uid: str, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.patient_uid == patient_uid).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    recs = (
        db.query(Record)
        .filter(Record.patient_id == patient.id)
        .order_by(Record.created_at.asc(), Record.id.asc())
        .all()
    )
    return recs

@app.post(
    "/patients/{patient_uid}/records",
    dependencies=[Depends(require_api_key)],
    response_model=RecordOut
)
def add_record(
    patient_uid: str,
    payload: RecordIn = Body(...),
    db: Session = Depends(get_db)
):
    patient = db.query(Patient).filter(Patient.patient_uid == patient_uid).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    category = payload.category or guess_category(payload.content)
    rec = Record(patient_id=patient.id, content=payload.content, category=category)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


# -------------------------------------------------------------------
# Zabudované mini-UI (2.2 štýl) – query param API key
# -------------------------------------------------------------------
HTML = r"""
<!doctype html>
<html lang="sk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MedAI Dashboard 2.2</title>
<style>
  :root{--bg:#0e4c92;--btn:#134a9a;--ok:#16a085;--err:#c0392b;}
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;background:#f6f8fb;margin:0}
  .header{background:var(--bg);color:#fff;padding:14px 18px;display:flex;gap:12px;align-items:center}
  .header input{padding:8px 10px;border:none;border-radius:6px;width:260px}
  .badge{display:inline-block;background:#eef5ff;color:#134a9a;border-radius:999px;padding:4px 8px;font-size:12px}
  .wrap{padding:18px;max-width:980px;margin:0 auto}
  .card{background:#fff;border-radius:12px;box-shadow:0 3px 14px rgba(0,0,0,.06);padding:16px;margin:12px 0}
  .row{display:flex;gap:10px;flex-wrap:wrap}
  .inp{width:100%;padding:10px;border:1px solid #dfe3ea;border-radius:8px;margin:6px 0}
  .btn{background:var(--btn);color:#fff;border:none;border-radius:8px;padding:10px 14px;cursor:pointer}
  .btn.secondary{background:#6b7a99}
  .list{margin:8px 0 0 0;padding-left:20px}
  .err{color:var(--err)} .ok{color:var(--ok)}
  table{width:100%;border-collapse:collapse;margin-top:10px}
  th,td{border-bottom:1px solid #eee;text-align:left;padding:8px;font-size:14px}
  .pill{display:inline-block;padding:2px 8px;border-radius:999px;background:#eef5ff;color:#134a9a;font-size:12px}
</style>
</head>
<body>
  <div class="header">
    <b>MedAI Dashboard 2.2</b>
    <input id="apiKey" placeholder="API Key">
    <span id="status" class="badge">offline</span>
  </div>

  <div class="wrap">
    <div class="card">
      <h3>Pacient</h3>
      <div class="row">
        <input id="uid" class="inp" placeholder="UID (napr. P001)" style="max-width:220px">
        <input id="first" class="inp" placeholder="Meno" style="max-width:220px">
        <input id="last" class="inp" placeholder="Priezvisko" style="max-width:220px">
      </div>
      <div class="row">
        <button class="btn" onclick="createPatient()">Vytvoriť</button>
        <button class="btn" onclick="loadPatients()">Načítať pacientov</button>
        <button class="btn" onclick="loadRecords()">Načítať záznamy</button>
      </div>
      <div id="patientsBox" style="margin-top:10px"></div>
      <div id="msg" class="err" style="margin-top:8px"></div>
    </div>

    <div class="card">
      <h3>Záznamy</h3>
      <textarea id="content" class="inp" rows="4" placeholder="Obsah (text alebo JSON)"></textarea>
      <div class="row">
        <button class="btn" onclick="saveRecord()">Uložiť</button>
      </div>
      <div id="recordsBox" style="margin-top:10px"></div>
      <div style="margin-top:8px;color:#666">TIP: „CRP 120 mg/L“ → kategória LAB sa určí automaticky.</div>
    </div>
  </div>

<script>
const BASE = "";
const $ = (id)=>document.getElementById(id);
const apikey = ()=> $('apiKey').value.trim();

async function ping() {
  try {
    const r = await fetch(BASE + '/health');
    const ok = r.ok;
    $('status').textContent = ok ? 'online' : 'offline';
    $('status').style.background = ok ? '#eafff3' : '#ffeaea';
    $('status').style.color = ok ? '#0a7a4b' : '#a00';
  } catch(e){
    $('status').textContent = 'offline';
    $('status').style.background = '#ffeaea';
    $('status').style.color = '#a00';
  }
}
ping();

function setMsg(t){ $('msg').textContent = t || ''; }

function patientRow(p) {
  const name = [p.first_name || '', p.last_name || ''].join(' ').trim();
  return `<li><a href="#" onclick="pick('${p.patient_uid}');return false;">${p.patient_uid}</a> — ${name || '—'}</li>`;
}
function pick(uid){
  $('uid').value = uid;
  loadRecords();
}

async function loadPatients(){
  setMsg('');
  try{
    const r = await fetch(BASE + '/patients?api_key=' + encodeURIComponent(apikey()));
    if(!r.ok){ setMsg('Chyba: ' + r.statusText); return; }
    const data = await r.json();
    if(!Array.isArray(data)){ setMsg('Chyba: neočakávané dáta'); return; }
    const html = '<ul class="list">' + data.map(patientRow).join('') + '</ul>';
    $('patientsBox').innerHTML = html || 'Žiadni pacienti.';
  }catch(e){ setMsg('Chyba: ' + e.message); }
}

async function createPatient(){
  setMsg('');
  const uid = $('uid').value.trim();
  if(!uid){ setMsg('Zadaj UID.'); return; }
  const first = $('first').value.trim();
  const last  = $('last').value.trim();

  try{
    const r = await fetch(BASE + '/patients?api_key=' + encodeURIComponent(apikey()), {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({patient_uid:uid, first_name:first || null, last_name:last || null})
    });
    if(!r.ok){ setMsg('Chyba: ' + r.status + ' ' + r.statusText); return; }
    await r.json();
    await loadPatients();
  }catch(e){ setMsg('Chyba: ' + e.message); }
}

function recordRow(r){
  const dt = new Date(r.created_at);
  const when = dt.toLocaleString();
  const cat = r.category ? `<span class="pill">${r.category}</span>` : '';
  return `<tr><td>${when}</td><td>${cat}</td><td>${escapeHtml(r.content)}</td></tr>`;
}
function escapeHtml(s){ return s.replace(/[&<>"']/g,(m)=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[m])); }

async function loadRecords(){
  setMsg('');
  $('recordsBox').innerHTML = '';
  const uid = $('uid').value.trim();
  if(!uid){ setMsg('Vyber pacienta.'); return; }
  try{
    const r = await fetch(
      BASE + '/patients/' + encodeURIComponent(uid) + '/records?api_key=' + encodeURIComponent(apikey())
    );
    if(!r.ok){ setMsg('Chyba: ' + r.status + ' ' + r.statusText); return; }
    const data = await r.json();
    const rows = data.map(recordRow).join('');
    $('recordsBox').innerHTML = rows
      ? `<table><thead><tr><th>Čas</th><th>Kategória</th><th>Obsah</th></tr></thead><tbody>${rows}</tbody></table>`
      : 'Žiadne záznamy.';
  }catch(e){ setMsg('Chyba: ' + e.message); }
}

async function saveRecord(){
  setMsg('');
  const uid = $('uid').value.trim();
  if(!uid){ setMsg('Vyber pacienta.'); return; }
  const content = $('content').value.trim();
  if(!content){ setMsg('Prázdny obsah.'); return; }
  try{
    const r = await fetch(
      BASE + '/patients/' + encodeURIComponent(uid) + '/records?api_key=' + encodeURIComponent(apikey()),
      { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({content}) }
    );
    if(!r.ok){ setMsg('Chyba: ' + r.status + ' ' + r.statusText); return; }
    $('content').value = '';
    await loadRecords();
  }catch(e){ setMsg('Chyba: ' + e.message); }
}
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def ui():
    return HTML
