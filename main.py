from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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
# ENDPOINTS (nezmenené)
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
            if "diag" in c: therapies.append(str(r.content)) if False else diagnoses.append(str(r.content))
            if "lie" in c: therapies.append(str(r.content))
            if "lab" in c: labs.append(r)
            if "viz" in c: visits.append(r)

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
# STATIC FRONTEND
# --------------------------------------------------------------------
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/", include_in_schema=False)
def serve_frontend():
    return FileResponse("frontend/index.html")
