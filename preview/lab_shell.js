(() => {
  'use strict';
  const $=id=>document.getElementById(id),frame=$('lab-frame'),viewport=$('lab-viewport');
  const screens=['auto','practice','quali','race','pit','summary','spotter'];
  const scenarios=[
    ['practice-empty','PRÁCTICA · Sin vueltas','practice'],['practice-10','PRÁCTICA · 10 vueltas','practice'],
    ['practice-32','PRÁCTICA · 32 vueltas','practice'],['practice-70','PRÁCTICA · 70 vueltas','practice'],
    ['practice-anomaly','PRÁCTICA · Anomalías de ritmo','practice'],['quali-official','QUALI · Oficial','quali'],
    ['quali-consultation','QUALI · Consulta','quali'],['quali-simulated','QUALI · Simulada','quali'],
    ['quali-first','QUALI · Primera lanzada','quali'],['quali-attempts','QUALI · Tanda de intentos','quali'],
    ['quali-invalid','QUALI · Vuelta inválida','quali'],['quali-best','QUALI · Mejor vuelta','quali'],
    ['quali-positive','QUALI · Delta positivo','quali'],['quali-negative','QUALI · Delta negativo','quali'],
    ['quali-garage','QUALI · Garage','quali'],['quali-no-reference','QUALI · Sin referencia','quali'],
    ['race-sprint','CARRERA · Sprint','race'],['race-endurance','CARRERA · Endurance','race'],
    ['race-practice-preview','CARRERA · Vista en práctica','race'],['race-fuel-normal','CARRERA · Fuel normal','race'],
    ['race-fuel-critical','CARRERA · Fuel crítico','race'],['race-window-open','CARRERA · Window open','race'],
    ['race-box-next','CARRERA · Box próxima vuelta','race'],['race-box-now','CARRERA · Box esta vuelta','race'],
    ['race-pit','CARRERA · Pit road','race'],['race-caution','CARRERA · Caution','race'],
    ['race-rival-manual','CARRERA · Rival manual','race'],['race-rival-pit','CARRERA · Rival en boxes','race'],
    ['race-rival-stale','CARRERA · Rival ausente','race'],['race-driver-swap','CARRERA · Cambio piloto','race'],
    ['spotter-team','SPOTTER · Equipo identificado','spotter'],['spotter-swap','SPOTTER · Relevo','spotter'],
    ['spotter-pending','SPOTTER · Relevo pendiente','spotter'],['spotter-stop','SPOTTER · Plan parada','spotter'],
    ['spotter-pit','SPOTTER · Coche en boxes','spotter'],['spotter-estimated','SPOTTER · Fuel estimado','spotter'],
    ['spotter-rival','SPOTTER · Rival estratégico','spotter'],['special-disconnected','ESPECIAL · SDK desconectado','race'],
    ['special-incomplete','ESPECIAL · Datos incompletos','race'],['special-stale','ESPECIAL · Datos obsoletos','race'],
    ['special-many-cars','ESPECIAL · Muchos coches','race'],['special-long-names','ESPECIAL · Pilotos largos','race'],
    ['special-max-values','ESPECIAL · Valores máximos','race'],['special-finished','ESPECIAL · Sesión finalizada','summary']
  ];
  window.ZRELabScenarios=scenarios;
  let ready=false,screen='practice',scenario='practice-32',paused=false,diagnostic=false,lap=0,resolution='fluid',font='normal';
  const post=message=>{if(ready)frame.contentWindow.postMessage({zreLab:true,...message},location.origin)};
  const options=()=>{const list=$('lab-scenario');list.replaceChildren(...scenarios.map(([id,label])=>new Option(label,id)));list.value=scenario};
  function refresh(){post({type:'state',screen,scenario,paused,diagnostic,lap,font})}
  function measure(){const h=$('lab-toolbar').getBoundingClientRect().height;document.documentElement.style.setProperty('--lab-top',h+'px');
    const shell=document.querySelector('.lab-frame-shell'),bounds=shell.getBoundingClientRect();
    if(resolution==='fluid'){frame.style.width='100%';frame.style.height='100%';frame.style.transform='none';viewport.style.width='100%';viewport.style.height='100%';post({type:'viewport',width:Math.floor(bounds.width),height:Math.floor(bounds.height)});return}
    const [w,height]=resolution.split('x').map(Number),scale=Math.min(bounds.width/w,bounds.height/height,1);
    viewport.style.width=(w*scale)+'px';viewport.style.height=(height*scale)+'px';
    frame.style.width=w+'px';frame.style.height=height+'px';frame.style.transform='scale('+scale+')';
    post({type:'viewport',width:w,height});
  }
  $('lab-screen').addEventListener('change',e=>{screen=e.target.value;refresh()});
  $('lab-scenario').addEventListener('change',e=>{scenario=e.target.value;lap=0;const family=scenarios.find(x=>x[0]===scenario)?.[2];if(family&&screen==='auto')screen=family;refresh()});
  $('lab-resolution').addEventListener('change',e=>{resolution=e.target.value;measure();refresh()});
  $('lab-font').addEventListener('change',e=>{font=e.target.value;refresh()});
  $('lab-play').addEventListener('click',()=>{paused=!paused;$('lab-play').textContent=paused?'REANUDAR':'PAUSAR';refresh()});
  $('lab-lap').addEventListener('click',()=>{lap++;refresh()});
  $('lab-reset').addEventListener('click',()=>{lap=0;paused=false;$('lab-play').textContent='PAUSAR';refresh()});
  $('lab-overflow').addEventListener('click',()=>{diagnostic=!diagnostic;$('lab-overflow').setAttribute('aria-pressed',String(diagnostic));refresh()});
  $('lab-hide').addEventListener('click',()=>{document.body.classList.add('lab-bar-hidden');$('lab-show').hidden=false;measure()});
  $('lab-show').addEventListener('click',()=>{document.body.classList.remove('lab-bar-hidden');$('lab-show').hidden=true;measure()});
  window.addEventListener('message',e=>{if(e.origin!==location.origin||e.source!==frame.contentWindow||!e.data?.zreLab)return;
    if(e.data.type==='ready'){ready=true;refresh();measure();$('lab-status').textContent='Preview listo · todo es sintético · ninguna conexión con iRacing'}
    if(e.data.type==='status')$('lab-status').textContent=e.data.message;
    if(e.data.type==='error')$('lab-status').textContent='ERROR VISUAL LAB · '+e.data.message;
  });
  fetch('./lab_manifest.json',{cache:'no-store'}).then(r=>r.json()).then(meta=>{$('lab-version').textContent=meta.branch+' · '+meta.sha.slice(0,12)+' · v'+meta.version}).catch(()=>{$('lab-version').textContent='Versión no disponible'});
  const observer=new ResizeObserver(measure);observer.observe(document.body);window.addEventListener('resize',measure);
  options();measure();setInterval(()=>{if(!paused&&ready){lap++;refresh()}},12000);
})();