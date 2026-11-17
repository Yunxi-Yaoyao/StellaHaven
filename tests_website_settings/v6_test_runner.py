"""Allowlisted standalone runner; only this process's listening TCP ports.
Never imports application bootstrap or reads production dotenv/configuration.
"""
import os
import socket
import sys
import ipaddress

owned=set()
original_listen=socket.socket.listen
original_connect=socket.socket.connect
original_connect_ex=socket.socket.connect_ex

def listen(sock,*args,**kwargs):
    result=original_listen(sock,*args,**kwargs)
    if sock.family in (socket.AF_INET,socket.AF_INET6):
        address=sock.getsockname()
        if ipaddress.ip_address(address[0]).is_loopback: owned.add(address[1])
    return result

def guard(original):
    def connect(sock,address):
        if sock.family in (socket.AF_INET,socket.AF_INET6):
            try: safe=ipaddress.ip_address(address[0]).is_loopback
            except ValueError: safe=False
            if not safe or address[1] not in owned or address[1] in {25436,24532,12031,5432}:
                raise AssertionError('Only process-owned fixture listeners are permitted')
        return original(sock,address)
    return connect

socket.socket.listen=listen
socket.socket.connect=guard(original_connect)
socket.socket.connect_ex=guard(original_connect_ex)
assert not any(os.getenv(key) for key in ('STELLA_DATABASE_URL','DATABASE_URL','HERMES_WORKER_PROFILE','HERMES_BROKER_PID','UV_PROJECT_ENVIRONMENT','VIRTUAL_ENV'))
import pytest
raise SystemExit(pytest.main(sys.argv[1:]))
