"""ZRE Core self-updater.

Runs before the dashboard starts. It only updates program files from the stable
GitHub repository and never removes local runtime data. If GitHub is unavailable,
the dashboard starts normally with the installed version.
"""
from __future__ import annotations

import json
import shutil
import socket
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = "zatzuro/ZRE-core"
BRANCH = "main"
REMOTE_VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/version.json"
ARCHIVE_URL = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"
CHECK_INTERVAL_SECONDS = 120
PROTECTED_TOP_LEVEL = {".venv", ".git", ".zre-backup", "data"}
PROTECTED_NAMES = {"dashboard.log", "session_replay.jsonl"}

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

def _fetch_json(url: str, timeout: float = 2.5) -> dict:
    sep = "&" if "?" in url else "?"
    fresh_url = f"{url}{sep}_zre={time.time_ns()}"
    req = urllib.request.Request(fresh_url, headers={"User-Agent": "ZRE-Core-Updater", "Cache-Control": "no-cache", "Pragma": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

def _download(url: str, target: Path, timeout: float = 12.0) -> None:
    sep = "&" if "?" in url else "?"
    fresh_url = f"{url}{sep}_zre={time.time_ns()}"
    req = urllib.request.Request(fresh_url, headers={"User-Agent": "ZRE-Core-Updater", "Cache-Control": "no-cache", "Pragma": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as response, target.open("wb") as out:
        shutil.copyfileobj(response, out)

def _copy_program_tree(source: Path) -> None:
    for item in source.iterdir():
        if item.name in PROTECTED_TOP_LEVEL or item.name in PROTECTED_NAMES:
            continue
        destination = ROOT / item.name
        if item.is_dir():
            shutil.copytree(item, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(item, destination)

def update_if_available(*, background: bool = False) -> bool:
    local = _read_local_version()
    try:
        remote_meta = _fetch_json(REMOTE_VERSION_URL)
        remote = str(remote_meta.get("version", "0.0.0"))
    except Exception as exc:
        print(f"ZRE Update: sin conexion al canal estable; inicio normal ({type(exc).__name__}).")
        return False
    if _version_tuple(remote) <= _version_tuple(local):
        print(f"ZRE Update: v{local} al dia.")
        return False
    where = "en segundo plano" if background else "antes de iniciar"
    print(f"ZRE Update: v{local} -> v{remote}. Actualizando {where}...")
    try:
        with tempfile.TemporaryDirectory(prefix="zre_update_") as temp_dir:
            temp = Path(temp_dir)
            archive = temp / "zre.zip"
            _download(ARCHIVE_URL, archive)
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(temp / "unpacked")
            roots = [p for p in (temp / "unpacked").iterdir() if p.is_dir()]
            if len(roots) != 1 or not (roots[0] / "version.json").exists():
                raise RuntimeError("paquete de actualizacion invalido")
            package_meta = json.loads((roots[0] / "version.json").read_text(encoding="utf-8"))
            if str(package_meta.get("version")) != remote:
                raise RuntimeError("version del paquete no coincide")
            _copy_program_tree(roots[0])
        suffix = " La carrera sigue con el codigo ya cargado; la nueva version queda activa al proximo inicio." if background else ""
        print(f"ZRE Update: actualizado correctamente a v{remote}.{suffix}")
        return True
    except Exception as exc:
        print(f"ZRE Update: no se pudo actualizar; se conserva v{local} ({type(exc).__name__}: {exc}).")
        return False

def start_background_updater(interval: int = CHECK_INTERVAL_SECONDS):
    interval = max(60, int(interval))
    def worker():
        while True:
            try:
                update_if_available(background=True)
            except Exception as exc:
                print(f"ZRE Update: comprobacion en segundo plano omitida ({type(exc).__name__}).")
            time.sleep(interval)
    thread = threading.Thread(target=worker, name="zre-auto-update", daemon=True)
    thread.start()
    return thread

def _dashboard_alive(port: int = 8765) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False

def watch_for_updates(interval: int = CHECK_INTERVAL_SECONDS) -> None:
    interval = max(60, int(interval))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not _dashboard_alive():
        time.sleep(2)
    if not _dashboard_alive():
        return
    while _dashboard_alive():
        time.sleep(interval)
        if not _dashboard_alive():
            return
        try:
            update_if_available(background=True)
        except Exception:
            pass

def _spawn_watcher() -> None:
    import os
    import subprocess
    import sys
    try:
        flags = 0
        if os.name == "nt":
            flags = 0x00000008 | 0x08000000
        subprocess.Popen(
            [sys.executable, str(ROOT / "updater.py"), "--watch"],
            cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=flags, close_fds=(os.name != "nt"),
        )
    except Exception as exc:
        print(f"ZRE Update: no se pudo iniciar vigilancia automatica ({type(exc).__name__}).")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=CHECK_INTERVAL_SECONDS)
    args, _ = parser.parse_known_args()
    if args.watch:
        watch_for_updates(args.interval)
    else:
        update_if_available()
