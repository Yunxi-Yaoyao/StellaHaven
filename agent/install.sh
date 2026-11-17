#!/bin/bash
# Legacy stella-agent is never adopted. One root Agent owns its file child.
set -e
command -v python3 >/dev/null || { printf '%s\n' '错误：请先安装 python3' >&2; exit 1; }
exec python3 -I - "$@" <<'STELLA_INSTANCE_INSTALLER'
import argparse, contextlib, fcntl, hashlib, json, os, re, shutil, stat, subprocess, sys, tempfile
from pathlib import Path
import urllib.parse, urllib.request
CODE_BASE = Path('/opt/stella-agents')
CONFIG_BASE = Path('/etc/stella-agents')
UNIT_BASE = Path('/etc/systemd/system')
SUDO_BASE = Path('/etc/sudoers.d')
HELPER_BASE = Path('/usr/local/libexec')

def run(args):
    return subprocess.run(args, check=True, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45)

def trusted(path):
    for part in [*reversed(path.parents), path]:
        if part.is_symlink(): raise ValueError('symlink refused')
        if part.exists():
            st = part.stat()
            if st.st_uid != 0 or st.st_mode & 0o022: raise ValueError('untrusted owner/mode')
            if part != path and not part.is_dir(): raise ValueError('invalid ancestor')

def atomic(path, data, mode=0o600, uid=0, gid=0, validator=None):
    fd, name = tempfile.mkstemp(prefix='.install-', dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out: out.write(data); out.flush(); os.fsync(out.fileno())
        os.chmod(name,mode); os.chown(name,uid,gid)
        if validator: validator(name)
        os.replace(name,path)
    finally: Path(name).unlink(missing_ok=True)

def fetch(url, token=None, limit=8*1024*1024):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs): return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect)
    headers = {'Authorization':'Bearer '+token} if token else {}
    with opener.open(urllib.request.Request(url,headers=headers),timeout=30) as response:
        if response.status != 200: raise ValueError('HTTP failure')
        body = response.read(limit+1)
        if len(body)>limit: raise ValueError('oversized response')
        return body

def preflight(url, token):
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('','/'): raise ValueError('invalid origin')
    if not token or any(c in token for c in '\r\n\x00'): raise ValueError('invalid token')
    value = json.loads(fetch(url.rstrip('/')+'/agent/identity',token,8192))
    if not isinstance(value,dict) or set(value)!={'center_id','node_id','source_version','source_sha256','source_size'}: raise ValueError('missing identity')
    if not re.fullmatch('[a-f0-9]{64}',str(value['center_id'])) or type(value['node_id']) is not int or value['node_id']<=0: raise ValueError('invalid binding')
    if not re.fullmatch('[a-f0-9]{64}',str(value['source_sha256'])) or type(value['source_size']) is not int or not 0<value['source_size']<=8*1024*1024: raise ValueError('invalid artifact metadata')
    body = fetch(url.rstrip('/')+'/agent/script')
    if len(body)!=value['source_size'] or hashlib.sha256(body).hexdigest()!=value['source_sha256']: raise ValueError('artifact mismatch')
    import ast
    tree=ast.parse(body,filename='stella_agent.py'); compile(tree,'stella_agent.py','exec')
    declarations=[n.value.value for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='AGENT_VERSION' and isinstance(n.value,ast.Constant)]
    if declarations != [value['source_version']]: raise ValueError('artifact version mismatch')
    return value,body

def helper_source(binding,code,config,unit,sudo,helper,account,systemctl):
    c = dict(binding=binding,code=str(code),config=str(config),unit=str(unit),sudo=str(sudo),helper=str(helper),account=account,systemctl=systemctl,systemd_run=shutil.which('systemd-run'),userdel=shutil.which('userdel'))
    return ('#!'+sys.executable+' -I\nC = '+repr(c)+'\n'+r'''
import fcntl,json,os,pathlib,shutil,subprocess,sys

def invoke(*args):
    subprocess.run(args,check=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=45)

def main():
    if os.geteuid()!=0 or sys.argv[1:] not in (['--schedule'],['--remove']): raise ValueError('request refused')
    config=pathlib.Path(C['config']); manifest=config/'instance.json'
    for path in [*reversed(config.parents),config,manifest,pathlib.Path(C['unit']),pathlib.Path(C['helper'])]:
        st=path.lstat()
        if path.is_symlink() or st.st_uid!=0 or st.st_mode&0o022: raise ValueError('untrusted ownership')
    if json.loads(manifest.read_text())!=C['binding']: raise ValueError('binding mismatch')
    fd=os.open(config.parent/('.'+C['binding']['instance_id']+'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    if os.fstat(fd).st_uid!=0 or os.fstat(fd).st_mode&0o022: raise ValueError('untrusted lock')
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if sys.argv[1]=='--schedule':
        invoke(C['systemd_run'],'--unit=stella-remove-'+C['binding']['instance_id'],'--on-active=3',C['helper'],'--remove'); return
    text=pathlib.Path(C['unit']).read_text()
    if 'User=root\n' not in text or ('EnvironmentFile='+C['config']+'/agent.env\n') not in text: raise ValueError('unit mismatch')
    invoke(C['systemctl'],'disable',C['binding']['service']); invoke(C['systemctl'],'stop',C['binding']['service'])
    pathlib.Path(C['unit']).unlink(); invoke(C['systemctl'],'daemon-reload')
    for name in ('code','config'):
        path=pathlib.Path(C[name])
        if path.is_symlink(): raise ValueError('symlink root refused')
        shutil.rmtree(path)
    pathlib.Path(C['sudo']).unlink(); invoke(C['userdel'],C['account']); pathlib.Path(C['helper']).unlink()

if __name__=='__main__':
    try: main()
    except Exception:
        print('Stella instance removal refused or failed',file=sys.stderr); sys.exit(1)
''').encode()

def install(args):
    if os.geteuid()!=0: raise ValueError('root required')
    systemctl,visudo=shutil.which('systemctl'),shutil.which('visudo')
    if not systemctl or not visudo or not shutil.which('useradd'): raise ValueError('systemd/visudo/useradd required')
    identity,body=preflight(args.url,args.token)  # before resident writes/accounts
    if args.instance and not re.fullmatch('[a-z0-9][a-z0-9-]{0,31}',args.instance): raise ValueError('invalid instance label')
    seed='stella-instance-v1:'+identity['center_id']+(':slot:'+args.instance if args.instance else '')
    iid=hashlib.sha256(seed.encode()).hexdigest()[:24]
    service,account='stella-agent-'+iid,'sta'+iid
    code,config=CODE_BASE/iid,CONFIG_BASE/iid
    unit,sudo,helper=UNIT_BASE/(service+'.service'),SUDO_BASE/service,HELPER_BASE/service
    binding=dict(format=1,center_id=identity['center_id'],node_id=identity['node_id'],instance_id=iid,service=service,slot=args.instance)
    for base in (CODE_BASE,CONFIG_BASE,UNIT_BASE,SUDO_BASE,HELPER_BASE): trusted(base)
    if not (config/'instance.json').exists() and any(p.exists() or p.is_symlink() for p in (code,config,unit,sudo,helper)):
        raise ValueError('foreign target exists')
    for base in (CODE_BASE,CONFIG_BASE,UNIT_BASE,SUDO_BASE,HELPER_BASE): base.mkdir(parents=True,exist_ok=True,mode=0o755)
    # mkdir's mode is filtered by the caller's umask; these trusted public
    # directories must remain traversable by the dedicated instance UID.
    for base in (CODE_BASE,CONFIG_BASE,HELPER_BASE): os.chmod(base,0o755)
    lockpath=CONFIG_BASE/('.'+iid+'.lock'); trusted(lockpath)
    with os.fdopen(os.open(lockpath,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600),'w') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        manifest=config/'instance.json'; existing=manifest.exists()
        if existing:
            trusted(config); trusted(manifest)
            if json.loads(manifest.read_text())!=binding: raise ValueError('same center already bound to another node')
            for path in (unit,sudo,helper): trusted(path)
            if code.is_symlink() or not code.is_dir() or not all(p.is_file() for p in (unit,sudo,helper)): raise ValueError('incomplete/foreign instance')
            unit_text=unit.read_text()
            if not any(('User='+user+'\n') in unit_text for user in (account,'root')): raise ValueError('foreign unit user')
            for expected in (f'EnvironmentFile={config}/agent.env\n',f'ExecStart=/usr/bin/env python3 {code}/stella_agent.py\n'):
                if expected not in unit_text: raise ValueError('foreign unit definition')
        else:
            if any(p.exists() or p.is_symlink() for p in (code,config,unit,sudo,helper)): raise ValueError('foreign target exists')
            if run([systemctl,'show',service,'--property=FragmentPath','--value']).stdout.strip(): raise ValueError('foreign service exists')
        user=subprocess.run(['id','-u',account],capture_output=True,text=True,timeout=5)
        if not existing and user.returncode==0: raise ValueError('foreign account exists')
        if existing and user.returncode!=0: raise ValueError('account missing')
        update_lock=None
        if existing:
            update_lock=os.open(code/'.update.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
            try: fcntl.flock(update_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except Exception: os.close(update_lock); raise
        saved={}; created_user=False
        saved_code=code.stat() if existing else None
        saved_lock=os.fstat(update_lock) if existing else None
        targets=(code/'stella_agent.py',config/'agent.env',manifest,unit,sudo,helper)
        if existing:
            for path in targets:
                if path.is_symlink() or not path.is_file(): raise ValueError('incomplete instance files')
                st=path.stat(); saved[path]=(path.read_bytes(),stat.S_IMODE(st.st_mode),st.st_uid,st.st_gid)
        try:
            if not existing:
                run(['useradd','--system','--no-create-home','--shell','/usr/sbin/nologin',account]); created_user=True
            # Keep the old account only for scoped legacy removal compatibility;
            # executable code and all new processes are root-owned.
            uid=gid=0
            config.mkdir(mode=0o755,exist_ok=True); os.chmod(config,0o755)
            code.mkdir(mode=0o700,exist_ok=True); os.chown(code,uid,gid); os.chmod(code,0o700)
            if update_lock is None:
                update_lock=os.open(code/'.update.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
                fcntl.flock(update_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            os.fchown(update_lock,uid,gid)
            installed_origin=args.url.rstrip('/')
            if existing:
                # An alias used to authenticate a repair must not reset the
                # runtime/cache origin or its monotonic report receipt sequence.
                previous_env=dict(line.split('=',1) for line in saved[config/'agent.env'][0].decode().splitlines() if '=' in line)
                installed_origin=json.loads(previous_env['STELLA_URL'])
                parsed=urllib.parse.urlsplit(installed_origin)
                if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
                    raise ValueError('invalid resident origin')
            env=dict(STELLA_URL=installed_origin,STELLA_TOKEN=args.token,STELLA_INSTANCE_ID=iid,STELLA_INSTANCE_MANIFEST=str(manifest))
            atomic(code/'stella_agent.py',body,0o700,uid,gid)
            atomic(config/'agent.env',''.join(k+'='+json.dumps(v)+'\n' for k,v in env.items()).encode())
            atomic(manifest,json.dumps(binding,sort_keys=True).encode(),0o644)
            atomic(helper,helper_source(binding,code,config,unit,sudo,helper,account,systemctl),0o755)
            grants=f'{account} ALL=(root) NOPASSWD: {helper} --schedule\n'
            if args.admin_network:
                for name in ('ip','nmcli','netplan','ufw','iptables-save','iptables','ping'):
                    exe=shutil.which(name)
                    if exe: grants+=f'{account} ALL=(root) NOPASSWD: {exe}\n'
                wg=shutil.which('wg')
                if wg:
                    for field in ('public-key','peers','endpoints','allowed-ips','latest-handshakes','transfer'): grants+=f'{account} ALL=(root) NOPASSWD: {wg} show all {field}\n'
            elif existing: grants=saved[sudo][0].decode()
            atomic(sudo,grants.encode(),0o440,validator=lambda stage: run([visudo,'-cf',stage]))
            text=f'''[Unit]
Description=Stella Agent instance {iid}
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=root
Group=root
KillMode=control-group
TimeoutStopSec=10
AmbientCapabilities=CAP_NET_RAW
ExecStart=/usr/bin/env python3 {code}/stella_agent.py
EnvironmentFile={config}/agent.env
WorkingDirectory={code}
Restart=always
RestartSec=5
UMask=0077
[Install]
WantedBy=multi-user.target
'''
            atomic(unit,text.encode(),0o644)
            run([systemctl,'daemon-reload']); run([systemctl,'enable',service]); run([systemctl,'restart',service]); run([systemctl,'is-active','--quiet',service])
        except Exception:
            if existing:
                for path,(data,mode,owner,group) in saved.items(): atomic(path,data,mode,owner,group)
                # Restore traversal and updater-lock access before the old UID
                # is restarted; restoring only executable bytes is insufficient.
                os.chown(code,saved_code.st_uid,saved_code.st_gid)
                os.chmod(code,stat.S_IMODE(saved_code.st_mode))
                os.fchown(update_lock,saved_lock.st_uid,saved_lock.st_gid)
                os.fchmod(update_lock,stat.S_IMODE(saved_lock.st_mode))
                with contextlib.suppress(Exception): run([systemctl,'daemon-reload']); run([systemctl,'restart',service])
            else:
                with contextlib.suppress(Exception): run([systemctl,'disable','--now',service])
                for path in (unit,sudo,helper): path.unlink(missing_ok=True)
                shutil.rmtree(code,ignore_errors=True); shutil.rmtree(config,ignore_errors=True)
                with contextlib.suppress(Exception): run([systemctl,'daemon-reload'])
                if created_user:
                    with contextlib.suppress(Exception): run(['userdel',account])
            raise
        finally:
            if update_lock is not None: os.close(update_lock)
    print('安装完成：'+service+'；旧实例未迁移。请在此中心核实节点心跳。')
    print('Linux 主 Agent 与受管文件子进程以 root 运行；文件根仍需中心显式启用，无独立文件 service。')
    if args.pbr: print('PBR 未修改：本实例现以 root 运行，旧独立 UID 出口规则不适用；请先核实显式路由策略。')

def main():
    parser=argparse.ArgumentParser(description='Stella authenticated instance installer')
    parser.add_argument('--url',required=True); parser.add_argument('--token',default=os.environ.get('STELLA_TOKEN',''))
    parser.add_argument('--no-deps',action='store_true'); parser.add_argument('--deps',action='store_true')
    parser.add_argument('--instance',default=''); parser.add_argument('--admin-network',action='store_true'); parser.add_argument('--pbr',action='store_true')
    args=parser.parse_args()
    if args.deps and args.no_deps: raise ValueError('dependency option conflict')
    if args.deps: print('可选依赖需自行安装 python3-httpx/python3-psutil；本安装不修改全局 Python。')
    install(args)

if __name__=='__main__':
    try: main()
    except Exception:
        print('错误：中心认证、工件预检或实例安装失败；未接管旧实例。',file=sys.stderr); sys.exit(1)
STELLA_INSTANCE_INSTALLER
