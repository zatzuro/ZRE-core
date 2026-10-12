"""Session continuity 2.6.7: resume observed laps after a restart.

These tests use SDK-shaped fixtures; they do not claim a live iRacing run.
Never upgrade locally recorded result positions to current official standings.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from server.session_recorder import SessionRecorder
from server.session_archive import SessionArchive
from server import iracing_bridge as bridge
from server.setup_engineer import SetupEngineer

WEEKEND={"SessionID":420,"SubSessionID":17,"TrackID":8,
         "TrackName":"QA Road","TrackDisplayName":"QA Road"}
META={"track":"QA Road","sessionType":"Race","sessionId":420,
      "subSessionId":17,"trackId":8,"sessionNum":0,"carIdx":1}

class SessionContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.path=self.base/"session_replay.jsonl"
        self.writer=SessionRecorder(self.path)
        self.addCleanup(self.writer.close)

    def captured(self):
        self.writer.start_session("SDK-420",META)
        self.writer.write({"type":"sdk_grid","sessionTime":200.0,
            "fields":{"SessionNum":0,"SessionType":"Race",
                      "ResultsPositions":[
                          {"CarIdx":1,"ClassPosition":1,"Position":3,"LastTime":88.5},
                          {"CarIdx":2,"ClassPosition":0,"Position":2,"LastTime":88.2}],
                      "CarIdxLapCompleted":[6,6,6]}})
        self.writer.write({"type":"sdk_roster","sessionTime":200.0,
            "driverInfo":{"Drivers":[
                {"CarIdx":1,"CarClassID":4,"CarNumber":"11",
                 "UserName":"You","UserID":101},
                {"CarIdx":2,"CarClassID":4,"CarNumber":"12",
                 "UserName":"Historic rival","UserID":102}]},
            "weekendInfo":WEEKEND})
        clean=[{"lap":i,"time":88.5+i*.01,"comparable":True,
                "sessionTime":i*89,"source":"SDK_OBSERVED"} for i in (3,4,5)]
        self.writer.write({"type":"competitor_history","sessionTime":201.0,
            "carIdx":2,"classId":4,"number":"12","driver":"Historic rival",
            "car":"QA GT3","lastLap":89.0,"bestLap":88.2,
            "lastSeenSessionTime":200,"lapsComplete":6,
            "lapTimes":clean,"cleanLapTimes":clean,"pitHistory":[],
            "presence":"STALE","source":"SDK_OBSERVED"})
        for lap in (3,4,5):
            self.writer.write({"type":"lap","lap":lap,
                "officialTime":90-lap*.1,"valid":True,
                "sessionTime":lap*90,"fuelUse":2.7,"source":"SDK_OBSERVED"})
        folder=self.writer.session_dir
        self.writer.finish_session("shutdown")
        self.assertTrue(self.writer.flush())
        self.assertTrue((folder/"recovery.json").exists())
        self.assertNotIn("recovery",json.loads((folder/"summary.json").read_text()))
        return folder

    def test_checkpoint_contains_rival_history_offline(self):
        folder=self.captured()
        result=self.writer.archive.recover_session(WEEKEND,0)
        self.assertEqual(result["fromSessionId"],folder.name)
        self.assertEqual(result["carIdx"],1)
        self.assertEqual(len(result["ownLaps"]),3)
        self.assertEqual(len(result["competitors"]["2"]["lapTimes"]),3)
        self.assertEqual(len(result["grid"]["ResultsPositions"]),2)

    def test_recovery_never_reuses_other_official_session(self):
        self.captured()
        for alteration in ({"SessionID":999},{"SubSessionID":18},{"TrackID":9}):
            weekend={**WEEKEND,**alteration}
            self.assertIsNone(self.writer.archive.recover_session(weekend,0))
        self.assertIsNone(self.writer.archive.recover_session(WEEKEND,1))

    def test_sdk_live_positions_win_and_offline_history_is_stale(self):
        folder=self.captured()
        source=bridge.DashboardSource(force_demo=True)
        source.ir=Mock()
        source.recorder=SessionRecorder(self.path)
        self.addCleanup(source.recorder.close)
        source.quali.recorder=source.recorder
        source.setup_engineer=SetupEngineer(self.base)
        drivers=[{"CarIdx":1,"CarClassID":4,"CarNumber":"11",
                  "UserName":"You","UserID":101}]
        results=[{"CarIdx":1,"ClassPosition":2,"Position":5,
                  "LapsComplete":6,"LastTime":89.8,"FastestTime":89.0}]
        sdk={"PlayerCarIdx":1,"DriverInfo":{"DriverUserID":101,
                  "DriverCarIdx":1,"Drivers":drivers},
             "SessionInfo":{"Sessions":[{"SessionType":"Race",
                                         "ResultsPositions":results}]},
             "WeekendInfo":WEEKEND,"SessionNum":0,"SessionTime":300,
             "Lap":7,"LapCompleted":6,"LapDistPct":.38,
             "IsOnTrack":True,"IsOnTrackCar":True,
             "FuelLevel":39.1,"LapLastLapTime":89.8,
             "LapBestLapTime":89.0,"CarIdxLapDistPct":[None,.38,None],
             "CarIdxTrackSurface":[-1,3,-1],
             "CarIdxClassPosition":[0,3,0],
             "CarIdxBestLapTime":[None,89.0,None],
             "CarIdxLastLapTime":[None,89.8,None],
             "CarIdxLapCompleted":[0,6,6],
             "CarIdxLap":[0,7,7],
             "CarIdxOnPitRoad":[False,False,False],
             "SessionTimeRemain":1200}
        source.get=lambda key,default=None:sdk.get(key,default)
        data=source.live_payload(force_driver=True)
        rows={x["carIdx"]:x for x in data["raceDashboard"]["classStandings"]}
        self.assertEqual(rows[1]["classPosition"],3)
        self.assertEqual(rows[1]["positionSource"],"RESULTS_POSITIONS")
        self.assertEqual(rows[2]["classPosition"],1)
        self.assertEqual(rows[2]["positionSource"],"RECOVERED_SDK_SNAPSHOT")
        self.assertIsNone(rows[2]["officialClassPosition"])
        self.assertEqual(rows[2]["presence"],"STALE")
        self.assertEqual(len(source.lap_history),3)
        self.assertTrue(all(x["source"]=="ZRE_RECORDED_RECOVERED" for x in source.lap_history))
        self.assertEqual(data["raceDashboard"]["recoveredFromJournal"]["fromSessionId"],
                         folder.name)
        # Second SDK frame has no double reconstruction or extra laps.
        second=source.live_payload(force_driver=True)
        self.assertEqual(len(source.lap_history),3)
        self.assertEqual(second["raceDashboard"]["classStandings"][0]["positionSource"],
                         "RECOVERED_SDK_SNAPSHOT")

if __name__=="__main__":
    unittest.main()
