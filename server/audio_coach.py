"""Optional local Windows SAPI voice; newest message supersedes pending speech."""
import os
import queue
import subprocess
import threading

class AudioCoach:
    def __init__(self):
        self.pending = queue.Queue(maxsize=1)
        self.thread = None

    def say(self, message):
        if os.name != 'nt' or not message:
            return
        try:
            self.pending.get_nowait()
        except queue.Empty:
            pass
        self.pending.put_nowait(message[:520])
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def _run(self):
        while True:
            try:
                message = self.pending.get(timeout=.1)
            except queue.Empty:
                return
            script = ("$s=New-Object -ComObject SAPI.SpVoice; "
                      "$v=$s.GetVoices() | Where-Object { $_.GetAttribute('Language') -match '0C0A|080A|040A|2C0A|100A|140A|180A|1C0A|200A|240A|280A|300A|340A|380A|3C0A|400A|440A|480A|4C0A|500A' } | Select-Object -First 1; "
                      "if($v){$s.Voice=$v}; $s.Rate=2; $s.Volume=100; "
                      "$s.Speak([Console]::In.ReadToEnd()) | Out-Null")
            try:
                subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                               input=message, text=True, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=15, creationflags=0x08000000)
            except (OSError, subprocess.TimeoutExpired):
                pass
