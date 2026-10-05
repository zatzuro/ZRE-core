(function(){
'use strict';

const STORAGE_KEY='zre-screen-layouts-v1';
const BUILT_INS={
  live:{name:'PISTA',items:['personal-reference','tyres','fuel','pit-info','strategic-rival','race-plan','track-map','curve-coach','timing','lap-history','qualifying-focus','session-intelligence','rival-strategy']},
  pit:{name:'PIT / GARAGE',items:['driver-coach','pit-assistant','race-director','pit-standings','pit-lap-history']},
  summary:{name:'RESUMEN',items:['summary-kpis','summary-opportunities','summary-lap-history']},
  spotter:{name:'SPOTTER',items:['spotter-kpis','spotter-identity','spotter-relative','spotter-standings','spotter-rival','spotter-race-plan','stop-history','spotter-controls']}
};
const COMPONENTS=[
 {id:'personal-reference',name:'Referencia personal',group:'PILOTO',view:'live',selector:'.live-telemetry .lap-card'},
 {id:'tyres',name:'Neumáticos',group:'PILOTO',view:'live',selector:'.live-telemetry .data-card:not(.lap-card):not(.fuel-card):not(.pit)'},
 {id:'fuel',name:'Combustible',group:'PILOTO',view:'live',selector:'.live-telemetry .fuel-card'},
 {id:'pit-info',name:'Información de parada',group:'ESTRATEGIA',view:'live',selector:'.live-telemetry .pit'},
 {id:'strategic-rival',name:'Rival estratégico',group:'ESTRATEGIA',view:'live',selector:'.live-rival-card'},
 {id:'race-plan',name:'Race Plan',group:'ESTRATEGIA',view:'live',selector:'#endurance-strategy-card'},
 {id:'track-map',name:'Mapa / recomendaciones',group:'COACH',view:'live',selector:'.loss-map-card'},
 {id:'curve-coach',name:'Coach · curva por curva',group:'COACH',view:'live',selector:'#practice-curve-coach'},
 {id:'timing',name:'Relative / clasificación',group:'TIMING',view:'live',selector:'.switchable-timing'},
 {id:'lap-history',name:'Historial de vueltas',group:'TIMING',view:'live',selector:'.practice-history'},
 {id:'qualifying-focus',name:'Quali · ataque de vuelta',group:'COACH',view:'live',selector:'#qualifying-focus-card',dynamic:true},
 {id:'session-intelligence',name:'Session Intelligence',group:'INTELIGENCIA',view:'live',selector:'#session-intelligence-card',dynamic:true},
 {id:'rival-strategy',name:'Rival Strategy',group:'ESTRATEGIA',view:'live',selector:'#rival-strategy-card',dynamic:true},
 {id:'driver-coach',name:'Driver Coach',group:'COACH',view:'pit',selector:'.pit-top-grid .coach-card'},
 {id:'pit-assistant',name:'Pit Assistant',group:'ESTRATEGIA',view:'pit',selector:'.pit-top-grid .strategy-card'},
 {id:'race-director',name:'Race Director',group:'ESTRATEGIA',view:'pit',selector:'.pit-top-grid .director-card'},
 {id:'pit-standings',name:'Clasificación · Garage',group:'TIMING',view:'pit',anchor:'pit-standing-rows'},
 {id:'pit-lap-history',name:'Historial de vueltas · Garage',group:'TIMING',view:'pit',anchor:'pit-pace-rows'},
 {id:'summary-kpis',name:'KPIs de sesión',group:'RESUMEN',view:'summary',selector:'.summary-kpis'},
 {id:'summary-opportunities',name:'Principales oportunidades',group:'COACH',view:'summary',selector:'.summary-focus'},
 {id:'summary-lap-history',name:'Historial de vueltas · Resumen',group:'TIMING',view:'summary',anchor:'summary-pace-rows'},
 {id:'spotter-kpis',name:'KPIs Spotter',group:'SPOTTER',view:'spotter',selector:'.spotter-kpis'},
 {id:'spotter-identity',name:'Identidad coche / piloto',group:'SPOTTER',view:'spotter',selector:'.spotter-choice'},
 {id:'spotter-relative',name:'Relative en pista',group:'TIMING',view:'spotter',anchor:'spotter-relative-rows'},
 {id:'spotter-standings',name:'Class Standings',group:'TIMING',view:'spotter',anchor:'spotter-standing-rows'},
 {id:'spotter-rival',name:'Rival estratégico · Spotter',group:'ESTRATEGIA',view:'spotter',anchor:'spotter-rival-name'},
 {id:'spotter-race-plan',name:'Race Plan · Spotter',group:'ESTRATEGIA',view:'spotter',selector:'#spotter-race-plan-card'},
 {id:'stop-history',name:'Historial de paradas',group:'ESTRATEGIA',view:'spotter',anchor:'spotter-stop-history'},
 {id:'spotter-controls',name:'Control de parada / stint',group:'SPOTTER',view:'spotter',selector:'.spotter-controls'}
];
const componentById=new Map(COMPONENTS.map(x=>[x.id,x]));
let state=null,selectedScreen='live',draft=null,navigate=null,activeCustom=null,dragId=null,observer=null,observerTimer=null;
const origins=new Map();

function $(id){return document.getElementById(id)}
function clone(value){return JSON.parse(JSON.stringify(value))}
function safeId(){return 'custom-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,7)}
function defaultItem(id){return {id,size:'normal'}}
function defaultScreen(key){
 const base=BUILT_INS[key];
 return {id:key,name:base.name,builtIn:true,items:base.items.map(defaultItem)};
}
function defaultState(){
 return {version:1,screens:Object.fromEntries(Object.keys(BUILT_INS).map(k=>[k,defaultScreen(k)]))};
}
function sanitizeItems(items){
 const seen=new Set(),out=[];
 for(const raw of Array.isArray(items)?items:[]){
  const id=typeof raw==='string'?raw:raw?.id;
  if((!componentById.has(id)&&!String(id).startsWith('kpi:'))||seen.has(id))continue;
  seen.add(id);
  out.push({id,size:['compact','normal','wide','full'].includes(raw?.size)?raw.size:'normal'});
 }
 return out;
}
function loadState(){
 let parsed=null;
 try{parsed=JSON.parse(localStorage.getItem(STORAGE_KEY)||'null')}catch(_){}
 const base=defaultState();
 if(parsed&&parsed.version===1&&parsed.screens&&typeof parsed.screens==='object'){
  for(const key of Object.keys(BUILT_INS)){
   const src=parsed.screens[key];
   if(src)base.screens[key]={...defaultScreen(key),items:sanitizeItems(src.items)};
  }
  for(const [key,screen] of Object.entries(parsed.screens)){
   if(key in BUILT_INS||!screen||screen.builtIn)continue;
   const name=String(screen.name||'Pantalla personalizada').trim().slice(0,40);
   base.screens[key]={id:key,name:name||'Pantalla personalizada',builtIn:false,items:sanitizeItems(screen.items)};
  }
 }
 return base;
}
function persist(){
 localStorage.setItem(STORAGE_KEY,JSON.stringify(state));
 refreshNavigation();
}
function resolveComponent(def){
 if(!def)return null;
 let node=def.selector?document.querySelector(def.selector):null;
 if(!node&&def.anchor){
  const anchor=$(def.anchor);
  node=anchor?.closest('article,section,.spotter-kpis,.spotter-choice')||null;
 }
 if(node){
  node.dataset.zreComponent=def.id;
  node.dataset.zreComponentName=def.name;
 }
 return node;
}
function screen(view){return state?.screens?.[view]||null}
function screenLabel(view){
 if(view==='admin')return 'ADMINISTRACIÓN';
 return screen(view)?.name||BUILT_INS[view]?.name||String(view||'').toUpperCase();
}
function itemSizeClass(node,size){
 node?.classList.remove('zre-size-compact','zre-size-normal','zre-size-wide','zre-size-full');
 if(node)node.classList.add('zre-size-'+(size||'normal'));
}
function clearBuiltInStyles(){
 for(const def of COMPONENTS){
  const node=resolveComponent(def);
  if(!node)continue;
  node.classList.remove('zre-layout-hidden');
  node.style.removeProperty('--zre-layout-order');
  node.classList.remove('zre-size-compact','zre-size-normal','zre-size-wide','zre-size-full');
 }
}
function applyBuiltIn(view){
 const cfg=screen(view);
 if(!cfg||!cfg.builtIn)return;
 placeBuiltInKpis(view,cfg);
 const positions=new Map(cfg.items.map((item,index)=>[item.id,{...item,index}]));
 for(const def of COMPONENTS.filter(x=>x.view===view)){
  const node=resolveComponent(def);
  if(!node)continue;
  const item=positions.get(def.id);
  node.classList.toggle('zre-layout-hidden',!item);
  if(item){
   node.style.setProperty('--zre-layout-order',String(item.index));
   itemSizeClass(node,item.size);
  }else{
   node.style.removeProperty('--zre-layout-order');
   itemSizeClass(node,'normal');
  }
 }
}
function placeBuiltInKpis(view,cfg){
 const roots={live:'live-view',pit:'pit-view',summary:'summary-view',spotter:'spotter-view'};
 const root=$(roots[view]);if(!root)return;
 let host=root.querySelector('.zre-built-in-kpis');
 if(!host){host=document.createElement('section');host.className='zre-built-in-kpis';root.append(host)}
 const selected=new Set(cfg.items.map(x=>x.id));
 for(const node of [...host.children]){
  if(!selected.has('kpi:'+node.dataset.zreKpiId))$('kpi-component-bank')?.append(node);
 }
 cfg.items.forEach((item,index)=>{
  if(!item.id.startsWith('kpi:'))return;
  const node=resolveComponent(componentById.get(item.id));if(!node)return;
  node.classList.remove('zre-layout-hidden');itemSizeClass(node,item.size);
  node.style.setProperty('--zre-layout-order',String(index));
  if(node.parentNode!==host)host.append(node);
 });
}
function rememberOrigin(node,id){
 if(origins.has(id))return;
 const marker=document.createComment('zre-origin:'+id);
 node.parentNode?.insertBefore(marker,node);
 origins.set(id,{node,marker});
}
function restoreMoved(){
 for(const [id,entry] of origins){
  const {node,marker}=entry;
  if(marker.parentNode)marker.parentNode.replaceChild(node,marker);
  node.classList.remove('zre-custom-component','zre-size-compact','zre-size-normal','zre-size-wide','zre-size-full');
  node.style.removeProperty('--zre-layout-order');
  origins.delete(id);
 }
 activeCustom=null;
}
function composeCustom(view){
 const cfg=screen(view),host=$('custom-screen-grid');
 if(!cfg||cfg.builtIn||!host)return;
 activeCustom=view;
 host.replaceChildren();
 $('custom-screen-title').textContent=cfg.name;
 const missing=[];
 cfg.items.forEach((item,index)=>{
  const def=componentById.get(item.id),node=resolveComponent(def);
  if(!node){missing.push(def?.name||item.id);return;}
  rememberOrigin(node,item.id);
  node.classList.remove('zre-layout-hidden');
  node.classList.add('zre-custom-component');
  node.style.setProperty('--zre-layout-order',String(index));
  itemSizeClass(node,item.size);
  host.append(node);
 });
 if(!cfg.items.length){
  const empty=document.createElement('div');
  empty.className='zre-custom-empty';
  empty.textContent='Esta pantalla todavía no tiene componentes. Agrégalos desde ADMINISTRACIÓN.';
  host.append(empty);
 }else if(missing.length){
  const info=document.createElement('div');
  info.className='zre-custom-missing';
  info.textContent='Esperando componentes dinámicos: '+missing.join(', ');
  host.append(info);
 }
}
function renderCustom(view){
 if(activeCustom!==view)composeCustom(view);
 else{
  const cfg=screen(view);
  if(!cfg)return;
  for(const item of cfg.items){
   const def=componentById.get(item.id),node=resolveComponent(def);
   if(node&&!origins.has(item.id)){
    rememberOrigin(node,item.id);
    node.classList.remove('zre-layout-hidden');
    node.classList.add('zre-custom-component');
    itemSizeClass(node,item.size);
    $('custom-screen-grid')?.append(node);
   }
  }
 }
}
function refreshNavigation(){
 const nav=$('screen-nav');
 if(!nav)return;
 const current=document.body.dataset.view||'';
 const adminButton=nav.querySelector('[data-zre-view="admin"]');
 nav.querySelectorAll('[data-zre-custom-nav]').forEach(x=>x.remove());
 for(const [id,cfg] of Object.entries(state.screens)){
  if(cfg.builtIn)continue;
  const button=document.createElement('button');
  button.type='button';button.dataset.zreCustomNav='1';button.dataset.zreView=id;
  button.textContent=cfg.name;
  button.classList.toggle('active',current===id);
  button.addEventListener('click',()=>navigate?.(id));
  nav.append(button);
 }
 if(adminButton)adminButton.classList.toggle('active',current==='admin');
}
function setAdminStatus(message,tone=''){
 const el=$('admin-status');if(!el)return;
 el.textContent=message;el.dataset.tone=tone;
}
function updateAdminSelect(){
 const select=$('admin-screen-select');if(!select)return;
 const previous=selectedScreen;
 select.replaceChildren(...Object.values(state.screens).map(cfg=>new Option((cfg.builtIn?'BASE · ':'PERSONAL · ')+cfg.name,cfg.id)));
 if(state.screens[previous])select.value=previous;
 else{selectedScreen='live';select.value='live'}
}
function renderComposition(){
 const cfg=screen(selectedScreen),list=$('admin-component-list');
 if(!cfg||!list)return;
 $('admin-screen-name').value=cfg.name;
 $('admin-screen-name').disabled=cfg.builtIn;
 $('admin-delete-screen').disabled=cfg.builtIn;
 $('admin-reset-screen').disabled=!cfg.builtIn;
 list.replaceChildren();
 draft=clone(cfg);
 if(!draft.items.length){
  const empty=document.createElement('p');empty.className='admin-empty';empty.textContent='Sin componentes. Agrega elementos desde el catálogo.';list.append(empty);
 }
 draft.items.forEach((item,index)=>list.append(makeCompositionRow(item,index)));
 renderCatalog();
 setAdminStatus('Cambios sin modificar.');
}
function makeCompositionRow(item,index){
 const def=componentById.get(item.id),row=document.createElement('div');
 row.className='admin-component-row';row.draggable=true;row.dataset.componentId=item.id;
 const grab=document.createElement('span');grab.className='admin-grab';grab.textContent='⋮⋮';grab.title='Arrastrar para reordenar';
 const meta=document.createElement('div');meta.className='admin-component-meta';
 const strong=document.createElement('strong');strong.textContent=def?.name||item.id;
 const small=document.createElement('small');small.textContent=(def?.group||'ZRE')+' · '+(def?.view?BUILT_INS[def.view]?.name||def.view:'');
 meta.append(strong,small);
 const size=document.createElement('select');size.className='admin-size';size.setAttribute('aria-label','Tamaño de '+strong.textContent);
 [['compact','COMPACTO'],['normal','NORMAL'],['wide','ANCHO'],['full','COMPLETO']].forEach(([v,t])=>size.add(new Option(t,v)));size.value=item.size||'normal';
 size.addEventListener('change',()=>{item.size=size.value;setAdminStatus('Hay cambios sin guardar.','dirty')});
 const up=document.createElement('button');up.type='button';up.textContent='↑';up.title='Subir';up.disabled=index===0;up.addEventListener('click',()=>moveDraft(item.id,-1));
 const down=document.createElement('button');down.type='button';down.textContent='↓';down.title='Bajar';down.disabled=index===draft.items.length-1;down.addEventListener('click',()=>moveDraft(item.id,1));
 const remove=document.createElement('button');remove.type='button';remove.className='danger';remove.textContent='QUITAR';remove.addEventListener('click',()=>removeDraft(item.id));
 row.append(grab,meta,size,up,down,remove);
 row.addEventListener('dragstart',()=>{dragId=item.id;row.classList.add('dragging')});
 row.addEventListener('dragend',()=>{dragId=null;row.classList.remove('dragging')});
 row.addEventListener('dragover',e=>e.preventDefault());
 row.addEventListener('drop',e=>{e.preventDefault();if(!dragId||dragId===item.id)return;const from=draft.items.findIndex(x=>x.id===dragId),to=draft.items.findIndex(x=>x.id===item.id);if(from<0||to<0)return;const [moved]=draft.items.splice(from,1);draft.items.splice(to,0,moved);redrawDraft('Hay cambios sin guardar.')});
 return row;
}
function redrawDraft(status){
 const list=$('admin-component-list');list.replaceChildren();
 if(!draft.items.length){const empty=document.createElement('p');empty.className='admin-empty';empty.textContent='Sin componentes. Agrega elementos desde el catálogo.';list.append(empty)}
 draft.items.forEach((item,index)=>list.append(makeCompositionRow(item,index)));
 renderCatalog();setAdminStatus(status,'dirty');
}
function moveDraft(id,delta){
 const index=draft.items.findIndex(x=>x.id===id),target=index+delta;
 if(index<0||target<0||target>=draft.items.length)return;
 [draft.items[index],draft.items[target]]=[draft.items[target],draft.items[index]];
 redrawDraft('Hay cambios sin guardar.');
}
function removeDraft(id){
 draft.items=draft.items.filter(x=>x.id!==id);redrawDraft('Componente retirado. Guarda para aplicar.');
}
function addDraft(id){
 if(draft.items.some(x=>x.id===id))return;
 draft.items.push(defaultItem(id));redrawDraft('Componente agregado. Guarda para aplicar.');
}
function renderCatalog(){
 const host=$('admin-component-catalog');if(!host||!draft)return;
 const selected=new Set(draft.items.map(x=>x.id));host.replaceChildren();
 const groups=new Map();
 for(const def of COMPONENTS){
  if(!groups.has(def.group))groups.set(def.group,[]);
  groups.get(def.group).push(def);
 }
 for(const [group,defs] of groups){
  const section=document.createElement('section'),title=document.createElement('h3');title.textContent=group;section.append(title);
  for(const def of defs){
   const row=document.createElement('div');row.className='admin-catalog-row';
   const text=document.createElement('span');text.textContent=def.name;
   const source=document.createElement('small');source.textContent=def.sourceLabel||BUILT_INS[def.view]?.name||def.view||'KPI';
   const button=document.createElement('button');button.type='button';button.textContent=selected.has(def.id)?'AGREGADO':'AGREGAR';button.disabled=selected.has(def.id);button.addEventListener('click',()=>addDraft(def.id));
   row.append(text,source,button);section.append(row);
  }
  host.append(section);
 }
}
function renderAdmin(){
 updateAdminSelect();renderComposition();refreshNavigation();
}
function saveDraft(){
 if(!draft||!state.screens[selectedScreen])return;
 const target=state.screens[selectedScreen];
 target.items=sanitizeItems(draft.items);
 if(!target.builtIn)target.name=String($('admin-screen-name')?.value||target.name).trim().slice(0,40)||target.name;
 persist();draft=clone(target);setAdminStatus('Configuración guardada.','saved');
 if(target.builtIn)applyBuiltIn(selectedScreen);
 updateAdminSelect();refreshNavigation();
}
function resetSelected(){
 const cfg=screen(selectedScreen);if(!cfg?.builtIn)return;
 state.screens[selectedScreen]=defaultScreen(selectedScreen);persist();renderComposition();applyBuiltIn(selectedScreen);setAdminStatus('Diseño predeterminado restaurado.','saved');
}
function createCustom(){
 const input=$('admin-new-screen-name'),name=String(input?.value||'').trim().slice(0,40);
 if(!name){setAdminStatus('Escribe un nombre para la nueva pantalla.','error');input?.focus();return}
 const id=safeId();state.screens[id]={id,name,builtIn:false,items:[]};persist();selectedScreen=id;if(input)input.value='';updateAdminSelect();renderComposition();setAdminStatus('Pantalla creada. Agrega componentes y guarda.','saved');
}
function deleteSelected(){
 const cfg=screen(selectedScreen);if(!cfg||cfg.builtIn)return;
 delete state.screens[selectedScreen];persist();selectedScreen='live';updateAdminSelect();renderComposition();setAdminStatus('Pantalla personalizada eliminada.','saved');
}
function bind(){
 $('admin-screen-select')?.addEventListener('change',e=>{selectedScreen=e.target.value;renderComposition()});
 $('admin-save-screen')?.addEventListener('click',saveDraft);
 $('admin-reset-screen')?.addEventListener('click',resetSelected);
 $('admin-create-screen')?.addEventListener('click',createCustom);
 $('admin-delete-screen')?.addEventListener('click',deleteSelected);
 $('admin-new-screen-name')?.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();createCustom()}});
 $('screen-nav')?.querySelector('[data-zre-view="admin"]')?.addEventListener('click',()=>navigate?.('admin'));
}
function leaveView(view){
 if(view&&screen(view)&&!screen(view).builtIn)restoreMoved();
}
function enterView(view){
 $('admin-view').hidden=view!=='admin';
 $('custom-view').hidden=!(screen(view)&&!screen(view).builtIn);
 if(view==='admin')renderAdmin();
 else if(screen(view)?.builtIn)applyBuiltIn(view);
 else if(screen(view))composeCustom(view);
 refreshNavigation();
}
function registerExternalComponents(defs){
 for(const def of defs||[]){
  if(!def?.id||!def?.selector||componentById.has(def.id))continue;
  const normalized={id:String(def.id),name:String(def.name||def.id),group:String(def.group||'KPI'),view:def.view||null,selector:String(def.selector),dynamic:true,sourceLabel:def.sourceLabel||'KPI'};
  COMPONENTS.push(normalized);componentById.set(normalized.id,normalized);
 }
 if(draft)renderCatalog();
}
function init(options={}){
 if(state)return;
 state=loadState();navigate=typeof options.onNavigate==='function'?options.onNavigate:null;
 bind();updateAdminSelect();refreshNavigation();
 for(const key of Object.keys(BUILT_INS))applyBuiltIn(key);
 observer=new MutationObserver(()=>{
  if(!activeCustom)return;
  clearTimeout(observerTimer);observerTimer=setTimeout(()=>renderCustom(activeCustom),30);
 });
 observer.observe(document.body,{childList:true,subtree:true});
}
window.ZREScreenAdmin={init,enterView,leaveView,renderAdmin,renderCustom,applyBuiltIn,registerExternalComponents,screenLabel,isManaged:view=>view==='admin'||Boolean(screen(view)),isCustom:view=>Boolean(screen(view)&&!screen(view).builtIn),getState:()=>clone(state||loadState())};
})();