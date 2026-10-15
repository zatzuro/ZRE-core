'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict');
const js=fs.readFileSync('web/race_v2.js','utf8');
const app=fs.readFileSync('web/app.js','utf8');
const qual=fs.readFileSync('web/quali.js','utf8');
const html=fs.readFileSync('web/index.html','utf8');
const admin=fs.readFileSync('web/session_archive.js','utf8');
new Function(js);new Function(app);new Function(qual);new Function(admin);
for(const id of ['rv2-alert','rv2-autonomy','rv2-lap','rv2-visible-count','rv2-font-select',
                  'rv2-standing-rows','rv2-standing-all','archive-sessions','archive-size',
                  'archive-retention-days','archive-clean','archive-message']){
  assert(html.includes('id="'+id+'"'),'Missing '+id);
}
assert(js.includes('visibleCount=2'),'Compact standings should default to self ±2');
assert(js.includes('center.push(strategic)'),'Always include manually selected rival');
assert(js.includes('race.practicePreview'),'Practice race preview source');
assert(js.includes('data.practiceRacePlan||{}'),'Practice preview must read simulated Race Plan separately from official');
assert(!js.includes('preview?{}:data.racePlanVNext'),'Do not discard valid trial plan');
assert(js.includes('rv2-font-select')&&js.includes('zre-race-font'),'Persist readable font');
assert(js.includes('rv2-visible-count')&&js.includes('zre-race-visible'),'Persist visible cars');
assert(js.includes('physicalGapSeconds'),'Never infer rival seconds from classification');
assert(qual.includes('timingLoss'),'Quali Coach performance timing only');
assert(qual.includes('LEGAlIDAD')===false);
assert(admin.includes('DELETE_FINISHED_TEMPORARY'),'Explicit deletion required');
assert(admin.includes('/api/session-archive/protect'),'manual protection required');
assert(app.includes("screenChoice==='race'"),'Race manual view remains');
console.log('2.6.7 storage / Quali / race functional frontend contracts: OK');
