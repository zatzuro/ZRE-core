"""Chromium QA: single comparison table + KPI + fuel edit, no live iRacing required."""
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from server.iracing_bridge import DashboardSource

OUT = ROOT / "diagnostics" / "lap-history-2673-screenshots"
OUT.mkdir(parents=True, exist_ok=True)

def fixture():
    demo = DashboardSource(force_demo=True).demo_payload()
    team = [
        {"lap":40,"car_number":"18","driver":"Santiago","lap_time":92.4,
         "remaining":30.0,"avgConsumption":2.5,"kind":"Normal","state":"REAL",
         "source":"SDK_OBSERVED","fuelSource":"MANUAL"},
        {"lap":41,"car_number":"18","driver":"David","lap_time":92.1,
         "remaining":27.5,"avgConsumption":2.5,"kind":"Normal","state":"REAL",
         "source":"SDK_OBSERVED","fuelSource":"ESTIMADO"},
    ]
    projected = [
        {"lap":42,"car_number":"18","driver":None,"lap_time":92.0,
         "remaining":25.0,"avgConsumption":2.5,"kind":"Entrada box",
         "state":"PROYECTADO","source":"ZRE_PROJECTION","fuelSource":"ESTIMADO"},
        {"lap":43,"car_number":"18","driver":None,"lap_time":94.0,
         "remaining":None,"avgConsumption":2.5,"kind":"Salida box",
         "state":"PROYECTADO","source":"ZRE_PROJECTION","fuelSource":"SIN_DATO"},
    ]
    rivals = [
        {"lap":40,"car_number":"27","driver":"Rival A","lap_time":92.7,"kind":"Normal"},
        {"lap":41,"car_number":"27","driver":"Rival A","lap_time":91.9,"kind":"Normal"},
    ]
    demo.update(connected=True, demo=True)
    demo["teamContext"]={**demo.get("teamContext", {}),"autoMode":"driver"}
    demo["raceDirector"]={"effectiveCarIdx":1,"selectedIdx":1,
                           "candidates":[{"idx":1,"label":"#27 · Rival A","position":"P5"}]}
    demo["lapDatabase"]={
        "available":True,"race":"QA-SYNTHETIC-1","teamCarIdx":0,"rivalCarIdx":1,
        "team":team,"rival":rivals,"projected":projected,"averages":{"Normal":2.5}
    }
    return demo

with socket.socket() as sock:
    sock.bind(("127.0.0.1",0))
    port=sock.getsockname()[1]

with tempfile.TemporaryFile(mode="w+") as log:
    proc=subprocess.Popen(
        [sys.executable,"-c",
         "from server import iracing_bridge as b; b.start_background_updater=None; b.main()",
         "--demo","--port",str(port)],cwd=ROOT,stdout=log,stderr=log)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
            page=browser.new_page(viewport={"width":1366,"height":768})
            errors=[]
            page.on("pageerror",lambda err:errors.append(str(err)))
            page.add_init_script("""window.__sent=[];
                window.WebSocket=class{
                  static OPEN=1;static CONNECTING=0;
                  constructor(){this.readyState=1;window.__ws=this;
                    setTimeout(()=>this.onopen?.(),0)}
                  send(message){window.__sent.push(JSON.parse(message))}
                  close(){this.readyState=3}
                }""")
            for _ in range(50):
                try:
                    page.goto(f"http://127.0.0.1:{port}/",wait_until="domcontentloaded")
                    break
                except Exception:
                    time.sleep(.1)
            page.wait_for_function("Boolean(window.__ws?.onmessage)")
            packet=fixture()
            page.evaluate("payload=>window.__ws.onmessage({data:JSON.stringify(payload)})",packet)
            page.locator("#screen-mode-select").select_option("lap-history")
            assert page.locator("#lap-history-view").is_visible()
            assert page.locator("#lh-rows tr").count()==4
            assert page.locator('#lh-rows tr[data-state="REAL"]').count()==2
            assert page.locator('#lh-rows tr[data-state="PROYECTADO"]').count()==2
            assert page.locator("#lh-kpi-five").inner_text()=="+0.050s"
            assert page.locator("#lh-rival").input_value()=="1"
            assert page.locator("#race-v2-view").is_hidden()
            assert page.locator("#spotter-view").is_hidden()
            page.locator(".lh-edit-button").nth(1).click()
            assert page.locator("#lh-manual-lap").input_value()=="41"
            page.locator("#lh-manual-fuel").fill("27.9")
            page.locator('#lh-manual-form button[type="submit"]').click()
            assert page.evaluate("""() => window.__sent.some(x=>x.type==='lapFuelEdit'
                     && x.lap===41 && x.remaining===27.9)""")
            page.locator("#lh-filter").select_option("normal")
            assert page.locator("#lh-rows tr").count()==2
            page.locator("#lh-filter").select_option("all")
            for width,height in ((1366,768),(1920,1080),(2560,1440)):
                page.set_viewport_size({"width":width,"height":height})
                assert page.locator("#lap-history-view").is_visible()
                dimensions=page.evaluate("""() => {
                  const box=document.querySelector('.lh-table-shell');
                  const r=box.getBoundingClientRect();
                  return {width:r.width,height:r.height,scrollWidth:box.scrollWidth,
                          clientWidth:box.clientWidth};
                }""")
                assert dimensions["width"]>700,dimensions
                assert dimensions["height"]>70,dimensions
                assert dimensions["scrollWidth"]>=dimensions["clientWidth"],dimensions
                page.screenshot(path=str(OUT/f"comparison-{width}x{height}.png"))
            page.locator("#screen-mode-select").select_option("race")
            assert page.locator("#race-v2-view").is_visible()
            assert page.locator("#lap-history-view").is_hidden()
            page.locator("#screen-mode-select").select_option("lap-history")
            assert page.locator("#lh-rows tr").count()==4
            # Real handoff sequence through one WebSocket and one UI:
            # teammate -> local pilot -> teammate, progressing lap numbers.
            from copy import deepcopy
            local=deepcopy(packet)
            local["teamContext"]["autoMode"]="driver"
            local["lapDatabase"]["team"].append({
                "lap":42,"car_number":"18","driver":"Santiago",
                "lap_time":91.8,"remaining":24.9,"avgConsumption":2.6,
                "kind":"Normal","state":"REAL",
                "source":"SDK_OBSERVED","fuelSource":"REAL_LOCAL"})
            local["lapDatabase"]["projected"]=[
                {"lap":43,"car_number":"18","driver":None,"lap_time":92,
                 "remaining":22.3,"avgConsumption":2.6,
                 "kind":"Normal","state":"PROYECTADO","fuelSource":"ESTIMADO"}]
            page.evaluate("data=>window.__ws.onmessage({data:JSON.stringify(data)})",local)
            assert page.locator("#lh-rows tr").count()==4
            assert page.locator("#lh-rows tr").nth(2).get_attribute("data-state")=="REAL"
            teammate=deepcopy(local)
            teammate["teamContext"]["autoMode"]="spotter"
            teammate["lapDatabase"]["team"].append({
                "lap":43,"car_number":"18","driver":"David",
                "lap_time":93.1,"remaining":22.3,"avgConsumption":2.6,
                "kind":"Normal","state":"REAL",
                "source":"RESULTS_OBSERVED","fuelSource":"ESTIMADO"})
            teammate["lapDatabase"]["projected"]=[
                {"lap":44,"car_number":"18","driver":None,"lap_time":93,
                 "remaining":19.7,"avgConsumption":2.6,
                 "kind":"Normal","state":"PROYECTADO","fuelSource":"ESTIMADO"}]
            page.evaluate("data=>window.__ws.onmessage({data:JSON.stringify(data)})",teammate)
            assert page.locator("#lh-rows tr").count()==5
            assert page.locator("#lh-rows tr").nth(3).get_attribute("data-state")=="REAL"
            assert "David" in page.locator("#lh-rows tr").nth(3).inner_text()
            assert not errors, errors
            browser.close()
            print("PASS: comparison table, KPIs, edit, navigation and 1366/1920/2560 Chromium")
    finally:
        proc.terminate()
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill();proc.wait()
        log.seek(0)
        contents=log.read()
        assert "Traceback" not in contents, contents
