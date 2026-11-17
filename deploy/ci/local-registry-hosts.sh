#!/bin/sh
# Project job only: canonical TLS/JWT names on verified Nyarch WG ingress.
# Never change shared Runner, daemon policy or global DNS.
set -eu
while read -r addr names; do
  for n in $names; do
    case "$n" in gitlab.xiya.live|gitlab-registry.xiya.live) exit 42;; esac
  done
done < /etc/hosts
printf '\n10.66.0.2 gitlab-registry.xiya.live\n10.66.0.2 gitlab.xiya.live\n' >> /etc/hosts
getent hosts gitlab-registry.xiya.live
getent hosts gitlab.xiya.live
