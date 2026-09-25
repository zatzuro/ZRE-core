"""ZRE Core self-updater.

The updater checks a tiny version manifest on GitHub and downloads an immutable
release branch for each published version. Runtime/user data is never replaced.
If a download or install fails, ZRE keeps the installed version and starts.
"""
from __future__ import annotations

import json
import shutil
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

def _copy_program_tree(source: Path) -> None:
    for item in source.iterdir():
        if item.name in PROTECTED_TOP_LEVEL or item.name in PROTECTED_NAMES:
            continue
        destination = ROOT / item.name
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            for src in item.rglob("*"):
                if src.is_dir():
                    continue
                rel = src.relative_to(item)
                if rel.parts and rel.parts[0] in PROTECTED_TOP_LEVEL:
                    continue
                dst = destination / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_name(dst.name + ".zre-new")
                shutil.copy2(src, tmp)
                tmp.replace(dst)
        else:
            tmp = destination.with_name(destination.name + ".zre-new")
            shutil.copy2(item, tmp)
            tmp.replace(destination)

def update_if_available(*, background: bool = False) -> bool:
    local = _read_local_version()
    try:
        remote_meta = _fetch_json(REMOTE_VERSION_URL)
        remote = str(remote_meta.get("version", "0.0.0"))
        archive_ref = str(remote_meta.get("archive_ref") or BRANCH)
    except Exception as exc:
        print(f"ZRE Update: no pude consultar GitHub; sigo con v{local} ({type(exc).__name__}).")
        return False

    if _version_tuple(remote) <= _version_tuple(local):
        print(f"ZRE Update: v{local} al dia.")
        return False

    where = "en segundo plano" if background else "antes de iniciar"
    print(f"ZRE Update: v{local} -> v{remote}. Descargando {archive_ref} {where}...")
    try:
        with tempfile.TemporaryDirectory(prefix="zre_update_") as temp_dir:
            temp = Path(temp_dir)
            archive = temp / "zre.zip"
            _download(_archive_url(archive_ref), archive)
            if archive.stat().st_size < 5_000:
                raise RuntimeError("descarga incompleta")
            with zipfile.ZipFile(archive) as zf:
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
            _copy_program_tree(roots[0])

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
    update_if_available()
