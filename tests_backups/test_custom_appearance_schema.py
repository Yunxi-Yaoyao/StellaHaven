"""Pure schema tests; no app config/database imports or environment access."""
import pytest
from pydantic import ValidationError
from app.schemas.backups import ClientPreferences, ClientPreferencesWrite

CUSTOM={'version':1,'base':'B','overrides':{'accent':'#AABBCC','metric-cpu':'#ABCDEF'}}

def test_custom_and_retained_custom_are_accepted_and_legacy_is_readable():
    assert ClientPreferences(appearance='custom',customAppearance=CUSTOM).model_dump()['customAppearance']==CUSTOM
    assert ClientPreferences(appearance='A',customAppearance=CUSTOM).model_dump()['customAppearance']==CUSTOM
    assert ClientPreferences.model_validate({'appearance':'B'}).appearance=='B'
    assert ClientPreferencesWrite.model_validate({'expected_revision':0,'appearance':'custom','customAppearance':CUSTOM,'home':{}}).customAppearance.base=='B'

@pytest.mark.parametrize('custom',[
    {'version':1,'base':'C','overrides':{}},
    CUSTOM|{'css':'body {}'},
    CUSTOM|{'version':True},
    CUSTOM|{'overrides':{'accent':'url(javascript:evil)'}},
    CUSTOM|{'overrides':{'accent':'#FFF'}},
    CUSTOM|{'overrides':{'unknown':'#FFFFFF'}},
    CUSTOM|{'overrides':{'accent':False}},
])
def test_closed_custom_contract(custom):
    with pytest.raises(ValidationError):
        ClientPreferences(appearance='custom',customAppearance=custom)

def test_custom_schema_exposes_hex_validation_for_openapi():
    schema = ClientPreferences.model_json_schema()
    assert schema['$defs']['CustomAppearance']['properties']['overrides']['additionalProperties']['pattern'] == '^#[0-9A-Fa-f]{6}$'


def test_registered_client_response_matches_approved_custom_schema():
    import json
    from pathlib import Path
    models = json.loads((Path(__file__).resolve().parents[1] / 'app/api_response_models.json').read_text())
    assert models['BackupClientPreferences'] == ClientPreferences.model_json_schema(mode='serialization')


def test_custom_requires_payload():
    with pytest.raises(ValidationError):
        ClientPreferences(appearance='custom')
