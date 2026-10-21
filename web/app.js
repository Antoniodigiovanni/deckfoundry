'use strict';
let csrf, active, pending;
const $ = id => document.getElementById(id);
const escapeText = s => s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
async function api(path, data) {
  const r = await fetch(path, data ? {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify(data)} : {});
  const body = await r.json();
  if (!r.ok) throw Error(body.error || 'Request failed');
  return body;
}
function status(s) { $('status').textContent = s; }
function button(text, fn) { const b = document.createElement('button'); b.type='button'; b.textContent=text; b.onclick=()=>run(fn); return b; }
async function run(fn) { try { await fn(); } catch(e) { status(e.message); } }
async function projects() {
  const data = await api('/api/projects'); csrf=data.csrf;
  $('projects').replaceChildren(...data.projects.map(p=>button(p.name+(p.unsupported?' (branded; build unsupported)':''),()=>open(p.name,1))));
}
async function open(name, slide) {
  active = await api('/api/slide?'+new URLSearchParams({project:name,slide})); pending=null; $('applyProposal').disabled=true;
  $('proposal').textContent=''; $('reply').textContent='';
  $('heading').textContent = `${name} · ${active.base} · Slide ${slide}`;
  status(active.unsupported?'Branded project: generic build unsupported. The brand guard remains enabled.':'');
  $('slides').replaceChildren(...active.slides.map((t,i)=>button(`${i+1}. ${t}`,()=>open(name,i+1))));
  $('preview').replaceChildren(); $('fields').replaceChildren();
  active.fields.forEach((f,i)=>{
    const p=document.createElement(f.kind==='title'?'h2':'p'); p.textContent=f.text; $('preview').append(p);
    const l=document.createElement('label'); l.textContent=`${f.kind} ${i+1}`;
    const input=document.createElement('textarea'); input.value=f.text; input.maxLength=4000; input.dataset.field=i;
    l.append(input); $('fields').append(l);
  });
  $('build').disabled=active.unsupported;
  $('downloads').replaceChildren();
  for(const [label,kind,file] of [['PPTX','deck','deck.pptx'],['PDF','render','deck.pdf'],['Slide preview','html-source',`slide-${slide}.png`]]) {
    const a=document.createElement('a'); a.textContent=label; a.href=`/download/${encodeURIComponent(name)}/${active.base}/${kind}/${file}`; $('downloads').append(a);
  }
}
async function apply(ops) {
  if(!active) throw Error('Choose a slide');
  await api('/api/apply',{project:active.project,slide:active.slide,base:active.base,ops});
  await open(active.project,active.slide); await projects(); status('New version created. Build and review the output.');
}
$('editor').onsubmit=e=>{e.preventDefault(); run(async()=>{
  if(!active) throw Error('Choose a slide');
  const ops=[...$('fields').querySelectorAll('textarea')].flatMap((input,i)=>input.value===active.fields[i].text?[]:[{slide:active.slide,old:active.fields[i].old,new:escapeText(input.value)}]);
  await apply(ops);
});};
$('build').onclick=()=>run(async()=>{if(!active) throw Error('Choose a project');status('Building…');const r=await api('/api/build',{project:active.project,base:active.base});status(r.message);});
$('chat').onsubmit=e=>{e.preventDefault();run(async()=>{
  if(!active) throw Error('Choose a slide');
  pending=null; $('applyProposal').disabled=true; $('proposal').textContent='';
  const captured=active;
  const result=await api('/api/chat',{project:active.project,slide:active.slide,base:active.base,message:$('prompt').value});
  if(active!==captured) return;
  $('reply').textContent=result.message; pending=result.ops; $('proposal').textContent=JSON.stringify(pending,null,2); $('applyProposal').disabled=!pending;
});};
$('applyProposal').onclick=()=>run(()=>apply(pending));
run(projects);
