#!/usr/bin/env python3
"""Render NEW configuration only. Never contact Docker, etcd or a database."""
import argparse
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit

from release import SCOPE, Refused, image_ref


def render(output, *, node, node_ip, app_image, pg_image, etcd_hosts, profile='manual'):
    if profile != 'manual':
        raise Refused('automatic profile unavailable: quorum and hardware fencing not accepted')
    if node not in ('nyarch', 'nas'):
        raise Refused('only two local data nodes supported')
    ipaddress.IPv4Address(node_ip)
    image_ref(app_image)
    image_ref(pg_image)
    if len(set(etcd_hosts)) != 3:
        raise Refused('three independently operated etcd voting endpoints required (not proof of quorum)')
    for host in etcd_hosts:
        parsed = urlsplit(host)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise Refused('etcd endpoint must be https://host:port without credentials')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name in ('compose.env', 'patroni.json'):
        if (output / name).exists():
            raise FileExistsError(output / name)
    config = {
        'scope': SCOPE, 'namespace': '/local-ha/', 'name': node,
        'etcd3': {'hosts': ','.join(urlsplit(h).netloc for h in etcd_hosts), 'protocol': 'https',
                  'cacert': '/run/secrets/etcd-ca.crt', 'cert': '/run/secrets/etcd-client.crt',
                  'key': '/run/secrets/etcd-client.key'},
        'restapi': {'listen': '0.0.0.0:24808', 'connect_address': f'{node_ip}:24808',
                    'allowlist': ['127.0.0.1', '10.66.0.2', '10.66.0.3']},
        'postgresql': {'listen': '0.0.0.0:24532', 'connect_address': f'{node_ip}:24532',
                       'data_dir': '/var/lib/postgresql/local-ha/pgdata', 'bin_dir': '/usr/lib/postgresql/18/bin',
                       'use_pg_rewind': False, 'remove_data_directory_on_rewind_failure': False,
                       'remove_data_directory_on_diverged_timelines': False,
                       'authentication': {'superuser': {'username': 'postgres'}, 'replication': {'username': 'replicator'}}},
        'watchdog': {'mode': 'off'},
        'tags': {'nofailover': True, 'noloadbalance': True},
    }
    root = f'/srv/stella-local-ha/{node}'
    env = {'COMPOSE_PROJECT_NAME': f'stella-local-ha-{node}', 'LOCAL_HA_NODE': node,
           'APP_IMAGE': app_image, 'PG_IMAGE': pg_image, 'NODE_ROOT': root,
           'CONFIG_DIR': str(output), 'HA_SCRIPTS': str(Path(__file__).resolve().parent),
           'PG_NODE_IP': node_ip, 'LOCAL_HA_PROFILE': profile,
           'LOCAL_HA_ENABLE_DATABASE': 'no', 'LOCAL_HA_ENABLE_APP': 'no'}
    if any('\n' in value or '$' in value or "'" in value for value in env.values()):
        raise Refused('unsafe dotenv value')
    with (output / 'patroni.json').open('x') as handle:
        json.dump(config, handle, indent=2)
        handle.write('\n')
    with (output / 'compose.env').open('x') as handle:
        handle.write(''.join(f"{key}='{value}'\n" for key, value in env.items()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--node', choices=['nyarch', 'nas'], required=True)
    parser.add_argument('--node-ip', required=True)
    parser.add_argument('--app-image', required=True)
    parser.add_argument('--pg-image', required=True)
    parser.add_argument('--etcd-hosts', nargs=3, required=True)
    parser.add_argument('--profile', default='manual')
    args = vars(parser.parse_args())
    output = args.pop('output')
    render(output, **args)
    print(json.dumps({'status': 'rendered-not-started', 'output': str(output)}))
