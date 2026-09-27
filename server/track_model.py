"""Pure, lightweight track geometry and corner helpers for Lap Coach.

No polling and no I/O live here. The functions run only on the bounded
completed-lap sample buffer produced by LapCoach.
"""
import math


def _num(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def circular_distance(a, b):
    d = abs(float(a) - float(b)) % 1.0
    return min(d, 1.0 - d)


def _canonical_orientation(raw):
    """Rotate display so start/finish direction points left and body reads upward."""
    if len(raw) < 8:
        return raw
    first_pct = raw[0][2]
    target = min(raw, key=lambda p: abs(p[2] - min(1.0, first_pct + 0.02)))
    dx = target[0] - raw[0][0]
    dy = target[1] - raw[0][1]
    if abs(dx) + abs(dy) < 1e-9:
        return raw
    angle = math.atan2(dy, dx)
    rotate = math.pi - angle
    cr, sr = math.cos(rotate), math.sin(rotate)
    rotated = [(x * cr - y * sr, x * sr + y * cr, pct) for x, y, pct in raw]
    start_y = rotated[0][1]
    median_y = sorted(p[1] for p in rotated)[len(rotated) // 2]
    if median_y < start_y:
        rotated = [(x, -y, pct) for x, y, pct in rotated]
    return rotated


def project_track(rows, bins=480):
    """Return raw track geometry and source; prefer live GPS over yaw integration."""
    gps = []
    for row in rows:
        if len(row) <= 10:
            continue
        lat, lon = _num(row[9]), _num(row[10])
        if lat is None or lon is None:
            continue
        gps.append((lat, lon, row[0] / max(1, bins - 1)))
    if len(gps) >= 40:
        lats = [p[0] for p in gps]
        lons = [p[1] for p in gps]
        if max(lats) - min(lats) > 1e-7 and max(lons) - min(lons) > 1e-7:
            lat0 = sum(lats) / len(lats)
            lon0 = sum(lons) / len(lons)
            cos_lat = max(0.05, math.cos(math.radians(lat0)))
            raw = [
                ((lon - lon0) * 111320.0 * cos_lat,
                 (lat - lat0) * 110540.0,
                 pct)
                for lat, lon, pct in gps
            ]
            return _canonical_orientation(raw), "GPS"

    if len(rows) < 2:
        return [], "NONE"
    x = y = heading = 0.0
    first_pct = rows[0][0] / max(1, bins - 1)
    raw = [(0.0, 0.0, first_pct)]
    prev_t = rows[0][1]
    for row in rows[1:]:
        t = _num(row[1])
        speed = _num(row[2]) or 0.0
        yaw = _num(row[7]) or 0.0
        if t is None:
            continue
        dt = max(0.0, min(0.5, t - prev_t))
        prev_t = t
        heading += yaw * dt
        x += speed * math.cos(heading) * dt
        y += speed * math.sin(heading) * dt
        raw.append((x, y, row[0] / max(1, bins - 1)))
    if len(raw) < 2:
        return [], "NONE"
    end_x, end_y = raw[-1][0], raw[-1][1]
    total = len(raw) - 1
    corrected = []
    for i, (px, py, pct) in enumerate(raw):
        f = i / total
        corrected.append((px - end_x * f, py - end_y * f, pct))
    return _canonical_orientation(corrected), "DEAD_RECKONING"


def normalize_points(raw):
    if len(raw) < 2:
        return []
    xs = [a for a, _, _ in raw]
    ys = [b for _, b, _ in raw]
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    if dx < 1e-6 or dy < 1e-6:
        return []
    scale = min(88 / dx, 88 / dy)
    cx = (max(xs) + min(xs)) / 2
    cy = (max(ys) + min(ys)) / 2
    return [
        {"x": round(50 + (px - cx) * scale, 2),
         "y": round(50 - (py - cy) * scale, 2),
         "pct": round(pct, 4)}
        for px, py, pct in raw
    ]


def detect_corners(rows, expected_turns=None, bins=480):
    """Detect turn centers from yaw/steering/lateral-G peaks."""
    samples = []
    for row in rows:
        if len(row) < 9:
            continue
        pct = row[0] / max(1, bins - 1)
        steering = _num(row[5]) or 0.0
        yaw = _num(row[7]) or 0.0
        lat_g = _num(row[8]) or 0.0
        score = abs(yaw) * 2.2 + min(abs(steering), 1.2) * 0.35 + min(abs(lat_g), 20.0) * 0.025
        sign = 1 if yaw > 0.015 else -1 if yaw < -0.015 else (1 if steering > 0 else -1 if steering < 0 else 0)
        samples.append((pct, score, sign, yaw))
    if len(samples) < 20:
        return []

    candidates = []
    radius = 4
    for i in range(radius, len(samples) - radius):
        pct, score, sign, yaw = samples[i]
        if abs(yaw) < 0.025 or score < 0.11:
            continue
        window = samples[i-radius:i+radius+1]
        if score < max(v[1] for v in window):
            continue
        candidates.append({
            "pct": pct,
            "score": score,
            "direction": "izquierda" if sign > 0 else "derecha" if sign < 0 else None,
        })
    if not candidates:
        return []

    try:
        target = int(expected_turns) if expected_turns is not None else None
    except (TypeError, ValueError):
        target = None
    if target is not None and not (2 <= target <= 40):
        target = None

    min_sep = 0.010 if target and target >= 12 else 0.014
    selected = []
    for cand in sorted(candidates, key=lambda c: c["score"], reverse=True):
        conflict = False
        for kept in selected:
            dist = circular_distance(cand["pct"], kept["pct"])
            if dist < min_sep:
                if cand["direction"] != kept["direction"] and dist >= 0.006:
                    continue
                conflict = True
                break
        if not conflict:
            selected.append(cand)
        if target and len(selected) >= target:
            break

    if target:
        selected = selected[:target]
    else:
        selected = [c for c in selected if c["score"] >= 0.16][:24]

    selected.sort(key=lambda c: c["pct"])
    confidence = "HIGH" if target and len(selected) == target else "MEDIUM" if len(selected) >= 3 else "LOW"
    for n, corner in enumerate(selected, 1):
        corner["number"] = n
        corner["confidence"] = confidence
        corner["pct"] = round(corner["pct"], 5)
        corner["score"] = round(corner["score"], 4)
    return selected


def nearest_corner(corners, pct, phase=None):
    if not corners or pct is None:
        return None
    pct = float(pct)
    if phase == "ENTRY":
        ahead = []
        for corner in corners:
            delta = (corner["pct"] - pct) % 1.0
            if delta <= 0.075:
                ahead.append((delta, corner))
        if ahead:
            return min(ahead, key=lambda item: item[0])[1]
    corner = min(corners, key=lambda c: circular_distance(c["pct"], pct))
    return corner if circular_distance(corner["pct"], pct) <= 0.075 else None


def advice_marker(title, metrics, zone, zones):
    """Return measured event position and driving phase for a coach finding."""
    center = (zone - 0.5) / zones

    def m(index):
        return metrics[index] if metrics is not None and len(metrics) > index else None

    title = title or ""
    if "Frenada" in title:
        return (m(0) if m(0) is not None else center), "ENTRY"
    if title in ("Giro demasiado temprano", "Giro temprano", "Giro tardío",
                 "Falta giro durante la frenada", "Demasiado giro con freno"):
        return (m(3) if m(3) is not None else center), "ENTRY"
    if title in ("Aceleración tardía", "Salida comprometida"):
        return (m(2) if m(2) is not None else center), "EXIT"
    if title == "Exceso de volante":
        return (m(12) if m(12) is not None else m(3) if m(3) is not None else center), "MID"
    if title == "Velocidad mínima baja":
        return (m(11) if m(11) is not None else center), "MID"
    return center, "GENERAL"


def consolidate_advice(advice, corners=None, limit=2):
    """Keep the strongest actionable finding per physical corner.

    compare() may find multiple symptoms in adjacent distance zones that belong
    to the same real corner. Preserve the highest-loss item for that corner and
    then fill remaining slots with findings from different locations.
    """
    corners = corners or []
    ranked = sorted(advice or [], key=lambda item: item[1], reverse=True)
    selected = []
    used_corner_numbers = set()
    used_positions = []
    for item in ranked:
        zone, loss, title, tip = item[:4]
        marker_pct = item[4] if len(item) > 4 else None
        phase = item[5] if len(item) > 5 else "GENERAL"
        corner = nearest_corner(corners, marker_pct, phase) if marker_pct is not None else None
        if corner:
            number = corner.get("number")
            if number in used_corner_numbers:
                continue
        elif marker_pct is not None and any(circular_distance(marker_pct, pct) < 0.055 for pct in used_positions):
            continue
        selected.append(item)
        if corner:
            used_corner_numbers.add(corner.get("number"))
        elif marker_pct is not None:
            used_positions.append(marker_pct)
        if len(selected) >= limit:
            break
    return selected
