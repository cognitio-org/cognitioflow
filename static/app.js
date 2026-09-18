// CognitioFlow app script. Moved out of static/index.html unchanged so the page
// drops under the swarm's 800-line edit limit and free models can maintain it.
// Nothing here was rewritten: render() -> chipify() -> priomark() are byte-identical.
const $=s=>document.querySelector(s); const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const api=async(p,o={})=>{const r=await fetch('/api'+p,o); if(!r.ok){let m=r.statusText; try{m=(await r.json()).detail||m}catch{} throw new Error(m)} return r.json()};
const post=(p,b)=>api(p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});
const put=(p,b)=>api(p,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
const del=p=>api(p,{method:'DELETE'});
/* ---- ⌘K palette + search ---- */
let palItems=[], palSel=0, palT=null;
const PAL_SCREENS=[['home','Overview'],['library','Files'],['tutor','Tutor'],['notes','Notes'],['recall','Recall'],['advocate','Advocate'],['arena','Arena'],['planner','Planner'],['progress','Progress']];
/* The palette is role="dialog" over a dimmed page, but nothing held focus inside it: one Tab walked
   out to #focusBtn, the sidebar and the nav behind the dim, and Escape was bound on #palQ alone, so
   once focus left there was no keyboard way back out at all. The 3D player already solves this
   properly a few hundred lines down — same inert list, same document-level Escape — so reuse it
   rather than inventing a second pattern. */
const palBehind=on=>['.app','#focusBtn','#timer'].forEach(sel=>{ const el=document.querySelector(sel); if(el) el.inert=on; });
let palOpener=null;
function openPal(){ palOpener=document.activeElement;
  $('#pal').hidden=false; $('#pal').setAttribute('aria-modal','true'); palBehind(true);
  $('#palQ').value=''; $('#palQ').placeholder='Search notes, files, chats, cards — or type a screen name'; palRender([]); setTimeout(()=>$('#palQ').focus(),0) }
function closePal(){ $('#pal').hidden=true; $('#pal').removeAttribute('aria-modal'); palBehind(false);
  // Put focus back where it came from, rather than dropping it on <body>
  if(palOpener && document.contains(palOpener)) palOpener.focus();
  palOpener=null; }
function palRender(items){ palItems=items; palSel=0; $('#palList').innerHTML=items.length?items.map((it,i)=>`<li class="${i===0?'sel':''}" data-i="${i}"><span class="k">${it.kind}</span><span class="t">${esc(it.title)}</span>${it.snippet?`<span class="s">${esc(it.snippet)}</span>`:''}</li>`).join(''):'<li class="muted small" style="display:block">Type to search this course.</li>';
  document.querySelectorAll('#palList li[data-i]').forEach(li=>{li.onmouseenter=()=>{palSel=+li.dataset.i;palPaint()}; li.onclick=()=>palGo(+li.dataset.i)}) }
function palPaint(){ document.querySelectorAll('#palList li[data-i]').forEach(li=>li.classList.toggle('sel',+li.dataset.i===palSel)); const el=document.querySelector('#palList li.sel'); el&&el.scrollIntoView({block:'nearest'}) }
async function palSearch(q){ const ql=q.toLowerCase(); const screens=PAL_SCREENS.filter(([id,n])=>!ql||n.toLowerCase().startsWith(ql)).map(([id,n])=>({kind:'screen',id,title:n}));
  if(ql.length<2){ palRender(screens); return } let hits=[]; try{ hits=await api(`/courses/${cid}/search?q=${encodeURIComponent(q)}`) }catch{} palRender([...screens,...hits]) }
async function palGo(i){ const it=palItems[i]; if(!it) return; closePal();
  if(it.kind==='version'){ previewVersion(it.id); return } if(it.kind==='screen') show(it.id); else if(it.kind==='note'){ nid=it.id; noteMode='read'; show('notes') } else if(it.kind==='file'){ show('library') } else if(it.kind==='chat'){ show('tutor') } else if(it.kind==='card'){ show('recall') } }
$('#palQ').addEventListener('input',e=>{ clearTimeout(palT); palT=setTimeout(()=>palSearch(e.target.value),140) });
$('#palQ').addEventListener('keydown',e=>{ if(e.key==='ArrowDown'){e.preventDefault();palSel=Math.min(palItems.length-1,palSel+1);palPaint()} else if(e.key==='ArrowUp'){e.preventDefault();palSel=Math.max(0,palSel-1);palPaint()} else if(e.key==='Enter'){e.preventDefault();palGo(palSel)} else if(e.key==='Escape'){closePal()} });
$('#pal').addEventListener('click',e=>{ if(e.target.id==='pal') closePal() });
document.addEventListener('keydown',e=>{ if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){ e.preventDefault(); $('#pal').hidden?openPal():closePal() }
  else if(e.key==='Escape'&&!$('#pal').hidden){ e.preventDefault(); closePal() } });
$('#searchBtn').onclick=openPal;
const setFocus=v=>{document.body.classList.toggle('focus',v);localStorage.setItem('cf.focus',v?'1':'0');$('#focusBtn').textContent=v?'Show all':'Focus'};
$('#focusBtn').onclick=()=>setFocus(!document.body.classList.contains('focus'));
document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key==='.'){e.preventDefault();$('#focusBtn').click()}});
if(localStorage.getItem('cf.focus')==='1') setFocus(true);
/* tone was guessed from the wording, and the guess was wrong often enough to matter: "The bench did
   not respond", "Microphone blocked" and "Mic: not-allowed" all showed the SUCCESS dot, the last
   because the regex wants "not allowed" and the API emits "not-allowed". Callers can now say. The
   regex stays as the default so no existing call changes, and a warn toast holds long enough to
   read and speaks assertively, because the polite live region was being missed. */
/* Controls built from innerHTML get their click handlers wired afterwards, and nothing ever made
   them reachable without a mouse. Measured: li[data-note] tabIndex -1 — the note list could not be
   opened by keyboard at all — and the same for the Recall week chips and the planner's done tick.
   #caseIndex's links report tabIndex 0 and still are not focusable, because an <a> with no href
   never is. keyable() adds the attributes after a render; one delegated handler turns Enter and
   Space into the click those existing handlers already expect. Attributes only: no id, no data-
   hook and no JS-written class is renamed. */
const KEYABLE = '[data-note],[data-wk],[data-weak],[data-sess],.cover,.tplay';
function keyable(root){
  for(const el of (root || document).querySelectorAll(KEYABLE)){
    if(!el.hasAttribute('tabindex')) el.tabIndex = 0;
    if(el.hasAttribute('role')) continue;
    if(el.matches('[data-sess]')){        // a done tick is a checkbox, not a button
      el.setAttribute('role','checkbox');
      el.setAttribute('aria-checked', el.closest('.sess')?.classList.contains('done') ? 'true' : 'false');
    } else {
      el.setAttribute('role','button');
    }
  }
}
document.addEventListener('keydown', e => {
  if(e.key !== 'Enter' && e.key !== ' ') return;
  const t = e.target.closest && e.target.closest(KEYABLE);
  if(!t || t.tabIndex < 0) return;
  e.preventDefault();          // Space would scroll the page
  t.click();
});

function toast(m,tone){const t=$('#toast');t.textContent=m;
  t.dataset.tone=tone||(/^(failed|could not|error)|failed|not[ -]allowed/i.test(m)?'warn':/…$/.test(m)?'busy':'ok');
  t.setAttribute('aria-live',t.dataset.tone==='warn'?'assertive':'polite');
  t.classList.add('show');clearTimeout(t._h);
  t._h=setTimeout(()=>t.classList.remove('show'),t.dataset.tone==='warn'?7000:2800)}
let courses=[], cid=localStorage.getItem('cf.course')||'', mode='drill', cfg={};
const C=()=>courses.find(c=>c.id===cid)||courses[0];

/* nav */
const SCREENS=['home','library','tutor','notes','recall','advocate','arena','planner','progress'];
const loaders={home:loadHome,library:loadFiles,tutor:loadTutor,notes:loadNotes,recall:loadRecall,advocate:loadAdvocate,arena:loadArena,planner:loadPlanner,progress:loadProgress};
function show(id){ if(!SCREENS.includes(id)) id='home'; document.querySelectorAll('.screen').forEach(s=>s.classList.toggle('active',s.id===id)); document.querySelectorAll('[data-nav]').forEach(a=>a.classList.toggle('active',a.dataset.nav===id)); localStorage.setItem('cf.screen',id); loaders[id](); }
document.addEventListener('click',e=>{const a=e.target.closest('a[data-nav]'); if(a){e.preventDefault(); show(a.dataset.nav)}});

/* courses */
async function loadCourses(){ courses=await api('/courses'); if(!courses.find(c=>c.id===cid)) cid=courses[0].id; const s=$('#course'); s.innerHTML=courses.map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('')+'<option value="__new">New course…</option>'; s.value=cid; document.documentElement.style.setProperty('--course',C().accent); }
$('#course').addEventListener('change',e=>{if(e.target.value==='__new'){e.target.value=cid;openCourseDlg(null);return} cid=e.target.value;sylForget();localStorage.setItem('cf.course',cid);document.documentElement.style.setProperty('--course',C().accent);show(localStorage.getItem('cf.screen')||'home')});
$('#addCourse').addEventListener('click',()=>openCourseDlg(null));

/* course dialog: "New course" in the switcher, "Course settings" on Overview */
let cdMeta=null, cdId=null, cdSlugTouched=false, cdPrevT=null;
const slugify=s=>(s||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'').slice(0,48).replace(/-+$/,'');
function briefFromForm(){ const b={}; document.querySelectorAll('#courseForm [data-brief]').forEach(el=>{ const k=el.dataset.brief, v=el.value;
  b[k]=k==='authority_order'?v.split('\n').map(x=>x.trim()).filter(Boolean):k==='provenance_tags'?(v.match(/\[[^\]]+\]|[^\s,\[\]]+/g)||[]):v.trim() }); return b }
function fillCourseForm(c){ const b=(c&&c.brief)||{}; $('#cfName').value=c?c.name:''; $('#cfSlug').value=c?(c.slug||''):'';
  document.querySelectorAll('#courseForm [data-brief]').forEach(el=>{ const v=b[el.dataset.brief]; el.value=Array.isArray(v)?v.join(el.dataset.brief==='authority_order'?'\n':' '):(v||'') }) }
function paintAccents(sel){ const pal=[...cdMeta.palette]; if(sel&&!pal.includes(sel)) pal.unshift(sel);
  $('#cfAccents').innerHTML=pal.map(c=>`<label class="swatch" title="${esc(c)}"><input type="radio" name="cfAccent" value="${esc(c)}" ${c===sel?'checked':''} aria-label="Accent ${esc(c)}"><span style="background:${esc(c)}"></span></label>`).join('') }
async function openCourseDlg(id){ try{ if(!cdMeta) cdMeta=await api('/course-meta') }catch(e){ toast('Could not open: '+e.message); return }
  cdId=id; const c=id?courses.find(x=>x.id===id):null; cdSlugTouched=!!c; fillCourseForm(c);
  const used=courses.map(x=>(x.accent||'').toLowerCase()); paintAccents(c?c.accent:(cdMeta.palette.find(p=>!used.includes(p))||cdMeta.palette[0]));
  $('#cdlgTitle').textContent=c?'Course settings':'New course'; $('#cfSave').textContent=c?'Save changes':'Create course'; $('#cfDelete').hidden=!c; $('#cfStatus').textContent='';
  $('#courseDlg').showModal(); $('#cfName').focus(); previewBrief(0) }
function previewBrief(wait=250){ clearTimeout(cdPrevT); cdPrevT=setTimeout(async()=>{ const b=briefFromForm();
  try{ const r=await post('/course-brief/preview',{name:$('#cfName').value.trim(),brief:b,cid:cdId});
    $('#cfPreview').textContent=r.prompt||'Fill in the brief and the tutor prompt appears here.';
    $('#cfPrevNote').textContent=r.fallback?'The brief is empty, so this course keeps its hand-written prompt. Filling the brief replaces it.':'';
    $('#cfHint').hidden=!((b.exam_format||b.wg_tutor||b.permitted_materials)&&/UNKNOWN/.test(b.notes)); }
  catch(e){ $('#cfPrevNote').textContent=e.message } },wait) }
$('#courseForm').addEventListener('input',e=>{ if(e.target.id==='cfSlug') cdSlugTouched=true; if(e.target.id==='cfName'&&!cdSlugTouched) $('#cfSlug').value=slugify(e.target.value); if(e.target.name!=='cfAccent') previewBrief() });
$('#courseForm').addEventListener('submit',async e=>{ e.preventDefault(); const name=$('#cfName').value.trim(); if(!name){ $('#cfStatus').textContent='Give the course a name.'; $('#cfName').focus(); return }
  const body={name,slug:$('#cfSlug').value.trim()||null,accent:(document.querySelector('#cfAccents input:checked')||{}).value||null,brief:briefFromForm()};
  $('#cfSave').disabled=true;
  try{ if(cdId){ await put(`/courses/${cdId}`,body); toast('Course settings saved') } else { const r=await post('/courses',body); cid=r.id; localStorage.setItem('cf.course',cid); toast(`${name} created`) }
    $('#courseDlg').close(); await loadCourses(); show(cdId?(localStorage.getItem('cf.screen')||'home'):'home') }
  catch(err){ $('#cfStatus').textContent=err.message }
  $('#cfSave').disabled=false });
$('#cdlgClose').onclick=$('#cfCancel').onclick=()=>$('#courseDlg').close();
$('#courseSettings').onclick=()=>openCourseDlg(cid);
$('#cfDelete').onclick=async()=>{ const c=courses.find(x=>x.id===cdId); if(!c) return; let u; try{ u=await api(`/courses/${c.id}/usage`) }catch(e){ $('#cfStatus').textContent=e.message; return }
  const has=u.files+u.notes+u.cards;
  if(!confirm(has?`Delete ${c.name} and everything in it: ${u.files} file(s), ${u.notes} note(s), ${u.cards} card(s), its conversation and planned sessions? This can't be undone.`:`Delete ${c.name}? It has no files, notes or cards.`)) return;
  try{ await del(`/courses/${c.id}${has?'?force=1':''}`) }catch(e){ $('#cfStatus').textContent=e.message; return }
  $('#courseDlg').close(); if(cid===c.id){ localStorage.removeItem('cf.course') } toast(`${c.name} deleted`); await loadCourses(); show('home') };

/* home */
const TABS=[["#2f5fae","Prohibitions","34 · 45 · 101"],["#d98a2b","Derogations","36 · 52 · 65"],["#1f7a4d","Competences","5 · 114 · 352"],["#8fbf6a","Secondary law","2004/38 · 1/2003"],["#8e2f6e","Enforcement","258 · 263 · 267"],["#d46a9a","Rights","18 · 21 · 157"],["#c9b23a","Definitions","28 · 54 · 57"]];
function drawBook(){ const tilt=document.querySelector('#book .booktilt'); if(!tilt||tilt.querySelector('.tab')) return;
  const name=i=>TABS[i][1]+' · Art '+TABS[i][2];
  TABS.forEach((t,i)=>{ const b=document.createElement('button'); b.type='button'; b.className='tab';
    const dark=`color-mix(in oklab,${t[0]},#000 34%)`;
    b.style.top=(12+i*32)+'px'; b.style.background=`linear-gradient(160deg,${t[0]},${dark})`; b.style.transitionDelay='0s, '+(i*60)+'ms';
    b.setAttribute('aria-label',`Tab ${i+1} of ${TABS.length}: ${name(i)}`);
    b.innerHTML=`<i class="tab__top" style="background:linear-gradient(90deg,${t[0]},${dark})"></i>`;
    const show=()=>{$('#tabname').textContent=name(i)}, hide=()=>{$('#tabname').textContent=''};
    b.onmouseenter=show; b.onmouseleave=hide; b.onfocus=show; b.onblur=hide;
    b.onclick=e=>{ e.stopPropagation(); openTab(i) }; tilt.appendChild(b); }); }
let _turnT=0;
function openTab(i){ const book=$('#book'), was=book.classList.contains('is-open'), t=TABS[i];
  book.classList.add('is-open','is-turning'); clearTimeout(_turnT);
  _turnT=setTimeout(()=>{ $('#leafEyebrow').textContent=`TAB ${i+1} OF ${TABS.length}`; $('#leafLabel').textContent=t[1];
    $('#leafRefs').textContent='Art '+t[2]; $('#leafFolio').textContent='§ '+t[1].toLowerCase();
    $('#leafRule1').style.background=t[0]; $('#leafRule2').style.background=t[0];
    book.classList.add('has-page'); book.classList.remove('is-turning'); }, was?240:420); }
let _tiltInit=false;
function bookMotion(){ const book=document.getElementById('book'); if(!book) return;
  const tilt=book.querySelector('.booktilt'); if(!tilt) return;
  setTimeout(()=>book.classList.add('is-loaded'),120);
  if(_tiltInit) return; _tiltInit=true;
  const toggle=()=>{ const open=!book.classList.contains('is-open'); book.classList.toggle('is-open',open); if(!open) book.classList.remove('has-page') };
  tilt.addEventListener('click',toggle);
  tilt.addEventListener('keydown',e=>{ if(e.target===tilt&&(e.key==='Enter'||e.key===' ')){ e.preventDefault(); toggle() } });
  if(matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  let raf=0;
  book.addEventListener('pointermove',e=>{ if(raf) return; const r=book.getBoundingClientRect();
    const px=(e.clientX-r.left)/r.width-0.5, py=(e.clientY-r.top)/r.height-0.5;
    raf=requestAnimationFrame(()=>{ raf=0; tilt.style.setProperty('--tt','.12s');
      tilt.style.setProperty('--ry',(px*10).toFixed(2)+'deg'); tilt.style.setProperty('--rx',(-py*7).toFixed(2)+'deg') }) });
  book.addEventListener('pointerleave',()=>{ tilt.style.setProperty('--tt','.5s'); tilt.style.setProperty('--rx','0deg'); tilt.style.setProperty('--ry','0deg') }); }
async function loadHome(){ drawBook(); bookMotion(); const c=C(); $('#homeTitle').textContent=c.name;
  $('#coverTitle').textContent=c.name.toUpperCase(); $('#leafTitle').textContent=c.name;
  $('#leafKicker').textContent=TABS.slice(0,3).map(x=>x[1]).join(' · ').toUpperCase(); const s=await api(`/courses/${cid}/stats`);
  $('#h-due').textContent=s.due; $('#h-streak').textContent=s.streak; $('#h-files').textContent=s.files; $('#h-acc').textContent=s.recall_accuracy==null?'–':s.recall_accuracy+'%';
  let next,body,go; if(s.files===0){next='Add your files';body='Slides, transcripts and notes go in first — the tutor only works from what you upload.';go='library'}
  else if(s.due>0){next=`Review ${s.due} due card${s.due>1?'s':''}`;body='Clear the queue before adding new material.';go='recall'}
  else if(s.cards===0){next='Generate a first deck';body='Pick a file in Recall and let the tutor write cards from it.';go='recall'}
  else{next='Drill with the tutor';body='Ask for one question on your weakest topic.';go='tutor'}
  $('#h-next').textContent=next; $('#h-nextBody').textContent=body; $('#h-go').onclick=()=>show(go);
  const ss=(await api('/sessions')).filter(x=>x.day===new Date().toISOString().slice(0,10));
  $('#h-today').innerHTML=ss.length?ss.map(x=>`<li style="padding:.35rem 0;border-bottom:1px solid var(--rule)" class="small">${esc(x.course)} — ${esc(x.topic)} <span class="tag ${x.done?'ok':''}">${x.done?'done':x.minutes+' min'}</span></li>`).join(''):'<li class="small muted">Nothing planned for today.</li>';
}

/* files */
async function loadFiles(){
  const fs=await api(`/courses/${cid}/files`);
  sylFill(fs);
  if(!fs.length){ $('#fileRows').innerHTML='<tr><td colspan="7"><div class="emptystate"><b>No files yet</b><span>Drop the Week 2 slides and a transcript in to start.</span><button class="btn small" type="button" onclick="document.getElementById(\'fileInput\').click()">Choose files</button></div></td></tr>'; }
  else {
    const groups={}; fs.forEach(f=>{ const k=f.week?('Week '+f.week):'Unsorted'; (groups[k]=groups[k]||[]).push(f) });
    const order=Object.keys(groups).sort((a,b)=>{ if(a==='Unsorted')return 1; if(b==='Unsorted')return -1; return (+a.slice(5))-(+b.slice(5)) });
    const row=f=>`<tr><td><label class="tick"><input type="checkbox" ${f.selected?'checked':''} data-toggle="${f.id}" aria-label="Include in tutor context"></label></td><td>${esc(f.name)}</td><td>${f.kind}</td><td>${esc(f.week)||'<span class=muted>—</span>'}</td><td class="small muted">${f.chars?Math.round(f.chars/1000)+'k':'–'}</td><td><span class="tag ${f.status==='indexed'?'ok':(f.status==='no text'?'warn':'')}">${f.status}</span></td><td><button class="btn small ghost" data-view="${f.id}" ${f.kind==='image'?'disabled':''}>Text</button> <button class="btn small ghost" data-del="${f.id}">Remove</button></td></tr>`;
    $('#fileRows').innerHTML=order.map(k=>{ const g=groups[k]; const on=g.filter(f=>f.selected).length; const ids=g.map(f=>f.id).join(',');
      return `<tr class="grouphead"><td><input type="checkbox" data-group="${ids}" ${on===g.length?'checked':''} ${on&&on<g.length?'data-some="1"':''} aria-label="Tick all in ${k}"></td><td colspan="6"><b>${k}</b> <span class="small muted">· ${g.length} file${g.length>1?'s':''}, ${on} on</span></td></tr>` + g.map(row).join(''); }).join('');
    document.querySelectorAll('[data-some="1"]').forEach(c=>c.indeterminate=true);
    document.querySelectorAll('[data-group]').forEach(b=>b.onchange=async()=>{ const ids=b.dataset.group.split(','); await Promise.all(ids.map(id=>post(`/files/${id}/toggle-to`,{on:b.checked}))); loadFiles(); });
  }
  document.querySelectorAll('[data-toggle]').forEach(b=>b.onchange=async()=>{await post(`/files/${b.dataset.toggle}/toggle`);loadFiles()});
  document.querySelectorAll('[data-del]').forEach(b=>b.onclick=async()=>{if(confirm('Remove this file?')){await del(`/files/${b.dataset.del}`);loadFiles()}});
  document.querySelectorAll('[data-view]').forEach(b=>b.onclick=async()=>{const t=await api(`/files/${b.dataset.view}/text`);const w=window.open('','_blank');w.document.write(`<pre style="white-space:pre-wrap;font:14px/1.5 Georgia,serif;max-width:80ch;margin:2rem auto">${esc(t.text)}</pre>`);w.document.title=t.name});
}
async function upload(files){ for(const f of files){ const fd=new FormData(); fd.append('file',f); fd.append('week',$('#week').value); toast('Indexing '+f.name+'…'); try{ const r=await api(`/courses/${cid}/files`,{method:'POST',body:fd}); toast(`${f.name}: ${r.status}${r.chars?' · '+Math.round(r.chars/1000)+'k chars':''}`);}catch(e){toast('Failed: '+e.message)} } loadFiles(); }
$('#inferBtn').onclick=async()=>{const b=$('#inferBtn');b.disabled=true;b.textContent='Detecting…';try{const r=await post(`/courses/${cid}/infer-weeks`);toast(r.tagged?`Sorted ${r.tagged} file(s) into weeks`:'Nothing to sort — all files already have a week');loadFiles()}catch(e){toast('Failed: '+e.message)}b.disabled=false;b.textContent='Detect weeks'};
/* syllabus in, weeks and topics out. The panel holds a proposal; only Apply writes anything. */
/* The proposal belongs to the course it was read from. cid can change under it — the course
   switcher only reassigns cid — and applying then writes one course's schedule onto another,
   overwriting its tutor prompt and retagging its files. Bound and checked, not assumed. */
let sylProposal=null, sylProposalCid=null;
function sylFill(fs){ const opts=fs.filter(f=>f.kind!=='image'&&f.chars); const sel=$('#sylFile'); const keep=sel.value;
  sel.innerHTML=opts.length?opts.map(f=>`<option value="${esc(f.id)}">${esc(f.name)}</option>`).join(''):'<option value="">No readable file yet</option>';
  if(opts.some(f=>f.id===keep)) sel.value=keep;
  else { const guess=opts.find(f=>/syllab|course guide|module guide|outline|studiewijzer/i.test(f.name)); if(guess) sel.value=guess.id }
  sel.disabled=$('#sylRead').disabled=!opts.length;
  if(!sylProposal) sylApplied(); }
async function sylApplied(){ try{ const s=await api(`/courses/${cid}/syllabus`);
    $('#sylState').textContent=s.weeks.length?`${s.weeks.length} week${s.weeks.length>1?'s':''} applied${s.source?' from '+s.source:''}`:''; }
  catch(e){ $('#sylState').textContent='' } }
function sylRender(p){ sylProposal=p; sylProposalCid=cid;
  $('#sylNote').textContent=p.note||'';
  $('#sylHint').textContent=p.weeks.length?'Untick a week to leave it out. Nothing is saved until you apply this.':'Nothing to apply.';
  $('#sylApply').disabled=!p.weeks.length;
  $('#sylWeeks').innerHTML=p.weeks.length?p.weeks.map((w,i)=>{
      const d=[(w.topics||[]).length?'Topics: '+w.topics.join('; '):'',(w.readings||[]).length?'Reading: '+w.readings.join('; '):''].filter(Boolean).join(' · ');
      return `<div class="sylwk" data-sylwk="${i}"><label class="tick"><input type="checkbox" checked data-sylpick="${i}" aria-label="Keep week ${esc(w.week)}"></label>`+
        `<span class="n">Week ${esc(w.week)}</span><span class="t">${w.title?esc(w.title):'<span class="muted">untitled</span>'}</span>`+
        (d?`<span class="d">${esc(d)}</span>`:'') + `</div>` }).join('')
    :'<p class="small muted">Nothing in that document reads as a teaching schedule, so no weeks are proposed.</p>';
  document.querySelectorAll('[data-sylpick]').forEach(b=>b.onchange=()=>{
    document.querySelector(`[data-sylwk="${b.dataset.sylpick}"]`).classList.toggle('off',!b.checked);
    $('#sylApply').disabled=!document.querySelectorAll('[data-sylpick]:checked').length });
  $('#sylPanel').hidden=false; }
$('#sylRead').onclick=async()=>{ const fid=$('#sylFile').value; if(!fid) return;
  const b=$('#sylRead'); b.disabled=true; b.textContent='Reading…';
  try{ sylRender(await post(`/courses/${cid}/syllabus/extract`,{file_id:fid})) }
  catch(e){ toast('Could not read it: '+e.message) }
  b.disabled=false; b.textContent='Read syllabus'; };
function sylForget(){ sylProposal=null; sylProposalCid=null; const p=$('#sylPanel'); if(p) p.hidden=true; }
$('#sylDiscard').onclick=()=>{ sylForget(); sylApplied() };
$('#sylApply').onclick=async()=>{ if(!sylProposal) return;
  if(sylProposalCid!==cid){ sylForget(); toast('That schedule was read from another course — read it again here.'); return }
  const keep=[...document.querySelectorAll('[data-sylpick]:checked')].map(b=>sylProposal.weeks[+b.dataset.sylpick]);
  const b=$('#sylApply'); b.disabled=true; b.textContent='Applying…';
  try{ const r=await post(`/courses/${cid}/syllabus/apply`,{weeks:keep,source:sylProposal.source||''});
    toast(`${r.weeks} week${r.weeks===1?'':'s'} applied${r.tagged?` · ${r.tagged} file${r.tagged===1?'':'s'} sorted`:' · no file matched a week by name'}`);
    sylProposal=null; $('#sylPanel').hidden=true; await loadCourses(); loadFiles() }
  catch(e){ toast('Failed: '+e.message) }
  b.disabled=false; b.textContent='Apply to this course'; };
$('#fileInput').addEventListener('change',e=>upload([...e.target.files]));
const drop=$('#drop'); ['dragenter','dragover'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add('over')})); ['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('over')})); drop.addEventListener('drop',e=>upload([...e.dataTransfer.files])); drop.querySelector('label').addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('#fileInput').click()}});

/* tutor */
async function loadTutor(){ const fs=await api(`/courses/${cid}/files`); const sel=fs.filter(f=>f.selected); $('#tutorSub').textContent=`${C().name} · auto-routing: notes and cards on ${(cfg.cheap_model||'').replace('claude-','')}, drilling on ${(cfg.model||'').replace('claude-','')}`;
  $('#ctxList').innerHTML=sel.length?sel.map(f=>`<li><span>${esc(f.name)}</span></li>`).join(''):'<li class="muted">No files ticked in Files.</li>';
  const chars=sel.reduce((a,f)=>a+(f.chars||0),0); $('#ctxSize').textContent=chars?`≈ ${Math.round(chars/4/1000)}k tokens of text per message${chars>180000?' — over budget, later files will be truncated':''}`:'';
  const ms=await api(`/courses/${cid}/messages`); const ch=$('#chat'); ch.innerHTML=''; ms.forEach(m=>{const d=addMsg(m.role,m.content); if(m.role==='assistant') render(d,m.content)}); if(!ms.length) addMsg('assistant',`Tutor for ${C().name}. Tick files in Files, then ask — or say "drill me on ${sel[0]?sel[0].name.replace(/\.\w+$/,''):'this week'}".`); ch.scrollTop=ch.scrollHeight;
}
let mmTheme=null;   // the scheme mermaid was last initialised for, so a theme switch re-inits rather than latching
function mmSetup(){
  /* fontFamily was 'inherit'. Mermaid measures every node in a sandbox it appends to <body> — which
     inherits the chrome sans — and the finished SVG then lands in .noteview, which is serif. Same
     size, wider glyphs, so labels overflowed the diamonds mermaid had sized for them. Naming the
     sans explicitly makes measurement and paint agree; .viz svg pins the paint side to match. A
     flowchart label is diagram furniture, not prose, so sans is also the right call. */
  const scheme=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'neutral';
  if(mmTheme===scheme) return;
  const sans=getComputedStyle(document.documentElement).getPropertyValue('--sans').trim()||'sans-serif';
  mermaid.initialize({startOnLoad:false,theme:scheme,fontFamily:sans,
                      flowchart:{useMaxWidth:true,nodeSpacing:28,rankSpacing:34,padding:8}});
  mmTheme=scheme;
}
async function render(d,raw){
  d.dataset.raw=raw; if(!window.marked){d.textContent=raw;return}
  const blocks=[]; let txt=raw.replace(/```(mermaid|svg)\n([\s\S]*?)```/g,(m,k,body)=>{blocks.push({k,body});return `\n<div class="viz" data-viz="${blocks.length-1}"></div>\n`});
  d.classList.add('md'); d.innerHTML=marked.parse(txt,{breaks:true});
  for(const el of d.querySelectorAll('.viz')){ const b=blocks[+el.dataset.viz]; if(!b) continue;
    if(b.k==='svg'){ el.innerHTML=b.body; continue }
    const mid='mm'+Math.random().toString(36).slice(2);
    try{ mmSetup(); const {svg}=await mermaid.render(mid,b.body.trim()); el.innerHTML=svg }
    catch(e){ el.innerHTML='<pre>'+b.body.replace(/</g,'&lt;')+'</pre>' }
    // Mermaid measures in a sandbox it appends to <body>, and on a parse error leaves it there with
    // its bomb graphic — the thing found stuck at the foot of an unrelated screen. The catch above
    // cannot reach it: it is not inside the element we render into. finally, not catch, because a
    // SUCCESSFUL render leaves the sandbox behind too. #45 contributed the wider selector, which
    // also catches the shapes this id lookup would miss.
    finally{ document.getElementById('d'+mid)?.remove();
             for(const stray of document.querySelectorAll('body>div[id^="dmm"],body>svg[id^="mm"]')) stray.remove() } }
  if(d.closest('#chat')) $('#chat').scrollTop=$('#chat').scrollHeight;
}
function addMsg(role,text){const d=document.createElement('div');d.className='msg '+role;d.textContent=text;$('#chat').appendChild(d);$('#chat').scrollTop=$('#chat').scrollHeight;return d}
const MODE_UI={
  drill:{hint:'Drill: one question at a time, firm correction. Reply with your answer, or say what to drill.',ph:'Your answer — or "drill me on Art 34"'},
  explain:{hint:'Explain: a tight structured answer with file references; asks for a diagram or table when it helps.',ph:'What do you want explained? e.g. "Keck vs Italian Trailers, with a flowchart"'},
  apply:{hint:'Apply to facts: paste the facts of a WG or exam question. Every step names the article or case from your ticked files that decides it, and what fact would flip it.',ph:'Paste the facts — e.g. "Germany bans the sale of energy drinks above 50mg caffeine. A French producer\u2026"'},
  notes:{hint:'Build notes: reconciles the ticked files into master notes with provenance tags and saves the result to Notes.',ph:'What to build — e.g. "Week 2 goods master notes" or "case map for Art 36 derogations"'}};
function setMode(m){mode=m;document.querySelectorAll('[data-mode]').forEach(x=>x.classList.toggle('active',x.dataset.mode===m));$('#modeHint').textContent=MODE_UI[m].hint;$('#q').placeholder=MODE_UI[m].ph;localStorage.setItem('cf.mode',m)}
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{setMode(b.dataset.mode);$('#q').focus()});
setMode(localStorage.getItem('cf.mode')||'drill');
/* ---- voice: browser speech, no API cost ---- */
let recog=null, listening=false, speakOn=localStorage.getItem('cf.speak')==='1', voiceUtter=null, lastSpeech='', sessionCost=+(localStorage.getItem('cf.cost')||0);
/* ---- one voice for the whole page (Phase 12): the server's (Kokoro / Google / ElevenLabs) when it is configured,
   the browser's otherwise — and the browser's for the rest of a reply whenever a server sentence fails ---- */
let cfRun=0, cfAudio=null, cfWake=null;
const TUTOR_SERVER_CHARS=1500;   // longer tutor replies are read by the browser: the server voice is for short spoken turns
const cfClean=t=>String(t||'').replace(/\[(?:LECTURE|WG|SLIDES|READER|SCHUTZE|SCRIPTUM|DCFR|NATIONAL|ADDED|OUTSIDE FILES)[^\]]*\]/g,'').replace(/[*_`#>|]/g,'').replace(/\s{2,}/g,' ').trim();
function cfChunks(t){   // sentences, merged to at least 40 characters ("Art." is not a sentence) and kept under the server's cap
  const out=[]; let cur='';
  for(const s of t.match(/[^.!?]+[.!?]*/g)||[]){
    cur=(cur+' '+s.trim()).trim(); if(cur.length<40) continue;
    while(cur.length>400){ const k=cur.lastIndexOf(' ',400), cut=k>0?k:400; out.push(cur.slice(0,cut)); cur=cur.slice(cut).trim(); }
    if(cur) out.push(cur); cur=''; }
  if(cur) out.push(cur);
  return out.filter(s=>/[\p{L}\p{N}]/u.test(s)); }   // a chunk of punctuation alone would come back empty and trip the fallback
function cfHush(){ cfRun++; window.speechSynthesis?.cancel();
  if(cfAudio){ try{ cfAudio.pause() }catch(e){} cfAudio=null; }
  const w=cfWake; cfWake=null; if(w) w(false); }   // whatever was waiting on the old voice finishes now, so nothing stays locked
function cfWait(start,ms){ return new Promise(done=>{ let t;
  const fin=ok=>{ clearTimeout(t); if(cfWake===fin) cfWake=null; done(ok); };
  t=setTimeout(()=>fin(true),ms); cfWake=fin; start(fin); }); }
function cfBrowser(parts,run){
  if(!('speechSynthesis' in window)||run!==cfRun||!parts.length) return Promise.resolve(false);
  const v=speechSynthesis.getVoices().find(v=>/Daniel|Serena|Kate|en-GB/.test(v.name+v.lang));
  return cfWait(fin=>parts.forEach((p,i)=>{
    const u=new SpeechSynthesisUtterance(p); u.lang=(window.CFVOICE||{}).language||'en-GB'; u.rate=1.05; if(v) u.voice=v;
    u.onerror=()=>fin(false);
    if(i===parts.length-1){ voiceUtter=u; u.onend=()=>fin(true); }   // keep the last one referenced until it ends
    speechSynthesis.speak(u); }), 3000+parts.join(' ').length*120); }
const cfFetch=s=>fetch('/api/speak',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:s})})
  .then(r=>r.ok&&r.status!==204&&/^audio\//.test(r.headers.get('content-type')||'')?r.blob():null).catch(()=>null);
async function cfSpeak(text,{serverMax=Infinity}={}){   // resolves true when fully spoken, false when stopped or failed
  cfHush(); const run=cfRun, clean=cfClean(text), parts=cfChunks(clean);
  if(!parts.length) return true;
  if(!(window.CFVOICE||{}).server||clean.length>serverMax) return cfBrowser(parts,run);
  let next=cfFetch(parts[0]);
  for(let i=0;i<parts.length;i++){
    const blob=await next; if(run!==cfRun) return false;
    if(!blob) return cfBrowser(parts.slice(i),run);          // 204, an error, or not audio: the browser reads the rest
    next=i+1<parts.length?cfFetch(parts[i+1]):null;          // one sentence ahead, never a burst of calls
    const src=URL.createObjectURL(blob);
    const ok=await cfWait(fin=>{ cfAudio=new Audio(src); cfAudio.onended=()=>fin(true); cfAudio.onerror=()=>fin(false);
      cfAudio.play().catch(()=>fin(false)); }, 60000);
    URL.revokeObjectURL(src);
    if(run!==cfRun) return false;
    cfAudio=null;
    if(!ok) return cfBrowser(parts.slice(i),run);             // playback refused (autoplay rules): same rule
  }
  return true; }
function showReading(r){
  /* Which of your own materials answered the last question, and what did not fit. */
  const box=$('#ctxAnswer'); if(!box) return;
  const esc=t=>String(t).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
  const used=(r.used||[]).map(esc), trimmed=(r.trimmed||[]).map(esc);
  box.hidden=false;
  box.innerHTML=`<b>Answered from</b> ${used.length} of ${used.length+trimmed.length} ticked files`
    + `<div class="muted" style="margin-top:.2rem">${used.join(' · ')||'—'}</div>`
    + (trimmed.length?`<div class="muted" style="margin-top:.35rem">Not needed for this question: ${trimmed.join(' · ')}</div>`:'')
    + `<div class="muted" style="margin-top:.35rem">${Math.round((r.chars||0)/1000)}k characters sent instead of the whole set</div>`;
}
function showCost(){ const el=$('#costState'); if(el) el.textContent=sessionCost?`$${sessionCost.toFixed(2)} this session`:'' }
function initVoice(){
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR){$('#micBtn').disabled=true;$('#micBtn').title='Dictation needs Chrome or Safari';}
  else{ recog=new SR(); recog.lang='en-GB'; recog.continuous=false; recog.interimResults=true;
    recog.onresult=e=>{let t='';for(const r of e.results)t+=r[0].transcript;$('#q').value=t;};
    recog.onend=()=>{listening=false;$('#micBtn').setAttribute('aria-pressed','false');$('#micBtn').textContent='🎙 Talk';
      if($('#q').value.trim()) send();};
    recog.onerror=e=>{listening=false;$('#micBtn').textContent='🎙 Talk';toast('Mic: '+e.error,'warn')};
  }
  if(cfg.voice?.gemini){ $('#micMode').hidden=false; document.querySelectorAll('#micMode [data-mic]').forEach(b=>b.onclick=()=>setMicMode(b.dataset.mic)); setMicMode(currentMicMode()); }
  $('#speakBtn').setAttribute('aria-pressed',speakOn?'true':'false'); $('#speakBtn').classList.toggle('primary',speakOn);
  if(!('speechSynthesis' in window) && !(window.CFVOICE||{}).server){$('#speakBtn').disabled=true}
}
/* ---- Gemini dictation (Phase 8): mic → 16 kHz PCM → this app's relay → Vertex AI; only text comes back ---- */
let gem=null;
const currentMicMode=()=>localStorage.getItem('cf.micMode')||((window.SpeechRecognition||window.webkitSpeechRecognition)?'browser':'gemini');
function setMicMode(m){ localStorage.setItem('cf.micMode',m);
  document.querySelectorAll('#micMode [data-mic]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.mic===m?'true':'false'));
  $('#micBtn').disabled=(m==='browser'&&!recog); }
const PCM_WORKLET=`class Pcm16k extends AudioWorkletProcessor{constructor(){super();this.r=sampleRate/16000;this.a=0;this.s=0;this.n=0;this.b=new Int16Array(1600);this.i=0}
process(inputs){const ch=inputs[0]&&inputs[0][0];if(!ch)return true;for(let k=0;k<ch.length;k++){this.s+=ch[k];this.n++;this.a+=1;
if(this.a>=this.r){this.a-=this.r;const v=Math.max(-1,Math.min(1,this.s/this.n));this.s=0;this.n=0;this.b[this.i++]=v<0?v*32768:v*32767;
if(this.i===1600){this.port.postMessage(this.b.buffer.slice(0));this.i=0}}}return true}}
registerProcessor('pcm16k',Pcm16k)`;
async function startGemini(){
  const btn=$('#micBtn'); let stream=null, ctx=null, node=null, ws=null, gotText=false, stopped=false, finished=false, guard=null;
  const cleanup=()=>{ try{node&&node.disconnect()}catch(e){} try{stream&&stream.getTracks().forEach(t=>t.stop())}catch(e){} try{ctx&&ctx.close()}catch(e){}
    clearTimeout(guard); gem=null; listening=false; btn.setAttribute('aria-pressed','false'); btn.textContent='🎙 Talk'; };
  const fallback=message=>{ cleanup(); toast(message);
    if(recog && !gotText){ listening=true; btn.setAttribute('aria-pressed','true'); btn.textContent='● Listening'; $('#q').value=''; recog.start(); } };
  const finish=()=>{ if(finished) return; finished=true; cleanup(); if($('#q').value.trim()) send(); };
  try{
    cfHush();
    stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}});
    ctx=new AudioContext();
    await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([PCM_WORKLET],{type:'application/javascript'})));
    node=new AudioWorkletNode(ctx,'pcm16k'); ctx.createMediaStreamSource(stream).connect(node);
    ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/api/voice/live?course=${encodeURIComponent(cid||'')}`);
    ws.binaryType='arraybuffer';
    node.port.onmessage=e=>{ if(ws.readyState===1 && !stopped) ws.send(e.data) };
    ws.onmessage=e=>{ let m; try{ m=JSON.parse(e.data) }catch(err){ return }
      if('interim' in m || 'final' in m){ gotText=true; $('#q').value=('final' in m)?m.final:m.interim; }
      if(m.limit){ toast('Gemini dictation stops at about ten minutes'); gem&&gem.stop(); }
      if(m.error){ finished=true; fallback(m.error+' Using the browser mic.'); }
      if('done' in m){ if(m.done) $('#q').value=m.done;
        if(m.cost_usd){ sessionCost+=m.cost_usd; localStorage.setItem('cf.cost',sessionCost); showCost(); }
        finish(); } };
    ws.onclose=()=>{ if(finished) return; if(stopped) finish(); else { finished=true; fallback('Gemini dictation is unavailable. Using the browser mic.'); } };
    gem={ stop(){ if(stopped) return; stopped=true; btn.textContent='… Finishing';
      try{ if(ws.readyState===1) ws.send(JSON.stringify({stop:true})) }catch(e){}
      try{ stream.getTracks().forEach(t=>t.stop()) }catch(e){}
      guard=setTimeout(()=>{ try{ws.close()}catch(e){} finish(); },10000); } };
    listening=true; btn.setAttribute('aria-pressed','true'); btn.textContent='● Listening'; $('#q').value='';
  }catch(e){ finished=true; fallback('Gemini dictation needs microphone access. Using the browser mic.'); }
}
$('#micBtn').onclick=()=>{ if(listening && !gem){ recog?.stop(); return }  // the browser mic is on (chosen, or a Gemini fallback): stop it
  if(cfg.voice?.gemini && currentMicMode()==='gemini'){ return gem ? gem.stop() : startGemini(); }
  if(!recog) return; if(listening){recog.stop();return}
  cfHush(); listening=true; $('#micBtn').setAttribute('aria-pressed','true'); $('#micBtn').textContent='● Listening'; $('#q').value=''; recog.start(); };
$('#costState').onclick=()=>{ sessionCost=0; localStorage.setItem('cf.cost',0); showCost() }; showCost();
$('#speakBtn').onclick=()=>{ speakOn=!speakOn; localStorage.setItem('cf.speak',speakOn?'1':'0');
  $('#speakBtn').setAttribute('aria-pressed',speakOn?'true':'false'); $('#speakBtn').classList.toggle('primary',speakOn);
  if(!speakOn) cfHush(); else { if(lastSpeech) speak(lastSpeech); else toast('Replies will be read aloud — the tutor now writes a spoken version of each answer'); } };
function speak(text){ if(!speakOn||!text||!text.trim()) return; cfSpeak(text,{serverMax:TUTOR_SERVER_CHARS}); }

const DOWN=["define","definition","what is","list","summarise","summarize","recap","translate","when did","who is","how many"];
const UP=["compare","contrast","irac","critique","conflict","diverge","exam answer","argue","reconcile","distinguish","apply to the facts","which outranks","is this caught","step by step","walk me through"];
function routeGuess(){ const sel=$('#modelSel').value; if(sel!=='auto'){ $('#routeHint').textContent=''; return } const t=$('#q').value.toLowerCase().trim(); let m=(mode==='notes')?window.CFCHEAP:window.CFMODEL;
  if(m===window.CFMODEL&&(mode==='drill'||mode==='explain')&&t.length<90&&DOWN.some(k=>t.startsWith(k)||t.slice(0,40).includes(k))&&!UP.some(k=>t.includes(k))) m=window.CFCHEAP;
  if(m===window.CFCHEAP&&UP.some(k=>t.includes(k))) m=window.CFMODEL;
  $('#routeHint').textContent = t? '→ '+(m||'').replace('claude-','') : ''; }
$('#q').addEventListener('input',routeGuess); document.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>setTimeout(routeGuess,0))); $('#modelSel').addEventListener('change',routeGuess);
async function send(){ const q=$('#q').value.trim(); if(!q) return; if(!cfg.has_key){toast('No Claude API key on the server — add it to .env.local and restart');return}
  addMsg('user',q); $('#q').value=''; $('#send').disabled=true; const d=addMsg('assistant','');
  try{ const r=await fetch(`/api/courses/${cid}/chat`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:q,mode,model:$('#modelSel').value,speech:speakOn})});
    const rd=r.body.getReader(); const td=new TextDecoder(); let buf='';
    while(true){const {value,done}=await rd.read(); if(done) break; buf+=td.decode(value,{stream:true}); const lines=buf.split('\n\n'); buf=lines.pop();
      for(const l of lines){ if(!l.startsWith('data: ')) continue; const p=l.slice(6); if(p==='[DONE]') continue; const j=JSON.parse(p); if(j.model){d.dataset.model=j.model; continue} if(j.reading){d.dataset.reading=JSON.stringify(j.reading); showReading(j.reading); continue} if(j.usage){d.dataset.usage=JSON.stringify(j.usage); sessionCost+=j.usage.cost; localStorage.setItem('cf.cost',sessionCost); showCost(); continue} if(j.error){d.textContent+='\n[error] '+j.error; d.style.borderLeftColor='var(--warn)'} else d.textContent+=j.t; $('#chat').scrollTop=$('#chat').scrollHeight; } }
  }catch(e){d.textContent+='\n[error] '+e.message}
  let raw=d.textContent; const sm=raw.match(/<speech>([\s\S]*?)<\/speech>\s*$/); if(sm){ d.dataset.speech=sm[1].trim(); raw=raw.replace(sm[0],'').trim() } await render(d,raw);
  lastSpeech=d.dataset.speech||raw.replace(/```[\s\S]*?```/g,' (see the diagram on screen) ');
  if(raw && !raw.startsWith('[error]')){
    const act=document.createElement('div'); act.className='small'; act.style.marginTop='.4rem';
    const sv=document.createElement('button'); sv.className='btn small ghost'; sv.textContent='Save as note';
    sv.onclick=async()=>{const t=(raw.match(/^#\s*(.+)$/m)||[])[1]||q.slice(0,60); const r=await post(`/courses/${cid}/notes`,{title:t,body:raw}); sv.textContent='Saved to Notes'; sv.disabled=true; nid=r.id};
    act.appendChild(sv); d.appendChild(act);
    if(mode==='notes'){ sv.click(); toast('Saved to Notes — open the Notes tab to edit'); }
  }
  if(d.dataset.model){ const u=d.dataset.usage?JSON.parse(d.dataset.usage):null; d.title='answered by '+d.dataset.model.replace('claude-','')+(u?` · $${u.cost.toFixed(4)} · ${(u.cache_read/1000).toFixed(1)}k cached, ${(u.in/1000).toFixed(1)}k new, ${u.out} out`:'') }
  speak(lastSpeech); $('#send').disabled=false; $('#q').focus(); routeGuess(); }
$('#send').onclick=send; $('#q').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});
$('#clearChat').onclick=async()=>{if(confirm('Clear this course\'s conversation?')){await del(`/courses/${cid}/messages`);loadTutor()}};

/* notes */
let nid=null, saveT=null;
async function loadNotes(){ const ns=await api(`/courses/${cid}/notes`); if(!ns.find(n=>n.id===nid)) nid=ns[0]?.id||null;
  $('#noteList').innerHTML=ns.length?ns.map(n=>`<li class="${n.id===nid?'active':''}" data-note="${n.id}">${esc(n.title)}<div class="small muted">${new Date(n.updated*1000).toLocaleDateString()} · ${Math.round(n.chars/1000)||0}k</div></li>`).join(''):'<li class="emptystate small"><b>No notes yet</b><span>Start one, or draft it from your files.</span><button class="btn small" type="button" onclick="document.getElementById(\'newNote\').click()">New note</button></li>';
  document.querySelectorAll('[data-note]').forEach(l=>l.onclick=()=>{nid=l.dataset.note;loadNotes()}); keyable($('#noteList'));
  if(nid){const n=await api(`/notes/${nid}`);$('#noteTitle').value=n.title;await loadRecIds();$('#noteBody').value=toDisplay(n.body);$('#noteStatus').textContent='Saved'} else {$('#noteTitle').value='';$('#noteBody').value='';$('#noteStatus').textContent=''}
  histVid=null; $('#histBar').hidden=true; $('#txBar').hidden=true; showNote(); loadRecs(); listenLoad();
}
const PROV={WG:'wg',LECTURE:'',LEC:'',SLIDES:'',READER:'',SCHUTZE:'',SCHÜTZE:'',ADDED:'flag','OUTSIDE FILES':'flag',P:'',VERIFY:'flag'};
function priomark(html){ return html.replace(/(<li[^>]*>)\s*●●/g,'$1<span class="prio core" title="Core">●●</span> ').replace(/(<li[^>]*>)\s*●/g,'$1<span class="prio know" title="Know">●</span> ').replace(/(<li[^>]*>)\s*○/g,'$1<span class="prio sup" title="Support">○</span> ').replace(/(<p>)\s*●●/g,'$1<span class="prio core">●●</span> ').replace(/(<p>)\s*●(?!●)/g,'$1<span class="prio know">●</span> ').replace(/(<p>)\s*○/g,'$1<span class="prio sup">○</span> '); }
function chipify(html){ return html.replace(/\[(WG|LECTURE|LEC|SLIDES|READER|SCH[UÜ]TZE|ADDED|OUTSIDE FILES|P|VERIFY|!)((?:\s[^\]]{0,40})?)\]/g,(m,k,rest)=>{const key=k.replace('Ü','U'); const cls=PROV[key]??''; return `<span class="prov ${k==='!'?'flag':cls}">${k==='!'?'CORRECTION':k}${rest}</span>`})
  .replace(/\?\?/g,'<span class="prov flag">VERIFY</span>'); }
let noteMode=localStorage.getItem('cf.noteMode')||'read';
/* anchors: stored as <!--r:RID:SEC-->, shown in the editor as ⏵N·mm:ss (N = recording number) */
let recIds=[];
function toDisplay(body){ return body.replace(/\s*<!--r:([a-z0-9]+):(\d+)-->/g,(m,r,s)=>{ const i=recIds.indexOf(r); return i<0?m:` ⏵${i+1}·${fmt(+s)}` }) }
function toRaw(body){ return body.replace(/\s*⏵(\d+)·(\d{1,3}):(\d\d)/g,(m,n,mm,ss)=>{ const r=recIds[+n-1]; return r?` <!--r:${r}:${+mm*60+ +ss}-->`:m }) }
const rawBody=()=>toRaw($('#noteBody').value);
function fmt(s){s=Math.max(0,Math.round(s));return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')}
/* A note is stored as it was written, and a reconcile wraps its lines. render() parses with
   breaks:true, so every one of those soft wraps becomes a <br> — which is why a bullet reads

       Week 2 covers two foundational freedoms
       : (1) free movement of goods (Art 34-36 TFEU), and (2) free movement of workers

   with the colon stranded on its own line, all the way down a note.

   The blunt fix is breaks:false for notes, and it is wrong here: Live capture is typed as one line
   per thought ([LEC] …, [!] …, [P] …), none of which start a markdown block, so they would all run
   together into a paragraph. Instead join only the lines that cannot be starting anything — a line
   opening with : ; , or ) is always the tail of the line above, never a new note line. Fenced
   blocks are left exactly as written. */
function unwrapSoftBreaks(md){
  const out=[]; let fenced=false;
  // A line that begins a block of its own is never a continuation. [ covers Live capture's
  // [LEC] / [!] / [P] lines, which are typed one per thought and must stay one per line.
  const STARTS_A_BLOCK=/^\s*(?:[-*+>|#]|\d+[.)]\s|```|~~~|\[|●|○|<)/;
  // Nor is it one if the line above finished a sentence, or asked for a hard break with two
  // trailing spaces, or is a setext underline / table rule.
  const ENDS_A_THOUGHT=/(?:[.!?:;|]|\s{2}|^\s*[-=|]+\s*)$/;
  for(const line of md.split("\n")){
    if(/^\s*(```|~~~)/.test(line)){ fenced=!fenced; out.push(line); continue; }
    const prev=out.length?out[out.length-1]:null;
    if(!fenced && prev!==null && prev.trim() && !ENDS_A_THOUGHT.test(prev) && !STARTS_A_BLOCK.test(line) && line.trim()){
      // : ; , ) attach to the word before them — joining with a space would read "freedoms : (1)"
      const glue=/^\s*[:;,)]/.test(line)?'':' ';
      out[out.length-1]=prev.replace(/\s+$/,'')+glue+line.replace(/^\s+/,'');
      continue;
    }
    out.push(line);
  }
  return out.join("\n");
}

async function paint(el,body){
  // <!--r:REC:SEC--> markers become tiny play chips (Read view only)
  const pre=unwrapSoftBreaks(body).replace(/<!--r:([a-z0-9]+):(\d+)-->/g,(m,r,s)=>`<a class="tplay" data-r="${r}" data-s="${s}" title="Recording ${recIds.indexOf(r)+1||'?'} · play from ${fmt(Math.max(0,s-20))}">▶ ${fmt(s)}</a>`);
  await render(el,pre); el.innerHTML=priomark(chipify(el.innerHTML));
  el.querySelectorAll('.tplay').forEach(a=>a.onclick=()=>playAt(a.dataset.r,+a.dataset.s));
  keyable(el);
  applyCover(el);
}
/* ---- cover mode: self-test off the notes ---- */
let coverMode='off';
function applyCover(el){ el.querySelectorAll('.cover').forEach(c=>{c.replaceWith(...c.childNodes)}); if(coverMode==='off') return;
  const wrap=(nodes)=>{ if(!nodes.length) return; const span=document.createElement('span'); span.className='cover'; nodes[0].parentNode.insertBefore(span,nodes[0]); nodes.forEach(n=>span.appendChild(n)); span.onclick=e=>{e.stopPropagation();span.classList.toggle('on')} };
  if(coverMode==='cases'){ el.querySelectorAll('li em, p em, td em').forEach(em=>wrap([em]));
    el.querySelectorAll('table').forEach(tb=>{ const hs=[...tb.querySelectorAll('th')].map(t=>t.textContent.toLowerCase()); const ci=hs.findIndex(x=>x.includes('case')); if(ci<0) return; tb.querySelectorAll('tbody tr').forEach(tr=>{ const td=tr.children[ci]; if(td&&!td.querySelector('.cover')) wrap([...td.childNodes]) }) }) }
  if(coverMode==='rules'){ el.querySelectorAll('table').forEach(tb=>{ const hs=[...tb.querySelectorAll('th')].map(t=>t.textContent.toLowerCase()); const ri=hs.findIndex(x=>x.includes('rule')); if(ri<0) return; tb.querySelectorAll('tbody tr').forEach(tr=>{ const td=tr.children[ri]; if(td) wrap([...td.childNodes]) }) }) }
  if(coverMode==='rules'){ el.querySelectorAll('li, td').forEach(li=>{ const b=li.querySelector('strong'); if(!b||b.parentNode!==li) return; const after=[]; let n=b.nextSibling; while(n){after.push(n); n=n.nextSibling} wrap(after.filter(x=>!(x.nodeType===3&&!x.textContent.trim())||true)); }); }
  keyable(el);   // the .cover spans are made here, after paint() has already run
}
document.querySelectorAll('[data-cover]').forEach(b=>b.onclick=()=>{coverMode=b.dataset.cover; document.querySelectorAll('[data-cover]').forEach(x=>x.setAttribute('aria-pressed',x===b)); applyCover($('#noteView'))});
let histVid=null;
$('#histBtn').onclick=async()=>{ if(!nid) return; const vs=await api(`/notes/${nid}/versions`); if(!vs.length){toast('No earlier versions yet — snapshots are kept as you edit');return}
  palRender(vs.map(v=>({kind:'version',id:v.id,title:new Date(v.created*1000).toLocaleString('en-GB',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}),snippet:`${v.title} · ${Math.round(v.chars/1000)||0}k chars`})));
  palOpener=document.activeElement; $('#pal').hidden=false; $('#pal').setAttribute('aria-modal','true'); palBehind(true);
  $('#palQ').value=''; $('#palQ').placeholder='Earlier versions — Enter to preview'; $('#palQ').focus() };
async function previewVersion(vid){ const v=await api(`/versions/${vid}`); histVid=vid; $('#histWhen').textContent=new Date(v.created*1000).toLocaleString('en-GB',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}); $('#histBar').hidden=false; noteMode='read'; await showNote(); await paint($('#noteView'),v.body) }
$('#txReconcile').onclick=()=>{ $('#txBar').hidden=true; $('#noteReconcile').click() }; $('#txLater').onclick=()=>{ $('#txBar').hidden=true };
$('#autoTx').checked=localStorage.getItem('cf.autoTx')!=='0'; $('#autoTx').onchange=e=>localStorage.setItem('cf.autoTx',e.target.checked?'1':'0');
$('#cleanBtn').onclick=async()=>{ if(!nid) return; const b=$('#cleanBtn'); b.disabled=true; b.textContent='Cleaning…'; toast('Fixing mis-heard names against your files — original kept in History');
  try{ const r=await post(`/notes/${nid}/clean-capture`); toast(r.changed?`Cleaned ${r.changed} capture section(s)`:'Nothing needed changing'); loadNotes() }catch(e){ toast('Clean failed: '+e.message) } b.disabled=false; b.textContent='Clean garble' };
$('#histBack').onclick=()=>{ histVid=null; $('#histBar').hidden=true; showNote() };
$('#histRestore').onclick=async()=>{ if(!histVid) return; if(!confirm('Replace the current text with this version? The current text is kept in History.')) return; await post(`/notes/${nid}/restore/${histVid}`); histVid=null; $('#histBar').hidden=true; toast('Restored'); loadNotes() };
$('#cardsFromMap').onclick=async()=>{ if(!nid) return; const r=await post(`/notes/${nid}/cards-from-tables`); toast(r.made?`${r.made} card(s) added to Recall`:'No case-map table found (needs a table with a Case column)') };
/* ---- the note, read aloud. Writing the script and recording it is a job on the server, so this
   polls exactly the way the Transcribe button does and then plays what the bucket holds. Audio made
   from an older version of the note comes back `stale`: it is not played, it is offered again. ---- */
let listenT=null, listenLast={status:'none'};
function listenPaint(s){ if(s) listenLast=s; s=listenLast; const b=$('#listenBtn'), a=$('#listenAudio');
  const working=s.status==='queued'||s.status==='running', playing=!!a.getAttribute('src')&&!a.paused&&!a.ended;
  b.dataset.listen=working?'working':(playing?'playing':'idle');
  b.textContent=working?'Reading…':(playing?'❚❚ Pause':(s.stale&&!s.ready?'▶ Read again':'▶ Listen'));
  b.setAttribute('aria-label',b.textContent.replace(/^[^ ]+ /,'')+' this note');
  $('#listenState').textContent=listenNote(s); }
function listenNote(s){ if(s.error) return s.error;
  if(s.status==='running'&&s.stage) return s.stage;
  if(s.stale&&!s.ready) return 'The note changed since it was read';
  if(window.CFVOICE&&window.CFVOICE.server===false) return 'No server voice configured';
  return ''; }
function listenStop(){ clearInterval(listenT); listenT=null; const a=$('#listenAudio'); try{ a.pause() }catch(e){} a.removeAttribute('src'); }
async function listenLoad(){ listenStop(); if(!nid){ listenPaint({status:'none'}); return }
  try{ listenPaint(await api(`/notes/${nid}/audio`)) }catch{ listenPaint({status:'none'}) } }
function listenPlay(){ const a=$('#listenAudio'); cfHush();                      // one voice at a time
  if(!a.getAttribute('src')) a.src=`/api/notes/${nid}/audio/file?v=${Date.now()}`;
  a.play().catch(()=>toast('Could not play the reading','warn')); }
function listenWatch(){ clearInterval(listenT); listenT=setInterval(async()=>{ let s; try{ s=await api(`/notes/${nid}/audio`) }catch{ return }
  listenPaint(s); if(s.status==='queued'||s.status==='running') return;
  clearInterval(listenT); listenT=null;
  if(s.ready) listenPlay(); else toast('Could not read the note aloud: '+(s.error||'try again'),'warn') },2500) }
$('#listenBtn').onclick=async()=>{ if(!nid){ toast('Open a note first'); return } const a=$('#listenAudio');
  if(a.getAttribute('src')&&!a.paused&&!a.ended){ a.pause(); return }
  let s; try{ s=await api(`/notes/${nid}/audio`) }catch{ s={status:'none'} }
  if(s.ready){ listenPaint(s); listenPlay(); return }
  try{ s=await post(`/notes/${nid}/audio`) }catch(e){ toast('Could not start the reading: '+e.message,'warn'); return }
  listenPaint(s);
  if(s.ready) listenPlay(); else { toast('Writing the script, then recording it — this takes a minute','busy'); listenWatch() } };
['play','pause','ended'].forEach(ev=>$('#listenAudio').addEventListener(ev,()=>listenPaint()));
/* ---- Advocate: oral revision. The engine lives on the server; this is the mouth and ears. ---- */
const adv={mastery:{},cooldown:{},misses:{},notes:[],asked:0,q:null,busy:false};
let advRecog=null, advListening=false;

function advSpeak(text){ return cfSpeak(text); }   // resolves once the whole line has been heard (false if interrupted)
function advQuiet(){ cfHush(); }

function advBubble(who,text){ const d=document.createElement('div'); d.className='advb '+who; d.textContent=text;
  const c=$('#advConvo'); c.appendChild(d); c.scrollTop=c.scrollHeight; return d; }

function advRender(){
  $('#advAsked').textContent=adv.asked;
  const vals=Object.values(adv.mastery);
  $('#advSolid').textContent=vals.filter(v=>v==='solid').length;
  $('#advWeak').textContent=vals.filter(v=>v==='missed'||v==='shaky').length;
  const map=$('#advMap');
  const keys=Object.keys(adv.mastery);
  map.innerHTML = keys.length ? keys.map(k=>`<div class="mrow"><span><span class="mdot m-${adv.mastery[k]}"></span>${esc(k)}</span><span class="mstate">${adv.mastery[k]}</span></div>`).join('')
                              : '<div class="small muted" style="padding-top:.4rem">Nothing tested yet.</div>';
  const n=$('#advNotes');
  n.innerHTML = adv.notes.length ? adv.notes.map(x=>`<div class="advnote"><b>${esc(x.concept)}</b> · ${esc(x.text)}</div>`).join('')
                                 : '<div class="emptystate">Nothing yet. Miss something and it lands here.</div>';
}

async function advNext(){
  advOwnOff();
  try{
    const r=await post(`/courses/${cid}/oral/next`,{mastery:adv.mastery,cooldown:adv.cooldown});
    if(!r.question){ adv.q=null; $('#advQ').textContent='No questions yet — press "Build questions from my files".'; $('#advTags').innerHTML=''; return; }
    adv.q=r.question;
    $('#advQ').textContent=r.question.question; $('#advCourse').textContent=C().name;
    $('#advTags').innerHTML=`<span class="tag">${esc(r.question.concept)}</span>`;
    if(!(r.question.concept in adv.mastery)) adv.mastery[r.question.concept]='untested';
    advRender(); advSpeak(r.question.question);
  }catch(e){ toast('Could not fetch a question: '+e.message); }
}

async function advSubmit(text){
  text=(text||'').trim();
  if(!text||adv.busy) return;
  const own=adv.own, q=adv.q;   // pinned: grading takes a few seconds and the stage can change meanwhile
  if(!own&&!q){ toast('Press Start, or ask your own question'); return; }
  adv.busy=true; advQuiet();
  advBubble('me',text); $('#advType').value='';
  const think=advBubble('tutor','…');
  let g;
  try{
    g = own
      ? {...await post('/speech',{question:own.question,answer:text,notes:own.text}), concept:own.concept}
      : await post(`/courses/${cid}/oral/grade`,{card_id:q.id,answer:text,teach:(adv.misses[q.concept]||0)>=2});
  }catch(e){ think.remove(); adv.busy=false; toast('Could not grade that — '+(e.message||'say it again')); return; }
  think.remove();
  adv.asked++; adv.mastery[g.concept]=g.mastery;
  if(!own){   // only cards have a queue to cool down
    adv.cooldown=Object.fromEntries(Object.entries(adv.cooldown).map(([k,v])=>[k,v-1]).filter(([,v])=>v>0));
    adv.cooldown[q.id]=g.mastery==='solid'?6:(g.mastery==='shaky'?2:1);
  }
  if(g.mastery==='missed') adv.misses[g.concept]=(adv.misses[g.concept]||0)+1;
  else if(g.mastery==='solid') adv.misses[g.concept]=0;
  if(g.note) adv.notes.unshift({concept:g.concept,text:g.note});
  const b=advBubble('tutor','');
  b.innerHTML=`<div class="verdict v-${g.mastery}">${esc(g.verdict)}</div>${esc(g.spoken)}`;
  advRender();
  adv.busy=false;   // answering again interrupts the verdict; it never locks the screen
  const heard=await advSpeak(g.spoken);
  if(heard && !own) setTimeout(()=>{ if(!adv.own&&!adv.busy&&!advListening) advNext(); }, g.mastery==='missed'?1400:700);
}

const ASR=window.SpeechRecognition||window.webkitSpeechRecognition;
if(ASR){
  advRecog=new ASR(); advRecog.lang='en-GB'; advRecog.interimResults=true; advRecog.continuous=false;
  let abuf='';
  const stopped=()=>{ advListening=false; $('#advMic').setAttribute('aria-pressed','false'); $('#advMic').textContent='🎙 Answer'; };
  advRecog.onresult=e=>{ abuf=''; for(let i=0;i<e.results.length;i++) abuf+=e.results[i][0].transcript; $('#advType').value=abuf; };
  advRecog.onend=()=>{ stopped(); if(abuf.trim()) advSubmit(abuf); abuf=''; };
  advRecog.onerror=()=>{ stopped(); $('#advHint').textContent='Mic problem — type your answer instead.'; };
}
$('#advMic').onclick=()=>{
  if(!ASR){ toast('Speaking needs Chrome — type your answer instead'); return; }
  if(advListening){ advRecog.stop(); return; }
  advQuiet();
  micOwner('#advMic','#advType','🎙 Answer',advSubmit);
  try{ advRecog.start(); advListening=true; $('#advMic').setAttribute('aria-pressed','true'); $('#advMic').textContent='● Listening';
       $('#advHint').textContent='Listening — click again when you have finished.'; }catch(e){}
};
$('#advSend').onclick=()=>advSubmit($('#advType').value);
$('#advType').addEventListener('keydown',e=>{ if(e.key==='Enter') advSubmit($('#advType').value); });
$('#advStart').onclick=()=>{ $('#advConvo').innerHTML=''; advNext(); };
$('#advBank').onclick=async()=>{
  const b=$('#advBank'); b.disabled=true; b.textContent='Writing questions…';
  try{ const r=await post(`/courses/${cid}/oral/bank`,{count:10});
       toast(r.made?`${r.made} spoken question(s) added`:'Nothing made — tick some files first'); if(r.made && !adv.own) advNext(); }
  catch(e){ toast('Could not build questions: '+e.message); }
  b.disabled=false; b.textContent='Build questions from my files';
};
$('#advCopy').onclick=()=>{
  const txt=adv.notes.map(n=>`• [${n.concept}] ${n.text}`).join('\n')||'No notes yet.';
  navigator.clipboard?.writeText(txt); $('#advCopy').textContent='Copied ✓';
  setTimeout(()=>$('#advCopy').textContent='Copy notes',1400);
};

async function loadAdvocate(){
  if(!window.CFVOICE){ try{ const cfg=await api('/config'); window.CFVOICE=cfg.voice||{}; }catch(e){ window.CFVOICE={}; } }
  $('#advSub').textContent = (window.CFVOICE||{}).server
    ? 'Oral revision — it asks, you answer out loud.'
    : 'Oral revision — using the browser voice for now.';
  if(adv.own && adv.own.cid!==cid) advOwnOff();   // a question graded against another course's note stays with that course
  if(!adv.own) $('#advCourse').textContent=C().name;
  advRender();
  advOwnNotes();
}

/* Two screens share one recogniser; whoever starts it owns it until it stops. */
function micOwner(btn,box,label,send){
  if(!ASR) return;
  let buf='';
  const stopped=()=>{ advListening=false; $(btn).setAttribute('aria-pressed','false'); $(btn).textContent=label; };
  advRecog.onresult=e=>{ buf=''; for(let i=0;i<e.results.length;i++) buf+=e.results[i][0].transcript; $(box).value=buf; };
  advRecog.onend=()=>{ stopped(); if(buf.trim()) send(buf); buf=''; };
  advRecog.onerror=()=>{ stopped(); toast('Mic problem — type it instead'); };
}

/* ---- Your own question (Phase 12): any question, graded only against a note you pick; nothing is rescheduled ---- */
async function advOwnNotes(){
  const sel=$('#advOwnRef'), keep=sel.value;
  let list=[]; try{ list=await api(`/courses/${cid}/notes`); }catch(e){}
  sel.innerHTML = list.length
    ? '<option value="">Pick a note to grade against…</option>'+list.map(n=>`<option value="${esc(n.id)}">${esc(n.title||'Untitled')}</option>`).join('')
    : '<option value="">No notes in this course yet</option>';
  sel.disabled=!list.length;
  if(keep && list.some(n=>n.id===keep)) sel.value=keep;
  $('#advOwnHint').textContent = list.length ? '' : 'Write or import a note first — the grader only uses your own material.';
  advOwnReady();
}
function advOwnReady(){ $('#advOwnGo').disabled = !($('#advOwnQ').value.trim() && $('#advOwnRef').value); }
async function advOwnStart(){
  const question=$('#advOwnQ').value.trim(), id=$('#advOwnRef').value;
  if(!question||!id){ advOwnReady(); return; }
  $('#advOwnGo').disabled=true;
  let note;
  try{ note=await api(`/notes/${encodeURIComponent(id)}`); }
  catch(e){ toast('Could not open that note: '+e.message); advOwnReady(); return; }
  let text=String(note.body||'').replace(/<!--[\s\S]*?-->/g,'').trim();
  if(!text){ toast('That note is empty — pick another'); advOwnReady(); return; }
  if(text.length>12000){ text=text.slice(0,12000); toast('Long note — only its first part is used for grading'); }
  advQuiet();
  adv.own={question, concept:question.slice(0,80), cid, text, title:note.title||'Untitled'};
  $('#advCourse').textContent=`Your question · graded against “${adv.own.title}”`;
  $('#advQ').textContent=question;
  $('#advTags').innerHTML='<span class="tag">your question</span>';
  $('#advOwn').classList.add('bar'); $('#advOwnOff').hidden=false;
  if(!(adv.own.concept in adv.mastery)) adv.mastery[adv.own.concept]='untested';
  advRender(); advOwnReady();
  $('#advType').focus();
  advSpeak(question);
}
function advOwnOff(){
  if(!adv.own) return;
  adv.own=null; adv.q=null;
  $('#advOwn').classList.remove('bar'); $('#advOwnOff').hidden=true;
  $('#advTags').innerHTML=''; $('#advCourse').textContent=C().name;
  $('#advQ').textContent='Press Start and it will ask you the first question.';
}
$('#advOwnQ').addEventListener('input',advOwnReady);
$('#advOwnQ').addEventListener('keydown',e=>{ if(e.key==='Enter'){ e.preventDefault(); advOwnStart(); } });
$('#advOwnRef').addEventListener('change',advOwnReady);
$('#advOwnGo').onclick=advOwnStart;
$('#advOwnOff').onclick=()=>advNext();
$('#advOwnMic').onclick=()=>{
  if(!ASR){ toast('Dictation needs Chrome — type your question instead'); return; }
  if(advListening){ advRecog.stop(); return; }
  advQuiet();
  micOwner('#advOwnMic','#advOwnQ','🎙',()=>advOwnReady());
  try{ advRecog.start(); advListening=true; $('#advOwnMic').setAttribute('aria-pressed','true'); $('#advOwnMic').textContent='●'; }catch(e){}
};
/* ---- Arena: the ladder and the courtroom. Both feed the same cards as everything else. ---- */
const RUNGS=15;   // asked for; the ladder is drawn from what the course can actually supply
const safeRungs=n=>n<6?[] :[...new Set([Math.ceil(n/3),Math.ceil(2*n/3),n])].filter(x=>x>0);
const law={q:[],i:0,used:{fifty:false,hint:false,skip:false},helped:false,over:false};

function arTab(which){
  $('#arTabLaw').setAttribute('aria-pressed',which==='law'); $('#arTabCourt').setAttribute('aria-pressed',which==='court');
  $('#arLawyer').hidden=which!=='law'; $('#arCourt').hidden=which!=='court'; $('#lawStart').hidden=which!=='law';
  localStorage.setItem('cf.arena',which);
  if(which==='court') loadCourtCases();
}
$('#arTabLaw').onclick=()=>arTab('law'); $('#arTabCourt').onclick=()=>arTab('court');

function ladder(){
  const el=$('#ladder'); el.innerHTML='';
  if(!law.q.length){ el.innerHTML='<div class="small muted">Press Start — the ladder is as long as the questions your cards can fill, up to '+RUNGS+'.</div>'; return; }
  const total=law.q.length, safe=safeRungs(total);
  for(let n=1;n<=total;n++){
    const d=document.createElement('div');
    d.className='rung'+(safe.includes(n)?' safe':'')+(n<law.i+1?' done':'')+(n===law.i+1&&!law.over?' at':'');
    d.innerHTML=`<span class="rn">${n}</span><span>${safe.includes(n)?'safe':''}</span>`;
    el.appendChild(d);
  }
}

function lawLifelines(on){
  $('#lifeFifty').disabled=!on||law.used.fifty;
  $('#lifeHint').disabled=!on||law.used.hint;
  $('#lifeSkip').disabled=!on||law.used.skip;
}

async function lawStart(){
  law.i=0; law.over=false; law.used={fifty:false,hint:false,skip:false};
  $('#lawHint').textContent=''; $('#lawQ').textContent='Writing fifteen questions from your cards…'; $('#lawOpts').innerHTML='';
  try{ law.q=await post(`/courses/${cid}/quiz`,{count:RUNGS}); }
  catch(e){ $('#lawQ').textContent='Could not write questions: '+e.message; return; }
  if(!law.q.length){ $('#lawQ').textContent='No cards yet — make some in Recall first.'; return; }
  ladder(); lawShow();
}

function lawShow(){
  const it=law.q[law.i];
  if(!it){ return lawEnd(true); }
  law.helped=false;
  $('#lawState').textContent=`Question ${law.i+1} of ${law.q.length}`;
  $('#lawHint').textContent='';
  $('#lawQ').textContent=it.question;
  const letters='ABCD';
  $('#lawOpts').innerHTML=it.options.map((o,i)=>`<button class="lawopt" data-opt="${i}"><span class="lt">${letters[i]}</span><span>${esc(o)}</span></button>`).join('');
  $('#lawOpts').querySelectorAll('.lawopt').forEach(b=>b.onclick=()=>lawAnswer(b,it));
  lawLifelines(true); ladder();
}

async function lawAnswer(btn,it){
  const chosen=it.options[+btn.dataset.opt], right=chosen===it.correct;
  $('#lawOpts').querySelectorAll('.lawopt').forEach(x=>{ x.disabled=true; x.onclick=null; });
  btn.dataset.state='picked';
  lawLifelines(false);
  await new Promise(r=>setTimeout(r,matchMedia('(prefers-reduced-motion: reduce)').matches?120:650));
  $('#lawOpts').querySelectorAll('.lawopt').forEach(x=>{
    const v=it.options[+x.dataset.opt];
    if(v===it.correct) x.dataset.state='right'; else if(x===btn) x.dataset.state='wrong';
  });
  // A miss always comes back. A win only counts as knowing it if no lifeline carried you.
  try{ if(!right) await post(`/cards/${it.id}/review`,{rating:0});
       else if(!law.helped) await post(`/cards/${it.id}/review`,{rating:2}); }catch(e){}
  setTimeout(()=>{
    if(!right) return lawEnd(false);
    law.i++; if(law.i>=law.q.length) return lawEnd(true);
    lawShow();
  }, 900);
}

function lawEnd(won){
  law.over=true; ladder(); lawLifelines(false);
  const reached=law.i;
  const safe=[...safeRungs(law.q.length||RUNGS)].reverse().find(n=>n<=reached)||0;
  $('#lawOpts').innerHTML='';
  $('#lawState').textContent=won?'Cleared':'Out';
  $('#lawQ').textContent = won
    ? `All ${law.q.length} — clean sweep. Nothing from this run comes back early.`
    : `Out at question ${reached+1}. You keep question ${safe||0}. That card is already back in your queue.`;
}

$('#lawStart').onclick=lawStart;
$('#lifeFifty').onclick=()=>{
  const it=law.q[law.i]; if(!it) return;
  law.used.fifty=true; law.helped=true; lawLifelines(true);
  const wrong=[...$('#lawOpts').querySelectorAll('.lawopt')].filter(b=>it.options[+b.dataset.opt]!==it.correct);
  wrong.sort(()=>Math.random()-0.5).slice(0,2).forEach(b=>{ b.dataset.state='gone'; b.disabled=true; b.onclick=null; });
};
$('#lifeHint').onclick=async()=>{
  const it=law.q[law.i]; if(!it) return;
  law.used.hint=true; law.helped=true; lawLifelines(true);
  $('#lawHint').textContent='Asking the tutor…';
  try{ const r=await post(`/courses/${cid}/hint`,{question:it.question,options:it.options}); $('#lawHint').textContent='💡 '+r.hint; }
  catch(e){ $('#lawHint').textContent='No hint available just now.'; }
};
$('#lifeSkip').onclick=()=>{
  if(!law.q[law.i]) return;
  law.used.skip=true; law.i++;
  if(law.i>=law.q.length) return lawEnd(true);
  lawShow();
};

/* ---- Courtroom ---- */
const court={case:null,hearing:null,qi:0,busy:false,kept:0};

/* The server turns a missed bench question into a card and returns when it falls due. Until now the
   page dropped that, so a hearing could tell you that you were wrong without ever telling you it had
   done anything about it. Phrased the way the rest of the app talks about a due card. */
function dueWord(iso){
  if(!iso) return '';
  const d=new Date(iso+'T00:00:00'); if(isNaN(d)) return '';
  const t=new Date(); t.setHours(0,0,0,0);
  const days=Math.round((d-t)/864e5);
  if(days<=0) return 'due today';
  if(days===1) return 'due tomorrow';
  return 'due '+d.toLocaleDateString('en-GB',{day:'numeric',month:'short'});
}

async function loadCourtCases(){
  const el=$('#courtCases');
  try{
    const cs=await api(`/courses/${cid}/cases`);
    if(!cs.length){ el.innerHTML='<div class="small muted">No cases yet — they appear once your notes name cases in *italics*.</div>'; return; }
    el.innerHTML=cs.map(c=>`<button data-case="${esc(c.name)}"><b>${esc(c.name)}</b>${c.cite?` <span class="muted">${esc(c.cite)}</span>`:''}</button>`).join('');
    el.querySelectorAll('button[data-case]').forEach(b=>b.onclick=()=>openCase(b.dataset.case));
  }catch(e){ el.innerHTML='<div class="small muted">Could not read your cases.</div>'; }
}

async function openCase(name){
  court.case=name; court.qi=0; court.hearing=null; court.kept=0;
  $('#courtLog').innerHTML=''; $('#courtHolding').innerHTML='';
  $('#courtWho').textContent='Preparing the hearing…'; $('#benchQ').textContent='…';
  try{ court.hearing=await post(`/courses/${cid}/court`,{case:name}); }
  catch(e){ $('#courtWho').textContent=''; $('#benchQ').textContent=e.message||'Could not build the hearing.'; return; }
  const h=court.hearing;
  $('#courtWho').innerHTML=`<b>${esc(h.case)}</b>${h.court?' · '+esc(h.court):''}${h.year?' · '+esc(h.year):''}${h.parties?' — '+esc(h.parties):''}`;
  if(h.issue) courtSay('tutor','The issue: '+h.issue);
  if(h.for) courtSay('tutor','You appear for: '+h.for);
  benchAsk();
}

function courtSay(who,text){
  const d=document.createElement('div'); d.className='advb '+who; d.textContent=text;
  const l=$('#courtLog'); l.appendChild(d); l.scrollTop=l.scrollHeight; return d;
}

function benchAsk(){
  const h=court.hearing; if(!h) return;
  const q=h.bench[court.qi];
  if(!q){ $('#benchQ').textContent='The bench has heard enough.';
    if(h.holding) $('#courtHolding').innerHTML=`<div class="holding"><b>What the court actually held</b><div>${esc(h.holding)}</div></div>`;
    if(court.kept) $('#courtHolding').insertAdjacentHTML('beforeend',
      `<div class="kepttally small muted">${court.kept===1?'One gap is':court.kept+' gaps are'} waiting in <a href="#recall" data-nav="recall">Recall</a>.</div>`);
    return; }
  $('#benchQ').textContent=q;
  advSpeak && advSpeak(q);
}

async function courtReply(text){
  text=(text||'').trim();
  if(!text||court.busy||!court.hearing) return;
  const q=court.hearing.bench[court.qi]; if(!q) return;
  court.busy=true; const b0=courtSay('me',text); $('#courtType').value='';
  const think=courtSay('tutor','…');
  try{
    const g=await post(`/courses/${cid}/court/reply`,{case:court.case,question:q,answer:text});
    think.remove();
    const b=courtSay('tutor','');
    b.innerHTML=`<div class="verdict v-${g.mastery}">${esc(g.verdict)}</div>${esc(g.spoken)}`;
    // g.due is present only when the grader found a gap worth carrying: the card is already written.
    if(g.due){ court.kept++;
      b.insertAdjacentHTML('beforeend',`<span class="kept">Kept as a card — <b>${esc(dueWord(g.due))}</b></span>`); }
    if(advSpeak) await advSpeak(g.spoken);   // the verdict finishes before the bench moves on
    court.qi++; setTimeout(benchAsk,700);
  }catch(e){ think.remove();
    // Give the submission back. It was cleared before the request, so a 502 used to lose a long
    // answer outright and the only way forward was to say the whole thing again.
    $('#courtType').value=text; b0 && b0.remove();
    toast('The bench did not respond — your submission is back in the box','warn'); }
  court.busy=false;
}
$('#courtSend').onclick=()=>courtReply($('#courtType').value);
$('#courtType').addEventListener('keydown',e=>{ if(e.key==='Enter') courtReply($('#courtType').value); });
$('#courtMic').onclick=()=>{
  if(!ASR){ toast('Speaking needs Chrome — type instead'); return; }
  if(advListening){ advRecog.stop(); return; }
  advQuiet();
  micOwner('#courtMic','#courtType','🎙 Submit',courtReply);
  try{ advRecog.start(); advListening=true; $('#courtMic').setAttribute('aria-pressed','true'); $('#courtMic').textContent='● Listening'; }catch(e){}
};

function loadArena(){ arTab(localStorage.getItem('cf.arena')||'law'); ladder();
  const c=C(); if(c) document.querySelectorAll('.p3course').forEach(e=>e.textContent=c.name); }   // C() is undefined until a course exists

/* ---- Arena in 3D: the player (/play/, signed-in only) in a full-screen frame. Back to Arena, Escape and browser Back all close it. ---- */
const P3={law:['Who Wants to Be a Lawyer — 3D','lawyer','#play3dLaw'],court:['Courtroom — 3D','','#play3dCourt']};
let p3Open=false, p3Which='law';
function p3Src(){
  const q=new URLSearchParams({course:cid});
  if(P3[p3Which][1]) q.set('mode',P3[p3Which][1]);
  if($('#play3dLow').checked) q.set('quality','low');
  if(matchMedia('(prefers-reduced-motion: reduce)').matches) q.set('reduced','1');
  return '/play/player/index.html?'+q;
}
// A fresh frame per visit, removed on close: changing an iframe's src would add entries to this page's Back history.
function p3Frame(){
  const f=document.createElement('iframe'); f.id='play3dFrame'; f.title='Arena in 3D'; f.allow='autoplay; fullscreen'; f.src=p3Src();
  $('#play3dStage').replaceChildren(f); f.focus();
}
const p3Behind=on=>['.app','#focusBtn','#timer'].forEach(s=>{ const el=document.querySelector(s); if(el) el.inert=on; });
function open3d(which){
  p3Which=which;
  $('#play3dMode').textContent=P3[which][0]; $('#play3dCourse').textContent=C().name;
  $('#play3d').hidden=false; p3Behind(true);
  if(!p3Open){ p3Open=true; history.pushState({cf3d:1},'','#arena-3d'); }
  p3Frame();
}
function close3d(fromHistory){
  if(!p3Open) return;
  p3Open=false;
  if(!fromHistory && history.state && history.state.cf3d) history.back();
  $('#play3dStage').replaceChildren(); $('#play3d').hidden=true; p3Behind(false);
  const b=$(P3[p3Which][2]); if(b) b.focus();
}
$('#play3dLaw').onclick=()=>open3d('law'); $('#play3dCourt').onclick=()=>open3d('court');
$('#play3dBack').onclick=()=>close3d(false);
$('#play3dLow').checked=localStorage.getItem('cf.play3d.low')==='1';
$('#play3dLow').onchange=e=>{ localStorage.setItem('cf.play3d.low',e.target.checked?'1':'0'); if(p3Open) p3Frame(); };
window.addEventListener('popstate',()=>close3d(true));
window.addEventListener('message',e=>{ if(e.origin===location.origin && e.data && e.data.type==='cf-play-exit') close3d(false); });
document.addEventListener('keydown',e=>{ if(e.key==='Escape' && p3Open){ e.preventDefault(); close3d(false); } });
if(location.hash==='#arena-3d') history.replaceState(null,'',location.pathname+location.search);

/* ---- recorder ---- */
let rec=null, recId=null, recStart=0, recChunks=[], recTimer=null;
async function loadRecIds(){ if(!nid){recIds=[];return} const all=await api(`/notes/${nid}/recordings?all=1`); recIds=all.map(r=>r.id) }
async function loadRecs(){ const box=$('#recList'); box.innerHTML=''; if(!nid) return; await loadRecIds(); const rs=await api(`/notes/${nid}/recordings`);
  rs.forEach((r,i)=>{ const a=document.createElement('audio'); a.controls=true; a.preload='none'; a.src=`/api/recordings/${r.id}/audio`; a.dataset.r=r.id; a.title=`Recording ${i+1} · ${fmt(r.seconds)}`; box.appendChild(a);
    const tr=document.createElement('button'); tr.className='btn small'; tr.textContent='Transcribe'; tr.title='Google Speech-to-Text (about €0.016 per minute of audio)'; tr.onclick=()=>transcribe(r.id,tr); box.appendChild(tr);
    api(`/recordings/${r.id}/transcribe`).then(s=>{ if(s.status==='running'||s.status==='queued') transcribe(r.id,tr,true); else if(s.status==='done'){ tr.textContent='Transcribed'; if(s.collected){ toast('Transcript collected from Google Cloud'); loadNotes() } } }).catch(()=>{});
    const x=document.createElement('button'); x.className='btn small ghost'; x.textContent='×'; x.title='Delete recording'; x.onclick=async()=>{ if(confirm('Delete this recording?')){ await del(`/recordings/${r.id}`); loadRecs() } }; box.appendChild(x) }) }
async function transcribe(rid,btn,resume){ btn.disabled=true; btn.textContent='Transcribing…';
  if(!resume){ toast('Transcribing in Google Cloud — reopen this note any time to collect the transcript');
    try{ await post(`/recordings/${rid}/transcribe`); }catch(e){ btn.disabled=false; btn.textContent='Transcribe'; toast('Could not start: '+e.message); return } }
  const tick=setInterval(async()=>{ const s=await api(`/recordings/${rid}/transcribe`);
    if(s.status==='done'){ clearInterval(tick); btn.textContent='Transcribed'; toast('Transcript added as a Live capture — press Reconcile with lecture'); loadNotes() }
    else if(s.status==='failed'){ clearInterval(tick); btn.disabled=false; btn.textContent='Transcribe'; toast('Transcription failed: '+s.error) } },3000) }
function playAt(r,s){ const a=document.querySelector(`audio[data-r="${r}"]`); if(!a){toast('Recording not found');return} a.currentTime=Math.max(0,s-20); a.play() }
function watchTranscript(rid){ const t0=Date.now(); const tick=setInterval(async()=>{ let s; try{ s=await api(`/recordings/${rid}/transcribe`) }catch{ return }
    if(s.status==='running'||s.status==='queued'){ $('#recState').textContent=(s.stage==='cleaning'?'Cleaning names ':'Transcribing in Google Cloud — reopen this note any time to collect · ')+fmt((Date.now()-t0)/1000); return }
    clearInterval(tick); $('#recState').textContent='';
    if(s.status==='done'){ await loadNotes(); offerReconcile() } else if(s.status==='failed'){ toast('Transcription failed: '+s.error) } },3000) }
function offerReconcile(){ const bar=$('#txBar'); bar.hidden=false; }
$('#recBtn').onclick=async()=>{ if(rec){ rec.stop(); return } if(!nid){$('#newNote').click(); await new Promise(r=>setTimeout(r,500))}
  let stream; try{ stream=await navigator.mediaDevices.getUserMedia({audio:true}) }catch(e){ toast('Microphone blocked — allow it in the browser','warn'); return }
  const r=await post(`/notes/${nid}/recordings/start`); recId=r.id; recStart=Date.now(); recChunks=[]; await loadRecIds();
  rec=new MediaRecorder(stream,{mimeType:'audio/webm'}); rec.ondataavailable=e=>{ if(e.data.size) recChunks.push(e.data) };
  rec.onstop=async()=>{ clearInterval(recTimer); stream.getTracks().forEach(t=>t.stop()); const blob=new Blob(recChunks,{type:'audio/webm'}); const fd=new FormData(); fd.append('audio',blob,'rec.webm'); fd.append('seconds',String((Date.now()-recStart)/1000));
    fd.append('auto',$('#autoTx').checked?'1':'0'); const rid=recId;
    $('#recState').textContent='Saving…'; let ok=false; try{ await api(`/recordings/${rid}/finish`,{method:'POST',body:fd}); ok=true; toast($('#autoTx').checked?'Saved — transcribing in Google Cloud':'Recording saved to this note'); }catch(e){ toast('Could not save recording: '+e.message) }
    rec=null; recId=null; $('#recBtn').classList.remove('on'); $('#recBtn').textContent='● Record'; $('#recState').textContent=''; loadRecs();
    if(ok&&$('#autoTx').checked) watchTranscript(rid) };

  rec.start(1000); $('#recBtn').classList.add('on'); $('#recBtn').textContent='■ Stop'; recTimer=setInterval(()=>{$('#recState').textContent='REC '+fmt((Date.now()-recStart)/1000)},1000); toast('Recording — each new line links to the audio'); };
window.addEventListener('beforeunload',e=>{ if(rec){ e.preventDefault(); e.returnValue='' } });
let liveT=null;
async function showNote(){ const v=$('#noteView'), t=$('#noteBody'), l=$('#noteLive2'), w=$('#editwrap'); const body=rawBody(); if(!body.trim()&&noteMode==='read') noteMode='edit';
  v.hidden=noteMode!=='read'; $('#readbar').hidden=noteMode!=='read'; $('#tagbar').hidden=noteMode==='read'; w.hidden=noteMode==='read'; t.hidden=noteMode==='read'; l.hidden=noteMode!=='split';
  if(noteMode==='read'){ await paint(v,body); v.scrollTop=0 } if(noteMode==='split'){ await paint(l,body) }
  ['read','split','edit'].forEach(m=>$('#note'+m[0].toUpperCase()+m.slice(1)).setAttribute('aria-pressed',noteMode===m)); }
$('#noteSplit').onclick=()=>{noteMode='split';localStorage.setItem('cf.noteMode','split');showNote();$('#noteBody').focus()};
$('#noteBody').addEventListener('input',()=>{ if(noteMode!=='split') return; clearTimeout(liveT); liveT=setTimeout(async()=>{const l=$('#noteLive2'); const atEnd=l.scrollTop+l.clientHeight>=l.scrollHeight-40; await paint(l,rawBody()); if(atEnd) l.scrollTop=l.scrollHeight},350) });
// insert at cursor
function tagAt(t,tag){ const s=t.selectionStart; const ls=t.value.lastIndexOf('\n',s-1)+1; const pre=(t.value.slice(ls).match(/^\s*(?:[-*]|\d+\.)\s?/)||[''])[0]; const at=ls+pre.length;
  t.setRangeText(tag,at,at,'preserve'); t.selectionStart=t.selectionEnd=Math.max(s+tag.length,at+tag.length); t.dispatchEvent(new Event('input')); t.focus() }
function ins(t,text,wrapEnd){ const s=t.selectionStart,e=t.selectionEnd,sel=t.value.slice(s,e); const out=wrapEnd?text+sel+wrapEnd:text+sel; t.setRangeText(out,s,e,'end'); if(wrapEnd&&!sel) t.selectionStart=t.selectionEnd=s+text.length; t.dispatchEvent(new Event('input')); t.focus() }
$('#bulletBtn').onclick=()=>{const t=$('#noteBody'); const s=t.selectionStart; const ls=t.value.lastIndexOf('\n',s-1)+1; const rest=t.value.slice(ls); const m=rest.match(/^(\s*)(- )?/);
  if(m[2]){ t.setRangeText('',ls+m[1].length,ls+m[1].length+2,'preserve'); t.selectionStart=t.selectionEnd=Math.max(ls,s-2) } else { t.setRangeText('- ',ls+m[1].length,ls+m[1].length,'preserve'); t.selectionStart=t.selectionEnd=s+2 } t.dispatchEvent(new Event('input')); t.focus()};
document.querySelectorAll('[data-ins]').forEach(b=>b.onclick=()=>tagAt($('#noteBody'),b.dataset.ins));
// smart keys: list continuation, tab indent, shortcuts
$('#noteBody').addEventListener('keydown',e=>{ const t=e.target; const s=t.selectionStart; const ls=t.value.lastIndexOf('\n',s-1)+1; const line=t.value.slice(ls,s);
  if(e.key==='Enter'&&!e.shiftKey&&rec&&line.trim()&&!/<!--r:|⏵\d+·/.test(line)){ const sec=Math.round((Date.now()-recStart)/1000); const i=recIds.indexOf(recId); t.setRangeText(i<0?` <!--r:${recId}:${sec}-->`:` ⏵${i+1}·${fmt(sec)}`,s,s,'end'); }
  if(e.key==='Enter'&&!e.shiftKey){ const s=t.selectionStart; const ls=t.value.lastIndexOf('\n',s-1)+1; const line=t.value.slice(ls,s); const m=line.match(/^(\s*)([-*]|\d+\.)\s(\[[^\]]*\]\s)?(.*)$/); if(m){ e.preventDefault();
      if(!m[4].trim()){ t.setRangeText('',ls,s,'end'); t.setRangeText('\n',t.selectionStart,t.selectionStart,'end') }   // empty item ends list
      else { const mark=/\d+\./.test(m[2])?(parseInt(m[2])+1)+'.':m[2]; t.setRangeText('\n'+m[1]+mark+' ',s,s,'end') }
      t.dispatchEvent(new Event('input')); return } }
  if(e.key===' '){ const body=line.replace(/^\s*(?:[-*]|\d+\.)\s?/,''); const SH={'lec':'[LEC] ','l':'[LEC] ','!':'[!] ','p':'[P] ','?':'?? ','v':'?? '}; if(body.toLowerCase()==='t'){ e.preventDefault(); const now=new Date(); t.setRangeText(`[${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}] `,s-1,s,'end'); t.dispatchEvent(new Event('input')); return }
    if(SH[body.toLowerCase()]){ e.preventDefault(); const at=s-body.length; const hasBullet=/^\s*(?:[-*]|\d+\.)\s?/.test(line); const ind=(line.match(/^\s*/)||[''])[0];
      t.setRangeText((hasBullet?'':'- ')+SH[body.toLowerCase()],hasBullet?at:ls+ind.length,s,'end'); t.dispatchEvent(new Event('input')); return } }
  if(e.key==='Tab'){ e.preventDefault(); if(e.shiftKey){ if(t.value.slice(ls,ls+2)==='  '){ t.setRangeText('',ls,ls+2,'preserve'); t.selectionStart=t.selectionEnd=Math.max(ls,s-2)} } else { t.setRangeText('  ',ls,ls,'preserve'); t.selectionStart=t.selectionEnd=s+2 } t.dispatchEvent(new Event('input')); return }
  if((e.metaKey||e.ctrlKey)&&!e.shiftKey){ const k=e.key.toLowerCase(); const tags={'1':'[LEC] ','2':'[!] ','3':'[P] ','4':'?? '};
    if(tags[k]){ e.preventDefault(); tagAt(t,tags[k]); return }
    if(k==='b'){ e.preventDefault(); ins(t,'**','**'); return } if(k==='k'){ e.preventDefault(); ins(t,'*','*'); return } } });
$('#noteLive').onclick=async()=>{ if(!nid){$('#newNote').click();return} const t=$('#noteBody'); const stamp=new Date().toLocaleDateString('en-GB',{day:'numeric',month:'short'});
  const block=`\n\n## Live capture — ${stamp}\n[LEC] `; t.value=(t.value.replace(/\s+$/,''))+block; noteMode='edit'; await showNote(); t.focus(); t.selectionStart=t.selectionEnd=t.value.length; t.scrollTop=t.scrollHeight; scheduleSave(); };
$('#noteRead').onclick=()=>{noteMode='read';localStorage.setItem('cf.noteMode','read');showNote()};
if(!['read','split','edit'].includes(noteMode)) noteMode='read';
$('#noteEdit').onclick=()=>{noteMode='edit';localStorage.setItem('cf.noteMode','edit');showNote();$('#noteBody').focus()};
$('#notePrint').onclick=async()=>{ const was=noteMode; noteMode='read'; await showNote();
  // the title lives in an <input> outside .noteview, so print never saw it. Put a header inside.
  const head=document.createElement('div'); head.className='printhead';
  const course=($('#courseSel')&&$('#courseSel').selectedOptions[0]||{}).textContent||'';
  head.textContent=$('#noteTitle').value||'Untitled';
  const meta=document.createElement('span'); meta.className='meta';
  meta.textContent=[course, new Date().toLocaleDateString('en-GB',{day:'numeric',month:'long',year:'numeric'})].filter(Boolean).join(' · ');
  head.appendChild(meta);
  const v=$('#noteView'); v.insertBefore(head, v.firstChild);
  // .printing scopes the print block; without it Cmd+P anywhere else printed a blank sheet.
  document.body.classList.add('printing');
  setTimeout(()=>{ try{ window.print() } finally {
    document.body.classList.remove('printing'); head.remove(); noteMode=was; showNote() } },150) };
/* The autosave had no catch. A rejected put left #noteStatus reading '…' for the rest of the
   session — no toast, nothing in the UI — so a dropped connection during a lecture lost the whole
   capture while the screen still said everything was fine. It has to fail loudly and keep trying.
   The unsaved text lives where it always did, in the textarea: CLAUDE.md keeps note state out of
   localStorage, and a copy there would not survive the tab closing anyway. */
async function saveNote(){
  if(!nid) return false;
  const st=$('#noteStatus');
  try{
    await put(`/notes/${nid}`,{title:$('#noteTitle').value||'Untitled',body:rawBody()});
    delete st.dataset.state; st.textContent='Saved '+new Date().toLocaleTimeString(); return true;
  }catch(e){
    st.dataset.state='failed';
    st.innerHTML=`Not saved — ${esc(e.message||'no connection')}. Your text is still here. `;
    const b=document.createElement('button'); b.type='button'; b.className='btn small'; b.textContent='Retry';
    b.onclick=saveNote; st.appendChild(b);
    return false;
  }
}
function scheduleSave(){ if(!nid) return;
  // Keep the failure visible while retrying, rather than flicking back to a reassuring '…'
  const st=$('#noteStatus'); if(st.dataset.state!=='failed') st.textContent='…';
  clearTimeout(saveT); saveT=setTimeout(saveNote,700); }
$('#noteTitle').addEventListener('input',scheduleSave); $('#noteBody').addEventListener('input',scheduleSave);
let draftScope='master';
const setScope=s=>{draftScope=s;$('#scopeMaster').setAttribute('aria-pressed',s==='master');$('#scopeWeek').setAttribute('aria-pressed',s==='week');$('#draftWeek').hidden=s!=='week';if(s==='week')$('#draftWeek').focus()};
$('#scopeMaster').onclick=()=>setScope('master'); $('#scopeWeek').onclick=()=>setScope('week');
$('#draftNote').onclick=async()=>{const b=$('#draftNote'); const week=draftScope==='week'?$('#draftWeek').value.trim():''; if(draftScope==='week'&&!week){toast('Type a week number first');$('#draftWeek').focus();return}
  b.disabled=true; b.textContent='Drafting…'; toast(week?`Drafting Week ${week} from its ticked files — 20–60 s`:'Drafting master notes from all ticked files — 20–60 s');
  try{const r=await post(`/courses/${cid}/notes/draft`,{week,diagrams:$('#draftViz').checked}); nid=r.id; noteMode='read'; toast(`Drafted from ${r.files.length} file(s)`); loadNotes()}catch(e){toast('Draft failed: '+e.message)}
  b.disabled=false; b.textContent='Draft from files'};
$('#newNote').onclick=async()=>{const r=await post(`/courses/${cid}/notes`,{title:'Lecture notes '+new Date().toLocaleDateString(),body:''});nid=r.id;noteMode='edit';loadNotes();setTimeout(()=>$('#noteBody').focus(),150)};
$('#delNote').onclick=async()=>{if(nid&&confirm('Delete this note?')){await del(`/notes/${nid}`);nid=null;loadNotes()}};
$('#noteContinue').onclick=async()=>{ if(!nid) return; const b=$('#noteContinue'); b.disabled=true; b.textContent='Finishing…'; toast('Finishing the note from where it stopped…');
  try{ await post(`/notes/${nid}/continue`); toast('Appended the rest'); const n=await api(`/notes/${nid}`); $('#noteBody').value=toDisplay(n.body); noteMode='read'; showNote(); loadNotes(); }catch(e){ toast('Continue failed: '+e.message) }
  b.disabled=false; b.textContent='Continue'; };
$('#noteReconcile').onclick=async()=>{ if(!nid) return; const b=$('#noteReconcile'); clearTimeout(saveT);
  // Reconcile reads the note back from the server, so an unsaved edit would be silently reconciled away
  if(!await saveNote()){ toast('Not reconciled — the note could not be saved first','warn'); return }
  if(!/^##\s+Live capture/m.test(rawBody())){ toast('No Live capture section yet — press + Lecture capture and type what was said'); return }
  b.disabled=true; b.textContent='Reconciling…'; toast('Comparing capture against the draft and files — 30–90 s');
  try{ const r=await post(`/notes/${nid}/reconcile`); nid=r.id; noteMode='read'; toast('Reconciled — original kept, corrected copy opened'); loadNotes() }catch(e){ toast('Reconcile failed: '+e.message) }
  b.disabled=false; b.textContent='Reconcile with lecture' };
$('#noteToTutor').onclick=async()=>{if(!nid) return; clearTimeout(saveT);
  if(!await saveNote()){ toast('Not sent — the note could not be saved first','warn'); return }
  try{ await post(`/notes/${nid}/to-file`); toast('Snapshot added to Files — ask the tutor to reconcile it') }
  catch(e){ toast('Could not add the snapshot: '+e.message,'warn') } };

/* recall */
let queue=[], cur=null, flipped=false;
let rmode='cards', qStart=0, qTotal=0, rweek='', rweak=false;
async function loadWeekDir(){ const m=await api(`/courses/${cid}/recall-map`); const d=$('#weekdir');
  const chip=(label,val,due,ready,extra='')=>`<div class="wk ${extra} ${rweek===val&&!rweak?'sel':''}" data-wk="${val}"><span class="rd ${ready}"></span>${label}${due!=null?`<span class="n">${due} due</span>`:''}</div>`;
  let html=chip('All','',m.weeks.reduce((a,w)=>a+w.due,0),'ready');
  m.weeks.filter(w=>w.week).forEach(w=>{ const r=w.ready?'ready':(w.indexed?'partial':''); html+=chip('Week '+w.week,w.week,w.due,r); });
  if(m.weak) html+=`<div class="wk weak ${rweak?'sel':''}" data-weak="1">Weak cards<span class="n">${m.weak}</span></div>`;
  d.innerHTML=html;
  d.querySelectorAll('[data-wk]').forEach(b=>b.onclick=()=>{ rweak=false; rweek=b.dataset.wk; loadRecall(); });
  const wb=d.querySelector('[data-weak]'); if(wb) wb.onclick=()=>{ rweak=true; rweek=''; loadRecall(); }; keyable(d); }
function scopeQS(){ const p=new URLSearchParams(); if(rweek)p.set('week',rweek); if(rweak)p.set('weak','1'); return p.toString()?('&'+p.toString()):''; }
async function loadRecall(){ const fs=await api(`/courses/${cid}/files`); $('#genFrom').innerHTML='<option value="">From all ticked files</option>'+fs.filter(f=>f.kind!=='image').map(f=>`<option value="${f.id}">${esc(f.name)}</option>`).join('');
  loadWeekDir();
  const all=await api(`/courses/${cid}/cards?x=1${scopeQS()}`); queue=await api(`/courses/${cid}/cards?due=1${scopeQS()}`);
  const scope = rweak?'weak cards':(rweek?('Week '+rweek):'all weeks');
  $('#recallSub').textContent=`${C().name} · ${scope} · ${queue.length} due · ${all.length} total`; qStart=queue.length; renderAll(all);
  if(rmode==='cards') nextCard(); else startQuiz(); }
function setRMode(m){ rmode=m; $('#mCards').setAttribute('aria-pressed',m==='cards'); $('#mQuiz').setAttribute('aria-pressed',m==='quiz');
  $('#cardStage').hidden=m!=='cards'; $('#quizStage').hidden=m!=='quiz'; loadRecall(); }
$('#mCards').onclick=()=>setRMode('cards'); $('#mQuiz').onclick=()=>setRMode('quiz');
function rprog(done,total){ $('#rprog').firstElementChild.style.width=total?(done/total*100)+'%':'0'; }
function nextCard(){ cur=queue.shift()||null; flipped=false; $('#ratings').hidden=true; $('#fc').classList.remove('flipped');
  rprog(qStart-queue.length-(cur?1:0), qStart||1);
  if(!cur){ $('#fc').hidden=true; $('#rdone').hidden=false; $('#rdone').innerHTML='<b>Queue clear</b><span>Generate cards from a file, or come back tomorrow.</span>'; rprog(1,1); return; }
  $('#fc').hidden=false; $('#rdone').hidden=true; $('#fcFront').textContent=cur.front; $('#fcBack').textContent=cur.back; }
function flipCard(){ if(!cur) return; flipped=!flipped; $('#fc').classList.toggle('flipped',flipped); $('#ratings').hidden=!flipped; }
$('#fc').onclick=flipCard; $('#fc').onkeydown=e=>{ if(e.key===' '||e.key==='Enter'){e.preventDefault();flipCard()} };
document.addEventListener('keydown',e=>{ if(!document.querySelector('#recall.active')||e.metaKey||e.ctrlKey) return;
  if(rmode==='cards'&&flipped&&'1234'.includes(e.key)){ e.preventDefault(); const b=document.querySelector(`#ratings [data-r="${+e.key-1}"]`); if(b) b.click(); }
  else if(rmode==='cards'&&e.key===' '&&!flipped){ e.preventDefault(); flipCard(); }
  else if(rmode==='quiz'&&'abcdABCD'.includes(e.key)){ const opts=document.querySelectorAll('.qopt'); const i='abcd'.indexOf(e.key.toLowerCase()); if(opts[i]&&opts[i].onclick){opts[i].click();} else if($('#qn')){$('#qn').click();} } });
document.querySelectorAll('#ratings [data-r]').forEach(b=>b.onclick=async()=>{const r=await post(`/cards/${cur.id}/review`,{rating:+b.dataset.r}); if(+b.dataset.r===0) queue.push(cur); nextCard();});
/* ---- quiz ---- */
let quiz=[], qi=0, qright=0;
async function startQuiz(){ $('#qdone').hidden=true; $('#qcard').hidden=false; $('#qcard').innerHTML='<div class="q muted">Writing questions…</div>'; rprog(0,1);
  try{ quiz=await post(`/courses/${cid}/quiz`,{count:8,week:rweek,weak:rweak?1:0}); }catch(e){ $('#qcard').innerHTML=`<div class="q muted">${esc(e.message)}</div>`; return; }
  if(!quiz.length){ $('#qcard').innerHTML='<div class="q muted">No cards yet — generate some first.</div>'; return; }
  qi=0; qright=0; qTotal=quiz.length; showQ(); }
function showQ(){ const it=quiz[qi]; rprog(qi,qTotal);
  if(!it){ $('#qcard').hidden=true; $('#qdone').hidden=false; $('#qdone').innerHTML=`You scored <b>${qright}/${qTotal}</b>. ${qright===qTotal?'Clean sweep.':'Review the ones you missed in Flashcards.'}`; rprog(1,1); return; }
  const letters='ABCD';
  $('#qcard').innerHTML=`<div class="q">${esc(it.question)}</div>`+it.options.map((o,i)=>`<button class="qopt" data-opt="${i}"><span class="lt">${letters[i]}</span>${esc(o)}</button>`).join('')+`<div class="qscore">${qi+1} of ${qTotal}</div>`;
  $('#qcard').querySelectorAll('.qopt').forEach(b=>b.onclick=async()=>{
    const chosen=it.options[+b.dataset.opt], ok=chosen===it.correct;
    $('#qcard').querySelectorAll('.qopt').forEach(x=>{ x.onclick=null; const v=it.options[+x.dataset.opt];
      if(v===it.correct) x.classList.add('correct'); else if(x===b) x.classList.add('wrong'); else x.classList.add('muted'); });
    if(ok) qright++;
    if(it.id){ post(`/cards/${it.id}/review`,{rating: ok?2:0}).catch(()=>{}); }
    const nx=document.createElement('div'); nx.className='qnext'; nx.innerHTML='<button class="btn small" id="qn">Next</button>';
    $('#qcard').appendChild(nx); $('#qn').onclick=()=>{ qi++; showQ(); }; $('#qn').focus();
  }); }
$('#genCards').onclick=async()=>{if(!cfg.has_key){toast('No Claude API key on the server — add it to .env.local and restart');return} $('#genCards').disabled=true; toast('Writing cards…'); try{const r=await post(`/courses/${cid}/cards/generate`,{file_id:$('#genFrom').value||null,count:8});toast(`${r.made} cards added`);loadRecall()}catch(e){toast('Failed: '+e.message)} $('#genCards').disabled=false;};
$('#addCard').onclick=async()=>{const f=prompt('Front'); if(!f) return; const b=prompt('Back'); if(!b) return; await post(`/courses/${cid}/cards`,{front:f,back:b,source:'manual'}); loadRecall();};
$('#showAll').onclick=()=>{$('#allCards').hidden=!$('#allCards').hidden};
function renderAll(all){ $('#cardRows').innerHTML=all.map(c=>`<tr><td>${esc(c.front)}</td><td class="small">${esc(c.back)}</td><td class="small muted">${c.week?'W'+c.week:''}</td><td class="small muted">${c.due}</td><td><button class="btn small ghost" data-delcard="${c.id}">Remove</button></td></tr>`).join(''); document.querySelectorAll('[data-delcard]').forEach(b=>b.onclick=async()=>{
    // Unconfirmed until now, in a table of small buttons. The card carries its whole review
    // history, so one stray click threw away weeks of scheduling with nothing shown.
    const c=all.find(x=>x.id===b.dataset.delcard);
    if(!confirm(`Remove this card and its review history?\n\n${c?c.front:''}`)) return;
    await del(`/cards/${b.dataset.delcard}`); toast('Card removed'); loadRecall()}); }

/* planner */
async function runPlan(replace){const b=$('#autoPlan'); b.disabled=true; $('#rePlan').disabled=true; toast('Planning…');
  try{const r=await post(`/courses/${cid}/plan`,{days:7,minutes_per_day:90,replace}); toast(`${r.added} session(s) planned`); loadPlanner()}catch(e){toast('Plan failed: '+e.message)}
  b.disabled=false; $('#rePlan').disabled=false}
$('#autoPlan').onclick=()=>runPlan(false); $('#rePlan').onclick=()=>{if(confirm('Discard unfinished sessions from today onward and plan again?')) runPlan(true)};
function sessIcon(t){ t=t.toLowerCase(); if(/pre-?read|read /.test(t))return['📖','pre-read']; if(/reconcile|lecture/.test(t))return['🎧','lecture']; if(/recall|card|drill|review/.test(t))return['🎴','recall']; if(/exam|irac|mock/.test(t))return['📝','exam']; return['•','study']; }
async function loadPlanner(){ const ss=await api('/sessions'); if(!$('#sDay').value) $('#sDay').value=new Date().toISOString().slice(0,10);
  const today=new Date().toISOString().slice(0,10);
  if(!ss.length){ $('#agenda').innerHTML='<div class="empty">Nothing planned. Use <b>Auto-plan week</b> to lay out pre-reads, reconciles and recall around your lectures.</div>'; $('#planSub').textContent='All courses'; return; }
  const days={}; ss.forEach(s=>{ (days[s.day]=days[s.day]||[]).push(s) });
  const dl=Object.keys(days).sort();
  const fmt=d=>{ const dt=new Date(d+'T00:00:00'); return [dt.toLocaleDateString('en-GB',{weekday:'long'}), dt.toLocaleDateString('en-GB',{day:'numeric',month:'short'})]; };
  $('#agenda').innerHTML=dl.map(d=>{ const g=days[d]; const [dow,date]=fmt(d); const mins=g.reduce((a,s)=>a+s.minutes,0); const done=g.filter(s=>s.done).length;
    const cls=d===today?'today':(d<today?'past':'');
    return `<div class="day ${cls}"><div class="dayhd"><span class="dow">${dow}</span><span class="date">${date}</span>${d===today?'<span class="todaymark">Today</span>':''}<span class="sum">${done}/${g.length} done · ${mins} min</span></div>`+
      g.map(s=>{ const [ic]=sessIcon(s.topic); return `<div class="sess ${s.done?'done':''}"><div class="chk" data-sess="${s.id}" title="${s.done?'Mark not done':'Mark done'}">✓</div><div class="ic">${ic}</div><div class="body"><div class="top"><span class="tp">${esc(s.topic)}</span></div><div class="meta">${esc(s.course)} · ${s.minutes} min</div></div><div class="act"><button class="btn small ghost" data-delsess="${s.id}" title="Remove">×</button></div></div>`; }).join('')+`</div>`;
  }).join('');
  const total=ss.reduce((a,s)=>a+s.minutes,0), left=ss.filter(s=>!s.done).length;
  $('#planSub').textContent=`${left} to do · ${(total/60).toFixed(1)} h planned`;
  document.querySelectorAll('[data-sess]').forEach(b=>b.onclick=async()=>{await post(`/sessions/${b.dataset.sess}/toggle`);loadPlanner()}); keyable($('#agenda'));
  document.querySelectorAll('[data-delsess]').forEach(b=>b.onclick=async()=>{
    if(!confirm(`Remove this session?\n\n${b.closest('.sess').querySelector('.tp').textContent}`)) return;
    await del(`/sessions/${b.dataset.delsess}`); loadPlanner()}); }
document.addEventListener('click',e=>{ if(e.target.id==='addToggle'){ const f=$('#addForm'); f.hidden=!f.hidden; if(!f.hidden)$('#sTopic').focus(); }});
$('#addSession').onclick=async()=>{const t=$('#sTopic').value.trim(); if(!t){toast('Give the session a topic');return} await post(`/courses/${cid}/sessions`,{day:$('#sDay').value,topic:t,minutes:+$('#sMin').value||60}); $('#sTopic').value=''; loadPlanner();};

/* progress */
async function loadCaseIndex(){ const el=$('#caseIndex'); try{ const cs=await api(`/courses/${cid}/cases`); if(!cs.length){el.innerHTML='<div class="muted">No cases yet — they appear once your notes name cases in *italics*.</div>';return}
    el.innerHTML=cs.map(c=>`<div class="ci"><b>${esc(c.name)}</b>${c.cite?` <span class="cc">${esc(c.cite)}</span>`:''} — ${c.notes.map(n=>`<a data-note="${n.id}">${esc(n.title)}</a>`).join(', ')}</div>`).join('');
    el.querySelectorAll('a[data-note]').forEach(a=>a.onclick=()=>{nid=a.dataset.note;noteMode='read';show('notes')}); keyable(el); }catch(e){ el.textContent='' } }
/* ---- study timer ---- */
let tStart=+(localStorage.getItem('cf.tStart')||0), tInt=null;
function tShow(){ const on=tStart>0; $('#timer').classList.toggle('running',on); $('#timerBtn').hidden=on; $('#timerClock').hidden=!on; $('#timerStop').hidden=!on;
  if(on){ const s=Math.floor((Date.now()-tStart)/1000); $('#timerClock').textContent=`${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`; } }
$('#timerBtn').onclick=()=>{ tStart=Date.now(); localStorage.setItem('cf.tStart',tStart); tInt=setInterval(tShow,1000); tShow(); toast('Timer started — it logs to your planner when you stop'); };
$('#timerStop').onclick=async()=>{ const mins=Math.max(1,Math.round((Date.now()-tStart)/60000)); const topic=prompt('What did you study? (logged to the planner)','Drilling '+C().name)||'Study session';
  try{ await post(`/courses/${cid}/sessions/log`,{minutes:mins,topic}); toast(`Logged ${mins} min`) }catch(e){ toast('Could not log: '+e.message) }
  tStart=0; localStorage.removeItem('cf.tStart'); clearInterval(tInt); tInt=null; tShow(); if(document.querySelector('#progress.active')) loadProgress(); };
if(tStart>0){ tInt=setInterval(tShow,1000); } tShow();
async function loadProgress(){ loadCaseIndex(); const s=await api(`/courses/${cid}/stats`); $('#progSub').textContent=C().name; $('#p-cards').textContent=`${s.cards} (${s.retained})`; $('#p-reviews').textContent=s.reviews; $('#p-time').textContent=(s.study_minutes/60).toFixed(1)+' h'; $('#p-q').textContent=s.questions_asked;
  $('#p-next').textContent=s.due?`Clear ${s.due} due cards`:(s.cards<10?'Build the deck to at least 10 cards':(s.recall_accuracy!=null&&s.recall_accuracy<70?'Accuracy under 70% — drill the weak cards with the tutor':'Ask the tutor for an IRAC case question'));}

/* init */
(async()=>{ cfg=await api('/config'); $('#dot').classList.toggle('off',!cfg.has_key); $('#dot').title=cfg.has_key?`Claude connected · auto ${cfg.cheap_model.replace('claude-','')} / ${cfg.model.replace('claude-','')}`:'No Claude API key on the server — add it to .env.local';
  $('#who').textContent=cfg.email||''; $('#who').title=$('#signOut').title=cfg.email?`Signed in as ${cfg.email}`:'';
  $('#modelSel').innerHTML='<option value="auto">Auto model</option>'+cfg.models.map(m=>`<option value="${m}">${m.replace('claude-','')}</option>`).join('');
  window.CFCHEAP=cfg.cheap_model; window.CFMODEL=cfg.model;
  window.CFVOICE=cfg.voice||{};   // every screen speaks with the same voice, not only the Advocate
  initVoice(); if('speechSynthesis' in window) speechSynthesis.onvoiceschanged=()=>{}; await loadCourses(); show(location.hash.slice(1)||localStorage.getItem('cf.screen')||'home'); })();
