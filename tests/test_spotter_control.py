import unittest
from pathlib import Path
from html.parser import HTMLParser
from server.spotter_control import SpotterControl
from server import iracing_bridge as bridge

class ViewIds(HTMLParser):
    def __init__(self):super().__init__();self.ids=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if 'id' in attrs:self.ids.append(attrs['id'])

class ControlsTests(unittest.TestCase):
    def send(self,control,action,lap=152,**kw):
        return control.apply(dict(id=f'{action}-{len(control.events)}',action=action,**kw),lap=lap,tank_capacity=55,projected_fuel=kw.get('projected',12.4))
    def test_stop_requires_fuel_choice_and_persists(self):
        c=SpotterControl();c.pit_transition(True,152)
        self.assertEqual(c.fuel_source,'PENDIENTE');self.assertIsNone(c.fuel_at(152,2.4))
        self.assertEqual(self.send(c,'fill'),None)
        self.assertEqual(c.fuel_at(153,2.4),52.6)
        self.assertEqual(c.fuel_source,'MANUAL · ESTIMADO')
        self.assertEqual(c.last_stop_lap,152)
    def test_add_and_no_fuel_and_driver(self):
        c=SpotterControl();c.pit_transition(True,152)
        self.send(c,'add_fuel',liters=35)
        self.assertAlmostEqual(c.fuel_at(152,2.4),47.4)
        c.pit_transition(True,160)
        self.send(c,'no_fuel',lap=160,projected=28.2)
        self.assertAlmostEqual(c.fuel_at(161,2.4),25.8)
        self.send(c,'driver',driver='David')
        self.send(c,'new_stint',lap=161,driver='David')
        self.assertEqual((c.manual_driver,c.stint_started_lap),('David',161))
    def test_dedupe_and_no_fictitious_refuel(self):
        c=SpotterControl();e={'id':'one','action':'stop'}
        c.apply(e,lap=152);c.apply(e,lap=152)
        self.assertEqual(len(c.events),1)
        self.assertEqual(c.fuel_source,'PENDIENTE')
    def test_role_view_contract_and_one_socket(self):
        root=Path(__file__).resolve().parents[1]
        page=(root/'web/index.html').read_text()
        ids=ViewIds();ids.feed(page)
        self.assertEqual(len(ids.ids),len(set(ids.ids)))
        for name in ('live-view','pit-view','summary-view','spotter-view','driver-view-select','spotter-relative-rows','spotter-standing-rows'):
            self.assertIn(name,ids.ids)
        js=(root/'web/app.js').read_text()
        self.assertIn("return'spotter'",js)
        self.assertIn("$('live-view').hidden=view!=='live'",js)
        self.assertIn("$('pit-view').hidden=view!=='pit'",js)
        self.assertIn("$('summary-view').hidden=view!=='summary'",js)
        self.assertEqual(js.count('new WebSocket('),1)
        self.assertEqual(js.count('location.replace('),1)
    def test_spotter_rows_even_without_fuel(self):
        source=bridge.DashboardSource(force_demo=True)
        arr={'CarIdxLap':[0]*8+[100,101], 'CarIdxLapCompleted':[0]*8+[99,100],
             'CarIdxLapDistPct':[0]*8+[.4,.6],'CarIdxOnPitRoad':[False]*10,
             'CarIdxLastLapTime':[0]*8+[80,81],'SessionTimeRemain':4000}
        source.get=lambda key,default=None:arr.get(key,default)
        from server.team_context import TeamCarContext
        info={'Drivers':[{'CarIdx':8,'TeamID':1,'UserID':2,'UserName':'David','CarClassID':1},
                         {'CarIdx':9,'TeamID':2,'UserID':3,'UserName':'Rival','CarClassID':1}]}
        ctx=TeamCarContext.resolve(info,8,False,8,None,1,'Santiago',1)
        packet=source.spotter_payload(ctx,info['Drivers'],{},
                {8:{'ClassPosition':0},9:{'ClassPosition':1}},{},30,info)
        self.assertEqual(packet['self']['fuel'],'—')
        self.assertEqual(len(packet['relative']),2)
        self.assertEqual(len(packet['standing']),2)
        self.assertTrue(packet['teamDebug']['spotterPayloadReady'])

class BridgeEventTests(unittest.TestCase):
    def test_manual_stop_fill_driver_updates_strategy_immediately(self):
        source=bridge.DashboardSource(force_demo=True)
        source.team_completed_now=152
        source.strategy_settings['tankCapacityLiters']=55
        source.strategy_settings['consumptionLiters']=2.5
        source.spotter_pre_pit_fuel=12.4
        source.strategy_stops_completed=3
        source.spotter_control.pit_transition(True,152)
        source.strategy_last_on_pit=True
        source.manual_stop_counted=True
        self.assertIsNone(source.apply_spotter_event({'id':'1','action':'stop'}))
        self.assertEqual(source.spotter_control.fuel_source,'PENDIENTE')
        self.assertIsNone(source.apply_spotter_event({'id':'2','action':'fill'}))
        self.assertEqual(source.spotter_control.fuel_at(153,2.5),52.5)
        self.assertIsNone(source.apply_spotter_event({'id':'3','action':'driver','driver':'David'}))
        source.team_completed_now=153
        self.assertIsNone(source.apply_spotter_event({'id':'4','action':'new_stint','driver':'David'}))
        self.assertEqual(source.strategy_stops_completed,3) # physical pit counted once
        self.assertEqual(source.strategy_stint_start_lap,153)
        self.assertEqual(source.manual_team_driver,'David')

class ManualSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_spotter_event_survives_reopening_tab(self):
        import asyncio
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        app=web.Application();source=bridge.DashboardSource(force_demo=True);app['source']=source
        source.team_completed_now=152
        app.router.add_get('/ws',bridge.websocket)
        client=TestClient(TestServer(app));await client.start_server()
        try:
            async with client.ws_connect('/ws') as ws:
                await ws.receive_json()
                await ws.send_json({'type':'spotterEvent','id':'manual-1','action':'stop'})
                await asyncio.sleep(.15)
            async with client.ws_connect('/ws') as ws:
                await ws.receive_json()
                self.assertEqual(len(source.spotter_control.events),1)
                self.assertEqual(source.spotter_control.last_stop_lap,152)
        finally:await client.close()
