"""2.6.3 regressions: numbered laps, automatic audio, frozen setup and gaps."""
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
from pathlib import Path

from server import iracing_bridge as b
from server.audio_coach import AudioCoach
from server.setup_snapshot import snapshot_from_sdk, snapshot_from_html
from server.setup_engineer import SetupEngineer
from server.setup_report import render_setup_report
from server.team_context import TeamCarContext


class Release263Tests(unittest.TestCase):
    def source(self):
        source=b.DashboardSource(force_demo=True)
        source.get=lambda key,default=None:default
        source.audio_coach=Mock()
        source.recorder=Mock()
        return source

    def rows(self):
        return [{'idx':0,'pos':1,'completedLaps':10},
                {'idx':1,'pos':2,'completedLaps':10,'isPlayer':True},
                {'idx':2,'pos':3,'completedLaps':10},
                {'idx':3,'pos':4,'completedLaps':10}]

    def lap(self,source,num,time,result=None):
        source.update_lap_tracking(num,.1,50,time,None,result)

    def test_full_pilot_payload_keeps_unloaded_standings_and_live_lap(self):
        s=self.source()
        s.ir=Mock()
        roster=[{'CarIdx':i,'CarClassID':1,'CarNumber':str(i),'UserName':str(i),'UserID':i+10} for i in range(3)]
        results=[{'CarIdx':i,'ClassPosition':i,'Position':i+5,'LapsComplete':0,'LastTime':None} for i in range(3)]
        readings={'PlayerCarIdx':1,'DriverInfo':{'DriverUserID':11,'DriverCarIdx':1,'Drivers':roster},
                  'SessionInfo':{'Sessions':[{'SessionType':'Race','ResultsPositions':results}]},
                  'SessionNum':0,'SessionTime':1,'Lap':1,'LapCompleted':0,'FuelLevel':None,
                  'CarIdxLapDistPct':[None,.3,None],'CarIdxLapCompleted':[0]*3,'CarIdxLastLapTime':[None]*3,
                  'SessionTimeRemain':1000,'IsOnTrack':True}
        s.get=lambda key,default=None:readings.get(key,default)
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        s.setup_engineer=SetupEngineer(folder.name)
        packet=s.live_payload(force_driver=True)
        self.assertEqual(s.setup_engineer.current['session']['session'],'Race')
        self.assertEqual(len(packet['standing']),3)
        self.assertEqual([r['idx'] for r in packet['relative']],[0,1,2])
        self.assertEqual(packet['relative'][0]['gap'],'ESTÁTICO · SIN INTERVALO')
        readings.update(LapCompleted=1,LapLastLapTime=92.481,SessionTime=2)
        results[1].update(LapsComplete=1,LastTime=92.481)
        packet=s.live_payload(force_driver=True)
        self.assertEqual(packet['self']['laps'][-1]['time'],'1:32.481')
        self.assertEqual(packet['self']['fuelSource'],'SIN DATO')
        self.assertEqual(packet['header']['driver'],'1')
        self.assertEqual(s.ir.freeze_var_buffer_latest.call_count,s.ir.unfreeze_var_buffer_latest.call_count)

    def test_race_keeps_setup_telemetry_analysis_without_coach_advice_audio(self):
        s=self.source();s.coach_session_mode='race_engineer';s.coach.finish=Mock(return_value=True)
        s.coach.advice=[('curve',1,'long advice','more advice')]
        self.lap(s,0,None);self.lap(s,1,92.481)
        s.coach.finish.assert_called_once()
        s.flush_race_engineer_audio()
        s.audio_coach.say.assert_called_once_with('1:32.481')

    def test_first_lap_waits_for_new_time(self):
        s=self.source();self.lap(s,0,90);self.lap(s,1,90)
        self.assertEqual(s.lap_history,[])
        self.lap(s,1,91)
        self.assertEqual([(r['lap'],r['time']) for r in s.lap_history],[(1,91)])
        for _ in range(5):self.lap(s,1,91)
        self.assertEqual(len(s.lap_history),1)

    def test_official_last_time_updates_immediately_even_sdk_late(self):
        s=self.source();self.lap(s,0,90)
        self.lap(s,1,90,{'LapsComplete':1,'LastTime':92})
        self.assertEqual(s.lap_history[-1]['time'],92)
        self.lap(s,1,92,{'LapsComplete':1,'LastTime':92})
        self.assertEqual(len(s.lap_history),1)

    def test_equal_times_need_numbered_confirmation(self):
        s=self.source();self.lap(s,0,90)
        self.lap(s,1,90,{'LapsComplete':1,'LastTime':90})
        self.lap(s,2,90)
        self.assertEqual(len(s.lap_history),1)
        self.lap(s,2,90,{'LapsComplete':2,'LastTime':90})
        self.assertEqual([r['lap'] for r in s.lap_history],[1,2])

    def test_best_lap_confirms_equal_time(self):
        s=self.source();self.lap(s,0,90)
        s.get=lambda key,default=None:{'LapBestLap':1,'LapBestLapTime':90}.get(key,default)
        self.lap(s,1,90)
        self.assertEqual(len(s.lap_history),1)

    def test_zero_and_negative_times_never_become_laps(self):
        s=self.source();self.lap(s,0,None)
        for value in (0,-1,None):self.lap(s,1,value,{'LapsComplete':1,'LastTime':value})
        self.assertEqual(s.lap_history,[])

    def test_invalid_lap_is_history_not_coach_reference(self):
        s=self.source();self.lap(s,0,None);self.lap(s,1,90)
        self.assertEqual(len(s.lap_history),1)
        self.assertIsNone(s.personal_session_best)
        self.assertIsNone(s.coach.best_lap)

    def test_pit_lap_does_not_become_valid(self):
        s=self.source();s.get=lambda key,default=None:{'OnPitRoad':True,'PlayerCarMyIncidentCount':0,'PlayerTrackSurface':3}.get(key,default)
        self.lap(s,0,None);self.lap(s,1,90)
        self.assertIsNone(s.personal_session_best)

    def test_session_reset_clears_lap_and_rival_state(self):
        s=self.source();self.lap(s,0,None);self.lap(s,1,90)
        s.update_race_engineer_audio('race_engineer',1,self.rows(),[90]*4,[10]*4)
        s.reset_session_tracking()
        self.assertEqual(s.lap_history,[]);self.assertEqual(s.race_engineer_car_laps,{})

    def test_automatic_session_modes(self):
        for name,expected in [('Practice','practice'),('Test','practice'),('Open Practice','practice'),('Qualify','qualifying'),('Lone Qualify','qualifying'),('Race','race_engineer')]:
            self.assertEqual(b.DashboardSource.coach_mode_for_session(name),expected)

    def test_qualifying_analyzes_current_session_without_speaking(self):
        s=self.source();s.coach_session_mode='qualifying';s.coach.finish=Mock()
        self.lap(s,0,None);self.lap(s,1,90)
        s.coach.finish.assert_called_once();s.audio_coach.say.assert_not_called()

    def test_race_own_time_is_short(self):
        s=self.source();s.coach_session_mode='race_engineer'
        self.lap(s,0,None);self.lap(s,1,92.481);s.flush_race_engineer_audio()
        s.audio_coach.say.assert_called_once_with('1:32.481')

    def test_rival_ahead_and_behind_once(self):
        s=self.source();rows=self.rows()
        s.update_race_engineer_audio('race_engineer',1,rows,[90]*4,[10]*4)
        self.assertEqual(s.race_engineer_audio,[])
        s.update_race_engineer_audio('race_engineer',1,rows,[91,90,92,90],[11,10,11,10])
        self.assertEqual(s.race_engineer_audio,['Delante, 1:31.000','Detrás, 1:32.000'])
        s.race_engineer_audio=[]
        s.update_race_engineer_audio('race_engineer',1,rows,[91,90,92,90],[11,10,11,10])
        self.assertEqual(s.race_engineer_audio,[])

    def test_overtake_changes_neighbor_without_speech(self):
        s=self.source();rows=self.rows()
        s.update_race_engineer_audio('race_engineer',1,rows,[90,91,92,93],[10]*4)
        rows[0]['pos']=4;rows[3]['pos']=1
        s.update_race_engineer_audio('race_engineer',1,rows,[90,91,92,93],[10]*4)
        self.assertEqual(s.race_engineer_audio,[])
        s.update_race_engineer_audio('race_engineer',1,rows,[90,91,92,94],[10,10,10,11])
        self.assertEqual(s.race_engineer_audio,['Delante, 1:34.000'])

    def test_rival_delayed_time_waits(self):
        s=self.source();rows=self.rows()
        s.update_race_engineer_audio('race_engineer',1,rows,[90]*4,[10]*4)
        s.update_race_engineer_audio('race_engineer',1,rows,[90]*4,[11,10,10,10])
        self.assertEqual(s.race_engineer_audio,[])
        s.update_race_engineer_audio('race_engineer',1,rows,[92,90,90,90],[11,10,10,10])
        self.assertEqual(s.race_engineer_audio,['Delante, 1:32.000'])

    def test_rival_equal_time_official_confirmation(self):
        s=self.source();rows=self.rows()
        s.update_race_engineer_audio('race_engineer',1,rows,[90]*4,[10]*4)
        s.update_race_engineer_audio('race_engineer',1,rows,[90]*4,[11,10,10,10],{0:{'LapsComplete':11,'LastTime':90}})
        self.assertEqual(s.race_engineer_audio,['Delante, 1:30.000'])

    def test_other_class_ignored(self):
        s=self.source();rows=self.rows()
        s.update_race_engineer_audio('race_engineer',1,rows,[90]*5,[10]*5)
        s.update_race_engineer_audio('race_engineer',1,rows,[90]*4+[91],[10]*4+[11])
        self.assertEqual(s.race_engineer_audio,[])

    def test_disconnect_rebaselines_rivals_without_old_audio(self):
        s=self.source();rows=self.rows()
        s.update_race_engineer_audio('race_engineer',1,rows,[90]*4,[10]*4)
        s.disconnected_payload('disconnected')
        s.update_race_engineer_audio('race_engineer',1,rows,[95]*4,[12]*4)
        self.assertEqual(s.race_engineer_audio,[])

    def test_strategic_alert_drops_secondary_audio(self):
        s=self.source();s.coach_session_mode='race_engineer';s.race_engineer_audio=['1:30.000']
        s.race_plan_audio_state='BOX THIS LAP';s.flush_race_engineer_audio()
        self.assertEqual(s.race_engineer_audio,[]);s.audio_coach.say.assert_not_called()

    def test_grouped_simultaneous_audio(self):
        s=self.source();s.coach_session_mode='race_engineer'
        s.race_engineer_audio=['1:30.000','Delante, 1:31.000','Detrás, 1:32.000']
        s.flush_race_engineer_audio()
        s.audio_coach.say.assert_called_once_with('1:30.000. Delante, 1:31.000. Detrás, 1:32.000')

    def test_sdk_setup_identity_report_and_fingerprint(self):
        a=snapshot_from_sdk({'Wing':8},{'DriverSetupName':'Race','DriverSetupIsModified':True})
        renamed=snapshot_from_sdk({'Wing':8},{'DriverSetupName':'Renamed'})
        changed=snapshot_from_sdk({'Wing':7},{'DriverSetupName':'Race'})
        self.assertEqual(a['fingerprint'],renamed['fingerprint'])
        self.assertNotEqual(a['fingerprint'],changed['fingerprint'])
        report=render_setup_report({'setup':a})
        self.assertLess(report.index('SETUP IDENTITY'),report.index('SESSION'))
        self.assertIn('Race',report);self.assertIn(a['fingerprint'],report)

    def test_sdk_update_counter_does_not_change_fingerprint(self):
        a=snapshot_from_sdk({'UpdateCount':1,'Wing':8})
        b=snapshot_from_sdk({'UpdateCount':99,'Wing':8})
        self.assertEqual(a['fingerprint'],b['fingerprint'])
        self.assertNotIn('UpdateCount',a['flatParameters'])

    def test_html_identity_and_frozen_setup_between_stints(self):
        with tempfile.TemporaryDirectory() as folder:
            e=SetupEngineer(folder);ctx={'car':'McLaren','track':'Zandvoort','layout':'GP'}
            e.set_owner({"authorized":True,"scope":"own","car_idx":8,"team_id":"99","driver_user_id":"10","reason":"SDK test verified"})
            a=snapshot_from_html('<table><tr><td>Wing</td><td>8</td></tr></table>','Zandvoort:Race?.html')
            e.start_stint(ctx,a)
            a['parameters']['General']['Wing']='7';a['metadata']['filename']='New.html'
            old=e.finish_stint({})
            self.assertEqual(old['setup']['parameters']['General']['Wing'],'8')
            self.assertIn('Zandvoort:Race?.html',render_setup_report(old))
            self.assertNotIn(':',e.last_report_path.name);self.assertNotIn('?',e.last_report_path.name)
            new=snapshot_from_html('<table><tr><td>Wing</td><td>7</td></tr></table>','New.html')
            e.start_stint(ctx,new);saved=e.finish_stint({})
            self.assertEqual(saved['setupChanges'][0]['before'],'8');self.assertEqual(saved['setupChanges'][0]['after'],'7')
            self.assertIn('new-html',e.last_report_path.name)

    def test_unloaded_relative_keeps_self_and_class_neighbors_without_fake_gap(self):
        rows=self.rows()
        for r in rows:r.update(gap='—',classId=1)
        relative=b.merge_official_neighbors([],rows,1,'gapSeconds')
        self.assertEqual([r['idx'] for r in relative],[0,1,2])
        self.assertEqual(relative[0]['gap'],'ESTÁTICO · SIN INTERVALO')
        self.assertIsNone(relative[2]['gapSeconds'])

    def test_static_to_dynamic_no_duplicates(self):
        rows=self.rows();dynamic=[{'idx':0,'gapSeconds':2.5,'isPlayer':False},{'idx':1,'gapSeconds':0,'isPlayer':True},{'idx':2,'gapSeconds':-1.5,'isPlayer':False}]
        relative=b.merge_official_neighbors(dynamic,rows,1,'gapSeconds')
        self.assertEqual(len(relative),3);self.assertEqual(relative[0]['gapSeconds'],2.5)
        self.assertEqual(relative[2]['gapSeconds'],-1.5)

    def test_results_time_never_invents_relative_for_any_session_or_lapped_car(self):
        for laps in (9,10,11):
            self.assertIsNone(b.official_static_gap({'LapsComplete':10,'Time':900},{'LapsComplete':laps,'Time':890}))

    def test_official_standings_include_unloaded_class_cars(self):
        cars={i:{'CarClassID':1,'CarIdx':i} for i in range(3)}
        results={i:{'ClassPosition':i,'Position':i+5,'LapsComplete':10} for i in range(3)}
        rows=b.class_results_rows(results,cars,set(),1,1,[],b.DashboardSource.lap_text)
        self.assertEqual([r['pos'] for r in rows],[1,2,3]);self.assertEqual(len(rows),3)

    def test_audio_queue_preserves_callouts_and_priority(self):
        a=AudioCoach();a.thread=Mock();a.thread.is_alive.return_value=True
        with patch('server.audio_coach.os.name','nt'):
            a.say('own');a.say('ahead');a.say('behind')
            self.assertEqual(list(a.pending.queue),['own','ahead','behind'])
            a.say_priority('Box, box.')
            self.assertEqual(list(a.pending.queue),['Box, box.'])
            for _ in range(30):a.say('lap')
            self.assertLessEqual(a.pending.qsize(),16)

    def test_spotter_announces_team_and_neighbors(self):
        s=self.source();roster=[{'CarIdx':i,'CarClassID':1,'CarNumber':str(i),'UserName':str(i)} for i in range(3)]
        ctx=TeamCarContext.resolve({'Drivers':roster},1,False,1)
        readings={'CarIdxLap':[11]*3,'CarIdxLapCompleted':[10]*3,'CarIdxLapDistPct':[None]*3,'CarIdxLastLapTime':[90]*3,'SessionTimeRemain':1000}
        s.get=lambda key,default=None:readings.get(key,default)
        results={i:{'ClassPosition':i,'Position':i+5,'LapsComplete':10} for i in range(3)}
        packet=s.spotter_payload(ctx,roster,{'SessionType':'Race'},results,{},1,{'Drivers':roster})
        self.assertEqual(len(packet['standingAll']),3)
        self.assertEqual([r['idx'] for r in packet['relative']],[0,1,2])
        readings['CarIdxLapCompleted']=[11]*3;readings['CarIdxLastLapTime']=[91,92,93]
        packet=s.spotter_payload(ctx,roster,{'SessionType':'Race'},results,{},2,{'Drivers':roster})
        self.assertEqual(packet['self']['laps'][0]['time'],'1:32.000')
        self.assertTrue(s.audio_coach.say.called)
        speech=s.audio_coach.say.call_args.args[0]
        self.assertIn('1:32.000',speech);self.assertIn('Delante, 1:31.000',speech);self.assertIn('Detrás, 1:33.000',speech)


if __name__=='__main__':unittest.main()
