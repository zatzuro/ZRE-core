import asyncio
import unittest
from pathlib import Path
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from server.team_context import TeamCarContext
from server import iracing_bridge as bridge

TEAM={'DriverCarIdx':8,'DriverUserID':101,'Drivers':[{'CarIdx':8,'TeamID':10,'UserID':202,'UserName':'David','CarClassID':1},{'CarIdx':9,'TeamID':11,'UserID':303,'UserName':'Rival','CarClassID':1}]}

class TeamContextTests(unittest.TestCase):
    def test_swap_and_override(self):
        before=dict(TEAM,Drivers=[dict(TEAM['Drivers'][0],UserID=101,UserName='Santiago'),TEAM['Drivers'][1]])
        self.assertEqual(TeamCarContext.resolve(before,8,True,8).auto_mode,'driver')
        swapped=TeamCarContext.resolve(TEAM,8,False,8)
        self.assertEqual((swapped.car_idx,swapped.current_driver,swapped.auto_mode),(8,'David','spotter'))
        self.assertEqual(TeamCarContext.resolve(TEAM,8,False,8,8).auto_mode,'spotter')
        self.assertEqual(TeamCarContext.resolve(TEAM,8,False).car_idx,8)
        self.assertEqual(TeamCarContext.resolve(TEAM,8,False).source,'sdk-car-provisional')

    def test_ui_one_socket_no_reload_on_role_change(self):
        js=(Path(__file__).resolve().parents[1]/'web/app.js').read_text()
        self.assertIn("rolePreference=event.target.value",js)
        self.assertIn("if(latestData)render(latestData)",js)
        self.assertEqual(js.count('new WebSocket('),1)
        self.assertEqual(js.count('location.replace('),1) # version update only

class DemoRoleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app=web.Application();app['source']=bridge.DashboardSource(force_demo=True)
        app.router.add_get('/ws',bridge.websocket)
        self.client=TestClient(TestServer(app));await self.client.start_server()
    async def asyncTearDown(self):await self.client.close()
    async def test_manual_spotter_requests_team_payload_without_reconnect(self):
        from unittest.mock import patch
        source=self.client.server.app['source']
        original=source.sample
        calls=[]
        def sampled(force_spotter=False):
            calls.append(force_spotter)
            return original(force_spotter=force_spotter)
        with patch.object(source,'sample',side_effect=sampled):
            async with self.client.ws_connect('/ws') as ws:
                await ws.receive_json()
                await ws.send_json({'type':'settings','key':'role','value':'spotter'})
                for _ in range(3):
                    await asyncio.wait_for(ws.receive_json(),2)
                    if True in calls:break
                self.assertIn(True,calls)
                await ws.send_json({'type':'settings','key':'role','value':'auto'})
                for _ in range(3):
                    await asyncio.wait_for(ws.receive_json(),2)
                    if calls[-1] is False:break
                self.assertFalse(calls[-1])

    async def test_switch_modes_on_same_socket(self):
        async with self.client.ws_connect('/ws') as ws:
            first=await ws.receive_json();self.assertEqual(first['teamContext']['autoMode'],'driver')
            await ws.send_json({'type':'settings','key':'demoRole','value':'spotter'})
            spotter=await asyncio.wait_for(ws.receive_json(),2)
            if spotter['teamContext']['autoMode']!='spotter':spotter=await asyncio.wait_for(ws.receive_json(),2)
            self.assertEqual(spotter['teamContext']['driver'],'DAVID')
            self.assertEqual(spotter['self']['fuel'],'—')
            self.assertEqual(spotter['enduranceStrategy']['fuelSource'],'NO DISPONIBLE')
            await ws.send_json({'type':'settings','key':'demoRole','value':'driver'})
            for _ in range(3):
                restored=await asyncio.wait_for(ws.receive_json(),2)
                if restored['teamContext']['autoMode']=='driver':break
            self.assertEqual(restored['teamContext']['autoMode'],'driver')

class SpotterPayloadTests(unittest.TestCase):
    def test_team_car_drives_rival_strategy_and_unknown_fuel(self):
        source=bridge.DashboardSource(force_demo=True)
        values={'CarIdxLap':[0]*8+[12,12],'CarIdxLapCompleted':[0]*8+[11,11],
                'CarIdxLapDistPct':[0]*8+[.4,.35],'CarIdxOnPitRoad':[False]*10,
                'CarIdxLastLapTime':[0]*8+[80,81],'SessionTimeRemain':18000}
        source.get=lambda key,default=None:values.get(key,default)
        car=dict(TEAM['Drivers'][0],CarNumber='8',CarScreenName='GT3')
        rival=dict(TEAM['Drivers'][1],CarNumber='9',CarScreenName='GT3')
        results={8:{'ClassPosition':0,'LapsComplete':11},9:{'ClassPosition':1,'LapsComplete':11}}
        context=TeamCarContext.resolve(TEAM,8,False,8)
        packet=source.spotter_payload(context,[car,rival],{},results,{},100,TEAM)
        self.assertEqual(packet['teamContext']['carIdx'],8)
        self.assertEqual(packet['teamContext']['driver'],'AUTO · no confirmado')
        self.assertEqual(packet['raceDirector']['selectedIdx'],9)
        self.assertTrue(packet['enduranceStrategy']['available'])
        self.assertEqual(packet['self']['fuel'],'—')
        self.assertEqual(packet['enduranceStrategy']['fuelNeeded'],'—')
        self.assertTrue(any(row['isPlayer'] and row['idx']==8 for row in packet['standing']))

from server.team_timing import relative_position,estimated_team_fuel

class RealTeamSessionCases(unittest.TestCase):
    def test_player_idx_and_sdk_driver_id_follow_car_but_person_does_not(self):
        before=dict(TEAM, DriverUserID=101, Drivers=[dict(TEAM['Drivers'][0],UserID=101,UserName='Santiago'),TEAM['Drivers'][1]])
        first=TeamCarContext.resolve(before,8,True)
        after=dict(TEAM,DriverUserID=202,DriverCarIdx=8)
        swapped=TeamCarContext.resolve(after,8,False,first.car_idx,None,first.local_user_id,first.local_driver_name,first.team_id)
        self.assertEqual((first.car_idx,swapped.car_idx),(8,8))
        self.assertEqual(swapped.local_user_id,101)
        self.assertEqual(swapped.current_user_id,202)
        self.assertEqual(swapped.auto_mode,'spotter') # IsOnTrackCar can remain true; IsOnTrack is false.

    def test_relative_laps_and_estimated_time(self):
        self.assertEqual(relative_position(100,.40,100,.60,80)[1],'≈ +16.0 s · EST.')
        self.assertEqual(relative_position(100,.40,99,.20,80)[1],'-1 LAP')
        self.assertEqual(relative_position(100,.40,101,.60,80)[1],'+1 LAP')
        rows=[relative_position(100,.40,n,p,80)[0] for n,p in [(100,.6),(99,.20),(101,.60)]]
        self.assertEqual(sorted(rows,reverse=True),[rows[0],rows[2],rows[1]])

    def test_fuel_never_reads_local_value_and_uses_snapshot(self):
        self.assertAlmostEqual(estimated_team_fuel(50,100,104,2.5),40)
        self.assertIsNone(estimated_team_fuel(None,100,104,2.5))
        self.assertIsNone(estimated_team_fuel(50,100,99,2.5))
        source=bridge.DashboardSource(force_demo=True)
        source.team_fuel_reference=(50,100)
        source.team_fuel_reference_valid=True
        source.fuel_per_lap=[2.5]
        data={'CarIdxLap':[0]*8+[105], 'CarIdxLapCompleted':[0]*8+[104],
              'CarIdxLapDistPct':[0]*8+[.4], 'CarIdxOnPitRoad':[False]*9,
              'CarIdxLastLapTime':[0]*8+[80], 'FuelLevel':88, 'SessionTimeRemain':5000}
        source.get=lambda key,default=None:data.get(key,default)
        context=TeamCarContext.resolve(TEAM,8,False,8,None,101,'Santiago',10)
        packet=source.spotter_payload(context,[dict(TEAM['Drivers'][0],CarNumber='8')],{},
                                      {8:{'ClassPosition':0}}, {},200,TEAM)
        self.assertIn('40.0 L · ESTIMADO',packet['self']['fuel'])
        self.assertEqual(packet['teamDebug']['FuelLevelLocal'],88)
        self.assertEqual(packet['teamDebug']['CarIdxLap'],105)
        self.assertEqual(packet['teamDebug']['CarIdxLapCompleted'],104)
        self.assertEqual(source.team_fuel_reference,(50,100))

    def test_swap_does_not_reset_strategy_or_car_laps(self):
        source=bridge.DashboardSource(force_demo=True)
        source.strategy_stops_completed=3
        source.strategy_stint_start_lap=100
        source.active_stint_driver='Santiago'
        laps={'CarIdxLap':[0]*8+[103], 'CarIdxLapCompleted':[0]*8+[102],
              'CarIdxLapDistPct':[0]*8+[.4], 'CarIdxOnPitRoad':[False]*9,
              'CarIdxLastLapTime':[0]*8+[80], 'SessionTimeRemain':5000}
        source.get=lambda key,default=None:laps.get(key,default)
        ctx=TeamCarContext.resolve(TEAM,8,False,8,None,101,'Santiago',10)
        packet=source.spotter_payload(ctx,[dict(TEAM['Drivers'][0],CarNumber='8')],{},
                                      {8:{'ClassPosition':0}}, {},200,TEAM)
        self.assertEqual(packet['header']['lap'],'VUELTA 103')
        self.assertEqual(source.strategy_stops_completed,3)
        self.assertEqual(source.strategy_stint_start_lap,100)
        self.assertEqual(packet['teamContext']['driver'],'AUTO · no confirmado')
