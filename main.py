from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import os

app = FastAPI(title="MedAI Dashboard 2.2")

# ====== Konfigurácia ======
API_KEY = os.getenv("API_KEY", "m3dAI_7YtqgY2WJr9vQdXz")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ====== Dátové modely ======
class Patient(BaseModel):
    patient_uid: str
    first_name: str | None = None
    last_name: str | None = None
    gender: str | None = None

class Record(BaseModel):
    category: str
    timestamp: str
    content: dict

patients = {}
records = {}

# ====== API endpointy ======
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
    return records.get(uid, [])

@app.post("/patients/{uid}/records")
def add_record(uid: str, request: Request, r: Record):
    if request.headers.get("X-API-Key") != API_KEY:
        raise HTTPException(403, "Invalid API Key")
    if uid not in records: raise HTTPException(404, "Patient not found")
    records[uid].append(r.dict())
    return {"status": "added"}

# ====== AI Heuristika (mock analýza) ======
@app.get("/ai/summary/{uid}")
def ai_summary(uid: str, request: Request):
    if request.headers.get("X-API-Key") != API_KEY:
        raise HTTPException(403, "Invalid API Key")
    recs = records.get(uid, [])
    if not recs: return {"summary": "No data"}

    labs = [r for r in recs if r["category"].lower() == "lab"]
    days = len(set(r["timestamp"][:10] for r in recs))
    diag = []
    if any("crp" in str(r["content"]).lower() for r in labs): diag.append("Infekcia?")
    if any("alt" in str(r["content"]).lower() for r in labs): diag.append("Možné poškodenie pečene")
    draft = f"Pacient mal {len(recs)} záznamov počas {days} dní.\n" \
            f"Detegované kategórie: {', '.join(set(r['category'] for r in recs))}\n" \
            f"AI vyhodnotila možné diagnózy: {', '.join(diag) if diag else 'žiadne abnormity'}."
    return {"discharge_draft": draft}

# ====== FRONTEND DASHBOARD ======
@app.get("/", response_class=HTMLResponse)
def ui():
    return """
    <html>
    <head>
        <title>MedAI Dashboard 2.2</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: 'Inter', sans-serif; background:#f3f4f6; color:#111; margin:0; }
            header { background:#1e4e9a; color:white; padding:10px 20px; display:flex; justify-content:space-between; align-items:center; }
            button { background:#1e4e9a; color:white; border:none; padding:6px 12px; border-radius:5px; cursor:pointer; }
            .container { display:flex; flex-wrap:wrap; padding:10px; }
            .panel { background:white; border-radius:8px; margin:8px; padding:10px; flex:1; min-width:300px; box-shadow:0 2px 6px rgba(0,0,0,0.1);}
            input, textarea { width:100%; margin:4px 0; padding:6px; border:1px solid #ccc; border-radius:4px; }
            #chartDiv { height:300px; }
        </style>
    </head>
    <body>
        <header>
            <h2>🧠 MedAI Dashboard 2.2</h2>
            <input id="apiKey" placeholder="API Key" style="width:250px;">
        </header>
        <div class="container">
            <div class="panel">
                <h3>Pacienti</h3>
                <button onclick="loadPatients()">🔄 Načítať</button>
                <div id="patientList"></div>
                <hr>
                <h4>Nový pacient</h4>
                <input id="uid" placeholder="UID (P001)">
                <input id="fname" placeholder="Meno">
                <input id="lname" placeholder="Priezvisko">
                <button onclick="createPatient()">➕ Vytvoriť</button>
            </div>
            <div class="panel">
                <h3>📋 Záznamy</h3>
                <input id="cat" placeholder="Kategória">
                <textarea id="content" placeholder='Obsah JSON {"test":"CRP","value":120,"unit":"mg/L"}'></textarea>
                <button onclick="addRecord()">💾 Uložiť</button>
                <hr>
                <h4>História</h4>
                <div id="records"></div>
            </div>
            <div class="panel">
                <h3>📊 AI Analýza a Grafy</h3>
                <button onclick="generateAI()">🧠 Analyzovať</button>
                <pre id="ai"></pre>
                <canvas id="chartDiv"></canvas>
            </div>
        </div>
        <script>
        let selected = null;
        async function loadPatients(){
            const key = document.getElementById('apiKey').value;
            const res = await fetch('/patients',{headers:{'X-API-Key':key}});
            const data = await res.json();
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
            data.forEach(r=> html+=`${r.category}: ${JSON.stringify(r.content)}<hr>`);
            document.getElementById('records').innerHTML=html;
            renderChart(data);
        }
        async function addRecord(){
            if(!selected){alert("Vyber pacienta");return;}
            const key=document.getElementById('apiKey').value;
            let c; try{c=JSON.parse(content.value);}catch{alert("Neplatný JSON");return;}
            const body={category:cat.value,timestamp:new Date().toISOString(),content:c};
            await fetch(`/patients/${selected}/records`,{method:'POST',headers:{'X-API-Key':key,'Content-Type':'application/json'},body:JSON.stringify(body)});
            selectPatient(selected);
        }
        async function generateAI(){
            const key=document.getElementById('apiKey').value;
            const res=await fetch(`/ai/summary/${selected}`,{headers:{'X-API-Key':key}});
            const data=await res.json();
            document.getElementById('ai').textContent=data.discharge_draft;
        }
        function renderChart(data){
            const ctx=document.getElementById('chartDiv');
            const labs=data.filter(r=>r.category.toLowerCase()==='lab');
            if(!labs.length)return;
            const labels=labs.map(r=>new Date(r.timestamp).toLocaleDateString());
            const values=labs.map(r=>r.content.value||0);
            new Chart(ctx,{type:'line',data:{labels:labels,datasets:[{label:'Lab trend',data:values,borderColor:'#1e4e9a'}]}});
        }
        </script>
    </body></html>
    """
