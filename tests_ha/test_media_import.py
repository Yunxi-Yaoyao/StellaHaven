import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

def test_import_inventory_preserves_existing_derivative_urls(tmp_path):
    script=Path(__file__).parents[1]/'scripts/import_media_objects.py'
    spec=importlib.util.spec_from_file_location('media_import',script);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    d=tmp_path/'assets/homebg';d.mkdir(parents=True)
    (d/'x.mp4').write_bytes(b'video');(d/'x-poster.jpg').write_bytes(b'poster')
    (d/'index.json').write_text(json.dumps([{'id':'keep-id','file':'x.mp4','owner':'synthetic'}]))
    (d/'.x.mp4.media.json').write_text(json.dumps({'url':'/assets/homebg/x.mp4','poster':'/assets/homebg/x-poster.jpg','variants':{'original':'/assets/homebg/x.mp4'}}))
    class DB:
        def execute(self,*args):return SimpleNamespace(scalars=lambda:[])
    objects,entries=m.inventory(DB(),tmp_path)
    assert set(objects)=={'homebg/x.mp4','homebg/x-poster.jpg'}
    assert entries[0]['id']=='keep-id'
    assert entries[0]['media']['poster']=='/assets/homebg/x-poster.jpg'
