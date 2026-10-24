"use strict";
const $ = (s) => document.querySelector(s);
const chat = $("#chat"), mem = $("#mem"), feed = $("#feed"), feedwrap = $("#feedwrap");
let sid = null, mode = "off";

const HINTS = {
  off: "OFF: the agent's memory is undefended — try to poison or extract it.",
  on: "ON: the full Memory Checks defence — authority, walls, erasure, source-counting.",
  paranoid: "Strict: an over-cautious defence. Safe, but watch it refuse even valid policy.",
};

function esc(s){return (s||"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}

function addMsg(role, text, who){
  const d = document.createElement("div");
  d.className = "msg " + (role === "user" ? "user" : "bot");
  const av = role === "user" ? "🧑" : "🐐";
  d.innerHTML = `<div class="av">${av}</div><div class="bubble"><div class="who">${who||(role==="user"?"You":"Sahayak")}</div>${esc(text)}</div>`;
  chat.appendChild(d); chat.scrollTop = chat.scrollHeight;
  return d;
}
function addSys(text){
  const d = document.createElement("div");
  d.className = "sys"; d.innerHTML = `<span class="pill">${esc(text)}</span>`;
  chat.appendChild(d); chat.scrollTop = chat.scrollHeight;
}

function renderMem(items){
  mem.innerHTML = "";
  if(!items || !items.length){ mem.innerHTML = `<div class="empty">No memories stored yet.</div>`; return; }
  for(const it of items){
    const d = document.createElement("div");
    d.className = "mi " + (it.status||"active");
    d.innerHTML = `<div class="t">${esc(it.text)}</div>
      <div class="meta"><span class="tag">${esc(it.type)}</span>
        <span class="tag">src: ${esc(it.source)}</span>
        <span class="tag ${esc(it.status)}">${esc(it.status)}</span></div>`;
    mem.appendChild(d);
  }
}
function renderFeed(events){
  if(mode === "off" || !events || !events.length){ feedwrap.style.display = "none"; return; }
  feedwrap.style.display = "block"; feed.innerHTML = "";
  for(const e of events.slice(-6)){
    const cls = e.decision === "write" ? "write" : (e.decision === "no" ? "no" : "probation");
    const verb = e.decision === "write" ? "stored" : (e.decision === "no" ? "blocked" : "probation");
    const d = document.createElement("div");
    d.className = "fe " + cls;
    d.innerHTML = `<span class="d">${verb}</span>${esc(e.source)} → ${esc(e.type)}`;
    feed.appendChild(d);
  }
}

async function post(url, body){
  const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  return r.json();
}

async function newSession(){
  const r = await post("/api/session", {checks:mode, user_id:$("#user").value||"ramesh", pincode:$("#pin").value||"560012"});
  sid = r.sid; renderMem(r.memory); feedwrap.style.display = "none";
  chat.innerHTML = "";
  addSys(`New session · Memory Checks ${mode.toUpperCase()}`);
  addMsg("bot", "Namaste! I'm Sahayak. I can help you apply for or update your Aadhaar. You can type or tap the mic and speak in your own language.");
}

function setMode(m){
  mode = m;
  document.querySelectorAll("#switch button").forEach(b => b.classList.toggle("on", b.dataset.m === m));
  $("#checkhint").textContent = HINTS[m];
  newSession();
}

async function send(){
  const box = $("#box"); const text = box.value.trim(); if(!text || !sid) return;
  box.value = ""; box.style.height = "auto";
  addMsg("user", text);
  const typing = addMsg("bot", "…");
  try{
    const r = await post("/api/chat", {sid, message:text, agent:"intake"});
    typing.remove();
    addMsg("bot", r.reply || "(no reply)");
    if(r.event && r.event.kind === "forget"){
      addSys(r.event.removed ? `🧹 erased ${r.event.removed} saved detail(s) — hard delete, with a signed receipt` : "nothing matched to erase");
    }
    renderMem(r.memory); renderFeed(r.checks);
    speak(r.reply);
  }catch(e){ typing.remove(); addMsg("bot", "⚠ error reaching Sahayak."); }
}

// ---- other actions
async function doAction(url, body, okMsg){
  if(!sid) return;
  const r = await post(url, {sid, ...body});
  if(r.decision){ addSys(`Application decision: ${r.decision.approved ? "✅ APPROVED" : "⛔ REJECTED"} — ${r.decision.reason||""}`); }
  else if(okMsg){ addSys(okMsg); }
  renderMem(r.memory); renderFeed(r.checks);
}

// ---- voice (Sarvam)
let rec = null, chunks = [];
async function toggleMic(){
  const mic = $("#mic");
  if(rec && rec.state === "recording"){ rec.stop(); return; }
  try{
    const stream = await navigator.mediaDevices.getUserMedia({audio:true});
    rec = new MediaRecorder(stream); chunks = [];
    rec.ondataavailable = e => chunks.push(e.data);
    rec.onstop = async () => {
      mic.classList.remove("rec"); stream.getTracks().forEach(t=>t.stop());
      const blob = new Blob(chunks, {type:"audio/wav"});
      const fd = new FormData(); fd.append("file", blob, "audio.wav");
      addSys("🎙 transcribing…");
      try{
        const r = await fetch("/api/voice/stt?sid="+sid, {method:"POST", body:fd}).then(x=>x.json());
        if(r.transcript){ $("#box").value = r.transcript; send(); }
        else addSys("voice unavailable: " + (r.error||"no transcript"));
      }catch(e){ addSys("voice error"); }
    };
    rec.start(); mic.classList.add("rec");
  }catch(e){ addSys("🎙 mic blocked or unavailable in this browser"); }
}
async function speak(text){
  if(!text) return;
  try{
    const r = await post("/api/voice/tts", {text});
    if(r.audio_b64){ const p = $("#player"); p.src = "data:audio/wav;base64,"+r.audio_b64; p.play().catch(()=>{}); }
  }catch(e){}
}

// ---- wire up
document.querySelectorAll("#switch button").forEach(b => b.onclick = () => setMode(b.dataset.m));
$("#send").onclick = send;
$("#mic").onclick = toggleMic;
$("#box").addEventListener("keydown", e => { if(e.key === "Enter" && !e.shiftKey){ e.preventDefault(); send(); }});
$("#box").addEventListener("input", e => { e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight,140)+"px"; });
$("#btnUpload").onclick = () => doAction("/api/upload", {text:$("#docText").value}, "📄 document uploaded");
$("#btnPolicy").onclick = () => doAction("/api/policy", {text:$("#polText").value}, "🏛 signed UIDAI policy published");
$("#btnApply").onclick = () => doAction("/api/apply", {has_address_proof:false});
$("#user").onchange = newSession; $("#pin").onchange = newSession;
setMode("off");
