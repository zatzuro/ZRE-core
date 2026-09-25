"""ZRE Core self-updater.

Runs before the dashboard starts. It only updates program files from the stable
GitHub repository and never removes local runtime data. If GitHub is unavailable,
the dashboard starts normally with the installed version.
"""
from __future__ import annotations
import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = "zatzuro/ZRE-core"
BRANCH = "main"
REMOTE_VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/version.json"
ARCHIVE_URL = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"
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
    req = urllib.request.Request(url, headers={"User-Agent": "ZRE-Core-Updater"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

def _download(url: str, target: Path, timeout: float = 12.0) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "ZRE-Core-Updater"})
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

def update_if_available() -> bool:
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
    print(f"ZRE Update: v{local} -> v{remote}. Actualizando antes de iniciar...")
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
        print(f"ZRE Update: actualizado correctamente a v{remote}.")
        return True
    except Exception as exc:
        print(f"ZRE Update: no se pudo actualizar; se conserva v{local} ({type(exc).__name__}: {exc}).")
        return False

if __name__ == "__main__":
    update_if_available()
