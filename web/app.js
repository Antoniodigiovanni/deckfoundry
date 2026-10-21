'use strict';
let csrf, active, pending, selected = null, dirty = false, busy = false;
const $ = id => document.getElementById(id);
async function api(path,data) {
  const r=await fetch(path,data?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(data)}:{});
  const body=await r.json(); if(!r.ok) throw Error(body.error||'Request failed'); return body;
}
function status(text){$('status').textContent=text;}
async function run(fn){if(busy)return;busy=true;document.body.classList.add('busy');for(const id of ['studio','library','chat','review'])$(id).inert=true;try{await fn();}catch(e){status(e.message);if(dirty)$('saveState').textContent='Save needed · operation failed';}finally{busy=false;document.body.classList.remove('busy');for(const id of ['studio','library','chat','review'])$(id).inert=false;}}
function button(text,fn){const b=document.createElement('button');b.type='button';b.textContent=text;b.onclick=()=>run(fn);return b;}
function mark(){clearProposal();dirty=true;$('saveState').textContent='Unsaved changes';}
function clearProposal(){pending=null;$('review').hidden=true;$('proposal').replaceChildren();}
async function projects(){
  const data=await api('/api/projects');csrf=data.csrf;
  $('projects').replaceChildren(...data.projects.map(p=>button(p.name+'  ↗',()=>open(p.name,1))));
  if(!data.projects.length){const p=document.createElement('p');p.className='empty';p.textContent='Your library is empty. Start blank or import your first presentation below.';$('projects').append(p);}
  const templates=await api('/api/templates');$('template').replaceChildren(new Option('Blank presentation',''),...templates.templates.map(t=>new Option(t.name,t.name)));
  $('templateState').textContent=templates.templates.length?`${templates.templates.length} reusable template(s), stored privately on this server.`:'No templates yet. Import a file and choose “Add to reusable templates”.';
}
function renderCanvas(view,target,editable=false){
  if(editable)view.fields.forEach(f=>{f.original=f.text;});
  target.replaceChildren();target.style.background=view.background;
  view.images.forEach(image=>{const el=document.createElement('img');el.src=image.src;el.alt='Imported slide image';Object.assign(el.style,image.style);target.append(el);});
  view.fields.forEach((f,i)=>{if(f.kind==='notes')return;const el=document.createElement(f.kind==='title'?'h1':'p');el.textContent=f.text;Object.assign(el.style,f.style);el.dataset.field=i;
    if(editable){el.tabIndex=0;el.contentEditable='plaintext-only';el.setAttribute('aria-label',`Edit ${f.kind} ${i+1}`);el.onfocus=()=>select(i);el.oninput=()=>{f.text=el.textContent.slice(0,4000);$('content').value=f.text;mark();};el.onpaste=e=>{e.preventDefault();document.execCommand('insertText',false,e.clipboardData.getData('text/plain'));};}
    target.append(el);
  });
}
function select(i){selected=i;const f=active.fields[i];$('elementTitle').textContent=`${f.kind} ${i+1}`;for(const id of ['content','fontSize','textColor','alignment'])$(id).disabled=false;
  $('content').value=f.text;$('fontSize').value=parseInt(f.style['font-size'])||(f.kind==='title'?52:28);$('textColor').value=f.style.color||'#172b4d';$('alignment').value=f.style['text-align']||'left';
  $('preview').querySelectorAll('[data-field]').forEach(el=>el.classList.toggle('selected',Number(el.dataset.field)===i));
}
function fit(){const width=$('viewport').clientWidth-64;$('preview').style.zoom=Math.max(.15,Math.min(1,width/1440));}
async function open(name,slide){
  if(dirty)await save();
  active=await api('/api/slide?'+new URLSearchParams({project:name,slide}));selected=null;dirty=false;clearProposal();
  $('library').hidden=true;$('studio').hidden=false;$('heading').textContent=name;$('slideLabel').textContent=`Slide ${slide} / ${active.slides.length}`;$('saveState').textContent=`Saved · ${active.base}`;
  $('slides').replaceChildren(...active.slides.map((t,i)=>{const b=button(`${String(i+1).padStart(2,'0')}   ${t||'Untitled slide'}`,()=>open(name,i+1));b.setAttribute('aria-current',String(i+1===slide));return b;}));
  for(const id of ['content','fontSize','textColor','alignment'])$(id).disabled=true;$('content').value='';$('elementTitle').textContent='Slide';$('background').value=active.background;
  renderCanvas(active,$('preview'),true);fit();$('build').disabled=active.unsupported;status(active.unsupported?'This project uses a custom brand adapter; generic build is unavailable.':'');downloads();
}
function downloads(){ $('downloads').replaceChildren();for(const [label,kind,file] of [['PowerPoint','deck','deck.pptx'],['PDF','render','deck.pdf']]){const a=document.createElement('a');a.textContent=label;a.href=`/download/${encodeURIComponent(active.project)}/${active.base}/${kind}/${file}`;$('downloads').append(a);} }
async function save(){
  if(!dirty||!active)return;
  $('saveState').textContent='Saving…';
  const edits=active.fields.flatMap((f,i)=>!f.changed&&f.text===f.original?[]:[{field:i,text:f.text,styles:f.styleEdit||{}}]);
  if(active.backgroundChanged)edits.push({styles:{background:active.background}});
  if(edits.length){const r=await api('/api/edit',{project:active.project,base:active.base,slide:active.slide,action:'format',edits});active.base=r.current;}
  active.fields.forEach(f=>{f.original=f.text;f.changed=false;});active.backgroundChanged=false;
  dirty=false;$('saveState').textContent=`Saved · ${active.base}`;clearProposal();downloads();
}
$('editor').onsubmit=e=>{e.preventDefault();run(save);};
for(const [id,key] of [['fontSize','font-size'],['textColor','color'],['alignment','text-align']])$(id).oninput=()=>{if(selected===null)return;const f=active.fields[selected];const value=$(id).value+(id==='fontSize'?'px':'');f.style[key]=value;f.styleEdit={...f.styleEdit,[key]:value};f.changed=true;Object.assign($('preview').querySelector(`[data-field="${selected}"]`).style,f.style);mark();};
$('content').oninput=()=>{if(selected===null)return;active.fields[selected].text=$('content').value;$('preview').querySelector(`[data-field="${selected}"]`).textContent=$('content').value;mark();};
$('background').oninput=()=>{active.background=$('background').value;active.backgroundChanged=true;$('preview').style.background=active.background;mark();};
for(const action of ['add','duplicate','delete','up','down'])$(action).onclick=()=>run(async()=>{await save();await api('/api/edit',{project:active.project,base:active.base,slide:active.slide,action});const n=action==='add'||action==='duplicate'?active.slide+1:action==='up'?active.slide-1:action==='down'?active.slide+1:Math.max(1,active.slide-1);await open(active.project,n);});
$('create').onsubmit=e=>{e.preventDefault();run(async()=>{const file=$('upload').files[0];const data={name:$('name').value,template:$('template').value,kind:$('asTemplate').checked?'template':'project'};if(file){if(file.size>8*1024*1024)throw Error('Upload limit is 8 MiB');data.filename=file.name;data.content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(Error('Could not read file'));reader.readAsDataURL(file);});data.template='';}status('Creating…');const r=await api('/api/create',data);await projects();if(r.project)await open(r.project,1);status(r.template?'Template added to your private library.':'Presentation ready.');});};
$('reload').onclick=()=>run(async()=>{if(!active)return;if(dirty&&!window.confirm('Discard unsaved edits and reload the saved revision?'))return;dirty=false;await open(active.project,active.slide);});
$('libraryToggle').onclick=()=>run(async()=>{await save();$('studio').hidden=true;$('library').hidden=false;await projects();});
function chatVisible(value){$('conversation').hidden=!value;$('chatToggle').setAttribute('aria-expanded',String(value));if(value)$('prompt').focus();else $('chatToggle').focus();}
$('chatToggle').onclick=()=>chatVisible($('conversation').hidden);$('chatClose').onclick=()=>chatVisible(false);
function message(text,who){const p=document.createElement('p');p.className=who;p.textContent=text;$('messages').append(p);p.scrollIntoView({block:'nearest'});}
async function chat(){if(!active)throw Error('Open a presentation first');await save();clearProposal();const captured={project:active.project,slide:active.slide,base:active.base};message($('prompt').value,'user');$('send').disabled=true;$('send').textContent='Thinking…';$('retry').hidden=true;try{const r=await api('/api/chat',{...captured,message:$('prompt').value});if(active.project!==captured.project||active.slide!==captured.slide||active.base!==captured.base)return;message(r.message,'response');pending=r.ops;if(pending){$('review').hidden=false;pending.forEach(op=>{const p=document.createElement('p');p.textContent=`${op.old} → ${op.new}`;$('proposal').append(p);});}}catch(e){$('retry').hidden=false;throw e;}finally{$('send').disabled=false;$('send').textContent='Send';}}
$('chat').onsubmit=e=>{e.preventDefault();run(chat);};$('retry').onclick=()=>run(chat);$('rejectProposal').onclick=()=>{clearProposal();message('Proposal rejected.','response');};
$('applyProposal').onclick=()=>run(async()=>{if(dirty)throw Error('Save your edits and request a fresh proposal.');await api('/api/apply',{project:active.project,slide:active.slide,base:active.base,ops:pending});await open(active.project,active.slide);status('Changes applied and saved as a new revision.');});
$('build').onclick=()=>run(async()=>{if(!active)throw Error('Open a presentation first');await save();status('Building presentation and rendering previews…');const r=await api('/api/build',{project:active.project,base:active.base});status(r.message);downloads();});
$('present').onclick=()=>run(async()=>{await save();$('deckSlides').replaceChildren();for(let i=1;i<=active.slides.length;i++){const view=await api('/api/slide?'+new URLSearchParams({project:active.project,slide:i}));const wrap=document.createElement('div');const art=document.createElement('article');art.className='deckSlide';renderCanvas(view,art);wrap.append(art);$('deckSlides').append(wrap);}$('deckPreview').showModal();});$('closePreview').onclick=()=>$('deckPreview').close();
window.addEventListener('resize',fit);window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='s'){e.preventDefault();run(save);}if(e.altKey&&active&&['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();const n=active.slide+(e.key==='ArrowLeft'?-1:1);if(n>=1&&n<=active.slides.length)run(()=>open(active.project,n));}if(e.key==='Escape')chatVisible(false);});
run(async()=>{await projects();status('Ready');});
