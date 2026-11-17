"""AST-isolated real HTTP routes: no application/DB/bootstrap imports."""
import ast
import hashlib
import os
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
from typing import Literal
ROOT=Path(__file__).resolve().parents[1]

def routes():
    source=ast.parse((ROOT/'app/routers/monitor.py').read_text())
    names={'agent_version','agent_release','AgentReleaseRead'}
    body=[n for n in source.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    ns={'__file__':str(ROOT/'app/routers/monitor.py'),'agent_router':APIRouter(prefix='/agent'),'HTTPException':HTTPException,'BaseModel':BaseModel,'ConfigDict':ConfigDict,'Literal':Literal}
    exec(compile(ast.Module(body=body,type_ignores=[]),'real-router-slice','exec'),ns)
    app=FastAPI();app.include_router(ns['agent_router'])
    return TestClient(app),ns

def test_exact_public_release_source_and_frozen_legacy_announcement():
    body=(ROOT/'agent/stella_agent.py').read_bytes()
    with patch.dict(os.environ,{'STELLA_AGENT_ROLLOUT_VERSION':'0.6.16'}):
        client,ns=routes()
        legacy=client.get('/agent/version');assert legacy.status_code==200
        assert legacy.json()=={'version':'0.6.16'}
        reply=client.get('/agent/release');assert reply.status_code==200
        assert reply.headers['cache-control']=='no-store'
        assert reply.json()=={'source_version':'0.6.21','source_sha256':hashlib.sha256(body).hexdigest(),'source_size':len(body),'announcement_version':'0.6.16','rollout_policy':'pinned'}
        # Old check_update exits on version equality before reading manifest/hash or requesting source.
        updater=ast.parse((ROOT/'agent/stella_agent.py').read_text())
        method=next(n for c in updater.body if isinstance(c,ast.ClassDef) for n in c.body if isinstance(n,ast.FunctionDef) and n.name=='check_update')
        text=ast.get_source_segment((ROOT/'agent/stella_agent.py').read_text(),method)
        assert 'version' in text
        assert ns['agent_version']()=={'version':'0.6.16'}
        import importlib.util
        spec=importlib.util.spec_from_file_location('v8_compat_agent',ROOT/'agent/stella_agent.py')
        agent=importlib.util.module_from_spec(spec);spec.loader.exec_module(agent)
        for actual in ('0.6.16','0.6.18','0.6.19','0.6.20'):
            with patch.object(agent,'AGENT_VERSION',actual):
                instance=agent.Agent('https://offline.invalid','synthetic-not-a-token')
                with patch.object(instance,'_get',return_value=legacy.json()),patch.object(instance,'_download_and_restart') as update:
                    instance.check_update();update.assert_not_called()
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ns['AgentReleaseRead'].model_validate({**reply.json(),'token':'must-not-be-accepted'})

def test_unpinned_release_is_exact_and_invalid_pin_is_fail_closed():
    with patch.dict(os.environ,{'STELLA_AGENT_ROLLOUT_VERSION':'0.6.21'}):
        client,_=routes();assert client.get('/agent/release').json()['rollout_policy']=='source'
    with patch.dict(os.environ,{'STELLA_AGENT_ROLLOUT_VERSION':'0.6.20'}):
        client,_=routes();assert client.get('/agent/version').json()=={'version':'0.6.20'}
    with patch.dict(os.environ,{'STELLA_AGENT_ROLLOUT_VERSION':'latest'}):
        client,_=routes();assert client.get('/agent/release').status_code==503
