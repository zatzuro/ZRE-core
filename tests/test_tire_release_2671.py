"""Senior P1-01..20: controlled SDK observations; no physical iRacing claim."""
import copy
import json
from pathlib import Path
from unittest.mock import patch
import unittest
import test_tire_reconciliation_2671 as fixtures
garage,SESSION,WEEKEND,OWNER=fixtures.garage,fixtures.SESSION,fixtures.WEEKEND,fixtures.OWNER
from server.setup_snapshot import snapshot_from_sdk, compare_setups
from server.setup_engineer import SetupEngineer
from server.stint_engineering_snapshot import capture_garage_tires
from server.stint_store import StintStore
from server.setup_report import write_setup_report, render_setup_report

class TireRelease2671(unittest.TestCase):
    setUp=fixtures.TireEngineering2671.setUp
    finish=fixtures.TireEngineering2671.finish
    def observed(self, value=None, clock=2902, identity=None):
        return self.engine.reconcile_tires(capture_garage_tires(value or garage(True), clock),
                                           identity or WEEKEND, in_pits=True)

    def test_P1_01_repeated_raw_never_zero_wear_claim(self):
        record=self.finish()
        self.assertEqual(record['tires']['delta'], {})
        self.assertEqual(record['tires']['provisionalDelta'], {})
        self.assertEqual(record['tires']['inspection']['freshness'], 'NOT_VERIFIED')

    def test_P1_02_separate_observation_attribution_set(self):
        self.finish();record=self.observed()
        self.assertEqual(record['tires']['inspection']['status'], 'OBSERVED')
        self.assertEqual(record['tires']['inspection']['attribution'], 'UNVERIFIED')
        self.assertEqual(record['tires']['inspection']['comparison'], 'NOT_COMPARABLE')
        self.assertEqual(record['tires']['delta'], {})

    def test_P1_03_repeated_garage_remains_pending(self):
        self.finish();self.assertIsNone(self.observed(garage()))
        self.assertEqual(self.engine.last_saved['tires']['inspection']['status'], 'PENDING')

    def test_P1_04_preserve_original_source_samples(self):
        original=copy.deepcopy(self.finish()['tires']['end'])
        record=self.observed()
        self.assertEqual(record['tires']['end'], original)
        self.assertIn('garageAtEnd', record['tires'])

    def test_P1_05_revision_alone_not_inspection(self):
        self.finish();new=garage();new['UpdateCount']=100
        self.assertIsNone(self.observed(new))

    def test_P1_06_pressure_only_never_certifies_wear(self):
        self.finish();new=garage();new['TiresAero']['LeftFront']['LastHotPressure']='185 kPa'
        record=self.observed(new)
        self.assertEqual(record['tires']['wheelEvidence']['RF']['freshness'], 'REPEATED')
        self.assertEqual(record['tires']['inspection']['attribution'], 'UNVERIFIED')

    def test_P1_07_requires_pit_and_matching_session_number(self):
        self.finish();self.assertIsNone(self.observed(identity={**WEEKEND,'SessionNum':1}))
        self.assertIsNone(self.engine.reconcile_tires(capture_garage_tires(garage(True),2902),WEEKEND,in_pits=False))

    def test_P1_08_partial_tire_replacement_per_wheel(self):
        self.finish(baseline=garage(True));new=garage(True)
        new['TiresAero']['LeftFront']['TreadRemaining']='100% 100% 100%'
        record=self.observed(new)
        self.assertEqual(record['tires']['wheelEvidence']['LF']['attribution'], 'AMBIGUOUS')
        self.assertEqual(record['tires']['wheelEvidence']['RF']['freshness'], 'REPEATED')
        self.assertEqual(record['tires']['delta'], {})

    def test_P1_09_next_stint_closes_window_durably(self):
        self.finish()
        self.engine.start_stint(SESSION,{'source':'SDK'},session_time=2903)
        old=self.engine.store.load_stints(SESSION['car'],SESSION['track'],SESSION['layout'])[0]
        self.assertTrue(old['tires']['inspection']['autoReconcileClosed'])
        self.assertIn('NEXT_STINT_STARTED',old['tires']['inspection']['reason'])

    def test_P1_10_owner_driver_team_changes_rejected(self):
        for field,value in [('car_idx',4),('driver_user_id','999'),('team_id','other'),('scope','team')]:
            with self.subTest(field=field):
                self.engine.set_owner(OWNER);self.finish()
                self.engine.set_owner({**OWNER,field:value})
                self.assertIsNone(self.observed())

    def test_P1_11_offline_zero_ids_need_runtime_generation(self):
        record=self.finish();record['session'].update(sessionID=0,subSessionID=0,trackID=0)
        zero={**WEEKEND,'SessionID':0,'SubSessionID':0,'TrackID':0}
        self.assertIsNone(self.observed(identity={**zero,'SessionGeneration':'another-run'}))
        self.assertIsNotNone(self.observed(identity=zero))

    def test_P1_12_restart_idempotent_without_duplicate(self):
        record=self.finish();self.observed()
        self.engine=SetupEngineer(self.root);self.engine.set_owner(OWNER)
        self.assertIsNone(self.observed(clock=2903))
        records=self.engine.store.load_stints(SESSION['car'],SESSION['track'],SESSION['layout'])
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['stintId'], record['stintId'])

    def test_P1_13_atomic_json_failure_preserves_original(self):
        p=self.root/'atomic.json';StintStore._write_json(p,{'original':1})
        with patch.object(Path,'replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):StintStore._write_json(p,{'new':2})
        self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {'original':1})

    def test_P1_14_partial_fields_never_zero_fill(self):
        self.finish();partial={'TiresAero':{'LeftFront':garage(True)['TiresAero']['LeftFront']}}
        record=self.observed(partial)
        self.assertEqual(record['tires']['wheelEvidence']['RF']['freshness'], 'UNAVAILABLE')
        self.assertEqual(record['tires']['garageAtEnd']['wheels'].get('RF',{}).get('lastHotPressureKPa'),None)

    def test_P1_15_pressure_units_orientation(self):
        sample=capture_garage_tires({'TiresAero':{'RightFront':{'LastHotPressure':'26.83 psi',
            'LastTempsIMO':'161F 167F 172F','TreadRemaining':'66% 68% 88%'}}},2902)
        data=sample['wheels']['RF']
        self.assertAlmostEqual(data['lastHotPressureKPa'],185,delta=1)
        self.assertEqual(data['treadRemainingPct']['inside'],66)
        self.assertEqual(data['treadRemainingPct']['outside'],88)

    def test_P1_16_second_inspection_no_rewrite(self):
        self.finish();self.observed()
        with patch.object(self.engine.store,'save_stint') as save:
            self.assertIsNone(self.observed(clock=2903));save.assert_not_called()

    def test_P1_17_normalized_fingerprint_inspection_ignored(self):
        a=snapshot_from_sdk(garage());b=snapshot_from_sdk(garage(True))
        self.assertEqual(a['setupFingerprintV2'],b['setupFingerprintV2'])
        self.assertNotEqual(a['fingerprint'],b['fingerprint']) # legacy retained
        self.assertEqual(compare_setups(a,b),[])

    def test_P1_18_real_settings_still_change_identity(self):
        base={'Chassis':{'Wing':9.5,'ARB':5,'Camber':-3,'Toe':.1},
              'TiresAero':{'LeftFront':{'StartingPressure':'159 kPa'}}}
        for section,key,value in [('Chassis','Wing',8.5),('Chassis','ARB',4),('Chassis','Camber',-2),
                                  ('Chassis','Toe',.2),('TiresAero','LeftFront',{'StartingPressure':'160 kPa'})]:
            with self.subTest(key=key):
                changed=copy.deepcopy(base);changed[section][key]=value
                a=snapshot_from_sdk(base);b=snapshot_from_sdk(changed)
                self.assertNotEqual(a['setupFingerprintV2'],b['setupFingerprintV2'])
                self.assertTrue(compare_setups(a,b))

    def test_P1_19_markdown_atomic_and_honest(self):
        self.finish();record=self.observed();p=self.engine.last_report_path
        report=p.read_text(encoding="utf-8");self.assertIn('UNVERIFIED',report);self.assertIn('NO COMPARABLE',report)
        with patch.object(Path,'replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):write_setup_report(p,record)
        self.assertEqual(p.read_text(encoding="utf-8"),report)
        legacy=copy.deepcopy(record);legacy['tires']['inspection']={'status':'CONFIRMED'}
        self.assertIn('LEGACY_CONFIRMED_UNVERIFIED',render_setup_report(legacy))

    def test_P1_20_time_window_rejects_backwards_and_expires(self):
        self.finish();self.assertIsNone(self.observed(clock=2899))
        record=self.observed(clock=3201)
        self.assertTrue(record['tires']['inspection']['autoReconcileClosed'])
        self.assertEqual(record['tires']['inspection']['reason'],'INSPECTION_WINDOW_EXPIRED')

    def test_P1_13b_report_failure_retry_after_durable_amendment(self):
        self.finish()
        with patch('server.setup_engineer.write_setup_report',side_effect=OSError('disk failure')):
            record=self.observed()
        self.assertEqual(record['tires']['inspection']['status'],'OBSERVED')
        self.assertIsNone(self.engine.last_report_path)
        self.assertIsNone(self.observed(clock=2903))
        self.assertIn('OBSERVED',self.engine.last_report_path.read_text(encoding="utf-8"))
        self.assertEqual(len(self.engine.store.load_stints(SESSION['car'],SESSION['track'],SESSION['layout'])),1)
