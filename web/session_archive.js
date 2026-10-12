/* Session journal administration. Works in the existing Screen Builder view.
 * All data stays on this PC, exports are written to reports/. */
(() => {
 'use strict';
 const $=id=>document.getElementById(id);
 const text=(id,value)=>{const node=$(id);if(node)node.textContent=String(value??'—')};
 const size=n=>{if(!Number.isFinite(Number(n)))return'—';const k=Number(n);return k>=1073741824?(k/1073741824).toFixed(2)+' GB':k>=1048576?(k/1048576).toFixed(1)+' MB':(k/1024).toFixed(1)+' KB'};
 let busy=false,lastAt=0;
 const request=async(path,payload)=>{const options=payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)};
   const response=await fetch(path,{...options,cache:'no-store'});
   if(!response.ok)throw new Error('HTTP '+response.status+' · '+response.statusText);
   return response.json();
 };
 const message=(m,error=false)=>{text('archive-message',m);const n=$('archive-message');if(n)n.dataset.error=error?'true':'false'};
 function row(item,active){
   const tr=document.createElement('tr');
   const cell=(value)=>{const td=document.createElement('td');td.textContent=String(value??'—');tr.append(td);return td};
   cell((item.track||'Pista')+' · '+(item.sessionType||'—'));
   const date=item.finishedAt||item.startedAt;
   cell(date?new Date(date).toLocaleString('es-CO'):'—');
   cell(item.complete?'FINALIZADA':active?'ACTIVA':'PENDIENTE · RECUPERACIÓN');
   cell(size(item.sizeBytes));
   const action=document.createElement('td');action.className='archive-actions';
   const btn=(label,handler)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.addEventListener('click',handler);action.append(b)};
   btn('EXPORTAR',()=>{
     const anchor=document.createElement('a');
     anchor.href='/api/session-archive/export?sessionId='+encodeURIComponent(item.sessionId);
     anchor.download='ZRE_SESSION_'+item.sessionId+'.zip';
     document.body.append(anchor);anchor.click();anchor.remove();
     message('Exportación solicitada; ZIP también conservado en reports.');
   });
   btn(item.protected?'DESPROTEGER':'PROTEGER',async()=>{
     try{await request('/api/session-archive/protect',{sessionId:item.sessionId,protected:!item.protected});await refresh(true)}
     catch(e){message('No se pudo actualizar la protección: '+e.message,true)}
   });
   tr.append(action);return tr;
 }
 async function refresh(force=false){
   if(busy||!$('archive-sessions'))return;
   if(!force&&Date.now()-lastAt<15000)return;
   busy=true;
   try{
     const state=await request('/api/session-archive');
     lastAt=Date.now();
     text('archive-size',size(state.sizeBytes));text('archive-oldest',state.oldestAt?new Date(state.oldestAt).toLocaleDateString('es-CO'):'—');
     text('archive-count',(state.sessions||[]).length+' sesiones');
     const days=$('archive-retention-days');
     if(days&&document.activeElement!==days)days.value=state.retentionDays||7;
     const host=$('archive-sessions');host.replaceChildren(...(state.sessions||[]).map(x=>row(x,x.sessionId===state.activeSessionId)));
     if(!(state.sessions||[]).length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=5;td.textContent='Todavía no hay registros temporales.';tr.append(td);host.append(tr)}
     text('archive-warnings',Number(state.droppedEvents||0)||Number(state.loggingErrors||0)?'ADVERTENCIA · eventos descartados: '+(state.droppedEvents||0)+' · errores de escritura: '+(state.loggingErrors||0):'REGISTRO ACTIVO · SIN ERRORES REPORTADOS');
   }catch(e){message('No se pudieron leer los registros: '+e.message,true)}
   finally{busy=false}
 }
 $('archive-refresh')?.addEventListener('click',()=>refresh(true));
 $('archive-retention-save')?.addEventListener('click',async()=>{
   try{
     const days=Number($('archive-retention-days').value);
     if(!Number.isInteger(days)||days<1||days>365){message('La retención debe ser entre 1 y 365 días.',true);return}
     await request('/api/session-archive/settings',{days});
     message('Retención guardada: '+days+' días.');await refresh(true);
   }catch(e){message('No se pudo guardar retención: '+e.message,true)}
 });
 $('archive-clean')?.addEventListener('click',async()=>{
   if(!window.confirm('¿Eliminar todos los registros temporales FINALIZADOS y NO PROTEGIDOS? No se pueden recuperar. Las sesiones activas, pendientes, setups y reportes quedan intactos.'))return;
   try{const result=await request('/api/session-archive/cleanup',{confirm:'DELETE_FINISHED_TEMPORARY'});
     message('Limpieza completada: '+(result.removed||[]).length+' sesiones · '+size(result.freedBytes)+' liberados.');await refresh(true);
   }catch(e){message('Falló la limpieza: '+e.message,true)}
 });
 const observer=new MutationObserver(()=>{
   if($('admin-view')&&!$('admin-view').hidden)refresh();
 });
 if($('admin-view'))observer.observe($('admin-view'),{attributes:true,attributeFilter:['hidden']});
 window.ZRESessionArchive={refresh};
})();
