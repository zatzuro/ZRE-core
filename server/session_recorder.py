"""Compact bounded JSONL recorder for real-session coach validation."""
import json
from pathlib import Path

class SessionRecorder:
    def __init__(self, path, max_bytes=5_000_000):
        self.path = Path(path)
        self.max_bytes = max_bytes

    def _rotate_if_needed(self):
        try:
            if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                backup = self.path.with_suffix(self.path.suffix + '.1')
                if backup.exists():
                    backup.unlink()
                self.path.replace(backup)
        except OSError:
            pass

    def write(self, record):
        self._rotate_if_needed()
        try:
            with self.path.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n')
        except OSError:
            pass
