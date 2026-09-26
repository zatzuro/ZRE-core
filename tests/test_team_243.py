import unittest
from server.team_timing import relative_position, relative_window
from server.stop_plan import build_stop_plan
from server.spotter_control import SpotterControl
from server import iracing_bridge as bridge
from server.team_context import TeamCarContext

class PhysicalRelativeTests(unittest.TestCase):
    def test_wrap_and_lapped_cars(self):
        self.assertAlmostEqual(relative_position(100,.96,101,.04,80)[0],.08)
        self.assertAlmostEqual(relative_position(101,.04,100,.96,80)[0],-.08)
        self.assertIn('EST.',relative_position(100,.96,101,.04,80)[1])
        self.assertEqual(relative_position(100,.2,101,.6,80)[1],'+1 LAP')
        self.assertEqual(relative_position(100,.8,99,.4,80)[1],'-1 LAP')
    def test_multiclass_order_is_physical(self):
        rows=[{'idx':8,'classId':1,'relativeDelta':0,'isPlayer':True}]
        for i,delta,cls in [(1,.06,2),(2,.1,1),(3,.16,3),(4,.29,1),(5,-.03,3),(6,-.14,2),(7,-.2,1),(9,-.25,1)]:
            rows.append({'idx':i,'classId':cls,'relativeDelta':delta})
        self.assertEqual([x['idx'] for x in relative_window(rows,8)],[3,2,1,8,5,6,7])
    def test_rival_selector_only_own_class(self):
        source=bridge.DashboardSource(force_demo=True)
        data={'CarIdxLap':[0]*8+[100,100,100],'CarIdxLapCompleted':[0]*8+[99,99,99],
              'CarIdxLapDistPct':[0]*8+[.4,.5,.45], 'CarIdxOnPitRoad':[False]*11,
              'CarIdxLastLapTime':[0]*8+[80,81,79], 'SessionTimeRemain':3000}
        source.get=lambda name,default=None:data.get(name,default)
        drivers=[{'CarIdx':8,'CarClassID':1,'UserID':2,'TeamID':1,'UserName':'David'},
                 {'CarIdx':9,'CarClassID':2,'UserID':3,'TeamID':2,'UserName':'Otra clase'},
                 {'CarIdx':10,'CarClassID':1,'UserID':4,'TeamID':3,'UserName':'Rival'}]
        context=TeamCarContext.resolve({'Drivers':drivers},8,False,8,None,1,'Santiago',1)
        packet=source.spotter_payload(context,drivers,{}, {8:{'ClassPosition':0},9:{'ClassPosition':0},10:{'ClassPosition':1}}, {},60,{'Drivers':drivers})
        self.assertIn(9,[r['idx'] for r in packet['relative']])
        self.assertEqual([r['idx'] for r in packet['standing']],[8,10])
        self.assertEqual([r['idx'] for r in packet['raceDirector']['candidates']],[10])

class FuelAndStopsTests(unittest.TestCase):
    def test_two_stops_keep_reference_through_pending(self):
        c=SpotterControl(fuel_liters=12.4,fuel_lap=149,fuel_source='ESTIMADO')
        c.pit_transition(True,150)
        self.assertEqual(c.fuel_source,'PENDIENTE')
        self.assertAlmostEqual(c.fuel_at(150,2.4),10.0)
        c.apply({'id':'1','action':'fill'},lap=150,tank_capacity=55,projected_fuel=10)
        self.assertAlmostEqual(c.fuel_at(153,2.4),47.8)
        c.pit_transition(True,160)
        self.assertAlmostEqual(c.fuel_at(160,2.4),31)
        c.apply({'id':'2','action':'add_fuel','liters':30},lap=160,tank_capacity=55,projected_fuel=c.fuel_at(160,2.4))
        self.assertEqual(c.fuel_at(160,2.4),55)
        c.pit_transition(True,170)
        c.apply({'id':'3','action':'no_fuel'},lap=170,tank_capacity=55,projected_fuel=c.fuel_at(170,2.4))
        self.assertEqual(c.fuel_at(171,2.4),28.6)
    def test_override_is_per_field_and_rest_recalculates(self):
        args=dict(remaining_seconds=18000,current_lap=210,lap_seconds=80,pit_seconds=30,
                  stint_laps=38,current_fuel=90,consumption=2.4,tank=99,stops_completed=4,current_driver='Santiago')
        initial=build_stop_plan(**args)
        self.assertGreater(initial['stopsRemaining'],1)
        first=initial['stops'][0];second=initial['stops'][1]
        overrides={first['number']:{'lap':first['lap']-2,'driver':'David','fuel':'add','liters':45}}
        edited=build_stop_plan(**args,overrides=overrides)
        self.assertEqual(edited['stops'][0]['lap'],first['lap']-2)
        self.assertEqual(edited['stops'][0]['driver'],'David')
        self.assertEqual(edited['stops'][0]['fuelAction'],'add')
        self.assertNotEqual(edited['stops'][1]['suggestedLap'],second['suggestedLap'])
        overrides[first['number']].pop('lap')
        restored=build_stop_plan(**args,overrides=overrides)
        self.assertEqual(restored['stops'][0]['lap'],first['lap'])
        self.assertEqual(restored['stops'][0]['driver'],'David')
    def test_reject_unknown_team_driver_and_clear_auto(self):
        source=bridge.DashboardSource(force_demo=True);source.team_completed_now=210
        n=source.strategy_stops_completed+1
        self.assertIsNotNone(source.apply_stop_override({'number':n,'field':'driver','value':'Rival'}))
        self.assertIsNone(source.apply_stop_override({'number':n,'field':'driver','value':'David'}))
        self.assertEqual(source.stop_overrides[n]['driver'],'David')
        self.assertIsNone(source.apply_stop_override({'number':n,'field':'driver','value':'auto'}))
        self.assertNotIn(n,source.stop_overrides)

class DelayedManualFuelTests(unittest.TestCase):
    def test_fill_at_pit_lap_even_when_entered_later(self):
        source=bridge.DashboardSource(force_demo=True)
        source.strategy_settings['tankCapacityLiters']=55
        source.strategy_settings['consumptionLiters']=2.5
        source.team_completed_now=153
        source.spotter_control.pit_transition(True,150)
        source.spotter_pre_pit_fuel=12.4
        self.assertIsNone(source.apply_spotter_event({'id':'fill-late','action':'fill'}))
        self.assertEqual(source.spotter_control.fuel_lap,150)
        self.assertAlmostEqual(source.spotter_control.fuel_at(153,2.5),47.5)
    def test_plus_liters_uses_pit_reference(self):
        source=bridge.DashboardSource(force_demo=True)
        source.strategy_settings['tankCapacityLiters']=55
        source.strategy_settings['consumptionLiters']=2.5
        source.team_completed_now=153
        source.spotter_control.pit_transition(True,150)
        source.spotter_pre_pit_fuel=12.4
        self.assertIsNone(source.apply_spotter_event({'id':'add-late','action':'add_fuel','liters':30}))
        self.assertAlmostEqual(source.spotter_control.fuel_at(153,2.5),34.9)

class PlanningTimeTests(unittest.TestCase):
    def test_remaining_time_drives_stop_count(self):
        params=dict(current_lap=210,lap_seconds=80,pit_seconds=30,stint_laps=38,
                    current_fuel=55,consumption=2.5,tank=55,stops_completed=4)
        long=build_stop_plan(remaining_seconds=18000,**params)
        short=build_stop_plan(remaining_seconds=7000,**params)
        self.assertGreater(long['stopsRemaining'],short['stopsRemaining'])
        self.assertGreater(long['finishLap'],short['finishLap'])
    def test_manual_fuel_none_changes_future_stops_and_can_restore_auto(self):
        args=dict(remaining_seconds=9000,current_lap=100,lap_seconds=80,pit_seconds=30,
                  stint_laps=30,current_fuel=25,consumption=2.5,tank=55,stops_completed=2)
        auto=build_stop_plan(**args)
        n=auto['stops'][0]['number']
        no_fuel=build_stop_plan(**args,overrides={n:{'fuel':'none'}})
        self.assertEqual(no_fuel['stops'][0]['fuelAction'],'none')
        self.assertNotEqual(no_fuel['stops'][1]['lap'],auto['stops'][1]['lap'])
        restored=build_stop_plan(**args,overrides={})
        self.assertEqual(restored,auto)
    def test_same_position_other_lap_still_displayed(self):
        self.assertGreater(relative_position(100,.5,101,.5,80)[0],0)
        self.assertEqual(relative_position(100,.5,101,.5,80)[1],'+1 LAP')

class StopOverrideSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_override_on_existing_websocket(self):
        import asyncio
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        app=web.Application();source=bridge.DashboardSource(force_demo=True);app['source']=source
        source.team_completed_now=100
        app.router.add_get('/ws',bridge.websocket)
        client=TestClient(TestServer(app));await client.start_server()
        try:
            async with client.ws_connect('/ws') as ws:
                await ws.receive_json()
                await ws.send_json({'type':'stopOverride','number':1,'field':'lap','value':'135'})
                await asyncio.sleep(.15)
                self.assertEqual(source.stop_overrides[1]['lap'],135)
                await ws.send_json({'type':'stopOverride','number':1,'field':'lap','value':'auto'})
                await asyncio.sleep(.15)
                self.assertNotIn(1,source.stop_overrides)
        finally:await client.close()
