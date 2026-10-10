"""Quali 2.6.6: SDK truth, simulated runs, identity, dedupe and valid comparison."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from server.quali_runs import QualiRuns
from server import iracing_bridge as bridge

ID1="SubSession:77,Num:0,Track:12,Car:8"
ID2="SubSession:77,Num:1,Track:12,Car:8"


class Recorder:
    def __init__(self):self.events=[]
    def write(self,e):self.events.append(e)


class QualiRunTests(unittest.TestCase):
    def setUp(self):
        self.recorder=Recorder();self.q=QualiRuns(self.recorder)
        self.q.observe(ID1,"Practice",3,.45,120)

    def test_official_activation_and_sdk_identity(self):
        self.q.observe(ID1,"Lone Qualify",5,.2,150)
        s=self.q.snapshot()
        self.assertEqual(s["qualifyingMode"],"official")
        self.assertFalse(s["manualOverrideActive"])
        self.assertEqual(s["activeRun"]["kind"],"official")
        self.assertFalse(self.q.command("simulate"))

    def test_simulated_without_mutating_session_type(self):
        self.assertTrue(self.q.command("simulate"))
        s=self.q.snapshot()
        self.assertEqual(s["officialSessionType"],"practice")
        self.assertTrue(s["manualOverrideActive"])
        self.assertEqual(s["activeRun"]["officialSessionIdentity"],ID1)

    def test_partial_lap_excluded_then_full_lap_recorded(self):
        self.q.command("simulate")
        self.assertIsNone(self.q.note_lap(4,90,clean=True,sdk_best=True))
        self.assertIsNotNone(self.q.note_lap(5,88.5,clean=True,sdk_best=True))
        self.assertEqual(len(self.q.current["attempts"]),1)

    def test_new_run_keeps_original_and_isolates_best(self):
        self.q.command("simulate")
        self.q.note_lap(5,88,sdk_best=True)
        old=self.q.current["runId"]
        self.assertTrue(self.q.command("new_run"))
        self.assertNotEqual(self.q.current["runId"],old)
        self.assertIsNone(self.q.current["bestValidLap"])
        self.assertEqual(self.q.runs[0]["bestValidLap"],88)
        self.assertEqual(self.q.runs[0]["status"],"CLOSED")

    def test_training_returns_and_new_simulation_is_new_run(self):
        self.q.command("simulate");old=self.q.current["runId"]
        self.assertTrue(self.q.command("training"))
        self.assertIsNone(self.q.mode)
        self.assertTrue(self.q.command("simulate"))
        self.assertNotEqual(old,self.q.current["runId"])

    def test_browser_reconnect_and_repeated_packets_do_not_create_runs(self):
        self.q.command("simulate");id=self.q.current["runId"]
        for _ in range(50):self.q.observe(ID1,"Practice",3,.6,122)
        self.q.command("simulate")
        self.assertEqual(len(self.q.runs),1)
        self.assertEqual(self.q.current["runId"],id)

    def test_duplicate_lap_does_not_inflate_counts(self):
        self.q.command("simulate")
        for _ in range(20):self.q.note_lap(5,88,sdk_best=True)
        self.assertEqual(len(self.q.current["attempts"]),1)
        self.assertEqual(sum(e["type"]=="quali_attempt" for e in self.recorder.events),1)

    def test_unknown_validity_is_not_official_valid_or_invalid(self):
        self.q.command("simulate")
        attempt=self.q.note_lap(5,90,clean=False,sdk_best=False)
        self.assertEqual(attempt["status"],"PENDING VALIDATION")
        self.assertIsNone(self.q.current["bestValidLap"])
        self.assertEqual(attempt["confidence"],"LOW")

    def test_missing_telemetry_and_nonfinite_lap_are_ignored(self):
        self.q.command("simulate")
        self.assertIsNone(self.q.note_lap(5,None))
        self.assertIsNone(self.q.note_lap(5,float("nan")))
        self.assertEqual(self.q.current["attempts"],[])

    def test_pit_lap_does_not_replace_best(self):
        self.q.command("simulate")
        entry=self.q.note_lap(5,120,in_pit=True)
        self.assertEqual(entry["status"],"IN LAP")
        self.assertIsNone(self.q.current["bestValidLap"])

    def test_auto_race_priority(self):
        self.q.command("simulate")
        self.q.observe(ID1,"Race",6,.5,200)
        self.assertIsNone(self.q.mode)
        self.assertEqual(self.q.runs[0]["status"],"CLOSED")
        self.assertFalse(self.q.command("simulate"))

    def test_change_session_closes_and_preserves_previous(self):
        self.q.command("simulate")
        self.q.observe(ID2,"Practice",1,.1,12)
        self.assertIsNone(self.q.mode)
        self.assertEqual(len(self.q.runs),1)
        self.assertEqual(self.q.runs[0]["officialSessionIdentity"],ID1)

    def test_official_session_after_manual_starts_distinct_official_run(self):
        self.q.command("simulate")
        self.q.observe(ID2,"Qualify",1,.1,12)
        self.assertEqual(self.q.snapshot()["qualifyingMode"],"official")
        self.assertEqual(len(self.q.runs),2)
        self.assertEqual(self.q.current["kind"],"official")

    def test_two_clients_share_exact_one_backend_state(self):
        source=QualiRuns()
        source.observe(ID1,"Practice",10,.2,60)
        assert source.command("simulate")
        client1=source.snapshot();client2=source.snapshot()
        self.assertEqual(client1["activeRunId"],client2["activeRunId"])
        self.assertEqual(len(source.runs),1)

    def test_sdk_delta_flags_and_zero(self):
        source=bridge.DashboardSource(force_demo=True)
        values={"LapDeltaToBestLap":0.0,"LapDeltaToBestLap_OK":True,
                "LapDeltaToOptimalLap":-0.4,"LapDeltaToOptimalLap_OK":False}
        source.get=lambda key,default=None:values.get(key,default)
        self.assertTrue(source._quali_sdk_delta("LapDeltaToBestLap")["valid"])
        self.assertEqual(source._quali_sdk_delta("LapDeltaToBestLap")["value"],0)
        self.assertIsNone(source._quali_sdk_delta("LapDeltaToOptimalLap")["value"])
        self.assertIsNone(source._quali_sdk_delta("LapDeltaToSessionBestLap")["value"])

    def test_dynamic_sector_boundaries_sdk_only(self):
        source=bridge.DashboardSource(force_demo=True)
        reading={"SplitTimeInfo":{"Sectors":[{"SectorStartPct":0.0},{"SectorStartPct":.28},
                                             {"SectorStartPct":.55},{"SectorStartPct":.81}]}}
        source.get=lambda key,default=None:reading.get(key,default)
        self.assertEqual(source._sector_boundaries(),[0,.28,.55,.81])
        reading["SplitTimeInfo"]={}
        self.assertEqual(source._sector_boundaries(),[])

    def test_audio_not_queued_in_qualifying(self):
        s=bridge.DashboardSource(force_demo=True)
        s.audio_coach=Mock();s.coach.finish=Mock(return_value=True)
        s.coach.advice=[(1,.4,"Frenada","Revisar",.2,"ENTRY")]
        s.coach_session_mode="qualifying"
        s.quali.observe(ID1,"Qualify",2,.1,60)
        s.finalize_lap({"lap":4,"usage":None,"sectors":[],"valid":True},90,None)
        s.audio_coach.say.assert_not_called()


if __name__=="__main__":unittest.main()
