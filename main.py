from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse
from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
import os

# --------------------------------------------------------------------
# SETTINGS
# --------------------------------------------------------------------
app = FastAPI(title="MedAI Backend v2.2")

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
# HEURISTIC AI SUMMARY
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
            c = r.category.lower()
            if "diag" in c:
                diagnoses.append(str(r.content))
            if "lie" in c:
                therapies.append(str(r.content))
            if "lab" in c:
                labs.append(r)
            if "viz" in c:
                visits.append(r)

        # štatistiky
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
# FRONTEND DASHBOARD 2.2
# --------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def ui_dashboard():
    return """
    <html>
    <head>
        <title>MedAI Dashboard 2.2</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
        <style>
            :root {
                --bg: #f2f4f8;
                --text: #111;
                --card: #fff;
                --accent: #1e4e9a;
                --border: #ccc;
            }
            body.dark {
                --bg: #121212;
                --text: #e0e0e0;
                --card: #1f1f1f;
                --accent: #4a90e2;
                --border: #333;
            }
            body { font-family: 'Inter', sans-serif; margin: 0; background: var(--bg); color: var(--text); transition: 0.3s; }
            header { background: var(--accent); color: white; padding: 12px 18px; display: flex; justify-content: space-between; align-items: center; }
            h1 { margin: 0; font-size: 22px; }
            .container { display: flex; flex-wrap: wrap; padding: 10px; }
            .sidebar { flex: 1; min-width: 260px; background: var(--card); margin: 10px; padding: 10px; border-radius: 8px; height: 88vh; overflow-y: auto; border: 1px solid var(--border); }
            .main { flex: 3; min-width: 300px; background: var(--card); margin: 10px; padding: 15px; border-radius: 8px; border: 1px solid var(--border); }
            button { background: var(--accent); color: white; border: none; padding: 8px 12px; border-radius: 6px; cursor: pointer; margin-top: 5px; }
            input, textarea, select { width: 100%; margin: 4px 0; padding: 6px; border: 1px solid var(--border); border-radius: 4px; background: var(--card); color: var(--text); }
            .patient-item { padding: 8px; border-bottom: 1px solid var(--border); cursor: pointer; }
            .tab { display:inline-block; padding:6px 10px; border-radius:5px; margin-right:5px; cursor:pointer; background:#e4e8ef; }
            .tab.active { background: var(--accent); color: white; }
            .tabContent { display:none; }
            pre { white-space: pre-wrap; background: #0001; padding: 10px; border-radius: 6px; color: var(--text); }
            canvas { max-width:100%; background:#fff1; border-radius:8px; margin-top:10px; }
        </style>
    </head>
    <body>
        <header><h1>🩺 MedAI Dashboard 2.2</h1><button onclick="toggleDark()">🌙 Režim</button></header>

        <div class="container">
            <div class="sidebar">
                <h3>Pacienti</h3>
                <input id="apiKey" placeholder="API Key">
                <button onclick="loadPatients()">Načítať pacientov</button>
                <div id="patientList"></div>
                <hr><h4>Nový pacient</h4>
                <input id="uid" placeholder="UID">
                <input id="fname" placeholder="Meno">
                <input id="lname" placeholder="Priezvisko">
                <select id="gender"><option value="M">M</option><option value="F">F</option></select>
                <button onclick="createPatient()">Vytvoriť</button>
            </div>

            <div class="main">
                <div>
                    <span class="tab active" onclick="showTab('timeline')">📆 Priebeh</span>
                    <span class="tab" onclick="showTab('summary')">🧠 AI Summary</span>
                    <span class="tab" onclick="showTab('therapy')">💊 Liečba</span>
                    <span class="tab" onclick="showTab('stats')">📊 Štatistiky</span>
                    <button onclick="exportPDF()">📄 Export PDF</button>
                </div>
                <div id="timeline" class="tabContent" style="display:block;"></div>
                <div id="summary" class="tabContent"></div>
                <div id="therapy" class="tabContent"></div>
                <div id="stats" class="tabContent">
                    <h3>Štatistiky hospitalizácie</h3>
                    <div id="statsBox"></div>
                    <canvas id="labChart"></canvas>
                </div>
                <hr><h4>Pridaj záznam</h4>
                <input id="cat" placeholder="Kategória">
                <textarea id="content" placeholder='Obsah JSON (napr. {"test":"CRP","value":120,"unit":"mg/L"})'></textarea>
                <button onclick="addRecord()">Pridať</button>
            </div>
        </div>

        <script>
        let selectedPatient=null;let latestSummary='';let chart=null;
        function toggleDark(){document.body.classList.toggle('dark');}
        function showTab(id){document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
            document.querySelectorAll('.tabContent').forEach(c=>c.style.display='none');
            document.querySelector(`.tab[onclick="showTab('${id}')"]`).classList.add('active');
            document.getElementById(id).style.display='block';}
        async function loadPatients(){
            const apiKey=document.getElementById('apiKey').value;
            const res=await fetch('/patients',{headers:{'X-API-Key':apiKey}});
            const data=await res.json();const list=document.getElementById('patientList');list.innerHTML='';
            data.forEach(p=>{const div=document.createElement('div');div.className='patient-item';
                div.textContent=`${p.patient_uid} - ${p.first_name||''} ${p.last_name||''}`;
                div.onclick=()=>loadPatient(p.patient_uid);list.appendChild(div);});}
        async function createPatient(){
            const apiKey=document.getElementById('apiKey').value;
            const body={patient_uid:uid.value,first_name:fname.value,last_name:lname.value,gender:gender.value};
            await fetch('/patients',{method:'POST',headers:{'Content-Type':'application/json','X-API-Key':apiKey},body:JSON.stringify(body)});loadPatients();}
        async function loadPatient(uid){
            selectedPatient=uid;const apiKey=document.getElementById('apiKey').value;
            const res=await fetch(`/ai/summary/${uid}`,{headers:{'X-API-Key':apiKey}});const data=await res.json();
            latestSummary=data.discharge_draft;
            document.getElementById('summary').innerHTML=`<pre>${latestSummary}</pre>`;
            document.getElementById('timeline').innerHTML=`<pre>${data.timeline}</pre>`;
            document.getElementById('therapy').innerHTML=`<pre>${data.diagnoses}</pre>`;
            document.getElementById('statsBox').innerHTML=`<pre>${JSON.stringify(data.stats,null,2)}</pre>`;
            if(data.labs.length>0){
                const values=data.labs.map(l=>l.data.value||0);
                const labels=data.labs.map(l=>new Date(l.time).toLocaleDateString());
                if(chart)chart.destroy();
                chart=new Chart(document.getElementById('labChart'),{type:'line',data:{labels:labels,datasets:[{label:'CRP / hodnoty LAB',data:values,borderColor:'#1e4e9a',fill:false}]},options:{scales:{y:{beginAtZero:true}}}});
            }}
        async function addRecord(){
            if(!selectedPatient){alert('Vyber pacienta');return;}
            const apiKey=document.getElementById('apiKey').value;const cat=document.getElementById('cat').value;
            let content;try{content=JSON.parse(document.getElementById('content').value);}catch{alert('Neplatný JSON');return;}
            await fetch(`/patients/${selectedPatient}/records`,{method:'POST',headers:{'Content-Type':'application/json','X-API-Key':apiKey},
                body:JSON.stringify({category:cat,timestamp:new Date().toISOString(),content:content})});
            loadPatient(selectedPatient);}
        function exportPDF(){
            if(!latestSummary){alert('Najprv načítaj AI summary');return;}
            const element=document.createElement('div');
            element.innerHTML=`<h2>Prepúšťacia správa</h2><pre>${latestSummary}</pre>`;
            html2pdf().from(element).save(`discharge_${selectedPatient}.pdf`);}
        </script>
    </body></html>
    """
