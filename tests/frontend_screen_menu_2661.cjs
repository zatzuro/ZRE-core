'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const html=fs.readFileSync('web/index.html','utf8');
const css=fs.readFileSync('web/black_theme.css','utf8');
const archive=fs.readFileSync('web/session_archive.js','utf8');
new Function(app);new Function(archive);
for(const s of ['id="screen-mode-control"','id="screen-mode-select"','id="screen-mode-context"',
  'value="auto"','value="practice"','value="quali"','value="race"',
  'value="pit"','value="summary"','value="spotter"','id="archive-open"'])
 assert(html.includes(s),'Missing screen option/control '+s);
for(const s of ['sessionScreenAvailability','reconcileScreenChoice','syncScreenMenu','screenChoice',
  "screenChoice==='practice'?'practice':null","if(screenChoice==='pit')return'pit'",
  "if(screenChoice==='summary')return'summary'","if(screenChoice==='spotter')return'spotter'",
  "zre-screen-choice-v2","option.disabled=false"])
 assert(app.includes(s),'Navigation contract '+s);
assert(!app.includes("if(screenChoice!=='auto'&&!allowed[screenChoice])screenChoice='auto'"),
  'Manual visual selection must not be reset based on telemetry availability');
assert(!app.includes("if(next!=='auto'&&!allowed[next])"),
  'All screens must remain accessible even when SDK data is unavailable');
const nav=app.slice(app.indexOf("$('screen-mode-select')?.addEventListener"),app.indexOf("$('driver-view-select').addEventListener"));
assert(!nav.includes('quali_mode'),'Visiting Quali is read-only; simulation requires an explicit separate action');
assert(app.includes("action:'quali_mode',value:event.target.value"),
  'Explicit qualifying action must be retained');
assert(app.includes("screenChoice==='race'"),'Manual Carrera remains available');
assert(archive.includes('zre-archive-dialog')&&archive.includes('archivePanel'),
  'Archive must remain accessible outside the archived screen builder');
assert(html.includes('black_theme.css')&&css.includes('--bg:#000')&&css.includes('background:#000!important'),
  'Global true-black theme must load last');
console.log('ZRE 2.6.7.1 free-navigation, non-invasive actions, archive, black theme: contracts OK');
