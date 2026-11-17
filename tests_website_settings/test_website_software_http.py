"""Actual bounded loopback GET exercises checker response, not URL-based detection."""
import pytest
from test_website_settings import upstream, run_check

@pytest.mark.parametrize('status,headers,body,kind,has_code',[
 (200,[],b'<meta name="generator" content="OpenList"><div id="root"></div>','openlist',True),
 (200,[],b'<meta name="application-name" content="Immich">','immich',False),
 (200,[],b'<title>OpenList Immich</title>','unknown',False),
 (401,[],b'<meta name="generator" content="OpenList">','unknown',False),
 (200,[('Content-Security-Policy',"frame-ancestors 'none'")],b'<meta name="generator" content="OpenList">','openlist',False),
])
def test_software_and_appearance_only_from_actual_response(upstream,status,headers,body,kind,has_code):
 root,responses,seen=upstream
 responses['/openlist.immich/path']=(status,[('Content-Type','text/html')]+headers,body)
 result=run_check(root+'/openlist.immich/path')
 assert result['software']['type']==kind
 assert bool(result['compatibility']) is has_code
 if has_code:
  code=result['compatibility']
  assert code['enabled'] and 'stella-bg-ready' in code['js']
  assert 'http://stella.test' in code['js']
  assert not any(value in code['js'] for value in ('oauth','authorize','/api/fs','client_secret','fetch='))
 assert len(seen)==1
 assert not any(k.lower() in {'cookie','authorization','referer'} for k in seen[0][1])

def test_explicit_unknown_site_type_only_adds_background_not_login_or_account_changes(upstream):
 root,_,seen=upstream
 result=run_check(root,website_type='openlist')
 assert result['software']=={'type':'unknown','source':None}
 assert result['compatibility']['enabled'] is True
 assert 'oauth' not in result['compatibility']['js']
 assert seen[0][0]=='/'


def test_real_software_response_matches_closed_check_contract_and_public_projection(upstream):
 import copy
 from jsonschema import Draft202012Validator
 from app.api_response_contracts import DECLARATIONS
 from app.public_website import public_check
 root,responses,_=upstream
 responses['/']=(200,[('Content-Type','text/html')],b'<meta name="generator" content="OpenList">')
 result=run_check(root)
 schema=DECLARATIONS[('POST','/website-settings/check')]['responses']['200']['content']['application/json']['schema']
 Draft202012Validator(schema).validate(result)
 private=copy.deepcopy(result)
 private['software']['secret_extension']='must-not-leave'
 private['compatibility']['secret_extension']='must-not-leave'
 projected=public_check(private)
 assert projected['software']==result['software']
 assert projected['compatibility']==result['compatibility']
 assert 'must-not-leave' not in str(projected)
 assert private['software']['secret_extension']=='must-not-leave'
 assert 'projection' not in projected
