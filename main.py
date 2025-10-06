# main.py
import os
import logging
from typing import Optional, List
from datetime import datetime

from fastapi import FastAPI, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, select, text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

# ------------------------------------------------------------------------------
# Konfigurácia & logovanie
# ------------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

API_KEY_ENV = os.getenv("API_KEY", "m3dAI_7YtqgY2WJr9vQdXz")  # default len pre dev
DB_URL = os.getenv("DATABASE_URL", "")

# Railway Postgres často vyžaduje SSL. Doplň, ak chýba.
if DB_URL.startswith("postgresql://") and "sslmode=" not in DB_URL:
    joiner = "&" if "?" in DB_URL else "?"
    DB_URL = f"{DB_URL}{joiner}sslmode=require"

if not DB_URL:
    logging.warning("DATABASE_URL nie je nastavené – app pôjde, ale DB volania spadnú.")

engine = create_engine(DB_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

app = FastAPI(title="MedAI Backend 2.2 (DB)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# ------------------------------------------------------------------------------
# DB modely
# ------------------------------------------------------------------------------
class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True)
    uid = Column(String(50), unique=True, index=True, nullable=False)
    first_name = Column(String(100), default="")
    last_name = Column(String(100), default="")
    records = relationship("Record", back_populates="patient", cascade="all,delete")

class Record(Base):
    __tablename__ = "records"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    category = Column(String(30), default="NOTE")  # LAB/EKG/RTG/NOTE
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    patient = relationship("Patient", back_populates="records")

# ------------------------------------------------------------------------------
# Schémy (Pydantic)
# ------------------------------------------------------------------------------
class PatientIn(BaseModel):
    uid: str = Field(..., examples=["P001"])
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""

class RecordIn(BaseModel):
    content: str = Field(..., description="Obsah textu alebo JSON")
    category: Optional[str] = None  # ak None, skúsime heuristiku

# ------------------------------------------------------------------------------
# API key ochrana (header aj query)
# ------------------------------------------------------------------------------
def require_api_key(
    api_key_header: Optional[str] = Header(default=None, alias="x-api-key"),
    api_key_query: Optional[str] = Query(default=None, alias="api_key"),
):
    key = api_key_header or api_key_query
    if not key or key != API_KEY_ENV:
        raise HTTPException(status_code=401, detail="unauthorized")
    return True

# ------------------------------------------------------------------------------
# Pomocné – heuristika kategórie
# ------------------------------------------------------------------------------
def detect_category(text_value: str) -> str:
    t = text_value.lower()
    if any(k in t for k in ["crp", "hb", "hemoglobin", "leu", "k+", "na+", "mg/l", "mmol/l"]):
        return "LAB"
    if any(k in t for k in ["ekg", "sinus", "tachykard", "bradykard", "qrs", "st "]):
        return "EKG"
    if any(k in t for k in ["rtg", "rentgen", "x-ray", "skiagraf"]):
        return "RTG"
    return "NOTE"

# ------------------------------------------------------------------------------
# Životný cyklus & diagnostika
# ------------------------------------------------------------------------------
@app.on_event("startup")
def on_startup():
    try:
        Base.metadata.create_all(bind=engine)
        logging.info("DB schema ready")
    except Exception as e:
        logging.exception("DB init failed: %s", e)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/diag/pingdb", dependencies=[Depends(require_api_key)])
def ping_db():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"db": "ok"}
    except Exception as e:
        logging.exception("DB ping failed")
        raise HTTPException(status_code=500, detail=f"db_error: {e}")

# ------------------------------------------------------------------------------
# Pacienti
# ------------------------------------------------------------------------------
@app.get("/patients", dependencies=[Depends(require_api_key)])
def list_patients():
    try:
        with SessionLocal() as db:
            pts = db.execute(select(Patient).order_by(Patient.uid.asc())).scalars().all()
            return [{"uid": p.uid, "first_name": p.first_name, "last_name": p.last_name} for p in pts]
    except Exception as e:
        logging.exception("GET /patients failed")
        raise HTTPException(status_code=500, detail=f"server_error: {e}")

@app.post("/patients", dependencies=[Depends(require_api_key)])
def create_patient(p: PatientIn):
    try:
        with SessionLocal() as db:
            exists = db.execute(select(Patient).where(Patient.uid == p.uid)).scalar_one_or_none()
            if exists:
                raise HTTPException(status_code=409, detail="patient_exists")
            patient = Patient(uid=p.uid.strip(), first_name=p.first_name.strip(), last_name=p.last_name.strip())
            db.add(patient)
            db.commit()
            return {"ok": True, "uid": patient.uid}
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("POST /patients failed")
        raise HTTPException(status_code=500, detail=f"server_error: {e}")

# ------------------------------------------------------------------------------
# Záznamy
# ------------------------------------------------------------------------------
@app.get("/patients/{uid}/records", dependencies=[Depends(require_api_key)])
def list_records(uid: str):
    try:
        with SessionLocal() as db:
            patient = db.execute(select(Patient).where(Patient.uid == uid)).scalar_one_or_none()
            if not patient:
                raise HTTPException(status_code=404, detail="patient_not_found")
            recs = db.execute(
                select(Record).where(Record.patient_id == patient.id).order_by(Record.created_at.desc())
            ).scalars().all()
            return [
                {
                    "id": r.id,
                    "category": r.category,
                    "content": r.content,
                    "created_at": r.created_at.isoformat() + "Z",
                }
                for r in recs
            ]
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("GET /patients/{uid}/records failed")
        raise HTTPException(status_code=500, detail=f"server_error: {e}")

@app.post("/patients/{uid}/records", dependencies=[Depends(require_api_key)])
def add_record(uid: str, body: RecordIn):
    try:
        with SessionLocal() as db:
            patient = db.execute(select(Patient).where(Patient.uid == uid)).scalar_one_or_none()
            if not patient:
                raise HTTPException(status_code=404, detail="patient_not_found")
            category = (body.category or "").strip().upper() or detect_category(body.content or "")
            rec = Record(patient_id=patient.id, category=category, content=body.content.strip())
            db.add(rec)
            db.commit()
            return {"ok": True, "id": rec.id, "category": rec.category}
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("POST /patients/{uid}/records failed")
        raise HTTPException(status_code=500, detail=f"server_error: {e}")

# ------------------------------------------------------------------------------
# Web UI (Dashboard 2.2)
# ------------------------------------------------------------------------------
INDEX_HTML = """
<!doctype html>
<html lang="sk">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>MedAI Dashboard 2.2 (DB)</title>
  <style>
    body{font-family:system-ui,Segoe UI,Roboto,Arial;background:#f6f8fb;margin:0}
    .header{background:#134a9a;color:#fff;padding:14px 18px;display:flex;gap:12px;align-items:center}
    .header h1{font-size:20px;margin:0}
    .badge{background:#19c37d;color:#083d31;padding:4px 10px;border-radius:999px;font-weight:600}
    .wrap{padding:16px;max-width:960px;margin:0 auto}
    .card{background:#fff;border-radius:12px;box-shadow:0 3px 14px rgba(0,0,0,.06);padding:16px;margin:12px 0}
    .row{display:flex;gap:10px;flex-wrap:wrap}
    .inp{width:100%;padding:10px;border:1px solid #dce4f0;border-radius:8px}
    .btn{background:#134a9a;color:#fff;border:none;border-radius:8px;padding:10px 14px;cursor:pointer}
    .err{color:#c0392b;margin-top:8px}
    .ok{color:#16a085;margin-top:8px}
    ul{margin-top:10px}
    li{cursor:pointer}
    pre{white-space:pre-wrap}
  </style>
</head>
<body>
  <div class="header">
    <h1>MedAI Dashboard 2.2</h1>
    <input id="apiKey" class="inp" placeholder="API Key" style="max-width:260px"/>
    <span id="online" class="badge">online</span>
  </div>

  <div class="wrap">

    <div class="card">
      <h2>Pacienti</h2>
      <input id="uid" class="inp" placeholder="P001"/>
      <div class="row">
        <input id="first" class="inp" placeholder="Meno" style="max-width:220px"/>
        <input id="last"  class="inp" placeholder="Priezvisko" style="max-width:220px"/>
      </div>
      <div class="row">
        <button class="btn" onclick="createPatient()">Vytvoriť</button>
        <button class="btn" onclick="loadPatients()">Načítať pacientov</button>
        <button class="btn" onclick="loadRecords()">Načítať záznamy</button>
      </div>
      <div id="pError" class="err"></div>
      <ul id="plist"></ul>
    </div>

    <div class="card">
      <h2>Záznamy</h2>
      <textarea id="content" class="inp" rows="4" placeholder='Obsah (text alebo JSON)'></textarea>
      <div class="row">
        <button class="btn" onclick="saveRecord()">Uložiť</button>
      </div>
      <div id="rError" class="err"></div>
      <div id="rList"></div>
      <p style="color:#666">TIP: „CRP 120 mg/L“ → kategória <b>LAB</b> sa určí automaticky.</p>
    </div>

  </div>

<script>
const base = location.origin;
const $ = (id) => document.getElementById(id);
const key = () => ($("apiKey").value || "").trim();

function showErr(id, msg) { $(id).textContent = msg || ""; }
function clearErrs() { showErr("pError",""); showErr("rError",""); }

async function api(path, opts={}) {
  const k = key();
  const headers = Object.assign({"Content-Type":"application/json"}, k ? {"x-api-key": k} : {});
  const res = await fetch(base + path, Object.assign({headers}, opts));
  if (!res.ok) {
    let detail = "";
    try { const j = await res.json(); detail = j.detail || res.statusText; } catch(e) { detail = res.statusText; }
    throw new Error(detail);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

async function loadPatients() {
  clearErrs();
  try {
    const data = await api("/patients");
    const ul = $("plist"); ul.innerHTML = "";
    data.forEach(p => {
      const li = document.createElement("li");
      li.textContent = `${p.uid} — ${p.first_name} ${p.last_name}`.trim();
      li.onclick = () => { $("uid").value = p.uid; loadRecords(); };
      ul.appendChild(li);
    });
  } catch(e) { showErr("pError", e.message); }
}

async function createPatient() {
  clearErrs();
  const uid = $("uid").value.trim();
  const first = $("first").value.trim();
  const last  = $("last").value.trim();
  if (!uid) { showErr("pError","Zadaj UID (napr. P001)"); return; }
  try {
    await api("/patients", { method:"POST", body: JSON.stringify({uid, first_name:first, last_name:last}) });
    await loadPatients();
  } catch(e) { showErr("pError", e.message); }
}

async function loadRecords() {
  clearErrs();
  const uid = $("uid").value.trim();
  if (!uid) { showErr("pError","Zadaj UID pacienta"); return; }
  try {
    const recs = await api(`/patients/${encodeURIComponent(uid)}/records`);
    const box = $("rList");
    box.innerHTML = recs.map(r => 
      `<div style="border:1px solid #eee;border-radius:8px;padding:8px;margin:6px 0">
        <div><b>${r.category}</b> • <small>${r.created_at}</small></div>
        <pre>${(r.content || "").replace(/[<>&]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))}</pre>
      </div>`).join("");
  } catch(e) { showErr("pError", e.message); }
}

async function saveRecord() {
  clearErrs();
  const uid = $("uid").value.trim();
  const content = $("content").value.trim();
  if (!uid) { showErr("rError","Zadaj UID pacienta"); return; }
  if (!content) { showErr("rError","Zadaj obsah"); return; }
  try {
    await api(`/patients/${encodeURIComponent(uid)}/records`, { method:"POST", body: JSON.stringify({content}) });
    $("content").value = "";
    await loadRecords();
  } catch(e) { showErr("rError", e.message); }
}
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(INDEX_HTML)
