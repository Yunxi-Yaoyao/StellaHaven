# Stella 一体化镜像：前端构建 + 后端运行
# 阶段 1：烤前端
FROM node:22-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 阶段 2：后端运行（FastAPI 直接 serve 前端 dist）
FROM python:3.13-slim
WORKDIR /app

# uv 装依赖（只装生产依赖，不装 test 组）
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv -q && uv sync --frozen --no-dev

# 后端代码 + 烤好的前端
COPY . .
COPY --from=frontend /build/frontend/dist ./frontend/dist

EXPOSE 12031
CMD ["/app/.venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "12031"]
