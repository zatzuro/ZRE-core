"""Cross-mode durability, privacy, retention and fuel confidence regression matrix."""
import math
import tempfile
import time
import unittest
from pathlib import Path

from server.lap_database import LapDatabase


class LapDatabase2674Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = LapDatabase(Path(self.tmp.name))
        self.sdk = {
            "CarIdxLapCompleted": [30, 30, 30],
            "CarIdxLastLapTime": [91.1, 91.3, 92.1],
            "CarIdxOnPitRoad": [False, False, False],
            "FuelLevel": 25.0,
        }
        self.drivers = [
            {"CarIdx": 0, "CarNumber": "18", "UserName": "Santiago"},
            {"CarIdx": 1, "CarNumber": "27", "UserName": "Rival 1"},
            {"CarIdx": 2, "CarNumber": "77", "UserName": "Rival 2"},
        ]

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def frame(self, race="R-2026", driver=True, rival=1):
        return self.db.observe(
            race, self.sdk.get, self.drivers, 0, local_driving=driver,
            tank=60, consumption=2.5, pace=92.1,
            rival_idx=rival, session_time=600)

    def test_7day_retention_and_live_session_preserved(self):
        self.frame(race="old")
        self.db.db.execute(
            "UPDATE race_meta SET last_seen_utc=? WHERE race='old'",
            (time.time()-9*86400,))
        self.frame(race="live")
        self.db.db.execute(
            "UPDATE race_meta SET last_seen_utc=? WHERE race='live'",
            (time.time()-9*86400,))
        self.assertEqual(self.db.cleanup_expired(), 1)
        self.assertFalse(self.db.db.execute("SELECT 1 FROM laps WHERE race='old'").fetchone())
        self.assertTrue(self.db.db.execute("SELECT 1 FROM laps WHERE race='live'").fetchone())

    def test_protected_race_not_removed(self):
        self.frame(race="protected")
        self.db.protect("protected", True)
        self.db.db.execute("UPDATE race_meta SET last_seen_utc=? WHERE race=?",
                           (time.time()-30*86400, "protected"))
        self.frame(race="new")
        self.assertEqual(self.db.cleanup_expired(), 0)
        self.assertTrue(self.db.db.execute(
            "SELECT 1 FROM laps WHERE race='protected'").fetchone())

    def test_history_survives_restart_and_driver_handoff(self):
        self.frame()
        self.sdk["CarIdxLapCompleted"] = [31, 31, 31]
        self.sdk["CarIdxLastLapTime"] = [91.2, 92.0, 92.4]
        self.sdk["FuelLevel"] = 22.4
        self.frame()
        self.db.close()
        self.db = LapDatabase(Path(self.tmp.name))
        self.drivers[0]["UserName"] = "Herney"
        self.drivers[1]["UserName"] = "Rival nuevo"
        self.sdk["CarIdxLapCompleted"] = [32, 32, 32]
        self.sdk["CarIdxLastLapTime"] = [91.7, 91.9, 91.9]
        self.sdk["FuelLevel"] = 12.0  # spectator value may be unrelated
        result = self.frame(driver=False)
        self.assertEqual([r["lap"] for r in result["team"]], [30,31,32])
        self.assertEqual([r["driver"] for r in result["team"]],
                         ["Santiago","Santiago","Herney"])
        self.assertEqual(result["team"][-1]["fuelSource"], "ESTIMADO")
        self.assertEqual(len(result["rival"]), 3)

    def test_switch_rival_and_missing_lap_times_persist(self):
        self.frame()
        self.sdk["CarIdxLapCompleted"]=[31,33,33]
        self.sdk["CarIdxLastLapTime"]=[92.0,91.9,90.8]
        self.frame()
        x=self.db.snapshot(0,1,60,2.5,92,None)
        y=self.db.snapshot(0,2,60,2.5,92,None)
        self.assertEqual(x["rivalCarIdx"],1)
        self.assertEqual(y["rivalCarIdx"],2)
        self.assertTrue(any(r["source"]=="SDK_MISSING" and r["lap_time"] is None
                            for r in x["rival"]))
        self.assertEqual(len(self.db._rows(1)),len(self.db._rows(2)))

    def test_manual_is_authoritative_and_can_be_corrected(self):
        self.frame()
        self.assertIsNone(self.db.edit_fuel(30,24.8,0,60))
        self.assertIsNone(self.db.edit_fuel(30,24.9,0,60))
        self.db._fuel_event(0,30,30.0,"REAL_LOCAL")
        self.assertEqual(self.db._anchors(0)[0]["remaining"],24.9)
        self.assertEqual(self.db._anchors(0)[0]["source"],"MANUAL")
        self.assertEqual(self.db.snapshot(0,1,60,2.5,92,None)["lastManualLap"],30)

    def test_consumption_last_10_and_no_refuel_training(self):
        rows=[{"lap":n,"source":"SDK_OBSERVED","kind":"Normal"} for n in range(1,23)]
        anchors=[{"lap":n,"remaining":(90-2*n if n<=11 else 68-3*(n-11))}
                 for n in range(1,23)]
        model,evidence=self.db._models(rows,anchors,None)
        self.assertEqual(model["Normal"],3.0)
        self.assertEqual(len(evidence["Normal"]),21)
        rows[16]["kind"]="Entrada box"
        model,evidence=self.db._models(rows,anchors,None)
        self.assertEqual(len(evidence["Entrada box"]),1)
        self.assertLess(len(evidence["Normal"]),21)
        anchors[20]["remaining"]=100.0
        model,evidence=self.db._models(rows,anchors,None)
        self.assertTrue(all(v["rate"]>0 for v in evidence["Normal"]))

    def test_invalid_manual_and_fuel_never_leaks_between_cars(self):
        self.frame()
        for entry in ("nan","inf",-2,99,301):
            self.assertIsNotNone(self.db.edit_fuel(30,entry,0,60))
        self.assertIsNotNone(self.db.edit_fuel(30,20,1,60))
        self.assertIsNotNone(self.db.edit_fuel(999,20,0,60))
        self.assertEqual(len(self.db._anchors(1)),0)

    def test_absurd_fuel_cannot_pollute_record_without_tank_capacity(self):
        self.sdk["FuelLevel"] = 99999
        self.frame()
        self.assertEqual(self.db._anchors(0), [])

    def test_database_failure_does_not_block_other_zre_screens(self):
        import sqlite3
        from unittest.mock import patch
        from server import iracing_bridge
        from server.lap_database import UnavailableLapDatabase
        with patch.object(iracing_bridge, "LapDatabase",
                          side_effect=sqlite3.OperationalError("disk locked")):
            source = iracing_bridge.DashboardSource(force_demo=True)
        self.assertIsInstance(source.lap_database, UnavailableLapDatabase)
        self.assertTrue(source.sample()["demo"])
        self.assertFalse(source.lap_database.observe()["available"])
        self.assertIn("almacenamiento", source.lap_database.edit_fuel(1,20,0))
        source.lap_database.close()

    def test_unknown_pit_refuel_is_not_guessed(self):
        self.frame()
        self.assertIsNone(self.db.edit_fuel(30,6.0,0,60))
        result=self.db.snapshot(0,1,60,2.5,92,None)
        kind=[r["kind"] for r in result["projected"]]
        self.assertIn("Entrada box",kind)
        self.assertIn("Salida box",kind)
        outgoing=next(r for r in result["projected"] if r["kind"]=="Salida box")
        self.assertIsNone(outgoing["remaining"])


if __name__ == "__main__":
    unittest.main()
