#!/bin/sh
# Digest-preserving prewarm AFTER admission/auth and BEFORE the first app solve.
# The public postgres:18 index in Dockerfile remains unchanged; this canonical
# linux/amd64 manifest is its exact descriptor, not a replacement app source.
set -eu
set +x
[ "$(id -u)" = 1000 ] || exit 1
[ ! -S /var/run/docker.sock ] && [ ! -S /run/docker.sock ] || exit 1
: "${DOCKER_CONFIG:?inherit existing job-scoped auth directory}"
: "${BUILDKITD_FLAGS:?inherit existing reviewed rootless flags}"
[ -f "$DOCKER_CONFIG/config.json" ] || exit 1
umask 077
# Outside the checkout regardless of a caller's TMPDIR; never in app context.
D=$(mktemp -d /tmp/stella-pg18-prewarm.XXXXXX)
trap 'rm -rf "$D"' EXIT HUP INT TERM
mkdir -p "$D/context" "$D/out"
printf '%s\n' \
 'FROM gitlab-registry.xiya.live/yaoyao/stellahaven/ci-base/postgres@sha256:885953109528ad3dfc90362b1a6f50a78620b5315be19f187753d267e484dc5b AS source' \
 'FROM scratch' \
 'COPY --from=source /usr/lib/postgresql/18/bin/pg_dump /pg_dump' \
 'COPY --from=source /usr/lib/postgresql/18/bin/pg_restore /pg_restore' \
 'COPY --from=source /usr/lib/x86_64-linux-gnu/libpq.so.5.18 /libpq.so.5.18' \
 > "$D/context/Dockerfile"
# Inherit the existing per-job worker/content store, auth and process sandbox.
buildctl-daemonless.sh build --frontend dockerfile.v0 \
 --local context="$D/context" --local dockerfile="$D/context" \
 --output "type=local,dest=$D/out"
# No push/shared cache; any failure stops the caller before the original solve.
