"""Authorization must not retain/reacquire an ORM checkout after auth resolution."""
import importlib
from urllib.parse import parse_qs,urlsplit
import pytest
from starlette.requests import Request
from starlette.responses import Response
from sqlalchemy import inspect,event
from tests_isolated.test_oidc_provider import api,oidc  # noqa:F401

@pytest.mark.parametrize('kind',['access','refresh','guest'])
def test_optional_principal_is_scalar_and_releases_auth_transaction(api,oidc,kind):
    public=importlib.import_module('app.routers.oidc')
    cookie=(f'stella_at={api.owner_cookie}' if kind=='access' else f'stella_rt={api.rt}' if kind=='refresh' else '')
    req=Request({'type':'http','method':'GET','path':'/oauth/authorize','headers':[(b'cookie',cookie.encode())],'query_string':b''})
    response=Response()
    with api.factory() as db:
        result=public._optional_user(req,response,db)
        assert not db.in_transaction(),'auth transaction must return checkout before OIDC service'
        if kind=='guest':assert result is None;return
        assert inspect(result,raiseerr=False) is None,'no attached/expired ORM object may escape'
        assert str(result.id)==str(api.owner_id)
        assert result.username=='actual-owner' and result.email=='owner@test'
        assert not db.in_transaction(),'reading claims must not reopen auth connection'
        if kind=='refresh':
            cookies=response.headers.getlist('set-cookie')
            assert any(s.startswith('stella_at=') for s in cookies)
            assert any(s.startswith('stella_rt=') for s in cookies)


def test_owner_rejection_is_not_swallowed_and_transaction_released(api,oidc):
    from fastapi import HTTPException
    public=importlib.import_module('app.routers.oidc')
    req=Request({'type':'http','method':'GET','path':'/oauth/authorize','headers':[(b'cookie',f'stella_at={api.foreign_cookie}'.encode())],'query_string':b''})
    with api.factory() as db:
        with pytest.raises(HTTPException) as error:public._optional_user(req,Response(),db)
        assert error.value.status_code==403
        assert not db.in_transaction()
