"""ZRE Core self-updater.

The updater checks a tiny version manifest on GitHub and downloads an immutable
release branch for each published version. Runtime/user data is never replaced.
If a download or install fails, ZRE keeps the installed version and starts.
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import threading
import time
import urllib.request
import zipfile
import re
import sys
from urllib.parse import quote
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = "zatzuro/ZRE-core"
BRANCH = "main"
REMOTE_VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/version.json"
CHECK_INTERVAL_SECONDS = 120
PROTECTED_TOP_LEVEL = {".venv", ".git", ".zre-backup", "data", "session_logs", "reports"}
PROTECTED_NAMES = {"dashboard.log", "session_replay.jsonl", ".zre-build.json"}

def _version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in value.strip().split("."))
    except (TypeError, ValueError):
        return (0,)

def _read_local_version() -> str:
    try:
        return str(json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"])
    except Exception:
        return "0.0.0"

def _request(url: str, timeout: float):
    sep = "&" if "?" in url else "?"
    fresh_url = f"{url}{sep}_zre={time.time_ns()}"
    req = urllib.request.Request(
        fresh_url,
        headers={
            "User-Agent": "ZRE-Core-Updater/2",
            "Accept": "application/octet-stream, application/json;q=0.9, */*;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    return urllib.request.urlopen(req, timeout=timeout)

def _fetch_json(url: str, timeout: float = 5.0) -> dict:
    with _request(url, timeout) as response:
        return json.loads(response.read().decode("utf-8"))

def _download(url: str, target: Path, timeout: float = 30.0) -> None:
    with _request(url, timeout) as response, target.open("wb") as out:
        shutil.copyfileobj(response, out)

def _archive_url(ref: str) -> str:
    return f"https://codeload.github.com/{REPO}/zip/refs/heads/{ref}"

def _copy_program_tree(source: Path, *, build_state=None) -> None:
    # Remove the retired uploader after applying 2.6.4; never remove session logs.
    if not (source / "server" / "session_uploader.py").exists():
        for retired in (ROOT / "server" / "session_uploader.py", ROOT / "upload_queue.jsonl"):
            if retired.is_file():retired.unlink()
        cache=ROOT / "server" / "__pycache__"
        if cache.is_dir():
            for retired in cache.glob("session_uploader.*.pyc"):retired.unlink()

    # Back up only program paths that this package replaces. User folders are
    # untouched; rollback also removes new program files from a failed install.
    files=[]
    for item in source.iterdir():
        if item.name in PROTECTED_TOP_LEVEL or item.name in PROTECTED_NAMES:continue
        for src in ([item] if item.is_file() else item.rglob("*")):
            if not src.is_file():continue
            rel=src.relative_to(source)
            if any(part in PROTECTED_TOP_LEVEL for part in rel.parts):continue
            if src.is_symlink():raise RuntimeError("archivo simbólico no permitido")
            files.append((src,ROOT/rel))
    files.sort(key=lambda pair:(pair[0].name=="version.json",str(pair[0])))
    with tempfile.TemporaryDirectory(prefix="zre-rollback-") as backup_dir:
        if build_state is not None:
            state_file=Path(backup_dir)/"state.json"
            state_file.write_text(json.dumps(build_state,indent=2),encoding="utf-8")
            files.append((state_file,ROOT/".zre-build.json"))
        backups=[]
        for index,(_,dst) in enumerate(files):
            saved=Path(backup_dir)/str(index) if dst.is_file() else None
            if saved:shutil.copy2(dst,saved)
            backups.append((dst,saved))
        try:
            for src,dst in files:
                dst.parent.mkdir(parents=True,exist_ok=True)
                tmp=dst.with_name(dst.name+".zre-new")
                shutil.copy2(src,tmp);tmp.replace(dst)
        except Exception:
            for dst,saved in reversed(backups):
                if saved:shutil.copy2(saved,dst)
                elif dst.is_file():dst.unlink()
                tmp=dst.with_name(dst.name+".zre-new")
                if tmp.is_file():tmp.unlink()
            raise

def update_if_available(*, background: bool = False, test_ref: str | None = None,
                        restore_stable: bool = False) -> bool:
    local = _read_local_version()
    # TEST is a locally pinned installation, never an automatic branch follower.
    state_path=ROOT/".zre-build.json"
    if not test_ref and not restore_stable and state_path.exists():
        try:
            state=json.loads(state_path.read_text(encoding="utf-8"))
            if state.get("mode")=="TEST":
                print(f"TEST BUILD ACTIVE: v{local}; commit {state.get('sourceCommit')}; actualizador estable suspendido.")
                return False
            if state.get("mode")!="STABLE":raise ValueError("modo inválido")
        except Exception as exc:
            print(f"Estado de build inválido; no actualizo: {exc}")
            return False
    try:
        if test_ref:
            if not re.fullmatch(r"develop/[A-Za-z0-9._/-]+",test_ref) or ".." in test_ref:
                raise ValueError("La prueba requiere una rama develop válida")
            # Resolve once: manifest and archive belong to the exact same commit.
            commit=_fetch_json(f"https://api.github.com/repos/{REPO}/commits/{quote(test_ref,safe='')}",20)
            commit_sha=commit["sha"]
            if not re.fullmatch(r"[0-9a-f]{40}",commit_sha):raise ValueError("SHA inválido")
            remote_meta=_fetch_json(f"https://raw.githubusercontent.com/{REPO}/{commit_sha}/version.json",20)
            if remote_meta.get("channel")!="development" or remote_meta.get("archive_ref")!=test_ref:
                raise ValueError("El manifiesto no corresponde a la rama de prueba")
        else:
            remote_meta = _fetch_json(REMOTE_VERSION_URL)
            if restore_stable:
                commit=_fetch_json(f"https://api.github.com/repos/{REPO}/commits/main",20)
                commit_sha=commit['sha']
                if not re.fullmatch(r"[0-9a-f]{40}",commit_sha):raise ValueError("SHA estable inválido")
                remote_meta=_fetch_json(f"https://raw.githubusercontent.com/{REPO}/{commit_sha}/version.json",20)
        remote = str(remote_meta.get("version", "0.0.0"))
        archive_ref = str(remote_meta.get("archive_ref") or BRANCH)
    except Exception as exc:
        print(f"ZRE Update: no pude consultar GitHub; sigo con v{local} ({type(exc).__name__}).")
        return False

    if not test_ref and not restore_stable and _version_tuple(remote) <= _version_tuple(local):
        print(f"ZRE Update: v{local} al dia.")
        return False

    where = "en segundo plano" if background else "antes de iniciar"
    print(f"ZRE Update: v{local} -> v{remote}. Descargando {archive_ref} {where}...")
    try:
        with tempfile.TemporaryDirectory(prefix="zre_update_") as temp_dir:
            temp = Path(temp_dir)
            archive = temp / "zre.zip"
            url=f"https://codeload.github.com/{REPO}/zip/{commit_sha}" if test_ref or restore_stable else _archive_url(archive_ref)
            _download(url, archive,60 if test_ref else 30)
            if archive.stat().st_size < 5_000:
                raise RuntimeError("descarga incompleta")
            with zipfile.ZipFile(archive) as zf:
                destination=(temp/"unpacked").resolve()
                for name in zf.namelist():
                    path=(destination/name).resolve()
                    if not path.is_relative_to(destination):raise RuntimeError("ruta ZIP inválida")
                bad = zf.testzip()
                if bad:
                    raise RuntimeError(f"ZIP dañado: {bad}")
                zf.extractall(temp / "unpacked")
            roots = [p for p in (temp / "unpacked").iterdir() if p.is_dir()]
            if len(roots) != 1 or not (roots[0] / "version.json").exists():
                raise RuntimeError("paquete de actualización inválido")
            package_meta = json.loads((roots[0] / "version.json").read_text(encoding="utf-8"))
            if str(package_meta.get("version")) != remote:
                raise RuntimeError(f"el paquete trae v{package_meta.get('version')} y esperaba v{remote}")
            if test_ref and (package_meta.get("channel")!="development" or package_meta.get("archive_ref")!=test_ref):
                raise RuntimeError("canal de prueba incoherente")
            if test_ref or restore_stable:
                # Retain only the installation controller when restoring old stable
                # code. Telemetry, HTML and all assets come unchanged from main.
                if restore_stable:
                    for name in ("start_dashboard.bat","zre_launch.ps1","zre_runtime.py","zre_build.py","install_test_build.ps1","restore_stable.bat"):
                        if (ROOT/name).is_file():shutil.copy2(ROOT/name,roots[0]/name)
                    shutil.copy2(Path(__file__),roots[0]/"updater.py")
                hashes={str(p.relative_to(roots[0])).replace("\\","/"):__import__('hashlib').sha256(p.read_bytes()).hexdigest()
                    for folder in ('web','server') for p in sorted((roots[0]/folder).rglob('*'))
                    if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.log')}
                build_state={"mode":"TEST" if test_ref else "STABLE","version":remote,
                    "channel":"development" if test_ref else "stable","sourceRef":test_ref or "main",
                    "sourceCommit":commit_sha,"root":str(ROOT.resolve()),"assetHashes":hashes}
                _copy_program_tree(roots[0],build_state=build_state)
            else:_copy_program_tree(roots[0])

        installed = _read_local_version()
        if installed != remote:
            raise RuntimeError(f"verificación final falló: quedó v{installed}")
        suffix = " Queda instalada; no reinicio ZRE durante una carrera." if background else ""
        print(f"ZRE Update: OK. v{remote} instalada.{suffix}")
        return True
    except Exception as exc:
        print(f"ZRE Update: FALLO. Se conserva v{local} ({type(exc).__name__}: {exc}).")
        return False

def start_background_updater(interval: int = CHECK_INTERVAL_SECONDS):
    interval = max(60, int(interval))
    def worker():
        while True:
            try:
                update_if_available(background=True)
            except Exception as exc:
                print(f"ZRE Update: comprobacion omitida ({type(exc).__name__}).")
            time.sleep(interval)
    thread = threading.Thread(target=worker, name="zre-auto-update", daemon=True)
    thread.start()
    return thread

if __name__ == "__main__":
    parser=argparse.ArgumentParser(description="Updater ZRE: estable por defecto; prueba sólo por petición explícita.")
    channels=parser.add_mutually_exclusive_group()
    channels.add_argument("--test-ref",help="Instala y fija TEST hasta Restore Stable explícito.")
    channels.add_argument("--restore-stable",action="store_true",help="Vuelve explícitamente al estable, incluso con una versión inferior.")
    parser.add_argument("--root",type=Path,help="Carpeta existente que contiene start_dashboard.bat")
    args=parser.parse_args()
    if args.root:
        ROOT=args.root.resolve()
        if not (ROOT/"start_dashboard.bat").is_file() or not (ROOT/"version.json").is_file():
            parser.error("La carpeta no es una instalación existente de ZRE")
    ok=update_if_available(test_ref=args.test_ref,restore_stable=args.restore_stable)
    if args.test_ref or args.restore_stable:sys.exit(0 if ok else 1)
