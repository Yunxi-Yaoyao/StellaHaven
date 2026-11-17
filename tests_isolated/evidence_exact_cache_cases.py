"""Exact-byte memoization must never memoize successful evidence validation."""
import ast
import hashlib
import os
from copy import deepcopy

import pytest
from test_api_response_v11_integration import check_metadata


def record(body, symbol='sample.f'):
    return dict(file='sample.py', symbol=symbol, line=1, end_line=2,
                sha256=hashlib.sha256(body).hexdigest(),
                symbol_sha256=hashlib.sha256(body.rstrip(b'\n')).hexdigest())


def test_repeated_exact_body_parses_once_and_parser_identity_invalidates(monkeypatch):
    body=b'def f():\n    return 517\n'
    real=ast.parse;calls=[]
    def parser(*a, **kw):
        calls.append(a[0]);return real(*a, **kw)
    monkeypatch.setattr(ast,'parse',parser)
    source=record(body)
    check_metadata(source,body);check_metadata(source,body)
    assert len(calls)==1
    def missing(*a, **kw):return real('')
    monkeypatch.setattr(ast,'parse',missing)
    with pytest.raises(AssertionError):check_metadata(source,body)


def test_same_filename_size_and_mtime_changed_body_cannot_reuse_metadata(tmp_path,monkeypatch):
    import api_response_evidence_fixture as evidence
    body=b'def f():\n    return 517\n';changed=body.replace(b'f()',b'g()')
    path=tmp_path/'sample.py';path.write_bytes(body);stat=path.stat()
    monkeypatch.setattr(evidence,'ROOT',tmp_path)
    monkeypatch.setattr(evidence,'reviewed_body',lambda source:(tmp_path/source['file']).read_bytes())
    source=record(body);check_metadata(source)
    path.write_bytes(changed);os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
    with pytest.raises(AssertionError):check_metadata(source)
    bad=source|{'sha256':hashlib.sha256(changed).hexdigest(),
                'symbol_sha256':hashlib.sha256(changed.rstrip(b'\n')).hexdigest()}
    with pytest.raises(AssertionError):check_metadata(bad)
    path.unlink()
    with pytest.raises(FileNotFoundError):check_metadata(source)


def test_expected_metadata_is_not_validation_result_or_mutable_ast(monkeypatch):
    body=b'def f():\n    return 518\n';source=record(body)
    check_metadata(source,body)
    for field,value in [('line',2),('end_line',3),('symbol','sample.absent'),('symbol_sha256','0'*64)]:
        with pytest.raises(AssertionError):check_metadata(source|{field:value},body)
    captured=[];real=ast.parse
    def parser(*a,**kw):
        tree=real(*a,**kw);captured.append(tree);return tree
    monkeypatch.setattr(ast,'parse',parser)
    check_metadata(source,body)
    captured[0].body.clear()
    check_metadata(source,body)
    def canceled(*a,**kw):raise KeyboardInterrupt('synthetic cancellation')
    monkeypatch.setattr(ast,'parse',canceled)
    with pytest.raises(KeyboardInterrupt):check_metadata(source,body)
    monkeypatch.setattr(ast,'parse',parser)
    check_metadata(source,body)


def test_bounded_eviction_oversize_bypass_and_segmenter_identity(monkeypatch):
    import evidence_exact_cache as cache
    cache._cached_index.cache_clear();cache._cached_segment.cache_clear()
    for number in range(270):
        text=f'def f():\n    return {number}\n'
        coordinates=cache.symbol_range(text,['f'])
        cache.symbol_digest(text,coordinates)
    assert cache._cached_index.cache_info().currsize==8
    assert cache._cached_segment.cache_info().currsize==256
    text='def f():\n    return 999\n';coordinates=cache.symbol_range(text,['f'])
    before=cache.symbol_digest(text,coordinates)
    monkeypatch.setattr(ast,'get_source_segment',lambda *a:'changed segment')
    assert cache.symbol_digest(text,coordinates)!=before
    monkeypatch.setattr(cache,'MAX_TEXT',1)
    real=ast.parse;calls=[]
    def parser(*a,**kw):calls.append(True);return real(*a,**kw)
    monkeypatch.setattr(ast,'parse',parser)
    cache.symbol_range(text,['f']);cache.symbol_range(text,['f'])
    assert len(calls)==2


def test_exact_json_derivation_is_fresh_and_parser_replacement_is_not_cached(monkeypatch):
    import evidence_exact_cache as cache
    import json
    cache._json_entries.clear()
    body=b'{"nested":[{"value":7}],"duplicate":1,"duplicate":2}'
    first=cache.json_body(body)
    first['nested'][0]['value']=99
    assert cache.json_body(body)==json.loads(body)
    assert cache.json_body(body.replace(b'7',b'8'))['nested'][0]['value']==8
    assert len(cache._json_entries)==2
    marker=object()
    monkeypatch.setattr(json,'loads',lambda body:marker)
    assert cache.json_body(body) is marker
    assert cache.json_body(body) is marker


def test_exact_json_byte_bound_eviction_oversize_and_decode_errors(monkeypatch):
    import evidence_exact_cache as cache
    import json
    cache._json_entries.clear()
    monkeypatch.setattr(cache,'JSON_CACHE_BYTES',100)
    for n in range(80):
        body=('{"value":'+str(n)+'}').encode()
        assert cache.json_body(body)==json.loads(body)
        assert sum(len(k)+len(v) for k,v in cache._json_entries.items())<=100
    assert len(cache._json_entries)<80
    cache._json_entries.clear()
    monkeypatch.setattr(cache,'JSON_CACHE_BYTES',1)
    assert cache.json_body(b'{"v":7}')=={'v':7}
    assert not cache._json_entries
    for body in (b'{bad',b'\xff'):
        with pytest.raises((ValueError,UnicodeError)):cache.json_body(body)
    assert not cache._json_entries


def test_duplicates_nested_assignments_unicode_and_function_only():
    from evidence_exact_cache import symbol_range, symbol_digest
    text='class C:\n    a = b = "汉"\n    x: int = 3\n    async def f(self):\n        return 7\n'
    tree=ast.parse(text)
    for name,node in [('a',tree.body[0].body[0]),('b',tree.body[0].body[0]),
                      ('x',tree.body[0].body[1]),('f',tree.body[0].body[2])]:
        coordinates=symbol_range(text,['C',name])
        assert coordinates[:2]==(node.lineno,node.end_lineno)
        assert symbol_digest(text,coordinates)==hashlib.sha256(ast.get_source_segment(text,node).encode()).hexdigest()
    with pytest.raises(AssertionError):symbol_range('def f(): pass\ndef f(): pass\n',['f'])
    with pytest.raises(AssertionError):symbol_range('class install: pass\n',['install'],function_only=True)
    with pytest.raises(SyntaxError):symbol_range('def invalid(',['f'])
