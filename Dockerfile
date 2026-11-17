# Stella 一体化镜像：前端构建 + 后端运行
# 阶段 1：烤前端
ARG STELLA_NODE_BASE=node:22-slim
ARG STELLA_PYTHON_BASE=python:3.13-slim
FROM postgres:18@sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336 AS backup-pg-client
FROM ${STELLA_NODE_BASE} AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --include=dev --registry=https://registry.npmmirror.com --fetch-timeout=30000 --fetch-retries=2 --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 阶段 2：后端运行（FastAPI 直接 serve 前端 dist）
FROM ${STELLA_PYTHON_BASE}
WORKDIR /app

# ffmpeg/ffprobe generate bounded background derivatives; originals remain unchanged.
RUN python -c "from pathlib import Path; p=Path('/etc/apt/sources.list.d/debian.sources'); p.write_text(p.read_text().replace('http://deb.debian.org/debian-security','https://mirrors.ustc.edu.cn/debian-security').replace('http://deb.debian.org/debian','https://mirrors.ustc.edu.cn/debian'))" \
    && apt-get -o Acquire::Retries=2 -o Acquire::https::Timeout=30 update \
    && apt-get -o Acquire::Retries=2 -o Acquire::https::Timeout=30 install -y --no-install-recommends ffmpeg nodejs libldap2 libgssapi-krb5-2 liblz4-1 libzstd1 \
    && rm -rf /var/lib/apt/lists/*

# PG18 server requires PG18 dump/restore, never the distro's older client.
# Private libpq is used only by the child tools, not the application driver.
COPY --from=backup-pg-client /usr/lib/postgresql/18/bin/pg_dump /usr/lib/postgresql/18/bin/pg_dump
COPY --from=backup-pg-client /usr/lib/postgresql/18/bin/pg_restore /usr/lib/postgresql/18/bin/pg_restore
COPY --from=backup-pg-client /usr/lib/x86_64-linux-gnu/libpq.so.5.18 /opt/stella/pg18/lib/libpq.so.5
ENV STELLA_BACKUP_PG_BIN=/usr/lib/postgresql/18/bin STELLA_BACKUP_PG_LIB=/opt/stella/pg18/lib
RUN python -c "import os,subprocess; e=dict(os.environ,LD_LIBRARY_PATH='/opt/stella/pg18/lib'); assert b'(PostgreSQL) 18.' in subprocess.check_output(['/usr/lib/postgresql/18/bin/pg_dump', '--version'],env=e); assert b'(PostgreSQL) 18.' in subprocess.check_output(['/usr/lib/postgresql/18/bin/pg_restore', '--version'],env=e)"

# uv 装依赖（只装生产依赖，不装 test 组）
COPY pyproject.toml uv.lock ./
RUN export UV_NO_CACHE=1 \
    && pip install --no-cache-dir --index-url https://pypi.tuna.tsinghua.edu.cn/simple --timeout 30 --retries 2 uv -q \
    && uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt \
    && uv venv \
    && UV_HTTP_TIMEOUT=30 UV_HTTP_RETRIES=2 uv pip sync --index-url https://pypi.tuna.tsinghua.edu.cn/simple --require-hashes /tmp/requirements.txt

# 后端代码 + 烤好的前端
COPY . .
COPY --from=frontend /build/frontend/dist ./frontend/dist

EXPOSE 12031
CMD ["/app/.venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "12031"]
