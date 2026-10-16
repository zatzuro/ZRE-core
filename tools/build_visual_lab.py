"""Build an isolated, static Visual Lab from the real ZRE web frontend.

Only static public code and synthetic adapter are emitted. The Windows source
is never patched. No Python server, WebSocket, local API or user data required.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web"
PREVIEW = ROOT / "preview"
CUT = "let webBuildReloading=false,buildCheckPending=false,reconnectTimer=null;"


def build(out: Path, branch: str, sha: str) -> None:
    version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"]
    src = (STATIC / "index.html").read_text(encoding="utf-8")
    assert src.count("/static/") >= 6, "ZRE frontend paths have changed"
    assert '<script src="/static/app.js' in src, "ZRE entrypoint changed"
    assert 'websocket' not in str(out).lower(), "Invalid output path"
    out.mkdir(parents=True, exist_ok=True)
    target = out / "static"
    target.mkdir(exist_ok=True)

    # Copy each real renderer and stylesheet verbatim. app.js is the single
    # compiled transport exception and retains ALL rendering functions.
    for source in STATIC.iterdir():
        if source.is_file() and source.suffix in (".js", ".css"):
            if source.name == "session_archive.js":
                continue  # Productive archives/export APIs must not exist in Lab.
            code = source.read_text(encoding="utf-8")
            if source.name == "app.js":
                assert code.count(CUT) == 1, "Transport sentinel missing/ambiguous"
                code = code.split(CUT, 1)[0]
                code += (
                    "\n// Visual Lab transport: local in-memory adapter, no network.\n"
                    "socket={readyState:WebSocket.OPEN,send:raw=>window.ZREVisualLab.action(JSON.parse(raw))};\n"
                    "window.ZREVisualLab.start(render);\n"
                )
                assert "new WebSocket" not in code
                assert "checkInstalledWebBuild" not in code
            (target / source.name).write_text(code, encoding="utf-8")
    shutil.copyfile(PREVIEW / "visual_lab.js", target / "visual_lab.js")
    shutil.copyfile(PREVIEW / "visual_lab.css", target / "visual_lab.css")

    # Pages is hosted under /ZRE-core/, never the domain root.
    html = src.replace('"/static/', '"./static/')
    html = re.sub(r'<script src="\./static/session_archive\.js[^"]*"></script>', '', html)
    assert "session_archive.js" not in html, "Archive scripts must not execute"
    html = html.replace("</head>", '<link rel="stylesheet" href="./static/visual_lab.css"></head>', 1)
    inject = (
        '<script>window.ZRELabManifest='
        + json.dumps({"sha": sha, "branch": branch, "version": version}, ensure_ascii=False)
        + ';</script>\n'
        '<script src="./static/visual_lab.js"></script>\n'
    )
    html = html.replace('<script src="./static/app.js', inject + '<script src="./static/app.js', 1)
    html = html.replace('<body data-view="live">', '<body data-view="live" data-visual-lab="true">'
                        '<div id="lab-simulation-banner" role="status">ZRE VISUAL LAB · DATOS SIMULADOS · SIN CONEXIÓN SDK</div>', 1)
    assert html.count("visual_lab.js") == 1 and '"/static/' not in html
    (out / "dashboard.html").write_text(html, encoding="utf-8")
    (out / "index.html").write_text((PREVIEW / "shell.html").read_text(encoding="utf-8"), encoding="utf-8")
    for filename in ("lab_shell.css", "lab_shell.js"):
        shutil.copyfile(PREVIEW / filename, out / filename)
    (out / "lab_manifest.json").write_text(
        json.dumps({"branch": branch, "sha": sha, "version": version, "simulated": True},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")

    assert not any(path.suffix in (".db", ".sqlite", ".log", ".jsonl", ".csv", ".html")
                   for path in target.iterdir()), "Only known CSS/JS may be exported"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "visual-lab")
    parser.add_argument("--branch", default="develop/visual-lab-web")
    parser.add_argument("--sha")
    args = parser.parse_args()
    try:
        git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        git_sha = "UNAVAILABLE"
    build(args.out, args.branch, args.sha or git_sha)
    print("Visual Lab static build:", args.out, "SHA:", args.sha or git_sha)
