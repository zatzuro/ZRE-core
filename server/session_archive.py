"""Safe seven-day session retention and local exports.

Retention is anchored to persisted *finish time*, never file mtime. Incomplete,
queued, protected or active sessions are ineligible for automated deletion.
This module does not touch setups, preferences, archives in reports or app files.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import shutil
import zipfile

DEFAULT_DAYS = 7

def utc_date(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None

def clean_id(value):
    if not isinstance(value, str) or not value or len(value) > 190:
        raise ValueError("Identificador de sesión inválido")
    if "/" in value or "\\" in value or value in (".", "..") or ".." in value:
        raise ValueError("Ruta de sesión no permitida")
    return value

class SessionArchive:
    def __init__(self, root):
        self.root = Path(root)
        self.settings_path = self.root / "_retention.json"
        self.retention_days = DEFAULT_DAYS
        self._load_settings()

    def _load_settings(self):
        try:
            info = json.loads(self.settings_path.read_text(encoding="utf-8"))
            self.retention_days = self._days(info.get("days"))
        except (OSError, ValueError, TypeError, AttributeError):
            self.retention_days = DEFAULT_DAYS

    @staticmethod
    def _days(value):
        if isinstance(value, bool) or int(value) != float(value) or not 1 <= int(value) <= 365:
            raise ValueError("La retención debe estar entre 1 y 365 días")
        return int(value)

    def configure(self, days):
        days = self._days(days)
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.settings_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"days": days}, indent=2), encoding="utf-8")
        tmp.replace(self.settings_path)
        self.retention_days = days
        return days

    def directory(self, session_id):
        name = clean_id(session_id)
        path = self.root / name
        if not path.is_dir() or path.is_symlink() or path.parent != self.root:
            raise ValueError("Sesión no encontrada")
        return path

    @staticmethod
    def info(folder):
        try:
            summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            summary = {}
        try:
            session = json.loads((folder / "session.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            session = {}
        # Only an explicit persisted finishedAt qualifies for automatic expiry.
        finished = utc_date(summary.get("finishedAt"))
        files = [p for p in folder.iterdir() if p.is_file() and not p.is_symlink()]
        return {"sessionId": folder.name, "startedAt": session.get("startedAt"),
                "finishedAt": finished.isoformat() if finished else None,
                "track": (session.get("metadata") or {}).get("track"),
                "sessionType": (session.get("metadata") or {}).get("sessionType"),
                "protected": (folder / ".protected").is_file(),
                "sizeBytes": sum(p.stat().st_size for p in files),
                "complete": finished is not None, "events": summary.get("events", 0)}

    def sessions(self, excluded=()):
        if not self.root.is_dir():
            return []
        excluded = {Path(x) for x in excluded if x}
        output = []
        for folder in self.root.iterdir():
            if not folder.is_dir() or folder.is_symlink() or folder in excluded:
                continue
            output.append(self.info(folder))
        return sorted(output, key=lambda item: item.get("startedAt") or "", reverse=True)

    def status(self, excluded=()):
        sessions = self.sessions(excluded)
        oldest = min((s["startedAt"] for s in sessions if s.get("startedAt")), default=None)
        return {"retentionDays": self.retention_days, "sizeBytes": sum(s["sizeBytes"] for s in sessions),
                "oldestAt": oldest, "sessions": sessions}

    def protect(self, session_id, enabled):
        folder = self.directory(session_id)
        marker = folder / ".protected"
        if enabled:
            marker.write_text("Protected manually by user.\n", encoding="utf-8")
        else:
            marker.unlink(missing_ok=True)
        return bool(enabled)

    def cleanup(self, *, excluded=(), all_completed=False, now=None):
        excluded = {Path(x) for x in excluded if x}
        now = now or datetime.now(timezone.utc)
        removed, freed = [], 0
        if not self.root.is_dir():
            return {"removed": removed, "freedBytes": freed}
        for folder in self.root.iterdir():
            if not folder.is_dir() or folder.is_symlink() or folder in excluded:
                continue
            info = self.info(folder)
            if info["protected"] or not info["complete"]:
                continue
            finished = utc_date(info["finishedAt"])
            if finished is None or finished > now:
                continue
            if not all_completed and now - finished <= timedelta(days=self.retention_days):
                continue
            try:
                size = info["sizeBytes"]
                shutil.rmtree(folder)
                removed.append(folder.name)
                freed += size
            except OSError:
                # Leave a partially inaccessible session for later investigation.
                continue
        return {"removed": removed, "freedBytes": freed}

    def recover_session(self, weekend, session_num, *, current_session_id=None):
        """Read last durable SDK/pace checkpoint for the SAME official session.

        Only exact numeric iRacing SessionID/SubSessionID/TrackID/SessionNum match.
        Never infer an official position from a cached checkpoint.
        """
        if not isinstance(weekend, dict) or not self.root.is_dir():
            return None
        keys=("SessionID","SubSessionID","TrackID")
        if any(weekend.get(key) is None for key in keys):
            return None
        try:
            session_num=int(session_num)
        except (TypeError,ValueError):
            return None
        # Filenames start with sortable UTC microsecond timestamps. Scan a
        # bounded set and inspect only JSON metadata + a small checkpoint file.
        folders=sorted((p for p in self.root.iterdir() if p.is_dir() and
                        not p.is_symlink()),reverse=True)
        for folder in folders[:120]:
            if current_session_id and folder.name==current_session_id:
                continue
            try:
                session=json.loads((folder/"session.json").read_text(encoding="utf-8"))
                meta=session.get("metadata") or {}
                if (meta.get("sessionId")!=weekend["SessionID"] or
                    meta.get("subSessionId")!=weekend["SubSessionID"] or
                    meta.get("trackId")!=weekend["TrackID"] or
                    meta.get("sessionNum")!=session_num):
                    continue
                recovery=json.loads((folder/"recovery.json").read_text(encoding="utf-8"))
                if not isinstance(recovery,dict):
                    continue
                return {"fromSessionId":folder.name,
                        "carIdx":meta.get("carIdx"),
                        "lastObservedAt":recovery.get("lastObservedAt"),
                        "grid":recovery.get("grid") or {},
                        "roster":recovery.get("roster") or {},
                        "competitors":recovery.get("competitors") or {},
                        "ownLaps":recovery.get("ownLaps") or []}
            except (OSError,ValueError,TypeError,AttributeError):
                continue
        return None

    def export(self, session_id, reports_root):
        folder = self.directory(session_id)
        reports_root = Path(reports_root)
        reports_root.mkdir(parents=True, exist_ok=True)
        dest = reports_root / ("ZRE_SESSION_" + folder.name + ".zip")
        temp = dest.with_suffix(".zip.tmp")
        try:
            with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5) as z:
                for p in folder.iterdir():
                    if p.is_file() and not p.is_symlink() and not p.name.endswith(".tmp"):
                        z.write(p, arcname=folder.name + "/" + p.name)
            temp.replace(dest)
        finally:
            temp.unlink(missing_ok=True)
        return dest
