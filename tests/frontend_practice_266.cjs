const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('web/index.html','utf8');
const css=fs.readFileSync('web/practice.css','utf8');
const js=fs.readFileSync('web/practice.js','utf8');
const app=fs.readFileSync('web/app.js','utf8');
const builder=fs.readFileSync('web/screen_admin.js','utf8');
new vm.Script(js,{filename:'web/practice.js'});new vm.Script(app,{filename:'web/app.js'});
for(const id of ['practice-workspace','pr-best','pr-last','pr-optimal','pr-delta',
 'pr-average','pr-consistency','pr-track-map','pr-corners','pr-fuel','pr-fuel-avg',
 'pr-fuel-last','pr-fuel-min','pr-fuel-max','pr-fuel-range','pr-pace-svg',
 'pr-corner-dialog','header-collapse-toggle']){
 assert.ok(html.includes('id="'+id+'"'),'missing practice component '+id);
}
assert.ok(!html.includes('<script src="/static/screen_admin.js'),'archived builder must not load');
assert.ok(!html.includes('data-zre-view="admin"'),'builder must not appear in navigation');
assert.ok(builder.includes("STORAGE_KEY"),'archived source must remain available for restoration');
assert.ok(!app.includes('localStorage.clear()'),'legacy layouts must not be deleted');
assert.ok(js.includes("columns=count>=19?4:count>=11?3:count>=5?2:1"),'8/14/20 zones density must vary');
assert.ok(js.includes("selectCorner(curve.id,true)"),'map and Coach selection contract missing');
assert.ok(js.includes("renderPace(analytics.laps)"),'valid-lap series not connected');
assert.ok(app.includes("window.ZREPractice?.render(data)"),'practice renderer must receive live payload');
assert.ok(css.includes("body.practice-session .live-view"),'practice layout not isolated');
console.log('Practice archived builder, 16:9 layout, Coach, fuel and pace structure: OK');
