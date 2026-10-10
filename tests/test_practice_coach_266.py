"""Practice Coach contract: real detected turns and measured losses only."""
import unittest
from server.lap_coach import LapCoach

class CoachInventoryTests(unittest.TestCase):
    def test_all_twenty_detected_turns_exposed_without_invented_diagnoses(self):
        coach=LapCoach()
        coach.corner_model=[{"number":i+1,"pct":(i+.5)/20} for i in range(20)]
        payload=coach.payload(lambda seconds: "—" if seconds is None else str(seconds))
        self.assertEqual(len(payload["allCorners"]),20)
        self.assertEqual([r["zone"] for r in payload["allCorners"]],[f"T{i}" for i in range(1,21)])
        self.assertTrue(all(r["state"]=="insufficient" and r["lossSeconds"] is None
                            for r in payload["allCorners"]))

    def test_measured_coach_loss_is_preserved_for_matching_corner(self):
        coach=LapCoach()
        coach.corner_model=[{"number":1,"pct":.041},{"number":2,"pct":.125}]
        # Source-shaped advice on a validated lap: zone, time loss, title,
        # tip, observed lap fraction, phase.
        coach.recent_valid_advice.append([(1,.420,"Frenada temprana",
                            "Frena después de tu referencia.",.041,"ENTRY")])
        payload=coach.payload(lambda value: "—" if value is None else str(value))
        corner=payload["allCorners"][0]
        self.assertEqual(corner["state"],"diagnosis")
        self.assertAlmostEqual(corner["lossSeconds"],.420)
        self.assertEqual(corner["title"],"Frenada temprana")
        self.assertEqual(payload["allCorners"][1]["state"],"insufficient")

if __name__=="__main__":
    unittest.main()
