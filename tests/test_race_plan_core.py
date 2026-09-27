import json
import tempfile
import unittest
from pathlib import Path

from server.fuel_model import (
    FuelLapSample, FuelModel, GREEN_FULL, OUT_LAP, IN_LAP, PIT_LAP, CAUTION,
    ANOMALO_EXPLICADO, classify_fuel_lap,
)
from server.pit_stop_engine import (
    PitRulesProfile, PitServiceRequest, PitLearningModel, ObservedPitStop,
    SIMULTANEOUS, SEQUENTIAL, UNKNOWN, estimate_pit_stop,
)
from server.race_state import RaceIdentity, RaceState, session_fuel_limit
from server.strategy_engine import (
    RacePlanInputs, calculate_race_plan, simulate_stop_lap,
    StopCountStabilizer, RacePlanEngine,
)
from server.strategy_store import StrategyStore


class RacePlanCoreTests(unittest.TestCase):
    def inputs(self, **overrides):
        base = dict(
            remaining_time_seconds=36000,
            current_lap=0,
            own_pace_seconds=82.0,
            current_fuel_liters=99.0,
            fuel_strategy_lpl=2.43,
            session_fuel_limit_liters=99.0,
            pit_loss_seconds=58.7,
            margin_laps=2,
            mandatory_stops_remaining=0,
            laps_remaining=None,
            leader_lap=0,
            leader_pace_seconds=82.0,
            stops_completed=0,
            fuel_confidence="HIGH",
        )
        base.update(overrides)
        return RacePlanInputs(**base)

    def test_A_40_minute_race_uses_same_engine(self):
        plan = calculate_race_plan(self.inputs(
            remaining_time_seconds=2400, own_pace_seconds=120,
            leader_pace_seconds=120, current_fuel_liters=55,
            session_fuel_limit_liters=55, fuel_strategy_lpl=3.76,
            pit_loss_seconds=35,
        ))
        self.assertTrue(plan.available)
        self.assertEqual(plan.minimum_stops, 1)
        self.assertIsNotNone(plan.window)

    def test_B_10_hour_endurance_finds_ten_stops_without_manual_target(self):
        plan = calculate_race_plan(self.inputs())
        self.assertTrue(plan.available)
        self.assertEqual(plan.minimum_stops, 10)
        self.assertEqual(plan.stints_remaining, 11)
        self.assertEqual(len(plan.stops), 10)

    def test_C_D_E_autonomy_improvement_can_reduce_stops(self):
        conservative = calculate_race_plan(self.inputs(fuel_strategy_lpl=2.67))
        improved = calculate_race_plan(self.inputs(fuel_strategy_lpl=2.43))
        long_stint = calculate_race_plan(self.inputs(
            current_fuel_liters=106, session_fuel_limit_liters=106,
            fuel_strategy_lpl=2.5,
        ))
        self.assertGreaterEqual(conservative.minimum_stops, improved.minimum_stops)
        self.assertEqual(long_stint.future_stint_capacity_laps, 42)

    def test_F_G_hysteresis_removes_and_recovers_stop(self):
        h = StopCountStabilizer(initial=11, removal_confirmations=3, addition_confirmations=2)
        self.assertEqual(h.update(10, confidence="HIGH", safety_margin_laps=1.2), (11, "STOP REMOVAL POSSIBLE"))
        self.assertEqual(h.update(10, confidence="HIGH", safety_margin_laps=1.2), (11, "STOP REMOVAL POSSIBLE"))
        self.assertEqual(h.update(10, confidence="HIGH", safety_margin_laps=1.2), (10, "STOP REMOVAL CONFIRMED"))
        self.assertEqual(h.update(11, confidence="HIGH", safety_margin_laps=0), (10, "STOP ADDITION POSSIBLE"))
        self.assertEqual(h.update(11, confidence="HIGH", safety_margin_laps=0), (11, "STOP ADDITION CONFIRMED"))

    def test_H_low_confidence_does_not_confirm_stop_removal(self):
        h = StopCountStabilizer(initial=11, removal_confirmations=2)
        for _ in range(5):
            stable, state = h.update(10, confidence="LOW", safety_margin_laps=2)
        self.assertEqual(stable, 11)
        self.assertEqual(state, "STOP REMOVAL POSSIBLE")

    def test_I_window_closed_soon_after_box(self):
        plan = calculate_race_plan(self.inputs(
            current_lap=244, remaining_time_seconds=16000,
            current_fuel_liters=106, session_fuel_limit_liters=106,
            fuel_strategy_lpl=2.5, leader_lap=244,
        ))
        self.assertTrue(plan.available)
        self.assertGreater(plan.window.earliest_safe, 244)
        self.assertEqual(plan.window.state, "WINDOW CLOSED")

    def test_J_window_opens_only_when_minimum_stop_count_is_preserved(self):
        plan = calculate_race_plan(self.inputs())
        self.assertGreater(plan.window.earliest_safe, 1)
        before = simulate_stop_lap(self.inputs(), plan.window.earliest_safe - 1, plan.minimum_stops)
        at = simulate_stop_lap(self.inputs(), plan.window.earliest_safe, plan.minimum_stops)
        self.assertTrue(before["addsStop"])
        self.assertTrue(at["preservesMinimum"])

    def test_K_L_box_next_and_box_this_lap_are_absolute_targets(self):
        engine = RacePlanEngine()
        first = engine.update(self.inputs(
            remaining_time_seconds=1200, current_lap=100, own_pace_seconds=100,
            leader_pace_seconds=100, current_fuel_liters=5,
            fuel_strategy_lpl=2.5, session_fuel_limit_liters=55,
            pit_loss_seconds=30, margin_laps=1,
        ))
        self.assertEqual(first.window.state, "BOX NEXT LAP")
        target = first.window.target
        elapsed = (target - 100) * 100
        fuel_left = max(.1, 5 - (target - 100) * 2.5)
        second = engine.update(self.inputs(
            remaining_time_seconds=max(1, 1200-elapsed), current_lap=target,
            own_pace_seconds=100, leader_pace_seconds=100,
            current_fuel_liters=fuel_left, fuel_strategy_lpl=2.5,
            session_fuel_limit_liters=55, pit_loss_seconds=30, margin_laps=1,
        ))
        self.assertEqual(second.window.target, target)
        self.assertEqual(second.window.state, "BOX THIS LAP")

    def test_M_last_stint_is_partial_fill(self):
        plan = calculate_race_plan(self.inputs(
            remaining_time_seconds=2400, own_pace_seconds=120,
            leader_pace_seconds=120, current_fuel_liters=55,
            session_fuel_limit_liters=55, fuel_strategy_lpl=3.76,
            pit_loss_seconds=35, margin_laps=1,
        ))
        self.assertTrue(plan.stops[-1].final_fill)
        self.assertLess(plan.final_fuel_required_liters, 55)

    def test_N_margin_two_laps_increases_final_fuel_requirement(self):
        no_margin = calculate_race_plan(self.inputs(
            remaining_time_seconds=2400, own_pace_seconds=120, leader_pace_seconds=120,
            current_fuel_liters=55, session_fuel_limit_liters=55,
            fuel_strategy_lpl=3.0, pit_loss_seconds=30, margin_laps=0,
        ))
        margin = calculate_race_plan(self.inputs(
            remaining_time_seconds=2400, own_pace_seconds=120, leader_pace_seconds=120,
            current_fuel_liters=55, session_fuel_limit_liters=55,
            fuel_strategy_lpl=3.0, pit_loss_seconds=30, margin_laps=2,
        ))
        self.assertGreaterEqual(margin.final_fuel_required_liters, no_margin.final_fuel_required_liters)

    def test_O_P_real_and_unknown_fuel_are_distinct(self):
        real = calculate_race_plan(self.inputs(current_fuel_liters=33.4))
        missing = calculate_race_plan(self.inputs(current_fuel_liters=None))
        self.assertTrue(real.available)
        self.assertFalse(missing.available)
        self.assertIn("FUEL", missing.reason)
        self.assertIsNone(missing.current_autonomy_laps)

    def test_Q_team_fuel_source_is_metadata_not_zero_coercion(self):
        identity = RaceIdentity(1, 2, 3, "GP", 99, "18", 123)
        state = RaceState(identity, "Race", 1000, 3600, 10, 9, 90,
                          current_driver="David", current_fuel_liters=33.4,
                          fuel_source="SDK OBSERVADO", fuel_confidence="MEDIUM")
        self.assertEqual(state.current_fuel_liters, 33.4)
        self.assertEqual(state.fuel_source, "SDK OBSERVADO")

    def test_R_driver_swap_does_not_change_team_car_identity(self):
        identity = RaceIdentity(1, 2, 3, "GP", 99, "18", 123)
        a = RaceState(identity, "Race", 1000, 3600, 10, 9, 90, current_driver="Santiago")
        b = RaceState(identity, "Race", 900, 3600, 11, 10, 90, current_driver="David")
        self.assertEqual(a.identity.key, b.identity.key)
        self.assertNotEqual(a.current_driver, b.current_driver)

    def test_S_strategy_store_survives_reopen(self):
        identity = RaceIdentity(1, 2, 3, "GP", 99, "18", 123)
        engine = RacePlanEngine()
        engine.update(self.inputs())
        with tempfile.TemporaryDirectory() as folder:
            store = StrategyStore(folder)
            store.save(identity.key, engine.snapshot())
            reopened = StrategyStore(folder).load(identity.key)
            self.assertEqual(reopened["initialPlan"]["minimum_stops"], 10)
            self.assertEqual(reopened["currentPlan"]["minimum_stops"], 10)

    def test_T_unplanned_stop_recalculates_from_real_state(self):
        before = calculate_race_plan(self.inputs())
        after = calculate_race_plan(self.inputs(
            remaining_time_seconds=35000, current_lap=12,
            current_fuel_liters=99, stops_completed=1,
        ))
        self.assertTrue(after.available)
        self.assertNotEqual(after.stops[0].number, before.stops[0].number)
        self.assertEqual(after.stops[0].number, 2)

    def test_U_simultaneous_tyres_can_add_zero_time(self):
        profile = PitRulesProfile(
            service_mode=SIMULTANEOUS, refuel_rate_lps=96.4/35.2,
            tyre_time_seconds=27.0, driver_change_seconds=0.0,
            pit_lane_seconds=23.5, source="RULESET",
        )
        estimate = estimate_pit_stop(profile, PitServiceRequest(fuel_liters=96.4, tyres=True))
        self.assertAlmostEqual(estimate.fuel_time, 35.2, places=2)
        self.assertAlmostEqual(estimate.stationary_time, 35.2, places=2)
        self.assertAlmostEqual(estimate.tyre_extra_time, 0.0, places=2)

    def test_V_tyres_add_time_when_fuel_service_is_shorter(self):
        profile = PitRulesProfile(
            service_mode=SIMULTANEOUS, refuel_rate_lps=10,
            tyre_time_seconds=27.0, driver_change_seconds=0.0,
            pit_lane_seconds=20, source="RULESET",
        )
        estimate = estimate_pit_stop(profile, PitServiceRequest(fuel_liters=98, tyres=True))
        self.assertAlmostEqual(estimate.fuel_time, 9.8, places=2)
        self.assertAlmostEqual(estimate.tyre_extra_time, 17.2, places=2)

    def test_unknown_service_concurrency_does_not_invent_stationary_time(self):
        profile = PitRulesProfile(service_mode=UNKNOWN, refuel_rate_lps=2.5, tyre_time_seconds=27)
        estimate = estimate_pit_stop(profile, PitServiceRequest(fuel_liters=50, tyres=True))
        self.assertIsNone(estimate.stationary_time)
        self.assertIsNone(estimate.total_pit_loss)

    def test_W_timed_finish_is_a_range_not_false_precision(self):
        plan = calculate_race_plan(self.inputs())
        self.assertLess(plan.finish.low, plan.finish.high)
        self.assertGreaterEqual(plan.finish.expected, plan.finish.low)
        self.assertLessEqual(plan.finish.expected, plan.finish.high)

    def test_X_leader_pace_changes_finish_uncertainty(self):
        fast = calculate_race_plan(self.inputs(leader_pace_seconds=75))
        slow = calculate_race_plan(self.inputs(leader_pace_seconds=95))
        self.assertGreaterEqual(slow.finish.high, fast.finish.high)

    def test_Y_high_valid_fuel_lap_is_retained_not_deleted_as_outlier(self):
        model = FuelModel()
        for lap, use in enumerate((2.40, 2.41, 2.39, 3.20), 1):
            model.add(FuelLapSample(lap, use, GREEN_FULL))
        estimate = model.estimate(margin_laps=2, margin_source="IRACING_APP_INI_DEFAULT")
        self.assertEqual(estimate.green_samples, 4)
        self.assertGreater(estimate.strategy_lpl, estimate.observed_lpl)
        self.assertEqual(estimate.margin_laps, 2)

    def test_Z_incomplete_data_never_becomes_zero(self):
        model = FuelModel()
        estimate = model.estimate()
        self.assertIsNone(estimate.observed_lpl)
        self.assertIsNone(estimate.strategy_lpl)
        self.assertEqual(estimate.source, "SIN DATO")

    def test_lap_classification_excludes_non_green_from_strategy(self):
        self.assertEqual(classify_fuel_lap(exited_pit=True), OUT_LAP)
        self.assertEqual(classify_fuel_lap(entered_pit=True), IN_LAP)
        self.assertEqual(classify_fuel_lap(on_pit=True), PIT_LAP)
        self.assertEqual(classify_fuel_lap(caution=True), CAUTION)
        self.assertEqual(classify_fuel_lap(anomalous=True, explanation="traffic"), ANOMALO_EXPLICADO)
        model = FuelModel()
        model.extend([
            FuelLapSample(1, 4.5, OUT_LAP),
            FuelLapSample(2, 2.5, GREEN_FULL),
            FuelLapSample(3, 1.5, CAUTION),
            FuelLapSample(4, 2.6, GREEN_FULL),
            FuelLapSample(5, 2.55, GREEN_FULL),
        ])
        estimate = model.estimate()
        self.assertEqual(estimate.green_samples, 3)
        self.assertGreater(estimate.observed_lpl, 2.4)
        self.assertLess(estimate.observed_lpl, 2.7)

    def test_session_fuel_limit_applies_percentage(self):
        self.assertAlmostEqual(session_fuel_limit(110, .90), 99)
        self.assertAlmostEqual(session_fuel_limit(110, 90), 99)
        self.assertAlmostEqual(session_fuel_limit(110, None), 110)

    def test_pit_learning_needs_more_than_one_sample(self):
        model = PitLearningModel()
        model.add(ObservedPitStop(23.0, 20.0, fuel_added_liters=50, tyres=False, driver_change=False))
        self.assertIsNone(model.learned_pit_lane_seconds())
        model.add(ObservedPitStop(25.0, 22.0, fuel_added_liters=55, tyres=False, driver_change=False))
        self.assertAlmostEqual(model.learned_pit_lane_seconds(), 24.0)

    def test_initial_plan_is_preserved_while_current_plan_changes(self):
        engine = RacePlanEngine()
        first = engine.update(self.inputs(fuel_strategy_lpl=2.67))
        initial = engine.snapshot()["initialPlan"]["minimum_stops"]
        for _ in range(3):
            engine.update(self.inputs(fuel_strategy_lpl=2.43))
        snapshot = engine.snapshot()
        self.assertEqual(snapshot["initialPlan"]["minimum_stops"], initial)
        self.assertLessEqual(snapshot["currentPlan"]["minimum_stops"], initial)

    def test_restart_restores_hysteresis_state(self):
        engine = RacePlanEngine()
        engine.update(self.inputs())
        engine.stabilizer.pending = 9
        engine.stabilizer.count = 2
        engine.last_transition = "STOP REMOVAL POSSIBLE"
        payload = engine.snapshot()
        restored = RacePlanEngine().restore_runtime(payload)
        self.assertEqual(restored.stabilizer.stable, 10)
        self.assertEqual(restored.stabilizer.pending, 9)
        self.assertEqual(restored.stabilizer.count, 2)
        self.assertEqual(restored.committed_target_lap, engine.committed_target_lap)
        self.assertEqual(restored.last_transition, "STOP REMOVAL POSSIBLE")


    def test_petit_le_mans_observed_stints_fixture_can_seed_history(self):
        fixture = Path(__file__).parent / "fixtures" / "endurance_laps.json"
        data = json.loads(fixture.read_text(encoding="utf-8"))
        model = FuelModel()
        for item in data["laps"]:
            model.add(FuelLapSample(item["lap"], item["consumptionLiters"], GREEN_FULL,
                                    item["paceSeconds"], "PETIT_LE_MANS_FIXTURE"))
        estimate = model.estimate()
        self.assertEqual(estimate.green_samples, len(data["laps"]))
        self.assertGreater(estimate.strategy_lpl, 2.4)
        self.assertLess(estimate.strategy_lpl, 2.8)


if __name__ == "__main__":
    unittest.main()
