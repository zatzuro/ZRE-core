/* Regression: navigable single comparator, measured/estimated labels, editing. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
class Element {
  constructor(tag='div'){
    this.tagName=tag;this.dataset={};this.children=[];this.options=[];
    this.value='';this.textContent='';this.parentElement={scrollTop:0};this.events={};
  }
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;if(this.tagName==='select')this.options=items;}
  addEventListener(kind,callback){this.events[kind]=callback;}
  focus(){}
}
const map=new Map();
function get(id){
  if(!map.has(id))map.set(id,new Element(id==='lh-rival'||id==='lh-filter'?'select':'div'));
  return map.get(id);
}
get('lh-filter').value='all';
const document={getElementById:get,createElement:tag=>new Element(tag)};
const win={};
const Option=function(text,value){this.text=text;this.value=value;};
const src=fs.readFileSync(path.resolve(__dirname,'../web/lap_history.js'),'utf8');
vm.runInNewContext(src,{window:win,document,Option});
assert.equal(typeof win.ZRELapHistory?.render,'function');
win.ZRELapHistory.init();
const team=[
 {lap:40,car_number:'18',driver:'David',lap_time:92.4,remaining:30,kind:'Normal',state:'REAL',fuelSource:'MANUAL',avgConsumption:2.5},
 {lap:41,car_number:'18',driver:'David',lap_time:92.1,remaining:27.5,kind:'Normal',state:'REAL',fuelSource:'ESTIMADO',avgConsumption:2.5}
];
const rival=[
 {lap:40,car_number:'27',driver:'Rival',lap_time:92.7,kind:'Normal'},
 {lap:41,car_number:'27',driver:'Rival',lap_time:91.9,kind:'Normal'}
];
const data={race:'777',available:true,teamCarIdx:0,rivalCarIdx:1,team,rival,projected:[
 {lap:42,car_number:'18',driver:null,lap_time:92,remaining:25,kind:'Normal',state:'PROYECTADO',fuelSource:'ESTIMADO',avgConsumption:2.5}
]};
const commands=[];
win.ZRELapHistory.render({connected:true,lapDatabase:data,raceDirector:{candidates:[{idx:1,label:'#27'}]}},command=>commands.push(command));
assert.equal(get('lh-rows').children.length,3);
assert.equal(get('lh-rows').children[2].dataset.state,'PROYECTADO');
assert.equal(get('lh-kpi-five').textContent,'+0.050s');
const ownRow=get('lh-rows').children[1];
const edit=ownRow.children[4].children[1];
assert.equal(typeof edit.events.click,'function');
edit.events.click();
assert.equal(get('lh-manual-lap').value,'41');
get('lh-manual-fuel').value='27.9';
get('lh-manual-form').events.submit({preventDefault(){}});
assert.equal(commands.length,1);
assert.equal(commands[0].type,'lapFuelEdit');
assert.equal(commands[0].lap,41);
assert.equal(commands[0].remaining,27.9);
console.log('ZRE lap history single-table and manual fuel regression: PASS');
