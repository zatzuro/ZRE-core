'use strict';
/** Render real SVG points through the published Practice renderer, no static mocks. */
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
function node(tag='div'){
 const n={tag,id:'',dataset:{},attributes:{},textContent:'',style:{setProperty(){}},
   classList:{toggle(){return false},contains(){return false},add(){},remove(){}},
   children:[],append(...a){this.children.push(...a)},
   replaceChildren(...a){this.children=a},
   setAttribute(k,v){this.attributes[k]=String(v)},
   insertBefore(child,_before){this.children.push(child)},
   addEventListener(k,callback){this.callbacks=this.callbacks||{};this.callbacks[k]=callback}};
 return n;
}
const ids=['pr-pace-svg','pr-pace-line','pr-pace-dots','pr-pace-status',
 'pr-pace-count','pr-pace-scale','pr-pace-fuel','header-collapse-toggle'];
const items=Object.fromEntries(ids.map(id=>[id,node()]));
items['pr-pace-scale'].value='focus';
const context={document:{body:node(),
    getElementById:id=>items[id]||(items[id]=node()),
    querySelectorAll:()=>[],
    createElement:tag=>node(tag),
    createElementNS:(ns,tag)=>node(tag)},
 localStorage:{getItem:()=>null,setItem(){}},
 window:{},console};
vm.createContext(context);
vm.runInContext(fs.readFileSync('web/practice.js','utf8'),context);
function show(rows){
 context.window.ZREPractice.render({practiceAnalytics:{laps:rows},self:{},coach:{}});
 const svg=items['pr-pace-svg'];
 return {count:Number(svg.dataset.laps),comparable:Number(svg.dataset.comparable),
   min:Number(svg.dataset.yMin),max:Number(svg.dataset.yMax),mean:Number(svg.dataset.averageSeconds),
   points:items['pr-pace-dots'].children};
}
function lap(n,seconds,comparable=true){return{lap:n,seconds,valid:comparable,
  comparable,caution:false,onPitRoad:false};}
for(const count of [3,10,32,70]){
 const rows=Array.from({length:count},(_,i)=>lap(i+1,85.2+(i%3-1)*.2));
 const result=show(rows);
 assert.equal(result.count,count);
 assert.equal(result.points.length,count);
 assert.equal(result.comparable,count);
 assert.ok(Math.abs(result.max-result.mean-1)<.002);
 assert.ok(Math.abs(result.mean-result.min-1)<.002);
}
const rows=Array.from({length:32},(_,i)=>lap(i+1,85.2));
rows[5]=lap(6,91.9,false);rows[17]=lap(18,83.0,false);
const result=show(rows);
assert.equal(result.count,32);assert.equal(result.comparable,30);
assert.equal(result.points.filter(x=>x.tag==='path').length,2);
assert.equal(result.points.filter(x=>x.tag==='circle').length,30);
assert.equal(result.mean,85.2);assert.equal(result.min,84.2);assert.equal(result.max,86.2);
items['pr-pace-scale'].callbacks.change({target:{value:'all'}});
assert.ok(Number(items['pr-pace-svg'].dataset.yMax)>=91.9);
assert.ok(Number(items['pr-pace-svg'].dataset.yMin)<=83.0);
assert.equal(items['pr-pace-dots'].children.length,32);
console.log('Practice 3/10/32/70 actual lap SVG, valid-only mean ±1s, outliers and full scale: PASS');
