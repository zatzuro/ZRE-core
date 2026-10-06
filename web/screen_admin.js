(function(){
'use strict';

const STORAGE_KEY='zre-screen-layouts-v1';
const HEADER_KEY='zre-header-collapsed-v1';
const COLS=12,MAX_ROWS=100;
const SIZE_TO_W={compact:3,normal:6,wide:9,full:12};
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
let state=null,selectedScreen='live',draft=null,navigate=null,activeCustom=null,dragId=null,selectedItemId=null,observer=null,observerTimer=null;
const origins=new Map();

function $(id){return document.getElementById(id)}
function clone(value){return JSON.parse(JSON.stringify(value))}
function clamp(n,min,max){return Math.min(max,Math.max(min,Number.isFinite(+n)?+n:min))}
function safeId(){return 'custom-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,7)}
function legacySize(w){if(w<=3)return 'compact';if(w<=6)return 'normal';if(w<=9)return 'wide';return 'full'}
function normalizeItem(raw,index=0){
 const id=typeof raw==='string'?raw:raw&&raw.id;
 if(!id)return null;
 const legacy=SIZE_TO_W[raw&&raw.size]||6;
 const w=clamp(raw&&raw.w||legacy,1,COLS);
 const h=clamp(raw&&raw.h||2,1,8);
 const fallbackX=1+((index*6)%COLS);
 const fallbackY=1+Math.floor((index*6)/COLS)*2;
 const x=clamp(raw&&raw.x||fallbackX,1,COLS-w+1);
 const y=clamp(raw&&raw.y||fallbackY,1,MAX_ROWS);
 return {id:String(id),size:legacySize(w),x,y,w,h,settings:(raw&&raw.settings&&typeof raw.settings==='object'&&!Array.isArray(raw.settings))?clone(raw.settings):{}};
}
function defaultItem(id,index=0){return normalizeItem({id,size:'normal'},index)}
function defaultScreen(key){
 const base=BUILT_INS[key];
 return {id:key,name:base.name,builtIn:true,items:base.items.map((id,i)=>defaultItem(id,i)),layout:{columns:COLS}};
}
function defaultState(){return {version:2,screens:Object.fromEntries(Object.keys(BUILT_INS).map(k=>[k,defaultScreen(k)]))}}
function sanitizeItems(items){
 const seen=new Set(),out=[];
 for(const raw of Array.isArray(items)?items:[]){
  const id=typeof raw==='string'?raw:raw&&raw.id;
  if(!id||seen.has(id))continue;
  if(!componentById.has(id)&&!String(id).startsWith('kpi:'))continue;
  const item=normalizeItem(raw,out.length);if(!item)continue;
  seen.add(id);out.push(item);
 }
 return out;
}
function loadState(){
 let parsed=null;
 try{parsed=JSON.parse(localStorage.getItem(STORAGE_KEY)||'null')}catch(_){parsed=null}
 const base=defaultState();
 if(!parsed||!parsed.screens||typeof parsed.screens!=='object')return base;
 for(const key of Object.keys(BUILT_INS)){
  const src=parsed.screens[key];
  if(src)base.screens[key]={...defaultScreen(key),items:sanitizeItems(src.items),layout:{columns:COLS}};
 }
 for(const [key,cfg] of Object.entries(parsed.screens)){
  if(key in BUILT_INS||!cfg||cfg.builtIn)continue;
  const name=String(cfg.name||'Pantalla personalizada').trim().slice(0,40)||'Pantalla personalizada';
  base.screens[key]={id:key,name,builtIn:false,items:sanitizeItems(cfg.items),layout:{columns:COLS}};
 }
 return base;
}
function persist(){
 try{localStorage.setItem(STORAGE_KEY,JSON.stringify(state))}catch(_){setAdminStatus('No fue posible guardar localmente la configuración.','error')}
 refreshNavigation();
}
function screen(view){return state&&state.screens&&state.screens[view]||null}
function screenLabel(view){if(view==='admin')return 'ADMINISTRACIÓN';return screen(view)?.name||BUILT_INS[view]?.name||String(view||'').toUpperCase()}
function resolveComponent(def){
 if(!def)return null;
 let node=def.selector?document.querySelector(def.selector):null;
 if(!node&&def.anchor){const anchor=$(def.anchor);node=anchor?.closest('article,section,.spotter-kpis,.spotter-choice')||null}
 if(node){node.dataset.zreComponent=def.id;node.dataset.zreComponentName=def.name}
 return node;
}
function itemSizeClass(node,size){
 node?.classList.remove('zre-size-compact','zre-size-normal','zre-size-wide','zre-size-full');
 if(node)node.classList.add('zre-size-'+(size||'normal'));
}
function applyGridStyle(node,item,index=0){
 if(!node||!item)return;
 node.style.setProperty('--zre-layout-order',String(index));
 node.style.setProperty('--zre-grid-x',String(item.x||1));
 node.style.setProperty('--zre-grid-y',String(item.y||1));
 node.style.setProperty('--zre-grid-w',String(item.w||6));
 node.style.setProperty('--zre-grid-h',String(item.h||2));
 itemSizeClass(node,legacySize(item.w||6));
}
function clearGridStyle(node){
 if(!node)return;
 for(const name of ['--zre-layout-order','--zre-grid-x','--zre-grid-y','--zre-grid-w','--zre-grid-h'])node.style.removeProperty(name);
 node.classList.remove('zre-size-compact','zre-size-normal','zre-size-wide','zre-size-full');
}
function clearBuiltInStyles(){
 for(const def of COMPONENTS){const node=resolveComponent(def);if(!node)continue;node.classList.remove('zre-layout-hidden');clearGridStyle(node)}
}
function applyBuiltIn(view){
 const cfg=screen(view);if(!cfg||!cfg.builtIn)return;
 placeBuiltInKpis(view,cfg);
 const positions=new Map(cfg.items.map((item,index)=>[item.id,{...item,index}]));
 for(const def of COMPONENTS.filter(x=>x.view===view)){
  const node=resolveComponent(def);if(!node)continue;
  const item=positions.get(def.id);node.classList.toggle('zre-layout-hidden',!item);
  if(item)applyGridStyle(node,item,item.index);else clearGridStyle(node);
 }
}
function placeBuiltInKpis(view,cfg){
 const roots={live:'live-view',pit:'pit-view',summary:'summary-view',spotter:'spotter-view'};
 const root=$(roots[view]);if(!root)return;
 let host=root.querySelector('.zre-built-in-kpis');
 if(!host){host=document.createElement('section');host.className='zre-built-in-kpis';root.append(host)}
 const selected=new Set(cfg.items.map(x=>x.id));
 for(const node of [...host.children])if(!selected.has('kpi:'+node.dataset.zreKpiId))$('kpi-component-bank')?.append(node);
 cfg.items.forEach((item,index)=>{
  if(!item.id.startsWith('kpi:'))return;
  const node=resolveComponent(componentById.get(item.id));if(!node)return;
  node.classList.remove('zre-layout-hidden');applyGridStyle(node,item,index);
  if(node.parentNode!==host)host.append(node);
 });
}
function rememberOrigin(node,id){
 if(origins.has(id))return;
 const marker=document.createComment('zre-origin:'+id);node.parentNode?.insertBefore(marker,node);origins.set(id,{node,marker});
}
function restoreMoved(){
 for(const [id,entry] of [...origins]){
  const {node,marker}=entry;if(marker.parentNode)marker.parentNode.replaceChild(node,marker);
  node.classList.remove('zre-custom-component','zre-layout-hidden');clearGridStyle(node);origins.delete(id);
 }
 activeCustom=null;
}
function composeCustom(view){
 const cfg=screen(view),host=$('custom-screen-grid');if(!cfg||cfg.builtIn||!host)return;
 activeCustom=view;host.replaceChildren();$('custom-screen-title').textContent=cfg.name;const missing=[];
 cfg.items.forEach((item,index)=>{
  const def=componentById.get(item.id),node=resolveComponent(def);
  if(!node){missing.push(def?.name||item.id);return}
  rememberOrigin(node,item.id);node.classList.remove('zre-layout-hidden');node.classList.add('zre-custom-component');applyGridStyle(node,item,index);host.append(node);
 });
 if(!cfg.items.length){const empty=document.createElement('div');empty.className='zre-custom-empty';empty.textContent='Esta pantalla todavía no tiene componentes. Agrégalos desde ADMINISTRACIÓN.';host.append(empty)}
 else if(missing.length){const info=document.createElement('div');info.className='zre-custom-missing';info.textContent='Componentes no disponibles en este contexto: '+missing.join(', ');host.append(info)}
}
function renderCustom(view){
 if(activeCustom!==view){composeCustom(view);return}
 const cfg=screen(view);if(!cfg)return;
 for(const [index,item] of cfg.items.entries()){
  const def=componentById.get(item.id),node=resolveComponent(def);
  if(node&&!origins.has(item.id)){rememberOrigin(node,item.id);node.classList.remove('zre-layout-hidden');node.classList.add('zre-custom-component');applyGridStyle(node,item,index);$('custom-screen-grid')?.append(node)}
 }
}
function refreshNavigation(){
 const nav=$('screen-nav');if(!nav||!state)return;
 const current=document.body.dataset.view||'';
 const adminButton=nav.querySelector('[data-zre-view="admin"]');
 nav.querySelectorAll('[data-zre-custom-nav]').forEach(x=>x.remove());
 for(const [id,cfg] of Object.entries(state.screens)){
  if(cfg.builtIn)continue;
  const button=document.createElement('button');button.type='button';button.dataset.zreCustomNav='1';button.dataset.zreView=id;button.textContent=cfg.name;
  button.classList.toggle('active',current===id);button.addEventListener('click',()=>navigate?.(id));nav.append(button);
 }
 if(adminButton)adminButton.classList.toggle('active',current==='admin');
}
function setAdminStatus(message,tone=''){const el=$('admin-status');if(!el)return;el.textContent=message;el.dataset.tone=tone}
function updateAdminSelect(){
 const select=$('admin-screen-select');if(!select||!state)return;
 const previous=selectedScreen;select.replaceChildren(...Object.values(state.screens).map(cfg=>new Option((cfg.builtIn?'BASE · ':'PERSONAL · ')+cfg.name,cfg.id)));
 if(state.screens[previous])select.value=previous;else{selectedScreen='live';select.value='live'}
}
function nextPlacement(){
 const items=draft?.items||[];
 for(let y=1;y<MAX_ROWS;y+=2)for(let x=1;x<=COLS;x+=3){
  const w=6,h=2;
  if(x+w-1>COLS)continue;
  const clash=items.some(i=>!(x+w-1<i.x||x>i.x+i.w-1||y+h-1<i.y||y>i.y+i.h-1));
  if(!clash)return {x,y,w,h};
 }
 return {x:1,y:MAX_ROWS-1,w:6,h:2};
}
function selectedItem(){return draft?.items?.find(x=>x.id===selectedItemId)||null}
function renderLayoutGrid(){
 const host=$('admin-layout-grid');if(!host||!draft)return;
 host.replaceChildren();
 if(!draft.items.length){const empty=document.createElement('div');empty.className='admin-layout-empty';empty.textContent='Pantalla vacía · agrega un componente desde el catálogo.';host.append(empty);return}
 for(const item of draft.items){
  const def=componentById.get(item.id),tile=document.createElement('div');tile.className='admin-layout-item';tile.dataset.componentId=item.id;
  tile.classList.toggle('selected',selectedItemId===item.id);tile.style.gridColumn=item.x+'/span '+item.w;tile.style.gridRow=item.y+'/span '+item.h;
  const title=document.createElement('strong');title.textContent=def?.name||item.id;
  const meta=document.createElement('small');meta.textContent=(def?.group||'ZRE')+' · '+item.w+'×'+item.h;
  const size=document.createElement('span');size.className='admin-widget-size';size.textContent='C'+item.x+' · F'+item.y;
  const resize=document.createElement('button');resize.type='button';resize.className='admin-resize-handle';resize.textContent='◢';resize.title='Redimensionar';
  tile.append(title,meta,size,resize);
  tile.addEventListener('click',e=>{if(e.target===resize)return;selectedItemId=item.id;renderLayoutGrid();renderComponentSettings()});
  tile.addEventListener('pointerdown',e=>{if(e.target===resize)return;startPointerEdit(e,item,'move',tile)});
  resize.addEventListener('pointerdown',e=>{e.stopPropagation();startPointerEdit(e,item,'resize',tile)});
  host.append(tile);
 }
}
function startPointerEdit(event,item,mode,tile){
 if(event.button!==undefined&&event.button!==0)return;
 const grid=$('admin-layout-grid');if(!grid)return;
 event.preventDefault();selectedItemId=item.id;renderComponentSettings();tile.classList.add('dragging');
 const startX=event.clientX,startY=event.clientY,orig={x:item.x,y:item.y,w:item.w,h:item.h};
 const rect=grid.getBoundingClientRect(),cellW=Math.max(1,(rect.width-16)/COLS),cellH=72;
 const move=e=>{
  const dx=Math.round((e.clientX-startX)/cellW),dy=Math.round((e.clientY-startY)/cellH);
  if(mode==='move'){item.x=clamp(orig.x+dx,1,COLS-item.w+1);item.y=clamp(orig.y+dy,1,MAX_ROWS)}
  else{item.w=clamp(orig.w+dx,1,COLS-item.x+1);item.h=clamp(orig.h+dy,1,8);item.size=legacySize(item.w)}
  tile.style.gridColumn=item.x+'/span '+item.w;tile.style.gridRow=item.y+'/span '+item.h;
  tile.querySelector('.admin-widget-size').textContent='C'+item.x+' · F'+item.y;
  tile.querySelector('small').textContent=(componentById.get(item.id)?.group||'ZRE')+' · '+item.w+'×'+item.h;
 };
 const up=()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',up);tile.classList.remove('dragging');redrawDraft('Hay cambios sin guardar.',false)};
 window.addEventListener('pointermove',move);window.addEventListener('pointerup',up,{once:true});
}
function renderComponentSettings(){
 const host=$('admin-component-settings');if(!host)return;host.replaceChildren();
 const item=selectedItem();
 if(!item){const p=document.createElement('p');p.className='admin-empty';p.textContent='Selecciona un componente de la parrilla.';host.append(p);return}
 const def=componentById.get(item.id);
 const title=document.createElement('strong');title.textContent=def?.name||item.id;
 const source=document.createElement('small');source.textContent=(def?.group||'ZRE')+' · '+(def?.sourceLabel||def?.view||'COMPONENTE');host.append(title,source);
 const grid=document.createElement('div');grid.className='admin-settings-grid';
 const fields=[['X','x',1,COLS],['Y','y',1,MAX_ROWS],['ANCHO','w',1,COLS],['ALTO','h',1,8]];
 for(const [label,key,min,max] of fields){
  const wrap=document.createElement('label');wrap.textContent=label;const input=document.createElement('input');input.type='number';input.min=String(min);input.max=String(max);input.value=String(item[key]);
  input.addEventListener('change',()=>{item[key]=clamp(+input.value,min,key==='x'?COLS-item.w+1:key==='w'?COLS-item.x+1:max);if(key==='w')item.size=legacySize(item.w);redrawDraft('Hay cambios sin guardar.',false)});
  wrap.append(input);grid.append(wrap);
 }
 host.append(grid);
 if(Array.isArray(def?.editorOptions)&&def.editorOptions.length){
  for(const option of def.editorOptions){const label=document.createElement('label');label.textContent=option.label||option.key;const input=document.createElement('input');input.value=item.settings[option.key]??option.default??'';input.addEventListener('change',()=>{item.settings[option.key]=input.value;setAdminStatus('Hay cambios sin guardar.','dirty')});label.append(input);host.append(label)}
 }else{const note=document.createElement('p');note.textContent='Este componente no expone opciones adicionales. La arquitectura admite opciones específicas por tipo cuando existan.';host.append(note)}
 const remove=document.createElement('button');remove.type='button';remove.className='danger';remove.textContent='ELIMINAR COMPONENTE';remove.addEventListener('click',()=>removeDraft(item.id));host.append(remove);
}
function renderComposition(){
 const cfg=screen(selectedScreen),list=$('admin-component-list');if(!cfg||!list)return;
 const topName=$('admin-screen-name'),panelName=$('admin-screen-name-panel');
 if(topName){topName.value=cfg.name;topName.disabled=cfg.builtIn}
 if(panelName){panelName.value=cfg.name;panelName.disabled=cfg.builtIn}
 $('admin-delete-screen').disabled=cfg.builtIn;$('admin-reset-screen').disabled=!cfg.builtIn;
 draft=clone(cfg);selectedItemId=draft.items[0]?.id||null;
 redrawDraft('Cambios sin modificar.',true);
}
function makeCompositionRow(item,index){
 const def=componentById.get(item.id),row=document.createElement('div');row.className='admin-component-row';row.draggable=true;row.dataset.componentId=item.id;
 const grab=document.createElement('span');grab.className='admin-grab';grab.textContent='⋮⋮';grab.title='Arrastrar para reordenar';
 const meta=document.createElement('div');meta.className='admin-component-meta';const strong=document.createElement('strong');strong.textContent=def?.name||item.id;const small=document.createElement('small');small.textContent=(def?.group||'ZRE')+' · '+item.w+'×'+item.h;meta.append(strong,small);
 const size=document.createElement('select');size.className='admin-size';[['compact','COMPACTO'],['normal','NORMAL'],['wide','ANCHO'],['full','COMPLETO']].forEach(([v,t])=>size.add(new Option(t,v)));size.value=legacySize(item.w);
 size.addEventListener('change',()=>{item.w=SIZE_TO_W[size.value];item.x=clamp(item.x,1,COLS-item.w+1);item.size=size.value;redrawDraft('Hay cambios sin guardar.',false)});
 const up=document.createElement('button');up.type='button';up.textContent='↑';up.disabled=index===0;up.addEventListener('click',()=>moveDraft(item.id,-1));
 const down=document.createElement('button');down.type='button';down.textContent='↓';down.disabled=index===draft.items.length-1;down.addEventListener('click',()=>moveDraft(item.id,1));
 const remove=document.createElement('button');remove.type='button';remove.className='danger';remove.textContent='QUITAR';remove.addEventListener('click',()=>removeDraft(item.id));
 row.append(grab,meta,size,up,down,remove);
 row.addEventListener('click',()=>{selectedItemId=item.id;renderLayoutGrid();renderComponentSettings()});
 row.addEventListener('dragstart',()=>{dragId=item.id;row.classList.add('dragging')});
 row.addEventListener('dragend',()=>{dragId=null;row.classList.remove('dragging')});
 row.addEventListener('dragover',e=>e.preventDefault());
 row.addEventListener('drop',e=>{e.preventDefault();if(!dragId||dragId===item.id)return;const from=draft.items.findIndex(x=>x.id===dragId),to=draft.items.findIndex(x=>x.id===item.id);if(from<0||to<0)return;const [moved]=draft.items.splice(from,1);draft.items.splice(to,0,moved);redrawDraft('Hay cambios sin guardar.',false)});
 return row;
}
function redrawDraft(status,clean=false){
 const list=$('admin-component-list');if(!list||!draft)return;list.replaceChildren();
 if(!draft.items.length){const empty=document.createElement('p');empty.className='admin-empty';empty.textContent='Sin componentes. Agrega elementos desde el catálogo.';list.append(empty)}
 draft.items.forEach((item,index)=>list.append(makeCompositionRow(item,index)));
 renderLayoutGrid();renderComponentSettings();renderCatalog();setAdminStatus(status,clean?'':'dirty');
}
function moveDraft(id,delta){const index=draft.items.findIndex(x=>x.id===id),target=index+delta;if(index<0||target<0||target>=draft.items.length)return;[draft.items[index],draft.items[target]]=[draft.items[target],draft.items[index]];redrawDraft('Hay cambios sin guardar.',false)}
function removeDraft(id){draft.items=draft.items.filter(x=>x.id!==id);if(selectedItemId===id)selectedItemId=draft.items[0]?.id||null;redrawDraft('Componente retirado. Guarda para aplicar.',false)}
function addDraft(id){
 if(!draft||draft.items.some(x=>x.id===id))return;
 const pos=nextPlacement(),item=normalizeItem({id,...pos,size:legacySize(pos.w)},draft.items.length);draft.items.push(item);selectedItemId=id;redrawDraft('Componente agregado. Ubícalo y guarda.',false);
}
function renderCatalog(){
 const host=$('admin-component-catalog');if(!host||!draft)return;const selected=new Set(draft.items.map(x=>x.id));host.replaceChildren();const groups=new Map();
 for(const def of COMPONENTS){if(!groups.has(def.group))groups.set(def.group,[]);groups.get(def.group).push(def)}
 for(const [group,defs] of groups){
  const section=document.createElement('section'),title=document.createElement('h3');title.textContent=group;section.append(title);
  for(const def of defs){const row=document.createElement('div');row.className='admin-catalog-row';const label=document.createElement('span');label.textContent=def.name;const source=document.createElement('small');source.textContent=def.sourceLabel||BUILT_INS[def.view]?.name||def.view||'KPI';const button=document.createElement('button');button.type='button';button.textContent=selected.has(def.id)?'AGREGADO':'AGREGAR';button.disabled=selected.has(def.id);button.addEventListener('click',()=>addDraft(def.id));row.append(label,source,button);section.append(row)}
  host.append(section);
 }
}
function renderAdmin(){updateAdminSelect();renderComposition();refreshNavigation()}
function syncScreenName(){
 const a=$('admin-screen-name'),b=$('admin-screen-name-panel');const value=(a?.value||b?.value||'').slice(0,40);if(a&&a.value!==value)a.value=value;if(b&&b.value!==value)b.value=value;
}
function saveDraft(){
 if(!draft||!state.screens[selectedScreen])return;
 const target=state.screens[selectedScreen];target.items=sanitizeItems(draft.items);
 if(!target.builtIn){syncScreenName();target.name=String($('admin-screen-name')?.value||target.name).trim().slice(0,40)||target.name}
 target.layout={columns:COLS};persist();draft=clone(target);setAdminStatus('Configuración guardada.','saved');
 if(target.builtIn)applyBuiltIn(selectedScreen);updateAdminSelect();refreshNavigation();renderComposition();
}
function resetSelected(){
 const cfg=screen(selectedScreen);if(!cfg?.builtIn)return;
 state.screens[selectedScreen]=defaultScreen(selectedScreen);persist();renderComposition();applyBuiltIn(selectedScreen);setAdminStatus('Diseño predeterminado restaurado.','saved');
}
function createCustom(){
 const input=$('admin-new-screen-name'),name=String(input?.value||'').trim().slice(0,40);if(!name){setAdminStatus('Escribe un nombre para la nueva pantalla.','error');input?.focus();return}
 const id=safeId();state.screens[id]={id,name,builtIn:false,items:[],layout:{columns:COLS}};persist();selectedScreen=id;if(input)input.value='';updateAdminSelect();renderComposition();setAdminStatus('Pantalla creada. Agrega componentes desde el catálogo.','saved');
}
function deleteSelected(){const cfg=screen(selectedScreen);if(!cfg||cfg.builtIn)return;delete state.screens[selectedScreen];persist();selectedScreen='live';updateAdminSelect();renderComposition();setAdminStatus('Pantalla personalizada eliminada.','saved')}
function setHeaderCollapsed(collapsed){
 document.body.classList.toggle('zre-header-collapsed',Boolean(collapsed));const btn=$('header-collapse-toggle');if(btn){btn.setAttribute('aria-expanded',String(!collapsed));btn.textContent=collapsed?'DESPLEGAR CONTROLES':'PLEGAR CONTROLES'}
 try{localStorage.setItem(HEADER_KEY,collapsed?'1':'0')}catch(_){}
}
function bind(){
 $('admin-screen-select')?.addEventListener('change',e=>{selectedScreen=e.target.value;renderComposition()});
 $('admin-save-screen')?.addEventListener('click',saveDraft);$('admin-save-screen-panel')?.addEventListener('click',saveDraft);
 $('admin-reset-screen')?.addEventListener('click',resetSelected);$('admin-reset-screen-panel')?.addEventListener('click',resetSelected);
 $('admin-create-screen')?.addEventListener('click',createCustom);$('admin-delete-screen')?.addEventListener('click',deleteSelected);
 $('admin-new-screen-name')?.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();createCustom()}});
 $('admin-screen-name')?.addEventListener('input',()=>{syncScreenName();setAdminStatus('Hay cambios sin guardar.','dirty')});
 $('admin-screen-name-panel')?.addEventListener('input',()=>{syncScreenName();setAdminStatus('Hay cambios sin guardar.','dirty')});
 $('screen-nav')?.querySelector('[data-zre-view="admin"]')?.addEventListener('click',()=>navigate?.('admin'));
 $('header-collapse-toggle')?.addEventListener('click',()=>setHeaderCollapsed(!document.body.classList.contains('zre-header-collapsed')));
}
function leaveView(view){if(view&&screen(view)&&!screen(view).builtIn)restoreMoved()}
function enterView(view){
 $('admin-view').hidden=view!=='admin';$('custom-view').hidden=!(screen(view)&&!screen(view).builtIn);
 if(view==='admin')renderAdmin();else if(screen(view)?.builtIn)applyBuiltIn(view);else if(screen(view))composeCustom(view);refreshNavigation();
}
function registerExternalComponents(defs){
 for(const def of defs||[]){
  if(!def?.id||!def?.selector||componentById.has(def.id))continue;
  const normalized={id:String(def.id),name:String(def.name||def.id),group:String(def.group||'KPI'),view:def.view||null,selector:String(def.selector),dynamic:true,sourceLabel:def.sourceLabel||'KPI',editorOptions:Array.isArray(def.editorOptions)?def.editorOptions:[]};
  COMPONENTS.push(normalized);componentById.set(normalized.id,normalized);
 }
 if(state){state=loadState()}if(draft)renderCatalog();
}
function init(options={}){
 if(state)return;state=loadState();navigate=typeof options.onNavigate==='function'?options.onNavigate:null;bind();updateAdminSelect();refreshNavigation();
 let collapsed=false;try{collapsed=localStorage.getItem(HEADER_KEY)==='1'}catch(_){}setHeaderCollapsed(collapsed);
 for(const key of Object.keys(BUILT_INS))applyBuiltIn(key);
 observer=new MutationObserver(()=>{if(!activeCustom)return;clearTimeout(observerTimer);observerTimer=setTimeout(()=>renderCustom(activeCustom),30)});
 observer.observe(document.body,{childList:true,subtree:true});
}
window.ZREScreenAdmin={init,enterView,leaveView,renderAdmin,renderCustom,applyBuiltIn,registerExternalComponents,screenLabel,isManaged:view=>view==='admin'||Boolean(screen(view)),isCustom:view=>Boolean(screen(view)&&!screen(view).builtIn),getState:()=>clone(state||loadState())};
})();