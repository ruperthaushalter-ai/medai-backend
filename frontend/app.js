let selectedPatient=null, latestSummary='', chart=null, allRecords=[], kind="ALL", allPatients=[];

function toggleTheme(){document.body.classList.toggle('dark')}
function markOnline(state){document.getElementById('online').textContent=state?'online':'offline'}

async function ping(){
  try{const r=await fetch('/health'); markOnline(r.ok)}catch{markOnline(false)}
} ping();

function showTab(id){
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  document.querySelector(`.tab[data-tab="${id}"]`).classList.add('active');
  document.querySelectorAll('.tabPane').forEach(x=>x.style.display='none');
  document.getElementById(id).style.display='block';
}

function setKind(k){ kind=k;
  document.querySelectorAll('.sub').forEach(x=>x.classList.remove('active'));
  document.querySelector(`.sub[data-kind="${k}"]`).classList.add('active');
  renderTimeline();
}

function filterPatients(){
  const q=document.getElementById('search').value.trim().toLowerCase();
  renderPatientList(allPatients.filter(p=>{
    const s = `${p.patient_uid} ${p.first_name||''} ${p.last_name||''}`.toLowerCase();
    return s.includes(q);
  }));
}

function renderPatientList(list){
  const box=document.getElementById('patientList'); box.innerHTML='';
  list.forEach(p=>{
    const div=document.createElement('div'); div.className='item';
    div.textContent = `${p.patient_uid} — ${p.first_name||''} ${p.last_name||''}`;
    div.onclick=()=>loadPatient(p.patient_uid);
    box.appendChild(div);
  });
}

async function loadPatients(){
  try{
    const apiKey=document.getElementById('apiKey').value;
    const res=await fetch('/patients',{headers:{'X-API-Key':apiKey}});
    if(!res.ok){throw new Error(await res.text())}
    allPatients=await res.json();
    renderPatientList(allPatients);
  }catch(e){alert('Načítanie pacientov zlyhalo'); console.error(e)}
}

async function createPatient(){
  try{
    const apiKey=document.getElementById('apiKey').value;
    const body={patient_uid:uid.value,first_name:fname.value,last_name:lname.value,gender:gender.value};
    const r=await fetch('/patients',{method:'POST',headers:{'Content-Type':'application/json','X-API-Key':apiKey},body:JSON.stringify(body)});
    if(!r.ok){throw new Error(await r.text())}
    await loadPatients();
  }catch(e){alert('Vytvorenie pacienta zlyhalo'); console.error(e)}
}

async function loadPatient(uid){
  selectedPatient=uid;
  document.getElementById('filterBar').style.display='flex';
  const apiKey=document.getElementById('apiKey').value;

  // AI summary
  const s=await fetch(`/ai/summary/${uid}`,{headers:{'X-API-Key':apiKey}}); const data=await s.json();
  latestSummary=data.discharge_draft || '';
  document.getElementById('summary').innerHTML=`<pre>${latestSummary}</pre>`;
  document.getElementById('therapy').innerHTML=`<pre>${data.diagnoses}</pre>`;
  document.getElementById('statsBox').innerHTML=`<pre>${JSON.stringify(data.stats,null,2)}</pre>`;

  // LAB graf
  if(data.labs && data.labs.length){
    const labels=data.labs.map(l=>new Date(l.time).toLocaleDateString());
    const values=data.labs.map(l=>Number(l.data.value)||0);
    if(chart) chart.destroy();
    chart=new Chart(document.getElementById('labChart'),{
      type:'line',
      data:{labels,datasets:[{label:'CRP / hodnoty LAB',data:values}]},
      options:{responsive:true, scales:{y:{beginAtZero:true}}}
    });
  } else { if(chart) chart.destroy(); }

  // všetky záznamy
  const r=await fetch(`/patients/${uid}/records`,{headers:{'X-API-Key':apiKey}});
  allRecords = r.ok ? await r.json() : [];
  document.getElementById('patientHeader').textContent = `Pacient: ${uid}`;
  renderTimeline();
}

function renderTimeline(){
  const el=document.getElementById('timeline');
  const filt = allRecords.filter(rec=>{
    const c=(rec.category||'').toUpperCase();
    if(kind==='ALL') return true;
    if(kind==='OTHER') return !['LAB','EKG','RTG','VIZITA','DIAG'].some(k=>c.includes(k));
    return c.includes(kind);
  });
  if(filt.length===0){el.innerHTML='<div class="helper">Žiadne záznamy pre vybraný filter.</div>'; return;}

  el.innerHTML = filt.map(rec=>{
    const t = new Date(rec.timestamp).toLocaleString();
    const c = rec.category || '';
    const json = JSON.stringify(rec.content,null,2).replace(/</g,"&lt;");
    return `<div class="item" onclick='openDrawer(${JSON.stringify(json)})'>
              <b>${t}</b> — <i>${c}</i>
            </div>`;
  }).join('');
}

function openDrawer(jsonText){
  const body=document.getElementById('drawerBody');
  body.innerHTML = `<pre>${jsonText}</pre>`;
  document.getElementById('drawer').classList.add('open');
}
function closeDrawer(){document.getElementById('drawer').classList.remove('open')}
async function copyDrawer(){
  const txt=document.getElementById('drawerBody').innerText;
  try{await navigator.clipboard.writeText(txt); alert('Skopírované')}catch{alert('Nedalo sa kopírovať')}
}

function quick(type){
  const c=document.getElementById('content'); const cat=document.getElementById('cat');
  if(type==='LAB'){cat.value='LAB'; c.value='{"test":"CRP","value":0,"unit":"mg/L"}'}
  if(type==='EKG'){cat.value='EKG'; c.value='{"rhythm":"sinus","rate":70,"st":"normal"}'}
  if(type==='RTG'){cat.value='RTG'; c.value='{"modality":"RTG","finding":"bez čerstvých ložísk"}'}
  if(type==='VIZITA'){cat.value='VIZITA'; c.value='{"note":"klinický stav stabilný"}'}
  if(type==='DIAG'){cat.value='DIAG'; c.value='{"dx":"J18.9 Pneumónia"}'}
  if(type==='LIEČBA'){cat.value='LIEČBA'; c.value='{"atb":"amoxicilín","dose":"1g 3x denne"}'}
}

function autoDetectCategory(obj){
  const txt = JSON.stringify(obj).toLowerCase();
  if(/crp|tropon|mmol\/l|mg\/l/.test(txt)) return 'LAB';
  if(/ekg|rhythm|qrs|st"/.test(txt)) return 'EKG';
  if(/rtg|rentgen|x-ray|modality":"rtg/.test(txt)) return 'RTG';
  if(/vizita|klinick/.test(txt)) return 'VIZITA';
  if(/diag|dx":/.test(txt)) return 'DIAG';
  if(/liec|atb|dose|mg/.test(txt)) return 'LIEČBA';
  return 'OTHER';
}

async function addRecord(){
  if(!selectedPatient){alert('Vyber pacienta');return;}
  let obj;
  try{ obj = JSON.parse(document.getElementById('content').value || '{}'); }
  catch{ alert('Neplatný JSON'); return; }

  let category = document.getElementById('cat').value.trim();
  if(document.getElementById('autoCat').checked || !category){
    category = autoDetectCategory(obj);
  }
  const apiKey=document.getElementById('apiKey').value;
  const payload = { category, timestamp:new Date().toISOString(), content:obj };

  const r = await fetch(`/patients/${selectedPatient}/records`,{
    method:'POST', headers:{'Content-Type':'application/json','X-API-Key':apiKey}, body:JSON.stringify(payload)
  });
  if(!r.ok){ alert('Ukladanie zlyhalo'); return; }
  await loadPatient(selectedPatient);
}

function exportPDF(){
  if(!latestSummary){alert('Najprv načítaj AI Summary');return;}
  const el=document.createElement('div');
  el.innerHTML = '<h2>Prepúšťacia správa</h2><pre>'+latestSummary.replace(/</g,"&lt;")+'</pre>';
  html2pdf().from(el).save('discharge_'+(selectedPatient||'patient')+'.pdf');
}
