"""Final ce25a6b binding controls. Candidate remains pending parent review."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from test_api_openapi_contract import ROOT, static_inventory
from test_api_response_contract import response_module
from private_remediation_evidence_fixture import review

OLD_REVIEW='56724a12ea42fb9f993e79b6d4032e227bf2d781bc3aa6886fc9873678c9f01a'
OLD_SERVICE='33dffdeda38a638799808bb09cce2e2256b8051583ea57c43b57bdfd00ca87a8'
OUT=ROOT/'docs/private-remediation/api-final'
FILE='app/services/website_settings.py'

def test_final_candidate_revises_only_seven_current_bindings_not_history():
    raw=gzip.decompress((OUT/'unreviewed-v22-493-review.json.gz').read_bytes())
    assert hashlib.sha256(raw).hexdigest()==OLD_REVIEW
    before=json.loads(raw);after=deepcopy(review())
    assert after.pop('candidate_revision_provenance')['previous_unreviewed_review_sha256']==OLD_REVIEW
    assert after['baseline']=='ce25a6be54f4c9108c34886eca77a1209bd056bf'
    after['baseline']=before['baseline']
    changed=[k for k in after['sources'] if after['sources'][k]!=before['sources'][k]]
    assert len(changed)==7
    assert {after['sources'][k]['file'] for k in changed}=={FILE}
    for key in changed:after['sources'][key]=before['sources'][key]
    assert after==before

@pytest.mark.parametrize('damage',['missing','byte','previous-unreviewed-body'])
def test_final_body_missing_byte_and_previous_candidate_fail_closed(damage):
    m=response_module();records=static_inventory()[0]
    assert m.validate_response_sources(ROOT,records)==[]
    read=Path.read_bytes;exists=Path.is_file;target=ROOT/FILE
    old=gzip.decompress((OUT/'website-settings-493.py.gz').read_bytes())
    assert hashlib.sha256(old).hexdigest()==OLD_SERVICE
    assert old!=read(target)
    if damage=='missing':
        with patch.object(Path,'is_file',lambda p:False if p==target else exists(p)):
            errors=m.validate_response_sources(ROOT,records)
    else:
        body=old if damage=='previous-unreviewed-body' else read(target)+b' '
        with patch.object(Path,'read_bytes',lambda p:body if p==target else read(p)):
            errors=m.validate_response_sources(ROOT,records)
    assert errors==['source drift or missing source: '+FILE]
