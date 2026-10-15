"""P1 regression: Indianapolis Stint10 deferred tire inspection and Stint07 control.

These are SDK-shaped samples derived from the user's report, NOT a physical
iRacing session. Validate reporting semantics and original stint identity.
"""
import json
import tempfile
import unittest
from pathlib import Path
from server.setup_engineer import SetupEngineer
from server.stint_engineering_snapshot import (
    capture_tires,capture_garage_tires,garage_signature
)

WHEEL_MAP={"LF":("LeftFront","OMI"),"RF":("RightFront","IMO"),
           "LR":("LeftRear","OMI"),"RR":("RightRear","IMO")}
OWNER={"authorized":True,"scope":"own","car_idx":1,
       "team_id":"mclaren","driver_user_id":"101","reason":"SDK_CONFIRMED"}
SESSION={"car":"McLaren 720S GT3 Evo","track":"Indianapolis Motor Speedway",
         "layout":"Road Course","session":"Practice","driver":"Piloto 101",
         "sessionNum":0,"sessionGeneration":"test-generation","sessionID":420,"subSessionID":17,"trackID":18}
WEEKEND={"SessionNum":0,"SessionGeneration":"test-generation","SessionID":420,"SubSessionID":17,"TrackID":18}

def garage(updated=False):
    real={"LF":(185,[72,75,78],[81,63,63]),
          "RF":(179,[71,67,60],[66,68,88]),
          "LR":(179,[70,72,75],[75,65,65]),
          "RR":(173,[68,65,58],[70,70,85])}
    tires={}
    for wheel,(key,order) in WHEEL_MAP.items():
        hot,temps,tread=real[wheel] if updated else (159,[35,35,35],[100,100,100])
        tires[key]={"ColdPressure":"159 kPa",
                    "LastHotPressure":str(hot)+" kPa",
                    "LastTemps"+order:" ".join(str(x)+"C" for x in temps),
                    "TreadRemaining":" ".join(str(x)+"%" for x in tread)}
    return {"UpdateCount":2 if updated else 1,"TiresAero":tires}

def raw_tires(used=False):
    values={}
    for wheel in WHEEL_MAP:
        values.update({wheel+"coldPressure":159.0,
                       wheel+"tempCL":75 if used else 35,
                       wheel+"tempCM":76 if used else 35,
                       wheel+"tempCR":77 if used else 35,
                       wheel+"wearL":.753 if used else 1.0,
                       wheel+"wearM":.80 if used else 1.0,
                       wheel+"wearR":.84 if used else 1.0})
    return capture_tires(values.get)

class TireEngineering2671(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.engine=SetupEngineer(self.root)
        self.engine.set_owner(OWNER)

    def finish(self,valid=32,end=None,baseline=None):
        self.engine.start_stint(SESSION,{"fingerprint":"bca2afe9c7605e3d",
            "metadata":{"setupName":"INDIANAPOLIS FULLTANQUE v2.sto"},
            "source":"SDK"},conditions={"trackTempC":33},fuel_start=104,
            session_time=10,tires_start=raw_tires(),
            garage_tires_start=capture_garage_tires(baseline or garage(),10))
        return self.engine.finish_stint({"validLaps":valid,
               "representativeAverage":85.2572,"bestLap":84.5203},
               fuel_end=2,session_time=2900,tires_end=end or raw_tires())

    def test_stint10_provisional_then_confirm_garage_same_stint(self):
        old=self.finish()
        folder=self.engine.store.context_dir(*[SESSION[k] for k in ("car","track","layout")])/"stints"
        self.assertEqual(len(list(folder.glob("stint-*.json"))),1)
        self.assertEqual(old["tires"]["inspection"]["status"],"PENDING")
        initial_report=self.engine.last_report_path.read_text(encoding="utf-8")
        self.assertIn("NO DISPONIBLE",initial_report)
        self.assertIn("NO CONFIRMADO",initial_report)
        stale=capture_garage_tires(garage(),2901)
        self.assertIsNone(self.engine.reconcile_tires(stale,WEEKEND,in_pits=True))
        self.assertEqual(self.engine.last_saved["tires"]["inspection"]["status"],"PENDING")
        fresh=capture_garage_tires(garage(updated=True),2902)
        updated=self.engine.reconcile_tires(fresh,WEEKEND,in_pits=True)
        self.assertEqual(updated["stintNumber"],old["stintNumber"])
        self.assertEqual(len(list(folder.glob("stint-*.json"))),1)
        self.assertEqual(updated["tires"]["inspection"]["status"],"OBSERVED")
        self.assertEqual(updated["tires"]["garageAtEnd"]["wheels"]["LF"]["lastHotPressureKPa"],185)
        self.assertEqual(updated["tires"]["garageAtEnd"]["wheels"]["LF"]["treadRemainingPct"]["middle"],63)
        self.assertEqual(updated["tires"]["garageAtEnd"]["wheels"]["RF"]["treadRemainingPct"]["inside"],66)
        self.assertEqual(updated["tires"]["garageAtEnd"]["wheels"]["RR"]["treadRemainingPct"]["outside"],85)
        self.assertEqual(updated["tires"]["garageAtEnd"]["wheels"]["LR"]["lastTempsC"]["outside"],70)
        self.assertEqual(updated["tires"]["delta"],{})
        report=self.engine.last_report_path.read_text(encoding="utf-8")
        self.assertIn("185",report);self.assertIn("63",report)
        self.assertIn("NO COMPARABLE",report)
        self.assertIn("GARAGE INSPECCIONADO",report)
        self.assertEqual(json.loads((folder/"stint-001.json").read_text(encoding="utf-8"))["tires"]["inspection"]["status"],"OBSERVED")

    def test_stint07_differentiated_raw_samples_remain_provisional(self):
        record=self.finish(valid=27,end=raw_tires(used=True))
        self.assertEqual(record["tires"]["inspection"]["status"],"PENDING")
        self.assertAlmostEqual(record["tires"]["provisionalDelta"]["LF"]["wearRemainingDelta"]["left"],-.247)
        report=self.engine.last_report_path.read_text(encoding="utf-8")
        self.assertIn("PROVISIONAL",report)
        self.assertIn("NO CONFIRMADO",report)

    def test_no_update_or_incomplete_snapshot_never_falsely_confirms(self):
        old=self.finish()
        stale=capture_garage_tires(garage(),2901)
        self.assertIsNone(self.engine.reconcile_tires(stale,WEEKEND,in_pits=True))
        incomplete=capture_garage_tires({},2903)
        self.assertIsNone(self.engine.reconcile_tires(incomplete,WEEKEND,in_pits=True))
        self.assertEqual(old["tires"]["inspection"]["status"],"PENDING")

    def test_two_stints_no_cross_attribution_after_new_start(self):
        previous=self.finish()
        self.engine.start_stint(SESSION,{"fingerprint":"second","source":"SDK"},
            session_time=2902,garage_tires_start=capture_garage_tires(garage(),2902))
        self.assertIsNone(self.engine.reconcile_tires(capture_garage_tires(garage(True),2903),WEEKEND,in_pits=True))
        self.assertEqual(self.engine.store.load_stints(SESSION["car"],SESSION["track"],SESSION["layout"])[0]["tires"]["inspection"]["status"],"PENDING")

    def test_spotter_wrong_identity_or_session_denied(self):
        self.finish()
        updated=capture_garage_tires(garage(True),2902)
        self.assertIsNone(self.engine.reconcile_tires(updated,{**WEEKEND,"SessionID":999},in_pits=True))
        self.assertIsNone(self.engine.reconcile_tires(updated,WEEKEND,in_pits=False))
        self.engine.set_owner({**OWNER,"car_idx":4})
        self.assertIsNone(self.engine.reconcile_tires(updated,WEEKEND,in_pits=True))

    def test_restart_recovers_pending_and_reconciles_only_with_same_owner(self):
        self.finish()
        fresh=SetupEngineer(self.root)
        self.assertIsNotNone(fresh.pending_tire_record)
        fresh.set_owner(OWNER)
        updated=fresh.reconcile_tires(capture_garage_tires(garage(True),2905),WEEKEND,in_pits=True)
        self.assertEqual(updated["tires"]["inspection"]["status"],"OBSERVED")

    def test_orientation_and_explicit_pressure_units(self):
        snapshot=capture_garage_tires(garage(True),2905)
        self.assertEqual(snapshot["availableFields"],28)
        self.assertEqual(snapshot["wheels"]["LF"]["physicalOrder"],"OMI")
        self.assertEqual(snapshot["wheels"]["RF"]["physicalOrder"],"IMO")
        self.assertEqual(snapshot["wheels"]["RF"]["lastTempsC"]["inside"],71)
        self.assertEqual(snapshot["wheels"]["LF"]["lastTempsC"]["outside"],72)
        self.assertNotEqual(garage_signature(snapshot),garage_signature(capture_garage_tires(garage())))
        psi=capture_garage_tires({"TiresAero":{"LeftFront":{
            "LastHotPressure":"26.83 psi","LastTempsOMI":"161F 167F 172F",
            "TreadRemaining":"81% 63% 63%"}}})
        self.assertAlmostEqual(psi["wheels"]["LF"]["lastHotPressureKPa"],185,delta=1)
        self.assertAlmostEqual(psi["wheels"]["LF"]["lastTempsC"]["outside"],71.67,delta=1)

if __name__=="__main__":unittest.main()
