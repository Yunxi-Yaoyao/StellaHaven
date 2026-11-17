"""Review-only isolation: never load application DB/config/auth bootstrap."""
import os,sys,types,pathlib
os.environ.update(STELLA_SECRET_KEY='review-synthetic-signing-key-00000000',STELLA_MAIN_ORIGIN='http://stella.test')
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column,sessionmaker
ROOT=pathlib.Path(__file__).resolve().parents[1]
for name in ('app.services','app.models','app.routers'):
    package=types.ModuleType(name);package.__path__=[str(ROOT.joinpath(*name.split('.')))];sys.modules[name]=package
class Base(DeclarativeBase):pass
sys.modules['app.models'].Base=Base
sys.modules['app.models'].Mapped=Mapped
sys.modules['app.models'].mapped_column=mapped_column
database=types.ModuleType('app.database')
database.engine=create_engine('sqlite://')
def forbid_bootstrap_connect(*args,**kwargs):
    raise AssertionError('Only fixture-owned engines may connect')
event.listen(database.engine,'do_connect',forbid_bootstrap_connect)
# Match the real module's lazy Session factory interface. Host middleware imports
# its default at module import, even when the test passes an owned db_factory.
# A real Session is safe here only because the bootstrap engine cannot connect.
database.sessionLocal=sessionmaker(bind=database.engine,autoflush=False)
def get_db():raise AssertionError('Only fixture dependency override may provide database')
database.get_db=get_db;sys.modules['app.database']=database
# Keep real auth dependencies: individual synthetic route fixtures override them,
# while real-owner/session cases must exercise the actual JWT/session reloads.
from uuid import UUID, uuid4
sys.modules['app.models'].UUID=UUID
sys.modules['app.models'].uuid4=uuid4
import app.routers.auth
# Globally fail closed on non-loopback TCP connections, including accidental PG.
import socket,ipaddress
real_connect=socket.socket.connect
real_connect_ex=socket.socket.connect_ex
def guard(original):
    def wrapped(sock,address):
        if sock.family in (socket.AF_INET,socket.AF_INET6):
            try: allowed=ipaddress.ip_address(address[0]).is_loopback
            except ValueError: allowed=False
            if not allowed:raise AssertionError('Review forbids non-loopback connect: '+repr(address))
            if address[1] in (5432,36532,12031):raise AssertionError('Review forbids application/recovered database ports')
        return original(sock,address)
    return wrapped
socket.socket.connect=guard(real_connect);socket.socket.connect_ex=guard(real_connect_ex)
