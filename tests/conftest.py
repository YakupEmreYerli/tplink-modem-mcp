import pytest


@pytest.fixture(autouse=True)
def no_real_config(tmp_path, monkeypatch):
    """Never read the developer's own devices.toml."""
    monkeypatch.setenv("TPLINK_CONFIG", str(tmp_path / "no-devices.toml"))
