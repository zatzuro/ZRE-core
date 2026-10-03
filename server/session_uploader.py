"""Non-blocking uploader for completed ZRE session journals.

Uploads are intentionally disabled unless ZRE_LOG_UPLOAD_URL is configured.
Authentication is read only from local environment variables; no token is
stored in source code or in the journal.
"""
import json, os, threading, urllib.request
from pathlib import Path

def upload_pending(queue_path):
    queue=Path(queue_path);url=os.getenv("ZRE_LOG_UPLOAD_URL");token=os.getenv("ZRE_LOG_UPLOAD_TOKEN")
    if not url or not queue.exists():return {"enabled":False,"uploaded":0}
    try:items=[json.loads(x) for x in queue.read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError,ValueError):return {"enabled":True,"uploaded":0}
    uploaded=0;remaining=[]
    for item in items:
        if item.get("status")!="PENDING":continue
        folder=Path(item.get("path",""))
        try:
            files={}
            for name in ("session.json","summary.json","summary.md","timeline.jsonl"):
                p=folder/name
                if p.exists():files[name]=p.read_text(encoding="utf-8")
            body=json.dumps({"sessionId":item.get("sessionId"),"files":files},ensure_ascii=False).encode("utf-8")
            headers={"Content-Type":"application/json","User-Agent":"ZRE-Core"}
            if token:headers["Authorization"]="Bearer "+token
            req=urllib.request.Request(url,data=body,headers=headers,method="POST")
            with urllib.request.urlopen(req,timeout=8) as response:
                if 200<=response.status<300:uploaded+=1
                else:remaining.append(item)
        except Exception:remaining.append(item)
    try:queue.write_text("".join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+"\n" for x in remaining),encoding="utf-8")
    except OSError:pass
    return {"enabled":True,"uploaded":uploaded,"pending":len(remaining)}

def upload_pending_background(queue_path):
    thread=threading.Thread(target=upload_pending,args=(queue_path,),daemon=True,name="zre-log-uploader")
    thread.start();return thread
