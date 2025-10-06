from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse
from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
import os

# --------------------------------------------------------------------
# SETTINGS
# --------------------------------------------------------------------
app = FastAPI(title="MedAI Backend v2.2+")

API_KEY = os.getenv("API_KEY", "m3dAI_7YtqgY2WJr9vQdXz")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/medai")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# --------------------------------------------------------------------
# DATABASE MODELS
# --------------------------------------------------------------------
class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True)
    patient_uid = Column(String, unique=True)
    first_name = Column(String)
    last_name = Column(String)
    gender = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    records = relationship("Record", back_populates="patient")


class Record(Base):
    __tablename__ = "records"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"))
    timestamp = Column(DateTime, default=datetime.utcnow)
    category = Column(String)
    content = Column(JSON)
    patient = relationship("Patient", back_populates="records")


Base.metadata.create_all(bind=engine)

# --------------------------------------------------------------------
# SECURITY
# --------------------------------------------------------------------
def check_key(x_api_key: str | None):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")

# --------------------------------------------------------------------
# ENDPOINTS
# --------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/patients")
def create_patient(patient: dict, x_api_key: str | None = Header(default=None)):
    check_key(x_api_key)
    with SessionLocal() as s:
        p = Patient(
            patient_uid=patient["patient_uid"],
            first_name=patient.get("first_name"),
            last_name=patient.get("last_name"),
            gender=patient.get("gender", "M"),
        )
        s.add(p)
        s.commit()
        return {"id": p.id, "patient_uid": p.patient_uid}

@app.get("/patients")
def list_patients(x_api_key: str | None = Header(default=None)):
    check_key(x_api_key)
    with SessionLocal() as s:
        rows = s.query(Patient).order_by(Patient.created_at.desc()).all()
        return [
            {
                "patient_uid": r.patient_uid,
                "first_name": r.first_name,
                "last_name": r.last_name,
                "gender": r.gender,
                "created_at": r.created_at,
            }
            for r in rows
        ]

@app.post("/patients/{patient_uid}/records")
def add_record(patient_uid: str, record: dict, x_api_key: str | None = Header(default=None)):
    check_key(x_api_key)
    with SessionLocal() as s:
        p = s.query(Patient).filter(Patient.patient_uid == patient_uid).first()
        if not p:
            raise HTTPException(404, "Patient not found")
        r = Record(
            patient=p,
            category=record["category"],
            timestamp=datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00")),
            content=record["content"],
        )
        s.add(r)
        s.commit()
        return {"status": "record added"}

@app.get("/patients/{patient_uid}/records")
def get_records(patient_uid: str, x_api_key: str | None = Header(default=None)):
    check_key(x_api_key)
    with SessionLocal() as s:
        p = s.query(Patient).filter(Patient.patient_uid == patient_uid).first()
        if not p:
            raise HTTPException(404, "Patient not found")
        recs = s.query(Record).filter(Record.patient == p).order_by(Record.timestamp).all()
        return [
            {"category": r.category, "timestamp": r.timestamp, "content": r.content}
            for r in recs
        ]

# --------------------------------------------------------------------
# HEURISTIC AI SUMMARY (nezmenené)
# --------------------------------------------------------------------
@app.get("/ai/summary/{patient_uid}")
def ai_summary(patient_uid: str, x_api_key: str | None = Header(default=None)):
    check_key(x_api_key)
    with SessionLocal() as s:
        p = s.query(Patient).filter(Patient.patient_uid == patient_uid).first()
        if not p:
            raise HTTPException(404, "Patient not found")
        recs = s.query(Record).filter(Record.patient == p).order_by(Record.timestamp).all()

        summary_lines = []
        diagnoses, therapies, labs, visits = [], [], [], []

        for r in recs:
            line = f"- {r.timestamp.strftime('%Y-%m-%d %H:%M')} {r.category}: {r.content}"
            summary_lines.append(line)
            c = (r.category or "").lower()
            if "diag" in c:
                diagnoses.append(str(r.content))
            if "lie" in c:
                therapies.append(str(r.content))
            if "lab" in c:
                labs.append(r)
            if "viz" in c:
                visits.append(r)

        num_days = (recs[-1].timestamp - recs[0].timestamp).days + 1 if recs else 0
        stats = {
            "pocet_zaznamov": len(recs),
            "pocet_vizit": len(visits),
            "pocet_lab": len(labs),
            "pocet_liecby": len(therapies),
            "dlzka_hospitalizacie_dni": num_days,
        }

        return {
            "diagnoses": "\n".join(diagnoses) or "bez diagnózy",
            "timeline": "\n".join(summary_lines),
            "stats": stats,
            "labs": [{"time": r.timestamp.isoformat(), "data": r.content} for r in labs],
            "discharge_draft": f"""
PREPÚŠŤACIA SPRÁVA – NÁVRH

Pacient: {p.first_name} {p.last_name} ({p.patient_uid})
Pohlavie: {p.gender}

Diagnózy:
{'; '.join(diagnoses) or 'bez diagnózy'}

Chronologický priebeh:
{chr(10).join(summary_lines)}

Liečba:
{chr(10).join(therapies) or 'bez liečby'}

Dĺžka hospitalizácie: {num_days} dní
            """,
        }

# --------------------------------------------------------------------
# FRONTEND DASHBOARD 2.2+ (rozšírené UI, bez zmeny API)
# --------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def ui_dashboard():
    return """
<!doctype html>
<html lang="sk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MedAI Dashboard 2.2+</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
<style>
:root{--bg:#f2f4f8;--text:#111;--card:#fff;--accent:#1e4e9a;--border:#d6d9e0;--muted:#6b7280}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,Inter,sans-serif}
header{background:var(--accent);color:#fff;padding:12px 16px;display:flex;align-items:center;gap:12px;justify-content:space-between}
header .brand{font-weight:700}
.wrap{display:flex;gap:12px;padding:12px;flex-wrap:wrap}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px}
.sidebar{flex:1;min-width:270px;max-width:360px;height:86vh;overflow:auto}
.main{flex:3;min-width:320px}
input,select,textarea{width:100%;padding:10px;border:1px solid var(--border);border-radius:8px;background:#fff}
button{background:var(--accent);color:#fff;border:none;border-radius:8px;padding:9px 12px;cursor:pointer}
.badge{font-size:12px;padding:4px 8px;border-radius:999px;background:#16a34a15;color:#16a34a;border:1px solid #16a34a33}
.list{border:1px solid var(--border);border-radius:8px;overflow:hidden}
.item{padding:10px 12px;border-bottom:1px solid var(--border);cursor:pointer}
.item:last-child{border-bottom:none}
.item:hover{background:#eef2ff}
.row{display:flex;gap:8px;flex-wrap:wrap}
.tabbar{display:flex;gap:8px;margin:6px 0 10px 0}
.tab{background:#e5e7eb;border-radius:8px;padding:8px 10px;cursor:pointer}
.tab.active{background:var(--accent);color:#fff}
.subtabs{display:flex;gap:6px;margin:8px 0 6px}
.sub{font-size:12px;background:#f1f5f9;border:1px solid var(--border);padding:6px 8px;border-radius:999px;cursor:pointer}
.sub.active{background:#dbeafe}
pre{white-space:pre-wrap;background:#00000008;padding:10px;border-radius:8px;border:1px solid var(--border)}
.helper{font-size:12px;color:var(--muted)}
.drawer{position:fixed;right:0;top:0;width:420px;max-width:100%;height:100%;background:#fff;border-left:1px solid var(--border);box-shadow:-10px 0 20px rgba(0,0,0,.06);transform:translateX(110%);transition:.25s;padding:14px;overflow:auto}
.drawer.open{transform:none}
.drawer h3{margin-top:0}
</style>
</head>
<body>
<header>
  <div class="brand">🩺 MedAI Dashboard 2.2+</div>
  <div class="row" style="align-items:center">
    <input id="apiKey" placeholder="API Key" style="width:240px">
    <span id="online" class="badge">offline</span>
    <button onclick="toggleTheme()">🌓</button>
  </div>
</header>

<div class="wrap">
  <!-- SIDEBAR -->
  <div class="card sidebar">
    <div class="row">
      <input id="search" placeholder="Hľadať pacienta..." oninput="filterPatients()">
      <button onclick="loadPatients()">Načítať pacientov</button>
    </div>
    <div class="helper">Filtrovanie: všetci | posledné vytvorené</div>
    <div id="patientList" class="list" style="margin-top:8px"></div>
    <hr>
    <h4>Nový pacient</h4>
    <div class="row">
      <input id="uid" placeholder="UID (napr. P001)">
      <select id="gender"><option value="M">M</option><option value="F">F</option></select>
      <input id="fname" placeholder="Meno">
      <input id="lname" placeholder="Priezvisko">
      <button onclick="createPatient()">Vytvoriť</button>
    </div>
  </div>

  <!-- MAIN -->
  <div class="card main">
    <div id="patientHeader" class="helper">Vyber pacienta zo zoznamu vľavo.</div>

    <div class="tabbar">
      <div class="tab active" data-tab="timeline" onclick="showTab('timeline')">📆 Priebeh</div>
      <div class="tab" data-tab="summary" onclick="showTab('summary')">🧠 AI Summary</div>
      <div class="tab" data-tab="therapy" onclick="showTab('therapy')">💊 Liečba</div>
      <div class="tab" data-tab="stats" onclick="showTab('stats')">📊 Štatistiky</div>
      <button onclick="exportPDF()">📄 Export PDF</button>
    </div>

    <div class="subtabs" id="filterBar" style="display:none">
      <div class="sub active" data-kind="ALL" onclick="setKind('ALL')">Všetko</div>
      <div class="sub" data-kind="LAB" onclick="setKind('LAB')">LAB</div>
      <div class="sub" data-kind="EKG" onclick="setKind('EKG')">EKG</div>
      <div class="sub" data-kind="RTG" onclick="setKind('RTG')">RTG</div>
      <div class="sub" data-kind="VIZITA" onclick="setKind('VIZITA')">Vizity</div>
      <div class="sub" data-kind="DIAG" onclick="setKind('DIAG')">Diagnózy</div>
      <div class="sub" data-kind="OTHER" onclick="setKind('OTHER')">Ostatné</div>
    </div>

    <div id="timeline" class="tabPane" style="display:block"></div>
    <div id="summary" class="tabPane"></div>
    <div id="therapy" class="tabPane"></div>
    <div id="stats" class="tabPane">
      <h3>Štatistiky hospitalizácie</h3>
      <div id="statsBox"><pre>{}</pre></div>
      <canvas id="labChart"></canvas>
    </div>

    <hr>
    <h4>Rýchle šablóny</h4>
    <div class="row">
      <button onclick='quick("LAB")'>LAB</button>
      <button onclick='quick("EKG")'>EKG</button>
      <button onclick='quick("RTG")'>RTG</button>
      <button onclick='quick("VIZITA")'>Vizita</button>
      <button onclick='quick("DIAG")'>Diagnóza</button>
      <button onclick='quick("LIEČBA")'>Liečba</button>
    </div>

    <h4 style="margin-top:10px">Pridaj záznam</h4>
    <div class="row">
      <label><input type="checkbox" id="autoCat" checked> Auto kategória</label>
    </div>
    <div class="row">
      <input id="cat" placeholder="Kategória (ak je Auto vypnuté)">
      <textarea id="content" rows="5" placeholder='Obsah JSON (napr. {"test":"CRP","value":120,"unit":"mg/L"})'></textarea>
      <button onclick="addRecord()">Pridať</button>
    </div>
    <div class="helper">TIP: „CRP 120 mg/L“ → pri zapnutej voľbe „Auto kategória“ sa zvolí LAB.</div>
  </div>
</div>

<!-- Drawer detail -->
<div id="drawer" class="drawer">
  <div class="row" style="justify-content:space-between">
    <h3>Detail záznamu</h3>
    <button onclick="closeDrawer()">✖</button>
  </div>
  <div id="drawerBody"><pre>{}</pre></div>
  <div class="row">
    <button onclick="copyDrawer()">Kopírovať JSON</button>
  </div>
</div>

<script>
let selectedPatient=null, latestSummary='', chart=null, allRecords=[], kind="ALL", allPatients=[];
function toggleTheme(){document.body.classList.toggle('dark')}
function markOnline(state){document.getElementById('online').textContent=state?'online':'offline'}

async function ping(){
  try{const r=await fetch('/health'); markOnline(r.ok)}catch{markOnline(false)}
} ping();

function showTab(id){
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  document.querySelector(`.tab[data-tab="${id}"]`).classList.add('active');
  document.querySelectorAll('.tabPane').forEach(x=>x.style.display='none');
  document.getElementById(id).style.display='block';
}

function setKind(k){ kind=k;
  document.querySelectorAll('.sub').forEach(x=>x.classList.remove('active'));
  document.querySelector(`.sub[data-kind="${k}"]`).classList.add('active');
  renderTimeline();
}

function filterPatients(){
  const q=document.getElementById('search').value.trim().toLowerCase();
  renderPatientList(allPatients.filter(p=>{
    const s = `${p.patient_uid} ${p.first_name||''} ${p.last_name||''}`.toLowerCase();
    return s.includes(q);
  }));
}

function renderPatientList(list){
  const box=document.getElementById('patientList'); box.innerHTML='';
  list.forEach(p=>{
    const div=document.createElement('div'); div.className='item';
    div.textContent = `${p.patient_uid} — ${p.first_name||''} ${p.last_name||''}`;
    div.onclick=()=>loadPatient(p.patient_uid);
    box.appendChild(div);
  });
}

async function loadPatients(){
  try{
    const apiKey=document.getElementById('apiKey').value;
    const res=await fetch('/patients',{headers:{'X-API-Key':apiKey}});
    if(!res.ok){throw new Error(await res.text())}
    allPatients=await res.json();
    renderPatientList(allPatients);
  }catch(e){alert('Načítanie pacientov zlyhalo'); console.error(e)}
}

async function createPatient(){
  try{
    const apiKey=document.getElementById('apiKey').value;
    const body={patient_uid:uid.value,first_name:fname.value,last_name:lname.value,gender:gender.value};
    const r=await fetch('/patients',{method:'POST',headers:{'Content-Type':'application/json','X-API-Key':apiKey},body:JSON.stringify(body)});
    if(!r.ok){throw new Error(await r.text())}
    await loadPatients();
  }catch(e){alert('Vytvorenie pacienta zlyhalo'); console.error(e)}
}

async function loadPatient(uid){
  selectedPatient=uid;
  document.getElementById('filterBar').style.display='flex';
  const apiKey=document.getElementById('apiKey').value;
  // AI summary
  const s=await fetch(`/ai/summary/${uid}`,{headers:{'X-API-Key':apiKey}}); const data=await s.json();
  latestSummary=data.discharge_draft || '';
  document.getElementById('summary').innerHTML=`<pre>${latestSummary}</pre>`;
  document.getElementById('therapy').innerHTML=`<pre>${data.diagnoses}</pre>`;
  document.getElementById('statsBox').innerHTML=`<pre>${JSON.stringify(data.stats,null,2)}</pre>`;

  // LAB graf
  if(data.labs && data.labs.length){
    const labels=data.labs.map(l=>new Date(l.time).toLocaleDateString());
    const values=data.labs.map(l=>Number(l.data.value)||0);
    if(chart) chart.destroy();
    chart=new Chart(document.getElementById('labChart'),{
      type:'line',
      data:{labels,datasets:[{label:'CRP / hodnoty LAB',data:values}]},
      options:{responsive:true, scales:{y:{beginAtZero:true}}}
    });
  } else { if(chart) chart.destroy(); }

  // všetky záznamy
  const r=await fetch(`/patients/${uid}/records`,{headers:{'X-API-Key':apiKey}});
  allRecords = r.ok ? await r.json() : [];
  document.getElementById('patientHeader').textContent = `Pacient: ${uid}`;
  renderTimeline();
}

function renderTimeline(){
  const el=document.getElementById('timeline');
  const filt = allRecords.filter(rec=>{
    const c=(rec.category||'').toUpperCase();
    if(kind==='ALL') return true;
    if(kind==='OTHER') return !['LAB','EKG','RTG','VIZITA','DIAG'].some(k=>c.includes(k));
    return c.includes(kind);
  });
  if(filt.length===0){el.innerHTML='<div class="helper">Žiadne záznamy pre vybraný filter.</div>'; return;}
  el.innerHTML = filt.map(rec=>{
    const t = new Date(rec.timestamp).toLocaleString();
    const c = rec.category || '';
    const json = JSON.stringify(rec.content,null,2).replace(/</g,"&lt;");
    return `<div class="item" onclick='openDrawer(${JSON.stringify(json)})'>
              <b>${t}</b> — <i>${c}</i>
            </div>`;
  }).join('');
}

function openDrawer(jsonText){
  const body=document.getElementById('drawerBody');
  body.innerHTML = `<pre>${jsonText}</pre>`;
  document.getElementById('drawer').classList.add('open');
}
function closeDrawer(){document.getElementById('drawer').classList.remove('open')}
async function copyDrawer(){
  const txt=document.getElementById('drawerBody').innerText;
  try{await navigator.clipboard.writeText(txt); alert('Skopírované')}catch{alert('Nedalo sa kopírovať')}
}

function quick(type){
  const c=document.getElementById('content'); const cat=document.getElementById('cat');
  if(type==='LAB'){cat.value='LAB'; c.value='{"test":"CRP","value":0,"unit":"mg/L"}'}
  if(type==='EKG'){cat.value='EKG'; c.value='{"rhythm":"sinus","rate":70,"st":"normal"}'}
  if(type==='RTG'){cat.value='RTG'; c.value='{"modality":"RTG","finding":"bez čerstých ložísk"}'}
  if(type==='VIZITA'){cat.value='VIZITA'; c.value='{"note":"klinický stav stabilný"}'}
  if(type==='DIAG'){cat.value='DIAG'; c.value='{"dx":"J18.9 Pneumónia"}'}
  if(type==='LIEČBA'){cat.value='LIEČBA'; c.value='{"atb":"amoxicilin","dose":"1g 3x denne"}'}
}

function autoDetectCategory(obj){
  const txt = JSON.stringify(obj).toLowerCase();
  if(/crp|tropon/i.test(txt)) return 'LAB';
  if(/ekg|rhythm|st"/.test(txt)) return 'EKG';
  if(/rtg|rentgen|x-ray|modality":"rtg/.test(txt)) return 'RTG';
  if(/vizita|klinick/.test(txt)) return 'VIZITA';
  if(/diag|dx":/.test(txt)) return 'DIAG';
  if(/liec|atb|dose|mg/.test(txt)) return 'LIEČBA';
  return 'OTHER';
}

async function addRecord(){
  if(!selectedPatient){alert('Vyber pacienta');return;}
  let obj;
  try{ obj = JSON.parse(document.getElementById('content').value || '{}'); }
  catch{ alert('Neplatný JSON'); return; }

  let category = document.getElementById('cat').value.trim();
  if(document.getElementById('autoCat').checked || !category){
    category = autoDetectCategory(obj);
  }

  const apiKey=document.getElementById('apiKey').value;
  const payload = { category, timestamp:new Date().toISOString(), content:obj };

  const r = await fetch(`/patients/${selectedPatient}/records`,{
    method:'POST', headers:{'Content-Type':'application/json','X-API-Key':apiKey}, body:JSON.stringify(payload)
  });
  if(!r.ok){ alert('Ukladanie zlyhalo'); return; }
  await loadPatient(selectedPatient);
}

function exportPDF(){
  if(!latestSummary){alert('Najprv načítaj AI Summary');return;}
  const el=document.createElement('div');
  el.innerHTML = '<h2>Prepúšťacia správa</h2><pre>'+latestSummary.replace(/</g,"&lt;")+'</pre>';
  html2pdf().from(el).save('discharge_'+(selectedPatient||'patient')+'.pdf');
}
</script>
</body>
</html>
    """
