import math
import unittest

from server.track_model import (
    advice_marker,
    consolidate_advice,
    detect_corners,
    nearest_corner,
    normalize_points,
    project_track,
)


class TrackModelTests(unittest.TestCase):
    def test_advice_marker_uses_measured_event_not_zone_center(self):
        # brake, min speed, throttle return, turn-in, max steer, brake release,
        # exit speed, direction, max brake, dir confidence, prep steer,
        # min-speed pct, max-steer pct
        metrics = (.412, 28.0, .486, .438, .52, .455, 43.0, 1, .88, .9, 0.0, .462, .451)
        self.assertEqual(advice_marker("Frenada temprana", metrics, 6, 12), (.412, "ENTRY"))
        self.assertEqual(advice_marker("Giro tardío", metrics, 6, 12), (.438, "ENTRY"))
        self.assertEqual(advice_marker("Velocidad mínima baja", metrics, 6, 12), (.462, "MID"))
        self.assertEqual(advice_marker("Aceleración tardía", metrics, 6, 12), (.486, "EXIT"))

    def test_new_driver_metrics_map_to_expected_phase(self):
        metrics = [None] * 18
        metrics[2] = .61
        metrics[3] = .56
        metrics[12] = .58
        metrics[14] = .59
        self.assertEqual(advice_marker("Gas demasiado progresivo", metrics, 7, 12), (.61, "EXIT"))
        self.assertEqual(advice_marker("Correcciones de volante", metrics, 7, 12), (.58, "MID"))

    def test_nearest_corner_entry_prefers_corner_ahead(self):
        corners = [
            {"number": 4, "pct": .31, "direction": "derecha"},
            {"number": 5, "pct": .38, "direction": "izquierda"},
        ]
        self.assertEqual(nearest_corner(corners, .35, "ENTRY")["number"], 5)
        self.assertEqual(nearest_corner(corners, .315, "MID")["number"], 4)

    def test_consolidate_advice_keeps_one_action_per_corner(self):
        corners = [
            {"number": 7, "pct": .50, "direction": "derecha"},
            {"number": 8, "pct": .72, "direction": "izquierda"},
        ]
        advice = [
            (6, .42, "Giro temprano", "A", .475, "ENTRY"),
            (6, .35, "Velocidad mínima baja", "B", .505, "MID"),
            (9, .28, "Aceleración tardía", "C", .725, "EXIT"),
        ]
        selected = consolidate_advice(advice, corners, 2)
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0][2], "Giro temprano")
        self.assertEqual(selected[1][2], "Aceleración tardía")

    def test_project_track_prefers_gps_when_available(self):
        rows = []
        for i in range(80):
            a = 2 * math.pi * i / 79
            # row: bin,time,speed,brake,throttle,steering,gear,yaw,latG,lat,lon,yawNorth
            rows.append([i, i*.1, 40.0, 0, 1, 0, 4, .02, 3.0,
                         4.60 + math.sin(a)*.001,
                         -74.08 + math.cos(a)*.001, 0.0])
        raw, source = project_track(rows, bins=80)
        self.assertEqual(source, "GPS")
        points = normalize_points(raw)
        self.assertGreater(len(points), 70)
        self.assertTrue(all(0 <= p["x"] <= 100 and 0 <= p["y"] <= 100 for p in points))

    def test_project_track_falls_back_without_gps(self):
        rows = []
        for i in range(80):
            yaw = .05 if 20 < i < 55 else 0.0
            rows.append([i, i*.1, 35.0, 0, 1, .1, 4, yaw, 2.0, None, None, None])
        raw, source = project_track(rows, bins=80)
        self.assertEqual(source, "DEAD_RECKONING")
        self.assertGreater(len(raw), 70)

    def test_detect_corners_numbers_in_lap_order(self):
        rows = []
        total = 240
        centers = (45, 115, 190)
        for i in range(total):
            yaw = 0.0
            steering = 0.0
            lat_g = 0.0
            for c, sign in zip(centers, (1, -1, 1)):
                d = abs(i-c)
                if d <= 7:
                    strength = 1 - d/8
                    yaw += sign * .18 * strength
                    steering += sign * .42 * strength
                    lat_g += sign * 7.0 * strength
            rows.append([i, i*.05, 40.0, 0, 1, steering, 4, yaw, lat_g, None, None, None])
        corners = detect_corners(rows, expected_turns=3, bins=total)
        self.assertEqual([c["number"] for c in corners], [1, 2, 3])
        self.assertEqual(len(corners), 3)
        self.assertLess(corners[0]["pct"], corners[1]["pct"])
        self.assertLess(corners[1]["pct"], corners[2]["pct"])


if __name__ == "__main__":
    unittest.main()
