"""Software hint must come from fetched HTML, never URL/title; no DB imports."""
import ast
from pathlib import Path
from html.parser import HTMLParser
import pytest

source=Path(__file__).resolve().parents[1]/'app/services/website_check.py'
module=ast.parse(source.read_text())
namespace={'HTMLParser':HTMLParser}
exec(compile(ast.Module(body=[n for n in module.body if isinstance(n,ast.ClassDef) and n.name=='Document' or isinstance(n,ast.FunctionDef) and n.name=='appearance_compatibility'],type_ignores=[]),str(source),'exec'),namespace)

def test_automatic_compatibility_is_appearance_only_not_auth_or_cache_replacement(monkeypatch):
 import sys, types
 package=types.ModuleType('app.services');package.__path__=[str(source.parent)]
 monkeypatch.setitem(sys.modules,'app.services',package)
 assert 'appearance_compatibility' in namespace
 result=namespace['appearance_compatibility']('openlist','https://current-parent.test')
 assert result['enabled'] is True
 assert 'https://current-parent.test' in result['js']
 assert 'event.source!==window.parent' in result['js']
 assert 'stella-bg-ready' in result['js']
 for forbidden in ('oauth','authorize','/api/fs','fetch=', 'XMLHttpRequest', 'location.href=', 'client_secret'):
  assert forbidden not in result['js']
 assert namespace['appearance_compatibility']('immich','https://current-parent.test') is None


@pytest.mark.parametrize('html,expected',[
 ('<meta name="generator" content="OpenList">',{'type':'openlist','source':'html:generator'}),
 ('<meta name="application-name" content="Immich">',{'type':'immich','source':'html:application-name'}),
 ('<title>OpenList Immich</title>',{'type':'unknown','source':None}),
 ('<meta name="generator" content="OpenList hacked">',{'type':'unknown','source':None}),
 ('<meta name="generator" content="OpenList"><meta name="generator" content="Immich">',{'type':'unknown','source':None}),
 ('<meta name="generator" content="OpenList"><meta name="application-name" content="Immich">',{'type':'unknown','source':None}),
 ('<meta content="immich" NAME="application-name">',{'type':'immich','source':'html:application-name'}),
])
def test_document_software_evidence(html,expected):
 document=namespace['Document']();document.feed(html)
 assert document.software == expected
