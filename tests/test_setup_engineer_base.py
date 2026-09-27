import tempfile
import unittest
from pathlib import Path

from server.setup_snapshot import (
    compare_setups,
    setup_fingerprint,
    snapshot_from_html,
    snapshot_from_sdk,
)
from server.setup_report import render_setup_report, write_setup_report
from server.setup_engineer import SetupEngineer, build_track_profile
from server.lap_coach import LapCoach
from server.stint_store import StintStore


class SetupEngineerBaseTests(unittest.TestCase):
    def test_sdk_snapshot_preserves_unknown_car_parameters(self):
        raw = {
            "Chassis": {
                "Front": {"ARB": 3, "RideHeight": "30 mm"},
                "Rear": {"Spring": "175 N/mm"},
            },
            "Aero": {"RearWing": 8.5},
            "CarSpecificThing": {"ModeX": "enabled"},
        }
        snap = snapshot_from_sdk(raw, {
            "DriverSetupName": "Race A",
            "DriverSetupIsModified": True,
        })
        self.assertEqual(snap["source"], "SDK")
        self.assertEqual(snap["flatParameters"]["Aero.RearWing"], 8.5)
        self.assertEqual(snap["flatParameters"]["CarSpecificThing.ModeX"], "enabled")
        self.assertEqual(snap["metadata"]["setupName"], "Race A")
        self.assertEqual(len(snap["fingerprint"]), 16)

    def test_fingerprint_is_stable_for_dict_order(self):
        a = {"B": 2, "A": {"X": 1}}
        b = {"A": {"X": 1}, "B": 2}
        self.assertEqual(setup_fingerprint(a), setup_fingerprint(b))

    def test_html_snapshot_is_generic_and_preserves_sections(self):
        html = """
        <html><body>
        <h2>Aero</h2>
        <table><tr><td>Rear Wing</td><td>8.5</td></tr></table>
        <h2>Chassis</h2>
        <table>
          <tr><td>Front ARB</td><td>3</td></tr>
          <tr><td>Front ARB</td><td>4 duplicate label</td></tr>
        </table>
        </body></html>
        """
        snap = snapshot_from_html(html, "setup.html")
        self.assertEqual(snap["source"], "IRACING_HTML")
        self.assertEqual(snap["parameters"]["Aero"]["Rear Wing"], "8.5")
        self.assertEqual(snap["parameters"]["Chassis"]["Front ARB"], "3")
        self.assertEqual(snap["parameters"]["Chassis"]["Front ARB [2]"], "4 duplicate label")

    def test_compare_setups_reports_only_changed_parameters(self):
        old = snapshot_from_sdk({"Aero": {"Wing": 8.5}, "Chassis": {"ARB": 3}})
        new = snapshot_from_sdk({"Aero": {"Wing": 7.5}, "Chassis": {"ARB": 3}, "Electronics": {"TC": 4}})
        changes = compare_setups(old, new)
        by_name = {item["parameter"]: item for item in changes}
        self.assertEqual(by_name["Aero.Wing"]["before"], 8.5)
        self.assertEqual(by_name["Aero.Wing"]["after"], 7.5)
        self.assertIsNone(by_name["Electronics.TC"]["before"])
        self.assertNotIn("Chassis.ARB", by_name)

    def test_stint_store_scopes_history_by_car_track_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            store = StintStore(folder)
            base = {
                "session": {"car": "McLaren 720S GT3 EVO", "track": "Spa", "layout": "GP"},
                "stintPerformance": {"validLaps": 5},
            }
            first = store.save_stint(base)
            second = store.save_stint(base)
            other = store.save_stint({
                "session": {"car": "McLaren 720S GT3 EVO", "track": "Spa", "layout": "Endurance"}
            })
            self.assertEqual(first.name, "stint-001.json")
            self.assertEqual(second.name, "stint-002.json")
            self.assertEqual(other.name, "stint-001.json")
            previous = store.previous_stint("McLaren 720S GT3 EVO", "Spa", "GP", before_number=2)
            self.assertEqual(previous["stintNumber"], 1)

    def test_setup_store_deduplicates_by_fingerprint(self):
        with tempfile.TemporaryDirectory() as folder:
            store = StintStore(folder)
            snap = snapshot_from_sdk({"Aero": {"Wing": 8.5}})
            a = store.save_setup("Car", "Track", "Layout", snap)
            b = store.save_setup("Car", "Track", "Layout", snap)
            self.assertEqual(a, b)
            self.assertEqual(len(list(a.parent.glob("setup-*.json"))), 1)

    def test_lap_coach_exposes_compact_engineering_contract(self):
        coach = LapCoach()
        metrics = (
            .10, 30.0, .16, .12, .45, .15, 40.0, 1, .80, .9, 0.0,
            .13, .125, .50, .14, .22, 2, .18, 48.0, 7.5, 3, .55
        )
        segments = [(1.2, metrics)] * 12
        coach.lap_segments.append((90.0, segments))
        coach.best_lap = 90.0
        coach.best_segments = segments
        coach.corner_model = [{"number": 1, "pct": .04, "direction": "derecha"}]
        snapshot = coach.engineering_snapshot()
        self.assertEqual(snapshot["validLaps"], 1)
        self.assertEqual(len(snapshot["zones"]), 12)
        self.assertEqual(snapshot["zones"][0]["entrySpeedKph"], 172.8)
        self.assertEqual(snapshot["zones"][0]["minGear"], 3)
        self.assertNotIn("samples", snapshot)

    def test_track_profile_marks_inference_vs_measurement(self):
        engineering = {
            "zones": [
                {"types": ["HIGH SPEED"], "fullThrottleShare": .8, "peakLatAccel": 8.0},
                {"types": ["HIGH SPEED", "DIRECTION CHANGE"], "fullThrottleShare": .7, "peakLatAccel": 7.0},
                {"types": ["HEAVY BRAKING", "MEDIUM SPEED"], "fullThrottleShare": .2, "peakLatAccel": 4.0},
                {"types": ["TRACTION", "LOW SPEED"], "fullThrottleShare": .1, "peakLatAccel": 3.0},
            ]
        }
        profile = build_track_profile(engineering)
        self.assertEqual(profile["highSpeed"]["source"], "INFERRED")
        self.assertEqual(profile["fullThrottleShare"]["source"], "MEASURED")
        self.assertEqual(profile["highSpeed"]["value"], "HIGH")

    def test_setup_engineer_saves_stint_compares_and_exports(self):
        engineering = {
            "validLaps": 4,
            "bestLap": 90.1,
            "optimalLap": 89.7,
            "representativeAverage": 90.5,
            "lapStdDev": .22,
            "corners": [{"number": 1, "pct": .10}],
            "zones": [{
                "zone": 1, "corner": "T1", "types": ["HEAVY BRAKING", "LOW SPEED"],
                "entrySpeedKph": 210.0, "minSpeedKph": 80.0, "exitSpeedKph": 125.0,
                "brakeStartPct": .07, "maxBrake": .9, "brakeDuration": 1.1,
                "brakeReleasePct": .11, "maxSteeringDeg": 28.0,
                "steeringCorrections": 1, "throttleReturnPct": .13,
                "throttleRampSeconds": .25, "peakYawRate": .15,
                "peakLatAccel": 6.0, "minGear": 2, "fullThrottleShare": .2,
                "averageZoneTime": 4.1,
            }],
            "repeatedBehavior": [{
                "zone": "Curva 1 · entrada", "title": "Giro temprano",
                "occurrences": 3, "sampleLaps": 4, "repeatRatio": .75,
                "confidence": "MEDIA", "advice": "Retrasa ligeramente el giro."
            }],
        }
        with tempfile.TemporaryDirectory() as folder:
            engineer = SetupEngineer(folder)
            session = {"car": "McLaren", "track": "Spa", "layout": "GP", "session": "Practice"}
            setup_a = snapshot_from_sdk({"Aero": {"Wing": 8.5}})
            engineer.start_stint(session, setup_a, {"trackTemp": {"value": 32, "source": "MEASURED"}}, 55.0, 100.0)
            engineer.set_feedback("NEUTRO", "SUELTO", "NEUTRO", "Rear moves in T1.")
            first = engineer.finish_stint(engineering, 40.0, 460.0, 3.75)
            self.assertEqual(first["stintNumber"], 1)
            self.assertEqual(first["driverFeedback"]["mid"], "SUELTO")
            self.assertEqual(first["dataQuality"]["telemetrySource"], "LAP_COACH_SUMMARY")
            report = engineer.export_report(first)
            self.assertTrue(report.exists())

            setup_b = snapshot_from_sdk({"Aero": {"Wing": 7.5}})
            engineer.start_stint(session, setup_b, {}, 55.0, 500.0)
            second = engineer.finish_stint({**engineering, "bestLap": 89.9}, 40.0, 860.0, 3.75)
            self.assertEqual(second["stintNumber"], 2)
            self.assertEqual(second["setupChanges"][0]["parameter"], "Aero.Wing")
            self.assertIn("bestLap", second["comparison"])


    def test_markdown_report_contains_required_contract(self):
        setup = snapshot_from_sdk({"Aero": {"Wing": 8.5}})
        stint = {
            "session": {"car": "McLaren", "track": "Spa", "layout": "GP"},
            "trackProfile": {
                "highSpeed": {"value": "HIGH", "source": "INFERRED"},
                "heavyBraking": {"value": "MEDIUM", "source": "MEASURED"},
            },
            "setup": setup,
            "stintPerformance": {"validLaps": 5, "bestLap": "2:16.100"},
            "corners": [{"zone": "T9", "types": ["HIGH SPEED"], "minSpeed": {"value": 145, "source": "MEASURED"}}],
            "balancePatterns": {"entry": "No repeated pattern"},
            "repeatedBehavior": [{"location": "T9", "pattern": "Rear corrections", "occurrences": 4, "validLaps": 5, "repeatRatio": "80%", "confidence": "HIGH"}],
            "driverFeedback": {"entry": "NEUTRO", "mid": "SUELTO", "exit": "NEUTRO"},
            "comparison": {"highSpeed": "Improved"},
            "setupEngineerSummary": ["Repeated T9 rear corrections detected."],
            "dataQuality": {"validLaps": 5, "confidence": "HIGH"},
        }
        report = render_setup_report(stint, setup_changes=[{"parameter": "Aero.Wing", "before": 8.5, "after": 7.5}])
        headings = [
            "## SESSION", "## TRACK PROFILE", "## CURRENT SETUP", "## SETUP CHANGES",
            "## STINT PERFORMANCE", "## CORNER / ZONE ANALYSIS", "## BALANCE PATTERNS",
            "## REPEATED BEHAVIOR", "## DRIVER FEEDBACK",
            "## COMPARISON VS PREVIOUS STINT", "## ZRE SETUP ENGINEER SUMMARY",
            "## DATA QUALITY", "## REQUEST TO AI SETUP ENGINEER",
        ]
        for heading in headings:
            self.assertIn(heading, report)
        self.assertIn("Aero.Wing", report)
        self.assertIn("8.5 → 7.5", report)
        self.assertIn("[INFERRED]", report)

    def test_report_can_be_written_as_markdown(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "ZRE_SETUP_REPORT_Test_Stint01.md"
            result = write_setup_report(target, {"session": {"car": "Test"}})
            self.assertEqual(result, target)
            self.assertTrue(target.exists())
            self.assertIn("# ZRE SETUP ENGINEER REPORT", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
