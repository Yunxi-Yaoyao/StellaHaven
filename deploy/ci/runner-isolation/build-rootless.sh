#!/bin/sh
# Used ONLY by the separately reviewed candidate CI, never by the current CI.
set -eu
set +x
[ "$(id -u)" = 1000 ] || { echo 'rootless UID required' >&2; exit 1; }
[ ! -S /var/run/docker.sock ] && [ ! -S /run/docker.sock ] || exit 1
[ -z "${STELLA_PRODUCTION_SSH_KEY:-}${STELLA_PRODUCTION_INVENTORY:-}${DATABASE_URL:-}${KUBECONFIG:-}" ] || exit 1
[ "${#CI_COMMIT_SHA}" = 40 ] || exit 1
case "$CI_COMMIT_SHA" in *[!0-9a-f]*) exit 1;; esac
# Conservative admission budget (not a measured build requirement): 6GiB working
# space + 2GiB reserve on BOTH checkout and rootless worker filesystems. Never prune.
if ! df -Pk . "$HOME/.local/share/buildkit" | awk 'NR > 1 { n++; if ($4 < 8388608) bad=1 } END { exit (bad || n != 2) }'; then
  echo 'BLOCKED_SPACE: require 8GiB free for full app+PG build; no automatic cleanup' >&2
  exit 1
fi
: "${CI_REGISTRY_USER:?job registry identity required}"
: "${CI_REGISTRY_PASSWORD:?job registry credential required}"
REGISTRY=gitlab-registry.xiya.live/yaoyao/stellahaven
umask 077
AUTH_DIR=$(mktemp -d /tmp/stella-build-auth.XXXXXX)
OUT_DIR=$(mktemp -d /tmp/stella-build-output.XXXXXX)
cleanup() { rm -rf "$AUTH_DIR" "$OUT_DIR"; }
trap cleanup EXIT HUP INT TERM
export DOCKER_CONFIG="$AUTH_DIR"
# Job-scoped credential only; no persistent credential store, no xtrace.
auth=$(printf '%s:%s' "$CI_REGISTRY_USER" "$CI_REGISTRY_PASSWORD" | base64 | tr -d '\n')
printf '{"auths":{"gitlab-registry.xiya.live":{"auth":"%s"}}}\n' "$auth" > "$AUTH_DIR/config.json"
unset auth CI_REGISTRY_PASSWORD
# The owned rootless worker uses the kernel overlayfs snapshotter verified on
# this runner. Native snapshots copy entire parents and exhausted the disk.
# Runner bridge/egress and process-sandbox policy remain external configuration.
export BUILDKITD_FLAGS='--oci-worker-snapshotter=overlayfs --oci-worker-gc=false'
# Warm only this job's worker before the unchanged public-source app solve.
sh deploy/ci/runner-isolation/prewarm-before-build.sh
rm -f .env .env.*
buildctl-daemonless.sh build --frontend dockerfile.v0 \
  --local context=. --local dockerfile=. \
  --opt build-arg:STELLA_NODE_BASE=gitlab-registry.xiya.live/yaoyao/stellahaven/ci-base/node@sha256:efd0ab5780c2d9ab1f0f869571a00d5edb17793bff4cce4a2792e3eb0ffc7562 \
  --opt build-arg:STELLA_PYTHON_BASE=gitlab-registry.xiya.live/yaoyao/stellahaven/ci-base/python@sha256:8fb4cfa1a2616d7b8e0c2175cc6ad68f5729c34ea8488c0b360d2934b7be9024 \
  --output "type=image,name=$REGISTRY:$CI_COMMIT_SHA,push=true" \
  --metadata-file "$OUT_DIR/app.json"
buildctl-daemonless.sh build --frontend dockerfile.v0 \
  --local context=. --local dockerfile=. --opt filename=Dockerfile.pg \
  --opt build-arg:STELLA_POSTGRES_BASE=gitlab-registry.xiya.live/yaoyao/stellahaven/ci-base/postgres@sha256:9551dd5bf356409a21b31248f49b33bba9bb1877365f3a7e933aecd9af3cf52d \
  --output "type=image,name=$REGISTRY/pg-patroni:$CI_COMMIT_SHA,push=true" \
  --metadata-file "$OUT_DIR/pg.json"
# Return raw metadata to a no-secret Python validation job; never scrape logs or
# invent RepoDigests from image IDs. There is deliberately no latest tag.
mkdir -p .ci-build-receipt
cp "$OUT_DIR/app.json" .ci-build-receipt/app.json
cp "$OUT_DIR/pg.json" .ci-build-receipt/pg.json
