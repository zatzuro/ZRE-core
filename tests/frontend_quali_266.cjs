const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('web/index.html','utf8');
const app=fs.readFileSync('web/app.js','utf8');
const q=fs.readFileSync('web/quali.js','utf8');
const css=fs.readFileSync('web/quali.css','utf8');
new vm.Script(app,{filename:'web/app.js'});new vm.Script(q,{filename:'web/quali.js'});
for(const id of ['quali-view','quali-mode-control','quali-mode-select','quali-new-run','q-kind',
'q-run-id','q-delta','q-best','q-last','q-optimal','q-potential','q-position','q-time-left',
'q-map-svg','q-map-line','q-priorities','q-sector-rows','q-ahead','q-behind','q-flag',
'q-track-temp','q-fuel','q-consumption','q-range','q-tyre-fl','q-tyre-fr',
'q-tyre-rl','q-tyre-rr','q-attempt-count','q-attempt-valid','q-attempt-pending',
'q-run-best','q-garage','q-compare-a','q-compare-b','q-garage-curves']){
 assert.ok(html.includes('id="'+id+'"'),'missing #'+id);
}
assert.ok(html.includes('<script src="/static/quali.js'),'Quali module not connected');
assert.ok(html.includes('<link rel="stylesheet" href="/static/quali.css'),'Quali styles missing');
assert.ok(app.includes('window.ZREQuali?.render'),'mode renderer not connected');
assert.ok(app.includes('window.ZREQuali?.sync'),'mode controls not synchronized');
assert.ok(app.includes("'quali-garage'"),'Garage route unavailable');
assert.ok(app.includes("action:'quali_mode',value:event.target.value"),'simulated mode has no backend action');
assert.ok(app.includes("action:'quali_mode',value:'new_run'"),'new run must be a backend command');
assert.ok(q.includes("delta?.valid===true"),'delta validity guard missing');
assert.ok(q.includes("q.qualifyingMode==='official'"),'official-only position must be guarded');
assert.ok(q.includes("const valid=(run.attempts||[]).filter"),'reference validity gating missing');
assert.ok(q.includes("const rows=data.coach?.allCorners||[]"),'full Garage coaching not connected');
assert.ok(css.includes('grid-template-columns:minmax(0,34fr) minmax(0,37fr) minmax(0,29fr)'),'horizontal layout proportions absent');
assert.ok(!html.includes('data-zre-view="admin"'),'archived editor should remain out of navigation');
console.log('Quali module routes, source labeling, safe selectors, responsive sections: OK');
