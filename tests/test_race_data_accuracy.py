"""SDK mapping regressions; lap values from the user's recorded session are separate.

The replay contains no DriverInfo or ResultsPositions. Those fields are
exercised with explicit SDK-shaped fixtures, not asserted against iRacing UI.
"""
import json
import statistics
import unittest
from pathlib import Path
from unittest.mock import patch
from server import iracing_bridge as bridge
from server.stop_plan import race_plan
from server.team_context import TeamCarContext
from diagnostics.capture_team_sdk import capture


class RaceDataAccuracyTests(unittest.TestCase):
    def packet(self, roster, results, readings=None, team_idx=8, source=None):
        source=source or bridge.DashboardSource(force_demo=True)
        source.debug_team_enabled=True
        defaults={'CarIdxLap':[101]*12,'CarIdxLapCompleted':[100]*12,
                  'CarIdxLapDistPct':[None]*12,'CarIdxOnPitRoad':[False]*12,
                  'CarIdxLastLapTime':[80]*12,'SessionTimeRemain':5000}
        defaults['CarIdxLapDistPct'][team_idx]=.4
        defaults['CarIdxLapDistPct'][9]=.45
        defaults['CarIdxLapDistPct'][10]=.37
        defaults.update(readings or {})
        source.get=lambda name,default=None:defaults.get(name,default)
        ctx=TeamCarContext.resolve({'Drivers':roster},team_idx,False,team_idx)
        packet=source.spotter_payload(ctx,roster,{},results,{},20,{'Drivers':roster})
        return source,packet

    def test_pilot_header_prefers_local_sdk_user_over_same_car_roster_order(self):
        teammate={'CarIdx':8,'CarClassID':1,'CarNumber':'18','UserName':'David','UserID':2,'TeamID':6,'CarScreenName':'McLaren'}
        local={'CarIdx':8,'CarClassID':1,'CarNumber':'18','UserName':'Santiago','UserID':1,'TeamID':6,'CarScreenName':'McLaren'}
        info={'DriverUserID':1,'Drivers':[teammate,local]}
        cars,conflicts=bridge.driver_roster_by_car(info['Drivers'])
        self.assertIn(8,conflicts)
        context=TeamCarContext.resolve(info,8,True,local_user_id=1,local_driver_name='Santiago',local_car_active=True)
        pilot=bridge.local_pilot_driver(info,info['Drivers'],cars,8,context)
        self.assertEqual(pilot['UserName'],'Santiago')
        self.assertEqual(pilot['UserID'],1)
        self.assertEqual(pilot['CarNumber'],'18')

    def test_pilot_live_roster_excludes_not_in_world_and_pace_car(self):
        cars={
            8:{'CarIdx':8,'UserName':'Santiago'},
            9:{'CarIdx':9,'UserName':'Ghost'},
            10:{'CarIdx':10,'UserName':'Live Rival'},
            11:{'CarIdx':11,'UserName':'Pace Car','CarIsPaceCar':True},
        }
        lap_pct=[None]*12
        lap_pct[8]=.20;lap_pct[9]=.42;lap_pct[10]=.31;lap_pct[11]=.10
        surface=[None]*12
        surface[8]=3;surface[9]=-1;surface[10]=3;surface[11]=3
        active=bridge.pilot_active_indices(cars,8,lap_pct,surface)
        self.assertEqual(active,{8,10})

    def test_solo_practice_keeps_local_car_even_when_in_garage(self):
        cars={
            8:{'CarIdx':8,'UserName':'Santiago'},
            9:{'CarIdx':9,'UserName':'Old Roster Driver'},
        }
        lap_pct=[None]*10
        surface=[-1]*10
        active=bridge.pilot_active_indices(cars,8,lap_pct,surface)
        self.assertEqual(active,{8})


    def test_relative_driver_tracks_current_sdk_user_name_not_team_or_spectator(self):
        car={'CarIdx':8,'CarClassID':1,'CarNumber':'18','UserName':'Santiago','TeamName':'ZRE','UserID':1,'TeamID':6}
        ahead={'CarIdx':9,'CarClassID':2,'CarNumber':'91','UserName':'Rival A','TeamName':'Team Prototype','UserID':2,'TeamID':7}
        behind={'CarIdx':10,'CarClassID':1,'CarNumber':'10','UserName':'GT3','TeamName':'Competidor','UserID':3,'TeamID':8}
        spectator={'CarIdx':9,'IsSpectator':True,'UserName':'Espectador','UserID':90,'CarClassID':2}
        results={8:{'ClassPosition':0,'Position':10},9:{'ClassPosition':0,'Position':1},10:{'ClassPosition':1,'Position':11}}
        source,one=self.packet([car,ahead,behind,spectator],results)
        self.assertEqual(next(r for r in one['relative'] if r['idx']==9)['driver'],'Rival A')
        self.assertEqual(next(r for r in one['standingAll'] if r['idx']==10)['driver'],'GT3')
        ahead=dict(ahead,UserName='Rival B',UserID=4)
        _,two=self.packet([car,ahead,behind,spectator],results,source=source)
        self.assertEqual(next(r for r in two['relative'] if r['idx']==9)['driver'],'Rival B')
        self.assertEqual(next(r for r in two['teamDebug']['relativeRoster'] if r['carIdx']==9)['shownDriver'],'Rival B')
        self.assertNotIn('Team Prototype',[r['driver'] for r in two['relative']])

    def test_conflicting_active_roster_does_not_guess_pilot(self):
        car={'CarIdx':8,'CarClassID':1,'CarNumber':'18','UserName':'Santiago','UserID':1,'TeamID':6}
        other={'CarIdx':9,'CarClassID':1,'CarNumber':'19','UserName':'A','UserID':2,'TeamID':7}
        _,packet=self.packet([car,other,dict(other,UserName='B',UserID=3)],
                             {8:{'ClassPosition':0},9:{'ClassPosition':1}})
        self.assertEqual(next(r for r in packet['relative'] if r['idx']==9)['driver'],'—')
        self.assertEqual(packet['teamDebug']['rosterConflicts'],[9])

    def test_disconnection_does_not_replay_old_driver_name(self):
        car={'CarIdx':8,'CarClassID':1,'CarNumber':'18','UserName':'Santiago','UserID':1,'TeamID':6}
        other={'CarIdx':9,'CarClassID':1,'CarNumber':'19','UserName':'David','UserID':2,'TeamID':7}
        source,packet=self.packet([car,other],{8:{'ClassPosition':0},9:{'ClassPosition':1}})
        source.session_state.remember_payload(packet)
        offline=source.disconnected_payload('SDK desconectado')
        self.assertEqual(next(r for r in offline['relative'] if r['idx']==9)['driver'],'—')
        self.assertEqual(next(r for r in offline['standingAll'] if r['idx']==9)['driver'],'—')
        self.assertEqual(next(r for r in source.session_state.preserved_payload()['relative'] if r['idx']==9)['driver'],'David')

    def test_official_class_position_not_overall_or_roster_order(self):
        own={'CarIdx':8,'CarClassID':1,'CarNumber':'18','UserName':'Santiago','TeamID':6,'UserID':1}
        gt3={'CarIdx':9,'CarClassID':1,'CarNumber':'99','UserName':'David','TeamID':7,'UserID':2}
        proto={'CarIdx':10,'CarClassID':2,'CarNumber':'1','UserName':'Prototype','TeamID':8,'UserID':3}
        # The class leader is disconnected and has no live lap distance.
        results={8:{'ClassPosition':3,'Position':17,'LapsComplete':100},
                 9:{'ClassPosition':0,'Position':6,'LapsComplete':101},
                 10:{'ClassPosition':0,'Position':1,'LapsComplete':102}}
        _,packet=self.packet([proto,own,gt3],results,
                             readings={'CarIdxLapDistPct':[None]*8+[.4,None,.37,None]})
        self.assertEqual([(r['idx'],r['pos']) for r in packet['standingAll']],[(9,1),(8,4)])
        self.assertEqual(packet['header']['position'],'P4')
        self.assertNotIn(10,[r['idx'] for r in packet['standingAll']])
        self.assertNotIn(9,[r['idx'] for r in packet['relative']])
        self.assertEqual(packet['teamDebug']['classResultPositions'][0]['classPositionRaw'],0)

    def test_missing_class_position_not_inferred_from_overall(self):
        car={'CarIdx':8,'CarClassID':1,'CarNumber':'18','UserName':'A','UserID':1,'TeamID':6}
        other=dict(car,CarIdx=9,CarNumber='19',UserID=2,TeamID=7,UserName='B')
        _,packet=self.packet([car,other],{8:{'ClassPosition':0,'Position':12},9:{'Position':2}})
        self.assertIsNone(next(r for r in packet['standingAll'] if r['idx']==9)['pos'])

    def test_partial_plan_distinct_from_calc_error_and_available(self):
        car={'CarIdx':8,'CarClassID':1,'CarNumber':'18','UserName':'A','UserID':1,'TeamID':6}
        source,packet=self.packet([car],{8:{'ClassPosition':0,'LapsComplete':100}},
                                  readings={'CarIdxLastLapTime':[None]*8+[80,None,None,None]})
        self.assertEqual(packet['racePlan']['state'],'SIN DATOS SUFICIENTES')
        self.assertEqual(packet['racePlan']['projectedLaps'],62)
        self.assertEqual(packet['racePlan']['currentStint'],1)
        self.assertIsNone(packet['racePlan']['stopsRemaining'])
        self.assertIn('FUEL',packet['teamDebug']['racePlanMissing'])
        source.strategy_settings.update(tankCapacityLiters=55,consumptionLiters=2.5)
        source.spotter_control.fuel_liters=40;source.spotter_control.fuel_lap=100
        _,complete=self.packet([car],{8:{'ClassPosition':0,'LapsComplete':100}},source=source)
        self.assertEqual(complete['racePlan']['state'],'PLAN DISPONIBLE')
        self.assertTrue(complete['racePlan']['stops'])
        self.assertGreater(complete['racePlan']['stintsRemaining'],1)
        with patch('server.stop_plan.build_stop_plan',side_effect=ValueError('bad math')):
            _,error=self.packet([car],{8:{'ClassPosition':0,'LapsComplete':100}},source=source)
        self.assertEqual(error['racePlan']['state'],'ERROR DE CÁLCULO')
        self.assertTrue(error['connected'])

    def test_recorded_lap_pace_and_consumption_feed_forward_plan(self):
        recorded=json.loads((Path(__file__).parent/'fixtures/endurance_laps.json').read_text())['laps']
        pace=statistics.median(r['paceSeconds'] for r in recorded)
        use=statistics.median(r['consumptionLiters'] for r in recorded)
        plan=race_plan(remaining_seconds=4500,current_lap=18,lap_seconds=pace,
                       pit_seconds=30,current_fuel=21,consumption=use,tank=55,
                       stops_completed=2,stint_start_lap=13)
        self.assertEqual(plan['state'],'PLAN DISPONIBLE')
        self.assertEqual(plan['currentStint'],3)
        self.assertEqual(plan['stintLaps'],5)
        self.assertGreater(plan['stopsRemaining'],0)
        self.assertGreaterEqual(plan['lastStintLaps'],0)
        self.assertIn(plan['lastStopAvoidable'],('SÍ','POSIBLE','NO'))

    def test_one_frame_sdk_capture_preserves_car_idx_and_official_class_position(self):
        class FakeSDK:
            def __init__(self):self.data={'SessionNum':0,'SessionInfo':{'Sessions':[{'ResultsPositions':[{'CarIdx':8,'ClassPosition':3,'Position':17}]}]},'DriverInfo':{'Drivers':[{'CarIdx':8,'UserName':'David','TeamName':'ZRE'}]},'PlayerCarIdx':8}
            def __getitem__(self,key):return self.data.get(key)
            def freeze_var_buffer_latest(self):self.frozen=True
            def unfreeze_var_buffer_latest(self):self.frozen=False
        sdk=FakeSDK();snapshot=capture(sdk)
        self.assertEqual(snapshot['ResultsPositions'][0]['ClassPosition'],3)
        self.assertEqual(snapshot['DriverInfo']['Drivers'][0]['UserName'],'David')
        self.assertFalse(sdk.frozen)

if __name__=='__main__':unittest.main()
