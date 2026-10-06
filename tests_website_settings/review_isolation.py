"""Review-only isolation: never load application DB/config/auth bootstrap."""
import os,sys,types,pathlib
os.environ.update(STELLA_SECRET_KEY='review-synthetic-signing-key-00000000',STELLA_MAIN_ORIGIN='http://stella.test')
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column
ROOT=pathlib.Path(__file__).resolve().parents[1]
for name in ('app.services','app.models','app.routers'):
    package=types.ModuleType(name);package.__path__=[str(ROOT.joinpath(*name.split('.')))];sys.modules[name]=package
class Base(DeclarativeBase):pass
sys.modules['app.models'].Base=Base
sys.modules['app.models'].Mapped=Mapped
sys.modules['app.models'].mapped_column=mapped_column
database=types.ModuleType('app.database')
database.engine=create_engine('sqlite://')
def get_db():raise AssertionError('Only fixture dependency override may provide database')
database.get_db=get_db;sys.modules['app.database']=database
auth=types.ModuleType('app.routers.auth')
def current_user():raise AssertionError('Synthetic fixture auth required')
def admin_user():raise AssertionError('Synthetic fixture elevation required')
auth.current_user=current_user;auth.admin_user=admin_user;sys.modules['app.routers.auth']=auth
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
