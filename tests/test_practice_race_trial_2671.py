"""P0 practice Race simulation: only local fuel and an explicit user target."""
import unittest
from server.iracing_bridge import DashboardSource

class PracticeRaceTrialTests(unittest.TestCase):
    def setUp(self):
        self.source=DashboardSource(force_demo=True)
        self.source.get=lambda key,default=None:{
            "DriverInfo":{"DriverCarFuelMaxLtr":100.0},
            "SessionTimeRemain":8000}.get(key,default)
        self.source.lap_history=[
            {"lap":i,"time":85.2,"fuelUse":v,"valid":True,
             "caution":False,"onPitRoad":False}
            for i,v in enumerate((3.12,3.22,3.18,3.20),1)]
        self.source.lap_history.extend([
            {"lap":5,"time":180,"fuelUse":10,"valid":False,"caution":False,"onPitRoad":True},
            {"lap":6,"time":100,"fuelUse":1,"valid":True,"caution":True,"onPitRoad":False},
        ])

    def test_no_target_retains_real_fuel_autonomy_without_fake_plan(self):
        trial=self.source.practice_race_preview(20.0,9,8,False,85.2)
        self.assertFalse(trial["available"])
        self.assertEqual(trial["source"],"PRACTICE_LOCAL_LAP_HISTORY")
        self.assertEqual(trial["fuelModel"]["green_samples"],4)
        self.assertAlmostEqual(trial["fuelModel"]["observed_lpl"],3.18,delta=.02)
        self.assertAlmostEqual(trial["autonomyLaps"],20/3.18,delta=.1)
        self.assertIn("DEFINE OBJETIVO",trial["reason"])

    def test_configured_ensayo_produces_true_box_countdown(self):
        self.source.apply_strategy_settings({"practiceRaceConfigured":True,
            "manualRaceSeconds":3600,"tankCapacityLiters":100.0,
            "baseStintLaps":37,"extendedStintLaps":38})
        normal=self.source.practice_race_preview(30,10,9,False,85.2)
        self.assertTrue(normal["available"])
        self.assertEqual(normal["mode"],"ENSAYO")
        self.assertTrue(normal["currentPlan"]["available"])
        near=self.source.practice_race_preview(8,10,9,False,85.2)
        self.assertEqual(near["currentPlan"]["window"]["state"],"BOX NEXT LAP")
        self.assertEqual(near["currentPlan"]["window"]["target"],11)
        urgent=self.source.practice_race_preview(4,10,9,False,85.2)
        self.assertEqual(urgent["currentPlan"]["window"]["state"],"BOX THIS LAP")
        pit=self.source.practice_race_preview(4,10,9,True,85.2)
        self.assertEqual(pit["currentPlan"]["window"]["state"],"IN PIT ROAD")
        self.assertEqual(self.source.get("SessionTimeRemain"),8000)
        self.assertEqual(normal["configuredHorizonSeconds"],3600)

    def test_no_fuel_samples_means_no_fake_consumption_or_box(self):
        self.source.apply_strategy_settings({"practiceRaceConfigured":True,
            "manualRaceSeconds":3600,"tankCapacityLiters":100.0})
        self.source.lap_history=[]
        trial=self.source.practice_race_preview(36,10,9,False,85.2)
        self.assertIsNone(trial["fuelModel"]["observed_lpl"])
        self.assertFalse(trial["available"])
        self.assertIsNone(trial["autonomyLaps"])

    def test_changing_view_does_not_reset_user_target(self):
        self.source.apply_strategy_settings({"practiceRaceConfigured":True,
            "manualRaceSeconds":3600,"tankCapacityLiters":100.0})
        first=self.source.practice_race_preview(8,10,9,False,85.2)
        second=self.source.practice_race_preview(8,10,9,False,85.2)
        self.assertEqual(first["currentPlan"],second["currentPlan"])
        self.assertTrue(self.source.practice_race_configured)

if __name__=="__main__":unittest.main()
