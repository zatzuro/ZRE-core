"""Senior integration: full app message router, simulated SDK packets only."""
import sys, socket, subprocess, tempfile, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from diagnostics.practice_visual_266 import fixture as practice
from diagnostics.quali_visual_266 import fixture as quali
from diagnostics.race_v2_visual_266 import fixture as race
from server.iracing_bridge import DashboardSource
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'diagnostics'/'senior-266-screenshots';OUT.mkdir(exist_ok=True)
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
with tempfile.TemporaryFile(mode='w+') as log:
 proc=subprocess.Popen([sys.executable,'-c','from server import iracing_bridge as b;b.start_background_updater=None;b.main()','--demo','--port',str(port)],cwd=ROOT,stdout=log,stderr=log)
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
   page=browser.new_page(viewport={'width':1366,'height':768})
   errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.add_init_script("""window.__sent=[];window.WebSocket=class{static OPEN=1;static CONNECTING=0;constructor(){this.readyState=1;window.__ws=this;setTimeout(()=>this.onopen?.(),0)}send(x){window.__sent.push(JSON.parse(x))}close(){this.readyState=3}}""")
   for i in range(50):
    try:page.goto(f'http://127.0.0.1:{port}/');break
    except Exception:time.sleep(.1)
   page.wait_for_function('Boolean(window.__ws?.onmessage)')
   base=DashboardSource(force_demo=True).demo_payload()
   def packet(extra,kind):
    d={**base,**extra,'sessionType':kind,'connected':True,'demo':True,'sessionMode':{'Race':'race_engineer','Practice':'practice','Qualify':'qualifying'}[kind]}
    d['self']={**base['self'],**extra.get('self',{}),'pit':'EN PISTA'}
    d['header']={**base['header'],'state':'QA SIMULADO','track':'QA fixtures — NO SDK real'}
    d['teamContext']={**base.get('teamContext',{}),'autoMode':'driver'}
    return d
   def feed(d):page.evaluate('d=>window.__ws.onmessage({data:JSON.stringify(d)})',d)
   for width,height in [(1366,768),(1920,1080),(2560,1440)]:
    page.set_viewport_size({'width':width,'height':height})
    d=packet(practice(20),'Practice');d['qualifying']={};feed(d)
    assert page.locator('#practice-workspace').is_visible()
    page.locator('.pr-corner').first.click();assert page.locator('#pr-corner-dialog').evaluate('n=>n.open');page.keyboard.press('Escape')
    d=packet(quali(14),'Practice');feed(d)
    assert page.locator('#quali-view').is_visible()
    assert page.locator('#quali-mode-control').is_visible()
    page.locator('#quali-mode-select').select_option('training')
    assert page.evaluate("window.__sent.some(x=>x.action==='quali_mode'&&x.value==='training')")
    d['qualifying']['inGarage']=True;feed(d);assert page.locator('#q-garage').is_visible()
    d=packet(quali(14,True),'Qualify');feed(d)
    assert page.locator('#quali-mode-control').is_hidden()
    d=packet(race(),'Race');d['qualifying']={};feed(d)
    assert page.locator('#race-v2-view').is_visible()
    page.locator('#role-select').select_option('spotter');assert page.locator('#spotter-view').is_visible()
    page.locator('#role-select').select_option('auto');assert page.locator('#race-v2-view').is_visible()
    for zoom in ['1','1.1']:
     page.set_viewport_size({'width':int(width/float(zoom)),'height':int(height/float(zoom))})
     page.wait_for_timeout(120)
     assert page.evaluate('document.documentElement.scrollHeight<=innerHeight+3')
     assert page.locator('.rv2-fuel-context').evaluate("n=>n.getBoundingClientRect().top>=document.getElementById('rv2-fuel-deviation').getBoundingClientRect().bottom")
     page.screenshot(path=str(OUT/f'race-{width}-{zoom}.png'))
    page.set_viewport_size({'width':width,'height':height})
   assert not errors,errors
   browser.close()
   print('PASS full-app: Practice → simulated/official Quali → Garage → Race → SPOTTER → AUTO; 3 resolutions, 100/110% scale, no JS errors')
 finally:
  proc.terminate();proc.wait(timeout=5)
