"""Functional storage and retention regressions, no user data touched."""
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from server.session_archive import SessionArchive
from server.session_recorder import SessionRecorder

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)

def make_session(root, name, ended, *, started=None, protect=False):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    metadata = {"sessionId": name, "startedAt": (started or (NOW-timedelta(days=9))).isoformat(),
                "metadata": {"track":"Test", "sessionType":"Practice"}}
    (folder/"session.json").write_text(json.dumps(metadata), encoding="utf-8")
    summary = {"events": 3}
    if ended is not None:
        summary["finishedAt"] = ended.isoformat()
    (folder/"summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (folder/"timeline.jsonl").write_text('{"type":"lap"}\n', encoding="utf-8")
    if protect:
        (folder/".protected").touch()
    return folder

class StorageArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"session_logs"
        self.archive=SessionArchive(self.root)

    def test_seven_days_from_finished_not_mtime_or_start(self):
        aged=make_session(self.root,"old",NOW-timedelta(days=8))
        recent=make_session(self.root,"recent",NOW-timedelta(days=5),
                            started=NOW-timedelta(days=15))
        result=self.archive.cleanup(now=NOW)
        self.assertIn("old",result["removed"])
        self.assertFalse(aged.exists())
        self.assertTrue(recent.exists())

    def test_protected_active_and_incomplete_never_auto_delete(self):
        protected=make_session(self.root,"protected",NOW-timedelta(days=20),protect=True)
        active=make_session(self.root,"active",NOW-timedelta(days=20))
        incomplete=make_session(self.root,"recovery",None)
        result=self.archive.cleanup(now=NOW,excluded=[active])
        self.assertEqual(result["removed"],[])
        self.assertTrue(protected.exists())
        self.assertTrue(active.exists())
        self.assertTrue(incomplete.exists())
        self.assertEqual(self.archive.status()["retentionDays"],7)

    def test_manual_clean_requires_finish_and_no_protection(self):
        a=make_session(self.root,"a",NOW-timedelta(hours=1))
        p=make_session(self.root,"p",NOW-timedelta(days=20),protect=True)
        waiting=make_session(self.root,"waiting",None)
        result=self.archive.cleanup(all_completed=True,now=NOW)
        self.assertEqual(result["removed"],["a"])
        self.assertFalse(a.exists())
        self.assertTrue(p.exists())
        self.assertTrue(waiting.exists())

    def test_protection_and_retention_are_persistent(self):
        folder=make_session(self.root,"session_one",NOW-timedelta(days=20))
        self.archive.protect(folder.name,True)
        self.archive.configure(14)
        reloaded=SessionArchive(self.root)
        self.assertEqual(reloaded.retention_days,14)
        self.assertTrue(reloaded.info(folder)["protected"])
        self.assertFalse(reloaded.cleanup(now=NOW)["removed"])
        reloaded.protect(folder.name,False)
        self.assertEqual(reloaded.cleanup(now=NOW)["removed"],["session_one"])

    def test_export_zip_is_safe_and_outside_temporary_retention(self):
        folder=make_session(self.root,"session_two",NOW-timedelta(days=20))
        reports=Path(self.temp.name)/"reports"
        path=self.archive.export(folder.name,reports)
        self.assertTrue(path.exists())
        with zipfile.ZipFile(path) as z:
            self.assertIn("session_two/session.json",z.namelist())
            self.assertIn("session_two/timeline.jsonl",z.namelist())
        self.archive.cleanup(now=NOW)
        self.assertTrue(path.exists())
        with self.assertRaises(ValueError):
            self.archive.export("../session_two",reports)

    def test_unparseable_finish_and_future_timestamps_not_deleted(self):
        bad=make_session(self.root,"bad",NOW-timedelta(days=8))
        marker=bad/"summary.json"
        marker.write_text(json.dumps({"finishedAt":"unknown"}), encoding="utf-8")
        future=make_session(self.root,"future",NOW+timedelta(days=1))
        self.assertEqual(self.archive.cleanup(now=NOW)["removed"],[])
        self.assertTrue(future.exists())

    def test_rotations_never_overwrite_seven_day_history(self):
        rec=SessionRecorder(Path(self.temp.name)/"session_replay.jsonl",max_bytes=200)
        rec.root=self.root
        rec.archive=self.archive
        rec.start_session("id-1")
        for i in range(70):
            rec.write({"type":"observation","iteration":i,"details":"A"*80})
        rec.finish_session()
        self.assertTrue(rec.flush(15))
        folders=list(self.root.glob("*id-1*"))
        self.assertEqual(len(folders),1)
        files=list(folders[0].glob("timeline*.jsonl"))
        self.assertGreater(len(files),3)
        events=[json.loads(line) for file in files for line in file.read_text().splitlines()]
        self.assertEqual(sorted(e["iteration"] for e in events),list(range(70)))

    def test_sdk_capture_records_full_context_dedup_and_nonfinite_values(self):
        rec=SessionRecorder(Path(self.temp.name)/"session_replay.jsonl")
        rec.root=self.root
        rec.archive=self.archive
        rec.start_session("id-2")
        source={"Lap":12,"Speed":130.5,"Throttle":.81,"Brake":float("nan"),
                "CarIdxLap":[12,13],"SessionNum":0,
                "SessionInfo":{"Sessions":[{"SessionType":"Race","ResultsPositions":[{"CarIdx":0}]}]},
                "DriverInfo":{"Drivers":[{"CarIdx":0,"UserName":"TEST"}]}}
        get=lambda k:source.get(k)
        rec.observe_sdk(get,session_time=10.0)
        rec.observe_sdk(get,session_time=10.0)
        rec.observe_sdk(get,session_time=10.12)
        rec.observe_sdk(get,session_time=12.50)
        rec.finish_session()
        self.assertTrue(rec.flush(15))
        folder=next(self.root.glob("*id-2*"))
        lines=[json.loads(x) for x in (folder/"timeline.jsonl").read_text().splitlines()]
        telemetry=[x for x in lines if x["type"]=="sdk_telemetry"]
        self.assertEqual(len(telemetry),3)
        self.assertIsNone(telemetry[0]["fields"]["Brake"])
        self.assertEqual(sum(x["type"]=="sdk_roster" for x in lines),1)
        self.assertEqual(sum(x["type"]=="sdk_grid" for x in lines),2)

if __name__=="__main__":
    unittest.main()
