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
    text('pr-detail-confidence',curve.confidence?'Confianza: '+curve.confidence+(valid(curve.lossSeconds)?' · Pérdida media observada +'+curve.lossSeconds.toFixed(2)+' s':''):'DATOS INSUFICIENTES · todavía no hay diagnóstico validado');
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
      b.dataset.loss=valid(curve.lossSeconds)?(curve.lossSeconds>=.25?'significant':'observed'):'unknown';
      const top=document.createElement('span');top.className='pr-corner-top';
      const zone=document.createElement('strong');zone.textContent=curve.zone||'TRAMO '+(i+1);
      const confidence=document.createElement('small');confidence.textContent=(curve.confidence||'SIN EVIDENCIA')+(valid(curve.lossSeconds)?' · +'+curve.lossSeconds.toFixed(2)+' s':'');
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
        g.dataset.loss=valid(curve.lossSeconds)?(curve.lossSeconds>=.25?'significant':'observed'):'unknown';
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
  // Comparable laps define the operating mean; ALL observed timed laps remain
  // visible. Never use min/max dynamic scale for the default ±1 second view.
  let paceScale=(()=>{try{return localStorage.getItem('zre-pr-pace-scale')==='all'?'all':'focus'}catch(_){return'focus'}})();
  let lastRows=null;
  function renderPace(rows){
    const list=(Array.isArray(rows)?rows:[])
      .filter(r=>valid(r.seconds)&&r.seconds>0&&Number.isInteger(Number(r.lap)))
      .slice().sort((a,b)=>a.lap-b.lap);
    lastRows=list;
    const scale=el('pr-pace-scale');
    if(scale&&scale.value!==paceScale)scale.value=paceScale;
    const signature=JSON.stringify([list,paceScale]);if(lastPace===signature)return;lastPace=signature;
    const clean=list.filter(r=>r.comparable===true);
    text('pr-pace-count',list.length+' VUELTAS · '+clean.length+' COMPARABLES');
    const line=el('pr-pace-line'),dots=el('pr-pace-dots'),canvas=el('pr-pace-svg');
    if(!line||!dots||!canvas)return;
    let guides=el('pr-pace-guides'),segments=el('pr-pace-segments');
    if(!guides){guides=svg('g');guides.id='pr-pace-guides';canvas.insertBefore(guides,line)}
    if(!segments){segments=svg('g');segments.id='pr-pace-segments';canvas.insertBefore(segments,dots)}
    line.setAttribute('points','');dots.replaceChildren();guides.replaceChildren();segments.replaceChildren();
    if(!list.length||!clean.length){text('pr-pace-status',list.length?'SIN VUELTAS COMPARABLES':'SIN VUELTAS');return}
    const mean=clean.reduce((total,r)=>total+r.seconds,0)/clean.length;
    const speeds=list.map(x=>x.seconds),range=paceScale==='all'?
      [Math.min(...speeds,mean-0.10),Math.max(...speeds,mean+0.10)]:[mean-1,mean+1];
    const spread=Math.max(.2,range[1]-range[0]);
    const minLap=list[0].lap,maxLap=list[list.length-1].lap;
    const coord=r=>({
      x:32+360*(maxLap===minLap?.5:(r.lap-minLap)/(maxLap-minLap)),
      rawY:13+66*(r.seconds-range[0])/spread,
      y:Math.max(13,Math.min(79,13+66*(r.seconds-range[0])/spread)),
      outside:r.seconds<range[0]?'FAST':r.seconds>range[1]?'SLOW':null,
      row:r
    });
    // Fast laps are at the top (lower time). Three axes stay visible.
    const guide=(value,name,y)=>{
      const g=svg('line');g.setAttribute('x1','32');g.setAttribute('y1',String(y));
      g.setAttribute('x2','392');g.setAttribute('y2',String(y));g.setAttribute('class','pr-pace-guide');guides.append(g);
      const label=svg('text');label.setAttribute('x','1');label.setAttribute('y',String(y+2));
      label.setAttribute('class','pr-pace-axis');label.textContent=(name?name+' ':'')+value.toFixed(1);
      guides.append(label);
    };
    guide(range[0],'',13);guide(mean,'Ø',13+66*(mean-range[0])/spread);guide(range[1],'',79);
    let chain=[];
    const flush=()=>{
      if(chain.length>1){const node=svg('polyline');node.classList.add('pr-pace-connect');
        node.setAttribute('points',chain.map(p=>p.x.toFixed(2)+','+p.y.toFixed(2)).join(' '));
        segments.append(node)}
      chain=[];
    };
    for(const p of list.map(coord)){
      if(p.row.comparable===true&&!p.outside){chain.push(p)}
      else{flush()}
      const node=svg(p.outside?'path':'circle');
      node.setAttribute('class',p.row.comparable?'comparable':'not-comparable');
      if(p.outside){
        node.setAttribute('d',p.outside==='FAST'?
          'M'+(p.x-3)+' 19 L'+p.x+' 13 L'+(p.x+3)+' 19 Z':
          'M'+(p.x-3)+' 73 L'+p.x+' 79 L'+(p.x+3)+' 73 Z');
        node.classList.add('clipped');
      }else{
        node.setAttribute('cx',p.x);node.setAttribute('cy',p.y);
        node.setAttribute('r',p.row.comparable?'2.6':'2.2');
      }
      const title=svg('title');const flags=[!p.row.valid?'INVÁLIDA':null,p.row.caution?'CAUTION':null,p.row.onPitRoad?'PIT':null,p.outside?'FUERA DE ESCALA':null].filter(Boolean);
      title.textContent='V'+p.row.lap+' · '+p.row.seconds.toFixed(3)+' s · '+(p.row.comparable?'COMPARABLE':flags.join(' / ')||'NO COMPARABLE')+' · media '+mean.toFixed(3)+' s';node.append(title);dots.append(node);
    }
    flush();
    const last=list[list.length-1],diff=last.seconds-mean;
    text('pr-pace-status','Ø '+mean.toFixed(3)+' s · '+(paceScale==='focus'?'FOCO ±1.000 s':'TODAS')+
       ' · ÚLT. V'+last.lap+' '+(diff>0?'+':'')+diff.toFixed(3)+' s');
    canvas.dataset.averageSeconds=mean.toFixed(3);
    canvas.dataset.yMin=range[0].toFixed(3);
    canvas.dataset.yMax=range[1].toFixed(3);
    canvas.dataset.laps=String(list.length);
    canvas.dataset.comparable=String(clean.length);
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
    el('pr-pace-scale')?.addEventListener('change',event=>{
      paceScale=event.target.value==='all'?'all':'focus';
      try{localStorage.setItem('zre-pr-pace-scale',paceScale)}catch(_){}
      lastPace='';renderPace(lastRows||[]);
    });
    button?.addEventListener('click',()=>{
      const now=document.body.classList.toggle('zre-header-collapsed');
      try{localStorage.setItem('zre-header-collapsed-v1',now?'1':'0')}catch(_){}
      sync();
    });
  }
  window.ZREPractice={render,init};
  init();
})();
