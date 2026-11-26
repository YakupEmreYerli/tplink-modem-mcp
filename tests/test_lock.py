"""Login lock: an authentication failure locks the device; timeouts and unreachable hosts do not."""
import pytest
import requests
from tplinkrouterc6u.common.exception import AuthorizeError, ClientException

from tplink_modem import history, lock
from tplink_modem.router import Config, LoginFailed, Router


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "STATE", tmp_path)
    return tmp_path


class FakeClient:
    """authorize() raises what the test says; counts how often the router was asked to log in."""
    def __init__(self, error=None):
        self.error, self.logins = error, 0

    def authorize(self):
        self.logins += 1
        if self.error:
            raise self.error


def router(error=None, password="pw", name="home"):
    r = Router(Config(name=name, host="192.168.1.1", username="admin", password=password))
    client = FakeClient(error)
    r._make_client = lambda: client
    return r, client


def test_auth_failure_locks_and_tries_login_once():
    r, client = router(AuthorizeError("login refused (71233: wrong username or password)"))
    with pytest.raises(LoginFailed, match="unlock home"):
        r.call(lambda c: 1)
    assert client.logins == 1  # no second attempt: a retry would count as another failed login
    assert lock.is_locked(r.config)


def test_locked_device_is_not_tried_again():
    r, client = router(AuthorizeError("login refused (71233: x)"))
    with pytest.raises(LoginFailed):
        r.call(lambda c: 1)
    r2, client2 = router()
    with pytest.raises(lock.LoginLocked) as e:
        r2.call(lambda c: 1)
    assert client2.logins == 0
    assert str(e.value) == ("login to http://192.168.1.1 failed earlier; not retrying until the password changes "
                            "or you run 'tplink-modem unlock home'")


def test_library_wrong_password_is_auth_failure():
    r, _ = router(ClientException("TplinkRouter - Archer - Cannot authorize! Error - 'stok'; Response - {}"))
    with pytest.raises(LoginFailed):
        r.call(lambda c: 1)


@pytest.mark.parametrize("error", [
    requests.ConnectTimeout("timed out"),
    requests.ConnectionError("unreachable"),
    TimeoutError(),
    ClientException("could not read keys"),
])
def test_network_trouble_does_not_lock(error):
    r, client = router(error)
    with pytest.raises(Exception) as e:
        r.call(lambda c: 1)
    assert not isinstance(e.value, LoginFailed)
    assert not lock.is_locked(r.config)
    assert client.logins == 2  # the normal one retry still applies


def test_wrapped_connection_error_does_not_lock():
    try:
        try:
            raise requests.ConnectionError("down")
        except requests.ConnectionError as inner:
            raise AuthorizeError(str(inner)) from inner
    except AuthorizeError as err:
        error = err
    r, _ = router(error)
    with pytest.raises(AuthorizeError):
        r.call(lambda c: 1)
    assert not lock.is_locked(r.config)


def test_error_inside_the_call_does_not_lock():
    r, _ = router()
    def boom(c):
        raise ClientException("Cannot authorize! later")
    with pytest.raises(ClientException):
        r.call(boom)
    assert not lock.is_locked(r.config)


def test_new_password_clears_lock():
    r, _ = router(AuthorizeError("login refused"))
    with pytest.raises(LoginFailed):
        r.call(lambda c: 1)
    r2, client2 = router(password="new-pw")
    assert r2.call(lambda c: 7) == 7
    assert client2.logins == 1 and not lock.is_locked(r2.config)


def test_unlock():
    r, _ = router(AuthorizeError("login refused"))
    with pytest.raises(LoginFailed):
        r.call(lambda c: 1)
    assert lock.clear("home") is True
    assert lock.clear("home") is False
    assert not lock.is_locked(r.config)


def test_lock_file_never_holds_the_password(state):
    r, _ = router(AuthorizeError("login refused"), password="hunter2-secret")
    with pytest.raises(LoginFailed):
        r.call(lambda c: 1)
    files = list(state.rglob("*"))
    assert any(f.is_file() for f in files)
    assert all("hunter2-secret" not in f.read_text() for f in files if f.is_file())


def test_locks_are_per_device():
    r, _ = router(AuthorizeError("login refused"), name="a")
    with pytest.raises(LoginFailed):
        r.call(lambda c: 1)
    other, client = router(name="b")
    assert other.call(lambda c: 3) == 3


def test_legacy_client_reports_refusal_as_auth_failure():
    from tplink_modem.legacy import LoginRefused
    assert issubclass(LoginRefused, AuthorizeError)


def test_non_json_answer_does_not_lock():
    """The library says 'Cannot authorize' for any bad login answer; an empty or HTML page is not a refusal."""
    try:
        try:
            import json
            json.loads("")
        except ValueError as inner:
            raise ClientException("TplinkRouter - Cannot authorize! Error - Expecting value; Response - ")
    except ClientException as err:
        error = err
    r, _ = router(error)
    with pytest.raises(ClientException):
        r.call(lambda c: 1)
    assert not lock.is_locked(r.config)


def test_wrong_password_answer_still_locks():
    """A JSON answer without a session token (KeyError) is the router refusing the login."""
    try:
        try:
            {}["stok"]
        except KeyError:
            raise ClientException("TplinkRouter - Cannot authorize! Error - 'stok'; Response - {'success': False}")
    except ClientException as err:
        error = err
    r, _ = router(error)
    with pytest.raises(LoginFailed):
        r.call(lambda c: 1)
