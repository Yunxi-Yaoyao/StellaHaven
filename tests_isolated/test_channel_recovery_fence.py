"""Late authenticated success belongs to the whole observed policy and origin."""
import json
import threading
import pytest
from test_agent_channels import obj,policy


@pytest.mark.parametrize('change',['revision','nonce','epoch','mode','selected_entry_id','entries','origin'])
def test_stale_auto_success_cannot_clear_new_failure_or_write_cache(tmp_path,change):
    a=obj();a._channel_cache_path=lambda:tmp_path/'fenced.json'
    cfg=policy(['https://installed.test','https://other.test'],'auto')
    a._channel_probe=lambda *args:dict(ok=False,duration_ms=1)
    a._channel_apply(cfg)
    entered,release=threading.Event(),threading.Event()
    errors=[]
    def probe(origin,observed):
        if threading.current_thread() is worker:
            entered.set();assert release.wait(3)
            return dict(ok=origin=='https://installed.test',duration_ms=1)
        return dict(ok=False,duration_ms=1)
    a._channel_probe=probe
    def tick():
        try:a._channel_tick(now=a._channel_switched_at+61)
        except BaseException as exc:errors.append(exc)
    worker=threading.Thread(target=tick);worker.start();assert entered.wait(1)
    try:
        new=json.loads(json.dumps(cfg))
        if change=='origin':
            with a._channel_lock:a.url='https://other.test';a._channel_save()
        else:
            if change=='revision':new['revision']=2
            elif change=='nonce':new['nonce']='d'*64
            elif change=='epoch':new['epoch']='new-epoch'
            elif change=='mode':new['mode']='fixed'
            elif change=='selected_entry_id':new['selected_entry_id']='private'
            elif change=='entries':new['entries'][1]['origin']='https://new.test'
            a._channel_apply(new)
        frozen=a._channel_cache_path().read_bytes()
    finally:release.set();worker.join(3)
    assert not worker.is_alive() and not errors
    assert a._channel_policy==new and a._channel_state=='failed'
    assert a._channel_error=='probe_failed' and a._channel_samples=={}
    assert a.url==('https://other.test' if change=='origin' else 'https://installed.test')
    assert a._channel_cache_path().read_bytes()==frozen
