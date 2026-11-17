"""Restart only the known private HTTPS QA, retaining its synthetic data/env."""
import os
from pathlib import Path
import signal
import sys
import time
root=Path(__file__).resolve().parents[1]
pid=int(sys.argv[1]);proc=Path('/proc')/str(pid)
assert Path(os.readlink(proc/'cwd')).resolve()==root
args=(proc/'cmdline').read_bytes().split(b'\0')
assert b'33171' in args and b'uvicorn' in b' '.join(args)
env=dict(x.split('=',1) for x in (proc/'environ').read_text().split('\0') if '=' in x)
assert env['POSTGRES_HOST']=='127.0.0.1' and env['POSTGRES_PORT']=='33070' and env['POSTGRES_DB']=='navqa'
for key in ('STELLA_BACKUP_DATA_ROOT','STELLA_BACKUP_DIRECTORY'):
    assert str(Path(env[key]).resolve()).startswith('/root/.hermes/cache/scratch/')
os.kill(pid,signal.SIGTERM)
end=time.monotonic()+15
while proc.exists():
    if time.monotonic()>end: raise RuntimeError('owned QA did not stop')
    time.sleep(.1)
os.chdir(root)
os.execvpe(args[0].decode(),[a.decode() for a in args if a],env)
