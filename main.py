@app.get("/", response_class=HTMLResponse)
def ui_dashboard():
    return """
    <html>
    <head>
        <title>MedAI Dashboard 2.1</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            :root {
                --bg: #f2f4f8;
                --text: #111;
                --card: #fff;
                --accent: #1e4e9a;
                --border: #ccc;
            }
            body.dark {
                --bg: #121212;
                --text: #e0e0e0;
                --card: #1f1f1f;
                --accent: #4a90e2;
                --border: #333;
            }
            body { font-family: 'Inter', sans-serif; margin: 0; background: var(--bg); color: var(--text); transition: all 0.3s ease; }
            header { background: var(--accent); color: white; padding: 12px 18px; display: flex; justify-content: space-between; align-items: center; }
            h1 { margin: 0; font-size: 22px; }
            .container { display: flex; flex-wrap: wrap; padding: 10px; }
            .sidebar { flex: 1; min-width: 260px; background: var(--card); margin: 10px; padding: 10px; border-radius: 8px; height: 88vh; overflow-y: auto; border: 1px solid var(--border); }
            .main { flex: 3; min-width: 300px; background: var(--card); margin: 10px; padding: 15px; border-radius: 8px; border: 1px solid var(--border); }
            button { background: var(--accent); color: white; border: none; padding: 8px 12px; border-radius: 6px; cursor: pointer; margin-top: 5px; }
            button:hover { opacity: 0.9; }
            input, textarea, select { width: 100%; margin: 4px 0; padding: 6px; border: 1px solid var(--border); border-radius: 4px; background: var(--card); color: var(--text); }
            .patient-item { padding: 8px; border-bottom: 1px solid var(--border); cursor: pointer; }
            .patient-item:hover { background: rgba(0,0,0,0.05); }
            pre { white-space: pre-wrap; background: #0001; padding: 10px; border-radius: 6px; color: var(--text); }
            .tabs { display: flex; gap: 10px; margin-bottom: 10px; }
            .tab { flex: 1; text-align: center; background: #e4e8ef; padding: 8px; border-radius: 6px; cursor: pointer; transition: 0.3s; }
            body.dark .tab { background: #333; }
            .tab.active { background: var(--accent); color: white; }
            #pdfBtn { float: right; margin-top: -5px; }
            ::-webkit-scrollbar { width: 6px; } 
            ::-webkit-scrollbar-thumb { background: #888; border-radius: 3px; }
        </style>
    </head>
    <body>
        <header>
            <h1>🩺 MedAI Dashboard 2.1</h1>
            <div>
                <button onclick="toggleDark()">🌙 Režim</button>
            </div>
        </header>

        <div class="container">
            <div class="sidebar">
                <h3>Pacienti</h3>
                <input id="apiKey" placeholder="API Key" style="width:100%; margin-bottom:5px;">
                <button onclick="loadPatients()">Načítať pacientov</button>
                <div id="patientList"></div>

                <hr>
                <h4>Nový pacient</h4>
                <input id="uid" placeholder="UID (napr. P003)">
                <input id="fname" placeholder="Meno">
                <input id="lname" placeholder="Priezvisko">
                <select id="gender"><option value="M">M</option><option value="F">F</option></select>
                <button onclick="createPatient()">Vytvoriť</button>
            </div>

            <div class="main">
                <div class="tabs">
                    <div class="tab active" onclick="showTab('timeline')">📆 Priebeh</div>
                    <div class="tab" onclick="showTab('summary')">🧠 AI Summary</div>
                    <div class="tab" onclick="showTab('therapy')">💊 Liečba</div>
                </div>

                <button id="pdfBtn" onclick="exportPDF()">📄 Exportovať PDF</button>

                <div id="timeline" class="tabContent"></div>
                <div id="summary" class="tabContent" style="display:none;"></div>
                <div id="therapy" class="tabContent" style="display:none;"></div>

                <hr>
                <h4>Pridaj záznam</h4>
                <input id="cat" placeholder="Kategória (napr. LAB, RTG, vizita...)">
                <textarea id="content" placeholder='Obsah JSON, napr. {"test":"CRP","value":120,"unit":"mg/L"}'></textarea>
                <button onclick="addRecord()">Pridať záznam</button>
            </div>
        </div>

        <script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
        <script>
        let selectedPatient = null;
        let latestSummary = '';

        function toggleDark(){
            document.body.classList.toggle('dark');
        }

        function showTab(id){
            document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
            document.querySelectorAll('.tabContent').forEach(c=>c.style.display='none');
            document.querySelector(`.tab[onclick="showTab('${id}')"]`).classList.add('active');
            document.getElementById(id).style.display='block';
        }

        async function loadPatients(){
            const apiKey = document.getElementById('apiKey').value;
            const res = await fetch('/patients', { headers: { 'X-API-Key': apiKey }});
            const data = await res.json();
            const list = document.getElementById('patientList');
            list.innerHTML = '';
            data.forEach(p=>{
                const div = document.createElement('div');
                div.className='patient-item';
                div.textContent = `${p.patient_uid} - ${p.first_name||''} ${p.last_name||''}`;
                div.onclick = ()=>loadPatient(p.patient_uid);
                list.appendChild(div);
            });
        }

        async function createPatient(){
            const apiKey = document.getElementById('apiKey').value;
            const body = {
                patient_uid: document.getElementById('uid').value,
                first_name: document.getElementById('fname').value,
                last_name: document.getElementById('lname').value,
                gender: document.getElementById('gender').value
            };
            await fetch('/patients', { method:'POST', headers:{'Content-Type':'application/json','X-API-Key':apiKey}, body:JSON.stringify(body)});
            loadPatients();
        }

        async function loadPatient(uid){
            selectedPatient = uid;
            const apiKey = document.getElementById('apiKey').value;
            const res = await fetch(`/patients/${uid}/records`, { headers:{'X-API-Key':apiKey} });
            const data = await res.json();
            let html = '';
            let therapyList = [];
            data.forEach(r=>{
                const time = new Date(r.timestamp).toLocaleString();
                html += `<b>${r.category}</b> (${time})<br>${JSON.stringify(r.content)}<hr>`;
                if(r.category.toLowerCase().includes('lieč')){
                    therapyList.push(JSON.stringify(r.content));
                }
            });
            document.getElementById('timeline').innerHTML = html || 'Žiadne záznamy';
            document.getElementById('therapy').innerHTML = therapyList.join('<br>') || 'Žiadna liečba';
            const ai = await fetch(`/ai/summary/${uid}`, { headers:{'X-API-Key':apiKey}});
            const sum = await ai.json();
            latestSummary = sum.discharge_draft;
            document.getElementById('summary').innerHTML = `<pre>${latestSummary}</pre>`;
        }

        async function addRecord(){
            if(!selectedPatient){alert('Vyber pacienta.');return;}
            const apiKey = document.getElementById('apiKey').value;
            const cat = document.getElementById('cat').value;
            let content;
            try{ content = JSON.parse(document.getElementById('content').value); }catch{ alert('Neplatný JSON'); return; }
            await fetch(`/patients/${selectedPatient}/records`, {
                method:'POST',
                headers:{'Content-Type':'application/json','X-API-Key':apiKey},
                body:JSON.stringify({ category:cat, timestamp:new Date().toISOString(), content:content })
            });
            loadPatient(selectedPatient);
        }

        function exportPDF(){
            if(!latestSummary){alert('Najprv načítaj AI summary');return;}
            const element = document.createElement('div');
            element.innerHTML = `<h2>Prepúšťacia správa</h2><pre>${latestSummary}</pre>`;
            html2pdf().from(element).save(`discharge_${selectedPatient}.pdf`);
        }
        </script>
    </body>
    </html>
    """
