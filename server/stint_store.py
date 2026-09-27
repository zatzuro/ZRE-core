"""Small local persistence layer for Setup Engineer history."""
import json
from pathlib import Path
import re


def slug(value, fallback="unknown"):
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or fallback


class StintStore:
    def __init__(self, root):
        self.root = Path(root)

    def context_dir(self, car, track, layout):
        return self.root / slug(car) / slug(track) / slug(layout)

    @staticmethod
    def _write_json(path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
        return path

    @staticmethod
    def _read_json(path, default=None):
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return default

    def save_setup(self, car, track, layout, snapshot):
        folder = self.context_dir(car, track, layout) / "setups"
        fingerprint = (snapshot or {}).get("fingerprint") or "unknown"
        path = folder / f"setup-{slug(fingerprint)}.json"
        if not path.exists():
            self._write_json(path, snapshot)
        return path

    def _stint_files(self, car, track, layout):
        folder = self.context_dir(car, track, layout) / "stints"
        return sorted(folder.glob("stint-*.json")) if folder.exists() else []

    def next_stint_number(self, car, track, layout):
        numbers = []
        for path in self._stint_files(car, track, layout):
            match = re.search(r"stint-(\d+)\.json$", path.name)
            if match:
                numbers.append(int(match.group(1)))
        return max(numbers, default=0) + 1

    def save_stint(self, record):
        session = (record or {}).get("session") or {}
        car = session.get("car") or "unknown"
        track = session.get("track") or "unknown"
        layout = session.get("layout") or "default"
        payload = dict(record or {})
        number = int(payload.get("stintNumber") or self.next_stint_number(car, track, layout))
        payload["stintNumber"] = number
        folder = self.context_dir(car, track, layout) / "stints"
        path = folder / f"stint-{number:03d}.json"
        self._write_json(path, payload)
        return path

    def load_stints(self, car, track, layout):
        result = []
        for path in self._stint_files(car, track, layout):
            value = self._read_json(path)
            if isinstance(value, dict):
                result.append(value)
        return result

    def previous_stint(self, car, track, layout, before_number=None):
        stints = self.load_stints(car, track, layout)
        if before_number is not None:
            stints = [s for s in stints if int(s.get("stintNumber") or 0) < int(before_number)]
        return stints[-1] if stints else None

    def save_track_profile(self, car, track, layout, profile):
        path = self.context_dir(car, track, layout) / "track_profile.json"
        return self._write_json(path, profile)

    def load_track_profile(self, car, track, layout):
        path = self.context_dir(car, track, layout) / "track_profile.json"
        return self._read_json(path, {})
