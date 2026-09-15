#!/usr/bin/env python3
"""Read-only live nonproduction validation; never deploy or promote."""
import argparse
import json
from pathlib import Path
from release import Refused, SCOPE, SSHTransport, plan


def validate_inventory(inventory):
    if inventory.get('scope') != SCOPE or inventory.get('environment') != 'nonproduction':
        raise Refused('nonproduction isolated inventory required')
    if inventory.get('current_primary') not in ('nyarch', 'nas'):
        raise Refused('operator inventory current_primary required')
    return inventory


def validate(inventory, transport, image):
    validate_inventory(inventory)
    snapshot = transport.snapshot()
    result = plan(snapshot, image)
    if result['primary'] != inventory['current_primary']:
        raise Refused('live primary changed from inventory; operator review required')
    result.update(status='read-only-validated', deployment_authorized=False,
                  fencing_status='not-accepted', apply_status='blocked')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', required=True)
    parser.add_argument('--ssh-config', required=True)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    try:
        inventory = validate_inventory(json.loads(Path(args.inventory).read_text()))
        transport = SSHTransport(inventory['hosts'], args.ssh_config)
        print(json.dumps(validate(inventory, transport, args.image), indent=2))
    except Exception as exc:
        print(json.dumps({'status': 'blocked', 'error': type(exc).__name__}))
        raise SystemExit(2)
