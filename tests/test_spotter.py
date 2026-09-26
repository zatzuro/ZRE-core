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
        self.assertIsNone(TeamCarContext.resolve(TEAM,8,False).car_idx)

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
        self.assertEqual(packet['teamContext']['driver'],'David')
        self.assertEqual(packet['raceDirector']['selectedIdx'],9)
        self.assertTrue(packet['enduranceStrategy']['available'])
        self.assertEqual(packet['self']['fuel'],'—')
        self.assertEqual(packet['enduranceStrategy']['fuelNeeded'],'—')
        self.assertTrue(any(row['isPlayer'] and row['idx']==8 for row in packet['standing']))
