#!/usr/bin/env python3
"""Remote/local read-only ingress receipt. Never emit raw nginx/journal lines."""
import collections
from datetime import datetime, timezone
import json
import pathlib
import re
import subprocess

def run(*args):
    r = subprocess.run(args, capture_output=True, text=True, timeout=25)
    return r.returncode, r.stdout + r.stderr

def main():
    rc, config = run('nginx', '-T')
    selected = []
    # Config file sections, keep only non-secret routing directives for these domains.
    for section in config.split('# configuration file ')[1:]:
        if not re.search(r'server_name[^;]*(?:immich\.xiya\.live|stella\.xiya\.live|\*\.xiya\.live|app-)', section):
            continue
        selected.append({'file': section.split(':\n', 1)[0], 'directives': [line.strip() for line in section.splitlines()
                         if re.match(r'\s*(server_name|listen|ssl_certificate|proxy_pass|proxy_set_header\s+(Host|Connection|Upgrade)|proxy_read_timeout|proxy_connect_timeout|proxy_http_version|proxy_buffering|sub_filter|location)(?:\s|$)', line)
                         and '?' not in line and 'Authorization' not in line and 'Cookie' not in line]})
    certs=[]
    for path in sorted(set(re.findall(r'^\s*ssl_certificate\s+([^;]+);',config,re.M))):
        c_rc, c = run('openssl', 'x509', '-in', path, '-noout', '-enddate', '-ext', 'subjectAltName')
        certs.append({'file':path,'rc':c_rc,'public_certificate':c.strip()})
    journal = {}
    for unit in ['frps','frpc@hk','frpc@tyo','frpc@stella-ha']:
        jrc, text = run('journalctl', '-u', unit, '--since', '24 hours ago', '--no-pager')
        journal[unit] = {'rc': jrc, 'lines': len(text.splitlines()), 'counts': {p: text.count(p) for p in [
            'write timeout','i/o timeout','login to server success','start proxy success',
            'listener is closed','use of closed network connection','already exists','stella-runtime-nyarch','stella-runtime-nas']}}
    error_counts = {}
    for log in pathlib.Path('/var/log/nginx').glob('*error*log'):
        # Fixed tail byte budget; never transmit request strings or query tokens.
        with log.open('rb') as f:
            f.seek(max(0, log.stat().st_size - 262144))
            text = f.read().decode(errors='replace')
        if 'immich' not in log.name and 'immich.xiya.live' not in text:
            continue
        immich = [x for x in text.splitlines() if 'immich.xiya.live' in x or 'immich' in log.name]
        error_counts[log.name] = {'sample_bytes': min(log.stat().st_size, 262144), 'lines': len(immich),
            'categories': {p: sum(p in x for x in immich) for p in ['upstream timed out','connect() failed','upstream prematurely closed connection','connection reset by peer','no live upstreams']},
            'upstream_hosts': sorted(set(re.findall(r'upstream: "https?://([^/" ]+)', '\n'.join(immich))))}
    lrc,listeners=run('ss','-ltn')
    ports = sorted(set(int(p) for p in re.findall(r':(\d+)\s',listeners) if int(p) in [443,80,17000,11198,12031,12020,25131]))
    frpc=[]
    import tomllib
    for conf in pathlib.Path('/opt/frpc/conf').glob('*.toml'):
        if conf.name not in {'stella-ha.toml','hk.toml','tyo.toml'}: continue
        try:
            data=tomllib.loads(conf.read_text())
            frpc.append({'instance':conf.stem, 'serverAddr':data.get('serverAddr'), 'serverPort':data.get('serverPort'),
                         'proxies':[{k:p.get(k) for k in ['name','localIP','localPort','remotePort','healthCheck']} |
                                    {'group':p.get('loadBalancer',{}).get('group')} for p in data.get('proxies',[]) if p.get('remotePort') in [12020,12031]]})
        except (ValueError, OSError): pass
    print(json.dumps({'timestamp':datetime.now(timezone.utc).isoformat(), 'nginx_rc':rc, 'routes':selected,'certificates':certs,
                      'listeners':ports, 'journal':journal,'nginx_error_counts':error_counts,'frpc':frpc},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
