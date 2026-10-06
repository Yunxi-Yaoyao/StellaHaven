#!/usr/bin/python3 -I
"""Privileged Docker gateway. Install root:root 0755 outside agent-writable dirs."""
import subprocess
import sys
import re

DOCKER = "/usr/bin/docker"
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/var/empty",
       "LANG": "C", "LC_ALL": "C", "DOCKER_CONFIG": "/etc/stella-agent/docker"}


def docker_args(args):
    if args == ['ps']:
        return ['ps', '-a', '--format', '{{json .}}']
    if (len(args) == 2 and args[0] in ('inspect', 'start', 'stop', 'restart')
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', args[1])):
        if args[0] == 'inspect':
            return ['inspect', '--type', 'container', args[1]]
        return args
    if (len(args) == 3 and args[0] == 'logs'
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', args[1])
            and re.fullmatch(r'[1-9][0-9]{0,2}', args[2]) and int(args[2]) <= 500):
        return ['logs', '--tail', args[2], args[1]]
    raise ValueError('request refused')


def main():
    try:
        args = docker_args(sys.argv[1:])
        result = subprocess.run([DOCKER, '--host', 'unix:///var/run/docker.sock'] + args,
                                shell=False, env=ENV, cwd='/', stdin=subprocess.DEVNULL,
                                timeout=65)
        return result.returncode
    except ValueError:
        print('stella Docker helper: request refused', file=sys.stderr)
        return 2
    except (OSError, subprocess.TimeoutExpired):
        print('stella Docker helper: command failed or timed out', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
