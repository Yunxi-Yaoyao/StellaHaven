"""Admission must reject missing prerequisites, never silently skip or spawn Docker."""
import json
import os
from pathlib import Path
import pytest
from tests_website_settings.save_owned_pg import admitted_database


def test_missing_owned_pg_receipt_fails_before_connection(monkeypatch):
    monkeypatch.delenv('STELLA_CI_NONCE_PG',raising=False)
    monkeypatch.delenv('STELLA_SAVE_PG_RECEIPT',raising=False)
    with pytest.raises(KeyError): admitted_database()


@pytest.mark.parametrize('fault',['permissions','nonce','parent','database','role','port','system','symlink'])
def test_foreign_owned_pg_receipt_fails_before_connection(tmp_path,monkeypatch,fault):
    monkeypatch.delenv('STELLA_CI_NONCE_PG',raising=False)
    root=tmp_path/'private';root.mkdir(mode=0o700)
    path=root/'owner.json';nonce='a'*32
    data=dict(nonce=nonce,pid=os.getppid(),port=39001,database='save_'+nonce,role='save_'+nonce,system='123456789',password='synthetic-never-connect')
    if fault=='nonce':data['nonce']='b'*32
    elif fault=='parent':data['pid']+=1
    elif fault=='database':data['database']='stella'
    elif fault=='role':data['role']='stalla'
    elif fault=='port':data['port']=5432
    elif fault=='system':data['system']='foreign'
    path.write_text(json.dumps(data));path.chmod(0o600)
    if fault=='permissions':path.chmod(0o644)
    if fault=='symlink':
        linked=root/'linked.json';linked.symlink_to(path);path=linked
    monkeypatch.setenv('TMPDIR',str(root));monkeypatch.setenv('STELLA_SAVE_PG_RECEIPT',str(path));monkeypatch.setenv('STELLA_SAVE_PG_NONCE',nonce)
    with pytest.raises(ValueError): admitted_database()
