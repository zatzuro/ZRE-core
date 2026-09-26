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
const spotter=code.slice(code.indexOf('function renderSpotter('),code.indexOf('function drawTrackMap('));
const nodes=new Map();
const el=id=>{if(!nodes.has(id))nodes.set(id,{hidden:false,value:'auto',textContent:'',replaceChildren(...children){this.children=children;}});return nodes.get(id);};
const rendered={};
const ui={
  $:el,renderCache:new Map(),strategyConfig:{driverNames:['Santiago','David','Herney']},
  document:{activeElement:null,createElement:()=>({dataset:{}})},
  localStorage:{getItem:()=>null},Option:context.Option,
  setText(id,value){el(id).textContent=String(value??'—');},
  timingRows(id,rows,full){rendered[id]={size:rows.length,full};},
  renderStopPlan(plan){rendered.plan=plan;},refreshSpotterRivalOptions(){},
};
vm.createContext(ui);vm.runInContext(spotter,ui);
ui.renderSpotter({teamContext:{carIdx:8,carNumber:'18',driver:'AUTO · no confirmado',remainingTime:'1:00:00'},header:{position:'P4',lap:'V100'},self:{fuel:'—'},relative:[{idx:8}],standing:[{idx:8}],standingAll:Array.from({length:40},(_,idx)=>({idx})),racePlan:{state:'SIN DATOS SUFICIENTES',missing:['FUEL'],projectedLaps:40,currentStint:3,stopsRemaining:null,completed:[]}});
assert.equal(el('spotter-plan-state').textContent,'SIN DATOS SUFICIENTES');
assert.equal(el('spotter-plan-current-stint').textContent,'S3');
assert.equal(el('spotter-plan-stops').textContent,'—');
assert.equal(rendered['spotter-standing-all'].size,40);
assert.equal(rendered['spotter-standing-all'].full,true);
console.log('Spotter view partial data and full standings: OK');
