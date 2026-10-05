(function(){
'use strict';
const registered=new Set();

function safeText(value){return value==null||value===''?'—':String(value)}
function cssState(state){return String(state||'WAITING').toLowerCase().replaceAll('_','-')}
function ensureCard(item){
  let node=document.querySelector('[data-zre-kpi-id="'+CSS.escape(item.id)+'"]');
  if(node)return node;
  const bank=document.getElementById('kpi-component-bank');
  if(!bank)return null;
  node=document.createElement('article');
  node.className='zre-kpi-card';
  node.dataset.zreKpiId=item.id;
  const head=document.createElement('div');head.className='zre-kpi-head';
  const label=document.createElement('span');label.className='zre-kpi-label';
  const state=document.createElement('small');state.className='zre-kpi-state';
  head.append(label,state);
  const value=document.createElement('strong');value.className='zre-kpi-value';
  const meta=document.createElement('small');meta.className='zre-kpi-meta';
  node.append(head,value,meta);bank.append(node);
  return node;
}
function register(item){
  if(registered.has(item.id))return;
  registered.add(item.id);
  window.ZREScreenAdmin?.registerExternalComponents?.([{
    id:'kpi:'+item.id,
    name:item.label,
    group:'KPI · '+safeText(item.group),
    selector:'[data-zre-kpi-id="'+item.id.replaceAll('"','\\"')+'"]',
    sourceLabel:'KPI'
  }]);
}
function render(library){
  const items=library?.items||[];
  for(const item of items){
    if(!item?.id)continue;
    register(item);
    const node=ensureCard(item);if(!node)continue;
    node.dataset.kpiState=item.state||'WAITING';
    node.dataset.kpiSource=item.source||'UNKNOWN';
    node.dataset.kpiSemantic=item.semantic||'LIVE';
    node.classList.remove('kpi-available','kpi-waiting','kpi-not-applicable','kpi-estimated','kpi-last-valid','kpi-stale');
    node.classList.add('kpi-'+cssState(item.state));
    const label=node.querySelector('.zre-kpi-label'),state=node.querySelector('.zre-kpi-state'),value=node.querySelector('.zre-kpi-value'),meta=node.querySelector('.zre-kpi-meta');
    if(label&&label.textContent!==safeText(item.label))label.textContent=safeText(item.label);
    if(state&&state.textContent!==safeText(item.state))state.textContent=safeText(item.state);
    if(value&&value.textContent!==safeText(item.display))value.textContent=safeText(item.display);
    if(meta){
      const bits=[item.source,item.semantic].filter(Boolean);
      const text=bits.join(' · ');if(meta.textContent!==text)meta.textContent=text;
    }
    node.title=item.description||'';
  }
}
window.ZREKPI={render,getRegistered:()=>[...registered]};
})();