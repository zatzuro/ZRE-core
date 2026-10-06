"""Local installation identity shared by updater and the existing bridge launcher."""
import hashlib
import json
import os
import sys
from pathlib import Path

STATE_NAME='.zre-build.json'

def read_state(root):
    path=Path(root)/STATE_NAME
    if not path.exists():return {}
    state=json.loads(path.read_text(encoding='utf-8'))
    if state.get('mode') not in ('TEST','STABLE'):raise ValueError('Estado de instalación inválido')
    return state

def asset_hashes(root):
    root=Path(root)
    return {str(p.relative_to(root)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('web','server') for p in sorted((root/folder).rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.log')}

def identity(root,runtime_version,instance_id=None):
    root=Path(root).resolve();meta=json.loads((root/'version.json').read_text(encoding='utf-8'))
    state=read_state(root)
    return {'installedVersion':str(meta['version']),'runtimeVersion':str(runtime_version),
            'mode':state.get('mode','STABLE'),'channel':state.get('channel',meta.get('channel','stable')),
            'sourceRef':state.get('sourceRef',meta.get('archive_ref')),'sourceCommit':state.get('sourceCommit'),
            'root':str(root),'pid':os.getpid(),'executable':sys.executable,'instanceId':instance_id,
            'assetsVerified':bool(state.get('assetHashes')) and asset_hashes(root)==state['assetHashes']}
