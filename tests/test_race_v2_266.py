"""Carrera V2 domain and critical risks: official rank, physical gap, role dedupe,
manual rival continuity, pace sampling, session identity and unchanged Race Plan.
All data are labeled FIXTURE and must not be mistaken for a live iRacing session.
"""
from copy import deepcopy
import unittest

from server.race_dashboard import race_view, clean_history, physical_neighbor, numeric
from server.race_director import RaceDirector, select_rival
from server import iracing_bridge as bridge


class RaceV2Tests(unittest.TestCase):
    def setUp(self):
        self.carrows = [
            {"idx":2,"pos":3,"classPos":3,"classId":4,"number":"20","car":"GT3 A",
             "driver":"Me","isPlayer":True,"positionSource":"RESULTS_POSITIONS"},
            {"idx":4,"pos":2,"classPos":2,"classId":4,"number":"40","car":"GT3 B",
             "driver":"Driver B","isPlayer":False,"positionSource":"RESULTS_POSITIONS"},
            {"idx":5,"pos":1,"classPos":1,"classId":4,"number":"50","car":"GT3 C",
             "driver":"Driver C","isPlayer":False,"positionSource":"RESULTS_POSITIONS"},
            {"idx":6,"pos":4,"classPos":4,"classId":4,"number":"60","car":"GT3 D",
             "driver":"Driver D","isPlayer":False,"positionSource":"RESULTS_POSITIONS"},
        ]
        self.results={2:{"ClassPosition":2,"Position":10,"FastestTime":81.5,"LastTime":82},
                      4:{"ClassPosition":1,"Position":9,"FastestTime":80,"LastTime":83},
                      5:{"ClassPosition":0,"Position":8,"FastestTime":87,"LastTime":85},
                      6:{"ClassPosition":3,"Position":11,"FastestTime":79,"LastTime":81}}
        self.cars={idx:{"CarClassID":4,"CarNumber":str(idx)} for idx in (2,4,5,6)}
        self.best=[None]*10
        self.last=[None]*10
        self.best[4]=80
        self.last[4]=83
        def laps(offset,driver):
            return [{"lap":i+1,"time":82.5-i*.13+offset,"source":"SDK_OBSERVED",
                     "sessionTime":i*90,"driverName":driver} for i in range(8)]
        self.a=laps(.5,"Driver A")
        self.b=laps(-.3,"Driver B")
        self.c=laps(.8,"Driver C")
        self.d=laps(-.1,"Driver D")
        self.own=[{**x,"valid":True} for x in self.a]
        self.neighbors=[
            {"carIdx":4,"number":"40","driver":"Driver B","sameClass":True,"presence":"LIVE",
             "onPitRoad":False,"relativeLapFraction":.03,
             "gapEvidence":{"seconds":3.1,"source":"ZRE_INFERRED","confidence":"MEDIUM"},
             "lapTimes":self.b,"cleanLapTimes":self.b,"lastSeenSessionTime":680,"lastSeenAgo":0,
             "car":"GT3 B"},
            {"carIdx":6,"number":"60","driver":"Driver D","sameClass":True,"presence":"LIVE",
             "onPitRoad":False,"relativeLapFraction":-.04,
             "gapEvidence":{"seconds":-4.5,"source":"ZRE_INFERRED","confidence":"LOW"},
             "lapTimes":self.d,"cleanLapTimes":self.d,"lastSeenSessionTime":680,"lastSeenAgo":0,
             "car":"GT3 D"},
            {"carIdx":5,"number":"50","driver":"Driver C","sameClass":True,"presence":"LIVE",
             "onPitRoad":False,"relativeLapFraction":.2,"gapEvidence":{"seconds":21,"source":"ZRE_INFERRED"},
             "lapTimes":self.c,"cleanLapTimes":self.c,"car":"GT3 C"},
        ]
        self.plan={"available":True,"currentPlan":{
                    "available":True,"window":{"earliest_safe":20,"target":23,"fuel_limit":25},
                    "stops":[{"lap":23,"fuel_to_add_liters":87.5}],"minimum_stops":2},
                   "fuelModel":{"source":"REAL LOCAL","observed_lpl":3.14,
                                "strategy_lpl":3.05,"confidence":"HIGH"}}
        self.director=RaceDirector()

    def test_own_caution_lap_is_visible_but_not_in_pace_mean(self):
        rows=[{"lap":i,"time":90,"valid":True} for i in range(1,5)]
        rows.append({"lap":5,"time":150,"valid":True,"caution":True})
        result=clean_history(rows,rows,own=True)
        self.assertEqual(result["recentAverageSeconds"],90)
        self.assertFalse(result["samples"][-1]["comparable"])
        self.assertEqual(result["samples"][-1]["comparabilityReason"],"CAUTION")

    def state(self,*,selected=None,neighbors=None,carrows=None,own=None,plan=None,session="race-100"):
        if selected is not None:self.director.set_selected(selected)
        rows=carrows if carrows is not None else self.carrows
        packet=self.director.payload(rows,2)
        others=self.neighbors if neighbors is None else neighbors
        traffic={"nearestAhead":next((x for x in others if x.get("relativeLapFraction") is not None and x["relativeLapFraction"]>0 and x.get("presence")=="LIVE" and not x.get("onPitRoad")),None),
                 "nearestBehind":next((x for x in others if x.get("relativeLapFraction") is not None and x["relativeLapFraction"]<0 and x.get("presence")=="LIVE" and not x.get("onPitRoad")),None)}
        intel={"traffic":{"observed":traffic},"competitors":{"observed":others}}
        return race_view(session_identity=session,own_idx=2,class_rows=rows,results=self.results,
                         cars=self.cars,best_laps=self.best,last_laps=self.last,
                         intelligence=intel,own_history=self.own if own is None else own,
                         director=packet,fuel=42.5,fuel_history=[3.1,3.12,3.14],
                         race_plan=self.plan if plan is None else plan,session_time=680)

    def test_official_order_not_derived_from_best_laps(self):
        payload=self.state()
        self.assertEqual([x["carIdx"] for x in payload["classStandings"]],[5,4,2,6])
        self.assertEqual(payload["ownClassPosition"],3)
        self.assertEqual(payload["ownOverallPosition"],10)
        self.assertEqual(payload["ownPositionSource"],"RESULTS_POSITIONS")
        self.assertLess(payload["classStandings"][-1]["bestLapSeconds"],payload["classStandings"][0]["bestLapSeconds"])

    def test_zero_based_official_class_position(self):
        rows=bridge.class_results_rows(self.results,self.cars,set(),4,2,self.last,bridge.DashboardSource.lap_text)
        self.assertEqual([x["pos"] for x in rows],[1,2,3,4])
        self.assertTrue(all(x["positionSource"]=="RESULTS_POSITIONS" for x in rows))

    def test_position_fallback_is_not_official(self):
        self.results[5].pop("ClassPosition")
        row=next(x for x in self.carrows if x["idx"]==5)
        row["positionSource"]="CarIdxClassPosition"
        view=self.state()
        entry=next(x for x in view["classStandings"] if x["carIdx"]==5)
        self.assertEqual(entry["positionSource"],"CARIDX_CLASS_POSITION_FALLBACK")
        self.assertIsNone(entry["officialClassPosition"])

    def test_physical_neighbors_can_disagree_with_official_positions(self):
        v=self.state(selected=5)
        self.assertEqual(v["physical"]["ahead"]["carIdx"],4)
        self.assertEqual(v["physical"]["behind"]["carIdx"],6)
        self.assertEqual(v["rival"]["effectiveCarIdx"],5)
        self.assertEqual(v["physical"]["ahead"]["gapSeconds"],3.1)
        self.assertEqual(v["physical"]["ahead"]["gapSource"],"ZRE_INFERRED")

    def test_nonclass_physical_neighbor_remains_eligible(self):
        other={**self.neighbors[0],"carIdx":7,"number":"70","sameClass":False}
        view=self.state(neighbors=[other,*self.neighbors[1:]])
        self.assertEqual(view["physical"]["ahead"]["carIdx"],7)
        self.assertFalse(view["physical"]["ahead"]["sameClass"])
        self.assertNotIn(7,[r["carIdx"] for r in view["classStandings"]])

    def test_missing_dynamic_gap_does_not_fall_back_to_standings(self):
        changes=[{**self.neighbors[0],"gapEvidence":None,"relativeLapFraction":.04},self.neighbors[1]]
        view=self.state(neighbors=changes)
        self.assertIsNone(view["physical"]["ahead"]["gapSeconds"])
        self.assertEqual(view["physical"]["ahead"]["gapLabel"],"EST. SIN DATO")

    def test_no_live_track_position_yields_no_neighbor(self):
        changes=[{**self.neighbors[0],"presence":"STALE","relativeLapFraction":None},self.neighbors[1]]
        view=self.state(neighbors=changes)
        self.assertIsNone(view["physical"]["ahead"])

    def test_manual_rival_selection_keeps_four_distinct_roles(self):
        view=self.state(selected=5)
        self.assertEqual(view["roles"],{"YOU":2,"AHEAD":4,"BEHIND":6,"RIVAL":5})
        self.assertEqual(len(view["paceSeries"]),4)
        self.assertTrue(all(len(x["samples"])==8 for x in view["paceSeries"]))

    def test_same_rival_as_ahead_is_one_physical_series_with_two_roles(self):
        v=self.state(selected=4)
        self.assertEqual(len(v["paceSeries"]),3)
        self.assertEqual(next(s for s in v["paceSeries"] if s["carIdx"]==4)["roles"],["AHEAD","RIVAL"])
        self.assertEqual(len(v["roles"]),4)

    def test_same_rival_as_behind_is_one_physical_series_with_two_roles(self):
        v=self.state(selected=6)
        self.assertEqual(len(v["paceSeries"]),3)
        self.assertEqual(next(s for s in v["paceSeries"] if s["carIdx"]==6)["roles"],["BEHIND","RIVAL"])

    def test_change_rival_only_reassigns_rival_series(self):
        old=self.state(selected=4)
        new=self.state(selected=5)
        for role in ("YOU","AHEAD","BEHIND"):
            self.assertEqual(old["roles"][role],new["roles"][role])
        self.assertEqual(new["roles"]["RIVAL"],5)

    def test_automatic_selector_chooses_closest_class_position(self):
        v=self.state()
        self.assertEqual(v["rival"]["selectionMode"],"auto")
        self.assertIn(v["roles"]["RIVAL"],(4,6))

    def test_manual_selection_survives_pit_and_position_changes(self):
        self.state(selected=4)
        self.neighbors[0]["onPitRoad"]=True
        self.carrows[1]["classPos"]=4
        v=self.state()
        self.assertEqual(v["rival"]["selectionMode"],"manual")
        self.assertEqual(v["rival"]["effectiveCarIdx"],4)

    def test_manual_selection_unobserved_no_silent_auto(self):
        self.state(selected=5)
        reduced=[row for row in self.carrows if row["idx"]!=5]
        view=self.state(carrows=reduced,neighbors=self.neighbors[:2])
        self.assertEqual(view["rival"]["selectionMode"],"manual")
        self.assertEqual(view["rival"]["requestedCarIdx"],5)
        self.assertIsNone(view["rival"]["effectiveCarIdx"])
        self.assertEqual(view["rival"]["selectionState"],"TEMPORARILY_UNAVAILABLE")

    def test_auto_explicitly_clears_manual(self):
        self.state(selected=4)
        self.director.set_selected("auto")
        self.assertIsNone(self.director.selected_idx)
        self.assertEqual(self.state()["rival"]["selectionMode"],"auto")

    def test_driver_change_keeps_car_history(self):
        original=self.state(selected=4)
        modified=[{**self.neighbors[0],"driver":"Driver NEW",
                    "lapTimes":[*self.b[:-1],{**self.b[-1],"driverName":"Driver NEW"}]},
                  *self.neighbors[1:]]
        later=self.state(neighbors=modified)
        history=next(s for s in later["paceSeries"] if s["carIdx"]==4)["samples"]
        self.assertEqual(history[0]["driverName"],"Driver B")
        self.assertEqual(history[-1]["driverName"],"Driver NEW")
        self.assertEqual(later["rival"]["requestedCarIdx"],4)
        self.assertEqual(len(original["paceSeries"]),len(later["paceSeries"]))

    def test_history_gap_not_interpolated(self):
        full=[{**x,"lap":x["lap"]*2} for x in self.b]
        changed=[{**self.neighbors[0],"lapTimes":full,"cleanLapTimes":full},*self.neighbors[1:]]
        view=self.state(neighbors=changed)
        observed=next(s for s in view["paceSeries"] if s["carIdx"]==4)["samples"]
        self.assertEqual([x["lapNumber"] for x in observed],[2,4,6,8,10,12,14,16])

    def test_clean_pace_average_latest_five_only(self):
        view=self.state()
        series=next(s for s in view["paceSeries"] if s["carIdx"]==4)
        expected=sum(x["time"] for x in self.b[-5:])/5
        self.assertAlmostEqual(series["recentAverageSeconds"],expected,3)
        self.assertEqual(series["sampleCount"],5)

    def test_small_sample_count_no_fabricated_average(self):
        laps=self.b[:2]
        view=self.state(neighbors=[{**self.neighbors[0],"lapTimes":laps,"cleanLapTimes":laps},*self.neighbors[1:]])
        row=next(s for s in view["paceSeries"] if s["carIdx"]==4)
        self.assertEqual(row["sampleCount"],2)
        self.assertFalse(row["representative"])
        self.assertIsNone(row["recentAverageSeconds"])
        self.assertEqual(len(row["samples"]),2)

    def test_laps_without_comparability_remain_diagnostic_only(self):
        last=[{**x,"comparabilityReason":"PIT_LAP"} for x in self.b[-2:]]
        view=self.state(neighbors=[{**self.neighbors[0],"lapTimes":[*self.b[:-2],*last],
                    "cleanLapTimes":self.b[:-2]},*self.neighbors[1:]])
        row=next(s for s in view["paceSeries"] if s["carIdx"]==4)
        self.assertFalse(row["samples"][-1]["comparable"])
        self.assertEqual(row["samples"][-1]["comparabilityReason"],"PIT_LAP")
        self.assertEqual(row["sampleCount"],5)

    def test_clean_is_not_officially_valid(self):
        view=self.state()
        self.assertIn("NO CONFIRMACIÓN OFICIAL",view["paceSeries"][0]["label"])

    def test_own_pace_uses_only_local_valid_history(self):
        own=self.own[:-2]+[{**x,"valid":False} for x in self.own[-2:]]
        view=self.state(own=own)
        row=next(s for s in view["paceSeries"] if s["carIdx"]==2)
        self.assertEqual(row["sampleCount"],5)
        self.assertFalse(row["samples"][-1]["comparable"])

    def test_fuel_target_and_deviation_preserve_vnext(self):
        copy=deepcopy(self.plan)
        v=self.state()
        self.assertEqual(v["fuel"]["observedLpl"],3.14)
        self.assertEqual(v["fuel"]["targetLpl"],3.05)
        self.assertEqual(v["fuel"]["deviationLpl"],.09)
        self.assertEqual(self.plan,copy)

    def test_no_defined_target_is_not_invented(self):
        p=deepcopy(self.plan);p["fuelModel"]["strategy_lpl"]=None
        v=self.state(plan=p)
        self.assertIsNone(v["fuel"]["targetLpl"])
        self.assertIsNone(v["fuel"]["deviationLpl"])

    def test_no_valid_fuel_no_autonomy(self):
        p=deepcopy(self.plan);p["fuelModel"]["observed_lpl"]=None
        v=race_view(session_identity="race",own_idx=2,class_rows=self.carrows,results=self.results,
               cars=self.cars,best_laps=self.best,last_laps=self.last,
               intelligence={},own_history=[],director={},fuel=None,fuel_history=[],
               race_plan=p)
        self.assertIsNone(v["fuel"]["autonomyLaps"])
        self.assertIsNone(v["fuel"]["currentLiters"])

    def test_timing_stale_falls_back_to_results(self):
        stale=[{**self.neighbors[0],"presence":"STALE","lastSeenAgo":40},
               *self.neighbors[1:]]
        self.last[4]=84
        view=self.state(neighbors=stale)
        row=next(r for r in view["classStandings"] if r["carIdx"]==4)
        self.assertEqual(row["lastLapSeconds"],83)
        self.assertNotEqual(row["timingSource"],"CARIDX_LIVE")
        self.assertEqual(row["presence"],"STALE")

    def test_missing_best_is_none_not_zero(self):
        self.best[6]=0
        self.results[6]["FastestTime"]=0
        view=self.state()
        row=next(r for r in view["classStandings"] if r["carIdx"]==6)
        self.assertIsNone(row["bestLapSeconds"])

    def test_session_identity_is_explicit(self):
        one=self.state(session="race-one")
        two=self.state(session="race-two")
        self.assertNotEqual(one["sessionIdentity"],two["sessionIdentity"])
        self.assertFalse(any("race-one" in str(x) for x in two["paceSeries"]))

    def test_race_director_not_modified_by_view_generation(self):
        self.state(selected=4)
        selected=self.director.selected_idx
        self.state()
        self.assertEqual(self.director.selected_idx,selected)

    def test_fuel_model_is_sole_source_for_operational_average(self):
        p=deepcopy(self.plan);p["fuelModel"]["observed_lpl"]=None
        view=self.state(plan=p)
        self.assertIsNone(view["fuel"]["observedLpl"])
        self.assertIsNone(view["fuel"]["autonomyLaps"])
        self.assertIsNone(view["fuel"]["deviationLpl"])

    def test_offline_after_race_marks_dynamic_positions_stale(self):
        s=bridge.DashboardSource(force_demo=True)
        view=self.state()
        last={"header":{"car":"QA GT3","track":"QA Road",
                        "driver":"QA","state":"RUNNING"},
              "self":{"fuel":"42.5 L","lastLap":"1:32.400"},
              "connected":True,"sessionType":"Race","sessionMode":"race_engineer",
              "raceDashboard":view,"racePlanVNext":self.plan}
        s.session_state.remember_payload(last)
        disconnected=s.disconnected_payload("SDK desconectado")
        race=disconnected["raceDashboard"]
        self.assertFalse(disconnected["connected"])
        self.assertTrue(race["stale"])
        self.assertIsNone(race["physical"]["ahead"])
        self.assertIsNone(race["physical"]["behind"])
        self.assertTrue(all(row["presence"]=="STALE" for row in race["classStandings"]))
        self.assertTrue(all(row["observationState"]=="STALE" for row in race["paceSeries"]))
        self.assertIsNone(race["fuel"]["currentLiters"])
        self.assertFalse(disconnected["racePlanVNext"]["available"])

    def test_no_prior_sdk_sample_never_pretends_demo_is_live(self):
        s=bridge.DashboardSource(force_demo=True)
        no_data=s.disconnected_payload("SDK ausente")
        self.assertFalse(no_data["connected"])
        self.assertFalse(no_data["demo"])
        self.assertEqual(no_data["sessionType"],"UNKNOWN")
        self.assertEqual(no_data["header"]["car"],"—")
        self.assertEqual(no_data["standing"],[])
        self.assertEqual(no_data["relative"],[])
        self.assertEqual(no_data["coach"],{})

    def test_live_sdk_driver_contract_emits_race_dashboard(self):
        from unittest.mock import Mock
        from tempfile import TemporaryDirectory
        from server.setup_engineer import SetupEngineer
        src=bridge.DashboardSource(force_demo=True)
        src.ir=Mock()
        drivers=[{"CarIdx":i,"CarClassID":4,"CarNumber":str(10+i),
                  "UserName":"SDK QA "+str(i),"UserID":100+i} for i in range(3)]
        results=[{"CarIdx":i,"ClassPosition":i,"Position":i+4,
                  "LapsComplete":0,"LastTime":90+i,"FastestTime":89+i} for i in range(3)]
        sdk={"PlayerCarIdx":1,"DriverInfo":{"DriverUserID":101,"DriverCarIdx":1,"Drivers":drivers},
             "SessionInfo":{"Sessions":[{"SessionType":"Race","ResultsPositions":results}]},
             "SessionNum":0,"SessionTime":1,"Lap":1,"LapCompleted":0,
             "FuelLevel":42.5,"LapLastLapTime":90.5,"LapBestLapTime":89.5,
             "CarIdxLapDistPct":[.2,.3,.35],"CarIdxTrackSurface":[3,3,3],
             "CarIdxClassPosition":[1,2,3],"CarIdxBestLapTime":[89,89.5,90],
             "CarIdxLastLapTime":[90,90.5,91],"CarIdxLapCompleted":[0,0,0],
             "CarIdxLap":[1,1,1],"CarIdxOnPitRoad":[False,False,False],
             "SessionTimeRemain":1200,"IsOnTrack":True}
        src.get=lambda key,default=None:sdk.get(key,default)
        with TemporaryDirectory() as folder:
            src.setup_engineer=SetupEngineer(folder)
            src.recorder=Mock()
            src.quali.recorder=src.recorder
            packet=src.live_payload(force_driver=True)
            race=packet["raceDashboard"]
            self.assertEqual(packet["sessionType"],"Race")
            self.assertEqual(race["ownCarIdx"],1)
            self.assertEqual(race["ownClassPosition"],2)
            self.assertEqual([r["classPosition"] for r in race["classStandings"]],[1,2,3])
            self.assertFalse(packet["demo"])
            self.assertEqual(race["fuel"]["currentLiters"],42.5)
            self.assertIn("racePlanVNext",packet)
            self.assertIn("raceDirector",packet)

    def test_session_change_resets_manual_selection(self):
        src=bridge.DashboardSource(force_demo=True)
        src.race_director.set_selected(4)
        src.race_class_candidates={4}
        src.reset_session_tracking()
        self.assertIsNone(src.race_director.selected_idx)
        self.assertFalse(src.race_class_candidates)

    def test_no_unbounded_lap_array_sent_to_browser(self):
        laps=[{"lap":i+1,"time":80+i*.005,"source":"SDK_OBSERVED"} for i in range(200)]
        row=clean_history(laps,laps)
        self.assertEqual(len(row["samples"]),8)
        self.assertEqual(row["sampleCount"],5)


if __name__=="__main__":
    unittest.main()
