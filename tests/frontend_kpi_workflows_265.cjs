// Behavioral DOM fixture: actual registry, editor events, moves and persistence.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node{
 constructor(tag='div'){this.tagName=tag;this.children=[];this.parentNode=null;this.dataset={};this.listeners={};this.textContent='';this.value='';this.hidden=false;const classes=new Set();this.classList={add:(...xs)=>xs.forEach(x=>classes.add(x)),remove:(...xs)=>xs.forEach(x=>classes.delete(x)),toggle:(x,on)=>on?classes.add(x):classes.delete(x),contains:x=>classes.has(x)};this.style={setProperty(){},removeProperty(){}};}
 set className(v){this.classList.add(...v.split(' '))}
 append(...nodes){for(const n of nodes){n.parentNode?.removeChild(n);n.parentNode=this;this.children.push(n)}}
 insertBefore(n,b){n.parentNode?.removeChild(n);n.parentNode=this;this.children.splice(this.children.indexOf(b),0,n)}
 removeChild(n){this.children.splice(this.children.indexOf(n),1);n.parentNode=null}
 replaceChild(n,b){const i=this.children.indexOf(b);n.parentNode?.removeChild(n);this.children[i]=n;n.parentNode=this;b.parentNode=null}
 replaceChildren(...nodes){for(const n of [...this.children])this.removeChild(n);this.append(...nodes)}
 remove(){this.parentNode?.removeChild(this)}
 add(n){this.append(n)}
 addEventListener(k,f){this.listeners[k]=f}
 click(){this.listeners.click?.({target:this})}
 setAttribute(){}
 matches(s){if(s.startsWith('.'))return this.classList.contains(s.slice(1));if(s.startsWith('#'))return this.id===s.slice(1);const m=s.match(/^\[data-([\w-]+)(?:="([^"]*)")?\]$/);if(m){const key=m[1].replace(/-([a-z])/g,(_,x)=>x.toUpperCase());return m[2]===undefined?key in this.dataset:this.dataset[key]===m[2]}return this.tagName===s}
 querySelectorAll(s){const out=[];for(const n of this.children){if(n.matches(s))out.push(n);out.push(...n.querySelectorAll(s))}return out}
 querySelector(s){return this.querySelectorAll(s)[0]||null}
}
const body=new Node(),nodes=new Map();
for(const id of ['live-view','pit-view','summary-view','spotter-view','custom-view','custom-screen-grid','custom-screen-title','kpi-component-bank','admin-view','screen-nav','admin-screen-select','admin-screen-name','admin-delete-screen','admin-reset-screen','admin-status','admin-component-list','admin-component-catalog','admin-save-screen','admin-create-screen','admin-new-screen-name']){const n=new Node();n.id=id;nodes.set(id,n);body.append(n)}
const adminButton=new Node('button');adminButton.dataset.zreView='admin';nodes.get('screen-nav').append(adminButton);
const saved=new Map();const context={document:{body,getElementById:id=>nodes.get(id)||null,querySelector:s=>body.querySelector(s),createElement:tag=>new Node(tag),createComment:()=>new Node('comment')},localStorage:{getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v)},Option:function(t,v){const n=new Node('option');n.textContent=t;n.value=v;return n},CSS:{escape:x=>x},MutationObserver:class{observe(){}},setTimeout,clearTimeout};context.window=context;vm.createContext(context);
for(const f of ['screen_admin.js','kpi_library.js'])vm.runInContext(fs.readFileSync('web/'+f,'utf8'),context);
context.ZREScreenAdmin.init();
const lib={items:[{id:'fuel.current',label:'Fuel',group:'FUEL',value:0,display:'0.0 L',state:'AVAILABLE'}]};context.ZREKPI.render(lib);
context.ZREScreenAdmin.enterView('admin');nodes.get('admin-new-screen-name').value='Fuel QA';nodes.get('admin-create-screen').click();
const id=Object.keys(context.ZREScreenAdmin.getState().screens).find(x=>x.startsWith('custom-'));
function addFuel(){const row=nodes.get('admin-component-catalog').querySelectorAll('.admin-catalog-row').find(n=>n.children[0].textContent==='Fuel');row.children[2].click()}
addFuel();context.ZREKPI.render(lib);assert.equal(nodes.get('admin-component-list').querySelectorAll('.admin-component-row').length,1);
nodes.get('admin-save-screen').click();assert.equal(context.ZREScreenAdmin.getState().screens[id].items[0].id,'kpi:fuel.current');
context.ZREScreenAdmin.enterView(id);assert.equal(nodes.get('custom-screen-grid').querySelector('[data-zre-kpi-id="fuel.current"]').querySelector('.zre-kpi-value').textContent,'0.0 L');
context.ZREScreenAdmin.leaveView(id);assert.ok(nodes.get('kpi-component-bank').querySelector('[data-zre-kpi-id="fuel.current"]'));
context.ZREScreenAdmin.enterView('admin');nodes.get('admin-screen-select').value='live';nodes.get('admin-screen-select').listeners.change({target:nodes.get('admin-screen-select')});addFuel();nodes.get('admin-save-screen').click();context.ZREScreenAdmin.enterView('live');assert.ok(nodes.get('live-view').querySelector('[data-zre-kpi-id="fuel.current"]'));
context.ZREScreenAdmin.enterView(id);context.ZREScreenAdmin.leaveView(id);context.ZREScreenAdmin.enterView('live');assert.ok(nodes.get('live-view').querySelector('[data-zre-kpi-id="fuel.current"]'));
context.ZREScreenAdmin.enterView('admin');nodes.get('admin-reset-screen').click();assert.equal(nodes.get('live-view').querySelector('[data-zre-kpi-id="fuel.current"]'),null);
const config=JSON.parse(saved.get('zre-screen-layouts-v1'));assert.equal(config.screens[id].items[0].id,'kpi:fuel.current');
console.log('KPI behavioral editor, valid zero, custom/base placement, restoration, reset and persisted IDs: OK');
