from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import json
import re

app = FastAPI(title="MedAI Backend 2.3")

# ✅ Povolenie CORS pre frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔑 API kľúč
API_KEY = os.getenv("API_KEY", "m3dAI_7YtgqY2WJr9vQdXz")

def require_api_key(request: Request):
    key = request.headers.get("x-api-key")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")

# 📦 Jednoduchá „databáza“ (pamäť)
patients = {}
records = {}

# 🧠 Automatické rozpoznanie kategórie z textu
def detect_category(text: str) -> str:
    text = text.lower()
    if any(word in text for word in ["crp", "hb", "leu", "lab"]):
        return "Laboratórium"
    elif any(word in text for word in ["ekg", "sinus", "tachykardia", "fibrilácia"]):
        return "EKG"
    elif any(word in text for word in ["rtg", "sono", "ct", "mri"]):
        return "Zobrazovacie vyšetrenia"
    elif any(word in text for word in ["tlak", "puls", "dych", "teplota"]):
        return "Vitalné funkcie"
    else:
        return "Iné"

# 📋 Modely
class Patient(BaseModel):
    patient_uid: str
    first_name: str
    last_name: str

class Record(BaseModel):
    content: str

# 🌍 Hlavná stránka (frontend)
@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content, media_type="text/html")
    except FileNotFoundError:
        return HTMLResponse("<h1>MedAI Dashboard not found</h1>", status_code=404)

# 🧩 API endpointy
@app.post("/patients", dependencies=[Depends(require_api_key)])
def create_patient(patient: Patient):
    patients[patient.patient_uid] = patient
    records[patient.patient_uid] = []
    return {"status": "ok", "patient_uid": patient.patient_uid}

@app.get("/patients", dependencies=[Depends(require_api_key)])
def list_patients():
    return list(patients.values())

@app.post("/patients/{patient_uid}/records", dependencies=[Depends(require_api_key)])
def add_record(patient_uid: str, record: Record):
    if patient_uid not in records:
        raise HTTPException(status_code=404, detail="Patient not found")
    category = detect_category(record.content)
    records[patient_uid].append({"content": record.content, "category": category})
    return {"status": "ok", "category": category}

@app.get("/patients/{patient_uid}/records", dependencies=[Depends(require_api_key)])
def list_records(patient_uid: str):
    if patient_uid not in records:
        raise HTTPException(status_code=404, detail="Patient not found")
    return records[patient_uid]

# 🧠 AI sumarizácia (jednoduchá heuristika)
@app.post("/summarize", dependencies=[Depends(require_api_key)])
def summarize(data: dict):
    text = data.get("text", "")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Text is empty")

    findings = detect_category(text)
    summary = f"Zhrnutie: text bol zaradený do kategórie {findings}."
    return {"summary": summary, "category": findings}

# 💓 Health check
@app.get("/health")
def health():
    return {"status": "ok"}
