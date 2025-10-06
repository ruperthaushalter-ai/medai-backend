from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import os

app = FastAPI(title="MedAI Dashboard 2.4")

API_KEY = os.getenv("API_KEY", "m3dAI_7YtqgY2WJr9vQdXz")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== MODELY =====
class Patient(BaseModel):
    patient_uid: str
    first_name: str | None = None
    last_name: str | None = None
    gender: str | None = None

class Record(BaseModel):
    category: str | None = None
    timestamp: str
    content: dict | str

patients = {}
records = {}

# ===== DETEKCIA KATEGÓRIE =====
def detect_category(content):
    text = str(content).lower()
    if any(k in text for k in ["crp", "hb", "alt", "ast", "value", "mg/l", "mmol", "g/l"]):
        return "LAB"
    elif any(k in text for k in ["rtg", "röntgen", "rentgen"]):
        return "RTG"
    elif "ekg" in text:
        return "EKG"
    elif any(k in text for k in ["ceftriax", "lieč", "podan", "infuz", "antibiotik"]):
        return "THERAPY"
    elif any(k in text for k in ["teplota", "tlak", "sat", "frekv", "pulse"]):
        return "VITALS"
    else:
        return "NOTE"

# ===== API =====
@app.get("/health")
def health(): return {"status": "OK"}

@app.get("/patients")
def get_patients(request: Request):
    if request.headers.get("X-API-Key") != API_KEY:
        raise HTTPException(403, "Invalid API Key")
    return list(patients.values())

@app.post("/patients")
def create_patient(request: Request, p: Patient):
    if request.headers.get("X-API-Key") != API_KEY:
        raise HTTPException(403, "Invalid API Key")
    patients[p.patient_uid] = p.dict()
    records[p.patient_uid] = []
    return {"status": "created", "uid": p.patient_uid}

@app.get("/patients/{uid}/records")
def get_records(uid: str, request: Request):
    if request.headers.get("X-API-Key") != API_KEY:
        raise HTTPException(403, "Invalid API Key")
    return sorted(records.get(uid, []), key=lambda r: r["timestamp"])

@app.post("/patients/{uid}/records")
def add_record(uid: str, request: Request, r: Record):
    if request.headers.get("X-API-Key") != API_KEY:
        raise HTTPException(403, "Invalid API Key")
    if uid not in records:
        raise HTTPException(404, "Patient not found")
    if not r.category:
        r.category = detect_category(r.content)
    records[uid].append(r.dict())
    return {"status": "added", "detected_category": r.category}

# ===== AI ANALÝZA =====
@app.get("/ai/summary/{uid}")
def ai_summary(uid: str, request: Request):
    if request.headers.get("X-API-Key") != API_KEY:
        raise HTTPException(403, "Invalid API Key")
    recs = sorted(records.get(uid, []), key=lambda r: r["timestamp"])
    if not recs:
        return {"discharge_draft": "Žiadne dáta."}
    days = len(set(r["timestamp"][:10] for r in recs))
    labs = [r for r in recs if r["category"] == "LAB"]
    diag = []
    if any("crp" in str(r["content"]).lower() for r in labs): diag.append("Infekcia?")
    if any("alt" in str(r["content"]).lower() for r in labs): diag.append("Hepatopatia?")
    if any("hb" in str(r["content"]).lower() for r in labs): diag.append("Anémia?")
    timeline = "\n".join([f"{r['timestamp'][:10]} [{r['category']}] – {r['content']}" for r in recs])
    summary = f"""
🩺 Chronologická epikríza:

{timeline}

----------------------------
📋 Súhrn hospitalizácie:
Pacient mal {len(recs)} záznamov počas {days} dní hospitalizácie.
Z toho {len(labs)} laboratórnych vyšetrení.
AI detegovala možné diagnózy: {', '.join(diag) if diag else 'bez abnormít'}.
"""
    return {"discharge_draft": summary}

# ===== FRONTEND =====
@app.get("/", response_class=HTMLResponse)
def ui():
    return """
    <html>
    <head>
        <title>MedAI Dashboard 2.4</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
        <style>
            body { font-family: 'Inter', sans-serif; background:#f4f6fa; color:#111; margin:0; }
            header { background:#1e4e9a; color:white; padding:10px 20px; display:flex; justify-content:space-between; align-items:center; }
            .container { display:flex; flex-wrap:wrap; padding:10px; }
            .panel { background:white; border-radius:8px; margin:8px; padding:12px; flex:1; min-width:320px; box-shadow:0 2px 6px rgba(0,0,0,0.1);}
            input, textarea { width:100%; margin:5px 0; padding:6px; border:1px solid #ccc; border-radius:4px; }
            button { background:#1e4e9a; color:white; border:none; padding:6px 12px; border-radius:5px; cursor:pointer; }
            pre { white-space: pre-wrap; background:#f0f0f0; padding:10px; border-radius:6px; }
        </style>
    </head>
    <body>
        <header>
            <h2>🏥 MedAI Dashboard 2.4</h2>
            <input id="apiKey" placeholder="API Key" style="width:250px;">
        </header>

        <div class="container">
            <div class="panel">
                <h3>Pacienti</h3>
                <button onclick="loadPatients()">🔄 Načítať</button>
                <div id="patientList"></div>
                <hr>
                <input id="uid" placeholder="UID (P001)">
                <input id="fname" placeholder="Meno">
                <input id="lname" placeholder="Priezvisko">
                <button onclick="createPatient()">➕ Vytvoriť</button>
            </div>

            <div class="panel">
                <h3>Záznamy</h3>
                <textarea id="content" placeholder='Obsah (text alebo JSON)'></textarea>
                <button onclick="addRecord()">💾 Uložiť</button>
                <hr>
                <div id="records"></div>
            </div>

            <div class="panel">
                <h3>Epikríza a AI</h3>
                <button onclick="generateAI()">🧠 Vytvoriť epikrízu</button>
                <button onclick="exportPDF()">📄 Exportovať PDF</button>
                <pre id="ai"></pre>
            </div>
        </div>

        <script>
        let selected=null, latest='';
        async function loadPatients(){
            const key=document.getElementById('apiKey').value;
            const res=await fetch('/patients',{headers:{'X-API-Key':key}});
            const data=await res.json();
            let html='';
            data.forEach(p=> html+=`<div onclick="selectPatient('${p.patient_uid}')">${p.patient_uid} ${p.first_name||''}</div>`);
            document.getElementById('patientList').innerHTML=html;
        }
        async function createPatient(){
            const key=document.getElementById('apiKey').value;
            const p={patient_uid:uid.value,first_name:fname.value,last_name:lname.value};
            await fetch('/patients',{method:'POST',headers:{'X-API-Key':key,'Content-Type':'application/json'},body:JSON.stringify(p)});
            loadPatients();
        }
        async function selectPatient(uid){
            selected=uid;
            const key=document.getElementById('apiKey').value;
            const res=await fetch(`/patients/${uid}/records`,{headers:{'X-API-Key':key}});
            const data=await res.json();
            let html='';
            data.forEach(r=> html+=`<b>${r.category}</b> (${r.timestamp.slice(0,10)}): ${JSON.stringify(r.content)}<hr>`);
            document.getElementById('records').innerHTML=html;
        }
        async function addRecord(){
            if(!selected){alert("Vyber pacienta");return;}
            const key=document.getElementById('apiKey').value;
            let contentVal=document.getElementById('content').value;
            let parsed; try{parsed=JSON.parse(contentVal);}catch{parsed=contentVal;}
            const body={timestamp:new Date().toISOString(),content:parsed};
            const res=await fetch(`/patients/${selected}/records`,{method:'POST',headers:{'X-API-Key':key,'Content-Type':'application/json'},body:JSON.stringify(body)});
            const out=await res.json();
            alert("Detegovaná kategória: "+out.detected_category);
            selectPatient(selected);
        }
        async function generateAI(){
            const key=document.getElementById('apiKey').value;
            const res=await fetch(`/ai/summary/${selected}`,{headers:{'X-API-Key':key}});
            const data=await res.json();
            latest=data.discharge_draft;
            document.getElementById('ai').textContent=data.discharge_draft;
        }
        function exportPDF(){
            if(!latest){alert('Najprv vytvor epikrízu');return;}
            const element=document.createElement('div');
            element.innerHTML='<h2>Prepúšťacia správa</h2><pre>'+latest+'</pre>';
            html2pdf().from(element).save(`epikriza_${selected}.pdf`);
        }
        </script>
    </body>
    </html>
    """
