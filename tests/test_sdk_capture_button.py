import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from server import iracing_bridge as bridge

FIELDS=('DriverInfo','SessionInfo','SessionNum','PlayerCarIdx','SessionTime','SessionTimeRemain','FuelLevel','Lap','LapCompleted','CarIdxLapDistPct','CarIdxLap','CarIdxLapCompleted','CarIdxPosition','CarIdxClassPosition','CarIdxLastLapTime','CarIdxBestLapTime','CarIdxOnPitRoad','CarIdxEstTime')

class OneFrameCaptureTests(unittest.TestCase):
    def test_one_freeze_one_json_all_requested_fields_in_zre_root(self):
        class FakeSDK:
            is_initialized=True
            is_connected=True
            def __init__(self):self.freezes=0;self.unfreezes=0
            def freeze_var_buffer_latest(self):self.freezes+=1
            def unfreeze_var_buffer_latest(self):self.unfreezes+=1
            def __getitem__(self,key):
                values={'DriverInfo':{'Drivers':[{'CarIdx':8,'UserName':'David'}]},
                        'SessionInfo':{'Sessions':[{'ResultsPositions':[{'CarIdx':8,'ClassPosition':3}]}]},
                        'SessionNum':0,'PlayerCarIdx':8,'FuelLevel':30.5}
                return values.get(key)
        source=bridge.DashboardSource(force_demo=True);sdk=FakeSDK();source.ir=sdk
        with tempfile.TemporaryDirectory() as tmp,patch.object(bridge,'ROOT',Path(tmp)):
            file=source.capture_sdk_once()
            self.assertRegex(file.name,r'^ZRE_TEAM_CAPTURE_\d{8}_\d{6}\.json$')
            self.assertEqual(file.parent,Path(tmp))
            data=json.loads(file.read_text(encoding='utf-8'))
            self.assertTrue(set(FIELDS).issubset(data))
            self.assertEqual(data['DriverInfo']['Drivers'][0]['UserName'],'David')
            self.assertEqual(data['SessionInfo']['Sessions'][0]['ResultsPositions'][0]['ClassPosition'],3)
            self.assertEqual(data['ResultsPositions'][0]['CarIdx'],8)
            self.assertEqual((sdk.freezes,sdk.unfreezes),(1,1))
            self.assertIn(file.name,source.capture_status)
    def test_unavailable_sdk_does_not_create_file(self):
        source=bridge.DashboardSource(force_demo=True)
        with tempfile.TemporaryDirectory() as tmp,patch.object(bridge,'ROOT',Path(tmp)):
            self.assertIsNone(source.capture_sdk_once())
            self.assertEqual(list(Path(tmp).iterdir()),[])
            self.assertIn('no conectado',source.capture_status)

class SameSocketCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_button_action_reuses_existing_websocket(self):
        app=web.Application();source=bridge.DashboardSource(force_demo=True);app['source']=source
        app.router.add_get('/ws',bridge.websocket)
        client=TestClient(TestServer(app));await client.start_server()
        try:
            async with client.ws_connect('/ws') as ws:
                first=await ws.receive_json()
                self.assertEqual(first['captureStatus'],'Listo para capturar')
                await ws.send_json({'type':'action','action':'capture_sdk'})
                for _ in range(4):
                    next_payload=await asyncio.wait_for(ws.receive_json(),2)
                    if 'fallida' in next_payload['captureStatus']:break
                self.assertIn('iRacing SDK no conectado',next_payload['captureStatus'])
                self.assertFalse(ws.closed)
        finally:await client.close()

if __name__=='__main__':unittest.main()
