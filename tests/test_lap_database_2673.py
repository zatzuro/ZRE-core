"""Regression coverage for the integrated team/rival lap ledger and fuel projection."""
import tempfile
import unittest
from pathlib import Path

from server.lap_database import LapDatabase


class LapDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = LapDatabase(Path(self.directory.name))
        self.values = {
            "CarIdxLapCompleted": [10, 10],
            "CarIdxLastLapTime": [92.1, 92.8],
            "CarIdxOnPitRoad": [False, False],
            "FuelLevel": 30.0,
        }
        self.drivers = [
            {"CarIdx": 0, "CarNumber": "18", "UserName": "Santiago"},
            {"CarIdx": 1, "CarNumber": "27", "UserName": "Rival"},
        ]

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def observe(self, driving=True, plan=None):
        return self.db.observe(
            "session-777", self.values.get, self.drivers, team_idx=0,
            local_driving=driving, tank=60, consumption=2.8,
            pace=92.0, plan=plan, rival_idx=1, session_time=120)

    def test_two_cars_single_table_and_no_duplicate_on_repeated_frame(self):
        self.observe()
        self.observe()
        self.assertEqual([r["lap"] for r in self.db._rows(0)], [10])
        self.assertEqual([r["lap"] for r in self.db._rows(1)], [10])
        self.assertEqual(self.db._rows(1)[0]["driver"], "Rival")
        self.values["CarIdxLapCompleted"] = [11, 11]
        self.values["CarIdxLastLapTime"] = [92.2, 92.9]
        self.values["FuelLevel"] = 27.2
        state = self.observe()
        self.assertEqual(len(state["team"]), 2)
        self.assertEqual(len(state["rival"]), 2)
        self.assertEqual(state["fuelEvidenceCount"]["Normal"], 1)
        self.assertAlmostEqual(state["averages"]["Normal"], 2.8)
        self.assertEqual(state["team"][1]["fuelSource"], "REAL_LOCAL")

    def test_manual_fuel_correction_and_recovery(self):
        self.observe()
        self.values["CarIdxLapCompleted"] = [11, 11]
        self.observe(driving=False)
        self.assertIsNone(self.db.edit_fuel(11, 27.4, 0, tank=60))
        report = self.db.snapshot(0, 1, 60, 2.8, 92, None)
        self.assertEqual(report["team"][-1]["fuelSource"], "MANUAL")
        self.assertAlmostEqual(report["averages"]["Normal"], 2.6)
        self.assertTrue(report["projected"])
        self.db.close()
        self.db = LapDatabase(Path(self.directory.name))
        self.db.race = "session-777"
        self.db.team_idx = 0
        persisted = self.db.snapshot(0, 1, 60, 2.8, 92, None)
        self.assertAlmostEqual(persisted["team"][-1]["remaining"], 27.4)

    def test_spotter_never_saves_untrusted_remote_fuel(self):
        self.observe(driving=False)
        self.assertEqual(self.db._anchors(0), [])
        report = self.db.snapshot(0, 1, 60, 2.8, 92, None)
        self.assertIsNone(report["team"][-1]["remaining"])

    def test_pit_types_and_no_training_across_refueling(self):
        self.observe()
        self.values["CarIdxOnPitRoad"] = [True, False]
        self.values["CarIdxLapCompleted"] = [11, 11]
        self.values["FuelLevel"] = 27.5
        self.observe()
        self.values["CarIdxOnPitRoad"] = [False, False]
        self.values["CarIdxLapCompleted"] = [12, 12]
        self.values["FuelLevel"] = 58.0
        self.observe()
        history = self.db._rows(0)
        self.assertEqual(history[1]["kind"], "Entrada box")
        self.assertEqual(history[2]["kind"], "Salida box")
        self.assertEqual(self.db.snapshot(0, 1, 60, 2.8, 92, None)["fuelEvidenceCount"]["Normal"], 0)

    def test_unknown_refuel_never_assumes_full_tank(self):
        self.observe()
        self.assertIsNone(self.db.edit_fuel(10, 5.0, 0, 60))
        result = self.db.snapshot(0, 1, 60, 2.8, 92, None)
        entries = [r for r in result["projected"] if r["kind"] == "Entrada box"]
        exits = [r for r in result["projected"] if r["kind"] == "Salida box"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(exits), 1)
        self.assertIsNone(exits[0]["remaining"])

    def test_plan_fill_supports_subsequent_stint(self):
        self.observe()
        self.db.edit_fuel(10, 8.0, 0, 60)
        plan = {"stops": [{"lap": 12, "fuelAction": "fill", "liters": 52}]}
        result = self.db.snapshot(0, 1, 60, 2.8, 92, plan)
        out = next(r for r in result["projected"] if r["kind"] == "Salida box")
        self.assertGreater(out["remaining"], 50)
        self.assertTrue(any(r["lap"] > out["lap"] for r in result["projected"]))

    def test_lap_counter_jumps_create_unknown_times(self):
        self.observe()
        self.values["CarIdxLapCompleted"] = [13, 13]
        self.values["CarIdxLastLapTime"] = [92.4, 93.1]
        self.observe(driving=False)
        laps = self.db._rows(1)
        self.assertEqual([v["lap"] for v in laps], [10, 11, 12, 13])
        self.assertIsNone(laps[1]["lap_time"])
        self.assertIsNone(laps[2]["lap_time"])
        self.assertEqual(laps[3]["lap_time"], 93.1)

    def test_reject_invalid_and_wrong_car_manual_values(self):
        self.observe()
        self.assertIsNotNone(self.db.edit_fuel(10, -2, 0, 60))
        self.assertIsNotNone(self.db.edit_fuel(20, 3, 0, 60))
        self.assertIsNotNone(self.db.edit_fuel(10, 90, 0, 60))
        self.assertIsNotNone(self.db.edit_fuel(10, 4, 1, 60))
        self.assertEqual(self.db._anchors(0)[0]["source"], "REAL_LOCAL")


if __name__ == "__main__":
    unittest.main()
