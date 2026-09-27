const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const code=fs.readFileSync('web/app.js','utf8');
const render=code.slice(code.indexOf('function renderStopPlan('),code.indexOf("$('spotter-stop-plan')?.addEventListener"));
const target={contains:()=>false,replaceChildren(...children){this.children=children;this.textContent='';}};
const doc={activeElement:null,createElement:()=>({dataset:{},append(){},add(){},setAttribute(){}})};
const context={document:doc,$:()=>target,renderCache:new Map(),strategyConfig:{driverNames:['Santiago','David','Herney']},Option:class{constructor(label,value){this.label=label;this.value=value;}}};
vm.createContext(context);vm.runInContext(render,context);
context.renderStopPlan({state:'SIN DATOS SUFICIENTES',missing:['FUEL'],available:false,stops:[]});
assert.match(target.textContent,/SIN DATOS SUFICIENTES.*FUEL/);
context.renderStopPlan({state:'ERROR DE CÁLCULO',missing:[],available:false,stops:[]});
assert.match(target.textContent,/ERROR DE CÁLCULO/);
context.renderStopPlan({state:'PLAN DISPONIBLE',available:true,stops:[{number:3,lap:100,suggestedLap:98,autoDriver:'David',autoFuel:'LLENAR',status:'pending',driver:'David',fuelAction:'auto',liters:55}]});
assert.equal(target.children.length,1);
assert.equal(target.children[0].dataset.stop,'3');
console.log('Race Plan frontend states: OK');
const html=fs.readFileSync('web/index.html','utf8');
['spotter-race-plan-card','spotter-race-plan-expand','spotter-plan-earliest','spotter-plan-target','spotter-plan-fuel-limit','spotter-vnext-stints','race-plan-dialog','race-plan-sim-lap','race-plan-sim-now','spotter-stop-plan'].forEach(id=>assert(html.includes('id="'+id+'"'),'missing Race Plan SPOTTER id '+id));
assert.match(code,/action:'race_plan_simulate'/);
assert.match(code,/data\.racePlanVNext/);
console.log('Race Plan vNext SPOTTER structure: OK');

const spotter=code.slice(code.indexOf('function racePlanLap('),code.indexOf('function drawTrackMap('));
const nodes=new Map();
const makeNode=()=>({hidden:false,value:'',textContent:'',dataset:{},style:{left:''},children:[],append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;this.textContent='';}});
const el=id=>{if(!nodes.has(id))nodes.set(id,makeNode());return nodes.get(id);};
const rendered={};
const ui={
  $:el,renderCache:new Map(),strategyConfig:{driverNames:['Santiago','David','Herney']},
  document:{activeElement:null,createElement:()=>makeNode()},
  localStorage:{getItem:()=>null},Option:context.Option,
  setText(id,value){el(id).textContent=String(value??'—');},
  timingRows(id,rows,full){rendered[id]={size:rows.length,full};},
  renderStopPlan(plan){rendered.plan=plan;},refreshSpotterRivalOptions(){},
};
vm.createContext(ui);vm.runInContext(spotter,ui);
ui.renderSpotter({teamContext:{carIdx:8,carNumber:'18',driver:'David',remainingTime:'1:00:00'},header:{position:'P4',lap:'V100'},self:{fuel:'33.4 L · SDK OBSERVADO'},relative:[{idx:8}],standing:[{idx:8}],standingAll:Array.from({length:40},(_,idx)=>({idx})),racePlan:{state:'PLAN DISPONIBLE',stopsRemaining:2,completed:[]},racePlanVNext:{stopsCompleted:1,transition:'STABLE',fuelModel:{observed_lpl:2.39,strategy_lpl:2.43,confidence:'HIGH',source:'CURRENT_SESSION',margin_laps:2,margin_source:'IRACING_APP_INI_DEFAULT'},fuelCalculator:{autoFuelEnabled:true,autoFuelActive:true,pitSvFuelLiters:76.4},raceState:{current_lap:100,completed_laps:99},initialPlan:{minimum_stops:3},currentPlan:{available:true,minimum_stops:2,stints_remaining:3,current_autonomy_laps:13,finish:{low:136,expected:137,high:138},window:{earliest_safe:105,target:108,fuel_limit:109,state:'WINDOW CLOSED'},stops:[{number:2,lap:108,earliest_safe:105,fuel_limit:109,fuel_to_add_liters:76.4,final_fill:false},{number:3,lap:121,earliest_safe:120,fuel_limit:122,fuel_to_add_liters:40,final_fill:true}],final_fuel_required_liters:40}}});
assert.equal(el('spotter-plan-state').textContent,'WINDOW CLOSED');
assert.equal(el('spotter-plan-box').textContent,'V108');
assert.equal(el('spotter-plan-earliest').textContent,'V105');
assert.equal(el('spotter-plan-target').textContent,'V108');
assert.equal(el('spotter-plan-fuel-limit').textContent,'V109');
assert.equal(el('spotter-plan-stops').textContent,'2 PARADAS');
assert.equal(el('spotter-plan-delta').textContent,'-1 STOP');
assert.equal(el('spotter-plan-finish').textContent,'V136–V138');
assert.equal(el('race-plan-popup-margin').textContent,'+2 vueltas');
assert.equal(rendered['spotter-standing-all'].size,40);
assert.equal(rendered['spotter-standing-all'].full,true);
assert.ok((el('spotter-vnext-stints').children||[]).length>=3);
console.log('Spotter Race Plan vNext rendering and full standings: OK');

