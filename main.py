# main.py
import os
from datetime import datetime
from enum import Enum

from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship

# -----------------------------------------------------------------------------
# Konfigurácia DB
# -----------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("RAILWAY_DATABASE_URL")
if not DATABASE_URL:
    # bezpečný fallback pre lokálne testovanie (na Railway normálne príde Postgres URL)
    DATABASE_URL = "sqlite:///./local.db"

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# -----------------------------------------------------------------------------
# Modely
# -----------------------------------------------------------------------------
class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True)
    uid = Column(String(50), unique=True, index=True, nullable=False)
    first_name = Column(String(120), nullable=True)
    last_name = Column(String(120), nullable=True)
    records = relationship("Record", back_populates="patient", cascade="all,delete")

class Record(Base):
    __tablename__ = "records"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), index=True, nullable=False)
    category = Column(String(16), index=True, nullable=False, default="NOTE")
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, index=True, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="records")

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -----------------------------------------------------------------------------
# API key ochrana (hlavička X-API-Key AJ query ?api_key=)
# -----------------------------------------------------------------------------
EXPECTED_API_KEY = os.getenv("API_KEY", "m3dAI_7YtqgY2WJr9vQdXz")

def _is_valid_key(k: str) -> bool:
    return isinstance(k, str) and k.startswith("m3dAI_") and len(k) >= 12 and k == EXPECTED_API_KEY

async def require_api_key(
    x_api_key: str | None = Header(default=None),
    api_key: str | None = Query(default=None),
):
    key = x_api_key or api_key
    if not _is_valid_key(key or ""):
        raise HTTPException(status_code=401, detail="Unauthorized: invalid API key")

# -----------------------------------------------------------------------------
# Heuristické rozpoznanie kategórie
# -----------------------------------------------------------------------------
class Category(str, Enum):
    LAB = "LAB"
    EKG = "EKG"
    RTG = "RTG"
    USG = "USG"
    NOTE = "NOTE"

def guess_category(text: str) -> str:
    t = (text or "").lower()
    lab_markers = ["mg/l", "mmol/l", "μmol/l", "umol/l", "crp", "k+", "na+", "hemoglobin", "glukóz", "glyc", "creat"]
    if any(m in t for m in lab_markers): return "LAB"
    if "ekg" in t or "qrs" in t or "st elev" in t or "st depr" in t or "tachykard" in t: return "EKG"
    if "rtg" in t or "rentgen" in t or "röntgen" in t or "x-ray" in t: return "RTG"
    if "usg" in t or "sono" in t or "ultrazvuk" in t: return "USG"
    return "NOTE"

# -----------------------------------------------------------------------------
# Schemy (Pydantic v2)
# -----------------------------------------------------------------------------
class PatientIn(BaseModel):
    uid: str
    first_name: str | None = None
    last_name: str | None = None

class RecordIn(BaseModel):
    content: str
    category: Category | None = None
    ts: datetime | None = None

# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(title="MedAI Backend", version="2.2")

@app.get("/health")
def health():
    return {"status": "ok"}

# ----------------------- Pacienti -----------------------
@app.post("/patients", dependencies=[Depends(require_api_key)])
def create_patient(body: PatientIn, db: Session = Depends(get_db)):
    exists = db.query(Patient).filter_by(uid=body.uid).first()
    if exists:
        return {"id": exists.id, "uid": exists.uid}
    p = Patient(uid=body.uid, first_name=body.first_name, last_name=body.last_name)
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"id": p.id, "uid": p.uid}

@app.get("/patients", dependencies=[Depends(require_api_key)])
def list_patients(db: Session = Depends(get_db)):
    rows = db.query(Patient).order_by(Patient.uid.asc()).all()
    return [{"uid": p.uid, "first_name": p.first_name, "last_name": p.last_name} for p in rows]

# ----------------------- Záznamy ------------------------
@app.get("/patients/{patient_uid}/records", dependencies=[Depends(require_api_key)])
def list_records(patient_uid: str, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter_by(uid=patient_uid).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    recs = (
        db.query(Record)
        .filter_by(patient_id=patient.id)
        .order_by(Record.created_at.asc())
        .all()
    )
    return [
        {"id": r.id, "category": r.category, "content": r.content, "created_at": r.created_at.isoformat()}
        for r in recs
    ]

@app.post("/patients/{patient_uid}/records", dependencies=[Depends(require_api_key)])
def add_record(patient_uid: str, body: RecordIn, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter_by(uid=patient_uid).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    cat_str = (body.category.value if isinstance(body.category, Category) else body.category) or guess_category(body.content)
    try:
        cat = Category(cat_str).value
    except Exception:
        cat = "NOTE"

    rec = Record(
        patient_id=patient.id,
        content=body.content,
        category=cat,
        created_at=body.ts or datetime.utcnow(),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {"id": rec.id, "category": rec.category, "created_at": rec.created_at.isoformat()}

# -----------------------------------------------------------------------------
# Jednoduchý dashboard (verzia 2.2 – zoznam pacientov klikateľný + záznamy)
# -----------------------------------------------------------------------------
DASHBOARD_HTML = f"""
<!doctype html>
<html lang="sk">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>MedAI Dashboard 2.2</title>
<style>
  body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;background:#f6f8fb;margin:0}}
  .header{{background:#134a9a;color:#fff;padding:14px 18px;display:flex;gap:12px;align-items:center}}
  .header input{{padding:8px;border:none;border-radius:6px;width:260px}}
  .wrap{{padding:18px;max-width:960px;margin:0 auto}}
  .card{{background:#fff;border-radius:12px;box-shadow:0 3px 14px rgba(0,0,0,.06);padding:16px;margin:12px 0}}
  .btn{{background:#134a9a;color:#fff;border:none;border-radius:8px;padding:10px 14px;cursor:pointer}}
  .row{{display:flex;gap:10px;flex-wrap:wrap}}
  .inp{{width:100%;padding:10px;border:1px solid #dfe4ea;border-radius:8px;margin:6px 0}}
  .list li{{padding:6px 8px;border-bottom:1px solid #eee;cursor:pointer}}
  .badge{{display:inline-block;background:#eef5ff;color:#134a9a;border-radius:999px;padding:4px 8px;font-size:12px}}
  .ok{{color:#16a085}} .err{{color:#c0392b}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
  @media(max-width:800px){{.grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
  <div class="header">
    <b>MedAI Dashboard 2.2</b>
    <input id="apiKey" placeholder="API Key" />
    <span id="status" class="badge">offline</span>
  </div>
  <div class="wrap">
    <div class="grid">
      <div class="card">
        <h3>Pacienti</h3>
        <div class="row">
          <input id="uid" class="inp" placeholder="UID (napr. P001)" />
          <input id="first" class="inp" placeholder="Meno" />
          <input id="last" class="inp" placeholder="Priezvisko" />
        </div>
        <div class="row">
          <button class="btn" onclick="createPatient()">Vytvoriť</button>
          <button class="btn" onclick="loadPatients()">Načítať pacientov</button>
          <button class="btn" onclick="loadRecords()">Načítať záznamy</button>
        </div>
        <div id="msg" style="margin-top:8px"></div>
        <ul id="patients" class="list"></ul>
      </div>

      <div class="card">
        <h3>Záznamy</h3>
        <textarea id="content" class="inp" rows="6" placeholder="Obsah (text alebo JSON)"></textarea>
        <button class="btn" onclick="saveRecord()">Uložiť</button>
        <div id="recMsg" style="margin-top:8px"></div>
        <ul id="records" class="list"></ul>
        <div style="margin-top:8px;color:#666">TIP: „CRP 120 mg/L“ → kategória LAB sa určí automaticky.</div>
      </div>
    </div>
  </div>

<script>
const base = location.origin;

// získa API key z inputu
function getApiKey() {{ return document.getElementById('apiKey').value.trim(); }}

function setStatus(ok) {{
  const s = document.getElementById('status');
  if(ok) {{ s.textContent='online'; s.classList.remove('err'); s.classList.add('ok'); }}
  else    {{ s.textContent='offline'; s.classList.remove('ok'); s.classList.add('err'); }}
}}

async function ping() {{
  try {{
    const r = await fetch(base + '/health');
    setStatus(r.ok);
  }} catch(e) {{ setStatus(false); }}
}}
ping();

function show(elId, html, ok=true) {{
  const el = document.getElementById(elId);
  el.innerHTML = html || '';
  el.style.color = ok ? '#16a085' : '#c0392b';
}}

async function createPatient() {{
  const api = getApiKey();
  const uid = document.getElementById('uid').value.trim();
  const first = document.getElementById('first').value.trim();
  const last = document.getElementById('last').value.trim();
  if(!uid) return show('msg','Zadaj UID', false);
  try {{
    const r = await fetch(base+'/patients?api_key='+encodeURIComponent(api), {{
      method:'POST',
      headers: {{ 'Content-Type':'application/json' }},
      body: JSON.stringify({{ uid, first_name:first || null, last_name:last || null }})
    }});
    const d = await r.json();
    if(!r.ok) throw new Error(d.detail || 'Chyba');
    show('msg','Pacient uložený: '+d.uid,true);
    loadPatients();
  }} catch(e) {{
    show('msg', e.message, false);
  }}
}}

async function loadPatients() {{
  const api = getApiKey();
  try {{
    const r = await fetch(base+'/patients?api_key='+encodeURIComponent(api));
    const d = await r.json();
    if(!r.ok) throw new Error(d.detail || 'Chyba');
    const ul = document.getElementById('patients');
    ul.innerHTML = '';
    d.forEach(p => {{
      const li = document.createElement('li');
      li.textContent = `${{p.uid}} — ${{p.first_name||''}} ${{p.last_name||''}}`.trim();
      li.onclick = () => {{
        document.getElementById('uid').value = p.uid;
        loadRecords();
      }};
      ul.appendChild(li);
    }});
    show('msg','Načítaní pacienti: '+d.length,true);
  }} catch(e) {{
    show('msg', e.message, false);
  }}
}}

async function loadRecords() {{
  const api = getApiKey();
  const uid = document.getElementById('uid').value.trim();
  if(!uid) return show('msg','Najprv zvoľ/zadaj UID', false);
  try {{
    const r = await fetch(base+`/patients/${{encodeURIComponent(uid)}}/records?api_key=${{encodeURIComponent(api)}}`);
    const d = await r.json();
    if(!r.ok) throw new Error(d.detail || 'Chyba');
    const ul = document.getElementById('records');
    ul.innerHTML = '';
    d.forEach(rec => {{
      const li = document.createElement('li');
      li.textContent = `[${{rec.category}}] ${{rec.created_at}} — ${{rec.content}}`;
      ul.appendChild(li);
    }});
    show('recMsg','Záznamov: '+d.length,true);
  }} catch(e) {{
    show('recMsg', e.message, false);
  }}
}}

async function saveRecord() {{
  const api = getApiKey();
  const uid = document.getElementById('uid').value.trim();
  const content = document.getElementById('content').value.trim();
  if(!uid) return show('recMsg','Najprv vyber pacienta', false);
  if(!content) return show('recMsg','Prázdny obsah', false);
  try {{
    const r = await fetch(base+`/patients/${{encodeURIComponent(uid)}}/records?api_key=${{encodeURIComponent(api)}}`, {{
      method:'POST',
      headers: {{ 'Content-Type':'application/json' }},
      body: JSON.stringify({{ content }})
    }});
    const d = await r.json();
    if(!r.ok) throw new Error(d.detail || 'Chyba');
    show('recMsg','Uložené ['+d.category+']', true);
    document.getElementById('content').value='';
    loadRecords();
  }} catch(e) {{
    show('recMsg', e.message, false);
  }}
}}
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(content=DASHBOARD_HTML)
