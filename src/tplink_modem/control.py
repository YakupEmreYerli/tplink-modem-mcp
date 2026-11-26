"""Full access to the router's data model, the same one its web UI uses.

TP-Link's CGI firmwares (the legacy ISP ones, and the MR/VR families in tplinkrouterc6u) keep every setting in
named objects (LAN_WLAN, LAN_DHCP_STATIC_ADDR, WAN_IP_CONN_PORTMAPPING, ...). The web UI reads them with GL/GET and
changes them with SET/ADD/DEL, and runs operations such as ACT_REBOOT with OP. The router publishes the object
names in /js/oid_str.js, so anything the web UI can do, these functions can do.

Changes go through a policy read from the environment, so a user can narrow what the assistant may change:
  TPLINK_WRITE=off            read only: change tools are not offered at all
  TPLINK_ALLOW=LAN_WLAN*,...  only these objects / operations may be changed (* matches any suffix)
  TPLINK_DENY=ACT_FACTORY_RESET,USER_CFG,...  never these
  TPLINK_SHOW_SECRETS=1       show passwords and keys in reads (masked by default)
"""
import fnmatch
import os
import re

ACTIONS = {"set": "SET", "add": "ADD", "delete": "DEL"}
SECRET = re.compile(r"(?i)(key|pass|psk|pwd|secret|pin)(?!.*(enable|index|interval|failures|size))")
ZERO = "0,0,0,0,0,0"


def _list(name: str) -> list[str]:
    return [p.strip() for p in os.environ.get(name, "").split(",") if p.strip()]


def writes_enabled() -> bool:
    return os.environ.get("TPLINK_WRITE", "on").lower() not in ("off", "0", "false", "no")


def check_allowed(name: str) -> None:
    """Raise PermissionError if the policy forbids changing this object or running this operation."""
    if not writes_enabled():
        raise PermissionError("changes are turned off (TPLINK_WRITE=off)")
    if any(fnmatch.fnmatchcase(name, p) for p in _list("TPLINK_DENY")):
        raise PermissionError(f"{name} is in TPLINK_DENY")
    allow = _list("TPLINK_ALLOW")
    if allow and not any(fnmatch.fnmatchcase(name, p) for p in allow):
        raise PermissionError(f"{name} is not in TPLINK_ALLOW")


def mask(row: dict) -> dict:
    if os.environ.get("TPLINK_SHOW_SECRETS") == "1":
        return row
    return {k: ("***" if v and SECRET.search(k) else v) for k, v in row.items()}


def _stack(s: str | None) -> str:
    s = (s or "").strip()
    if not s:
        return ZERO
    parts = s.split(",")
    if not all(p.strip().isdigit() for p in parts) or len(parts) > 6:
        raise ValueError(f"stack must be up to six comma-separated numbers, got {s!r}")
    return ",".join([p.strip() for p in parts] + ["0"] * (6 - len(parts)))


class DataModel:
    """Works on any client with req_act/ActItem (LegacyCgiClient and the tplinkrouterc6u MR/VR clients)."""

    def __init__(self, client):
        if not (hasattr(client, "req_act") and hasattr(client, "ActItem")):
            raise NotImplementedError(
                f"{type(client).__name__} does not use TP-Link's CGI data model; only the curated tools work on it")
        self.c = client

    def objects(self) -> list[str]:
        """Object names the firmware knows, from the web UI's own /js/oid_str.js (feature flags and page ids left out)."""
        text = self.c.req.get(f"{self.c.host}/js/oid_str.js", timeout=self.c.timeout).text
        names = set(re.findall(r"\b([A-Z][A-Z0-9_]{2,})\s*[:=]", text))
        return sorted(n for n in names if not n.startswith(("INCLUDE_", "INLCUDE_", "PAGE_", "SUPPORT_")))

    def operations(self) -> list[str]:
        """Operation names for run(), from the web UI's lib.js (ACT_REBOOT, ACT_DHCP_RENEW, ...)."""
        text = self.c.req.get(f"{self.c.host}/js/lib.js", timeout=self.c.timeout).text
        return sorted(set(re.findall(r'var ACT_OP_\w+\s*=\s*"(ACT_\w+)"', text)))

    def _act(self, kind: str, oid: str, stack: str = ZERO, pstack: str = ZERO, attrs: list[str] | None = None):
        item = self.c.ActItem(getattr(self.c.ActItem, kind), oid, stack, pstack, attrs or [])
        resp = self.c.req_act([item])
        text = resp[0].text if hasattr(resp[0], "text") else str(resp[0])
        err = re.search(r"\[error\](\d+)", text)
        if err and err.group(1) != "0":
            raise RuntimeError(f"router refused {kind} {oid} (error {err.group(1)})")
        return text

    @staticmethod
    def _parse(text: str) -> list[dict]:
        out = []
        for block in text.split("\n["):
            head, _, body = block.lstrip("[").partition("\n")
            m = re.match(r"([\d,]+)\]\d+$", head.strip())
            if not m:
                continue
            row = {"_stack": m.group(1)}
            for line in body.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    row[k.strip()] = v.strip()
            out.append(row)
        return out

    def read(self, oid: str, stack: str = "", attributes: list[str] | None = None) -> list[dict]:
        """Every instance of oid, or the one at stack; attributes limits the fields."""
        oid = oid.strip().upper()
        if stack:
            rows = self._parse(self._act("GET", oid, _stack(stack), ZERO, attributes))
            for r in rows:
                if r["_stack"] == ZERO:
                    r["_stack"] = _stack(stack)
        else:
            rows = self._parse(self._act("GL", oid, ZERO, ZERO, attributes))
            if not rows:  # singletons and some tables answer GS, not GL
                rows = self._parse(self._act("GS", oid, ZERO, ZERO, attributes))
        return [mask(r) for r in rows]

    def change(self, action: str, oid: str, stack: str = "", parent_stack: str = "",
               attributes: dict | None = None) -> dict:
        oid = oid.strip().upper()
        kind = ACTIONS.get(action)
        if not kind:
            raise ValueError(f"action must be one of {sorted(ACTIONS)}")
        check_allowed(oid)
        attrs = [f"{k}={v}" for k, v in (attributes or {}).items()]
        if kind in ("SET", "DEL") and not stack:
            stack = ZERO  # singleton objects live at 0,0,0,0,0,0
        self._act(kind, oid, _stack(stack), _stack(parent_stack), attrs)
        return {"done": action, "object": oid, "stack": _stack(stack)}

    def run(self, operation: str) -> dict:
        operation = operation.strip().upper()
        if not operation.startswith("ACT_"):
            operation = "ACT_" + operation
        check_allowed(operation)
        self._act("OP", operation)
        return {"done": "run", "operation": operation}
