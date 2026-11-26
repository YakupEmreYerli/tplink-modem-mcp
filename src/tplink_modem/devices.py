"""Named devices from an optional devices.toml; without the file there is one device from the environment.

    [[device]]
    name = "upstairs"
    host = "192.168.1.1"
    username = "admin"        # optional, default admin
    client = "legacy"         # optional: "legacy" or a tplinkrouterc6u class name; default = auto-detect
    default = true            # optional: the device used when none is named

Passwords are never in the file: TPLINK_PASSWORD_<NAME> (name in capitals, '-' as '_'); the default device also
accepts plain TPLINK_PASSWORD.
"""
import os
import re
import tomllib
from pathlib import Path

from . import history
from .history import History
from .router import Config, Router

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_KEYS = {"name", "host", "username", "client", "default"}


def config_path() -> Path:
    if os.environ.get("TPLINK_CONFIG"):
        return Path(os.environ["TPLINK_CONFIG"])
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tplink-modem" / "devices.toml"


class Devices:
    def __init__(self, path: Path | None = None):
        self._path = path
        self._loaded = False  # read on first use, so a bad file is a normal error, not an import crash
        self._entries: dict[str, dict] = {}
        self._routers: dict[str, Router] = {}
        self._histories: dict[str, History] = {}
        self._use = None

    def _ensure(self) -> None:
        if not self._loaded:
            path = self._path or config_path()
            if path.is_file():
                self._load(path)
            self._loaded = True

    @property
    def default(self) -> str:
        self._ensure()
        return next((n for n, e in self._entries.items() if e.get("default")), None) \
            or next(iter(self._entries), "default")

    def _load(self, path: Path) -> None:
        try:
            rows = tomllib.loads(path.read_text()).get("device", [])
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"{path}: {e}") from e
        for row in rows:
            name = str(row.get("name", ""))
            if not _NAME.match(name):
                raise ValueError(f"{path}: bad device name {name!r} (letters, digits, '-' and '_')")
            if name in self._entries:
                raise ValueError(f"{path}: device {name!r} listed twice")
            if "password" in row:
                raise ValueError(f"{path}: device {name!r}: passwords do not belong in this file; "
                                 f"set TPLINK_PASSWORD_{self._env(name)}")
            extra = set(row) - _KEYS
            if extra:
                raise ValueError(f"{path}: device {name!r}: unknown key {sorted(extra)[0]!r}")
            if "host" not in row:
                raise ValueError(f"{path}: device {name!r} has no host")
            self._entries[name] = row
        if sum(1 for e in self._entries.values() if e.get("default")) > 1:
            raise ValueError(f"{path}: more than one device is marked default")

    @staticmethod
    def _env(name: str) -> str:
        return name.upper().replace("-", "_")

    def names(self) -> list[str]:
        self._ensure()
        return list(self._entries) or ["default"]

    def resolve(self, device: str = "") -> str:
        name = device or self._use or self.default
        if name not in self.names():
            raise ValueError(f"unknown device {name!r}; known: {', '.join(self.names())}")
        return name

    def use(self, device: str) -> None:
        """Make this device the default for the rest of the process (the --device option)."""
        self._use = self.resolve(device)

    def config(self, device: str = "") -> Config:
        name = self.resolve(device)
        if not self._entries:
            return Config(name)
        e = self._entries[name]
        password = os.environ.get(f"TPLINK_PASSWORD_{self._env(name)}")
        if password is None:
            password = os.environ.get("TPLINK_PASSWORD", "") if name == self.default else ""
        return Config(name, host=e["host"], username=e.get("username", "admin"), password=password,
                      client=e.get("client", ""))

    def router(self, device: str = "") -> Router:
        name = self.resolve(device)
        if name not in self._routers:
            self._routers[name] = Router(self.config(name))
        return self._routers[name]

    def history(self, device: str = "") -> History:
        """The default device keeps the original presence.jsonl and last.json; the others get a folder each."""
        name = self.resolve(device)
        if name not in self._histories:
            path = None if name == self.default else history.STATE / "devices" / name / "presence.jsonl"
            self._histories[name] = History(path)
        return self._histories[name]
