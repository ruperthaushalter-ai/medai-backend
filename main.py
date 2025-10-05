from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, JSON, DateTime, ForeignKey, text
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from datetime import datetime
import os

# ---------- FastAPI inicializácia ----------
app = FastAPI(title="MedAI Backend")

# ---------- Premenné prostredia ----------
DATABASE_URL = os.getenv("DATABASE_URL")
API_KEY = os.getenv("API_KEY")

# ---------- Kontrola API kľúča ----------
def check_key(key: str | None):
    if API_KEY and key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

# ---------- Databázová inicializácia ----------
Base = declarative_base()
engine = None
SessionLocal = None
db_init_error = None

def init_db_once():
    global engine, SessionLocal, db_init_error
    if engine is not None:
        return
    try:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL not set")
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

# ---------- Modely ----------
class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True, index=True)
    patient_uid = Column(String, unique=True, index=True)
    first_name = Column(String)
    last_name = Column(String)
    gender = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    records = relationship("Record", back_populates="patient", cascade="all, delete")

class Record(Base):
    __tablename__ = "records"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"))
    category = Column(String)
    timestamp = Column(DateTime)
    content = Column(JSON)
    patient = relationship("Patient", back_populates="records")

# ---------- Pydantic modely ----------
class PatientIn(BaseModel):
    patient_uid: str
    first_name: str | None = None
    last_name: str | None = None
    gender: str | None = None

class RecordIn(BaseModel):
    category: str
    timestamp: datetime
    content: dict

# ---------- Endpointy ----------
@app.get("/health")
def health():
    init_db_once()
    if db_init_error:
        return {"status": "db_error", "detail": db_init_error}
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        return {"status": "db_error", "detail": str(e)}

@app.post("/patients")
def create_patient(p: PatientIn, x_api_key: str | None = Header(default=None)):
    check_key(x_api_key)
    init_db_once()
    if db_init_error:
        raise HTTPException(500, f"DB not ready: {db_init_error}")
    with SessionLocal() as s:
        existing = s.query(Patient).filter_by(patient_uid=p.patient_uid).first()
        if existing:
            raise HTTPException(400, "Patient already exists")
        obj = Patient(**p.dict())
        s.add(obj)
        s.commit()
        s.refresh(obj)
        return {"id": obj.id, "patient_uid": obj.patient_uid}

@app.post("/patients/{patient_uid}/records")
def add_record(patient_uid: str, r: RecordIn, x_api_key: str | None = Header(default=None)):
    check_key(x_api_key)
    init_db_once()
    if db_init_error:
        raise HTTPException(500, f"DB not ready: {db_init_error}")
    with SessionLocal() as s:
        pat = s.query(Patient).filter_by(patient_uid=patient_uid).first()
        if not pat:
            raise HTTPException(404, "Patient not found")
        rec = Record(patient_id=pat.id, category=r.category, timestamp=r.timestamp, content=r.content)
        s.add(rec)
        s.commit()
        s.refresh(rec)
        return {"id": rec.id, "category": rec.category, "timestamp": rec.timestamp.isoformat()}

@app.get("/patients/{patient_uid}/records")
def list_records(patient_uid: str, x_api_key: str | None = Header(default=None)):
    check_key(x_api_key)
    init_db_once()
    if db_init_error:
        raise HTTPException(500, f"DB not ready: {db_init_error}")
    with SessionLocal() as s:
        pat = s.query(Patient).filter_by(patient_uid=patient_uid).first()
        if not pat:
            raise HTTPException(404, "Patient not found")
        rows = s.query(Record).filter_by(patient_id=pat.id).order_by(Record.timestamp.asc()).all()
        return [{"id": r.id, "category": r.category, "timestamp": r.timestamp, "content": r.content} for r in rows]
