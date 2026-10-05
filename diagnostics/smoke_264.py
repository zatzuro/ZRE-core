"""Launch the actual local server; simulate demo driver/spotter over WebSocket."""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import aiohttp

async def smoke():
    root=Path(__file__).resolve().parents[1]
    expected_version=json.loads((root/'version.json').read_text())['version']
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    runner="from server import iracing_bridge as b; b.start_background_updater=None; b.main()"
    with tempfile.TemporaryFile(mode='w+') as output:
        process=subprocess.Popen([sys.executable,'-c',runner,'--demo','--port',str(port)],cwd=root,stdout=output,stderr=output)
        try:
            async with aiohttp.ClientSession() as client:
                for attempt in range(60):
                    if process.poll() is not None:raise AssertionError('server exited')
                    try:
                        async with client.get(f'http://127.0.0.1:{port}/version') as response:
                            version=await response.json();assert version['runtimeVersion']==expected_version;break
                    except aiohttp.ClientConnectorError:await asyncio.sleep(.1)
                else:raise AssertionError('server did not start')
                for path in ['/', '/static/app.js','/static/style.css']:
                    async with client.get(f'http://127.0.0.1:{port}'+path) as response:
                        assert response.status==200;assert 'no-store' in response.headers['Cache-Control']
                        body=await response.text();assert body
                async with client.ws_connect(f'http://127.0.0.1:{port}/ws') as ws:
                    packet=await ws.receive_json(timeout=5);assert packet['demo'];assert packet['sessionMode']=='race_engineer';assert packet['appVersion']==expected_version
                    assert packet['relative'];assert packet['self']['laps']
                    await ws.send_json({'type':'settings','key':'demoRole','value':'spotter'})
                    for i in range(10):
                        packet=await ws.receive_json(timeout=5)
                        if packet.get('teamContext',{}).get('autoMode')=='spotter':break
                    else:raise AssertionError('spotter did not activate')
                    assert packet['racePlan'];assert packet['standingAll']
                    await ws.send_json({'type':'settings','key':'role','value':'driver'})
                    for i in range(10):
                        packet=await ws.receive_json(timeout=5)
                        if packet.get('teamContext',{}).get('autoMode')=='driver':break
                    else:raise AssertionError('driver override did not activate')
            print('2.6.4 actual server / assets / version / WebSocket / demo PILOTO-SPOTTER-AUTO: OK')
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
            output.seek(0);logs=output.read()
            assert 'Traceback' not in logs,logs

if __name__=='__main__':asyncio.run(smoke())
