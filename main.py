import os
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Header, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, Session

# ---------- KONFIG ----------
API_KEY = os.getenv("API_KEY", "m3dAI_7YtgqY2WJr9vQdXz")
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Chýba DATABASE_URL (Railway → Variables).")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

app = FastAPI(title="MedAI 2.3 (DB)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def require_api_key(x_api_key: str = Header(default=None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

# ---------- DB MODELY ----------
class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True)
    patient_uid = Column(String(64), unique=True, index=True, nullable=False)
    first_name = Column(String(120))
    last_name = Column(String(120))
    gender = Column(String(8), default="U")
    created_at = Column(DateTime, default=datetime.utcnow)
    records = relationship("Record", back_populates="patient", cascade="all, delete-orphan")

class Record(Base):
    __tablename__ = "records"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), index=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    category = Column(String(32), default="NOTE")
    content = Column(Text, nullable=False)
    patient = relationship("Patient", back_populates="records")

Base.metadata.create_all(bind=engine)

# ---------- Pydantic vstupy ----------
class PatientIn(BaseModel):
    patient_uid: str
    first_name: str
    last_name: str
    gender: Optional[str] = "U"

class RecordIn(BaseModel):
    timestamp: Optional[str] = None
    category: Optional[str] = None
    content: str

# ---------- Heuristika kategórií ----------
def detect_category(text: str) -> str:
    t = (text or "").lower()
    if any(x in t for x in ["crp", "hb", "leu", "mg/l", "mmol", "gluk"]): return "LAB"
    if any(x in t for x in ["ekg", "fibril", "tachy", "brady"]): return "EKG"
    if any(x in t for x in ["rtg", "rentgen", "infiltr", "pneumon"]): return "RTG"
    if any(x in t for x in ["podan", "lieč", "infuz", "antibio", "ceftriax", "amoxicil"]): return "THERAPY"
    if any(x in t for x in ["tlak", "puls", "dych", "teplota"]): return "VITALS"
    return "NOTE"

# ---------- DB session helper ----------
def get_db() -> Session:
    db = SessionLocal()
    try: yield db
    finally: db.close()

# ---------- API ----------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/patients", dependencies=[Depends(require_api_key)])
def create_patient(body: PatientIn, db: Session = Depends(get_db)):
    uid = body.patient_uid.strip()
    exists = db.query(Patient).filter(Patient.patient_uid == uid).first()
    if not exists:
        p = Patient(
            patient_uid=uid,
            first_name=body.first_name.strip(),
            last_name=body.last_name.strip(),
            gender=(body.gender or "U").upper()
        )
        db.add(p); db.commit(); db.refresh(p)
    return {"status": "ok", "patient_uid": uid}

@app.get("/patients", dependencies=[Depends(require_api_key)])
def list_patients(db: Session = Depends(get_db)):
    pts = db.query(Patient).order_by(Patient.created_at.desc()).all()
    return [{"patient_uid": p.patient_uid, "first_name": p.first_name, "last_name": p.last_name} for p in pts]

@app.get("/patients/{uid}/records", dependencies=[Depends(require_api_key)])
def list_records(uid: str, db: Session = Depends(get_db)):
    p = db.query(Patient).filter(Patient.patient_uid == uid).first()
    if not p: raise HTTPException(404, "Patient not found")
    recs = (db.query(Record)
            .filter(Record.patient_id == p.id)
            .order_by(Record.timestamp.asc(), Record.id.asc())
            .all())
    return [{"timestamp": r.timestamp.isoformat(), "category": r.category, "content": r.content} for r in recs]

@app.post("/patients/{uid}/records", dependencies=[Depends(require_api_key)])
def add_record(uid: str, body: RecordIn, db: Session = Depends(get_db)):
    p = db.query(Patient).filter(Patient.patient_uid == uid).first()
    if not p: raise HTTPException(404, "Patient not found")
    ts = datetime.fromisoformat(body.timestamp) if body.timestamp else datetime.utcnow()
    cat = body.category or detect_category(body.content)
    r = Record(patient_id=p.id, timestamp=ts, category=cat, content=body.content.strip())
    db.add(r); db.commit(); db.refresh(r)
    return {"status": "ok", "saved": {"timestamp": r.timestamp.isoformat(), "category": r.category, "content": r.content}}

# Import textu alebo súboru (vyžaduje python-multipart v requirements.txt)
@app.post("/import", dependencies=[Depends(require_api_key)])
async def import_data(
    patient_uid: str = Form(...),
    text: str = Form(None),
    file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    p = db.query(Patient).filter(Patient.patient_uid == patient_uid).first()
    if not p: raise HTTPException(404, "Patient not found")
    content = ""
    if file:
        content = (await file.read()).decode("utf-8", errors="ignore")
    else:
        content = text or ""
    if not content.strip(): raise HTTPException(400, "Empty import content")
    cat = detect_category(content)
    r = Record(patient_id=p.id, timestamp=datetime.utcnow(), category=cat, content=content.strip())
    db.add(r); db.commit(); db.refresh(r)
    return {"status": "imported", "patient_uid": patient_uid, "category": cat}

# ---------- UI (vložený HTML+JS) ----------
HTML = r"""
<!doctype html><html lang="sk"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MedAI Dashboard 2.3 (DB)</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;background:#f6f8fb;margin:0}
.header{background:#134a9a;color:#fff;padding:14px 18px;display:flex;gap:12px;align-items:center}
.header input{padding:8px;border:none;border-radius:6px;width:260px}
.wrap{padding:18px;max-width:900px;margin:0 auto}
.card{background:#fff;border-radius:12px;box-shadow:0 3px 14px rgba(0,0,0,.06);padding:16px;margin:12px 0}
.btn{background:#134a9a;color:#fff;border:none;border-radius:8px;padding:10px 14px;cursor:pointer}
.inp{width:100%;padding:10px;border:1px solid #dcdfea;border-radius:8px;margin:6px 0}
.row{display:flex;gap:10px;flex-wrap:wrap}
.badge{display:inline-block;background:#eef3ff;color:#134a9a;border-radius:999px;padding:4px 10px;font-size:12px}
.err{color:#c0392b}.ok{color:#16a085}
table{width:100%;border-collapse:collapse;margin-top:10px}
th,td{border-bottom:1px solid #eee;text-align:left;padding:8px;font-size:14px}
small{color:#666}
</style>
</head><body>
<div class="header">
  <b>MedAI Dashboard 2.3 (DB)</b>
  <input id="apiKey" placeholder="API Key">
  <span id="status" class="badge">offline</span>
</div>
<div class="wrap">

  <div class="card">
    <h3>Pacient</h3>
    <div class="row">
      <input id="uid" class="inp" placeholder="UID (napr. P001)" style="max-width:180px">
      <input id="first" class="inp" placeholder="Meno" style="max-width:220px">
      <input id="last" class="inp" placeholder="Priezvisko" style="max-width:220px">
    </div>
    <div class="row">
      <button class="btn" onclick="createPatient()">Vytvoriť</button>
      <button class="btn" onclick="loadPatients()">Načítať pacientov</button>
      <button class="btn" onclick="loadRecords()">Načítať záznamy</button>
      <span id="msg" style="margin-left:8px"></span>
    </div>
    <div id="plist"></div>
  </div>

  <div class="card">
    <h3>Záznamy</h3>
    <textarea id="content" class="inp" rows="4" placeholder="Obsah (text alebo JSON)"></textarea>
    <div class="row">
      <button class="btn" onclick="saveRecord()">Uložiť</button>
      <small>TIP: „CRP 120 mg/L“ → kategória LAB sa určí automaticky.</small>
    </div>
    <div id="list"></div>
  </div>

  <div class="card">
    <h3>Importovať dáta</h3>
    <input id="imp_uid" class="inp" placeholder="UID pacienta (napr. P001)">
    <textarea id="imp_text" class="inp" rows="4" placeholder="Sem vlož text (alebo použi súbor)."></textarea>
    <input id="imp_file" type="file" class="inp">
    <div class="row"><button class="btn" onclick="doImport()">Importovať</button></div>
    <div id="imp_msg"></div>
  </div>

</div>

<script>
const $ = id => document.getElementById(id);
const api = (path, opt={})=>{
  const key = localStorage.getItem('apiKey') || $('apiKey').value;
  if(!key) throw new Error('Chýba API Key');
  opt.headers = Object.assign({'x-api-key': key}, opt.headers||{});
  return fetch(path, opt);
};
function setStatus(ok){
  $('status').textContent = ok ? 'online' : 'offline';
  $('status').style.background = ok ? '#e8f7f0' : '#fdeeee';
  $('status').style.color = ok ? '#0a7f58' : '#a33';
}
(async()=>{
  const storedKey = localStorage.getItem('apiKey'); if(storedKey) $('apiKey').value = storedKey;
  $('apiKey').addEventListener('change', e=> localStorage.setItem('apiKey', e.target.value));
  try{ const r = await fetch('/health'); const d = await r.json(); setStatus(d.status==='ok'); }catch(_){ setStatus(false); }
})();

async function createPatient(){
  const uid = $('uid').value.trim(), first=$('first').value.trim(), last=$('last').value.trim();
  if(!uid || !first || !last){ $('msg').innerHTML = '<span class="err">Vyplň UID, meno, priezvisko.</span>'; return; }
  try{
    const res = await api('/patients', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ patient_uid: uid, first_name:first, last_name:last, gender:'U' })});
    if(!res.ok){ throw new Error(await res.text()); }
    $('msg').innerHTML = '<span class="ok">Pacient uložený ('+uid+')</span>';
    localStorage.setItem('lastUID', uid);
    await loadPatients(); await loadRecords();
  }catch(e){ $('msg').innerHTML = '<span class="err">Chyba: '+e.message+'</span>'; }
}

async function loadPatients(){
  try{
    const res = await api('/patients'); const data = await res.json();
    if(!Array.isArray(data) || !data.length){ $('plist').innerHTML='<small>Žiadni pacienti.</small>'; return; }
    const rows = data.map(p=>`<li>${p.patient_uid} — ${p.first_name} ${p.last_name}</li>`).join('');
    $('plist').innerHTML = '<ul>'+rows+'</ul>';
  }catch(e){ $('plist').innerHTML = '<span class="err">Chyba: '+e.message+'</span>'; }
}

async function loadRecords(){
  const uid = $('uid').value.trim() || localStorage.getItem('lastUID');
  if(!uid){ $('msg').innerHTML = '<span class="err">Zadaj UID pacienta.</span>'; return; }
  $('uid').value = uid;
  try{
    const res = await api('/patients/'+encodeURIComponent(uid)+'/records');
    const items = await res.json();
    if(!items.length){ $('list').innerHTML = '<small>Žiadne záznamy.</small>'; return; }
    const rows = items.map(r=>`
      <tr><td><small>${(r.timestamp||'').replace('T',' ').slice(0,16)}</small></td>
          <td><span class="badge">${r.category}</span></td>
          <td>${escapeHtml(r.content||'')}</td></tr>`).join('');
    $('list').innerHTML = '<table><thead><tr><th>Čas</th><th>Kategória</th><th>Obsah</th></tr></thead><tbody>'+rows+'</tbody></table>';
  }catch(e){ $('list').innerHTML = '<span class="err">Chyba: '+e.message+'</span>'; }
}

async function saveRecord(){
  const uid = $('uid').value.trim() || localStorage.getItem('lastUID');
  if(!uid){ $('msg').innerHTML = '<span class="err">Najprv vyplň UID.</span>'; return; }
  const raw = $('content').value.trim();
  if(!raw){ $('msg').innerHTML = '<span class="err">Prázdny obsah.</span>'; return; }

  let payload = { content: raw };
  try{ const j = JSON.parse(raw);
    payload = { content: j.content || raw, category: j.category || null, timestamp: j.timestamp || null };
  }catch(_){}

  try{
    const res = await api('/patients/'+encodeURIComponent(uid)+'/records',
      {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    if(!res.ok){ throw new Error(await res.text()); }
    $('content').value=''; await loadRecords();
    $('msg').innerHTML = '<span class="ok">Záznam uložený.</span>';
  }catch(e){ $('msg').innerHTML = '<span class="err">Chyba: '+e.message+'</span>'; }
}

async function doImport(){
  const uid = ($('imp_uid').value || $('uid').value || '').trim();
  if(!uid){ $('imp_msg').innerHTML = '<span class="err">Zadaj UID pacienta.</span>'; return; }
  const form = new FormData();
  form.append('patient_uid', uid);
  const file = $('imp_file').files[0];
  const text = $('imp_text').value.trim();
  if(file){ form.append('file', file); } else { form.append('text', text); }

  try{
    const res = await api('/import', { method:'POST', body: form });
    if(!res.ok){ throw new Error(await res.text()); }
    const d = await res.json();
    $('imp_msg').innerHTML = '<span class="ok">Import OK ('+d.category+')</span>';
    await loadRecords();
  }catch(e){
    $('imp_msg').innerHTML = '<span class="err">Chyba: '+e.message+'</span>';
  }
}

function escapeHtml(s){return s.replace(/[&<>"']/g, m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
</script>
</body></html>
"""

@app.get("/", response_class=HTMLResponse)
def ui():
    return HTMLResponse(content=HTML, media_type="text/html")
