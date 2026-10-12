"""SDK-shaped integration: actual bridge logic for Quali and stint transitions.
No external iRacing server or Windows claim; controlled SDK observations.
"""
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from server import iracing_bridge as bridge
from server.setup_engineer import SetupEngineer

class BridgeFunctionalTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source=bridge.DashboardSource(force_demo=True)
        self.source.ir=Mock()
        self.source.setup_engineer=SetupEngineer(self.temp.name)
        self.source.recorder=Mock()
        self.source.quali.recorder=self.source.recorder
        self.drivers=[{"CarIdx":i,"CarClassID":4,"CarNumber":str(i+12),
             "UserName":"SDK Pilot "+str(i),"UserID":100+i,"CarScreenName":"GT3"} for i in range(3)]
        self.drivers[1]["UserID"]=101
        self.result=[{"CarIdx":i,"ClassPosition":i,"Position":i+3,
                       "LapsComplete":1,"LastTime":90+i,"FastestTime":89+i} for i in range(3)]
        self.sdk={"PlayerCarIdx":1,
            "DriverInfo":{"DriverUserID":101,"DriverCarIdx":1,"Drivers":self.drivers},
            "WeekendInfo":{"SessionID":420,"SubSessionID":17,"TrackID":8,"TrackName":"QA"},
            "SessionInfo":{"Sessions":[{"SessionType":"Practice","ResultsPositions":self.result},
                                       {"SessionType":"Lone Qualify","ResultsPositions":self.result},
                                       {"SessionType":"Race","ResultsPositions":self.result}]},
            "SessionNum":0,"SessionTime":10.0,"Lap":2,"LapCompleted":1,"LapDistPct":.3,
            "FuelLevel":40.0,"LapLastLapTime":90.1,"LapBestLapTime":89.8,
            "CarIdxLapDistPct":[.2,.3,.35],"CarIdxTrackSurface":[3,3,3],
            "CarIdxClassPosition":[1,2,3],"CarIdxBestLapTime":[89,89.8,90],
            "CarIdxLastLapTime":[90,90.1,91],"CarIdxLapCompleted":[1,1,1],
            "CarIdxLap":[2,2,2],"CarIdxOnPitRoad":[False,False,False],
            "SessionTimeRemain":1200,"IsOnTrack":True,"IsOnTrackCar":True,
            "LapBestLap":1,"LapDeltaToBestLap":-.10,"LapDeltaToBestLap_OK":True}
        self.source.get=lambda key,default=None:self.sdk.get(key,default)
    def tick(self,seconds):
        self.sdk["SessionTime"]=seconds
        return self.source.live_payload(force_driver=True)

    def test_official_quali_routes_and_updates_kpis_with_real_sdk_times(self):
        self.sdk["SessionNum"]=1
        payload=self.tick(10)
        self.assertEqual(payload["sessionType"],"Lone Qualify")
        self.assertEqual(payload["qualifying"]["qualifyingMode"],"official")
        self.assertEqual(payload["sessionMode"],"qualifying")
        self.assertEqual(payload["qualifying"]["bestPersonalSDK"],89.8)
        self.assertTrue(payload["qualifying"]["deltaReferences"]["LapDeltaToBestLap"]["valid"])
        self.assertEqual(payload["qualifying"]["deltaReferences"]["LapDeltaToBestLap"]["value"],-.1)
        run_id=payload["qualifying"]["activeRunId"]
        next_payload=self.tick(11)
        self.assertEqual(next_payload["qualifying"]["activeRunId"],run_id)
        self.assertEqual(len(self.source.quali.runs),1)

    def test_manual_quali_from_practice_preserves_run_and_real_sdk_session(self):
        practice=self.tick(10)
        self.assertEqual(practice["sessionMode"],"practice")
        self.assertTrue(practice["raceDashboard"]["practicePreview"])
        self.assertIsNone(practice["qualifying"]["qualifyingMode"])
        self.assertTrue(self.source.quali.command("simulate"))
        one=self.tick(11)
        self.assertEqual(one["sessionType"],"Practice")
        self.assertEqual(one["qualifying"]["qualifyingMode"],"simulated")
        run_id=one["qualifying"]["activeRunId"]
        # Mid-lap switch and next complete timed SDK lap.
        self.sdk.update(Lap=3,LapCompleted=2,LapLastLapTime=89.2,LapBestLap=2,LapBestLapTime=89.2)
        two=self.tick(102)
        self.assertEqual(two["qualifying"]["activeRunId"],run_id)
        self.assertEqual(two["qualifying"]["bestPersonalSDK"],89.2)
        self.assertEqual(two["sessionType"],"Practice")
        self.tick(103)
        self.assertEqual(len(self.source.quali.runs),1)
        # Visual navigation is frontend-only and must not call command("training").
        self.assertEqual(self.source.quali.mode,"simulated")

    def test_quali_ignores_team_car_idx_fluctuation_in_same_official_session(self):
        self.tick(10)
        identity=self.source.quali.identity
        run=self.source.quali.snapshot()["activeRunId"]
        self.assertEqual(self.source.quali.official_type,"practice")
        self.assertTrue(self.source.quali.command("simulate"))
        run=self.source.quali.snapshot()["activeRunId"]
        # Identity passed to QualiRuns is 4-tuple without CarIdx.
        self.source.quali.observe(identity,"Practice",2,.4,20)
        self.assertEqual(self.source.quali.snapshot()["activeRunId"],run)
        self.assertNotIn("CarIdx",str(identity))
        self.assertEqual(len(self.source.quali.runs),1)

    def test_isolated_sdk_session_clock_regression_does_not_restart_coach(self):
        self.tick(10)
        first=self.source.recorder.write.call_count
        self.tick(1)
        self.assertEqual(self.source.last_session_time,10)
        self.tick(11)
        self.assertEqual(self.source.last_session_time,11)
        events=[c.args[0] for c in self.source.recorder.write.call_args_list
                if c.args and isinstance(c.args[0],dict) and c.args[0].get("type")=="stint_start"]
        self.assertEqual(len(events),1)
        self.assertTrue(self.source.stint_active)

    def test_confirmed_sdk_clock_restart_only_after_three_frames(self):
        self.tick(10)
        for sample in (2,2.1):
            self.tick(sample)
            self.assertEqual(self.source.last_session_time,10)
        self.tick(2.2)
        self.assertEqual(self.source.last_session_time,2.2)
        events=[c.args[0] for c in self.source.recorder.write.call_args_list
                if c.args and isinstance(c.args[0],dict) and c.args[0].get("type")=="stint_start"]
        self.assertEqual(len(events),2)
        self.tick(2.3)
        events=[c.args[0] for c in self.source.recorder.write.call_args_list
                if c.args and isinstance(c.args[0],dict) and c.args[0].get("type")=="stint_start"]
        self.assertEqual(len(events),2)

    def test_transient_is_on_track_false_does_not_reopen_stint(self):
        self.tick(10)
        first=[e for c in self.source.recorder.write.call_args_list for e in c.args if isinstance(e,dict) and e.get("type")=="stint_start"]
        self.assertEqual(len(first),1)
        self.sdk["IsOnTrack"]=False
        self.tick(10.1)
        self.sdk["IsOnTrack"]=True
        self.tick(10.2)
        self.sdk["IsOnTrack"]=False
        self.tick(10.3)
        self.sdk["IsOnTrack"]=True
        self.tick(10.4)
        events=[c.args[0] for c in self.source.recorder.write.call_args_list if c.args and isinstance(c.args[0],dict) and c.args[0].get("type")=="stint_start"]
        self.assertEqual(len(events),1)
        self.assertTrue(self.source.stint_active)

    def test_real_pit_ends_stint_and_next_track_entry_starts_one(self):
        self.tick(10)
        self.sdk["OnPitRoad"]=True
        self.tick(12)
        self.sdk["OnPitRoad"]=False
        self.sdk["IsOnTrack"]=True
        self.tick(13)
        events=[c.args[0] for c in self.source.recorder.write.call_args_list if c.args and isinstance(c.args[0],dict) and c.args[0].get("type")=="stint_start"]
        self.assertEqual(len(events),2)

    def test_real_offtrack_continuous_over_two_seconds_closes_stint(self):
        self.tick(10)
        self.sdk["IsOnTrack"]=False
        self.tick(11)
        self.assertTrue(self.source.stint_active)
        self.tick(14)
        self.assertFalse(self.source.stint_active)

if __name__=="__main__":unittest.main()
