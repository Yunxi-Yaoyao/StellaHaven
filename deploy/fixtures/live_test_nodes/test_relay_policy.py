import ssl,unittest
from relay_policy import allowed_client_hello
class RelayScope(unittest.TestCase):
 def hello(self,host):
  incoming=ssl.MemoryBIO();outgoing=ssl.MemoryBIO();s=ssl.create_default_context().wrap_bio(incoming,outgoing,server_hostname=host)
  try:s.do_handshake()
  except ssl.SSLWantReadError:pass
  return outgoing.read()
 def test_exact_preview_sni_only(self):
  self.assertTrue(allowed_client_hello(self.hello('stella-dev.p.xiya.live')))
  for host in ['stella.p.xiya.live','example.com','stella-dev.p.xiya.live.evil']:
   self.assertFalse(allowed_client_hello(self.hello(host)))
  for data in [b'',b'GET / HTTP/1.1\r\n',self.hello('stella-dev.p.xiya.live')[:30]]:
   self.assertFalse(allowed_client_hello(data))
if __name__=='__main__':unittest.main()
