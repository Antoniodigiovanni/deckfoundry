#!/usr/bin/env node
// Native editable presentations from an independently authored JSON plan.
const fs = require('fs');
const path = require('path');
const PptxGenJS = require('pptxgenjs');
const [specFile, output] = process.argv.slice(2);
if (!specFile || !output) throw new Error('Usage: node generate.js SPEC.json OUT.pptx');
const spec = JSON.parse(fs.readFileSync(specFile, 'utf8'));
const pptx = new PptxGenJS();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'DeckFoundry';
pptx.subject = spec.objective || 'Presentation';
pptx.title = spec.title || 'Presentation';
pptx.lang = 'en-US';
const W = 13.333, H = 7.5;
const theme = Object.assign({primary:'172B4D', accent:'137C87', light:'EAF3F4', ink:'182538', muted:'53667C', font:'Aptos'}, spec.theme || {});
pptx.theme = {headFontFace:theme.font, bodyFontFace:theme.font, lang:'en-US'};
for (let i=0; i<spec.slides.length; i++) {
  const s = spec.slides[i], slide = pptx.addSlide();
  slide.background = {color:'FFFFFF'};
  slide.addShape(pptx.ShapeType.rect, {x:0,y:0,w:.16,h:H,line:{color:theme.accent},fill:{color:theme.accent}});
  slide.addText(s.title, {x:.72,y:.55,w:11.85,h:.85,fontFace:theme.font,fontSize:30,bold:true,color:theme.primary,breakLine:false,margin:0});
  slide.addShape(pptx.ShapeType.line, {x:.72,y:1.51,w:11.8,h:0,line:{color:theme.accent,width:1.4}});
  const bullets = s.bullets || [];
  if (bullets.length) {
    const runs = bullets.map((t,j) => ({text:t,options:{bullet:{indent:20},breakLine:j<bullets.length-1,paraSpaceAfterPt:14}}));
    slide.addText(runs, {x:.85,y:1.95,w:11.45,h:Math.min(4.6, .63*bullets.length+1),fontFace:theme.font,fontSize:21,color:theme.ink,margin:0,breakLine:false,valign:'top'});
  }
  if (s.takeaway) {
    slide.addShape(pptx.ShapeType.roundRect,{x:.72,y:6.4,w:11.85,h:.58,rectRadius:.07,line:{color:theme.light},fill:{color:theme.light}});
    slide.addText(s.takeaway,{x:.98,y:6.46,w:11.3,h:.45,fontFace:theme.font,fontSize:15,bold:true,color:theme.primary,margin:0});
  }
  slide.addText(`${String(i+1).padStart(2,'0')}  /  ${String(spec.slides.length).padStart(2,'0')}`,{x:11.56,y:7.12,w:1.01,h:.22,fontFace:theme.font,fontSize:9,color:theme.muted,align:'right',margin:0});
  if (s.notes) slide.addNotes(s.notes);
}
fs.mkdirSync(path.dirname(path.resolve(output)),{recursive:true});
pptx.writeFile({fileName:output}).catch(e=>{console.error(e);process.exitCode=1});
