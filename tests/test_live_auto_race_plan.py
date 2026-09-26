"""Observed team-session identities and forward projection without private fuel."""
import unittest

from server.team_context import TeamCarContext
from server.stop_plan import race_plan
from server.iracing_bridge import DashboardSource,valid_fuel


class LiveAutoRacePlanTests(unittest.TestCase):
    def test_local_identity_survives_team_swap_in_both_directions(self):
        car={'CarIdx':22,'CarNumber':'95','TeamID':228623,'UserID':531145,
             'UserName':'Santiago Ramirez','CarClassID':4011}
        info={'DriverCarIdx':22,'DriverUserID':531145,'Drivers':[car]}
        driving=TeamCarContext.resolve(info,22,False,local_car_active=True)
        self.assertEqual(driving.auto_mode,'driver')
        teammate=dict(car,UserID=1285290,UserName='David Rios Garcia')
        info['Drivers']=[teammate]
        observing=TeamCarContext.resolve(info,22,False,driving.car_idx,None,
                                           driving.local_user_id,driving.local_driver_name,
                                           driving.team_id,None,driving.car_number)
        self.assertEqual(observing.auto_mode,'spotter')
        self.assertEqual(observing.car_idx,22)
        self.assertEqual(observing.local_user_id,531145)
        info['Drivers']=[car]
        again=TeamCarContext.resolve(info,22,False,observing.car_idx,None,
                                      observing.local_user_id,observing.local_driver_name,
                                      observing.team_id,None,observing.car_number,
                                      local_car_active=True)
        self.assertEqual(again.auto_mode,'driver')

    def test_remote_car_active_does_not_make_local_user_driver(self):
        info={'DriverCarIdx':22,'DriverUserID':531145,'Drivers':[
            {'CarIdx':22,'UserID':1285290,'CarNumber':'95','TeamID':228623}]}
        context=TeamCarContext.resolve(info,22,True,local_car_active=True)
        self.assertEqual(context.auto_mode,'spotter')

    def test_remaining_time_projects_partial_plan_without_fake_fuel(self):
        p=race_plan(remaining_seconds=3878,current_lap=387,lap_seconds=80.7444,
                    pit_seconds=30,base_stint_laps=37,extended_stint_laps=38)
        self.assertEqual(p['state'],'SIN DATOS SUFICIENTES')
        self.assertEqual(p['projectedLaps'],48)
        self.assertIsNone(p['autonomyLaps'])
        self.assertIsNone(p['stopsRemaining'])
        self.assertIsNotNone(p['baseScenario'])
        self.assertIsNotNone(p['dynamicScenario'])
        self.assertIn('FUEL',p['missing'])

    def test_real_fuel_and_invalid_zero_remain_distinct(self):
        self.assertAlmostEqual(valid_fuel(33.4),33.4)
        for invalid in (None,0,0.0,float('nan'),-1):
            self.assertIsNone(valid_fuel(invalid))
        full=race_plan(remaining_seconds=3878,current_lap=387,lap_seconds=80.7444,
                       pit_seconds=30,current_fuel=33.4,consumption=2.5,tank=110,
                       base_stint_laps=37,extended_stint_laps=38)
        self.assertEqual(full['state'],'PLAN DISPONIBLE')
        self.assertGreater(full['autonomyLaps'],0)
        self.assertTrue(full['stops'])
        self.assertEqual(full['stops'][0]['number'],1)
        shorter=race_plan(remaining_seconds=900,current_lap=387,lap_seconds=80.7444,
                          pit_seconds=30,current_fuel=33.4,consumption=2.5,tank=110)
        self.assertLess(shorter['stopsRemaining'],full['stopsRemaining'])

    def test_spotter_zero_local_reading_keeps_real_reference(self):
        source=DashboardSource(force_demo=True)
        source.team_fuel_reference=(50.6,243)
        source.team_fuel_reference_valid=True
        source.strategy_settings.update(consumptionLiters=2.5,tankCapacityLiters=110)
        roster=[{'CarIdx':22,'UserID':1285290,'UserName':'David',
                 'CarNumber':'95','TeamID':228623,'CarClassID':4011}]
        info={'DriverUserID':531145,'DriverCarIdx':22,'Drivers':roster}
        context=TeamCarContext.resolve(info,22,False,22,local_car_active=False)
        readings={'FuelLevel':0,'SessionTimeRemain':3878,
                  'CarIdxLap':[0]*22+[248],'CarIdxLapCompleted':[0]*22+[247],
                  'CarIdxLapDistPct':[None]*22+[.4],
                  'CarIdxLastLapTime':[None]*22+[80.74],
                  'CarIdxOnPitRoad':[False]*23}
        source.get=lambda key,default=None:readings.get(key,default)
        packet=source.spotter_payload(context,roster,{},
                                       {22:{'ClassPosition':2,'LapsComplete':247}},
                                       {},1000,info)
        self.assertIn('40.6 L · ESTIMADO',packet['self']['fuel'])
        self.assertEqual(packet['teamDebug']['FuelLevelRaw'],0)
        self.assertIsNone(packet['teamDebug']['FuelLevelValidated'])
        self.assertAlmostEqual(packet['teamDebug']['fuelValueUsed'],40.6)
        self.assertEqual(packet['teamDebug']['fuelSource'],'ESTIMADO')
        self.assertEqual(packet['racePlan']['autonomyLaps'],int(packet['self']['fuelValue']/2.5))
        self.assertEqual(packet['teamDebug']['racePlanInputs']['fuelLiters'],packet['self']['fuelValue'])
        self.assertEqual(source.team_fuel_reference,(50.6,243))
        self.assertEqual(packet['racePlan']['state'],'PLAN DISPONIBLE')

    def test_observed_sdk_334_reaches_ui_and_plan_with_both_auto_states(self):
        roster=[{'CarIdx':22,'UserID':1285290,'UserName':'David',
                 'CarNumber':'95','TeamID':228623,'CarClassID':4011}]
        info={'DriverUserID':531145,'DriverCarIdx':22,'Drivers':roster}
        for driving in (False,True):
            with self.subTest(driving=driving):
                source=DashboardSource(force_demo=True)
                source.strategy_settings.update(consumptionLiters=2.5,tankCapacityLiters=110)
                source.get=lambda key,default=None:{'FuelLevel':33.4,'SessionTimeRemain':3878,
                    'CarIdxLap':[0]*22+[388],'CarIdxLapCompleted':[0]*22+[387],
                    'CarIdxLapDistPct':[None]*22+[.4],
                    'CarIdxLastLapTime':[None]*22+[80.74],
                    'CarIdxOnPitRoad':[False]*23}.get(key,default)
                context=TeamCarContext.resolve(info,22,False,22,local_car_active=False)
                context=type(context)(**{**vars(context),'local_driving':driving})
                packet=source.spotter_payload(context,roster,{},
                    {22:{'ClassPosition':2,'LapsComplete':387}}, {},1000,info)
                label='REAL LOCAL' if driving else 'SDK OBSERVADO'
                self.assertEqual(packet['self']['fuel'],f'33.4 L · {label}')
                self.assertEqual(packet['self']['fuelValue'],33.4)
                self.assertEqual(packet['teamDebug']['FuelLevelRaw'],33.4)
                self.assertEqual(packet['teamDebug']['FuelLevelValidated'],33.4)
                self.assertEqual(packet['teamDebug']['fuelSource'],label)
                self.assertEqual(packet['teamDebug']['racePlanInputs']['fuelLiters'],33.4)
                self.assertEqual(packet['racePlan']['autonomyLaps'],13)

    def test_absent_sdk_fuel_is_not_converted_to_zero(self):
        source=DashboardSource(force_demo=True)
        roster=[{'CarIdx':22,'UserID':1285290,'UserName':'David',
                 'CarNumber':'95','TeamID':228623,'CarClassID':4011}]
        info={'DriverUserID':531145,'DriverCarIdx':22,'Drivers':roster}
        source.get=lambda key,default=None:{'FuelLevel':None,'SessionTimeRemain':3878,
            'CarIdxLap':[0]*22+[388],'CarIdxLapCompleted':[0]*22+[387],
            'CarIdxLapDistPct':[None]*22+[.4],
            'CarIdxLastLapTime':[None]*22+[80.74],
            'CarIdxOnPitRoad':[False]*23}.get(key,default)
        context=TeamCarContext.resolve(info,22,False,22)
        packet=source.spotter_payload(context,roster,{},
            {22:{'ClassPosition':2,'LapsComplete':387}}, {},1000,info)
        self.assertEqual(packet['self']['fuel'],'—')
        self.assertIsNone(packet['self']['fuelValue'])
        self.assertIsNone(packet['teamDebug']['fuelValueUsed'])
        self.assertIsNone(packet['teamDebug']['racePlanInputs']['fuelLiters'])


if __name__=='__main__':unittest.main()
