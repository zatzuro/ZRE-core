const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');

const admin=fs.readFileSync('web/screen_admin.js','utf8');
const app=fs.readFileSync('web/app.js','utf8');
const html=fs.readFileSync('web/index.html','utf8');
const css=fs.readFileSync('web/screen_admin.css','utf8');

new vm.Script(admin,{filename:'web/screen_admin.js'});
new vm.Script(app,{filename:'web/app.js'});

for(const id of ['admin-view','custom-view','admin-screen-select','admin-component-list','admin-component-catalog','custom-screen-grid','screen-nav']){
  assert.ok(new RegExp(`id=[\\"']${id}[\\"']`).test(html),`missing #${id}`);
}
for(const label of ['Relative / clasificación','Class Standings','Race Plan','Session Intelligence','Historial de paradas','Driver Coach']){
  assert.ok(admin.includes(label),`catalog missing ${label}`);
}
assert.ok(admin.includes("localStorage.setItem(STORAGE_KEY"),'screen preferences are not persisted');
assert.ok(admin.includes("row.draggable=true"),'drag and drop ordering missing');
assert.ok(admin.includes("RESTORE")||admin.includes("restoreMoved"),'component restoration missing');
assert.ok(admin.includes("zre-size-full"),'resizing support missing');
assert.ok(app.includes("window.ZREScreenAdmin?.isCustom(driverViewPreference)"),'custom screens not integrated into desiredView');
assert.ok(app.includes("window.ZREScreenAdmin?.renderCustom(view)"),'custom screen renderer not integrated');
assert.ok(app.includes("window.ZREScreenAdmin?.applyBuiltIn(view)"),'built-in personalization not applied');
assert.ok(css.includes('.zre-layout-hidden'), 'visibility customization CSS missing');
assert.ok(css.includes('#custom-screen-grid'), 'custom screen grid CSS missing');

console.log('2.6.5 screen administration builder structure and integration: OK');
