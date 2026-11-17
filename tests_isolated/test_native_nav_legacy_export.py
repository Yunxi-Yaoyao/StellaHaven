"""Offline extraction oracle, including real legacy singular table names."""
import importlib.util
import json
import sqlite3
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]

def exporter():
    spec=importlib.util.spec_from_file_location('nav_legacy_export',ROOT/'tools/native_nav_legacy_export.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

@pytest.fixture
def legacy(tmp_path):
    db=tmp_path/'database.db'
    with sqlite3.connect(db) as c:
        c.executescript('''CREATE TABLE item_icon_group(id,user_id,title,description,icon,sort,style_json,deleted_at);
CREATE TABLE item_icon(id,user_id,item_icon_group_id,title,url,lan_url,description,icon_json,open_method,sort,deleted_at);
CREATE TABLE user_config(user_id,panel_json,search_engine_json);
CREATE TABLE file(id,user_id,src,file_name,purpose,deleted_at);
CREATE TABLE nav_auth_sessions(secret); INSERT INTO nav_auth_sessions VALUES ('DO-NOT-EXPORT');
INSERT INTO item_icon_group VALUES (1,1,'group','desc','star',0,'{"hideTitle":false}',NULL);
INSERT INTO item_icon_group VALUES (2,2,'PRIVATE','','',0,NULL,NULL);
INSERT INTO item_icon VALUES (1,1,1,'card','https://example.test','','','{"itemType":1,"text":"A","src":""}',2,0,NULL);
INSERT INTO user_config VALUES (1,'{"clockShow":false}','{}');''')
    return db,tmp_path

def test_extract_read_only_owner_complete_fields_and_no_auth(legacy):
    db,root=legacy
    before=db.read_bytes()
    transfer,original=exporter().extract(db,root,1)
    assert db.read_bytes()==before
    assert transfer['userConfig']=={'panel':{'clockShow':False},'searchEngine':{}}
    group=transfer['list']['icons'][0]
    assert (group['sort'],group['description'],group['icon'],group['style']['hideTitle'])==(0,'desc','star',False)
    assert group['children'][0]['sort']==0
    assert 'PRIVATE' not in json.dumps(original) and 'DO-NOT-EXPORT' not in json.dumps(original)
    assert original['counts']=={'groups':1,'items':1,'assets':0}

def test_effective_defaults_materialized_without_overriding_explicit_false(legacy):
    db,root=legacy
    defaults={'panel':{'clockShow':True,'maxWidth':1200,'logoShow':True},'searchEngine':{'searchEngineList':[{'title':'Search','url':'https://example.test/?q=%s','iconSrc':''}],'currentSearchEngine':{'url':'https://example.test/?q=%s'},'newWindowOpen':False},'assets':[],'provenance':{'source_sha256':'synthetic'}}
    transfer,original=exporter().extract(db,root,1,defaults)
    assert transfer['userConfig']['panel']=={'clockShow':False,'maxWidth':1200,'logoShow':True}
    assert len(transfer['userConfig']['searchEngine']['searchEngineList'])==1
    assert original['user_configs'][0]['panel_json']=='{"clockShow":false}'
    assert original['effective_defaults']['provenance']==defaults['provenance']


def test_default_builder_refuses_unrecognized_source(tmp_path):
    spec=importlib.util.spec_from_file_location('defaults',ROOT/'tools/native_nav_legacy_defaults.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with pytest.raises(ValueError,match='source'):module.build(tmp_path)


def test_export_refuses_missing_owner_and_symlink_asset(legacy,tmp_path):
    db,root=legacy
    with pytest.raises(ValueError):exporter().extract(db,root,99)
    (root/'files').mkdir();(root/'outside.png').write_bytes(b'private')
    (root/'files'/'evil.png').symlink_to(root/'outside.png')
    with sqlite3.connect(db) as c:c.execute("INSERT INTO file VALUES (1,1,'./files/evil.png','evil.png','icon',NULL)")
    with pytest.raises((ValueError,OSError)):exporter().extract(db,root,1)
