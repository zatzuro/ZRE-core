/* Carrera V2 frontend contract: no builder and 4 independent logical roles. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('web/index.html','utf8'),app=fs.readFileSync('web/app.js','utf8');
const race=fs.readFileSync('web/race_v2.js','utf8'),css=fs.readFileSync('web/race_v2.css','utf8');
new vm.Script(app,{filename:'web/app.js'});
new vm.Script(race,{filename:'web/race_v2.js'});
for(const id of ['race-v2-view','rv2-position','rv2-gap-ahead','rv2-car-ahead',
 'rv2-gap-behind','rv2-car-behind','rv2-last-lap','rv2-my-pace','rv2-fuel',
 'rv2-consumption','rv2-remaining','rv2-standing-rows','rv2-standing-all',
 'rv2-standing-scope','rv2-standings-expand','rv2-standings-dialog',
 'rv2-rival-auto','rv2-rival-search','rv2-rival-select','rv2-rival-name',
 'rv2-rival-pos','rv2-rival-presence','rv2-rival-best','rv2-rival-last',
 'rv2-rival-pace','rv2-rival-gap','rv2-pace-legend','rv2-pace-chart',
 'rv2-pace-series','rv2-box-lap','rv2-box-countdown','rv2-earliest',
 'rv2-target','rv2-fuel-limit','rv2-add-fuel','rv2-stops-left',
 'rv2-tyres','rv2-next-driver','rv2-plan-expand','rv2-fuel-observed',
 'rv2-fuel-target','rv2-fuel-deviation','rv2-fuel-autonomy']){
 assert.ok(html.includes('id="'+id+'"'),'missing raceV2 #'+id);
}
assert.ok(html.includes('<script src="/static/race_v2.js'),'missing race renderer import');
assert.ok(html.includes('<link rel="stylesheet" href="/static/race_v2.css'),'missing race CSS import');
assert.ok(app.includes("return'race-v2'"),'Race session does not route to Race V2');
assert.ok(app.includes("view==='race-v2'"),'new race view does not render');
assert.ok(app.includes('window.ZRERaceV2?.render(data)'),'race model not bound');
assert.ok(app.includes('window.ZRERaceV2?.init('),'race controls not bound');
assert.ok(race.includes("['YOU','AHEAD','BEHIND','RIVAL']"),'four logical roles absent');
assert.ok(race.includes("const one=new Map")||race.includes("one=new Map"),'physical-series dedupe absent');
assert.ok(race.includes("entry.roles?.[0]"),'series must be one per physical CarIdx');
assert.ok(race.includes("lapNumber"),'actual source lap number must be shown in tooltip');
assert.ok(race.includes("!point.comparable"),'noncomparable laps must not join plot lines');
assert.ok(race.includes("roleIds")||race.includes("race.roles"),'backend-provided roles not bound');
assert.ok(css.includes('grid-template-columns:minmax(0,48fr) minmax(0,30fr) minmax(0,22fr)'),'main proportions absent');
assert.ok(css.includes('grid-template-columns:minmax(0,70fr) minmax(0,30fr)'),'bottom proportions absent');
assert.ok(css.includes("body.race-v2-session"),'scoped race palette absent');
assert.ok(!html.includes('data-zre-view="admin"'),'archived editor must remain archived');
console.log('Race V2 horizontal UI, official class, four-role chart, manual rival, Race Plan, builder archive: OK');
