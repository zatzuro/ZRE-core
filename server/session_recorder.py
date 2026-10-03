"""Compact session logging and upload queue for ZRE diagnostics."""
import json
from datetime import datetime, timezone
from pathlib import Path

class SessionRecorder:
    def __init__(self, path, max_bytes=5_000_000):
        self.path=Path(path);self.max_bytes=max_bytes
        self.root=self.path.parent/"session_logs";self.root.mkdir(parents=True,exist_ok=True)
        self.retention_days=7
        self.session_id=None;self.session_dir=None;self.timeline_path=None
        self.summary={"events":0,"laps":0,"predictions":0,"outcomes":0}

    def _rotate_if_needed(self):
        try:
            if self.path.exists() and self.path.stat().st_size>=self.max_bytes:
                backup=self.path.with_suffix(self.path.suffix+'.1')
                if backup.exists():backup.unlink()
                self.path.replace(backup)
        except OSError:pass

    def start_session(self, identity, metadata=None):
        key=str(identity or "unknown").replace("/","_").replace("\\","_").replace(" ","_")
        stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.session_id=f"{stamp}_{key}"[:180]
        self.session_dir=self.root/self.session_id;self.session_dir.mkdir(parents=True,exist_ok=True)
        self.timeline_path=self.session_dir/"timeline.jsonl"
        self.summary={"sessionId":self.session_id,"startedAt":stamp,"events":0,"laps":0,"predictions":0,"outcomes":0,
                      "metadata":metadata or {}}
        self._write_json(self.session_dir/"session.json",self.summary)
        return self.session_id

    def _write_json(self,path,data):
        try:path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        except OSError:pass

    def write(self, record):
        self._rotate_if_needed()
        item=dict(record or {});item.setdefault("utc",datetime.now(timezone.utc).isoformat())
        try:
            with self.path.open('a',encoding='utf-8') as handle:handle.write(json.dumps(item,ensure_ascii=False,separators=(',',':'))+'\n')
        except OSError:pass
        if self.timeline_path:
            try:
                with self.timeline_path.open('a',encoding='utf-8') as handle:handle.write(json.dumps(item,ensure_ascii=False,separators=(',',':'))+'\n')
                self.summary["events"]+=1
                kind=item.get("type")
                if kind=="lap":self.summary["laps"]+=1
                if kind=="strategy_prediction":self.summary["predictions"]+=1
                if kind=="prediction_outcome":self.summary["outcomes"]+=1
            except OSError:pass

    def finish_session(self, reason="session-change", extra=None):
        if not self.session_dir:return None
        self.summary.update({"finishedAt":datetime.now(timezone.utc).isoformat(),"finishReason":reason})
        if extra:self.summary["final"]=extra
        self._write_json(self.session_dir/"summary.json",self.summary)
        md=[f"# ZRE Session {self.session_id}","",f"- Eventos: {self.summary['events']}",f"- Vueltas: {self.summary['laps']}",
            f"- Predicciones: {self.summary['predictions']}",f"- Resultados evaluados: {self.summary['outcomes']}",
            f"- Cierre: {reason}","","> Datos SDK observados e inferencias ZRE se distinguen por el campo source."]
        try:(self.session_dir/"summary.md").write_text("\n".join(md)+"\n",encoding="utf-8")
        except OSError:pass
        self.cleanup_old_sessions()
        finished=self.session_dir
        self.session_id=None;self.session_dir=None;self.timeline_path=None
        return finished

    def cleanup_old_sessions(self):
        """Delete completed local journals older than the retention window."""
        now=datetime.now(timezone.utc).timestamp();cutoff=max(1,int(self.retention_days))*86400
        try:
            for folder in self.root.iterdir():
                if not folder.is_dir() or folder==self.session_dir:continue
                summary=folder/"summary.json"
                marker=summary if summary.exists() else folder
                try:
                    if now-marker.stat().st_mtime<=cutoff:continue
                    for child in folder.iterdir():
                        if child.is_file():child.unlink()
                    folder.rmdir()
                except OSError:pass
        except OSError:pass

