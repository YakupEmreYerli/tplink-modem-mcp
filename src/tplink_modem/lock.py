"""Login lock: after three refused logins in a row, that device is not tried again until its credentials change.

TP-Link locks the admin account after a few wrong attempts, and a timer that retries every minute would keep it
locked. A single refusal can also be a session conflict (the router allows one admin session at a time), so only
consecutive refusals count and a working login resets the count. The state file holds a salted hash of host, username and password, never the password itself, so changing
any of them lifts the lock by itself.
"""
import hashlib
import hmac
import json
import os
import time

from . import history


MAX_FAILURES = 3


class LoginLocked(RuntimeError):
    pass


def _path(name: str):
    return history.STATE / "locks" / f"{name}.json"


def _fingerprint(config, salt: bytes) -> str:
    secret = f"{config.host}\0{config.username}\0{config.password}".encode()
    return hashlib.pbkdf2_hmac("sha256", secret, salt, 100_000).hex()


def _read(config) -> dict | None:
    """The failure record for these credentials; a record for other credentials is dropped."""
    path = _path(config.name)
    try:
        data = json.loads(path.read_text())
        same = hmac.compare_digest(_fingerprint(config, bytes.fromhex(data["salt"])), data["fingerprint"])
    except (OSError, ValueError, KeyError):
        return None
    if not same:
        path.unlink(missing_ok=True)  # credentials changed
        return None
    return data


def failures(config) -> int:
    data = _read(config) if config.password else None
    return data["failures"] if data else 0


def is_locked(config) -> bool:
    return failures(config) >= MAX_FAILURES


def check(config) -> None:
    if is_locked(config):
        raise LoginLocked(f"login to {config.host} failed earlier; not retrying until the password changes "
                          f"or you run 'tplink-modem unlock {config.name}'")


def _write(config, count: int) -> None:
    path = _path(config.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    salt = os.urandom(16)
    data = {"time": int(time.time()), "host": config.host, "failures": count, "salt": salt.hex(),
            "fingerprint": _fingerprint(config, salt)}
    path.write_text(json.dumps(data))
    path.chmod(0o600)


def fail(config) -> int:
    """Count one refused login; returns how many tries are left before the lock."""
    count = failures(config) + 1
    _write(config, count)
    return max(MAX_FAILURES - count, 0)


def set(config) -> None:
    _write(config, MAX_FAILURES)


def reset(config) -> None:
    """A login worked: the count starts again."""
    _path(config.name).unlink(missing_ok=True)


def clear(name: str) -> bool:
    """True if the device was locked."""
    path = _path(name)
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed
