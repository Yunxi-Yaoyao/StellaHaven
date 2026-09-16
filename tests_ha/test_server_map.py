"""World map tests: pure assembly + mocked persistence; never open a DB."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import importlib
import pytest

NOW = datetime(2026, 9, 16, 8, tzinfo=timezone.utc)


def node(id=1, **kwargs):
    return SimpleNamespace(**(dict(id=id, name=f"Tokyo-{id}", status="online",
        last_seen_at=NOW, net_type="public", public_ip=None,
        public_ip_source=None, region="Tokyo") | kwargs))


def svc():
    try:
        return importlib.import_module("app.services.server_map")
    except ModuleNotFoundError:
        pytest.fail("server map service is not implemented")


def test_old_agent_is_unknown_without_city_guessing():
    result = svc().build_topology([node()], {}, {}, now=NOW)
    assert result["nodes"][0]["location_source"] == "unknown"
    assert result["nodes"][0]["latitude"] is None
    assert result["nodes"][0]["longitude"] is None
    assert result["links"] == []
    assert result["stats"] == {"located": 0, "unknown": 1, "links": 0}


def snapshot(**location):
    return dict(observed_at=NOW.isoformat(), location=dict(status="located", source="nat",
        public_ip="8.8.8.8", label="Test city", latitude=35.0, longitude=139.0,
        reason=None) | location, wireguard=dict(status="ok", interfaces=[]))


def test_location_is_explicit_and_manual_wins():
    s = svc()
    auto = s.build_topology([node()], {1: snapshot()}, {}, now=NOW)["nodes"][0]
    assert (auto["latitude"], auto["location_source"]) == (35.0, "nat")
    internal = s.build_topology([node(net_type="internal")], {1: snapshot()}, {}, now=NOW)["nodes"][0]
    assert (internal["latitude"], internal["location_source"]) == (35.0, "nat")
    manual = s.build_topology([node(net_type="internal")], {1: snapshot()},
        {1: dict(latitude=0.0, longitude=0.0, label="Real origin")}, now=NOW)["nodes"][0]
    assert (manual["latitude"], manual["longitude"], manual["location_source"]) == (0, 0, "manual")


@pytest.mark.parametrize("change", [dict(public_ip="10.0.0.1"), dict(latitude=float("nan")),
    dict(longitude=181), dict(latitude=None), dict(status="unknown", source="unknown")])
def test_invalid_or_unknown_auto_location_never_gets_coordinates(change):
    result = svc().build_topology([node()], {1: snapshot(**change)}, {}, now=NOW)
    assert result["nodes"][0]["latitude"] is None


def test_manual_public_ip_mismatch_requires_manual_city():
    result = svc().build_topology([node(public_ip="1.1.1.1", public_ip_source="manual")],
        {1: snapshot()}, {}, now=NOW)["nodes"][0]
    assert result["latitude"] is None
    assert result["public_ip"] == "1.1.1.1"
    assert result["location_reason"] == "manual_ip_requires_location"


def test_snapshot_and_manual_validation_are_bounded():
    from app.schemas.monitor import AgentReport
    from pydantic import ValidationError
    assert "map_snapshot" in AgentReport.model_fields
    assert AgentReport(map_snapshot=snapshot()).map_snapshot["location"]["public_ip"] == "8.8.8.8"
    for bad in [snapshot(latitude=float("nan")), snapshot(longitude=181),
                snapshot(label="x" * 300), snapshot() | {"private_key": "secret"}]:
        with pytest.raises(ValidationError):
            AgentReport(map_snapshot=bad)
    for bad in [dict(latitude=1, longitude=None), dict(latitude=float("nan"), longitude=1),
                dict(latitude=True, longitude=1), dict(latitude=91, longitude=1)]:
        with pytest.raises(ValidationError):
            svc().MapLocationUpdate(**bad)
    assert svc().MapLocationUpdate(latitude=None, longitude=None, label=None).latitude is None


def wg_snapshot(key, peer_key, *, iface="wg0", handshake=None):
    s = snapshot()
    s["wireguard"]["interfaces"] = [dict(name=iface, public_key_id=key * 64,
        addresses=["10.0.0.1/24"], peers=[dict(public_key_id=peer_key * 64,
        endpoint="1.1.1.1:51820", allowed_ips=["10.0.0.0/24"],
        latest_handshake_at=int(NOW.timestamp()) - 30 if handshake is None else handshake,
        rx_bytes=100, tx_bytes=200)])]
    return s


def test_exact_key_matching_and_bidirectional_tunnel_dedup():
    a, b = wg_snapshot("a", "b"), wg_snapshot("b", "a")
    links = svc().build_topology([node(), node(2)], {1: a, 2: b}, {}, now=NOW)["links"]
    assert len(links) == 1
    assert (links[0]["source"], links[0]["target"], links[0]["state"]) == (1, 2, "recent")
    a["wireguard"]["interfaces"] += wg_snapshot("c", "d", iface="wg1")["wireguard"]["interfaces"]
    b["wireguard"]["interfaces"] += wg_snapshot("d", "c", iface="wg1")["wireguard"]["interfaces"]
    assert len(svc().build_topology([node(), node(2)], {1: a, 2: b}, {}, now=NOW)["links"]) == 2


def test_unknown_and_ambiguous_peers_are_not_guessed_from_endpoint():
    s = svc()
    a, b = wg_snapshot("a", "b"), wg_snapshot("b", "a")
    unknown = s.build_topology([node(), node(2, public_ip="1.1.1.1")], {1: a}, {}, now=NOW)["links"][0]
    assert unknown["target"] is None
    assert unknown["reason"] == "unmatched_peer"
    ambiguous = s.build_topology([node(), node(2), node(3)], {1: a, 2: b, 3: b}, {}, now=NOW)["links"]
    assert next(x for x in ambiguous if x["source"] == 1)["target"] is None
    assert next(x for x in ambiguous if x["source"] == 1)["reason"] == "ambiguous_peer_key"


@pytest.mark.parametrize("age,state", [(0, "never"), (30, "recent"), (180, "recent"), (181, "stale"), (-5, "unknown")])
def test_handshake_state(age, state):
    handshake = 0 if age == 0 else int(NOW.timestamp()) - age
    result = svc().build_topology([node()], {1: wg_snapshot("a", "b", handshake=handshake)}, {}, now=NOW)
    assert result["links"][0]["state"] == state


@pytest.mark.parametrize("offline,expired", [(True, False), (False, True)])
def test_expired_or_offline_report_never_claims_recent(offline, expired):
    a = wg_snapshot("a", "b")
    if expired:
        a["observed_at"] = (NOW - timedelta(seconds=181)).isoformat()
    result = svc().build_topology([node(status="offline" if offline else "online")], {1: a}, {}, now=NOW)
    assert result["links"][0]["state"] == "unknown"


def test_target_offline_downgrades_link_even_if_source_is_fresh():
    result = svc().build_topology([node(), node(2, status="offline")],
        {1: wg_snapshot("a", "b"), 2: wg_snapshot("b", "a")}, {}, now=NOW)
    assert result["links"][0]["state"] == "unknown"
