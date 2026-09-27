import inspect
import tempfile
import unittest
from pathlib import Path

from server import iracing_bridge as bridge
from server.race_state import RaceIdentity, session_fuel_limit
from server.strategy_runtime import (
    RacePlanRuntime, read_iracing_auto_fuel_margin, leader_from_results,
)


class RacePlanRuntimeTests(unittest.TestCase):
    def identity(self, subsession=2, session_num=0):
        return RaceIdentity(1, subsession, 100, "GP", 99, "18", 123, session_num)

    def frame(self, runtime, identity=None, **overrides):
        data = dict(
            identity=identity or self.identity(),
            session_type="Race",
            remaining_seconds=3600,
            session_total_seconds=3600,
            current_lap=10,
            completed_laps=9,
            own_pace_seconds=100.0,
            leader_lap=10,
            leader_pace_seconds=99.0,
            laps_remaining=None,
            current_driver="Santiago",
            current_fuel_liters=50.0,
            fuel_source="REAL LOCAL",
            physical_tank_liters=100.0,
            max_fuel_pct=1.0,
            on_pit_road=False,
            session_flags=0x4,
            pit_loss_seconds=30.0,
            mandatory_stops_remaining=0,
            require_tire_change=False,
            min_drivers=1,
            max_drivers=4,
            session_time=1000.0,
            last_lap_time=100.0,
            auto_fuel_enabled=True,
            auto_fuel_active=True,
            pit_sv_fuel=48.0,
        )
        data.update(overrides)
        return runtime.observe_frame(**data)

    def test_app_ini_margin_is_read_but_not_claimed_when_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            ini = Path(folder) / "app.ini"
            ini.write_text("[Pit Service]\nautoFuelDefaultMarginLaps=2\n", encoding="utf-8")
            self.assertEqual(read_iracing_auto_fuel_margin([ini]), (2.0, "IRACING_APP_INI_DEFAULT"))
            self.assertEqual(read_iracing_auto_fuel_margin([Path(folder)/"missing.ini"]), (0.0, "UNKNOWN"))

    def test_estimated_team_fuel_never_teaches_consumption(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = RacePlanRuntime(folder, margin_paths=[])
            self.frame(runtime, completed_laps=9, current_fuel_liters=50, fuel_source="ESTIMADO")
            self.frame(runtime, completed_laps=10, current_lap=11, current_fuel_liters=47.5,
                       fuel_source="ESTIMADO", session_time=1100, last_lap_time=100)
            self.assertEqual(runtime.fuel_model.current, [])
            self.assertIsNone(runtime.payload()["fuelModel"]["strategy_lpl"])

    def test_sdk_observed_team_fuel_can_teach_consumption_without_local_driving(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = RacePlanRuntime(folder, margin_paths=[])
            self.frame(runtime, completed_laps=9, current_fuel_liters=50, fuel_source="SDK OBSERVADO")
            payload = self.frame(runtime, completed_laps=10, current_lap=11, current_fuel_liters=47.5,
                                 fuel_source="SDK OBSERVADO", session_time=1100, last_lap_time=100)
            self.assertEqual(len(runtime.fuel_model.current), 1)
            self.assertAlmostEqual(runtime.fuel_model.current[0].liters, 2.5)
            self.assertEqual(payload["raceState"]["fuel_source"], "SDK OBSERVADO")
            self.assertEqual(payload["raceState"]["fuel_confidence"], "MEDIUM")

    def test_driver_swap_does_not_reset_race_plan_identity_or_history(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = RacePlanRuntime(folder, margin_paths=[])
            identity = self.identity()
            self.frame(runtime, identity=identity, current_driver="Santiago", completed_laps=9,
                       current_fuel_liters=50)
            self.frame(runtime, identity=identity, current_driver="David", completed_laps=10,
                       current_lap=11, current_fuel_liters=47.5, session_time=1100)
            self.assertEqual(runtime.identity.key, identity.key)
            self.assertEqual(runtime.last_driver, "David")
            self.assertEqual(len(runtime.fuel_model.current), 1)

    def test_same_car_track_layout_history_seeds_next_race_not_same_race_twice(self):
        with tempfile.TemporaryDirectory() as folder:
            first = RacePlanRuntime(folder, margin_paths=[])
            race_a = self.identity(subsession=2)
            self.frame(first, identity=race_a, completed_laps=9, current_fuel_liters=50)
            self.frame(first, identity=race_a, completed_laps=10, current_lap=11,
                       current_fuel_liters=47.5, session_time=1100)
            self.assertEqual(len(first.fuel_model.current), 1)

            reopened = RacePlanRuntime(folder, margin_paths=[])
            self.frame(reopened, identity=race_a, completed_laps=10, current_lap=11,
                       current_fuel_liters=47.5, session_time=1100)
            self.assertEqual(len(reopened.fuel_model.current), 1)
            self.assertEqual(len(reopened.fuel_model.historical), 0)

            next_race = RacePlanRuntime(folder, margin_paths=[])
            race_b = self.identity(subsession=3)
            self.frame(next_race, identity=race_b, completed_laps=0, current_lap=1,
                       current_fuel_liters=100, session_time=0)
            self.assertEqual(len(next_race.fuel_model.current), 0)
            self.assertEqual(len(next_race.fuel_model.historical), 1)

    def test_restart_preserves_original_initial_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = RacePlanRuntime(folder, margin_paths=[])
            identity = self.identity()
            self.frame(runtime, identity=identity, completed_laps=0, current_lap=1, current_fuel_liters=100)
            self.frame(runtime, identity=identity, completed_laps=1, current_lap=2,
                       current_fuel_liters=97.5, session_time=1100, remaining_seconds=3500)
            before = runtime.payload()["initialPlan"]
            self.assertIsNotNone(before)

            reopened = RacePlanRuntime(folder, margin_paths=[])
            after = self.frame(reopened, identity=identity, completed_laps=1, current_lap=2,
                               current_fuel_liters=97.5, session_time=1100, remaining_seconds=3400)
            self.assertEqual(after["initialPlan"], before)

    def test_pit_entry_is_counted_once_and_marked_unplanned_when_outside_window(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = RacePlanRuntime(folder, margin_paths=[])
            identity = self.identity()
            self.frame(runtime, identity=identity, completed_laps=0, current_lap=1, current_fuel_liters=100)
            self.frame(runtime, identity=identity, completed_laps=1, current_lap=2,
                       current_fuel_liters=97.5, session_time=1100)
            self.frame(runtime, identity=identity, completed_laps=1, current_lap=2,
                       current_fuel_liters=97.0, on_pit_road=True, session_time=1110)
            self.frame(runtime, identity=identity, completed_laps=1, current_lap=2,
                       current_fuel_liters=97.0, on_pit_road=True, session_time=1115)
            self.assertEqual(runtime.stops_completed, 1)
            self.assertEqual(len(runtime.stop_history), 1)
            self.assertIn(runtime.stop_history[0]["status"], ("PLANNED", "UNPLANNED STOP"))

    def test_green_pace_uses_median_and_ignores_one_slow_lap(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = RacePlanRuntime(folder, margin_paths=[])
            identity = self.identity()
            self.frame(runtime, identity=identity, completed_laps=0, current_lap=1, current_fuel_liters=100)
            fuel = 100
            for lap, pace in enumerate((100, 101, 99, 160, 100), 1):
                fuel -= 2.5
                self.frame(runtime, identity=identity, completed_laps=lap, current_lap=lap+1,
                           current_fuel_liters=fuel, last_lap_time=pace, own_pace_seconds=pace,
                           session_time=1000+lap*pace)
            self.assertEqual(runtime.last_state.own_pace_seconds, 100.0)

    def test_zero_or_missing_max_fuel_pct_never_creates_zero_capacity(self):
        self.assertEqual(session_fuel_limit(110, 0), 110)
        self.assertEqual(session_fuel_limit(110, None), 110)

    def test_leader_resolution_uses_position_one_and_live_last_time(self):
        results = {
            4: {"CarIdx":4, "Position":2, "LastTime":101},
            8: {"CarIdx":8, "Position":1, "LastTime":100},
        }
        laps = [None]*9; laps[8] = 25
        last = [None]*9; last[8] = 99.5
        idx, lap, pace = leader_from_results(results, laps, last)
        self.assertEqual((idx, lap, pace), (8, 25, 99.5))

    def test_bridge_exposes_vnext_without_replacing_existing_strategy_contracts(self):
        source = inspect.getsource(bridge.DashboardSource)
        self.assertIn("racePlanVNext", source)
        self.assertIn("payload[\"strategy\"] = self.strategy_payload(fuel)", source)
        self.assertIn("payload[\"enduranceStrategy\"]", source)
        self.assertIn("'racePlan':plan,'racePlanVNext':race_plan_vnext", source)

    def test_simulate_stop_does_not_mutate_plan_target_or_hysteresis(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = RacePlanRuntime(folder, margin_paths=[])
            identity = self.identity()
            self.frame(runtime, identity=identity, completed_laps=0, current_lap=1, current_fuel_liters=100)
            fuel = 100
            for lap in range(1, 5):
                fuel -= 2.5
                self.frame(runtime, identity=identity, completed_laps=lap, current_lap=lap+1,
                           current_fuel_liters=fuel, session_time=1000+lap*100,
                           remaining_seconds=3600-lap*100, last_lap_time=100)
            before = runtime.engine.snapshot()
            target_before = runtime.engine.committed_target_lap
            sim = runtime.simulate_stop()
            after = runtime.engine.snapshot()
            self.assertTrue(sim["valid"])
            self.assertEqual(before, after)
            self.assertEqual(runtime.engine.committed_target_lap, target_before)
            self.assertIn("preservesMinimum", sim)
            self.assertEqual(runtime.payload()["simulation"], sim)


    def test_runtime_has_no_sdk_reader_timer_or_thread(self):
        import server.strategy_runtime as runtime_module
        source = inspect.getsource(runtime_module.RacePlanRuntime)
        self.assertNotIn("IRSDK(", source)
        self.assertNotIn("threading", source)
        self.assertNotIn("Timer(", source)


if __name__ == "__main__":
    unittest.main()
