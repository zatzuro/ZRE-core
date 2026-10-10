"""ZRE 2.6.6.1: full-app three-screen menu, preserving real SDK session and Quali run.
All packets in this test are EXPLICITLY simulated; not a Windows/iRacing hardware test.
"""
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from diagnostics.practice_visual_266 import fixture as practice_fixture
from diagnostics.quali_visual_266 import fixture as quali_fixture
from diagnostics.race_v2_visual_266 import fixture as race_fixture
from server.iracing_bridge import DashboardSource

OUT = ROOT / "diagnostics" / "screen-menu-2661-screenshots"
OUT.mkdir(exist_ok=True)
base = DashboardSource(force_demo=True).demo_payload()

def packet(source, kind, identity, *, qualification=None):
    src = {**base, **source, "connected": True, "demo": True,
           "sessionMode": {"Practice": "practice", "Qualify": "qualifying", "Race": "race_engineer"}[kind],
           "sessionType": kind}
    # The real live payload publishes analytics regardless of SDK session type.
    src["practiceAnalytics"] = source.get("practiceAnalytics") or practice_fixture(8)["practiceAnalytics"]
    src["self"] = {**base["self"], **source.get("self", {}), "pit": "EN PISTA"}
    src["header"] = {**base["header"], "state": "QA SIMULADO", "track": "QA · NO SDK REAL"}
    src["teamContext"] = {**base.get("teamContext", {}), "autoMode": "driver"}
    src["qualifying"] = {"qualifyingMode": None, "officialSessionType": kind,
                         "officialSessionIdentity": identity, "inGarage": False,
                         **(qualification or {})}
    return src

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

with tempfile.TemporaryFile(mode="w+") as log:
    proc = subprocess.Popen([sys.executable, "-c",
                             "from server import iracing_bridge as b;b.start_background_updater=None;b.main()",
                             "--demo", "--port", str(port)], cwd=ROOT, stdout=log, stderr=log)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script("""window.__sent=[];
window.WebSocket=class {
 static OPEN=1;static CONNECTING=0;
 constructor(){this.readyState=1;window.__ws=this;setTimeout(()=>this.onopen?.(),0)}
 send(message){window.__sent.push(JSON.parse(message))}
 close(){this.readyState=3}
};""")
            for _ in range(50):
                try:
                    page.goto(f"http://127.0.0.1:{port}/")
                    break
                except Exception:
                    time.sleep(.1)
            page.wait_for_function("Boolean(window.__ws?.onmessage)")
            def feed(payload):
                page.evaluate("payload => window.__ws.onmessage({data: JSON.stringify(payload)})", payload)
            def choose(name):
                page.locator("#screen-mode-select").select_option(name)
            def actions(name):
                return page.evaluate("name => window.__sent.filter(x => x.action === 'quali_mode' && x.value === name).length", name)

            noquali = {"qualifyingMode": None, "officialSessionType": "Practice",
                       "officialSessionIdentity": "QA-PRACTICE-1", "inGarage": False}
            pr = packet(practice_fixture(14), "Practice", "QA-PRACTICE-1", qualification=noquali)
            feed(pr)
            assert page.locator("#practice-workspace").is_visible()
            assert page.locator("#screen-mode-select").input_value() == "auto"
            assert not page.locator('#screen-mode-select option[value="practice"]').is_disabled()
            assert not page.locator('#screen-mode-select option[value="quali"]').is_disabled()
            assert page.locator('#screen-mode-select option[value="race"]').is_disabled()

            # Enter full Quali while the *real* SDK remains Practice.
            choose("quali")
            assert actions("simulate") == 1
            assert page.locator("#quali-view").is_visible()
            assert page.locator("#live-view").is_hidden()
            qu = packet(quali_fixture(14, False), "Practice", "QA-PRACTICE-1",
                        qualification={**quali_fixture(14, False)["qualifying"],
                                       "officialSessionIdentity": "QA-PRACTICE-1"})
            feed(qu)
            assert page.locator("#q-kind").inner_text() == "SIMULADA"
            assert "Practice" in page.locator("#q-session-source").inner_text()
            run_before = page.locator("#q-run-id").inner_text()

            # Visual return must neither close the run nor re-arm simulation.
            choose("practice")
            assert page.locator("#practice-workspace").is_visible()
            assert page.locator("#quali-view").is_hidden()
            assert actions("training") == 0
            assert "SIMULACIÓN QUALI ACTIVA" in page.locator("#screen-mode-context").inner_text()
            choose("quali")
            assert page.locator("#quali-view").is_visible()
            assert page.locator("#q-run-id").inner_text() == run_before
            assert actions("simulate") == 1

            # AUTO respects active backend Quali simulation.
            choose("auto")
            assert page.locator("#quali-view").is_visible()
            page.locator("#quali-mode-select").select_option("training")
            assert actions("training") == 1
            feed(pr)
            assert page.locator("#practice-workspace").is_visible()

            # Official Quali is read-only from screen switching; no sim action.
            official = packet(quali_fixture(14, True), "Qualify", "QA-QUALI-2",
                              qualification={**quali_fixture(14, True)["qualifying"],
                                             "officialSessionIdentity": "QA-QUALI-2"})
            feed(official)
            assert page.locator("#quali-view").is_visible()
            assert page.locator("#screen-mode-select").input_value() == "auto"
            choose("practice")
            assert page.locator("#practice-workspace").is_visible()
            assert "SOLO CONSULTA" in page.locator("#screen-mode-context").inner_text()
            choose("quali")
            assert page.locator("#quali-view").is_visible()
            assert actions("simulate") == 1

            # Carrera real has race-only live dashboards; practice is consultation.
            rc = packet(race_fixture(18), "Race", "QA-RACE-3")
            feed(rc)
            assert page.locator("#race-v2-view").is_visible()
            assert page.locator('#screen-mode-select option[value="quali"]').is_disabled()
            assert not page.locator('#screen-mode-select option[value="race"]').is_disabled()
            choose("practice")
            assert page.locator("#practice-workspace").is_visible()
            assert "SOLO CONSULTA" in page.locator("#screen-mode-context").inner_text()
            choose("race")
            assert page.locator("#race-v2-view").is_visible()
            page.locator("#role-select").select_option("spotter")
            assert page.locator("#spotter-view").is_visible()
            assert page.locator("#screen-mode-control").is_hidden()
            page.locator("#role-select").select_option("auto")
            assert page.locator("#race-v2-view").is_visible()

            # Layout: menu must fit horizontal surfaces without blocking controls.
            for width, height in [(1366, 768), (1920, 1080), (2560, 1440)]:
                for scale in [1.0, 1.1]:
                    page.set_viewport_size({"width": int(width / scale),
                                            "height": int(height / scale)})
                    page.wait_for_timeout(75)
                    assert page.locator("#screen-mode-control").is_visible()
                    assert page.locator("#header-collapse-toggle").is_visible()
                    geometry = page.evaluate("""() => {
                      const menu = document.getElementById('screen-mode-control').getBoundingClientRect();
                      const toggle = document.getElementById('header-collapse-toggle').getBoundingClientRect();
                      return {menuRight: menu.right, toggleLeft: toggle.left,
                        width: document.documentElement.scrollWidth, viewport: innerWidth}
                    }""")
                    assert geometry["menuRight"] <= geometry["toggleLeft"] + 3, geometry
                    assert geometry["width"] <= geometry["viewport"] + 3, geometry
                    page.screenshot(path=str(OUT / f"screen-{width}-{scale}.png"))
            assert not errors, errors
            print("PASS screen menu 2.6.6.1: Practice → simulated Quali → Practice → same Quali run,"
                  " AUTO, official Quali, Race, SPOTTER, 3 viewports at 100/110%")
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=5)
