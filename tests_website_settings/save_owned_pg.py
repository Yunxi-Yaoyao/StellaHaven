"""Nonce-admitted PostgreSQL only. No Docker or resource provisioning in pytest."""
import json
import os
from pathlib import Path
import re
from uuid import uuid4


def admitted_database():
    if os.environ.get('STELLA_CI_NONCE_PG')=='1':
        from deploy.ci.owned_pg import admitted_marker,verify_admin
        marker=admitted_marker()
        params=dict(host='postgres',port=5432,dbname='stella_test',user='stalla',password=os.environ['POSTGRES_PASSWORD'])
        def verify(connection): verify_admin(connection,marker)
        return params,verify
    path=Path(os.environ['STELLA_SAVE_PG_RECEIPT'])
    root=Path(os.environ['TMPDIR'])
    if path.parent!=root or path.is_symlink() or root.is_symlink() or root.stat().st_mode&0o077 or path.stat().st_mode&0o077 or path.stat().st_uid!=os.geteuid():
        raise ValueError('private owned save PG receipt required')
    data=json.loads(path.read_text())
    nonce=os.environ.get('STELLA_SAVE_PG_NONCE','')
    if (not re.fullmatch('[0-9a-f]{32}',nonce) or set(data)!={'nonce','pid','port','database','role','system','password'}
        or data['nonce']!=nonce or data['pid']!=os.getppid() or data['database']!='save_'+nonce or data['role']!=data['database']
        or type(data['port']) is not int or not 1024<data['port']<65536 or data['port'] in {5432,24532,25432,25436,36532,12031}
        or not re.fullmatch('[0-9]+',data['system'])):
        raise ValueError('foreign owned save PG identity')
    params=dict(host='127.0.0.1',port=data['port'],dbname=data['database'],user=data['role'],password=data['password'])
    def verify(connection):
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_database(),current_user,system_identifier::text FROM pg_control_system()')
            if cursor.fetchone()!=(data['database'],data['role'],data['system']): raise ValueError('foreign save PG server')
        connection.rollback()
    return params,verify


def isolated_factory():
    from sqlalchemy import create_engine,event,text
    from sqlalchemy.engine import URL
    from sqlalchemy.orm import sessionmaker
    from app.models.config import AppConfig
    params,verify=admitted_database()
    if any(k.startswith('PG') for k in os.environ) or os.environ.get('DATABASE_URL') or os.environ.get('STELLA_DATABASE_URL'):
        raise ValueError('ambient DSN/libpq overrides forbidden')
    schema='save_closure_'+uuid4().hex
    engine=create_engine(URL.create('postgresql+psycopg2',username=params['user'],password=params['password'],host=params['host'],port=params['port'],database=params['dbname']))
    def checkout(connection,*args):
        verify(connection)
        connection.rollback()
        with connection.cursor() as cursor: cursor.execute('SET search_path TO '+schema+',public')
        connection.commit()
    event.listen(engine,'checkout',checkout)
    created=False
    try:
        with engine.begin() as connection:
            connection.execute(text('CREATE SCHEMA '+schema));created=True
        AppConfig.__table__.create(engine)
        yield sessionmaker(engine,expire_on_commit=False)
    finally:
        if created:
            with engine.begin() as connection: connection.execute(text('DROP SCHEMA '+schema+' CASCADE'))
            with engine.connect() as connection:
                assert connection.execute(text('SELECT count(*) FROM pg_namespace WHERE nspname=:schema'),{'schema':schema}).scalar()==0
        engine.dispose()
