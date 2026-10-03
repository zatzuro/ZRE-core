"""2.6.4 simulated SDK contracts, session isolation and local journals."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from server.session_intelligence import build_intelligence, predict_next, reconcile_stop, temporal_gap, strategy_intelligence
from server.session_recorder import SessionRecorder
from server import iracing_bridge as b
import updater

class Intelligence264Tests(unittest.TestCase):
    def setUp(self):
        self.history={};self.now=0;self.values={'SessionTime':0,'CarIdxLapCompleted':[0,0], 'CarIdxLap':[1,1], 'CarIdxLastLapTime':[78,None], 'CarIdxBestLapTime':[78,78], 'CarIdxOnPitRoad':[False,False],'LapBestLapTime':78,'CarIdxEstTime':[15.6,23.4],'PitsOpen':True}
        self.cars={0:{'CarClassID':1,'CarNumber':'1'},1:{'CarClassID':1,'CarNumber':'23','UserName':'Rival'}}
        self.results={1:{'LapsComplete':0,'LastTime':None,'Position':2,'ClassPosition':1,'Incidents':0}}
        self.pct=[.2,.3];self.surface=[3,3]
    def get(self,k,default=None):return self.values.get(k,default)
    def sample(self,lap=None,seconds=None,pit=None,advance=10,session='Race'):
        self.now+=advance;self.values['SessionTime']=self.now
        if lap is not None:
            self.values['CarIdxLapCompleted'][1]=lap;self.values['CarIdxLap'][1]=lap+1
            self.values['CarIdxLastLapTime'][1]=seconds;self.results[1].update(LapsComplete=lap,LastTime=seconds)
        if pit is not None:self.values['CarIdxOnPitRoad'][1]=pit
        self.intel=build_intelligence(self.get,{'TeamRacing':True,'NumCarClasses':2},{'SessionType':session},self.cars,self.results,0,1,self.pct,self.surface,self.history)
        return self.intel['competitors']['observed'][0]
    def baseline(self):
        self.sample()
        for lap,seconds in enumerate([78,78,79],1):self.sample(lap,seconds)
    def test_continuously_live_anomalous_pair_recovery(self):
        self.baseline();self.assertEqual(self.sample(4,97)['anomalyState'],'FIRST_ANOMALY')
        self.assertEqual(self.sample(5,144)['anomalyState'],'CORROBORATED')
        r=self.sample(6,80);self.assertEqual(len(r['pitHistory']),1)
        self.assertEqual(r['lastPit']['source'],'ZRE_INFERRED');self.assertEqual(r['lastPit']['status'],'PROBABLE')
        self.assertEqual([x['time'] for x in r['cleanLapTimes']],[78,78,79,80]);self.assertEqual(len(r['lapTimes']),6)
        self.assertAlmostEqual(r['lastPit']['abnormalLapExcess'],85)
        self.assertIsNone(r['pitLossEstimate'])
    def test_single_slow_lap_is_not_stop(self):
        self.baseline();self.sample(4,144);r=self.sample(5,78);self.assertEqual(r['pitHistory'],[])
    def test_caution_suppresses_inference(self):
        self.baseline();self.values['SessionFlags']=0x4000
        self.sample(4,97);self.sample(5,144);r=self.sample(6,80);self.assertEqual(r['pitHistory'],[])
    def test_blue_flag_is_not_caution(self):
        self.values['SessionFlags']=0x20;self.sample();self.assertFalse(self.intel['caution'])
    def test_incident_suppresses_cycle(self):
        self.baseline();self.sample(4,97);self.results[1]['Incidents']=4
        self.sample(5,144);r=self.sample(6,80);self.assertEqual(r['pitHistory'],[])
    def test_class_slowdown_suppresses_cycle(self):
        self.baseline();self.cars[2]={'CarClassID':1,'CarNumber':'24'}
        self.history[2]={'cleanLapTimes':[{'lap':i,'time':78} for i in range(3)]}
        for k in ['CarIdxLapCompleted','CarIdxLap','CarIdxLastLapTime','CarIdxBestLapTime','CarIdxOnPitRoad']:self.values[k].append(False if k=='CarIdxOnPitRoad' else 78)
        self.pct.append(.4);self.surface.append(3)
        self.values['CarIdxLastLapTime'][2]=97;r=self.sample(4,97)
        self.assertTrue(r['classSlowdown']);self.assertEqual(r['anomalyState'],'BASELINE')
    def test_sdk_entry_exit_exactly_one(self):
        self.baseline();self.sample(pit=True);self.sample(pit=True);r=self.sample(pit=False)
        self.assertEqual(len(r['pitHistory']),1);self.assertEqual(r['lastPit']['status'],'COMPLETE')
        self.assertEqual(r['lastPit']['pitRoadDurationObserved']['seconds'],20)
        self.assertEqual(r['lastPit']['source'],'SDK_OBSERVED')
    def test_interrupted_pit_observation_lowers_duration_confidence(self):
        self.baseline();self.sample(pit=True);self.surface[1]=-1;self.pct[1]=-1;self.sample()
        self.surface[1]=3;self.pct[1]=.3;r=self.sample(pit=False)
        self.assertEqual(r['lastPit']['pitRoadDurationObserved']['confidence'],'LOW')
        self.assertIsNone(r['pitLossEstimate'])
    def test_inferred_then_sdk_reconciles(self):
        self.baseline();self.sample(4,97);self.sample(5,144);self.sample(6,80)
        r=self.sample(pit=True);self.assertEqual(len(r['pitHistory']),1);self.assertTrue(r['lastPit']['reconciled'])
        r=self.sample(pit=False);self.assertEqual(len(r['pitHistory']),1);self.assertEqual(r['lastPit']['source'],'SDK_OBSERVED')
    def test_sdk_then_inference_reconciles(self):
        stops=[];event=reconcile_stop(stops,{'lap':4,'sessionTime':40,'source':'SDK_OBSERVED','status':'COMPLETE'},78)
        found=reconcile_stop(stops,{'lap':5,'sessionTime':50,'source':'ZRE_INFERRED'},78)
        self.assertIs(found,event);self.assertEqual(len(stops),1)
    def test_two_actual_sdk_stops_remain_two(self):
        stops=[]
        for t in (40,50):reconcile_stop(stops,{'lap':4,'sessionTime':t,'source':'SDK_OBSERVED'},78)
        self.assertEqual(len(stops),2)
    def test_stale_retains_then_reappears(self):
        self.baseline();first=self.sample();self.surface[1]=-1;self.pct[1]=-1
        stale=self.sample();self.assertEqual(stale['presence'],'STALE');self.assertEqual(stale['lastLap'],79)
        self.assertEqual(stale['lastSeenSessionTime'],first['lastSeenSessionTime']);self.assertEqual(stale['lastSeenAgo'],10)
        self.assertIsNone(stale['lapDistPct']);self.assertIsNone(stale['gapEvidence'])
        self.surface[1]=3;self.pct[1]=.4;r=self.sample();self.assertEqual(r['presence'],'LIVE');self.assertEqual(r['lastSeenAgo'],0)
    def test_roster_removal_retains_stale(self):
        self.baseline();del self.cars[1];r=self.sample();self.assertEqual(r['presence'],'STALE');self.assertEqual(r['number'],'23')
    def test_unknown_current_observation_does_not_erase_position(self):
        self.sample();self.surface[1]=-1;self.pct[1]=-1;self.results={};r=self.sample();self.assertEqual(r['position'],2);self.assertEqual(r['classPosition'],2)
    def test_buffers_bounded(self):
        self.sample()
        for lap in range(1,150):r=self.sample(lap,78)
        self.assertEqual(len(r['lapTimes']),24);self.assertEqual(len(r['cleanLapTimes']),12)
    def test_est_time_semantics_and_fallback(self):
        g=temporal_gap(self.get,0,1,.2,.3,78,78)
        self.assertAlmostEqual(g['seconds'],7.8);self.assertEqual(g['source'],'ZRE_INFERRED');self.assertEqual(g['inputSource'],'SDK_OBSERVED')
        self.values['CarIdxEstTime']=[None,None];g=temporal_gap(self.get,0,1,.2,.3,78,78)
        self.assertEqual(g['source'],'ZRE_INFERRED');self.assertEqual(g['confidence'],'LOW')
    def test_wetness_units_and_sentinels(self):
        self.values.update(TrackWetness=1,AirPressure=101300,RelativeHumidity=.6,SessionLapsRemain=32767)
        self.sample();self.assertEqual(self.intel['environment']['wetnessLabel'],'DRY')
        self.assertEqual(self.intel['environment']['fields']['AirPressure']['unit'],'Pa');self.assertIsNone(self.intel['session']['observed']['lapsRemain'])
    def test_prediction_pattern_and_confidence(self):
        p,l=predict_next([{'lap':10},{'lap':25},{'lap':40}]);self.assertEqual((p['fromLap'],p['toLap']),(54,56));self.assertEqual(p['confidence'],'MEDIUM')
        p,l=predict_next([{'lap':10},{'lap':25},{'lap':40},{'lap':55}]);self.assertEqual(p['confidence'],'HIGH')
        self.assertIsNone(predict_next([{'lap':10}])[0]);self.assertIsNone(predict_next([{'lap':10},{'lap':25}],99)[0])
    def test_non_race_never_detects_pits(self):
        self.sample(session='Qualify',pit=True);r=self.sample(session='Qualify',pit=False);self.assertEqual(r['pitHistory'],[])
    def test_pit_excess_updates_after_second_lap(self):
        self.baseline();self.sample(pit=True);self.sample(4,97,pit=False)
        r=self.sample(5,144);self.assertEqual(r['lastPit']['abnormalLapExcess'],85)
        self.assertNotEqual(r['pitLossEstimate']['seconds'],r['lastPit']['pitRoadDurationObserved']['seconds'])
    def test_no_strategy_without_evidence(self):
        rival={'carIdx':1,'number':'23','sameClass':True,'presence':'LIVE','nextPitEstimate':{'fromLap':54,'toLap':56,'confidence':'HIGH'}}
        result=strategy_intelligence([rival],50,40,[2,2,2],{'target':54})
        self.assertFalse(result['available']);self.assertEqual(result['primary']['action'],'NO RECOMMENDATION')
    def test_strategy_required_evidence_and_actions(self):
        rival={'carIdx':1,'number':'23','sameClass':True,'presence':'LIVE','nextPitEstimate':{'fromLap':54,'toLap':56,'confidence':'HIGH'},'cleanPace':82,'cleanLapTimes':[1,2,3],'pitLossEstimate':{'seconds':25,'confidence':'MEDIUM'},'rejoinProjection':{'projectedGapAfterPit':2,'confidence':'MEDIUM','uncertaintySeconds':7},'trendSeconds':1}
        evidence={'planAvailable':True,'fuelSource':'REAL LOCAL','cleanPace':78,'cleanLaps':[1,2,3],'pitsOpen':True,'trafficClear':True}
        self.assertEqual(strategy_intelligence([rival],50,40,[2,2,2],{'target':53},evidence)['primary']['action'],'UNDERCUT')
        self.assertEqual(strategy_intelligence([rival],50,40,[2,2,2],{'target':57},evidence)['primary']['action'],'OVERCUT')
        rival['cleanPace']=78
        self.assertEqual(strategy_intelligence([rival],50,40,[2,2,2],{'target':53},evidence)['primary']['action'],'HOLD')
        for key,value in [('pitsOpen',False),('trafficClear',False),('fuelSource','ESTIMATED')]:
            e={**evidence,key:value};self.assertFalse(strategy_intelligence([rival],50,40,[2,2,2],{'target':53},e)['available'])

class Journal264Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.logger=SessionRecorder(Path(self.temp.name)/'old.jsonl');self.addCleanup(self.logger.close)
    def test_four_files_finish_and_event_only(self):
        self.logger.start_session('session',{'track':'Spa','sessionType':'Race'});folder=self.logger.session_dir
        self.logger.write({'type':'lap','lap':1,'telemetry':[1]*10000});self.logger.finish_session();self.assertTrue(self.logger.flush())
        self.assertTrue(all((folder/n).exists() for n in ['session.json','timeline.jsonl','summary.json','summary.md']))
        self.assertNotIn('telemetry',json.loads((folder/'timeline.jsonl').read_text()))
        self.assertEqual(json.loads((folder/'summary.json').read_text())['finishReason'],'session-change')
    def test_retention_protects_active(self):
        self.logger.start_session('active');self.logger.flush();active=self.logger.session_dir
        old=self.logger.root/'old';old.mkdir();(old/'summary.json').write_text('{}')
        ancient=time.time()-8*86400
        os.utime(old/'summary.json',(ancient,ancient));os.utime(active/'summary.json',(ancient,ancient))
        self.logger.cleanup_old_sessions(force=True);self.assertFalse(old.exists());self.assertTrue(active.exists())
    def test_retention_failure_does_not_propagate(self):
        with patch.object(Path,'iterdir',side_effect=OSError('disk')):self.logger.cleanup_old_sessions(force=True)
        self.assertEqual(self.logger.errors,1)
    def test_conditions_throttled_no_frames(self):
        self.logger.start_session('active');payload={'sessionMode':'Race','sessionIntelligence':{'environment':{'observed':{'WindVel':1}}}}
        for tick in range(100):
            payload['sessionIntelligence']['environment']['observed']['WindVel']=tick/10
            self.logger.observe(payload,tick/10)
        folder=self.logger.session_dir;self.logger.finish_session();self.logger.flush()
        events=[json.loads(x) for x in (folder/'timeline.jsonl').read_text().splitlines()];self.assertEqual(len(events),1)
    def test_prediction_audit(self):
        self.logger.start_session('race');row={'carIdx':1,'presence':'LIVE','lapsComplete':50,'pitHistory':[],'nextPitEstimate':{'fromLap':54,'toLap':56,'confidence':'MEDIUM','source':'ZRE_INFERRED'}}
        payload={'sessionIntelligence':{'competitors':{'observed':[row]}}};self.logger.observe(payload,100)
        row['pitHistory']=[{'eventId':'a','lap':55,'sessionTime':200,'source':'SDK_OBSERVED','status':'COMPLETE'}];self.logger.observe(payload,200)
        folder=self.logger.session_dir;self.logger.finish_session();self.logger.flush();summary=json.loads((folder/'summary.json').read_text())
        self.assertEqual(summary['predictions'],1);self.assertEqual(summary['outcomes'],1);self.assertTrue(summary['predictionResults'][0]['hit'])
        self.assertEqual(summary['predictionResults'][0]['actualPitLap'],55)
    def test_rotation_is_bounded(self):
        self.logger.max_bytes=100;self.logger.start_session('r');folder=self.logger.session_dir
        for i in range(30):self.logger.write({'type':'event','value':'x'*100})
        self.logger.finish_session();self.logger.flush();self.assertEqual(len(list(folder.glob('timeline*'))),2)

class Session264Tests(unittest.TestCase):
    def test_practice_quali_race_isolation_and_finished_report(self):
        with tempfile.TemporaryDirectory() as temp:
            s=b.DashboardSource(force_demo=True);s.ir=Mock();s.audio_coach=Mock();s.recorder=SessionRecorder(Path(temp)/'old.jsonl')
            self.addCleanup(s.recorder.close)
            roster=[{'CarIdx':i,'CarClassID':1,'CarNumber':str(i),'UserName':str(i),'UserID':10+i} for i in range(2)]
            sessions=[{'SessionType':name,'ResultsPositions':[]} for name in ['Practice','Qualify','Race']]
            values={'PlayerCarIdx':0,'DriverInfo':{'DriverUserID':10,'DriverCarIdx':0,'Drivers':roster},'WeekendInfo':{'SessionID':42,'SubSessionID':43,'TrackID':5,'TrackDisplayName':'Spa'},'SessionInfo':{'Sessions':sessions},'SessionNum':0,'SessionTime':1,'Lap':1,'LapCompleted':0,'CarIdxLapDistPct':[.2,.3],'CarIdxTrackSurface':[3,3],'FuelLevel':40}
            s.get=lambda k,default=None:values.get(k,default)
            folders=[]
            for num,mode in enumerate(['practice','qualifying','race_engineer']):
                values['SessionNum']=num;values['SessionTime']=num+1;p=s.live_payload(force_driver=True)
                self.assertEqual(p['sessionMode'],mode);self.assertEqual(s.lap_history,[]);self.assertIsNone(s.coach.best_lap)
                self.assertEqual(p['coach']['referenceSessionType'],sessions[num]['SessionType'])
                folders.append(s.recorder.session_dir);s.lap_history=[{'lap':5,'time':90,'valid':True}];s.coach.best_lap=90
            s.recorder.close();self.assertEqual(len(set(folders)),3);self.assertTrue(all((f/'summary.json').exists() for f in folders))
    def test_reset_removes_cached_previous_session(self):
        s=b.DashboardSource(force_demo=True);s.audio_coach=Mock();s.session_state.remember_payload(s.demo_payload())
        s.reset_session_tracking();self.assertIsNone(s.session_state.preserved_payload())
    def test_live_position_is_one_based_official_class_zero_based(self):
        # Contract exercised in existing race-data tests; direct intelligence keeps official base.
        history={};intel=build_intelligence(lambda k,d=None:d,{}, {'SessionType':'Race'}, {0:{'CarClassID':1},1:{'CarClassID':1}}, {1:{'Position':1,'ClassPosition':0}},0,1,[.1,.2],[3,3],history)
        row=intel['competitors']['observed'][0];self.assertEqual(row['position'],1);self.assertEqual(row['classPosition'],1)
    def test_disconnect_marks_intelligence_stale_and_disables_strategy(self):
        s=b.DashboardSource(force_demo=True);s.audio_coach=Mock()
        payload=s.demo_payload();payload['sessionIntelligence']={'competitors':{'observed':[{'carIdx':1,'presence':'LIVE','lapDistPct':.3}]}}
        payload['rivalStrategy']={'available':True,'primary':{'action':'UNDERCUT'}};s.session_state.remember_payload(payload)
        packet=s.disconnected_payload('offline');self.assertEqual(packet['sessionIntelligence']['competitors']['observed'][0]['presence'],'STALE')
        self.assertFalse(packet['rivalStrategy']['available']);self.assertIsNone(packet['rivalStrategy']['primary'])
    def test_class_live_fallback_does_not_override_official(self):
        cars={0:{'CarClassID':1},1:{'CarClassID':1},2:{'CarClassID':2}}
        rows=b.class_results_rows({0:{'ClassPosition':3}},cars,set(),1,0,[],b.DashboardSource.lap_text,[1,2,1])
        self.assertEqual({r['idx']:r['pos'] for r in rows},{0:4,1:2})
    def test_ambiguous_intelligence_identity_is_not_guessed(self):
        intel=build_intelligence(lambda k,d=None:d,{}, {'SessionType':'Race'}, {0:{'CarClassID':1},1:{'CarClassID':1,'UserName':'Wrong','identityAmbiguous':True}}, {},0,1,[.1,.2],[3,3],{})
        self.assertEqual(intel['competitors']['observed'][0]['driver'],'—')
    def test_updater_protects_journals_and_removes_legacy(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'installed';root.mkdir();source=Path(temp)/'source';(source/'server').mkdir(parents=True)
            (source/'server'/'new.py').write_text('ok');(root/'server').mkdir();(root/'server'/'session_uploader.py').write_text('obsolete')
            (root/'upload_queue.jsonl').write_text('obsolete');(root/'session_logs').mkdir();(root/'session_logs'/'keep').write_text('local')
            with patch.object(updater,'ROOT',root):updater._copy_program_tree(source)
            self.assertFalse((root/'server'/'session_uploader.py').exists());self.assertFalse((root/'upload_queue.jsonl').exists());self.assertEqual((root/'session_logs'/'keep').read_text(),'local')

if __name__=='__main__':unittest.main()
