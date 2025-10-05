from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, JSON, DateTime, ForeignKey, text
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from datetime import datetime, timezone
import os

# ---------- FastAPI ----------
app = FastAPI(title="MedAI Backend", version="1.0.0")

# ---------- Env ----------
DATABASE_URL = os.getenv("DATABASE_URL")
API_KEY = os.getenv("API_KEY")

# ---------- API key guard ----------
def check_key(key: str | None):
    if API_KEY and key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

# ---------- DB init (safe) ----------
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

# ---------- Models ----------
class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True, index=True)
    patient_uid = Column(String, unique=True, index=True)  # napr. P001
    first_name = Column(String)
    last_name = Column(String)
    gender = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    records = relationship("Record", back_populates="patient", cascade="all, delete")

class Record(Base):
    __tablename__ = "records"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"))
    category = Column(String)        # "anamneza", "vizita", "lab", "RTG", "EKG", "USG", "liecba", ...
    timestamp = Column(DateTime)
    content = Column(JSON)           # voľný JSON – text, hodnoty, popisy
    patient = relationship("Patient", back_populates="records")

# ---------- Schemas ----------
class PatientIn(BaseModel):
    patient_uid: str
    first_name: str | None = None
    last_name: str | None = None
    gender: str | None = None

class RecordIn(BaseModel):
    category: str
    timestamp: datetime
    content: dict

# ---------- Core endpoints ----------
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

# ---------- Heuristická „AI“: summary + draft prepúšťacej ----------
def _fmt_ts(dt: datetime) -> str:
    try:
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(dt)

def _heuristic_summary(pat: Patient, recs: list[Record]) -> dict:
    lines = []
    lines.append(f"Pacient: {pat.first_name or ''} {pat.last_name or ''} ({pat.patient_uid})")
    lines.append(f"Pohlavie: {pat.gender or 'neuvedené'}")
    lines.append("")
    lines.append("Chronologický priebeh:")

    diagnoses_block = []
    last_treatments = []
    last_vitals = []

    for r in recs:
        ts = _fmt_ts(r.timestamp)
        cat = (r.category or "").upper()

        if cat == "LAB":
            t = r.content.get("test", "?")
            v = r.content.get("value", "?")
            u = r.content.get("unit", "")
            lines.append(f" - {ts} LAB: {t} = {v} {u}")
            # pár jednoduchých pravidiel
            try:
                if t.upper() == "CRP" and float(v) >= 100:
                    lines.append("   ↳ výrazne zvýšené CRP – suspekcia na infekciu")
            except Exception:
                pass

        elif cat in ("RTG", "EKG", "USG", "CT", "MRI"):
            finding = r.content.get("finding") or r.content.get("popis") or "(pozri záznam)"
            lines.append(f" - {ts} {cat}: {finding}")

        elif cat in ("ANAMNEZA", "ANAMNÉZA"):
            snippet = (r.content.get("text") or str(r.content))[:180].replace("\n", " ")
            lines.append(f" - {ts} Anamnéza: {snippet}")

        elif cat in ("VIZITA", "PRIEBEH"):
            snippet = (r.content.get("text") or r.content.get("note") or str(r.content))[:180].replace("\n", " ")
            lines.append(f" - {ts} Vizita: {snippet}")

        elif cat in ("DIAGNOZA", "DIAGNÓZA", "DX"):
            dx = r.content.get("text") or r.content.get("dx") or str(r.content)
            diagnoses_block.append(dx)
            lines.append(f" - {ts} Diagnóza: {dx}")

        elif cat in ("LIECBA", "LIEČBA", "THERAPY"):
            therapy = r.content.get("text") or r.content.get("schema") or str(r.content)
            last_treatments.append(therapy)
            lines.append(f" - {ts} Liečba: {therapy}")

        elif cat in ("VITALS", "FYZIKAL", "FYZIKÁL"):
            vit = r.content.get("text") or str(r.content)
            last_vitals.append(vit)
            lines.append(f" - {ts} Fyzikálne: {vit}")

        else:
            snippet = (r.content.get("text") or r.content.get("note") or str(r.content))[:180].replace("\n", " ")
            lines.append(f" - {ts} {r.category}: {snippet}")

    # blok diagnóz
    diag_text = "• " + "\n• ".join(dict.fromkeys(diagnoses_block)) if diagnoses_block else "— (diagnózy nešpecifikované v záznamoch)"

    # krátka predstavačka (mini-epikríza)
    intro = f"{pat.first_name or ''} {pat.last_name or ''} ({pat.patient_uid}) – hospitalizovaný/á, priebeh a kľúčové udalosti v časovej osi nižšie."

    # draft prepúšťacej
    discharge = [
        "PREPÚŠŤACIA SPRÁVA – NÁVRH (MVP)",
        "",
        "I. Diagnóza:",
        diag_text,
        "",
        "II. Priebeh hospitalizácie:",
        *[l for l in lines if l.startswith(" - ")],
        "",
        "III. Vyšetrenia: pozri zoznam vyššie (RTG/EKG/USG/LAB).",
        "",
        "IV. Liečba:",
        ("• " + "\n• ".join(last_treatments)) if last_treatments else "— podľa ordinácie v záznamoch",
        "",
        "V. Stav pri prepustení:",
        (last_vitals[-1] if last_vitals else "klinicky stabilizovaný/á, podľa aktuálneho vyšetrenia"),
        "",
        "VI. Odporúčania:",
        "• pokračovať v liečbe podľa ordinácie",
        "• kontrola v príslušnej ambulancii/oddelení",
        "• podľa klinického stavu skôr",
    ]
    return {
        "diagnoses": diag_text,
        "intro": intro,
        "timeline": "\n".join(lines),
        "discharge_draft": "\n".join(discharge),
    }

@app.get("/ai/summary/{patient_uid}")
def ai_summary(patient_uid: str, x_api_key: str | None = Header(default=None)):
    """
    Heuristický sumár: bez externého AI – pravidlá a šablóny nad uloženými záznamami.
    Vráti blok diagnóz, krátku predstavačku, chronologickú epikrízu a draft prepúšťacej správy.
    """
    check_key(x_api_key)
    init_db_once()
    if db_init_error:
        raise HTTPException(500, f"DB not ready: {db_init_error}")

    with SessionLocal() as s:
        pat = s.query(Patient).filter_by(patient_uid=patient_uid).first()
        if not pat:
            raise HTTPException(404, "Patient not found")
        recs = (
            s.query(Record)
             .filter_by(patient_id=pat.id)
             .order_by(Record.timestamp.asc())
             .all()
        )
    return _heuristic_summary(pat, recs)
