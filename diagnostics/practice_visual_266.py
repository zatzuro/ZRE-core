"""Chromium acceptance of practice layout with controlled QA telemetry fixtures.

This is a real browser layout test, not an iRacing SDK hardware validation.
Writes annotated evidence screenshots to diagnostics/practice-screenshots/.
"""
import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"diagnostics"/"practice-screenshots"
OUT.mkdir(parents=True,exist_ok=True)

def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        return sock.getsockname()[1]

def fixture(n):
    from math import sin,cos,pi
    points=[{"x":50+38*cos(i/199*2*pi),"y":50+29*sin(i/199*2*pi),
             "pct":i/199} for i in range(200)]
    turns=[{"id":f"T{i+1}","zone":f"T{i+1}","pct":i/n,
            "state":"diagnosis" if i%3==0 else "insufficient",
            "title":"Salida lenta" if i%3==0 else "Sin diagnóstico validado",
            "advice":"La referencia muestra una salida de curva con menos velocidad." if i%3==0 else "Completa vueltas comparables.",
            "confidence":"MEDIA" if i%3==0 else None} for i in range(n)]
    laps=[{"lap":i+1,"seconds":93.2-i*.12,"fuelUse":3.0+i*.02} for i in range(10)]
    return {"self":{"bestLap":"1:31.800","fuelValue":42.5,"fuelSource":"REAL LOCAL"},
            "practiceAnalytics":{"lastValidLap":"1:32.120","lastDelta":"+0.320",
                  "averageLap":"1:32.500","consistencySeconds":.194,"fuelLast":3.18,
                  "fuelAverage":3.08,"fuelMin":3.0,"fuelMax":3.18,
                  "fuelLapsEstimated":13.8,"laps":laps},
            "coach":{"optimalLap":"1:31.400","allCorners":turns,
                     "trackMap":{"points":points,"source":"QA FIXTURE","geometrySource":"QA GEOMETRY"}}}

def main():
    p=port()
    launcher="from server import iracing_bridge as b; b.start_background_updater=None; b.main()"
    with tempfile.TemporaryFile(mode="w+") as logs:
        server=subprocess.Popen([sys.executable,"-c",launcher,"--demo","--port",str(p)],
                                cwd=ROOT,stdout=logs,stderr=logs)
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
                page=browser.new_page()
                page.add_init_script("""window.WebSocket=class FakeSocket {
                    static CONNECTING=0;static OPEN=1;
                    constructor(){this.readyState=0;}
                    send(){} close(){this.readyState=3;}
                };""")
                page.goto(f"http://127.0.0.1:{p}/",wait_until="domcontentloaded",timeout=30000)
                page.wait_for_function("Boolean(window.ZREPractice)",timeout=10000)
                errors=[]
                page.on("pageerror",lambda err:errors.append(str(err)))
                for width,height in [(1366,768),(1920,1080),(2560,1440)]:
                    page.set_viewport_size({"width":width,"height":height})
                    for n in (8,14,20):
                        page.evaluate("""data=>{
                            document.body.classList.add('practice-session');
                            document.body.dataset.view='live';
                            document.getElementById('practice-workspace').hidden=false;
                            document.getElementById('live-view').hidden=false;
                            window.ZREPractice.render(data);
                        }""",fixture(n))
                        page.wait_for_timeout(130)
                        measured=page.evaluate("""() => {
                            let stage=document.getElementById('practice-workspace');
                            const corners=[...document.querySelectorAll('.pr-corner')];
                            const rect=id=>{let r=document.getElementById(id).getBoundingClientRect();
                                return {x:r.x,y:r.y,left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
                            return {count:corners.length,viewport:innerHeight,
                                bodyScroll:document.documentElement.scrollHeight>innerHeight+3,
                                stage:rect('practice-workspace'),map:rect('pr-track-map'),
                                coach:rect('pr-corners'),fuel:rect('pr-fuel-panel'),
                                pace:rect('pr-pace-panel'),cornerBoxes:corners.map(x=>{const r=x.getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height};})};
                        }""")
                        assert measured["count"]==n,measured
                        assert not measured["bodyScroll"],(width,height,n,measured)
                        assert measured["map"]["right"]<measured["coach"]["left"],measured
                        assert measured["fuel"]["right"]<measured["pace"]["left"],measured
                        assert all(c["height"]>=21 and c["bottom"]<=measured["coach"]["bottom"]+1
                                   for c in measured["cornerBoxes"]),(width,height,n,measured)
                        if n==20:
                            page.screenshot(path=str(OUT/f"practice-{width}x{height}-20zones.png"),full_page=True)
                        # Full-text modal must work without a general scroll.
                        page.locator(".pr-corner").nth(n-1).click()
                        assert page.locator("#pr-corner-dialog").evaluate("(el)=>el.open")
                        page.locator("#pr-corner-dialog button").click()
                assert not errors,errors
                browser.close()
                print("PASS: Chromium 1366/1920/2560, 8/14/20 curves, no overlaps/scroll, detail dialog")
        finally:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill();server.wait()
            logs.seek(0);txt=logs.read()
            assert "Traceback" not in txt,txt

if __name__=="__main__":
    main()
