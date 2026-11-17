#!/usr/bin/env python3
"""Offline integrations_v1 snapshot migration. Default dry-run; never connects to DB.

Freeze both hashes before review. Only the marked bridge is replaced; all owner
code outside it and active CSS/draft/previous are retained. Apply is for a local
snapshot only, NOT a production DB write. Production import must CAS the original
raw config in the owner's existing transaction, then read back the exact target.
"""
import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

MARKER='/* stella:background-ready:v1 */'

def sha(value):
    return hashlib.sha256(value).hexdigest()

def fragment(code):
    if code.count(MARKER)!=1:
        raise ValueError('exactly one background bridge required; custom copy retained')
    start=code.index(MARKER)
    end=code.find('\n})();',start)
    if end<0:
        raise ValueError('unknown bridge boundary; custom copy retained')
    return start,end+6

def prepare(raw,module_id,expected_config,expected_js,replacement):
    for digest in (expected_config,expected_js):
        if not re.fullmatch('[0-9a-f]{64}',digest):
            raise ValueError('exact frozen SHA256 required')
    if sha(raw)!=expected_config:
        raise ValueError('configuration CAS mismatch; nothing changed')
    config=json.loads(raw)
    updated=copy.deepcopy(config)
    active=updated['modules'][module_id]['injection']['active']
    if sha(active['js'].encode())!=expected_js:
        raise ValueError('active JS CAS mismatch; custom copy retained')
    a,b=fragment(active['js']);c,d=fragment(replacement)
    active['js']=active['js'][:a]+replacement[c:d]+active['js'][b:]
    active['version']='background-'+sha(active['js'].encode())[:16]
    return json.dumps(updated,ensure_ascii=False,separators=(',',':')).encode()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot',type=Path)
    parser.add_argument('--module-id',required=True)
    parser.add_argument('--expected-config-sha256',required=True)
    parser.add_argument('--expected-js-sha256',required=True)
    parser.add_argument('--replacement-js',type=Path,required=True,help='actual candidate export, not a handwritten bridge')
    parser.add_argument('--backup-dir',type=Path,required=True)
    parser.add_argument('--apply-local-file',action='store_true')
    args=parser.parse_args()
    if args.snapshot.is_symlink() or not args.snapshot.is_file():
        parser.error('snapshot must be a regular local file, not a symlink')
    if not args.apply_local_file:
        raw=args.snapshot.read_bytes()
        candidate=prepare(raw,args.module_id,args.expected_config_sha256,args.expected_js_sha256,args.replacement_js.read_text())
        print(json.dumps({'dry_run':True,'source_sha256':sha(raw),'candidate_sha256':sha(candidate),'module_id':args.module_id,'scope':'offline snapshot only; production DB not changed'}))
        return
    # A stable sidecar serializes this tool's cooperative local file writers.
    lock=args.snapshot.with_name(args.snapshot.name+'.migration.lock')
    fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+b') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX)
        raw=args.snapshot.read_bytes()
        candidate=prepare(raw,args.module_id,args.expected_config_sha256,args.expected_js_sha256,args.replacement_js.read_text())
        receipt={'dry_run':not args.apply_local_file,'source_sha256':sha(raw),'candidate_sha256':sha(candidate),'module_id':args.module_id,'scope':'offline snapshot only; production DB not changed'}
        if args.apply_local_file:
            args.backup_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
            if args.backup_dir.is_symlink() or args.backup_dir.stat().st_mode&0o077:
                raise ValueError('backup directory must be private (0700)')
            backup=args.backup_dir/(sha(raw)+'.json')
            with os.fdopen(os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as out:
                out.write(raw);out.flush();os.fsync(out.fileno())
            # Recheck after backup; refuse owner edits rather than replacing them.
            if args.snapshot.read_bytes()!=raw:
                raise ValueError('configuration changed after planning; private backup retained')
            temp_fd,temp_name=tempfile.mkstemp(prefix='.background-',dir=args.snapshot.parent)
            try:
                with os.fdopen(temp_fd,'wb') as out:
                    os.fchmod(out.fileno(),0o600);out.write(candidate);out.flush();os.fsync(out.fileno())
                os.replace(temp_name,args.snapshot)
            finally:
                Path(temp_name).unlink(missing_ok=True)
            if args.snapshot.read_bytes()!=candidate:
                raise ValueError('local readback mismatch; private backup retained')
        print(json.dumps(receipt))

if __name__=='__main__':
    main()
