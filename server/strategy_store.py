"""Atomic local persistence for ZRE Race Plan state."""
from __future__ import annotations
import json
from pathlib import Path
import re


def _slug(value):
    text = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "unknown")).strip("-")
    return text or "unknown"


class StrategyStore:
    def __init__(self, root):
        self.root = Path(root)

    def path_for(self, identity_key):
        return self.root / "data" / "race_plan" / f"{_slug(identity_key)}.json"

    def save(self, identity_key, payload):
        path = self.path_for(identity_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
        return path

    def load(self, identity_key):
        path = self.path_for(identity_key)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError, TypeError):
            return None
