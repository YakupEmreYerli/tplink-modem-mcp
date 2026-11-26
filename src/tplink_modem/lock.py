"""Login lock: after the router refuses a login, that device is not tried again until its credentials change.

TP-Link locks the admin account after a few wrong attempts, and a timer that retries every minute would keep it
locked. The lock file holds a salted hash of host, username and password, never the password itself, so changing
any of them lifts the lock by itself.
"""
import hashlib
import hmac
import json
import os
import time

from . import history


class LoginLocked(RuntimeError):
    pass


def _path(name: str):
    return history.STATE / "locks" / f"{name}.json"


def _fingerprint(config, salt: bytes) -> str:
    secret = f"{config.host}\0{config.username}\0{config.password}".encode()
    return hashlib.pbkdf2_hmac("sha256", secret, salt, 100_000).hex()


def _locked(config) -> bool:
    path = _path(config.name)
    try:
        data = json.loads(path.read_text())
        same = hmac.compare_digest(_fingerprint(config, bytes.fromhex(data["salt"])), data["fingerprint"])
    except (OSError, ValueError, KeyError):
        return False
    if not same:
        path.unlink(missing_ok=True)  # credentials changed
    return same


def is_locked(config) -> bool:
    return bool(config.password) and _locked(config)


def check(config) -> None:
    if is_locked(config):
        raise LoginLocked(f"login to {config.host} failed earlier; not retrying until the password changes "
                          f"or you run 'tplink-modem unlock {config.name}'")


def set(config) -> None:
    path = _path(config.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    salt = os.urandom(16)
    data = {"time": int(time.time()), "host": config.host, "salt": salt.hex(),
            "fingerprint": _fingerprint(config, salt)}
    path.write_text(json.dumps(data))
    path.chmod(0o600)


def clear(name: str) -> bool:
    """True if the device was locked."""
    path = _path(name)
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed
