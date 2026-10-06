"""Real PG concurrency, fresh-app and bounded-window proof in owned schema only."""
import json
import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Lock
import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from tests_isolated.test_owner_admin_security_pg import pg_security
from tests_isolated.test_email_attempts import MAIL, ISSUE, VERIFY, verify, DAILY, ADMIN
from app.models.user import User, EmailCode, AuthSession
from app.models.config import AppConfig
from app.services import email_attempts as guard

@pytest.fixture
def pg_email(pg_security, monkeypatch):
    from app.routers import admin_email
    engine, c0, c1, make_app = pg_security
    EmailCode.__table__.create(engine)
    with Session(engine) as db:
        user = db.query(User).one()
        user.email = MAIL
        user.email_verified = True
        db.commit()
    deliveries = []
    mutex = Lock()
    sequence = iter(range(123400,124000))
    monkeypatch.setattr(guard.secrets,'randbelow',lambda limit:next(sequence))
    monkeypatch.setattr(admin_email,'_load',lambda:{'enabled':True,'host':'smtp.invalid','username':'fixture','password':'fixture'})
    def send(cfg,email,subject,html):
        with mutex:
            deliveries.append(re.search(r'>\s*(\d{6})\s*</div>',html).group(1))
    monkeypatch.setattr(admin_email,'_send',send)
    c2 = TestClient(make_app())
    c2.cookies.update(c0.cookies)
    # FastAPI/Starlette lazily builds routes on first request; initialize each
    # app before sharing clients across concurrent request threads.
    for client in [c0,c1,c2]:
        assert client.get('/auth/me').status_code == 200
    yield engine,[c0,c1,c2],make_app,deliveries
    c2.close()


def issue(env,purpose):
    engine,clients,make_app,deliveries = env
    assert clients[0].post(ISSUE[purpose],json={'email':MAIL}).status_code == 200
    return deliveries[-1]


def parallel(n,fn):
    barrier = Barrier(n)
    def act(i):
        barrier.wait(timeout=15)
        return fn(i)
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(act,range(n)))


def receipt(name, statuses, **counts):
    target = os.getenv('STELLA_EMAIL_PG_PROOF')
    if target:
        with open(target,'a') as out:
            out.write(json.dumps({'name':name,'statuses':dict(Counter(statuses)),**counts})+'\n')


@pytest.mark.parametrize('purpose',['login','reset','bind'])
def test_pg_twelve_parallel_guesses_only_five_attempts_commit(pg_email,purpose):
    engine,clients,make_app,deliveries = pg_email
    code = issue(pg_email,purpose)
    with Session(engine) as db:
        before = db.query(AuthSession).count()
    def attempt(i):
        response = verify(clients[i%3],purpose,'wrong')
        return response.status_code, response.json().get('detail')
    responses = parallel(12,attempt)
    statuses = [status for status, _ in responses]
    assert Counter(statuses) == {401:5,429:7}, responses
    assert verify(clients[2],purpose,code).status_code == 429
    with Session(engine) as db:
        state = json.loads(db.get(AppConfig,guard.STATE_KEY).value)
        assert len(state['failures']) == 5
        assert state['slots'][purpose]['attempts'] == 5
        assert db.query(EmailCode).count() == 0
        assert db.query(AuthSession).count() == before
    receipt('parallel_guesses_'+purpose,statuses,attempts=5,code_rows=0,new_sessions=0)


@pytest.mark.parametrize('purpose',['login','reset','bind'])
def test_pg_correct_redemption_exactly_once_across_fresh_apps(pg_email,purpose):
    engine,clients,make_app,deliveries = pg_email
    code = issue(pg_email,purpose)
    statuses = parallel(3,lambda i:verify(clients[i],purpose,code).status_code)
    assert Counter(statuses) == {200:1,404:2}
    with Session(engine) as db:
        assert db.query(EmailCode).count() == 0
    receipt('one_time_redemption_'+purpose,statuses,code_rows=0)


def test_pg_parallel_resend_preserves_account_failures_and_invalidates_old_code(pg_email):
    engine,clients,make_app,deliveries = pg_email
    old = issue(pg_email,'login')
    assert [verify(clients[0],'login','wrong').status_code for _ in range(4)] == [401]*4
    statuses = parallel(8,lambda i:clients[i%3].post('/auth/email/resend',json={'email':MAIL,'purpose':'login'}).status_code)
    assert Counter(statuses) == {200:1,429:7}
    new = deliveries[-1]
    assert old != new
    assert verify(clients[2],'login',old).status_code == 401  # fifth account failure
    assert verify(clients[1],'login',new).status_code == 429
    assert clients[0].post('/auth/forgot',json={'email':MAIL}).status_code == 429
    with Session(engine) as db:
        state = json.loads(db.get(AppConfig,guard.STATE_KEY).value)
        assert len(state['failures']) == 5 and len(state['deliveries']) == 2
    receipt('parallel_resend',statuses,failures=5,deliveries=2)


def test_pg_cooldown_expires_but_exhausted_code_cannot_return(pg_email,monkeypatch):
    engine,clients,make_app,deliveries = pg_email
    started = guard.now()
    monkeypatch.setattr(guard,'now',lambda:started)
    old = issue(pg_email,'login')
    assert [verify(clients[0],'login','wrong').status_code for _ in range(5)] == [401]*5
    monkeypatch.setattr(guard,'now',lambda:started+timedelta(seconds=301))
    fresh = TestClient(make_app())
    assert verify(fresh,'login',old).status_code == 404
    assert fresh.post('/auth/login-code/send',json={'email':MAIL}).status_code == 200
    assert verify(fresh,'login',deliveries[-1]).status_code == 200
    fresh.close()
    receipt('bounded_cooldown',[404,200,200],elapsed_seconds=301)


def test_pg_per_code_limit_survives_account_window_expiration(pg_email,monkeypatch):
    engine,clients,make_app,deliveries = pg_email
    started = guard.now()
    monkeypatch.setattr(guard,'now',lambda:started)
    old = issue(pg_email,'bind')
    assert [verify(clients[0],'bind','wrong').status_code for _ in range(4)] == [401]*4
    monkeypatch.setattr(guard,'now',lambda:started+timedelta(seconds=301))
    assert verify(clients[2],'bind','wrong').status_code == 401
    assert verify(clients[2],'bind',old).status_code == 404
    assert clients[2].post('/auth/email/send-code',json={'email':MAIL}).status_code == 200
    assert verify(clients[2],'bind',deliveries[-1]).status_code == 200
    receipt('per_code_across_window',[401,404,200,200],attempts=5)


def test_pg_concurrent_initial_sends_do_not_duplicate_delivery(pg_email):
    engine,clients,make_app,deliveries = pg_email
    statuses = parallel(8,lambda i:clients[i%3].post('/auth/login-code/send',json={'email':MAIL}).status_code)
    assert statuses == [200]*8
    assert len(deliveries) == 1
    with Session(engine) as db:
        assert db.query(EmailCode).count() == 1
        state = json.loads(db.get(AppConfig,guard.STATE_KEY).value)
        assert len(state['deliveries']) == 1
    receipt('concurrent_initialization',statuses,deliveries=1,code_rows=1)
