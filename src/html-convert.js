#!/usr/bin/env node
// Local, network-denied extraction of slide DOM into editable PowerPoint geometry.
const fs=require('fs'),path=require('path');
const {chromium}=require('playwright');
const PptxGenJS=require('pptxgenjs');
async function convert(input,output,count=5){
 const raw=fs.readFileSync(input,'utf8');
 const html=raw.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(String.raw`\( S(A,B) = \tfrac{1}{2}\Big( \tfrac{1}{|A|}\sum_{a \in A} \max_{b \in B} \cos(a,b) \;+\; \tfrac{1}{|B|}\sum_{b \in B} \max_{a \in A} \cos(a,b) \Big) \)`, 'S(A,B) = ½ [ (1/|A|) Σₐ maxᵦ cos(a,b) + (1/|B|) Σᵦ maxₐ cos(a,b) ]');
 const browser=await chromium.launch({headless:true});
 try{
 const ctx=await browser.newContext({viewport:{width:1440,height:810},javaScriptEnabled:false});
 await ctx.route('**/*',r=>r.abort());
 const page=await ctx.newPage();page.setDefaultTimeout(20000);
 const overrides='<style>.stage{position:absolute!important;left:0!important;top:0!important;transform:none!important;box-shadow:none!important;border:0!important}.slide{animation:none!important}.deck-controls,.overview,.help,.notes-panel{display:none!important}</style>';
 await page.setContent(html.replace('</head>',overrides+'</head>'),{waitUntil:'domcontentloaded'});
 const available=await page.locator('section.slide').count();
 if(count>available||count<1)throw Error(`Requested ${count} slides, available ${available}`);
 const dir=path.join(path.dirname(path.resolve(output)),'html-source');fs.mkdirSync(dir,{recursive:true});
 const spec={source:path.basename(input),size:[1440,810],network:'denied',slides:[],limitations:['CSS gradients/shadows/filters omitted; solid geometry preserved','Curves approximated with editable line segments','No arbitrary CSS/JS presentation framework support']};
 for(let index=0;index<count;index++){
 await page.evaluate(i=>{document.querySelectorAll('section.slide').forEach((s,j)=>{s.style.display=j===i?'block':'none';s.classList.toggle('active',j===i);});},index);
 const data=await page.evaluate(i=>{
  const root=document.querySelectorAll('section.slide')[i],items=[],warnings=[];
  const box=el=>{const r=el.getBoundingClientRect();return{x:r.x,y:r.y,w:r.width,h:r.height}};
  const color=c=>{const m=c.match(/rgba?\((\d+)[, ]+(\d+)[, ]+(\d+)(?:[, /]+([\d.]+))?\)/);return m?{hex:[m[1],m[2],m[3]].map(n=>(+n).toString(16).padStart(2,'0')).join(''),alpha:m[4]===undefined?1:+m[4]}:null};
  const st=el=>{const c=getComputedStyle(el);return{color:color(c.color),fill:color(c.backgroundColor),stroke:color(c.borderTopColor),border:parseFloat(c.borderTopWidth)||0,radius:parseFloat(c.borderRadius)||0,size:parseFloat(c.fontSize),font:c.fontFamily.split(',')[0].replace(/["']/g,''),bold:parseInt(c.fontWeight)>=600,letterSpacing:parseFloat(c.letterSpacing)||0}};
  function visit(el){
   const css=getComputedStyle(el);if(css.display==='none'||css.visibility==='hidden')return;
   if(el.tagName.toLowerCase()==='svg'){
    for(const foreign of el.querySelectorAll('foreignObject'))for(const child of foreign.children)visit(child);
    for(const e of el.querySelectorAll('rect,circle,ellipse,line,path,text')){
     if(e.closest('defs'))continue;
     const cs=getComputedStyle(e),r=box(e),tag=e.tagName;
     const fill=cs.fill==='none'?null:color(cs.fill),stroke=cs.stroke==='none'?null:color(cs.stroke);
     if(tag==='text'){const rotation=e.getAttribute('transform')?.match(/rotate\((-?[\d.]+)/);items.push({type:'text',...r,text:e.textContent,style:{...st(e),color:fill||st(e).color},svg:true,rotation:rotation?Number(rotation[1]):0});continue;}
     if(tag==='path'||tag==='line'){
      const total=e.getTotalLength(),points=[],matrix=e.getScreenCTM();
      const steps=tag==='line'?1:Math.max(2,Math.min(48,Math.ceil(total/10)));
      for(let j=0;j<=steps;j++){const p=e.getPointAtLength(total*j/steps),q=new DOMPoint(p.x,p.y).matrixTransform(matrix);points.push([q.x,q.y]);}
      if(fill&& !stroke){warnings.push('Filled SVG path represented as line segments');}
      items.push({type:'polyline',points,stroke:stroke||fill,width:parseFloat(cs.strokeWidth)||1.5,dash:cs.strokeDasharray!=='none',arrow:cs.markerEnd!=='none'});
     }else items.push({type:tag==='rect'?'rect':'ellipse',...r,fill,stroke,width:parseFloat(cs.strokeWidth)||0,dash:cs.strokeDasharray!=='none',radius:+e.getAttribute('rx')||0});
    }return;
   }
   const r=box(el),s=st(el);
   if((!s.fill||s.fill.alpha===0)&&css.backgroundImage.includes('gradient')){const first=css.backgroundImage.match(/rgba?\([^)]*\)/);if(first)s.fill=color(first[0]);warnings.push('CSS gradient replaced by its first color');}
   if(el!==root&&r.w&&r.h&&s.fill&&s.fill.alpha>0)items.push({type:'rect',...r,fill:s.fill,stroke:null,width:0,radius:s.radius});
   if(el!==root&&r.w&&r.h){
    for(const side of ['Top','Right','Bottom','Left']){const w=parseFloat(css['border'+side+'Width'])||0;if(!w)continue;const x1=side==='Right'?r.x+r.w:r.x,y1=side==='Bottom'?r.y+r.h:r.y;const x2=side==='Left'||side==='Right'?x1:r.x+r.w,y2=side==='Top'||side==='Bottom'?y1:r.y+r.h;items.push({type:'polyline',points:[[x1,y1],[x2,y2]],stroke:color(css['border'+side+'Color']),width:w,arrow:false});}
   }
   for(const node of el.childNodes){
    if(node.nodeType===1)visit(node);
    else if(node.nodeType===3&&node.textContent.trim()){
     const text=node.textContent,lines=new Map();
     for(let k=0;k<text.length;k++){
      const range=document.createRange();range.setStart(node,k);range.setEnd(node,k+1);const r=range.getBoundingClientRect();if(!r.width||!r.height)continue;
      const key=Math.round(r.y*10)/10;
      if(!lines.has(key))lines.set(key,{x:r.x,y:r.y,w:0,h:r.height,text:''});
      const line=lines.get(key);line.text+=text[k];line.w=Math.max(line.w,r.right-line.x);line.h=Math.max(line.h,r.height);
     }
     for(const line of lines.values())if(line.text.trim())items.push({type:'text',...line,style:s});
    }
   }
  }
  visit(root);
  return{title:root.querySelector('h1')?.innerText||'',background:color(getComputedStyle(root).backgroundColor)?.hex||'FFFFFF',notes:root.querySelector('.speaker-notes')?.textContent||'',items,warnings};
 },index);
 spec.slides.push(data);await page.screenshot({path:path.join(dir,`slide-${index+1}.png`)});
 }
 fs.writeFileSync(path.join(dir,'source.html'),raw);
 fs.writeFileSync(path.join(dir,'spec.json'),JSON.stringify(spec,null,2));
 const pptx=new PptxGenJS();pptx.defineLayout({name:'HTML',width:16,height:9});pptx.layout='HTML';pptx.title=path.basename(input,'.html');
 const scale=1/90; // 1440 CSS px maps to 16 inches; CSS font px -> 0.8 points.
 function styleColor(c){return c?{color:c.hex,transparency:Math.round(100*(1-c.alpha))}:{color:'000000',transparency:100}}
 for(const s of spec.slides){const slide=pptx.addSlide();slide.background={color:s.background};
 for(const item of s.items){
  if(item.type==='text'){
   const t=item.style;let x=item.x,y=item.y,w=item.w,h=item.h;
   if(Math.abs(item.rotation)===90){x=item.x+(item.w-item.h)/2;y=item.y+(item.h-item.w)/2;w=item.h;h=item.w;}
   slide.addText(item.text,{x:x*scale,y:y*scale,w:Math.max(.03,(w+3)*scale),h:(h+3)*scale,rotate:item.rotation?((item.rotation+360)%360):0,fontFace:'Arial',fontSize:t.size*.8,bold:t.bold,color:t.color?.hex||'FFFFFF',charSpacing:t.letterSpacing*.8,wrap:false,margin:0,breakLine:false,valign:'mid',paraSpaceAfterPt:0});
  }else if(item.type==='polyline'){
   for(let j=1;j<item.points.length;j++){const [x1,y1]=item.points[j-1],[x2,y2]=item.points[j];slide.addShape(pptx.ShapeType.line,{x:Math.min(x1,x2)*scale,y:Math.min(y1,y2)*scale,w:Math.abs(x2-x1)*scale,h:Math.abs(y2-y1)*scale,flipH:x2<x1,flipV:y2<y1,line:{...styleColor(item.stroke),width:item.width*.8,dashType:item.dash?'dash':'solid', ...(j===item.points.length-1&&item.arrow?{endArrowType:'triangle'}:{})}});}
  }else slide.addShape(item.type==='ellipse'?pptx.ShapeType.ellipse:item.radius?pptx.ShapeType.roundRect:pptx.ShapeType.rect,{x:item.x*scale,y:item.y*scale,w:item.w*scale,h:item.h*scale,radius:item.radius*scale,rectRadius:item.radius*scale,fill:styleColor(item.fill),line:{...styleColor(item.stroke),width:item.stroke?item.width*.8:0,dashType:item.dash?'dash':'solid'}});
 }
 if(s.notes)slide.addNotes(s.notes);
 }
 await pptx.writeFile({fileName:output});
 console.log(JSON.stringify({pptx:output,slides:spec.slides.length,spec:path.join(dir,'spec.json'),source_previews:dir,warnings:spec.slides.map(s=>s.warnings)}));
 return spec;
 }finally{await browser.close();}
}
if(require.main===module){const [input,output,n]=process.argv.slice(2);convert(input,output,Number(n||5)).catch(e=>{console.error(e);process.exitCode=1});}
module.exports={convert};
