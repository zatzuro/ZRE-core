"""Run the actual Windows installer and SAME batch launcher twice, not a substitute."""
import json,os,re,shutil,subprocess,sys,tempfile,time,urllib.request,zipfile
from pathlib import Path

assert sys.platform=='win32','This acceptance test requires Windows'
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
ROOT=Path(tempfile.mkdtemp(prefix='ZRE existing installation ')).resolve()
EXPECTED=os.environ['GITHUB_SHA']

def http(path='/version'):
    with urllib.request.urlopen('http://127.0.0.1:8765'+path,timeout=2) as r:return r.read().decode()
def ps(script):
    return subprocess.check_output(['powershell','-NoProfile','-Command',script],text=True).strip()
def stop(process):
    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:raise AssertionError('launcher tree did not close')
    for _ in range(30):
        try:http();time.sleep(.2)
        except Exception:return
    raise AssertionError('8765 still responds after closing exact launcher process tree')
def start_and_check(mode,version,wait=False):
    log=(ROOT/('run-'+mode+'-'+str(time.time_ns())+'.log')).open('w')
    # Actual cmd.exe -> start_dashboard.bat -> PowerShell -> .venv -> runtime.
    process=subprocess.Popen(['cmd','/c',str(ROOT/'start_dashboard.bat'),'-Demo','-NoBrowser'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    try:
        for _ in range(180):
            if process.poll() is not None:raise AssertionError('launcher exited: '+Path(log.name).read_text())
            try:status=json.loads(http());break
            except Exception:time.sleep(.5)
        else:raise AssertionError('runtime not ready: '+Path(log.name).read_text())
        assert status['installedVersion']==status['runtimeVersion']==version,status
        assert status['mode']==mode and Path(status['root'])==ROOT,status
        assert status['assetsVerified'] and status['sourceCommit'],status
        if mode=='TEST':assert status['sourceCommit']==EXPECTED,status
        owners=json.loads(ps('@(Get-NetTCPConnection -LocalPort 8765 -State Listen).OwningProcess | ConvertTo-Json -Compress'))
        owners=owners if isinstance(owners,list) else [owners];assert status['pid'] in owners
        executable=ps(f'(Get-CimInstance Win32_Process -Filter "ProcessId={status["pid"]}").ExecutablePath')
        expected_python=str(ROOT/'.venv'/'Scripts'/'python.exe').lower()
        assert status['executable'].lower()==expected_python,status
        if executable.lower()!=expected_python:
            parent=ps(f'$p=Get-CimInstance Win32_Process -Filter "ProcessId={status["pid"]}"; (Get-CimInstance Win32_Process -Filter "ProcessId=$($p.ParentProcessId)").ExecutablePath')
            assert parent.lower()==expected_python,(executable,parent)
        print('Listener process:',executable,'venv:',status['executable'],flush=True)
        html=http('/');assert f'content="{version}"' in html and f'v{version}' in html
        for url in re.findall(r'(?:src|href)="(/static/[^\"]+)"',html):
            assert '?v='+version in url,url
            served=http(url).encode();local=(ROOT/url.split('?')[0].replace('/static/','web/')).read_bytes()
            assert served==local,url
        # A second invocation must refuse occupied port, without altering running PID.
        conflict=subprocess.run(['cmd','/c',str(ROOT/'start_dashboard.bat'),'-NoBrowser'],cwd=ROOT,capture_output=True,text=True,timeout=30)
        assert conflict.returncode!=0 and '8765' in conflict.stdout+conflict.stderr,conflict
        assert json.loads(http())['instanceId']==status['instanceId']
        # Installer must also stop before touching anything, even with another process.
        blocker=subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(REPO/'install_test_build.ps1'),'-NoLaunch'],capture_output=True,text=True,timeout=30)
        assert blocker.returncode!=0 and str(status['pid']) in blocker.stdout+blocker.stderr
        remembered=ps("(Get-ItemProperty HKCU:\Software\ZRE).InstallationRoot")
        assert Path(remembered)==ROOT,remembered
        if wait:
            # >120s so the real background updater gets a second chance to execute.
            deadline=time.monotonic()+125
            while time.monotonic()<deadline:time.sleep(5)
            again=json.loads(http());assert again['runtimeVersion']==version and again['mode']==mode and again['sourceCommit']==EXPECTED
            assert 'actualizador estable suspendido' in Path(log.name).read_text(encoding='utf-8',errors='replace')
        print('WINDOWS VERIFIED',mode,version,'commit',status['sourceCommit'],'root',status['root'],'PID',status['pid'],flush=True)
        return status
    finally:stop(process);log.close()

try:
    import updater
    updater.ROOT=ROOT
    # Existing stable 2.6.5 with its original launcher, then explicit test installer.
    meta=updater._fetch_json(updater.REMOTE_VERSION_URL,20);assert meta['version']=='2.6.5'
    archive=ROOT/'stable.zip';updater._download(updater._archive_url(meta['archive_ref']),archive,60)
    with zipfile.ZipFile(archive) as z:z.extractall(ROOT/'unpack')
    source=next((ROOT/'unpack').iterdir())
    for p in source.iterdir():
        if p.is_dir():shutil.copytree(p,ROOT/p.name)
        else:shutil.copy2(p,ROOT/p.name)
    shutil.rmtree(ROOT/'unpack');archive.unlink()
    subprocess.run([sys.executable,'-m','venv',str(ROOT/'.venv')],check=True)
    for folder in ('.venv','data','session_logs','reports'):
        p=ROOT/folder;p.mkdir(exist_ok=True);(p/'preserve-marker').write_text('user data')
    (ROOT/'local-settings.json').write_text('user configuration')
    subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(REPO/'install_test_build.ps1'),'-Root',str(ROOT),'-NoLaunch'],check=True)
    first=start_and_check('TEST','2.6.5.1')
    second=start_and_check('TEST','2.6.5.1',wait=True)
    assert first['instanceId']!=second['instanceId']
    # Restore Stable local entrypoint, suppressing automatic GUI launch for QA.
    subprocess.run(['cmd','/c',str(ROOT/'restore_stable.bat'),'-NoLaunch'],cwd=ROOT,check=True)
    start_and_check('STABLE','2.6.5')
    for folder in ('.venv','data','session_logs','reports'):assert (ROOT/folder/'preserve-marker').read_text()=='user data'
    assert (ROOT/'local-settings.json').read_text()=='user configuration'
    print('WINDOWS ACCEPTANCE: installer, same BAT twice, 125-second updater wait, PID/root/port, assets and Restore Stable: OK',flush=True)
finally:
    # Print evidence before removing reproducible test files; user PC never touched.
    for log in ROOT.glob('run-*.log'):print(log.name,log.read_text(encoding='utf-8',errors='replace')[-2500:],flush=True)
    shutil.rmtree(ROOT,ignore_errors=True)
