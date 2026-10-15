/* ZRE Visual Lab: browser-only synthetic transport for the actual ZRE renderers.
 * This module is included ONLY by preview builder; never by the Windows app. */
(() => {
 'use strict';
 const $=id=>document.getElementById(id);
 const note=message=>window.parent.postMessage({zreLab:true,type:'status',message},location.origin);
 const state={screen:'practice',scenario:'practice-32',lap:0,paused:false,font:'normal',diagnostic:false,rival:null,qOverride:null};
 let render=null,latest=null,ready=false;
 const ftime=n=>{if(!Number.isFinite(n)||n<=0)return '—';const m=Math.floor(n/60);return m+':'+(n-m*60).toFixed(3).padStart(6,'0')};
 const names=['Alex Rivera','Noah Vega','Lucas Mora','Ari Blake','Ren Kim','Sam Torres','Max Foster','Robin Cruz','Eli Morgan','Taylor Silva','Jordan López','Kai Parker','Leo Chen','Uma Costa','Mila Reed','Drew Hale','Ash Baker','Luca West','Emery Lane','Casey Fox','Ira Stone','Quinn Miller','Jules Ross','Rowan Gray','Nico Bell','Billie Knight','Remy Hunt','Morgan Snow','Aiden Cruz','Kim Young'];
 const sections=[0,0.21,0.43,0.69];
 const rawSeries=(idx,count,shift)=>Array.from({length:count},(_,i)=>{
   const lap=Math.max(1,25-count+i+state.lap),seconds=92.1+shift+Math.sin((i+idx)*1.3)*.24+(i%14===0?.35:0);
   return {lapNumber:lap,lapTimeSeconds:+seconds.toFixed(3),sessionTime:lap*93,comparable:true,comparabilityReason:'LAB_SINTETICO',source:'LAB_FIXTURE'};
 });
 const pace=(idx,count,shift,roles)=>{
   const samples=rawSeries(idx,count,shift).slice(-8);
   const times=samples.filter(x=>x.comparable).slice(-5).map(x=>x.lapTimeSeconds);
   const n=times.length,avg=n>=3?+(times.reduce((a,b)=>a+b,0)/n).toFixed(3):null;
   return {carIdx:idx,carNumber:String(10+idx),driverName:names[idx%names.length],roles,samples,recentAverageSeconds:avg,sampleCount:n,representative:n>=3,observationState:'LIVE'};
 };
 const mapPoints=()=>Array.from({length:80},(_,i)=>{
   const a=i*Math.PI*2/79,r=32+Math.sin(3*a)*5+Math.cos(5*a)*3;
   return {x:+(50+Math.cos(a)*r*1.17).toFixed(2),y:+(50+Math.sin(a)*r*.82).toFixed(2),pct:i/79};
 });
 const corners=()=>Array.from({length:16},(_,i)=>({
   id:'LAB-C'+(i+1),zone:'CURVA '+(i+1),title:i%3===0?'Pérdida en frenada':i%3===1?'Salida de curva':'Transición',
   advice:'Escenario sintético: '+(i%2?'comparar salida y tracción':'verificar punto de frenado')+'.',
   confidence:i%4===0?'MEDIA':'ALTA',state:i%6===0?'insufficient':'diagnosis',
   lossSeconds:i%6===0?null:+(.05+(i%5)*.07).toFixed(3),pct:(i+1)/17
 }));
 const makeLaps=(n,anomaly)=>Array.from({length:n},(_,i)=>{
   const invalid=anomaly&&i%7===3;
   const seconds=92.35+Math.sin(i*1.7)*.33+Math.cos(i/6)*.12+(invalid?7.8:0);
   return {lap:i+1,seconds:+seconds.toFixed(3),comparable:!invalid,valid:!invalid,caution:false,
     time:ftime(seconds),delta:(seconds-92.1>=0?'+':'')+(seconds-92.1).toFixed(3),
     consumption:(2.25+(i%5)*.03).toFixed(2)+' L',
     source:'LAB_FIXTURE',comparabilityReason:invalid?'ANOMALO':'SINTETICO'};
 });
 function makeData(){
   const id=state.scenario,pref=id.split('-')[0],flags=new Set(id.split('-'));
   const practice=id.startsWith('practice'),quali=id.startsWith('quali'),spotter=id.startsWith('spotter');
   const count=practice?(id==='practice-empty'?0:id==='practice-10'?10:id==='practice-70'?70:id==='practice-32'||id==='practice-anomaly'?32:10):18;
   const anomaly=id==='practice-anomaly',laps=makeLaps(count+state.lap,anomaly);
   const comparable=laps.filter(x=>x.comparable),average=comparable.length?comparable.reduce((t,x)=>t+x.seconds,0)/comparable.length:null;
   const last=laps.at(-1),best=comparable.length?Math.min(...comparable.map(x=>x.seconds)):null;
   const totalCars=id==='special-many-cars'?42:25;
   const longNames=id==='special-long-names';
   const standings=Array.from({length:totalCars},(_,i)=>{
     const idx=i+1,name=longNames?names[i%names.length]+' DE LA ESCUDERÍA DE RESISTENCIA INTERNACIONAL':names[i%names.length];
     const time=91.5+(idx%7)*.17;
     return {carIdx:idx,carNumber:String(10+idx),driverName:name,carModel:'GT3 TEST',teamName:'LAB TEAM '+idx,
       classId:1,officialClassPosition:idx,classPosition:idx,overallPosition:idx,positionSource:'RESULTS_POSITIONS',
       bestLapSeconds:time,lastLapSeconds:time+.34,recentPaceSeconds:time+.22,recentPaceSamples:5,
       lastSeenAgo:0,lastSeenSessionTime:1400, presence:'LIVE',isPlayer:idx===10};
   });
   const stale=id==='race-rival-stale'||id==='special-stale',pit=id==='race-rival-pit'||id==='spotter-pit'||id==='race-pit';
   if(id==='race-driver-swap'||id==='spotter-swap')standings[8].driverName='Piloto Relevo Sintético';
   const own=standings.find(x=>x.carIdx===10),chosen=Number.isInteger(state.rival)?state.rival:(id==='race-rival-manual'?13:9);
   const rival=standings.find(x=>x.carIdx===chosen)||standings[8];
   if(stale){rival.presence='STALE';rival.lastSeenAgo=125}
   const ahead={carIdx:9,carNumber:'19',driverName:standings[8].driverName,relativeLapFraction:.036,gapSeconds:2.38,
      gapLabel:'≈ 2.38 s · EST.',gapSource:'SDK_DYNAMIC_ESTIMATE',gapConfidence:'ESTIMATED',observationState:'LIVE',presence:'LIVE',driver:standings[8].driverName,number:'19'};
   const behind={carIdx:11,carNumber:'21',driverName:standings[10].driverName,relativeLapFraction:-.022,gapSeconds:1.64,
      gapLabel:'≈ 1.64 s · EST.',gapSource:'SDK_DYNAMIC_ESTIMATE',gapConfidence:'ESTIMATED',observationState:'LIVE',presence:'LIVE',driver:standings[10].driverName,number:'21'};
   const roles={YOU:10,AHEAD:9,BEHIND:11,RIVAL:rival.carIdx},groups=new Map();
   for(const [role,idx] of Object.entries(roles))groups.set(idx,[...(groups.get(idx)||[]),role]);
   const series=[...groups].map(([idx,rs])=>pace(idx,8,idx===10?0:idx===9?-.3:idx===11?.45:.15,rs));
   if(stale)series.find(x=>x.carIdx===rival.carIdx).observationState='STALE';
   const avgRole=key=>series.find(x=>x.carIdx===roles[key])?.recentAverageSeconds;
   const target=47,lapNo=33+state.lap;
   const critical=id==='race-fuel-critical',disconnect=id==='special-disconnected',incomplete=id==='special-incomplete';
   const observed=2.28,targetFuel=2.25,fuel=critical?3.3:42.6;
   let windowState='PLAN STABLE';
   if(id==='race-window-open')windowState='WINDOW OPEN';
   if(id==='race-box-next')windowState='BOX NEXT LAP';
   if(id==='race-box-now')windowState='BOX THIS LAP';
   const boxLap=(windowState==='BOX THIS LAP'?lapNo:windowState==='BOX NEXT LAP'?lapNo+1:target);
   const raceMode=quali?'qualifying':practice||id==='race-practice-preview'?'practice':'race_engineer';
   const plan={available:!incomplete,minimum_stops:id==='race-sprint'?0:2,
      current_autonomy_laps:+(fuel/observed).toFixed(1),
      window:{earliest_safe:Math.max(1,boxLap-3),target:boxLap,fuel_limit:boxLap+3,state:windowState},
      stops:id==='race-sprint'?[]:[{number:2,lap:boxLap,earliest_safe:boxLap-3,fuel_limit:boxLap+3,fuel_to_add_liters:65.3,driver:'LAB PILOTO 2'}],
      finish:{low:92,high:94},state:'ESTABLE'};
   const vnext={available:plan.available,currentPlan:plan,plan,initialPlan:plan,
      raceState:{current_lap:lapNo,completed_laps:lapNo-1,on_pit_road:pit,require_tire_change:false},
      fuelModel:{observed_lpl:observed,strategy_lpl:targetFuel,source:'LAB_SYNTHETIC',confidence:'LAB · SINTÉTICO',green_samples:9,historical_samples:18},
      transition:windowState,stopHistory:[]};
   let qMode=id==='quali-simulated'?'simulated':quali?'official':null;
   if(id==='quali-consultation')qMode=null;
   if(state.qOverride)qMode=state.qOverride;
   const attemptNum=id==='quali-first'?0:id==='quali-no-reference'?0:id==='quali-attempts'||id==='quali-garage'?5:3;
   const attempts=Array.from({length:attemptNum},(_,i)=>{
     const status=id==='quali-invalid'&&i===attemptNum-1?'INVALID':'VALID';
     return {attemptId:'LAB-Q'+(i+1),sourceLap:i+2,lapTime:92.4-i*.11,status,
       validity:status==='VALID'?'SDK_CONFIRMED':'ZRE_INCOMPLETE',sectorSource:'SDK_SPLITS',
       sectorTimes:[27.1-i*.02,30.3-i*.04,35-i*.05]};
   });
   const q={qualifyingMode:qMode,inGarage:id==='quali-garage',onTrack:true,onPitRoad:false,
     officialSessionIdentity:'LAB_SESSION_'+id,officialSessionType:'Qualify',fuelValue:27.1,fuelPerLap:2.18,autonomyLaps:12.4,
     activeRun:{runId:'LAB-01',attempts,bestValidLap:attempts.filter(x=>x.status==='VALID').reduce((a,x)=>Math.min(a,x.lapTime),Infinity),counts:{VALID:attempts.filter(x=>x.status==='VALID').length,INVALID:attempts.filter(x=>x.status==='INVALID').length}},
     previousRuns:[],activeAttempt:{status:id==='quali-first'?'FLYING':'IN LAP'},sectorBoundaries:sections,
     sectorTimes:[27.12,30.28,35.11],lastSectors:[27.2,30.4,35.2],deltaReferences: id==='quali-no-reference'?{}:{
       LapDeltaToBestLap:{valid:true,value:id==='quali-negative'?-.246:id==='quali-positive'?.312:-.083}}};
   if(!Number.isFinite(q.activeRun.bestValidLap))q.activeRun.bestValidLap=null;
   const curve=corners(),trackMap={points:mapPoints(),geometrySource:'TRAZADO SINTÉTICO LAB',
     markers:curve.slice(0,3).map(x=>({...trackPoint(x.pct),label:x.zone}))};
   function trackPoint(pct){return trackMapRef(Math.floor(pct*79))}
   function trackMapRef(i){return mapPoints()[Math.max(0,Math.min(79,i))]}
   const ownLaps=laps.map(x=>({lap:x.lap,time:x.time,delta:x.delta,consumption:x.consumption}));
   const raceObj={sessionIdentity:'LAB_SESSION_'+id,ownCarIdx:10,ownClassPosition:10,ownOverallPosition:10,
     ownPositionSource:'RESULTS_POSITIONS',classStandings:standings,
     physical:{ahead,behind,source:'LAB_DYNAMIC_ESTIMATED'},
     roles,paceSeries:series,paceDifferenceToRival:avgRole('YOU')-avgRole('RIVAL'),
     rival:{selectionMode:state.rival!==null||id==='race-rival-manual'?'manual':'auto',
       requestedCarIdx:state.rival!==null?state.rival:(id==='race-rival-manual'?13:null),
       effectiveCarIdx:rival.carIdx,selectionState:stale?'TEMPORARILY_UNAVAILABLE':'AVAILABLE',
       selectedRival:rival,rivalPace:avgRole('RIVAL'),
       observation:{presence:stale?'STALE':'LIVE',onPitRoad:pit,lastSeenAgo:stale?125:0,
         gapEvidence:{seconds:2.38,source:'LAB_ESTIMATE'}}},
     fuel:{currentLiters:fuel,observedLpl:observed,targetLpl:targetFuel,deviationLpl:observed-targetFuel,
       autonomyLaps:+(fuel/observed).toFixed(2),source:'LAB_SYNTHETIC',sampleCount:9},
     practicePreview:id==='race-practice-preview'};
   const candidates=standings.filter(x=>!x.isPlayer).map(x=>({idx:x.carIdx,label:'#'+x.carNumber+' · '+x.driverName,position:'P'+x.classPosition}));
   const classRows=standings.slice(0,20).map(x=>({idx:x.carIdx,pos:x.classPosition,isPlayer:x.isPlayer,number:x.carNumber,driver:x.driverName,car:x.carModel,
     bestLap:ftime(x.bestLapSeconds),lastLap:ftime(x.lastLapSeconds),pace:ftime(x.recentPaceSeconds),gap:'—'}));
   const connected=!disconnect,mode=state.screen==='auto'?raceMode:state.screen==='practice'?'practice':
     state.screen==='quali'?'qualifying':state.screen==='race'?'race_engineer':raceMode;
   if(id==='special-many-cars')raceObj.classStandings=standings;
   if(incomplete){raceObj.physical={ahead:null,behind:null,source:'SIN DATO'};raceObj.fuel={source:'SIN DATO'};raceObj.paceSeries=[];raceObj.roles={YOU:10,AHEAD:null,BEHIND:null,RIVAL:null}}
   if(id==='special-max-values'){raceObj.fuel.currentLiters=125.9;raceObj.fuel.autonomyLaps=123.5}
   const timestamp=2000+state.lap*93;
   return {
     demo:true,connected,captureStatus:'SIMULACIÓN · NO HAY SDK',sessionMode:mode,
     sessionType:mode==='qualifying'?'Qualify':mode==='practice'?'Practice':'Race',
     buildIdentity:{mode:'VISUAL LAB · SIMULADO',runtimeVersion:'2.6.7',sourceCommit:window.ZRELabManifest?.sha||'PREVIEW',instanceId:'LAB'},
     header:{car:'GT3 DE PRUEBA #20',track:'CIRCUITO SINTÉTICO · NO iRACING',driver:'Piloto LAB',
       position:'P10',lap:String(lapNo),state:connected?'SIMULADO · '+mode.toUpperCase():'SDK SIMULADO DESCONECTADO'},
     self:{pit:pit?'EN BOXES':'EN PISTA',lastLap:last?.time||'—',bestLap:ftime(best),fuel:fuel.toFixed(1)+' L · SIMULADO',
       fuelValue:fuel,fuelSource:'LAB_SYNTHETIC',lastUse:'2.28 L',bestUse:'2.19 L',worstUse:'2.44 L',
       pitWindow:'V'+boxLap,nextStop:'V'+boxLap,wear:{FL:'91%',FR:'92%',RL:'90%',RR:'93%'},laps:ownLaps,
       position:'P10'},
     practiceAnalytics:{laps,lastValidLap:comparable.at(-1)?.time||'—',averageLap:ftime(average),
       consistencySeconds:comparable.length?.246:null,lastDelta:last?.delta||'—',
       fuelAverage:2.28,fuelLast:2.31,fuelMin:2.16,fuelMax:2.48,fuelLapsEstimated:fuel/observed},
     coach:{bestLap:ftime(best),optimalLap:ftime(best?best-.3:null),potential:ftime(best?best-.18:null),
       trackMap,allCorners:count===0?[]:curve,
       curveRecommendations:count===0?[]:curve.filter(x=>x.lossSeconds).slice(0,3),
       primary:curve[0],secondary:curve[1],reference:'ÓPTIMA · SIMULADA',
       pattern:'Comparar puntos de frenada',patternConfidence:'MEDIA',patternAdvice:'Datos de ejemplo',diagnostics:{}},
     qualifying:q,sessionIntelligence:{caution:{active:id==='race-caution'},
       traffic:{observed:{nearestAhead:ahead,nearestBehind:behind}},
       environment:{observed:{TrackTemp:37.5}},session:{observed:{flags:id==='race-caution'?0x4000:0x0004}}},
     raceDashboard:raceObj,racePlanVNext:vnext,practiceRacePlan:vnext,
     racePlan:{stops:[{lap:boxLap}],stopsRemaining:2,autonomyLaps:fuel/observed},
     raceDirector:{selectedIdx:rival.carIdx,requestedCarIdx:raceObj.rival.requestedCarIdx,
       mode:raceObj.rival.selectionMode,rival:'#'+rival.carNumber+' '+rival.driverName,position:'P'+rival.classPosition,
       gap:'≈2.38 s · EST.',lastLap:ftime(rival.lastLapSeconds),lap:String(lapNo),pit:pit?'PIT':'EN PISTA',
       status:stale?'STALE / SIN SEÑAL':'SIMULADO',confidence:'LAB',candidates},
     enduranceStrategy:{raceFormat:id==='race-endurance'?'ENDURANCE':id==='race-sprint'?'SPRINT':null,
       stopPlan:{stops:[{lap:boxLap}],stopsRemaining:2}},
     teamContext:{autoMode:spotter?'spotter':'driver',carIdx:10,carNumber:'20',driver:'Piloto LAB',
       driverSource:'LAB_SYNTHETIC',remainingTime:id==='race-endurance'?'06:35:00':'00:42:10',fuelState:'LAB',
       manualEvents:[],controlError:'LAB · NO ENVÍA ACCIONES'},
     strategy:{consumption:'2.28 L/v',nextStop:'V'+boxLap,addFuel:'+65.3 L',lapsRemaining:14},
     relative:classRows.slice(6,13),standing:classRows,
     sessionSummary:{active:id==='special-finished',lapCount:laps.length,bestLap:ftime(best),
       optimalLap:ftime(best?best-.3:null),potential:ftime(best?best-.18:null),
       priorities:curve.slice(0,3)},
     setupEngineer:{available:true,status:'SINTÉTICO · SOLO VISUAL',owner:{authorized:false,reason:'SOLO VISUAL LAB'},
       setupName:'DEMO · SIN ARCHIVO',setupSource:'LAB'},
     kpiLibrary:null
   };
 }
 function scenarioRender(){
   if(!render)return;
   latest=makeData();
   try{render(latest);$('notice').textContent='ZRE VISUAL LAB · DATOS SINTÉTICOS · '+state.scenario.toUpperCase();
      if(state.diagnostic)requestAnimationFrame(checkOverflow);
   }catch(err){window.parent.postMessage({zreLab:true,type:'error',message:err.message+' · '+(err.stack||'').split('\n')[1]},location.origin);
      console.error('Visual Lab snapshot failed',err)}
 }
 function checkOverflow(){
   document.querySelectorAll('.lab-overflow').forEach(x=>x.classList.remove('lab-overflow'));
   if(!state.diagnostic)return;
   const w=window.innerWidth,h=window.innerHeight;let count=0;
   document.querySelectorAll('main.dashboard article,main.dashboard button,main.dashboard select,main.dashboard .rv2-kpi').forEach(el=>{
     if(!el.getClientRects().length||!el.offsetParent||el.closest('[hidden]'))return;
     const r=el.getBoundingClientRect();
     if(r.right>w+2||r.left < -2||r.bottom>h+4){el.classList.add('lab-overflow');count++}
   });
   note('LAB DIAGNÓSTICO · '+count+' controles/paneles potencialmente desbordados · '+w+'×'+h);
 }
 function notifyOnly(label){note(label+' · FUNCIÓN DISPONIBLE SOLO EN ZRE LOCAL · no se ejecutó ninguna acción real');}
 function action(packet){
   if(!packet||typeof packet!=='object')return;
   if(packet.type==='settings'){
     if(packet.key==='rival'){
       state.rival=packet.value==='auto'?null:Number(packet.value);
       scenarioRender();return;
     }
     if(packet.key==='teamDriver'||packet.key==='teamCar'||packet.key==='role'){
       if(packet.key!=='role')notifyOnly('AJUSTE DE EQUIPO');
       return;
     }
     if(packet.key==='strategy')return; // UI preference only, never writes a plan.
     notifyOnly('AJUSTE '+String(packet.key).toUpperCase());return;
   }
   if(packet.type==='action'&&packet.action==='quali_mode'){
     if(packet.value==='new_run'){notifyOnly('NUEVA TANDA REAL');return}
     state.qOverride=packet.value==='simulate'?'simulated':null;scenarioRender();return;
   }
   if(packet.type==='action'||packet.type==='spotterEvent'){notifyOnly(String(packet.action||'OPERACIÓN').toUpperCase());return}
 }
 function safeClicks(){
   const blocked=['capture-sdk','audio-test','setup-feedback-save','setup-report-export','setup-html-file',
     'archive-open','archive-clean','archive-protect','archive-export','archive-refresh'];
   document.addEventListener('click',e=>{
     const target=e.target.closest('button,input[type="file"],a');
     if(!target)return;
     if(blocked.includes(target.id)||target.matches('[data-spotter-action]')){
       e.preventDefault();e.stopImmediatePropagation();notifyOnly(target.textContent.trim()||target.id||'ACCIÓN');}
   },true);
   document.addEventListener('submit',e=>{
     const form=e.target;
     if(form?.id?.includes('export')){e.preventDefault();e.stopImmediatePropagation();notifyOnly('EXPORTACIÓN')}
   },true);
 }
 function selectScreen(){
   const select=$('screen-mode-select'),screen=state.screen;
   if(select&&select.value!==screen){select.value=screen;select.dispatchEvent(new Event('change',{bubbles:true}))}
   if(screen==='spotter'&&$('role-select').value!=='spotter'){
     $('role-select').value='spotter';$('role-select').dispatchEvent(new Event('change'))}
   else if(screen!=='spotter'&&$('role-select').value!=='driver'){
     $('role-select').value='driver';$('role-select').dispatchEvent(new Event('change'))}
   // Quali garage is an existing subview driven by the synthetic inGarage flag.
 }
 function receive(e){
   if(e.origin!==location.origin||e.source!==window.parent||!e.data?.zreLab)return;
   const msg=e.data;
   if(msg.type==='state'){
     state.screen=msg.screen||'auto';state.scenario=msg.scenario||'practice-32';state.lap=Math.min(200,Number(msg.lap)||0);
     state.paused=!!msg.paused;state.font=msg.font||'normal';state.diagnostic=!!msg.diagnostic;
     document.body.classList.toggle('lab-diagnose',state.diagnostic);
     document.body.dataset.raceFont=state.font;
     if($('rv2-font-select'))$('rv2-font-select').value=state.font;
     selectScreen();scenarioRender();if(state.diagnostic)requestAnimationFrame(checkOverflow);
   }
   if(msg.type==='viewport'&&state.diagnostic)requestAnimationFrame(checkOverflow);
 }
 function start(appRender){
   if(ready)return;ready=true;render=appRender;
   safeClicks();
   window.addEventListener('message',receive);
   window.parent.postMessage({zreLab:true,type:'ready'},location.origin);
   scenarioRender();
 }
 window.ZREVisualLab={enabled:true,start,action,getSnapshot:()=>latest,
   setScenario:id=>{state.scenario=id;scenarioRender()}};
})();