"""ZRE 2.6.7 browser acceptance (fixture telemetry, NOT Windows/iRacing live).
Tests runtime routing, Practice race preview, Quali and compact Carrera/admin.
"""
import sys
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from diagnostics.practice_visual_266 import fixture as practice
from diagnostics.quali_visual_266 import fixture as quali
from diagnostics.race_v2_visual_266 import fixture as race
from server.iracing_bridge import DashboardSource

OUT=ROOT/"diagnostics"/"functionality-267-screenshots"
OUT.mkdir(exist_ok=True,parents=True)
with socket.socket() as sock:
    sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]

with tempfile.TemporaryFile(mode="w+") as log:
 proc=subprocess.Popen([sys.executable,"-c","from server import iracing_bridge as b;b.start_background_updater=None;b.main()",
                        "--demo","--port",str(port)],cwd=ROOT,stdout=log,stderr=log)
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
   page=browser.new_page(viewport={"width":1366,"height":768})
   errors=[];page.on("pageerror",lambda e:errors.append(str(e)))
   page.add_init_script("""window.__messages=[];window.WebSocket=class{
    static OPEN=1;static CONNECTING=0;
    constructor(){this.readyState=1;window.__ws=this;setTimeout(()=>this.onopen?.(),0)}
    send(v){window.__messages.push(JSON.parse(v))}
    close(){this.readyState=3}
   }""")
   for i in range(50):
    try:page.goto(f"http://127.0.0.1:{port}/",wait_until="domcontentloaded");break
    except Exception:time.sleep(.1)
   page.wait_for_function("Boolean(window.__ws?.onmessage)")
   base=DashboardSource(force_demo=True).demo_payload()
   def packet(fragment,mode,identity,qualification=None):
    data={**base,**fragment,"connected":True,"demo":True,"sessionType":mode,
      "sessionMode":{"Practice":"practice","Qualify":"qualifying","Race":"race_engineer"}[mode]}
    data["self"]={**base["self"],**fragment.get("self",{}),"pit":"EN PISTA"}
    data["header"]={**base["header"],"lap":"VUELTA 17","track":"QA · FICTICIA","state":"QA SIMULADO"}
    data["teamContext"]={**base.get("teamContext",{}),"autoMode":"driver"}
    data["practiceAnalytics"]=fragment.get("practiceAnalytics") or practice(8)["practiceAnalytics"]
    data["qualifying"]={"qualifyingMode":None,"officialSessionType":mode,
      "officialSessionIdentity":identity,"inGarage":False,**(qualification or {})}
    return data
   def feed(data):page.evaluate("d=>window.__ws.onmessage({data:JSON.stringify(d)})",data)
   pr=packet(practice(12),"Practice","P-101")
   feed(pr)
   assert page.locator("#practice-workspace").is_visible()
   page.locator("#screen-mode-select").select_option("quali")
   assert not page.evaluate("window.__messages.some(m=>m.action==='quali_mode'&&m.value==='simulate')")
   page.locator("#quali-mode-select").select_option("simulate")
   assert page.evaluate("window.__messages.some(m=>m.action==='quali_mode'&&m.value==='simulate')")
   q=quali(12)
   sim=packet(q,"Practice","P-101",{**q["qualifying"],"officialSessionIdentity":"P-101"})
   feed(sim)
   assert page.locator("#quali-view").is_visible()
   assert page.locator("#q-kind").inner_text()=="SIMULADA"
   assert page.locator("#q-delta").inner_text()!=""
   page.locator("#screen-mode-select").select_option("practice")
   assert page.locator("#practice-workspace").is_visible()
   page.locator("#screen-mode-select").select_option("quali")
   assert page.locator("#quali-view").is_visible()
   assert sum(m["value"]=="simulate" for m in page.evaluate("window.__messages.filter(m=>m.action==='quali_mode')"))==1
   # Preview Carrera during real Practice: no official race plan.
   test_race=race(18)
   sim["raceDashboard"]={**test_race["raceDashboard"],"practicePreview":True}
   sim["racePlanVNext"]=test_race["racePlanVNext"]
   feed(sim)
   page.locator("#screen-mode-select").select_option("race")
   assert page.locator("#race-v2-view").is_visible()
   assert "PRÁCTICA" in page.locator("#rv2-plan-status").inner_text()
   assert page.locator("#rv2-alert").inner_text()=="ENSAYO"
   page.locator("#screen-mode-select").select_option("quali")
   assert page.locator("#q-kind").inner_text()=="SIMULADA"

   official=quali(20,True)
   qa=packet(official,"Qualify","Q-102",{**official["qualifying"],"officialSessionIdentity":"Q-102"})
   feed(qa)
   assert page.locator("#screen-mode-select").input_value()=="quali"  # user visual choice persists
   assert page.locator("#q-kind").inner_text()=="OFICIAL"
   assert page.locator("#q-best").inner_text()!="—"
   assert page.locator("#q-last").inner_text()!="—"
   # No braking/setup technique advice exposed in Quali time-only Coach.
   assert "Retrasa 5 metros" not in page.locator("#q-priorities").inner_text()
   assert page.locator("#q-delta").inner_text()!=""
   page.locator("#screen-mode-select").select_option("auto")
   rc=packet(test_race,"Race","R-103")
   feed(rc)
   assert page.locator("#race-v2-view").is_visible()
   assert page.locator("#rv2-lap").inner_text()=="17"
   assert page.locator("#rv2-fuel").inner_text()!="—"
   assert page.locator("#rv2-position").inner_text().startswith("P")
   assert page.locator("#rv2-standing-rows .rv2-standing-row").count()<=6
   assert page.locator('#rv2-standing-rows [data-player="true"]').count()==1
   page.locator("#rv2-visible-count").select_option("3")
   assert page.locator("#rv2-standing-rows .rv2-standing-row").count()<=8
   page.locator("#rv2-font-select").select_option("large")
   assert page.locator("body").get_attribute("data-race-font")=="large"
   page.locator("#rv2-standing-scope").select_option("all")
   assert page.locator("#rv2-standing-rows .rv2-standing-row").count()==18
   page.locator("#rv2-standing-scope").select_option("near")
   page.locator("#rv2-visible-count").select_option("2")
   for width,height in [(1366,768),(1920,1080),(2560,1440)]:
    page.set_viewport_size({"width":width,"height":height})
    page.wait_for_timeout(130)
    dims=page.evaluate("""() => ({scrollWidth:document.documentElement.scrollWidth,
      viewport:innerWidth,scrollHeight:document.documentElement.scrollHeight,
      height:innerHeight,rows:document.querySelectorAll('#rv2-standing-rows .rv2-standing-row').length})""")
    assert dims["scrollWidth"]<=dims["viewport"]+3,dims
    assert dims["scrollHeight"]<=dims["height"]+3,dims
    page.screenshot(path=str(OUT/f"race-{width}.png"))
   # History management remains accessible without restoring the archived builder.
   assert page.locator("#archive-open").is_visible()
   page.locator("#archive-open").click()
   assert page.locator("#zre-archive-dialog").is_visible()
   page.locator("#archive-refresh").click()
   page.wait_for_function("document.getElementById('archive-retention-days').value!==''")
   archive=page.evaluate("""async()=>await(await fetch('/api/session-archive')).json()""")
   assert archive["retentionDays"]>=1
   assert "sizeBytes" in archive and "sessions" in archive
   page.screenshot(path=str(OUT/"session-archive.png"))
   page.locator("#zre-archive-dialog .zre-archive-dialog-head button").click()
   assert not page.locator("#zre-archive-dialog").is_visible()
   assert page.evaluate("getComputedStyle(document.body).backgroundColor")=="rgb(0, 0, 0)"
   assert not errors,errors
   browser.close()
   print("PASS 2.6.7.1: unrestricted screen selection + explicit Quali action + Carrera,")
   print("  full Race → compact self/rival → all → zoom/resolution 1366/1920/2560 and storage API.")
 finally:
  proc.terminate();proc.wait(timeout=5)
