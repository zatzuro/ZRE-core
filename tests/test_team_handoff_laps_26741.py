"""Regression for live team handoff: teammate -> local -> teammate.
The team CAR laps and fuel ledger must continue independently of who drives.
Every telemetry field here is a synthetic SDK fixture, not physical iRacing.
"""
import tempfile
import unittest
from pathlib import Path

from server.team_context import TeamCarContext
from server.lap_database import LapDatabase


class TeamDriverRoundtripTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=LapDatabase(Path(self.tmp.name))
        self.data={
            "CarIdxLapCompleted":[-1]*16,
            "CarIdxLastLapTime":[-1.0]*16,
            "CarIdxOnPitRoad":[False]*16,
            "FuelLevel":35.0,
        }
        self.data["CarIdxLapCompleted"][8]=41
        self.data["CarIdxLastLapTime"][8]=93.0
        self.data["CarIdxOnPitRoad"][8]=True
        self.drivers=[
            {"CarIdx":8,"CarNumber":"18","TeamID":10,"UserID":202,
             "UserName":"David","CarClassID":1},
            {"CarIdx":9,"CarNumber":"27","TeamID":11,"UserID":303,
             "UserName":"Rival","CarClassID":1}
        ]
        self.context=None
        self.results={8:{"CarIdx":8,"LapsComplete":41,"LastTime":93.0}}
        self.local_id=101

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def sample(self,on_track=False,locally=False,driver_idx=8):
        info={"DriverCarIdx":driver_idx,"DriverUserID":self.local_id,
              "Drivers":self.drivers}
        prior=self.context
        self.context=TeamCarContext.resolve(
            info,8,on_track,
            last_team_idx=prior.car_idx if prior else 8,
            last_team_id=prior.team_id if prior else 10,
            local_user_id=prior.local_user_id if prior else self.local_id,
            local_driver_name=prior.local_driver_name if prior else "Santiago",
            last_car_number=prior.car_number if prior else "18",
            local_car_active=locally)
        return self.db.observe(
            "official-session-123",self.data.get,self.drivers,
            self.context.car_idx,local_driving=self.context.local_driving,
            team_car_number=self.context.car_number,
            results=self.results,consumption=2.8,
            tank=60,rival_idx=9,session_time=900)

    def test_round_trip_spotter_driver_spotter_results_progress(self):
        one=self.sample()
        self.assertFalse(self.context.local_driving)
        self.assertEqual(one["team"][-1]["lap"],41)
        self.assertEqual(one["team"][-1]["driver"],"David")
        # We enter the car and complete lap 42 on our own SDK.
        self.drivers[0]=dict(self.drivers[0],UserID=101,UserName="Santiago")
        self.data["CarIdxLapCompleted"][8]=42
        self.data["CarIdxLastLapTime"][8]=91.7
        self.data["CarIdxOnPitRoad"][8]=False
        self.results[8].update(LapsComplete=42,LastTime=91.7)
        second=self.sample(on_track=True,locally=True)
        self.assertTrue(self.context.local_driving)
        self.assertEqual(second["team"][-1]["driver"],"Santiago")
        self.assertEqual(second["team"][-1]["fuelSource"],"REAL_LOCAL")
        # David takes the car back; the local car-index arrays are frozen
        # at lap 42 and the old pit flag True, while ResultsPositions moves.
        self.drivers[0]=dict(self.drivers[0],UserID=202,UserName="David")
        self.data["CarIdxOnPitRoad"][8]=True
        self.results[8].update(LapsComplete=43,LastTime=92.9)
        third=self.sample()
        self.assertFalse(self.context.local_driving)
        self.assertEqual(self.context.car_idx,8)
        self.assertEqual([x["lap"] for x in third["team"]],[41,42,43])
        self.assertEqual(third["team"][-1]["source"],"RESULTS_OBSERVED")
        self.assertEqual(third["team"][-1]["driver"],"David")
        self.assertEqual(third["team"][-1]["kind"],"Normal")
        self.assertNotEqual(third["team"][-1]["fuelSource"],"REAL_LOCAL")
        self.results[8].update(LapsComplete=44,LastTime=93.1)
        fourth=self.sample()
        self.assertEqual([x["lap"] for x in fourth["team"]],[41,42,43,44])
        self.assertEqual([round(x["lap_time"],1) for x in fourth["team"]],[93.0,91.7,92.9,93.1])

    def test_roster_missing_after_swap_preserves_team_car(self):
        self.sample()
        self.drivers[0]=dict(self.drivers[0],UserID=101,UserName="Santiago")
        self.data["CarIdxLapCompleted"][8]=42
        self.results[8].update(LapsComplete=42,LastTime=91.7)
        self.sample(on_track=True,locally=True)
        # Some client frames temporarily drop the team's DriverInfo row.
        self.drivers=self.drivers[1:]
        self.results[8].update(LapsComplete=43,LastTime=93.0)
        recovered=self.sample()
        self.assertEqual(self.context.source,"previous-unconfirmed")
        self.assertEqual(self.context.auto_mode,"spotter")
        self.assertIsNone(self.context.current_driver)
        self.assertEqual(self.context.car_idx,8)
        self.assertEqual(recovered["team"][-1]["lap"],43)
        self.assertIsNone(recovered["team"][-1]["driver"])
        self.assertEqual(recovered["team"][-1]["car_number"],"18")
        self.drivers.insert(0,{"CarIdx":8,"CarNumber":"18","TeamID":10,
                               "UserID":202,"UserName":"David","CarClassID":1})
        self.results[8].update(LapsComplete=44,LastTime=93.1)
        restored=self.sample()
        self.assertEqual(restored["team"][-1]["driver"],"David")
        self.assertEqual(self.context.current_driver,"David")

    def test_sdk_unavailable_multiple_laps_missing_no_fake_times(self):
        self.sample()
        self.results[8].update(LapsComplete=45,LastTime=94.5)
        self.data["CarIdxLapCompleted"][8]=-1
        observed=self.sample()
        self.assertEqual([x["lap"] for x in observed["team"]],[41,42,43,44,45])
        self.assertEqual([x["lap_time"] for x in observed["team"][1:4]],[None]*3)
        self.assertEqual(observed["team"][-1]["lap_time"],94.5)
        self.assertTrue(all(x["source"]=="SDK_MISSING" for x in observed["team"][1:4]))

    def test_results_may_be_behind_and_must_not_reduce_sdk_counter(self):
        self.sample()
        self.data["CarIdxLapCompleted"][8]=42
        self.data["CarIdxLastLapTime"][8]=91.4
        self.results[8].update(LapsComplete=40,LastTime=84.0)
        observed=self.sample()
        self.assertEqual(observed["team"][-1]["lap"],42)
        self.assertEqual(observed["team"][-1]["lap_time"],91.4)
        self.assertEqual(observed["team"][-1]["source"],"SDK_OBSERVED")

    def test_no_session_results_and_no_roster_does_not_invent_laps(self):
        self.sample()
        self.drivers=self.drivers[1:]
        self.data["CarIdxLapCompleted"][8]=-1
        self.results={}
        again=self.sample()
        self.assertEqual(len(again["team"]),1)
        self.assertEqual(again["team"][0]["lap"],41)

    def test_restart_mid_handoff_deduplicates_and_continues(self):
        self.sample()
        self.db.close()
        self.db=LapDatabase(Path(self.tmp.name))
        self.drivers[0]=dict(self.drivers[0],UserID=101,UserName="Santiago")
        self.data["CarIdxLapCompleted"][8]=42
        self.results[8].update(LapsComplete=42,LastTime=92.1)
        self.sample(on_track=True,locally=True)
        self.drivers[0]=dict(self.drivers[0],UserID=202,UserName="David")
        self.results[8].update(LapsComplete=43,LastTime=94.2)
        row=self.sample()
        self.assertEqual(len(row["team"]),3)
        self.assertEqual(row["team"][-1]["lap"],43)
        repeat=self.sample()
        self.assertEqual(len(repeat["team"]),3)
        self.assertEqual(self.db.db.execute(
            "SELECT COUNT(*) FROM laps WHERE race='official-session-123' AND car_idx=8").fetchone()[0],3)


if __name__=="__main__":
    unittest.main()
