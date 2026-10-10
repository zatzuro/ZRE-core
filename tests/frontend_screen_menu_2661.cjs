'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const html=fs.readFileSync('web/index.html','utf8');
const css=fs.readFileSync('web/practice.css','utf8');
new Function(app);
for(const s of ['id="screen-mode-control"','id="screen-mode-select"','id="screen-mode-context"','value="auto"','value="practice"','value="quali"','value="race"'])
  assert(html.includes(s),s);
for(const s of ['sessionScreenAvailability','reconcileScreenChoice','syncScreenMenu','screenChoice',"'quali_mode',value:'simulate'", "screenChoice==='practice'?'practice':null"])
  assert(app.includes(s),s);
assert(app.includes("if(screenChoice==='practice')return'live'"));
assert(app.includes("if(screenChoice==='quali')return data?.qualifying?.inGarage?'quali-garage':'quali'"));
assert(app.includes("if(screenChoice==='race')return'race-v2'"));
assert(app.includes("if(screenChoice!=='auto'&&!allowed[screenChoice])screenChoice='auto'"));
assert(!/screen-mode-select[\\s\\S]{0,1000}value:'training'/.test(app),'Changing visual screens must not close a Quali run');
assert(css.includes('#screen-mode-control[hidden]'),'spotter toolbar must honor hidden');
assert(css.includes('#quali-mode-control[hidden]'),'quali action must honor hidden in race');
console.log('ZRE 2.6.6.1 three-screen menu: frontend contracts OK');
