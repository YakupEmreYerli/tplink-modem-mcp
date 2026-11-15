from tplink_modem_mcp.history import History


def dev(mac, ip, name="phone"):
    return {"mac": mac, "ip": ip, "hostname": name, "connection": "2.4G"}


def test_first_sample_records_no_events(tmp_path):
    h = History(tmp_path / "presence.jsonl")
    assert h.sample([dev("aa:bb:cc:00:00:01", "192.168.1.10")]) == []
    assert h.query() == []


def test_join_leave_and_ip_change(tmp_path):
    h = History(tmp_path / "presence.jsonl")
    h.sample([dev("aa:bb:cc:00:00:01", "192.168.1.10"), dev("aa:bb:cc:00:00:02", "192.168.1.11", "tv")])
    events = h.sample([dev("aa:bb:cc:00:00:01", "192.168.1.20"), dev("aa:bb:cc:00:00:03", "192.168.1.12", "laptop")])
    kinds = sorted((e["event"], e["mac"][-1]) for e in events)
    assert kinds == [("ip_change", "1"), ("join", "3"), ("leave", "2")]
    assert len(h.query()) == 3


def test_one_shot_runs_compare_with_previous_snapshot(tmp_path):
    path = tmp_path / "presence.jsonl"
    History(path).sample([dev("aa:bb:cc:00:00:01", "192.168.1.10")])
    events = History(path).sample([])  # a new process, as from a timer
    assert [e["event"] for e in events] == ["leave"]


def test_query_filters_by_mac_in_any_notation(tmp_path):
    h = History(tmp_path / "presence.jsonl")
    h.sample([])
    h.sample([dev("aa:bb:cc:00:00:01", "192.168.1.10"), dev("aa:bb:cc:00:00:02", "192.168.1.11")])
    assert [e["mac"] for e in h.query(mac="AA-BB-CC-00-00-02")] == ["aa:bb:cc:00:00:02"]
