"""Launch the existing ZRE bridge with installation/process identity; no telemetry engine."""
import socket
import sys
import uuid
from pathlib import Path
from aiohttp import web
from zre_build import identity,read_state

ROOT=Path(__file__).resolve().parent

def main():
    port=8765
    if '--port' in sys.argv:port=int(sys.argv[sys.argv.index('--port')+1])
    # Fail before importing the bridge or starting updater/audio workers.
    with socket.socket() as probe:
        try:probe.bind(('127.0.0.1',port))
        except OSError:raise SystemExit(f'Puerto {port} ocupado. No se reutiliza otra instancia. Root: {ROOT}')
    from server import iracing_bridge as bridge
    instance=uuid.uuid4().hex
    info=identity(ROOT,bridge.APP_VERSION,instance)
    if read_state(ROOT).get('mode')=='TEST' and (not info['assetsVerified'] or info['installedVersion']!=info['runtimeVersion']):
        raise SystemExit(f'TEST BUILD incoherente; reinstala antes de arrancar. Root: {ROOT}')
    async def status(request):return web.json_response(identity(ROOT,bridge.APP_VERSION,instance),headers={'Cache-Control':'no-store'})
    bridge.version_status=status
    original=bridge.DashboardSource.sample
    def sample(self,*args,**kwargs):
        payload=original(self,*args,**kwargs);payload['buildIdentity']=info;return payload
    bridge.DashboardSource.sample=sample
    print(f"{info['mode']} BUILD ACTIVE | ZRE Core {info['runtimeVersion']} | commit: {info['sourceCommit']} | root: {ROOT}",flush=True)
    bridge.main()

if __name__=='__main__':main()
