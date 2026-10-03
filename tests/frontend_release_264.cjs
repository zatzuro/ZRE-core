const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const code=fs.readFileSync('web/app.js','utf8');
const nodes=new Map(),classes=new Set();
function el(id){if(!nodes.has(id))nodes.set(id,{id,hidden:false,textContent:'',dataset:{},classList:{toggle(){}},querySelector(){return null;}});return nodes.get(id);}
const selectors=new Map(['.live-telemetry .pit','.loss-map-card'].map(x=>[x,el(x)]));
const context={$:el,setText(id,v){el(id).textContent=String(v??'—');},document:{body:{dataset:{},classList:{toggle(k,on){on?classes.add(k):classes.delete(k);}}},querySelector(s){return selectors.get(s)||null;},createElement(){return {hidden:false};}}};
vm.createContext(context);vm.runInContext(code.slice(code.indexOf('function sessionWorkspaceMode('),code.indexOf('function renderLive(')),context);
for(const [sessionType,mode] of [['Practice','practice'],['Lone Qualify','qualifying'],['Race','race']]){
 const data={sessionType,coach:{primary:{title:'Actual Quali',advice:'Current session'},optimalLap:'1:18.000'},self:{lastLap:'1:19.000',bestLap:'1:18.800'}};
 assert.equal(context.applySessionWorkspace(data),mode);
 assert.equal(el('race-tools-grid').hidden,mode!=='race');assert.equal(selectors.get('.live-telemetry .pit').hidden,mode!=='race');
 assert.equal(el('practice-curve-coach').hidden,mode!=='practice');assert.equal(el('qualifying-focus-card').hidden,mode!=='qualifying');
 context.renderQualifyingFocus(data,mode);context.renderSessionIntelligence(data,mode);context.renderRivalStrategy(data,mode);
 assert.equal(el('rival-strategy-card').hidden,mode!=='race');assert.equal(el('intel-air-temp').textContent,'—');assert.equal(el('intel-session').textContent,'—');
}
assert.equal(el('quali-title').textContent,'Actual Quali');
context.renderSessionIntelligence({sessionIntelligence:{environment:{observed:{TrackWetness:1,AirTemp:0},wetnessLabel:'DRY'}}},'race');
assert.equal(el('intel-air-temp').textContent,'0.0 °C');assert.equal(el('intel-wet').textContent,'DRY');assert.ok(!el('intel-context').textContent.includes('húmeda'));
context.renderRivalStrategy({rivalStrategy:{primary:{action:'NO RECOMMENDATION',number:'23',confidence:'LOW',reason:'Missing evidence'}}},'race');
assert.ok(el('rival-strategy-primary').textContent.startsWith('SIN RECOMENDACIÓN'));
context.renderSessionIntelligence({sessionIntelligence:{competitors:{observed:[{number:'23',presence:'STALE',lastPit:{lap:55,confidence:'CONFIRMED'}}]}}},'race');
assert.ok(el('intel-context').textContent.includes('STALE'));assert.ok(el('intel-source').textContent.includes('ZRE · INFERIDO'));
const css=fs.readFileSync('web/style.css','utf8');assert.ok(css.includes('.race-session .pit-view .coach-card'));assert.ok(css.includes('.qualifying-session .pit-view .director-card'));
console.log('2.6.4 Practice / Quali / Race, missing SDK, dry track, STALE and inference labels: OK');
