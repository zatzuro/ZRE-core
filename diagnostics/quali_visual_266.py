"""Headless browser acceptance: Quali 16:9, 8/14/20 curves, data provenance and Garage."""
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"diagnostics"/"quali-screenshots"
OUT.mkdir(parents=True,exist_ok=True)


def random_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        return sock.getsockname()[1]


def fixture(n,official=False):
    from math import sin,cos,pi
    points=[{"x":50+38*cos(i/199*2*pi),"y":50+29*sin(i/199*2*pi),"pct":i/199} for i in range(200)]
    corners=[{"zone":"T"+str(i+1),"state":"diagnosis" if i%3==0 else "insufficient",
              "title":"Frenada temprana" if i%3==0 else "Datos insuficientes",
              "advice":"Compara la frenada con la referencia." if i%3==0 else "Completa vueltas."} for i in range(n)]
    attempts=[{"runId":"test-run","attemptId":"test-"+str(i),"sourceLap":i+4,
               "status":"VALID","lapTime":89.5-i*.15,"sectorTimes":[29.5-i*.05,30.0-i*.05,30-i*.05],
               "sectorSource":"ZRE_RECONSTRUCTED_FROM_SDK_SPLITS"} for i in range(2)]
    q={"qualifyingMode":"official" if official else "simulated","officialSessionType":"Qualify" if official else "Practice",
       "inGarage":False,"inPitRoad":False,"onTrack":True,
       "sessionTime":120,"timeRemaining":420,"classPosition":4 if official else None,
       "deltaReferences":{"LapDeltaToBestLap":{"value":-.145,"valid":True,"source":"SDK:LapDeltaToBestLap"}},
       "sectorBoundaries":[0,.32,.66],"sectorTimes":[29.4],"lastSectors":[29.5,30,30],
       "fuelValue":42.5,"fuelPerLap":3.2,"autonomyLaps":13.3,
       "activeRunId":"test-run","activeRun":{"runId":"test-run","kind":"simulated",
          "attempts":attempts,"counts":{"VALID":2},"bestValidLap":89.35},"previousRuns":[]}
    return {"connected":True,"qualifying":q,"self":{"bestLap":"1:29.350","lastLap":"1:29.400","wear":{"FL":"97%","FR":"96%","RL":"95%","RR":"94%"}},
         "coach":{"optimalLap":"1:28.900","potential":"0.450","allCorners":corners,
                  "curveRecommendations":[{"zone":"T1","title":"Frenada temprana","advice":"Retrasa 5 metros la frenada."}],
                  "trackMap":{"points":points,"markers":[{"x":25,"y":50,"corner":"T1"},{"x":72,"y":42,"corner":"T5"}],
                              "geometrySource":"QA FIXTURE"}},
         "sessionIntelligence":{"environment":{"observed":{"TrackTemp":29.5}},
                               "session":{"observed":{"flags":0}},
                               "traffic":{"observed":{"nearestAhead":{"driver":"QA rival","presence":"LIVE",
                                     "relativeLapFraction":.03},"nearestBehind":None}}}}


def main():
    port=random_port()
    runner="from server import iracing_bridge as b; b.start_background_updater=None; b.main()"
    with tempfile.TemporaryFile(mode="w+") as output:
        server=subprocess.Popen([sys.executable,"-c",runner,"--demo","--port",str(port)],
                                cwd=ROOT,stdout=output,stderr=output)
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
                page=browser.new_page()
                page.add_init_script("""window.WebSocket=class FakeSocket {
                    static CONNECTING=0;static OPEN=1;
                    constructor(){this.readyState=0;}
                    send(){} close(){this.readyState=3;}
                };""")
                page.goto(f"http://127.0.0.1:{port}/",wait_until="domcontentloaded",timeout=30000)
                page.wait_for_function("Boolean(window.ZREQuali)")
                errors=[]
                page.on("pageerror",lambda err:errors.append(str(err)))
                for width,height in ((1366,768),(1920,1080),(2560,1440)):
                    page.set_viewport_size({"width":width,"height":height})
                    for n in (8,14,20):
                        data=fixture(n)
                        page.evaluate("""({data,garage})=>{
                            document.body.classList.add('quali-session');
                            document.body.classList.remove('practice-session','qualifying-session');
                            document.getElementById('quali-view').hidden=false;
                            document.getElementById('live-view').hidden=true;
                            window.ZREQuali.render(data,{garage});
                        }""",{"data":data,"garage":False})
                        page.wait_for_timeout(100)
                        metrics=page.evaluate("""() => {
                          let names=['quali-view','q-map-svg','q-sector-rows','q-ahead','q-car-panel','q-attempt-panel'];
                          const rect=x=>{let el=document.getElementById(x)||document.querySelector('.'+x);
                            if(!el)return null;let r=el.getBoundingClientRect();
                            return {x:r.x,y:r.y,left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
                          return {outer:rect('quali-view'),map:rect('q-map-svg'),sectors:rect('q-sector-rows'),
                              car:rect('q-car-panel'),attempts:rect('q-attempt-panel'),
                              bodyOverflow:document.documentElement.scrollHeight>innerHeight+3,
                              horizontalOverflow:document.documentElement.scrollWidth>innerWidth+3,
                              sectionWidth:document.getElementById('quali-view').scrollWidth};
                        }""")
                        assert metrics["map"]["right"]<metrics["sectors"]["left"],(width,height,metrics)
                        assert metrics["car"]["right"]<metrics["attempts"]["left"],(width,height,metrics)
                        assert not metrics["bodyOverflow"],(width,height,metrics)
                        assert not metrics["horizontalOverflow"],(width,height,metrics)
                        assert metrics["outer"]["bottom"]<=height+1,(width,height,metrics)
                        assert page.locator("#q-position").inner_text()=="NO OFICIAL"
                        assert page.locator("#q-delta").inner_text()=="-0.145 s"
                        if n==20:page.screenshot(path=str(OUT/f"quali-track-{width}x{height}.png"),full_page=True)
                        page.evaluate("data=>window.ZREQuali.render(data,{garage:true})",data)
                        assert page.locator(".q-garage-curve").count()==n,(width,height,n)
                        assert "Δ" in page.locator("#q-comparison").inner_text()
                        if n==20:page.screenshot(path=str(OUT/f"quali-garage-{width}x{height}.png"),full_page=True)
                    official=fixture(8,True)
                    page.evaluate("data=>window.ZREQuali.render(data,{garage:false})",official)
                    assert page.locator("#q-position").inner_text()=="P4"
                    official["qualifying"]["deltaReferences"]["LapDeltaToBestLap"]["valid"]=False
                    page.evaluate("data=>window.ZREQuali.render(data,{garage:false})",official)
                    assert page.locator("#q-delta").inner_text()=="—"
                assert not errors,errors
                browser.close()
                print("Quali Chromium three resolutions, 8/14/20 zones, official/simulated, Garage: PASS")
        finally:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait()
            output.seek(0);logs=output.read()
            assert "Traceback" not in logs,logs


if __name__=="__main__":
    main()
