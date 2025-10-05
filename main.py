import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, JSON, DateTime, ForeignKey, text
from sqlalchemy.orm import sessionmaker, declarative_base, relationship

app = FastAPI(title="MedAI Backend (safe)")

DATABASE_URL = os.getenv("DATABASE_URL")  # musí byť nastavené v Railway Variables
engine = None
SessionLocal = None
Base = declarative_base()
db_init_error: Optional[str] = None

# ---------- DB MODELS ----------
class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True, index=True)
    patient_uid = Column(String, unique=True, index=True)  # napr. "P001"
    first_name = Column(String)
    last_name = Column(String)
    gender = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    records = relationship("Record", back_populates="patient", cascade="all, delete")

class Record(Base):
    __tablename__ = "records"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"))
    category = Column(String)              # "anamneza","vizita","lab","RTG","EKG","USG","liecba","uvahy"
    timestamp = Column(DateTime)
    content = Column(JSON)
    patient = relationship("Patient", back_populates="records")

class PatientIn(BaseModel):
    patient_uid: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    gender: Optional[str] = None

class RecordIn(BaseModel):
    category: str
    timestamp: datetime
    content: dict

# ---------- LAZY INIT DB (nespadne pri štarte) ----------
def init_db_once():
    global engine, SessionLocal, db_init_error
    if engine is not None:
        return
    try:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set")
        engine = create_engine(
            f"{DATABASE_URL}" + ("" if "sslmode=" in DATABASE_URL else "?sslmode=require"),
            pool_pre_ping=True,
            future=True,
            connect_args={"sslmode": "require"},
        )
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        db_init_error = str(e)

@app.get("/health")
def health():
    # pokus o jednoduchý SELECT; ukáž chybu namiesto crashu
    init_db_once()
    if db_init_error:
        return {"status": "db_error", "detail": db_init_error}
    try:
        with engine.connect() as c:
            c.execute(text("select 1"))
        return {"status": "ok"}
    except Exception as e:
        return {"status": "db_error", "detail": str(e)}

@app.post("/patients")
def create_patient(p: PatientIn):
    init_db_once()
    if db_init_error:
        raise HTTPException(500, f"DB not ready: {db_init_error}")
    with SessionLocal() as s:
        existing = s.query(Patient).filter_by(patient_uid=p.patient_uid).first()
        if existing:
            raise HTTPException(400, "Patient already exists")
        obj = Patient(**p.dict())
        s.add(obj); s.commit(); s.refresh(obj)
        return {"id": obj.id, "patient_uid": obj.patient_uid}

@app.post("/patients/{patient_uid}/records")
def add_record(patient_uid: str, r: RecordIn):
    init_db_once()
    if db_init_error:
        raise HTTPException(500, f"DB not ready: {db_init_error}")
    with SessionLocal() as s:
        pat = s.query(Patient).filter_by(patient_uid=patient_uid).first()
        if not pat:
            raise HTTPException(404, "Patient not found")
        rec = Record(patient_id=pat.id, category=r.category, timestamp=r.timestamp, content=r.content)
        s.add(rec); s.commit(); s.refresh(rec)
        return {"id": rec.id, "category": rec.category, "timestamp": rec.timestamp.isoformat()}

@app.get("/patients/{patient_uid}/records")
def list_records(patient_uid: str):
    init_db_once()
    if db_init_error:
        raise HTTPException(500, f"DB not ready: {db_init_error}")
    with SessionLocal() as s:
        pat = s.query(Patient).filter_by(patient_uid=patient_uid).first()
        if not pat:
            raise HTTPException(404, "Patient not found")
        rows = s.query(Record).filter_by(patient_id=pat.id).order_by(Record.timestamp.asc()).all()
        return [{"id": r.id, "category": r.category, "timestamp": r.timestamp, "content": r.content} for r in rows]
