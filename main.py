from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from typing import List
import os

# === KONFIGURÁCIA ===
app = FastAPI(title="MedAI 3.1 – Login + Workflow")

SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# === DATABÁZY V PAMÄTI ===
users_db = {}
patients_db = []

# === MODELY ===
class User(BaseModel):
    username: str
    full_name: str | None = None
    hashed_password: str
    role: str = "doctor"

class UserIn(BaseModel):
    username: str
    password: str
    full_name: str | None = None

class Patient(BaseModel):
    id: int
    first_name: str
    last_name: str
    admission_date: str
    discharge_date: str | None = None
    status: str = "hospitalized"
    assigned_to: str | None = None  # lekár

# === AUTENTIFIKÁCIA ===
def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_user(username: str):
    return users_db.get(username)

def authenticate_user(username: str, password: str):
    user = get_user(username)
    if not user or not verify_password(password, user.hashed_password):
        return False
    return user

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = get_user(username)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# === ENDPOINTY PRE LOGIN ===
@app.post("/register")
def register(user: UserIn):
    if user.username in users_db:
        raise HTTPException(400, "User already exists")
    hashed = get_password_hash(user.password)
    new_user = User(username=user.username, full_name=user.full_name, hashed_password=hashed)
    users_db[user.username] = new_user
    return {"status": "registered", "username": user.username}

@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(401, "Incorrect username or password")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.username}, expires_delta=access_token_expires)
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/me")
def read_me(current_user: User = Depends(get_current_user)):
    return {"username": current_user.username, "role": current_user.role}

# === PACIENTI (WORKFLOW) ===
@app.get("/patients", response_model=List[Patient])
def get_patients(current_user: User = Depends(get_current_user)):
    return [p for p in patients_db if p.assigned_to == current_user.username]

@app.post("/patients")
def add_patient(first_name: str, last_name: str, current_user: User = Depends(get_current_user)):
    new_id = len(patients_db) + 1
    new_patient = Patient(
        id=new_id,
        first_name=first_name,
        last_name=last_name,
        admission_date=datetime.utcnow().strftime("%Y-%m-%d"),
        assigned_to=current_user.username,
    )
    patients_db.append(new_patient)
    return {"status": "added", "patient": new_patient}

@app.post("/patients/{pid}/discharge")
def discharge_patient(pid: int, current_user: User = Depends(get_current_user)):
    patient = next((p for p in patients_db if p.id == pid and p.assigned_to == current_user.username), None)
    if not patient:
        raise HTTPException(404, "Patient not found or not yours")
    patient.status = "discharged"
    patient.discharge_date = datetime.utcnow().strftime("%Y-%m-%d")
    return {"status": "discharged", "patient": patient}

# === MINI UI ===
@app.get("/")
def ui():
    return """
    <html>
    <head>
        <title>MedAI Dashboard</title>
        <style>
        body{font-family:Arial;background:#f5f6fa;margin:0;padding:20px;}
        .card{background:white;padding:20px;border-radius:10px;box-shadow:0 2px 4px rgba(0,0,0,0.1);margin-bottom:15px;}
        input{padding:6px;margin:4px;}
        button{background:#1e4e9a;color:white;border:none;padding:6px 10px;border-radius:4px;cursor:pointer;}
        table{width:100%;border-collapse:collapse;}
        th,td{border-bottom:1px solid #ddd;padding:8px;text-align:left;}
        </style>
    </head>
    <body>
    <h2>🏥 MedAI 3.1 – Oddelenie</h2>
    <div>
        <input id="username" placeholder="Používateľ">
        <input id="password" type="password" placeholder="Heslo">
        <button onclick="login()">Prihlásiť</button>
        <button onclick="me()">Kto som?</button>
    </div>
    <div class="card">
        <h3>Pacienti</h3>
        <button onclick="loadPatients()">Načítať</button>
        <input id="fname" placeholder="Meno">
        <input id="lname" placeholder="Priezvisko">
        <button onclick="addPatient()">Pridať pacienta</button>
        <div id="patients"></div>
    </div>
    <script>
    async function login(){
        const formData=new URLSearchParams();
        formData.append("username",document.getElementById("username").value);
        formData.append("password",document.getElementById("password").value);
        const res=await fetch("/login",{method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded"},body:formData});
        const data=await res.json();
        localStorage.setItem("token",data.access_token);
        alert("✅ Prihlásenie OK");
    }
    async function me(){
        const token=localStorage.getItem("token");
        const res=await fetch("/me",{headers:{"Authorization":"Bearer "+token}});
        alert(await res.text());
    }
    async function loadPatients(){
        const token=localStorage.getItem("token");
        const res=await fetch("/patients",{headers:{"Authorization":"Bearer "+token}});
        const data=await res.json();
        let html="<table><tr><th>ID</th><th>Meno</th><th>Priezvisko</th><th>Status</th><th>Akcia</th></tr>";
        data.forEach(p=>{
            html+=`<tr><td>${p.id}</td><td>${p.first_name}</td><td>${p.last_name}</td><td>${p.status}</td>
            <td>${p.status=="hospitalized"?'<button onclick="discharge('+p.id+')">Prepustiť</button>':'-'}</td></tr>`;
        });
        html+="</table>";
        document.getElementById("patients").innerHTML=html;
    }
    async function addPatient(){
        const token=localStorage.getItem("token");
        const fname=document.getElementById("fname").value;
        const lname=document.getElementById("lname").value;
        await fetch(`/patients?first_name=${fname}&last_name=${lname}`,{method:"POST",headers:{"Authorization":"Bearer "+token}});
        loadPatients();
    }
    async function discharge(id){
        const token=localStorage.getItem("token");
        await fetch(`/patients/${id}/discharge`,{method:"POST",headers:{"Authorization":"Bearer "+token}});
        loadPatients();
    }
    </script>
    </body>
    </html>
    """
