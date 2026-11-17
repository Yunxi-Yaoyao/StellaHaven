"""Bind the legacy browser's ephemeral socket to one namespace-only allowlisted port."""
import socket
import pytest
@pytest.fixture(autouse=True)
def browser_socket(monkeypatch):
 original=socket.socket.bind
 def bind(self,address):
  if address==('127.0.0.1',0):
   self.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
   address=('127.0.0.1',18081)
  return original(self,address)
 monkeypatch.setattr(socket.socket,'bind',bind)
