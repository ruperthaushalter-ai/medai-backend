import os
from datetime import datetime, date
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text, String, Date, DateTime, JSON, ForeignKey
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column

# ---- ENV ----
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # Railway nastavíme env premennú, ale nech to nezlyhá pri /docs build-e
    DATABASE_URL = "postgresql://postgres:password@localhost:5432/railway"  # placeholder

# ---- DB SETUP ----
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

# ---- MODELS ----
class Patient(Base):
    __tablename__ = "patients"
    patient_id: Mapped[str] = mapped_column(String, primary_key=True)
    first_name: Mapped[Optional[str]] = mapped_column(String)
    last_name: Mapped[Optional[str]] = mapped_column(String)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date)
    gender: Mapped[Optional[str]] = mapped_column(String)
    allergies: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Record(Base):
    __tablename__ = "records"
    record_id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id"), index=True)
    category: Mapped[str] = mapped_column(String)  # "anamneza","vizita","lab","RTG","EKG","USG","liecba","uvahy"
    content: Mapped[dict] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    created_by: Mapped[Optional[str]] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ai_processed: Mapped[bool] = mapped_column(default=False)

class Diagnosis(Base):
    __tablename__ = "diagnoses"
    diagnosis_id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id"), index=True)
    name: Mapped[Optional[str]] = mapped_column(String)
    status: Mapped[Optional[str]] = mapped_column(String)  # "aktivna" / "vyriesena"
    icd_code: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Treatment(Base):
    __tablename__ = "treatment"
    treatment_id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id"), index=True)
    medication: Mapped[Optional[str]] = mapped_column(String)
    dose: Mapped[Optional[str]] = mapped_column(String)
    route: Mapped[Optional[str]] = mapped_column(String)
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    notes: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

# ---- SCHEMAS ----
class PatientIn(BaseModel):
    patient_id: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    allergies: Optional[str] = None

class PatientOut(PatientIn):
    created_at: datetime
    updated_at: datetime

Category = Literal["anamneza","klinicke_vysetrenie","vizita","lab","RTG","EKG","USG","liecba","uvahy","ai_summary"]

class RecordIn(BaseModel):
    category: Category
    content: dict
    timestamp: datetime
    created_by: Optional[str] = None

class RecordOut(RecordIn):
    record_id: str
    updated_at: datetime
    ai_processed: bool

# ---- APP ----
app = FastAPI(title="MedAI MVP API")

@app.on_event("startup")
def on_startup():
    try:
        Base.metadata.create_all(engine)
    except Exception as e:
        print("DB init warning:", e)

@app.get("/health")
def health():
    try:
        with engine.connect() as c:
            c.execute(text("select 1"))
        return {"status": "ok"}
    except Exception as e:
        return {"status": "db_error", "detail": str(e)}

@app.post("/patients", response_model=PatientOut)
def create_patient(p: PatientIn):
    with SessionLocal() as s:
        if s.get(Patient, p.patient_id):
            raise HTTPException(400, "patient_id already exists")
        obj = Patient(
            patient_id=p.patient_id,
            first_name=p.first_name,
            last_name=p.last_name,
            date_of_birth=p.date_of_birth,
            gender=p.gender,
            allergies=p.allergies,
        )
        s.add(obj); s.commit(); s.refresh(obj)
        return obj

@app.get("/patients/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: str):
    with SessionLocal() as s:
        obj = s.get(Patient, patient_id)
        if not obj:
            raise HTTPException(404, "patient not found")
        return obj

@app.post("/patients/{patient_id}/records", response_model=RecordOut)
def add_record(patient_id: str, r: RecordIn):
    with SessionLocal() as s:
        if not s.get(Patient, patient_id):
            raise HTTPException(404, "patient not found")
        rec_id = f"rec_{int(datetime.utcnow().timestamp()*1000)}"
        obj = Record(
            record_id=rec_id, patient_id=patient_id,
            category=r.category, content=r.content,
            timestamp=r.timestamp, created_by=r.created_by
        )
        s.add(obj); s.commit(); s.refresh(obj)
        return obj

@app.get("/patients/{patient_id}/records")
def list_records(patient_id: str, category: Optional[str] = None):
    with SessionLocal() as s:
        q = s.query(Record).filter(Record.patient_id == patient_id)
        if category:
            q = q.filter(Record.category == category)
        q = q.order_by(Record.timestamp.asc())
        return [
            {"record_id": r.record_id, "category": r.category,
             "timestamp": r.timestamp, "content": r.content,
             "ai_processed": r.ai_processed}
            for r in q.all()
        ]
