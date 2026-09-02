#!/bin/bash
# Patroni 启动入口：从环境变量渲染 patroni.yml，然后启动
# 必需 env: PG_NODE_NAME, PG_NODE_IP, ETCD_HOSTS(逗号分隔), PG_PASSWORD_SUPER, PG_PASSWORD_REPL
set -e

DATA_DIR=/var/lib/postgresql/data/pgdata
mkdir -p "$DATA_DIR"
chown -R postgres:postgres /var/lib/postgresql/data
chmod 0700 "$DATA_DIR"

cat > /etc/patroni.yml <<EOF
scope: stella-pg
name: ${PG_NODE_NAME}
namespace: /db/

log:
  level: INFO

etcd3:
  hosts: ${ETCD_HOSTS}

restapi:
  listen: 0.0.0.0:8008
  connect_address: ${PG_NODE_IP}:8008

bootstrap:
  dcs:
    ttl: 90
    loop_wait: 15
    retry_timeout: 30
    maximum_lag_on_failover: 33554432
    postgresql:
      use_pg_rewind: true
      parameters:
        max_connections: 100
        shared_buffers: 256MB
        wal_log_hints: 'on'
  initdb:
    - encoding: UTF8
    - locale: C.UTF-8
  pg_hba:
    - host replication replicator 0.0.0.0/0 scram-sha-256
    - host all all 10.42.0.0/16 scram-sha-256
    - host all all 10.66.0.0/24 scram-sha-256
    - host all all 127.0.0.1/32 scram-sha-256
  users:
    stalla:
      password: ${PG_PASSWORD_APP}
      options:
        - createdb

postgresql:
  listen: 0.0.0.0:5432
  connect_address: ${PG_NODE_IP}:5432
  data_dir: ${DATA_DIR}
  bin_dir: /usr/lib/postgresql/18/bin
  authentication:
    superuser:
      username: postgres
      password: ${PG_PASSWORD_SUPER}
    replication:
      username: replicator
      password: ${PG_PASSWORD_REPL}
  callbacks:
    on_role_change: /usr/local/bin/label-pod.sh

tags:
  nofailover: false
  noloadbalance: false
EOF

# 角色变化回调：给 pod 打标签，让 k8s Service 能找到主库
cat > /usr/local/bin/label-pod.sh <<'CB'
#!/bin/bash
# Patroni 回调参数: $1=action $2=role $3=cluster_name
ROLE=$2
[ "$ROLE" = "master" ] || [ "$ROLE" = "primary" ] && LABEL="primary" || LABEL="replica"
kubectl label pod "$HOSTNAME" -n stella "pg-role=$LABEL" --overwrite 2>&1 | logger -t patroni-callback
CB
chmod +x /usr/local/bin/label-pod.sh

exec gosu postgres patroni /etc/patroni.yml
