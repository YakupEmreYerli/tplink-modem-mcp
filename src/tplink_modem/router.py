"""One shared, serialised connection to the router.

TP-Link firmwares allow a single admin session at a time, so every call goes through one lock and one client,
and a failed call logs in again once before giving up.
"""
import logging
import os
import threading
from dataclasses import fields, is_dataclass
from enum import Enum
from ipaddress import IPv4Address, IPv6Address

import requests
from tplinkrouterc6u import TplinkRouterProvider
import tplinkrouterc6u
from tplinkrouterc6u.common.exception import AuthorizeError, ClientException

from . import lock
from .legacy import LegacyCgiClient

log = logging.getLogger(__name__)


class LoginFailed(RuntimeError):
    """The router refused the login; the device is now locked."""


# AuthorizeError messages that are about the connection, not the credentials.
_NOT_CREDENTIALS = ("Cannot connect", "Session timed out", "Login timed out")


def is_auth_failure(e: Exception) -> bool:
    """True only when the router answered and refused the login. Timeouts, unreachable hosts and garbled
    answers are not: they must not lock the device."""
    cause = e
    while cause is not None:
        # An answer that is not JSON (empty page, wrong device at that address) is no credential refusal either.
        if isinstance(cause, (requests.RequestException, OSError, ValueError)):
            return False
        cause = cause.__cause__ or cause.__context__
    if isinstance(e, AuthorizeError):
        return not str(e).startswith(_NOT_CREDENTIALS)
    # tplinkrouterc6u clients (Archer, MR, ...) raise a plain ClientException once the login answer is wrong.
    return type(e) is ClientException and "Cannot authorize" in str(e)


class Config:
    def __init__(self, name: str = "default", host: str | None = None, username: str | None = None,
                 password: str | None = None, client: str | None = None):
        self.name = name
        self.host = (host or os.environ.get("TPLINK_HOST", "http://192.168.1.1")).rstrip("/")
        if "://" not in self.host:
            self.host = "http://" + self.host
        self.username = username or os.environ.get("TPLINK_USERNAME", "admin")
        self.password = os.environ.get("TPLINK_PASSWORD", "") if password is None else password
        # "legacy", a tplinkrouterc6u class name, or empty = auto-detect
        self.client = os.environ.get("TPLINK_CLIENT", "") if client is None else client
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

    def call(self, fn):
        """Run fn(client) logged in; on failure drop the session, log in again and retry once.

        A refused login is the exception: the device is locked and nothing tries again, because the router
        locks the admin account after a few wrong attempts."""
        with self._lock:
            lock.check(self.config)
            for attempt in (1, 2):
                try:
                    if self._client is None:
                        self._client = self._make_client()
                    try:
                        self._client.authorize()
                    except Exception as e:
                        if not is_auth_failure(e):
                            raise
                        left = lock.fail(self.config)
                        after = (f"{left} more failed {'try' if left == 1 else 'tries'} before it is locked"
                                 if left else f"not retrying until the password changes or you run "
                                              f"'tplink-modem unlock {self.config.name}'")
                        raise LoginFailed(f"login to {self.config.host} failed ({e}); {after}") from e
                    lock.reset(self.config)
                    return fn(self._client)
                except LoginFailed:
                    self._client = None
                    raise
                except Exception:
                    log.debug("router call failed (attempt %d)", attempt, exc_info=True)
                    self._client = None
                    if attempt == 2:
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
