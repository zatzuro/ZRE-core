import unittest
from server.kpi_library import build_kpi_library, STATE_NOT_APPLICABLE, STATE_LAST_VALID
from server.iracing_bridge import DashboardSource


class Getter:
    def __init__(self, values):
        self.values=values
    def __call__(self,key,default=None):
        return self.values.get(key,default)


def by_id(lib,key):
    return lib["byId"][key]


class KpiLibraryTests(unittest.TestCase):
    def test_driver_library_reuses_fuel_and_distinguishes_positions(self):
        values={
            "LapLastLapTime":79.5,"LapBestLapTime":78.9,"LapDeltaToSessionBestLap":0.25,
            "Throttle":0.72,"Brake":0.0,"SteeringWheelAngle":0.1,"Gear":4,"RPM":7200,"Speed":50,
            "dcBrakeBias":54.5,"dcTractionControl":4,"PlayerCarMyIncidentCount":2,
        }
        payload={
            "sessionType":"Race",
            "sessionIntelligence":{"session":{"observed":{"type":"Race","timeRemain":1800,"lapsRemainEx":12,"flags":0,"state":4}},
                                   "environment":{"observed":{"AirTemp":22.0,"TrackTemp":31.0},"wetnessLabel":"DRY"}},
            "racePlanVNext":{"currentPlan":{"available":True,"minimum_stops":1,"final_fuel_required_liters":40,
                                            "window":{"earliest_safe":20,"target":22,"fuel_limit":24},
                                            "stops":[{"fuel_to_add_liters":32.5,"driver":"David"}]},
                             "fuelModel":{"margin_laps":1.2}},
            "raceDirector":{"rival":"#12","gap":"+3.2"},
            "enduranceStrategy":{"currentStint":"S2"},
            "coach":{"optimal":78.4,"optimalLap":"1:18.400"},
        }
        drivers=[
            {"CarIdx":1,"CarClassID":10,"IRating":2200,"UserName":"Me","CarNumber":"7"},
            {"CarIdx":2,"CarClassID":10,"IRating":1800,"UserName":"Other","CarNumber":"8"},
            {"CarIdx":3,"CarClassID":20,"IRating":3000,"UserName":"OtherClass","CarNumber":"9"},
        ]
        result={"Position":5,"ClassPosition":1,"StartingPosition":6}
        overall=[{"idx":1,"pos":5,"isPlayer":True},{"idx":2,"pos":7}]
        cls=[{"idx":1,"pos":2,"classPos":2,"isPlayer":True},{"idx":2,"pos":3,"classPos":3}]
        lib=build_kpi_library(Getter(values),payload,role="driver",car_idx=1,
            car=drivers[0],result=result,drivers=drivers,overall_rows=overall,class_rows=cls,
            fuel_history=[3.0,3.1,2.9,3.2,3.0],lap_history=[],best_sectors=[],
            completed_laps=18,current_lap=19,fuel_value=45.0,fuel_source="REAL LOCAL",
            average_lap=79.0,stint_laps=8,current_driver="Me",last_valid={})
        self.assertEqual(by_id(lib,"session.position.overall")["value"],5)
        self.assertEqual(by_id(lib,"session.position.class")["value"],2)
        self.assertAlmostEqual(by_id(lib,"fuel.use.avg2")["value"],3.1)
        self.assertAlmostEqual(by_id(lib,"fuel.use.avg5")["value"],3.04)
        self.assertEqual(by_id(lib,"car.tc")["value"],4)
        self.assertEqual(by_id(lib,"input.brake")["value"],0.0)
        self.assertFalse(by_id(lib,"car.tc2")["available"])
        self.assertEqual(by_id(lib,"car.tc2")["state"],STATE_NOT_APPLICABLE)

    def test_spotter_does_not_leak_local_controls_or_tires(self):
        values={"Throttle":1.0,"dcTractionControl":5,"LFwearL":0.90,"LFwearM":0.91,"LFwearR":0.92}
        payload={"sessionIntelligence":{"session":{"observed":{}},"environment":{"observed":{}}},
                 "racePlanVNext":{"fuelModel":{"strategy_lpl":3.4}}}
        lib=build_kpi_library(Getter(values),payload,role="spotter",car_idx=7,
            car={"CarIdx":7,"CarClassID":1,"CarNumber":"22"},result={"Position":8,"ClassPosition":2},
            drivers=[{"CarIdx":7,"CarClassID":1,"CarNumber":"22"}],fuel_history=[],
            completed_laps=10,current_lap=11,fuel_value=20,fuel_source="ESTIMADO",average_lap=90)
        self.assertEqual(by_id(lib,"input.throttle")["state"],STATE_NOT_APPLICABLE)
        self.assertEqual(by_id(lib,"car.tc")["source"],"IDENTITY_PROTECTED_SPOTTER")
        self.assertEqual(by_id(lib,"tire.wear.fl")["state"],STATE_NOT_APPLICABLE)
        self.assertEqual(by_id(lib,"fuel.use.average")["source"],"RACE_PLAN_FUEL_MODEL")

    def test_tire_cache_is_explicitly_last_valid(self):
        cache={}
        payload={"sessionIntelligence":{"session":{"observed":{}},"environment":{"observed":{}}}}
        values={"LFwearL":0.9,"LFwearM":0.9,"LFwearR":0.9}
        first=build_kpi_library(Getter(values),payload,role="driver",car={},result={},drivers=[],
            fuel_history=[],lap_history=[],last_valid=cache)
        self.assertEqual(by_id(first,"tire.wear.fl")["state"],STATE_LAST_VALID)
        second=build_kpi_library(Getter({}),payload,role="driver",car={},result={},drivers=[],
            fuel_history=[],lap_history=[],last_valid=cache)
        self.assertTrue(by_id(second,"tire.wear.fl")["available"])
        self.assertEqual(by_id(second,"tire.wear.fl")["source"],"ZRE_CACHE_LAST_VALID")

    def test_official_sector_tracker_does_not_invent_splits(self):
        source=DashboardSource(force_demo=True)
        values={"SplitTimeInfo":{"Sectors":[{"SectorStartPct":0.0},{"SectorStartPct":0.33},{"SectorStartPct":0.66}]},
                "LapCurrentLapTime":5.0}
        source.get=lambda key,default=None:values.get(key,default)
        source.update_sector_tracking(1,0,None)
        values["LapCurrentLapTime"]=27.0;source.update_sector_tracking(1,.34,None)
        values["LapCurrentLapTime"]=55.0;source.update_sector_tracking(1,.67,None)
        values["LapCurrentLapTime"]=1.0;source.update_sector_tracking(2,.01,82.0)
        self.assertEqual(len(source.last_completed_sectors),3)
        self.assertAlmostEqual(sum(source.last_completed_sectors),82.0,places=3)
        source2=DashboardSource(force_demo=True)
        source2.get=lambda key,default=None:{"SplitTimeInfo":{"Sectors":[]},"LapCurrentLapTime":30}.get(key,default)
        source2.update_sector_tracking(1,.5,None)
        self.assertEqual(source2.last_completed_sectors,[])

    def test_missing_counts_zero_fuel_and_humidity(self):
        lib=build_kpi_library(Getter({"SessionTimeOfDay":0,"SessionTime":50}),
            {"sessionIntelligence":{"environment":{"observed":{"RelativeHumidity":.65}}}},
            role="driver",fuel_history=[3],fuel_value=0,average_lap=80)
        self.assertIsNone(by_id(lib,"session.participants.overall")["value"])
        self.assertEqual(by_id(lib,"fuel.autonomy.laps")["value"],0)
        self.assertEqual(by_id(lib,"environment.relativehumidity")["value"],65)
        self.assertEqual(by_id(lib,"environment.sim_time")["value"],0)

    def test_observed_identity_wins_over_local_player_marker(self):
        lib=build_kpi_library(Getter({}),{},role="spotter",car_idx=7,
            overall_rows=[{"idx":1,"pos":1,"isPlayer":True},{"idx":7,"pos":8}],
            drivers=[{"CarIdx":7},{"CarIdx":7},{"CarIdx":8}])
        self.assertEqual(by_id(lib,"session.position.overall")["value"],8)
        self.assertEqual(by_id(lib,"session.participants.overall")["value"],2)

    def test_disconnect_marks_preserved_kpis_stale(self):
        source=DashboardSource(force_demo=True)
        payload=source.demo_payload()
        payload["kpiLibrary"]=build_kpi_library(Getter({"Throttle":0}),{},role="driver")
        source.session_state.last_payload=payload
        source.session_state.preserved_payload=lambda:payload
        item=by_id(source.disconnected_payload("offline")["kpiLibrary"],"input.throttle")
        self.assertEqual(item["state"],"STALE")
        self.assertEqual(item["value"],0)

    def test_sector_jump_and_invalid_layout_do_not_reuse_readings(self):
        source=DashboardSource(force_demo=True)
        values={"SplitTimeInfo":{"Sectors":[{"SectorStartPct":0},{"SectorStartPct":.3},{"SectorStartPct":.6}]},"LapCurrentLapTime":0}
        source.get=Getter(values)
        source.update_sector_tracking(1,0,None)
        values["LapCurrentLapTime"]=25;source.update_sector_tracking(1,.31,None)
        values["LapCurrentLapTime"]=50;source.update_sector_tracking(1,.61,None)
        source.update_sector_tracking(4,0,80)
        self.assertEqual(source.last_completed_sectors,[])
        source.last_completed_sectors=[25,25,30]
        values["SplitTimeInfo"]={"Sectors":[]}
        source.update_sector_tracking(4,.2,80)
        self.assertEqual(source.last_completed_sectors,[])

    def test_session_reset_clears_cached_tires_and_sectors(self):
        source=DashboardSource(force_demo=True)
        source.kpi_last_valid={"tire.temp.fl":80}
        source.last_completed_sectors=[25,25,30]
        source.sector_last_sample=(1,.5,40)
        source.reset_session_tracking()
        self.assertEqual(source.kpi_last_valid,{})
        self.assertEqual(source.last_completed_sectors,[])
        self.assertIsNone(source.sector_last_sample)

    def test_numeric_coach_optimum_is_available(self):
        lib=build_kpi_library(Getter({}),{"coach":{"optimalSeconds":78.4,"optimalLap":"1:18.400"}},role="driver")
        self.assertTrue(by_id(lib,"lap.optimal")["available"])
        self.assertEqual(by_id(lib,"lap.optimal")["display"],"1:18.400")


if __name__=="__main__":
    unittest.main()
