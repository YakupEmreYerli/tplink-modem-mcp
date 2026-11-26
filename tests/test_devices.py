"""Named devices from devices.toml, passwords from the environment, per-device history."""
import pytest

from tplink_modem import history
from tplink_modem.devices import Devices

TOML = """
[[device]]
name = "upstairs"
host = "192.168.1.1"
username = "admin"

[[device]]
name = "garage-ap"
host = "http://192.168.0.5"
client = "legacy"
default = true
"""


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "STATE", tmp_path / "state")
    for k in ("TPLINK_HOST", "TPLINK_USERNAME", "TPLINK_PASSWORD", "TPLINK_CLIENT", "TPLINK_PASSWORD_UPSTAIRS",
              "TPLINK_PASSWORD_GARAGE_AP"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def conf(tmp_path, text=TOML):
    p = tmp_path / "devices.toml"
    p.write_text(text)
    d = Devices(p)
    d.names()  # the file is read on first use
    return d


def test_no_file_is_the_old_single_device(monkeypatch, tmp_path):
    monkeypatch.setenv("TPLINK_HOST", "10.0.0.1")
    monkeypatch.setenv("TPLINK_PASSWORD", "pw")
    d = Devices(tmp_path / "missing.toml")
    assert d.names() == ["default"] and d.default == "default"
    c = d.config("")
    assert (c.host, c.username, c.password) == ("http://10.0.0.1", "admin", "pw")
    assert d.history("").path == history.STATE / "presence.jsonl"


def test_file_lists_devices_and_default(tmp_path):
    d = conf(tmp_path)
    assert d.names() == ["upstairs", "garage-ap"]
    assert d.default == "garage-ap"
    assert d.config("").host == "http://192.168.0.5"
    assert d.config("garage-ap").client == "legacy"
    assert d.config("upstairs").host == "http://192.168.1.1"


def test_first_device_is_default_when_none_marked(tmp_path):
    d = conf(tmp_path, TOML.replace("default = true", ""))
    assert d.default == "upstairs"


def test_passwords_from_env_per_device(tmp_path, monkeypatch):
    monkeypatch.setenv("TPLINK_PASSWORD_UPSTAIRS", "one")
    monkeypatch.setenv("TPLINK_PASSWORD_GARAGE_AP", "two")
    monkeypatch.setenv("TPLINK_PASSWORD", "plain")
    d = conf(tmp_path)
    assert d.config("upstairs").password == "one"
    assert d.config("garage-ap").password == "two"


def test_plain_password_only_serves_the_default_device(tmp_path, monkeypatch):
    monkeypatch.setenv("TPLINK_PASSWORD", "plain")
    d = conf(tmp_path)
    assert d.config("garage-ap").password == "plain"
    assert d.config("upstairs").password == ""


def test_password_in_file_is_refused(tmp_path):
    with pytest.raises(ValueError, match="password"):
        conf(tmp_path, TOML + 'password = "x"\n')


def test_unknown_device_lists_known_names(tmp_path):
    with pytest.raises(ValueError, match="unknown device 'nope'.*upstairs, garage-ap"):
        conf(tmp_path).config("nope")


@pytest.mark.parametrize("bad", ['name = "../x"', 'name = ""'])
def test_bad_names_refused(tmp_path, bad):
    with pytest.raises(ValueError):
        conf(tmp_path, f'[[device]]\n{bad}\nhost = "h"\n')


def test_duplicate_and_double_default_refused(tmp_path):
    with pytest.raises(ValueError, match="twice"):
        conf(tmp_path, TOML.replace("garage-ap", "upstairs"))
    with pytest.raises(ValueError, match="default"):
        conf(tmp_path, TOML.replace('username = "admin"', "default = true"))


def test_history_default_keeps_old_files_others_get_own_folder(tmp_path):
    d = conf(tmp_path)
    assert d.history("").path == history.STATE / "presence.jsonl"
    assert d.history("garage-ap").path == history.STATE / "presence.jsonl"
    assert d.history("upstairs").path == history.STATE / "devices" / "upstairs" / "presence.jsonl"


def test_use_switches_default_for_this_process(tmp_path):
    d = conf(tmp_path)
    d.use("upstairs")
    assert d.config("").name == "upstairs"
    with pytest.raises(ValueError):
        d.use("nope")


@pytest.mark.parametrize("second", ["a_b", "A-B"])
def test_names_that_share_a_password_variable_are_refused(tmp_path, second):
    text = f'[[device]]\nname = "a-b"\nhost = "h"\n[[device]]\nname = "{second}"\nhost = "h2"\n'
    with pytest.raises(ValueError, match="TPLINK_PASSWORD_A_B"):
        conf(tmp_path, text)


def test_single_device_table_gives_clear_error(tmp_path):
    with pytest.raises(ValueError, match=r"\[\[device\]\]"):
        conf(tmp_path, '[device]\nname = "a"\nhost = "h"\n')
