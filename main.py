from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse
from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON, ForeignKey, func
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
import os

# --------------------------------------------------------------------
#  SETTINGS
# --------------------------------------------------------------------
app = FastAPI(title="MedAI Backend")

API_KEY = os.getenv("API_KEY", "m3dAI_7YtqgY2WJr9vQdXz")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/medai")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


# --------------------------------------------------------------------
#  DATABASE MODELS
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
#  SECURITY CHECK
# --------------------------------------------------------------------
def check_key(x_api_key: str | None):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")


# --------------------------------------------------------------------
#  ENDPOINTS
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
#  HEURISTIC AI SUMMARY
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
        diagnoses = []
        therapies = []

        for r in recs:
            line = f"- {r.timestamp.strftime('%Y-%m-%d %H:%M')} {r.category}: {r.content}"
            summary_lines.append(line)
            if "diag" in r.category.lower():
                diagnoses.append(str(r.content))
            if "lie" in r.category.lower():
                therapies.append(str(r.content))

        summary_text = "\n".join(summary_lines)
        diag_text = "\n".join(diagnoses) if diagnoses else "bez diagnózy"
        therapy_text = "\n".join(therapies) if therapies else "bez liečby"

        return {
            "diagnoses": diag_text,
            "timeline": summary_text,
            "discharge_draft": f"""
PREPÚŠŤACIA SPRÁVA – NÁVRH

Pacient: {p.first_name} {p.last_name} ({p.patient_uid})
Pohlavie: {p.gender}

Diagnózy:
{diag_text}

Chronologický priebeh:
{summary_text}

Liečba:
{therapy_text}

Odporúčania:
Pokračovať podľa klinického stavu, kontrola podľa potreby.
            """,
        }


# --------------------------------------------------------------------
#  FRONTEND DASHBOARD (v2.0)
# --------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def ui_dashboard():
    return """
    <html>
    <head>
        <title>MedAI Dashboard 2.0</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: Arial, sans-serif; margin: 0; background: #f2f4f8; }
            header { background: #1e4e9a; color: white; padding: 10px 15px; }
            h1 { margin: 0; font-size: 22px; }
            .container { display: flex; flex-wrap: wrap; padding: 10px; }
            .sidebar { flex: 1; min-width: 250px; background: #fff; margin: 10px; padding: 10px; border-radius: 8px; height: 90vh; overflow-y: auto; }
            .main { flex: 3; min-width: 300px; background: #fff; margin: 10px; padding: 15px; border-radius: 8px; }
            button { background: #1e4e9a; color: white; border: none; padding: 8px 12px; border-radius: 4px; cursor: pointer; }
            button:hover { background: #163b73; }
            input, textarea, select { width: 100%; margin: 4px 0; padding: 6px; border: 1px solid #ccc; border-radius: 4px; }
            .patient-item { padding: 8px; border-bottom: 1px solid #eee; cursor: pointer; }
            .patient-item:hover { background: #f3f3f3; }
            pre { white-space: pre-wrap; background: #f8f8f8; padding: 10px; border-radius: 6px; }
            .tabs { display: flex; gap: 10px; margin-bottom: 10px; }
            .tab { flex: 1; text-align: center; background: #e4e8ef; padding: 8px; border-radius: 6px; cursor: pointer; }
            .tab.active { background: #1e4e9a; color: white; }
        </style>
    </head>
    <body>
        <header><h1>🩺 MedAI Dashboard 2.0</h1></header>

        <div class="container">
            <div class="sidebar">
                <h3>Pacienti</h3>
                <input id="apiKey" placeholder="API Key" style="width:100%; margin-bottom:5px;" value="">
                <button onclick="loadPatients()">Načítať pacientov</button>
                <div id="patientList"></div>

                <hr>
                <h4>Nový pacient</h4>
                <input id="uid" placeholder="UID (napr. P003)">
                <input id="fname" placeholder="Meno">
                <input id="lname" placeholder="Priezvisko">
                <select id="gender"><option value="M">M</option><option value="F">F</option></select>
                <button onclick="createPatient()">Vytvoriť</button>
            </div>

            <div class="main">
                <div class="tabs">
                    <div class="tab active" onclick="showTab('timeline')">📆 Priebeh</div>
                    <div class="tab" onclick="showTab('summary')">🧠 AI Summary</div>
                    <div class="tab" onclick="showTab('therapy')">💊 Liečba</div>
                </div>

                <div id="timeline" class="tabContent"></div>
                <div id="summary" class="tabContent" style="display:none;"></div>
                <div id="therapy" class="tabContent" style="display:none;"></div>

                <hr>
                <h4>Pridaj záznam</h4>
                <input id="cat" placeholder="Kategória (napr. LAB, RTG, vizita...)">
                <textarea id="content" placeholder='Obsah JSON, napr. {"test":"CRP","value":120,"unit":"mg/L"}'></textarea>
                <button onclick="addRecord()">Pridať záznam</button>
            </div>
        </div>

        <script>
        let selectedPatient = null;

        function showTab(id){
            document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
            document.querySelectorAll('.tabContent').forEach(c=>c.style.display='none');
            document.querySelector(`.tab[onclick="showTab('${id}')"]`).classList.add('active');
            document.getElementById(id).style.display='block';
        }

        async function loadPatients(){
            const apiKey = document.getElementById('apiKey').value;
            const res = await fetch('/patients', { headers: { 'X-API-Key': apiKey }});
            const data = await res.json();
            const list = document.getElementById('patientList');
            list.innerHTML = '';
            data.forEach(p=>{
                const div = document.createElement('div');
                div.className='patient-item';
                div.textContent = `${p.patient_uid} - ${p.first_name||''} ${p.last_name||''}`;
                div.onclick = ()=>loadPatient(p.patient_uid);
                list.appendChild(div);
            });
        }

        async function createPatient(){
            const apiKey = document.getElementById('apiKey').value;
            const body = {
                patient_uid: document.getElementById('uid').value,
                first_name: document.getElementById('fname').value,
                last_name: document.getElementById('lname').value,
                gender: document.getElementById('gender').value
            };
            await fetch('/patients', { method:'POST', headers:{'Content-Type':'application/json','X-API-Key':apiKey}, body:JSON.stringify(body)});
            loadPatients();
        }

        async function loadPatient(uid){
            selectedPatient = uid;
            const apiKey = document.getElementById('apiKey').value;
            const res = await fetch(`/patients/${uid}/records`, { headers:{'X-API-Key':apiKey} });
            const data = await res.json();
            let html = '';
            let therapyList = [];
            data.forEach(r=>{
                const time = new Date(r.timestamp).toLocaleString();
                html += `<b>${r.category}</b> (${time})<br>${JSON.stringify(r.content)}<hr>`;
                if(r.category.toLowerCase().includes('lieč')){
                    therapyList.push(JSON.stringify(r.content));
                }
            });
            document.getElementById('timeline').innerHTML = html || 'Žiadne záznamy';
            document.getElementById('therapy').innerHTML = therapyList.join('<br>') || 'Žiadna liečba';
            const ai = await fetch(`/ai/summary/${uid}`, { headers:{'X-API-Key':apiKey}});
            const sum = await ai.json();
            document.getElementById('summary').innerHTML = `<pre>${sum.discharge_draft}</pre>`;
        }

        async function addRecord(){
            if(!selectedPatient){alert('Vyber pacienta.');return;}
            const apiKey = document.getElementById('apiKey').value;
            const cat = document.getElementById('cat').value;
            let content;
            try{ content = JSON.parse(document.getElementById('content').value); }catch{ alert('Neplatný JSON'); return; }
            await fetch(`/patients/${selectedPatient}/records`, {
                method:'POST',
                headers:{'Content-Type':'application/json','X-API-Key':apiKey},
                body:JSON.stringify({ category:cat, timestamp:new Date().toISOString(), content:content })
            });
            loadPatient(selectedPatient);
        }
        </script>
    </body>
    </html>
    """
