"""Byte-for-byte loopback TCP relay inside owned netns; no HTTP rewriting."""
import json,os,socket,threading,select
from pathlib import Path
s=json.loads(Path('/root/.hermes/cache/scratch/notes-joint-6b01e8e/private.json').read_text())
assert os.stat('/proc/self/ns/net').st_ino==os.stat('/proc/'+str(s['pid'])+'/ns/net').st_ino

def relay(client):
    with client,socket.create_connection(('127.0.0.1',18080)) as upstream:
        while True:
            readable,_,_=select.select([client,upstream],[],[],60)
            if not readable:continue
            for source in readable:
                data=source.recv(65536)
                if not data:return
                (upstream if source is client else client).sendall(data)
with socket.socket() as server:
    server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);server.bind(('127.0.0.1',s['http_port']));server.listen(128)
    print('owned namespace loopback relay ready',flush=True)
    while True:
        client,_=server.accept();threading.Thread(target=relay,args=(client,),daemon=True).start()
