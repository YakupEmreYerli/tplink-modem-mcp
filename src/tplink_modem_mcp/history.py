"""Join/leave history of clients, which the router itself does not keep.

A sampler compares the client list with the previous sample and appends events to a JSON-lines file.
"""
import json
import os
import threading
import time
from pathlib import Path

STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "tplink-modem-mcp"


class History:
    def __init__(self, path: Path | None = None):
        self.path = path or STATE / "presence.jsonl"
        self.last = None  # mac -> {"ip", "name", "type"}
        self._lock = threading.Lock()

    def sample(self, devices: list[dict]) -> list[dict]:
        """Record one sample; returns the new events."""
        now = time.time()
        cur = {d["mac"]: {"ip": d.get("ip"), "name": d.get("hostname"), "connection": d.get("connection")}
               for d in devices if d.get("mac")}
        events = []
        with self._lock:
            if self.last is not None:
                for mac in cur.keys() - self.last.keys():
                    events.append({"t": now, "event": "join", "mac": mac, **cur[mac]})
                for mac in self.last.keys() - cur.keys():
                    events.append({"t": now, "event": "leave", "mac": mac, **self.last[mac]})
                for mac in cur.keys() & self.last.keys():
                    if cur[mac]["ip"] != self.last[mac]["ip"]:
                        events.append({"t": now, "event": "ip_change", "mac": mac, "old_ip": self.last[mac]["ip"],
                                       **cur[mac]})
            self.last = cur
            if events:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a") as f:
                    for e in events:
                        f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return events

    def query(self, since_hours: float = 24, mac: str = "", limit: int = 200) -> list[dict]:
        if not self.path.exists():
            return []
        cutoff = time.time() - since_hours * 3600
        mac = mac.lower().replace("-", ":")
        out = []
        with self.path.open() as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e["t"] >= cutoff and (not mac or e["mac"].lower().replace("-", ":") == mac):
                    e["time"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["t"]))
                    out.append(e)
        return out[-limit:]
