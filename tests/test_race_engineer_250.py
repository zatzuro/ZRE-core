import unittest
from pathlib import Path
from html.parser import HTMLParser
from server import iracing_bridge as bridge
from server.team_context import TeamCarContext
from server.stop_plan import race_plan
from server.spotter_control import SpotterControl

class RaceEngineerTests(unittest.TestCase):
    def test_full_class_roster_independent_of_dynamic_cars(self):
        source=bridge.DashboardSource(force_demo=True)
        drivers=[{'CarIdx':i,'CarClassID':1,'CarNumber':str(100+i),'TeamID':i+1,
                  'TeamName':f'Team {i}','UserName':f'Driver {i}','UserID':i+20} for i in range(40)]
        drivers += [{'CarIdx':40,'CarClassID':2,'CarNumber':'99','TeamID':60,'UserName':'Prototype','UserID':99}]
        results={i:{'CarIdx':i,'ClassPosition':i,'Position':i+1,'LapsComplete':100,'LastTime':80.0} for i in range(40)}
        results[40]={'CarIdx':40,'ClassPosition':0,'Position':1,'LapsComplete':101}
        pct=[None]*41;lap=[None]*41;completed=[None]*41
        for i in range(15):pct[i]=(.1+i*.04)%1;lap[i]=101;completed[i]=100
        pct[40]=.44;lap[40]=102;completed[40]=101
        readings={'CarIdxLap':lap,'CarIdxLapCompleted':completed,'CarIdxLapDistPct':pct,
                  'CarIdxLastLapTime':[None]*41,'CarIdxOnPitRoad':[False]*41,'SessionTimeRemain':4000,'FuelLevel':80}
        source.get=lambda key,default=None:readings.get(key,default)
        context=TeamCarContext.resolve({'Drivers':drivers},8,False,8,None,28,'Driver 8',9)
        packet=source.spotter_payload(context,drivers,{},results,{},30,{'Drivers':drivers})
        self.assertEqual(len(packet['standingAll']),40)
        self.assertEqual(packet['teamDebug']['classCarsInResults'],40)
        self.assertEqual(packet['teamDebug']['totalResults'],41)
        self.assertEqual(packet['relativeAvailableCars'],16)
        self.assertIn(40,[r['idx'] for r in packet['relative']])
        self.assertEqual(len(packet['relative']),7)
        self.assertEqual(packet['teamContext']['driver'],'AUTO · no confirmado')
        self.assertEqual(packet['self']['fuel'],'—')
        self.assertTrue(all(r['classId']==1 for r in packet['standingAll']))
        self.assertTrue(all(c['idx']<40 for c in packet['raceDirector']['candidates']))

    def test_team_car_number_survives_index_change(self):
        first=[{'CarIdx':8,'CarNumber':'18','TeamID':9,'CarClassID':1,'TeamName':'ZRE','UserID':2,'UserName':'Santiago'}]
        second=[dict(first[0],CarIdx=19,UserID=3,UserName='David')]
        a=TeamCarContext.resolve({'Drivers':first},8,True,local_user_id=2)
        b=TeamCarContext.resolve({'Drivers':second},8,False,8,None,2,'Santiago',9,last_car_number='18')
        self.assertEqual((a.car_number,b.car_number),('18','18'))
        self.assertEqual(b.car_idx,19)
        self.assertEqual(b.auto_mode,'spotter')

    def test_forward_plan_uses_remaining_state_and_preserves_history(self):
        history=[{'number':1,'lap':150,'status':'completed','fuel':'LLENAR'}]
        args=dict(remaining_seconds=10000,current_lap=151,lap_seconds=80,pit_seconds=30,
                  current_fuel=55,consumption=2.5,tank=55,stops_completed=1,
                  current_driver='Santiago',completed=history)
        original=race_plan(**args)
        self.assertEqual(original['projectedLaps'],125)
        self.assertEqual(original['autonomyLaps'],22)
        self.assertEqual(original['minimumStops'],original['stopsRemaining'])
        first=original['stops'][0]
        edited=race_plan(**args,overrides={2:{'lap':first['lap']-2,'driver':'David','fuel':'add','liters':30}})
        self.assertEqual(edited['stops'][0]['driver'],'David')
        self.assertEqual(edited['stops'][0]['liters'],30)
        self.assertEqual(edited['completed'],history)
        self.assertNotEqual(edited['stops'][1]['lap'],original['stops'][1]['lap'])
        self.assertEqual(race_plan(**args,overrides={2:{'driver':'David'}})['stops'][0]['lap'],first['lap'])

    def test_no_fuel_reference_does_not_invent_stops(self):
        plan=race_plan(remaining_seconds=3200,current_lap=101,lap_seconds=80,pit_seconds=30,
                       current_fuel=None,consumption=2.5,tank=55)
        self.assertEqual(plan['projectedLaps'],40)
        self.assertIsNone(plan['stopsRemaining'])
        self.assertFalse(plan['available'])

    def test_detected_pit_does_not_infer_fuel_and_manual_reference_survives(self):
        c=SpotterControl(fuel_liters=12.4,fuel_lap=149)
        c.pit_transition(True,150)
        self.assertEqual(c.stops[-1]['fuel'],'PENDIENTE')
        self.assertAlmostEqual(c.fuel_at(150,2.4),10)
        c.pit_transition(False,150)
        self.assertEqual(c.stops[-1]['status'],'completed')
        c.apply({'id':'fill','action':'fill'},lap=150,tank_capacity=55,projected_fuel=10)
        self.assertAlmostEqual(c.fuel_at(153,2.4),47.8)
        c.pit_transition(True,160)
        c.apply({'id':'add','action':'add_fuel','liters':30},lap=160,tank_capacity=55,projected_fuel=c.fuel_at(160,2.4))
        self.assertEqual(c.fuel_at(160,2.4),55)
        c.pit_transition(False,160)
        self.assertEqual(len(c.stops),2)
        self.assertEqual(c.stops[0]['fuel'],'LLENAR')
        self.assertEqual(c.stops[1]['fuel'],'+30 L')

    def test_pilot_navigation_and_single_socket_remain(self):
        web=Path(__file__).parents[1]/'web'
        html=(web/'index.html').read_text()
        js=(web/'app.js').read_text()
        for token in ('PISTA','PIT','RESUMEN','id="spotter-view"','id="spotter-standing-all"','id="spotter-stop-history"'):
            self.assertIn(token,html)
        self.assertEqual(js.count('new WebSocket('),1)
        self.assertIn("if(view==='live')renderLive(data)",js)
        self.assertIn("else if(view==='pit')renderPit(data)",js)
        self.assertIn('else renderSpotter(data)',js)
        self.assertEqual(js.count('location.replace('),1)
        self.assertIn('webBuildReloading',js)

if __name__=='__main__':unittest.main()
