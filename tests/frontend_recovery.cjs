const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('web/app.js', 'utf8');
const fragment = source.slice(source.indexOf('let webBuildReloading=false'));
const store = new Map();
let installed = '2.3.3', pageBuild = '2.3.1', reloads = 0, connections = 0;
const timers = [];
function makeContext() {
  const ctx = {
    socket: null, audioSelect: null, strategyConfig: {}, sendSetting() {}, render() {},
    WebSocket: class {
      static CONNECTING = 0; static OPEN = 1;
      constructor() { connections++; this.readyState = 0; }
    },
    fetch: async () => ({ok: true, json: async () => ({installedVersion: installed})}),
    document: {querySelector: () => ({content: pageBuild})},
    sessionStorage: {
      getItem: key => store.get(key) || null,
      setItem: (key, value) => store.set(key, value),
      removeItem: key => store.delete(key)
    },
    location: {host: '127.0.0.1:8765', replace: () => reloads++},
    setInterval() {}, setTimeout: fn => {timers.push(fn);return timers.length;},
    Date, encodeURIComponent
  };
  vm.createContext(ctx);
  vm.runInContext(fragment, ctx);
  return ctx;
}

(async () => {
  let ctx = makeContext();
  await ctx.checkInstalledWebBuild();
  await ctx.checkInstalledWebBuild();
  assert.equal(reloads, 1, 'one reload attempt per installed version');
  ctx = makeContext(); // A new page after an attempted reload, but its HTML is still old.
  await ctx.checkInstalledWebBuild();
  assert.equal(reloads, 1, 'stale HTML must not cause a reload loop');
  pageBuild = installed;
  await ctx.checkInstalledWebBuild();
  assert.equal(store.has('zre-reload-attempt'), false);
  assert.equal(connections, 2);
  ctx.connect();
  assert.equal(connections, 2, 'only one socket while connecting');
  const first = ctx.socket;
  first.onclose();
  first.onclose();
  assert.equal(timers.length, 1, 'only one reconnect timer');
  timers.shift()();
  assert.equal(connections, 3, 'reconnect after closing');

  const timing = source.slice(source.indexOf('function rowsSignature('), source.indexOf('function paceRows('));
  const node = () => ({children: [], append(...children) {this.children.push(...children);}, setAttribute() {}});
  const host = {replaceChildren(...children) {this.children = children;}};
  const view = {renderCache: new Map(), document: {createElement: node}, $: () => host};
  vm.createContext(view);
  vm.runInContext(timing, view);
  for (const playerPosition of [0, 3, 6]) {
    view.renderCache.clear();
    const rows = Array.from({length: 7}, (_, i) => ({idx: i, pos: i + 1, isPlayer: i === playerPosition}));
    view.timingRows('timing-rows', rows);
    assert.equal(host.children.length, 7);
    assert.match(host.children[3].className, /player/, 'driver stays on row four');
  }
  console.log('Frontend reload and socket lifecycle: OK');
})().catch(err => {console.error(err);process.exitCode = 1;});
