"""One shared, serialised connection to the router.

TP-Link firmwares allow a single admin session at a time, so every call goes through one lock and one client.
Authentication and reads can retry after a session failure.
"""
import logging
import os
import threading
from dataclasses import fields, is_dataclass
from enum import Enum
from ipaddress import IPv4Address, IPv6Address

from tplinkrouterc6u import TplinkRouterProvider
import tplinkrouterc6u

from .legacy import LegacyCgiClient

log = logging.getLogger(__name__)


class Config:
    def __init__(self):
        self.host = os.environ.get("TPLINK_HOST", "http://192.168.1.1").rstrip("/")
        if "://" not in self.host:
            self.host = "http://" + self.host
        self.username = os.environ.get("TPLINK_USERNAME", "admin")
        self.password = os.environ.get("TPLINK_PASSWORD", "")
        self.client = os.environ.get("TPLINK_CLIENT", "")  # "legacy", a tplinkrouterc6u class name, or empty = auto-detect
        self.timeout = int(os.environ.get("TPLINK_TIMEOUT", "20"))


class Router:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self._lock = threading.Lock()
        self._client = None

    def _make_client(self):
        c = self.config
        if not c.password:
            raise RuntimeError("TPLINK_PASSWORD is not set")
        if c.client and c.client.lower() != "legacy":
            cls = getattr(tplinkrouterc6u, c.client, None)
            if cls is None:
                raise RuntimeError(f"unknown TPLINK_CLIENT {c.client!r}")
            return cls(c.host, c.password, c.username, timeout=c.timeout)
        if c.client.lower() == "legacy" or (not c.client and LegacyCgiClient.detect(c.host, c.timeout)):
            return LegacyCgiClient(c.host, c.password, c.username, timeout=c.timeout)
        return TplinkRouterProvider.get_client(c.host, c.password, c.username, timeout=c.timeout)

    def call(self, fn, *, retry: bool = True):
        """Run fn(client) logged in. Retry authentication and eligible reads once."""
        with self._lock:
            for attempt in (1, 2):
                dispatched = False
                try:
                    if self._client is None:
                        self._client = self._make_client()
                    self._client.authorize()
                    dispatched = True
                    return fn(self._client)
                except Exception:
                    log.debug("router call failed (attempt %d)", attempt, exc_info=True)
                    self._client = None
                    if attempt == 2 or (dispatched and not retry):
                        raise

    @property
    def client_name(self) -> str:
        return type(self._client).__name__ if self._client else ""


def plain(obj):
    """Library dataclasses -> JSON-friendly dicts; private '_x' fields come out through their public properties."""
    if isinstance(obj, (list, tuple)):
        return [plain(o) for o in obj]
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (IPv4Address, IPv6Address)):
        return str(obj)
    if is_dataclass(obj):
        out = {}
        for f in fields(obj):
            name = f.name.lstrip("_")
            value = getattr(obj, name, None) if f.name.startswith("_") else getattr(obj, f.name)
            if value is not None and value != []:
                out[name] = plain(value)
        return out
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)
