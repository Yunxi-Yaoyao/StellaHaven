# Stella 一体化镜像：前端构建 + 后端运行
# 阶段 1：烤前端
FROM node:22-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --include=dev --registry=https://registry.npmmirror.com --fetch-timeout=30000 --fetch-retries=2 --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 阶段 2：后端运行（FastAPI 直接 serve 前端 dist）
FROM python:3.13-slim
WORKDIR /app

# ffmpeg/ffprobe generate bounded background derivatives; originals remain unchanged.
RUN python -c "from pathlib import Path; p=Path('/etc/apt/sources.list.d/debian.sources'); p.write_text(p.read_text().replace('http://deb.debian.org/debian-security','https://mirrors.tuna.tsinghua.edu.cn/debian-security').replace('http://deb.debian.org/debian','https://mirrors.tuna.tsinghua.edu.cn/debian'))" \
    && apt-get -o Acquire::Retries=2 -o Acquire::https::Timeout=30 update \
    && apt-get -o Acquire::Retries=2 -o Acquire::https::Timeout=30 install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# uv 装依赖（只装生产依赖，不装 test 组）
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir --index-url https://pypi.tuna.tsinghua.edu.cn/simple --timeout 30 --retries 2 uv -q \
    && uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt \
    && uv venv \
    && UV_HTTP_TIMEOUT=30 UV_HTTP_RETRIES=2 uv pip sync --index-url https://pypi.tuna.tsinghua.edu.cn/simple --require-hashes /tmp/requirements.txt

# 后端代码 + 烤好的前端
COPY . .
COPY --from=frontend /build/frontend/dist ./frontend/dist

EXPOSE 12031
CMD ["/app/.venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "12031"]
