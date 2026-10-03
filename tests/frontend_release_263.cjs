const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const code=fs.readFileSync('web/app.js','utf8');
const fragment=code.slice(code.indexOf('function paceRows('),code.indexOf('\n',code.indexOf('function paceRows(')));
const target={replaceChildren(...children){this.children=children;}};
const context={$:()=>target,renderCache:new Map(),rowsSignature:JSON.stringify,document:{createElement:()=>({append(...cells){this.cells=[...(this.cells||[]),...cells];}})}};
vm.createContext(context);vm.runInContext(fragment,context);
const rows=[{lap:1,time:'1:30.000'},{lap:2,time:'1:31.000'}];
for(const view of ['pace-rows','pit-pace-rows','summary-pace-rows']){
    context.paceRows(view,rows);
    assert.equal(target.children[0].cells[0].textContent,2);
    assert.equal(target.children[1].cells[0].textContent,1);
}
assert.equal(rows[0].lap,1,'rendering must not mutate history');
console.log('2.6.3 latest lap in PISTA/PIT/RESUMEN: OK');
