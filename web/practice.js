/* Dedicated practice renderer; no Screen Builder dependency or new telemetry engine. */
(() => {
  'use strict';
  const el=id=>document.getElementById(id);
  const text=(id,value)=>{const node=el(id);if(node){const v=value==null||value===''?'—':String(value);if(node.textContent!==v)node.textContent=v;}};
  const svg=(tag)=>document.createElementNS('http://www.w3.org/2000/svg',tag);
  const valid=n=>typeof n==='number'&&Number.isFinite(n);
  const fuel=n=>valid(n)&&n>0?n.toFixed(2)+' L/v':'—';
  let lastCorners='',lastMap='',lastPace='',selected=null,curves=[];

  function selectCorner(id,showDetail=false){
    selected=id;
    document.querySelectorAll('.pr-corner').forEach(n=>n.dataset.selected=String(n.dataset.corner===id));
    document.querySelectorAll('.pr-map-zone').forEach(n=>n.dataset.selected=String(n.dataset.corner===id));
    const curve=curves.find(c=>c.id===id);
    if(!showDetail||!curve)return;
    text('pr-detail-zone',curve.zone||curve.id);
    text('pr-detail-title',curve.title||'Sin diagnóstico validado');
    text('pr-detail-advice',curve.advice||'No hay evidencia suficiente para una recomendación específica.');
    text('pr-detail-confidence',curve.confidence?'Confianza: '+curve.confidence:'DATOS INSUFICIENTES · todavía no hay diagnóstico validado');
    const dialog=el('pr-corner-dialog');
    if(dialog&&!dialog.open)dialog.showModal();
  }

  function renderCorners(coach){
    curves=Array.isArray(coach?.allCorners)?coach.allCorners:[];
    const host=el('pr-corners');if(!host)return;
    text('pr-coach-status',curves.length?curves.length+' CURVAS / ZONAS':'CONSTRUYENDO REFERENCIA');
    const signature=JSON.stringify(curves);
    if(signature===lastCorners)return;
    lastCorners=signature;
    const count=curves.length,columns=count>=19?4:count>=11?3:count>=5?2:1;
    const rows=Math.max(1,Math.ceil(count/columns));
    host.style.setProperty('--pr-cols',columns);
    host.style.setProperty('--pr-rows',rows);
    if(!count){
      const p=document.createElement('p');p.className='curve-coach-empty';
      p.textContent='Esperando curvas detectadas por ZRE. Completa vueltas válidas para construir la referencia.';
      host.replaceChildren(p);return;
    }
    host.replaceChildren(...curves.map((curve,i)=>{
      const b=document.createElement('button');b.type='button';b.className='pr-corner';b.dataset.corner=curve.id||String(i);
      b.dataset.diagnosis=String(curve.state==='diagnosis');
      const top=document.createElement('span');top.className='pr-corner-top';
      const zone=document.createElement('strong');zone.textContent=curve.zone||'TRAMO '+(i+1);
      const confidence=document.createElement('small');confidence.textContent=curve.confidence||'SIN EVIDENCIA';
      top.append(zone,confidence);
      const title=document.createElement('b');title.textContent=curve.title||'Sin diagnóstico validado';
      const advice=document.createElement('em');advice.textContent=curve.state==='diagnosis'?(curve.advice||'Recomendación disponible'):'Datos insuficientes';
      b.title='Abrir diagnóstico completo: '+(curve.zone||'TRAMO');
      b.setAttribute('aria-label',b.title);
      b.append(top,title,advice);b.addEventListener('click',()=>selectCorner(b.dataset.corner,true));
      return b;
    }));
    if(!curves.some(c=>c.id===selected))selected=curves[0].id;
    selectCorner(selected);
    // The map may have been drawn before the corner data changed.
    lastMap='';
  }
  function renderMap(map){
    const trace=Array.isArray(map?.points)?map.points:[];
    const ok=trace.length>10;
    const signature=JSON.stringify([map?.points,curves.map(x=>[x.id,x.pct,x.state])]);
    if(signature===lastMap)return;
    lastMap=signature;
    const line=el('pr-track-line'),group=el('pr-track-zones');
    if(!line||!group)return;
    line.setAttribute('points',ok?trace.filter(p=>valid(p.x)&&valid(p.y)).map(p=>p.x+','+p.y).join(' '):'');
    el('pr-map-empty').hidden=ok;
    text('pr-map-status',ok?(map.geometrySource||'TRAZADO SDK'):'SIN TRAZADO VALIDADO');
    const spots=[];
    if(ok){
      curves.forEach(curve=>{
        if(!valid(curve.pct))return;
        const best=trace.reduce((a,b)=>Math.abs(Number(b.pct)-curve.pct)<Math.abs(Number(a.pct)-curve.pct)?b:a,trace[0]);
        if(!valid(best.x)||!valid(best.y))return;
        const g=svg('g');g.classList.add('pr-map-zone');g.dataset.corner=curve.id;
        g.dataset.diagnosis=String(curve.state==='diagnosis');
        g.dataset.selected=String(curve.id===selected);g.setAttribute('tabindex','0');g.setAttribute('role','button');
        g.setAttribute('aria-label','Ver '+curve.zone);
        const circle=svg('circle');circle.setAttribute('cx',best.x);circle.setAttribute('cy',best.y);circle.setAttribute('r','2.3');
        const label=svg('text');label.setAttribute('x',best.x+2.5);label.setAttribute('y',best.y-2.5);label.textContent=curve.zone;
        g.append(circle,label);g.addEventListener('click',()=>selectCorner(curve.id,true));
        g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectCorner(curve.id,true);}});
        spots.push(g);
      });
    }
    group.replaceChildren(...spots);
  }
  function renderPace(rows){
    const validRows=Array.isArray(rows)?rows.filter(r=>valid(r.seconds)&&r.seconds>0):[];
    const signature=JSON.stringify(validRows);if(lastPace===signature)return;lastPace=signature;
    text('pr-pace-count',validRows.length+' vueltas válidas');
    const line=el('pr-pace-line'),dots=el('pr-pace-dots');if(!line||!dots)return;
    if(!validRows.length){line.setAttribute('points','');dots.replaceChildren();text('pr-pace-status','SIN VUELTAS VÁLIDAS');return;}
    const values=validRows.map(r=>r.seconds),min=Math.min(...values),max=Math.max(...values),range=Math.max(.15,max-min);
    const points=validRows.map((row,i)=>({
      x:12+(validRows.length===1?188:i*376/(validRows.length-1)),
      y:12+70*(row.seconds-min)/range,row
    }));
    line.setAttribute('points',points.map(p=>p.x.toFixed(1)+','+p.y.toFixed(1)).join(' '));
    dots.replaceChildren(...points.map(p=>{const node=svg('circle');node.setAttribute('cx',p.x);node.setAttribute('cy',p.y);node.setAttribute('r','2.4');const title=svg('title');title.textContent='V'+p.row.lap+' · '+p.row.seconds.toFixed(3)+' s';node.append(title);return node;}));
    const last=values[values.length-1],prev=values.length>=2?values[values.length-2]:null;
    text('pr-pace-status',prev==null?'REFERENCIA EN FORMACIÓN':last<prev?'MEJORA '+(prev-last).toFixed(3)+' s':last>prev?'MÁS LENTO +'+(last-prev).toFixed(3)+' s':'RITMO ESTABLE');
  }
  function render(data){
    const analytics=data.practiceAnalytics||{},coach=data.coach||{},self=data.self||{};
    text('pr-best',self.bestLap);
    text('pr-last',analytics.lastValidLap);
    text('pr-optimal',coach.optimalLap);
    text('pr-delta',analytics.lastDelta);
    const trend=String(analytics.lastDelta||'');
    el('pr-delta').dataset.trend=trend.startsWith('+')?'loss':trend.startsWith('-')?'gain':'neutral';
    text('pr-average',analytics.averageLap);
    text('pr-consistency',valid(analytics.consistencySeconds)?'±'+analytics.consistencySeconds.toFixed(3)+' s':'—');
    text('pr-fuel',valid(self.fuelValue)?self.fuelValue.toFixed(1)+' L':'—');
    text('pr-fuel-source',self.fuelSource||'SIN DATO');
    text('pr-fuel-avg',fuel(analytics.fuelAverage));
    text('pr-fuel-last',fuel(analytics.fuelLast));
    text('pr-fuel-min',fuel(analytics.fuelMin));
    text('pr-fuel-max',fuel(analytics.fuelMax));
    text('pr-fuel-range',valid(analytics.fuelLapsEstimated)?'≈ '+analytics.fuelLapsEstimated.toFixed(1)+' v':'—');
    text('pr-pace-fuel',valid(analytics.fuelAverage)?'Consumo válido '+fuel(analytics.fuelAverage):'Consumo: sin datos válidos');
    renderCorners(coach);renderMap(coach.trackMap);renderPace(analytics.laps);
  }
  function init(){
    const button=el('header-collapse-toggle');
    const sync=()=>{
      const collapsed=document.body.classList.contains('zre-header-collapsed');
      if(button){button.textContent=collapsed?'MOSTRAR CONTROLES':'PLEGAR CONTROLES';button.setAttribute('aria-expanded',String(!collapsed));}
    };
    try{document.body.classList.toggle('zre-header-collapsed',localStorage.getItem('zre-header-collapsed-v1')==='1')}catch(_){}
    sync();
    button?.addEventListener('click',()=>{
      const now=document.body.classList.toggle('zre-header-collapsed');
      try{localStorage.setItem('zre-header-collapsed-v1',now?'1':'0')}catch(_){}
      sync();
    });
  }
  window.ZREPractice={render,init};
  init();
})();
