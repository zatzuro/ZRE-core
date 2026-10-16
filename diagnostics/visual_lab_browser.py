"""Browser smoke for the REAL ZRE frontend wrapped by static Visual Lab."""
from __future__ import annotations
import http.server
import socket
import sys
import tempfile
import threading
from functools import partial
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
from build_visual_lab import build


class SilentHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*args): pass


def main():
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        build(root,"develop/visual-lab-web","TEST-BROWSER-SHA")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0))
            port=sock.getsockname()[1]
        srv=http.server.ThreadingHTTPServer(("127.0.0.1",port),partial(SilentHandler,directory=str(root)))
        thread=threading.Thread(target=srv.serve_forever,daemon=True)
        thread.start()
        try:
            with sync_playwright() as engine:
                browser=engine.chromium.launch(headless=True,args=["--no-sandbox"])
                context=browser.new_context(viewport={"width":1920,"height":1080},device_scale_factor=1)
                page=context.new_page()
                sockets=[]
                mutations=[]
                page.on("websocket",lambda ws:sockets.append(ws.url))
                page.on("request",lambda request:mutations.append((request.method,request.url)) if request.method!="GET" else None)
                page.goto(f"http://127.0.0.1:{port}/",wait_until="networkidle",timeout=30000)
                frame=page.frame_locator("#lab-frame")
                page.locator("#lab-status").filter(has_text="Preview listo").wait_for(timeout=20000)
                assert "ZRE VISUAL LAB" in frame.locator("#lab-simulation-banner").inner_text()
                assert not sockets,"Lab unexpectedly opened a WebSocket: "+repr(sockets)
                assert not mutations,"Lab unexpectedly submitted a network mutation: "+repr(mutations)

                def scenario(screen,choice,selector,expected=None):
                    page.locator("#lab-screen").select_option(screen)
                    page.locator("#lab-scenario").select_option(choice)
                    frame.locator(selector).wait_for(state="visible",timeout=8000)
                    if expected is not None:
                        actual=frame.locator(selector).first.inner_text()
                        assert expected in actual, (screen,choice,selector,actual,expected)

                scenario("practice","practice-32","#pr-pace-count","32 VUELTAS")
                scenario("practice","practice-70","#pr-pace-count","70 VUELTAS")
                scenario("practice","practice-empty","#pr-pace-status","SIN VUELTAS")
                scenario("practice","practice-anomaly","#pr-pace-count","32 VUELTAS")
                scenario("quali","quali-attempts","#q-attempt-count","5")
                scenario("quali","quali-garage","#q-garage-run","TANDA")
                scenario("race","race-endurance","#rv2-standing-rows")
                assert frame.locator("#rv2-standing-rows .rv2-standing-row").count()>0
                assert frame.locator("#rv2-pace-legend").locator("div").count()>=4
                assert frame.locator("#rv2-pace-series").locator("path,polyline,circle").count()>0
                frame.locator("#rv2-rival-select").select_option("13")
                frame.locator("#rv2-rival-name").filter(has_text="#23").wait_for(timeout=5000)
                scenario("race","race-fuel-critical","#rv2-alert","FUEL BAJO")
                scenario("race","race-box-now","#rv2-plan-status","BOX THIS LAP")
                scenario("pit","quali-garage","#pit-view")
                scenario("summary","special-finished","#summary-view")
                scenario("spotter","spotter-team","#spotter-car","#20")
                scenario("race","special-disconnected","#rv2-alert","SDK SIN SEÑAL")
                names=page.evaluate("window.ZRELabScenarios.map(x=>x[0])")
                for name in names:
                    page.locator("#lab-scenario").select_option(name)
                    assert "ERROR VISUAL LAB" not in page.locator("#lab-status").inner_text(),name
                page.locator("#lab-screen").select_option("practice")
                frame.locator("#capture-sdk").click()
                page.locator("#lab-status").filter(has_text="FUNCIÓN DISPONIBLE SOLO EN ZRE LOCAL").wait_for(timeout=5000)
                assert not sockets and not mutations
                for w,h in [(1366,768),(1920,1080),(2560,1440)]:
                    page.set_viewport_size({"width":w,"height":h})
                    page.locator("#lab-resolution").select_option(str(w)+"x"+str(h))
                    for screen,name in [("practice","practice-32"),("quali","quali-attempts"),
                                        ("race","race-endurance"),("spotter","spotter-team")]:
                        scenario(screen,name,"#lab-simulation-banner")
                        file=ROOT/"diagnostics"/"visual-lab-screenshots"/(screen+"-"+str(w)+"x"+str(h)+".png")
                        file.parent.mkdir(parents=True,exist_ok=True)
                        page.screenshot(path=str(file),full_page=True)
                # Browser 110% zoom: same product panels stay accessible.
                page.set_viewport_size({"width":1366,"height":768})
                page.locator("#lab-resolution").select_option("1366x768")
                frame.locator("body").evaluate("(el)=>{el.style.zoom='1.1'}")
                for screen,name,required in [("practice","practice-32","#pr-pace-svg"),
                                             ("quali","quali-attempts","#q-attempt-count"),
                                             ("race","race-endurance","#rv2-plan-card"),
                                             ("spotter","spotter-team","#spotter-car")]:
                    scenario(screen,name,required)
                    image=ROOT/"diagnostics"/"visual-lab-screenshots"/(screen+"-1366x768-110pct.png")
                    page.screenshot(path=str(image),full_page=True)
                assert not sockets and not mutations
                print("VISUAL LAB BROWSER PASS:",len(names),"scenarios, seven screens, 3 sizes, no WebSocket/POST; screenshots in diagnostics/visual-lab-screenshots")
                browser.close()
        finally:
            srv.shutdown()


if __name__=="__main__":main()
