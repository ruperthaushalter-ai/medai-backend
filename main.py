from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, JSON, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import os

# Získanie URL z Railway variables
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in environment variables")

# 🔒 SSL spojenie k Railway PostgreSQL
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
    connect_args={"sslmode": "require"}
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# ======== MODELY ========
class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(String, unique=True, index=True)
    first_name = Column(String)
    last_name = Column(String)
    gender = Column(String)
    records = relationship("Record", back_populates="patient", cascade="all, delete")

class Record(Base):
    __tablename__ = "records"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"))
    category = Column(String)
    timestamp = Column(DateTime)
    content = Column(JSON)
    patient = relationship("Patient", back_populates="records")

# ======== FASTAPI INIT ========
app = FastAPI(title="MedAI Backend", version="1.0")

Base.metadata.create_all(bind=engine)

# ======== SCHEMY ========
class RecordCreate(BaseModel):
    category: str
    timestamp: datetime
    content: dict

class PatientCreate(BaseModel):
    patient_id: str
    first_name: str
    last_name: str
    gender: str

# ======== ENDPOINTY ========
@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/patients")
def create_patient(patient: PatientCreate):
    db = SessionLocal()
    existing = db.query(Patient).filter_by(patient_id=patient.patient_id).first()
    if existing:
        db.close()
        raise HTTPException(status_code=400, detail="Patient already exists")
    db_patient = Patient(**patient.dict())
    db.add(db_patient)
    db.commit()
    db.refresh(db_patient)
    db.close()
    return db_patient

@app.post("/patients/{patient_id}/records")
def add_record(patient_id: str, record: RecordCreate):
    db = SessionLocal()
    db_patient = db.query(Patient).filter_by(patient_id=patient_id).first()
    if not db_patient:
        db.close()
        raise HTTPException(status_code=404, detail="Patient not found")
    db_record = Record(
        patient_id=db_patient.id,
        category=record.category,
        timestamp=record.timestamp,
        content=record.content
    )
    db.add(db_record)
    db.commit()
    db.refresh(db_record)
    db.close()
    return db_record

@app.get("/patients/{patient_id}/records")
def get_records(patient_id: str):
    db = SessionLocal()
    db_patient = db.query(Patient).filter_by(patient_id=patient_id).first()
    if not db_patient:
        db.close()
        raise HTTPException(status_code=404, detail="Patient not found")
    records = db.query(Record).filter_by(patient_id=db_patient.id).order_by(Record.timestamp.asc()).all()
    db.close()
    return records
