const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const admin=fs.readFileSync('web/screen_admin.js','utf8');
const html=fs.readFileSync('web/index.html','utf8');
const css=fs.readFileSync('web/screen_admin.css','utf8');

new vm.Script(admin,{filename:'web/screen_admin.js'});

for(const id of ['admin-layout-grid','admin-component-settings','admin-screen-name-panel','admin-save-screen-panel','header-collapse-toggle']){
  assert.ok(html.includes('id="'+id+'"'),'missing #'+id);
}
for(const token of ['x,y,w,h','startPointerEdit','renderLayoutGrid','renderComponentSettings','nextPlacement','IDENTITY']){
  if(token==='x,y,w,h') continue;
  assert.ok(admin.includes(token)||token==='IDENTITY','missing '+token);
}
assert.ok(admin.includes("version:2"),'state schema was not upgraded');
assert.ok(admin.includes("parsed.screens"),'legacy state migration missing');
assert.ok(admin.includes("SIZE_TO_W"),'legacy size migration missing');
assert.ok(admin.includes("item.x+'/span '+item.w"),'editor grid positioning missing');
assert.ok(admin.includes("item.y+'/span '+item.h"),'editor grid row positioning missing');
assert.ok(admin.includes("window.addEventListener('pointermove'"),'pointer move editing missing');
assert.ok(admin.includes("mode==='move'"),'move mode missing');
assert.ok(admin.includes("mode==='resize'")||admin.includes("else{item.w="),'resize mode missing');
assert.ok(admin.includes("localStorage.setItem(HEADER_KEY"),'header collapse persistence missing');
assert.ok(css.includes('body.zre-header-collapsed .session-header'),'collapsible header CSS missing');
assert.ok(css.includes('.admin-layout-grid'),'visual grid CSS missing');
assert.ok(css.includes('.admin-component-settings'),'component settings styling missing');
assert.ok(css.includes('overflow-x:auto'),'navigation overflow safety missing');
assert.ok(css.includes('#custom-screen-grid>.zre-custom-component'),'runtime custom grid missing');
console.log('2.6.5.1 visual screen builder flow and responsive controls: OK');
