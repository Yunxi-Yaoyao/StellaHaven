"""Release repair: real route bodies, no application/DB bootstrap."""
import ast
import hashlib
from pathlib import Path
from typing import Any, Literal

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[1]


def actual_source_version():
    source = ast.parse((ROOT / 'agent/stella_agent.py').read_bytes())
    version = next(ast.literal_eval(node.value) for node in source.body
                   if isinstance(node, ast.Assign) and any(
                       isinstance(target, ast.Name) and target.id == 'AGENT_VERSION'
                       for target in node.targets))
    assert version in {'0.6.18', '0.6.19', '0.6.20', '0.6.21'}, 'source version outside this approved rollout transition'
    return version


def release_app(source_root=None):
    tree = ast.parse((ROOT / 'app/routers/monitor.py').read_bytes())
    names = {'agent_version', 'agent_script', 'agent_release', 'AgentReleaseRead'}
    selected: list[ast.stmt] = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    for node in selected:
        assert isinstance(node, (ast.FunctionDef, ast.ClassDef))
        node.decorator_list = []
    ns: dict[str, Any] = dict(__file__=str((source_root or ROOT) / 'app/routers/monitor.py'), HTTPException=HTTPException,
              BaseModel=BaseModel, ConfigDict=ConfigDict, Literal=Literal)
    exec(compile(ast.Module(body=selected, type_ignores=[]), '<real-agent-routes>', 'exec'), ns)
    app = FastAPI()
    for suffix in ('version', 'script', 'release'):
        app.get('/agent/' + suffix)(ns['agent_' + suffix])
    return app


def test_production_15_pin_is_parked_without_forged_manifest(monkeypatch):
    monkeypatch.setenv('STELLA_AGENT_ROLLOUT_VERSION', '0.6.15')
    with TestClient(release_app()) as client:
        response = client.get('/agent/version')
        assert response.status_code == 200, response.text
        assert response.json() == {'version': '0.6.15'}
        body = client.get('/agent/script').content
        release = client.get('/agent/release')
        assert release.status_code == 200, release.text
        assert release.headers['cache-control'] == 'no-store'
        assert release.json() == dict(source_version=actual_source_version(), source_sha256=hashlib.sha256(body).hexdigest(),
                                      source_size=len(body), announcement_version='0.6.15', rollout_policy='pinned')


@pytest.mark.parametrize('pin', ['0.6.12', '0.6.14', '0.6.19', '0.6.015', '0.6.15 ', 'latest', ''])
def test_unsupported_or_malformed_pins_still_fail_closed(monkeypatch, tmp_path, pin):
    # Preserve the original .18 rejection oracle even after the Agent lane
    # merges .19: .19 is unsupported only while .18 is the served source.
    (tmp_path / 'app/routers').mkdir(parents=True)
    (tmp_path / 'agent').mkdir()
    (tmp_path / 'agent/stella_agent.py').write_bytes(b'AGENT_VERSION = "0.6.18"\n')
    monkeypatch.setenv('STELLA_AGENT_ROLLOUT_VERSION', pin)
    with TestClient(release_app(tmp_path)) as client:
        assert client.get('/agent/version').status_code == 503
        assert client.get('/agent/release').status_code == 503


def test_candidate_20_keeps_19_18_15_pins_and_exact_source(monkeypatch):
    body = (ROOT / 'agent/stella_agent.py').read_bytes()
    with TestClient(release_app()) as client:
        assert client.get('/agent/script').content == body
        for pin in ('0.6.19', '0.6.18', '0.6.15'):
            monkeypatch.setenv('STELLA_AGENT_ROLLOUT_VERSION', pin)
            response = client.get('/agent/version')
            assert response.status_code == 200, response.text
            assert response.json() == {'version': pin}
            assert client.get('/agent/release').json() == dict(source_version='0.6.21', source_sha256=hashlib.sha256(body).hexdigest(), source_size=len(body), announcement_version=pin, rollout_policy='pinned')
        monkeypatch.setenv('STELLA_AGENT_ROLLOUT_VERSION', '0.6.20')
        assert client.get('/agent/version').json() == {'version': '0.6.20'}
        monkeypatch.setenv('STELLA_AGENT_ROLLOUT_VERSION', '0.6.21')
        assert client.get('/agent/version').json() == dict(version='0.6.21', sha256=hashlib.sha256(body).hexdigest(), size=len(body))
        monkeypatch.setenv('STELLA_AGENT_ROLLOUT_VERSION', '0.6.22')
        assert client.get('/agent/version').status_code == 503
        assert client.get('/agent/release').status_code == 503


def test_source_announcement_is_exact_actual_18_artifact(monkeypatch):
    # Historical nodeID retained; exact served bytes are authoritative for
    # both approved transition versions, independently parsed through AST.
    monkeypatch.delenv('STELLA_AGENT_ROLLOUT_VERSION', raising=False)
    with TestClient(release_app()) as client:
        body = client.get('/agent/script').content
        assert body == (ROOT / 'agent/stella_agent.py').read_bytes()
        assert client.get('/agent/version').json() == dict(version=actual_source_version(), sha256=hashlib.sha256(body).hexdigest(), size=len(body))


def test_candidate_19_preserves_explicit_18_pin_and_15_fleet_hold(monkeypatch, tmp_path):
    """Synthetic served bytes exercise actual center version selection only."""
    (tmp_path / 'app/routers').mkdir(parents=True)
    (tmp_path / 'agent').mkdir()
    body = b'AGENT_VERSION = "0.6.19"\nclass Agent: pass\ndef main(): pass\n'
    (tmp_path / 'agent/stella_agent.py').write_bytes(body)
    with TestClient(release_app(tmp_path)) as client:
        for pin in ('0.6.18', '0.6.15'):
            monkeypatch.setenv('STELLA_AGENT_ROLLOUT_VERSION', pin)
            response = client.get('/agent/version')
            assert response.status_code == 200, response.text
            assert response.json() == {'version':pin}
            assert client.get('/agent/release').json() == dict(source_version='0.6.19',source_sha256=hashlib.sha256(body).hexdigest(),source_size=len(body),announcement_version=pin,rollout_policy='pinned')
        monkeypatch.setenv('STELLA_AGENT_ROLLOUT_VERSION','0.6.20')
        assert client.get('/agent/version').status_code == 503
        monkeypatch.setenv('STELLA_AGENT_ROLLOUT_VERSION','0.6.19')
        assert client.get('/agent/version').json() == dict(version='0.6.19',sha256=hashlib.sha256(body).hexdigest(),size=len(body))


def test_historical_allowlist_never_advertises_newer_than_served_source(monkeypatch, tmp_path):
    (tmp_path / 'app/routers').mkdir(parents=True)
    (tmp_path / 'agent').mkdir()
    (tmp_path / 'agent/stella_agent.py').write_bytes(b'AGENT_VERSION = "0.6.17"\n')
    monkeypatch.setenv('STELLA_AGENT_ROLLOUT_VERSION','0.6.18')
    with TestClient(release_app(tmp_path)) as client:
        assert client.get('/agent/version').status_code == 503
        assert client.get('/agent/release').status_code == 503
