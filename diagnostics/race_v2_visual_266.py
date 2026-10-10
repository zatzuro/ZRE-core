"""Carrera V2 Chromium acceptance using expressly simulated telemetry packets.

Three priority resolutions, short/long field, four unique roles, shared rival,
manual interaction, absent histories, pit and no Race Plan. Screenshots are
evidence for layout only, NOT an SDK/iRacing hardware certification.
"""
import math
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"diagnostics"/"race-v2-screenshots"
OUT.mkdir(parents=True,exist_ok=True)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        return sock.getsockname()[1]


def fixture(n=18, *, duplicate=False, sparse=False, pit=False, plan=True, endurance=False):
    standings=[]
    series=[]
    for i in range(n):
        idx=i+2
        standings.append({
            "carIdx":idx,"carNumber":str(10+i),"driverName":"QA Pilot "+str(i+1),
            "carModel":"QA GT3 "+str(i%3),"classId":4,
            "classPosition":i+1,"officialClassPosition":i+1,
            "positionSource":"RESULTS_POSITIONS",
            "bestLapSeconds":90+i*.14,"lastLapSeconds":91+i*.21,
            "overallPosition":i+5,
            "presence":"LIVE" if not(pit and idx==4) else "STALE",
            "lastSeenAgo":40 if pit and idx==4 else 0,
            "isPlayer":idx==8
        })
    physical={
        "ahead":{"carIdx":7,"carNumber":"15","driverName":"QA Pilot 6",
                 "gapSeconds":1.9,"gapLabel":"≈ 1.90 s · EST.","gapSource":"ZRE_INFERRED","observationState":"LIVE"},
        "behind":{"carIdx":9,"carNumber":"17","driverName":"QA Pilot 8",
                  "gapSeconds":3.2,"gapLabel":"≈ 3.20 s · EST.","gapSource":"ZRE_INFERRED","observationState":"LIVE"}
    }
    rival_idx=7 if duplicate else 4
    roles={"YOU":8,"AHEAD":7,"BEHIND":9,"RIVAL":rival_idx}
    role_groups={}
    for role,idx in roles.items():role_groups.setdefault(idx,[]).append(role)
    for car_idx,role_list in role_groups.items():
        usable=not sparse or car_idx in (8,7)
        laps=[{"lapNumber":30+j,"lapTimeSeconds":90.0+car_idx*.06+j*.12,
               "comparable":j not in (1,6),"source":"SDK_OBSERVED",
               "comparabilityReason":"LAP_TIME_ANOMALY" if j in (1,6) else "ZRE_COMPARABLE_FILTER",
               "driverName":"QA Pilot "+str(car_idx)} for j in range(8)] if usable else []
        series.append({"carIdx":car_idx,"carNumber":str(car_idx+8),"roles":role_list,
                       "recentAverageSeconds":91.1 if usable else None,
                       "sampleCount":5 if usable else 0,"representative":usable,
                       "observationState":"STALE" if pit and car_idx==4 else "LIVE",
                       "samples":laps})
    current_plan={"available":True,"window":{"earliest_safe":23,"target":28,"fuel_limit":31,
                  "state":"BOX NEXT LAP" if pit else "WINDOW OPEN"},
                  "stops":[{"lap":28,"fuel_to_add_liters":80.5}],"minimum_stops":2} if plan else None
    data={"connected":True,"demo":True,"sessionType":"Race",
        "self":{"lastLap":"1:31.250","fuelSource":"REAL LOCAL","pit":"EN PISTA"},
        "teamContext":{"remainingTime":"3:02:14"},"sessionIntelligence":{"session":{"observed":{"timeRemain":10934}}},
        "raceDirector":{"mode":"auto","selectedIdx":rival_idx,"candidates":[]},
        "racePlanVNext":{"available":bool(plan),"currentPlan":current_plan,
             "raceState":{"current_lap":27,"on_pit_road":pit,"require_tire_change":False},
             "fuelModel":{"confidence":"HIGH","source":"REAL LOCAL",
                          "observed_lpl":3.14,"strategy_lpl":3.03}},
        "enduranceStrategy":{"raceFormat":"ENDURANCE"} if endurance else {},
        "raceDashboard":{
             "sessionIdentity":"QA-RACE-SESSION","ownCarIdx":8,
             "ownClassPosition":7,"ownOverallPosition":12,"ownPositionSource":"RESULTS_POSITIONS",
             "classStandings":standings,"physical":physical,"roles":roles,
             "paceSeries":series,"paceDifferenceToRival":.32 if not sparse else None,
             "rival":{"selectionMode":"manual","requestedCarIdx":rival_idx,
                     "effectiveCarIdx":rival_idx,"selectionState":"SELECTED",
                     "selectedRival":next((x for x in standings if x["carIdx"]==rival_idx),None),
                     "observation":{"presence":"STALE" if pit else "LIVE",
                          "lastSeenAgo":40 if pit else 0},
                     "rivalPace":91.1 if not sparse else None},
             "fuel":{"currentLiters":46.2,"observedLpl":3.14,"targetLpl":3.03,
                     "deviationLpl":.11,"autonomyLaps":14.7,
                     "source":"REAL LOCAL","sampleCount":5},
             "source":"QA_FIXTURE"}}
    return data


def measure(page):
    return page.evaluate("""() => {
      const rect=id=>{
        let e=document.getElementById(id);
        if(!e)return null;let r=e.getBoundingClientRect();
        return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};
      };
      return {root:rect('race-v2-view'),standings:rect('rv2-standing-rows'),
        plan:rect('rv2-plan-card'),rival:rect('rv2-rival-select'),
        chart:rect('rv2-pace-chart'),fuel:rect('rv2-fuel-observed'),
        bodyScroll:document.documentElement.scrollHeight>innerHeight+3,
        horizontalScroll:document.documentElement.scrollWidth>innerWidth+3,
        header:rect('car')};
    }""")


def main():
    p=free_port()
    bootstrap="from server import iracing_bridge as b; b.start_background_updater=None; b.main()"
    with tempfile.TemporaryFile(mode="w+") as output:
        server=subprocess.Popen([sys.executable,"-c",bootstrap,"--demo","--port",str(p)],
                                cwd=ROOT,stdout=output,stderr=output)
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
                page=browser.new_page()
                page.add_init_script("""window.__zreSent=[];
                  window.WebSocket=class FakeSocket {
                    static CONNECTING=0;static OPEN=1;
                    constructor(){this.readyState=1;window.__zreFake=this;
                      setTimeout(()=>this.onopen?.(),0)}
                    send(x){window.__zreSent.push(JSON.parse(x))}
                    close(){this.readyState=3}
                  };""")
                page.goto(f"http://127.0.0.1:{p}/",wait_until="domcontentloaded",timeout=30000)
                page.wait_for_function("Boolean(window.ZRERaceV2)")
                errors=[]
                page.on("pageerror",lambda err:errors.append(str(err)))
                for w,h in ((1366,768),(1920,1080),(2560,1440)):
                    page.set_viewport_size({"width":w,"height":h})
                    for n in (8,18,38):
                        current=fixture(n)
                        page.evaluate("""data=>{
                          document.body.classList.remove('race-session','practice-session','quali-session');
                          document.body.classList.add('race-v2-session');
                          document.getElementById('race-v2-view').hidden=false;
                          document.getElementById('rv2-emphasis-control').hidden=false;
                          for(let id of ['live-view','quali-view','spotter-view','pit-view','summary-view'])
                            document.getElementById(id).hidden=true;
                          window.ZRERaceV2.render(data);
                        }""",current)
                        page.wait_for_timeout(100)
                        m=measure(page)
                        assert not m["bodyScroll"],(w,h,n,"body scroll",m)
                        assert not m["horizontalScroll"],(w,h,n,"horizontal scroll",m)
                        assert m["root"]["bottom"]<=h+2,(w,h,n,"root overflow",m)
                        assert m["standings"]["right"]<m["plan"]["left"],(w,h,n,"standings/plan overlap",m)
                        assert m["plan"]["right"]<m["rival"]["left"],(w,h,n,"plan/rival overlap",m)
                        assert m["chart"]["right"]<m["fuel"]["left"],(w,h,n,"chart/fuel overlap",m)
                        assert page.locator("#rv2-standing-rows .rv2-standing-row").count()<=9
                        assert page.locator("#rv2-pace-legend>div").count()==4
                        assert page.locator("#rv2-pace-series .rv2-pace-series-path").count()==4
                        assert page.locator("#race-v2-view").is_visible()
                        assert page.get_by_text("INGENIERO DE CARRERA").count()==0
                        assert page.locator("#rv2-add-fuel").inner_text()=="+80.5 L"
                        assert page.locator("#rv2-target").inner_text()=="V28"
                        assert page.locator("#rv2-stops-left").inner_text()=="2"
                        assert page.locator("#rv2-plan-autonomy").inner_text()=="≈14.7 V"
                        assert page.locator("#rv2-window-track").is_visible()
                        if n==18:
                            page.screenshot(path=str(OUT/f"race-{w}x{h}-4roles.png"),full_page=True)
                        page.locator("#rv2-standings-expand").click()
                        assert page.locator("#rv2-standing-all .rv2-standing-row").count()==n
                        page.locator("#rv2-standings-dialog form button").click()
                        if n==18:
                            page.locator("#rv2-plan-expand").click()
                            assert page.locator("#race-plan-dialog").evaluate("(node)=>node.open")
                            assert page.locator("#race-plan-sim-now").count()==1
                            page.locator("#race-plan-dialog button[aria-label='Cerrar']").click()
                    # Important: same CarIdx serves both AHEAD and strategic RIVAL.
                    shared=fixture(18,duplicate=True)
                    page.evaluate("data=>window.ZRERaceV2.render(data)",shared)
                    assert page.locator("#rv2-pace-legend>div").count()==4
                    assert page.locator("#rv2-pace-series .rv2-pace-series-path").count()==3
                    page.screenshot(path=str(OUT/f"race-{w}x{h}-rival-shared.png"),full_page=True)
                    # Sparse data: no synthetic five-lap mean, one physical series per available car.
                    limited=fixture(18,sparse=True,plan=False)
                    page.evaluate("data=>window.ZRERaceV2.render(data)",limited)
                    assert page.locator("#rv2-pace-series .rv2-pace-series-path").count()==2
                    assert page.locator("#rv2-plan-status").inner_text()=="PLAN NO DISPONIBLE"
                    assert page.locator("#rv2-window-track").is_hidden()
                    # Search by name/number/class position, select through standings.
                    page.locator("#rv2-rival-search").fill("QA Pilot 2")
                    choices=page.locator("#rv2-rival-select option")
                    assert choices.count()>=2
                    page.locator("#rv2-rival-search").fill("")
                    page.locator('#rv2-standing-rows .rv2-standing-row[data-car-idx="4"]').click()
                    assert page.evaluate("""() =>window.__zreSent.some(x=>
                        x.type==='settings'&&x.key==='rival'&&String(x.value)==='4')""")
                    page.locator("#rv2-rival-auto").click()
                    assert page.evaluate("""() =>window.__zreSent.some(x=>
                        x.type==='settings'&&x.key==='rival'&&x.value==='auto')""")
                    page.locator("#header-collapse-toggle").click()
                    m=measure(page)
                    assert not m["bodyScroll"] and not m["horizontalScroll"],(w,h,"collapsed",m)
                    page.locator("#header-collapse-toggle").click()
                    m=measure(page)
                    assert not m["bodyScroll"] and not m["horizontalScroll"],(w,h,"expanded",m)
                    page.evaluate("data=>window.ZRERaceV2.render(data)",fixture(18,pit=True,endurance=True))
                    assert page.locator("#rv2-plan-status").inner_text()=="EN BOXES"
                    pit_fixture=fixture(18,pit=True,endurance=True)
                    pit_fixture["raceDashboard"]["rival"]["observation"]={"presence":"LIVE","onPitRoad":True,"lastSeenAgo":0}
                    page.evaluate("data=>window.ZRERaceV2.render(data)",pit_fixture)
                    assert page.locator("#rv2-rival-presence").inner_text()=="EN BOXES"
                    for emphasis in ("sprint","endurance","auto"):
                        page.locator("#rv2-emphasis-select").select_option(emphasis)
                        assert page.evaluate("document.body.dataset.raceEmphasis")==emphasis
                        m=measure(page)
                        assert not m["bodyScroll"] and not m["horizontalScroll"],(w,h,emphasis,m)
                assert not errors,errors
                browser.close()
                print("PASS Carrera V2: 1366/1920/2560, four series, shared car, gaps, search/selection, plan and folded controls")
        finally:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait()
            output.seek(0)
            logs=output.read()
            assert "Traceback" not in logs,logs


if __name__=="__main__":
    main()
