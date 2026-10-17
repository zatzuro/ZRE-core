"""2.6.7.4.2: lap 268 -> 272 while spectator SDK Completed+YAML freeze.

Official iRacing SDK docs distinguish CarIdxLap (laps started) from
CarIdxLapCompleted (laps completed). Crossing evidence may exist in the
former even while the latter and SessionInfo YAML remain stale.
Never fabricate lap times or attribute a driver from stale per-car data.
"""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from server.lap_database import LapDatabase, choose_lap_counter


class LiveLapSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = LapDatabase(Path(self.temp.name))
        self.state = {
            "CarIdxLap": [-1] * 16,
            "CarIdxLapCompleted": [-1] * 16,
            "CarIdxLastLapTime": [-1] * 16,
            "CarIdxLapDistPct": [-1.0] * 16,
            "CarIdxTrackSurface": [-1] * 16,
            "CarIdxOnPitRoad": [False] * 16,
            "FuelLevel": 44.0,
        }
        self.state["CarIdxLap"][8] = 269
        self.state["CarIdxLapCompleted"][8] = 268
        self.state["CarIdxLastLapTime"][8] = 93.1
        self.state["CarIdxTrackSurface"][8] = 3
        self.session_clock = 20000
        self.roster = [{"CarIdx": 8, "CarNumber": "18", "UserName": "David",
                        "UserID": 202, "TeamID": 10}]
        self.results = {8: {"LapsComplete": 268, "LastTime": 93.1}}
        self.now = time.time()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def frame(self):
        with patch("server.lap_database.time.time", return_value=self.now):
            return self.db.observe(
                "session-272", self.state.get, self.roster, 8,
                local_driving=False, team_car_number="18",
                results=self.results, consumption=2.7, pace=90,
                rival_idx=None, session_time=self.session_clock)

    def test_started_count_is_lower_bound_one_below_current(self):
        self.assertEqual(choose_lap_counter(268, 273, 268),
                         (272, "STARTED_LAP_DERIVED"))
        self.assertEqual(choose_lap_counter(273, 273, 268),
                         (273, "SDK_COMPLETED"))
        self.assertEqual(choose_lap_counter(268, 273, 272),
                         (272, "RESULTS_COMPLETED"))
        self.assertEqual(choose_lap_counter(-1, -1, None),
                         (None, "SIN_CONTADOR"))

    def test_268_frozen_but_car_started_lap_273_recovers_272(self):
        self.frame()
        self.now += 20
        self.state["CarIdxLap"][8] = 273
        self.state["CarIdxOnPitRoad"][8] = True  # stale pit flag
        payload = self.frame()
        self.assertEqual(payload["sync"]["lastCompleted"], 272)
        self.assertEqual(payload["sync"]["currentStarted"], 273)
        self.assertEqual(payload["sync"]["state"], "ACTIVO")
        self.assertEqual([r["lap"] for r in payload["team"]],
                         [268, 269, 270, 271, 272])
        self.assertEqual([r["source"] for r in payload["team"][1:4]],
                         ["SDK_MISSING"] * 3)
        self.assertTrue(all(r["lap_time"] is None
                            for r in payload["team"][1:]))
        self.assertEqual(payload["team"][-1]["source"],
                         "STARTED_LAP_DERIVED")
        self.assertIsNone(payload["team"][-1]["driver"])
        self.assertEqual(payload["team"][-1]["kind"], "Normal")
        self.assertEqual(self.db._anchors(8), [])

    def test_direct_result_can_backfill_time_on_same_lap(self):
        self.frame()
        self.state["CarIdxLap"][8] = 273
        self.frame()
        self.results[8]["LapsComplete"] = 272
        self.results[8]["LastTime"] = 92.4
        updated = self.frame()
        self.assertEqual(len(updated["team"]), 5)
        self.assertEqual(updated["team"][-1]["lap_time"], 92.4)
        self.assertEqual(updated["team"][-1]["source"],
                         "RESULTS_OBSERVED")
        self.assertEqual(updated["team"][-2]["lap_time"], None)
        self.assertEqual(updated["team"][-3]["lap_time"], None)

    def test_completed_catches_up_without_duplication(self):
        self.frame()
        self.state["CarIdxLap"][8] = 273
        self.frame()
        self.state["CarIdxLapCompleted"][8] = 272
        self.state["CarIdxLastLapTime"][8] = 92.1
        p = self.frame()
        self.assertEqual(len(p["team"]), 5)
        self.assertEqual(p["team"][-1]["lap_time"], 92.1)
        self.assertEqual(p["team"][-1]["source"], "SDK_OBSERVED")

    def test_unchanged_sources_raise_stale_status_not_fake_laps(self):
        self.frame()
        self.now += 245  # greater than 2.5 * 90 seconds
        p = self.frame()
        self.assertEqual(p["sync"]["state"], "DESACTUALIZADO")
        self.assertGreaterEqual(p["sync"]["ageSeconds"], 245)
        self.assertEqual([r["lap"] for r in p["team"]], [268])

    def test_roster_disappears_but_started_counter_still_updates(self):
        self.frame()
        self.roster = []
        self.results = {}
        self.state["CarIdxLap"][8] = 271
        p = self.frame()
        self.assertEqual(p["sync"]["lastCompleted"], 270)
        self.assertEqual(p["team"][-1]["lap"], 270)
        self.assertEqual(p["team"][-1]["driver"], None)
        self.assertEqual(p["team"][-1]["source"],
                         "STARTED_LAP_DERIVED")

    def test_reconnect_resume_and_no_lap_duplication(self):
        self.frame()
        self.state["CarIdxLap"][8] = 273
        self.frame()
        self.db.close()
        self.db = LapDatabase(Path(self.temp.name))
        self.state["CarIdxLap"][8] = 275
        p = self.frame()
        self.assertEqual([r["lap"] for r in p["team"]],
                         [268, 269, 270, 271, 272, 273, 274])
        self.assertEqual(p["team"][-1]["source"],
                         "STARTED_LAP_DERIVED")
        self.assertIsNone(p["team"][-2]["lap_time"])
        p2 = self.frame()
        self.assertEqual(len(p2["team"]), 7)

    def test_distance_crossing_when_both_counters_and_yaml_frozen(self):
        self.state["CarIdxLapDistPct"][8] = .90
        self.frame()
        # Completed=268, Started=269, Results=268 stay frozen throughout.
        # Four independently observed line crossings are four rows.
        for target in (269, 270, 271, 272):
            self.session_clock += 4
            self.state["CarIdxLapDistPct"][8] = .04
            observed = self.frame()
            self.assertEqual(observed["sync"]["lastCompleted"], target)
            self.assertEqual(observed["team"][-1]["source"],
                             "DIST_CROSSING_OBSERVED")
            self.assertIsNone(observed["team"][-1]["lap_time"])
            self.assertIsNone(observed["team"][-1]["driver"])
            self.session_clock += 75
            self.state["CarIdxLapDistPct"][8] = .91
            self.frame()
        self.assertEqual([r["lap"] for r in observed["team"]],
                         [268, 269, 270, 271, 272])
        self.assertEqual(observed["sync"]["currentStarted"], 269)

    def test_distance_crossing_rejects_jumps_and_duplicate_wraps(self):
        self.state["CarIdxLapDistPct"][8] = .92
        self.frame()
        # A replay seek / dropped session clock or >12 second jump is not
        # proof of a crossed finish line.
        self.session_clock += 30
        self.state["CarIdxLapDistPct"][8] = .05
        self.assertEqual(self.frame()["sync"]["lastCompleted"], 268)
        self.session_clock += 70
        self.state["CarIdxLapDistPct"][8] = .90
        self.frame()
        self.session_clock += 3
        self.state["CarIdxLapDistPct"][8] = .05
        self.assertEqual(self.frame()["sync"]["lastCompleted"], 269)
        # A second implausibly quick high->low oscillation is suppressed.
        self.session_clock += 1
        self.state["CarIdxLapDistPct"][8] = .90
        self.frame()
        self.session_clock += 1
        self.state["CarIdxLapDistPct"][8] = .05
        self.assertEqual(self.frame()["sync"]["lastCompleted"], 269)

    def test_distance_crossing_with_no_counters_needs_prior_identity(self):
        self.state["CarIdxLapDistPct"][8] = .95
        self.state["CarIdxLapCompleted"][8] = -1
        self.state["CarIdxLap"][8] = -1
        self.results.clear()
        self.frame()
        self.session_clock += 3
        self.state["CarIdxLapDistPct"][8] = .03
        self.assertEqual(self.frame()["team"], [])

    def test_started_is_not_sufficient_when_absent_or_invalid(self):
        self.state["CarIdxLap"][8] = -1
        self.frame()
        self.state["CarIdxLapCompleted"][8] = 268
        self.results[8]["LapsComplete"] = 268
        p = self.frame()
        self.assertEqual(len(p["team"]), 1)
        self.assertEqual(p["team"][-1]["lap"], 268)


if __name__ == "__main__":
    unittest.main()
