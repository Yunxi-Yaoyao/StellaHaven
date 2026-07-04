# StellaHaven ✨

个人知识管理系统 · Personal Knowledge Workspace

> 还在搭骨架 — FastAPI + PostgreSQL，慢慢长成它该有的样子。

---

## 技术栈

| 层 | 技术 |
|:--|:--|
| 框架 | FastAPI |
| ORM | SQLAlchemy 2.0 |
| 迁移 | Alembic |
| 数据库 | PostgreSQL 18 |
| 配置 | Pydantic Settings |
| 包管理 | uv |

## 项目结构

```
StellaHaven/
├── app/
│   ├── config.py          # 配置（Settings, database_url）
│   ├── database.py        # engine, session, Base
│   ├── models/            # 数据库模型
│   ├── schemas/           # Pydantic 请求/响应模型
│   ├── routers/           # API 路由
│   ├── services/          # 业务逻辑
│   └── repositories/      # 数据访问层
├── alembic/               # 数据库迁移
├── tests/                 # 测试
└── main.py                # 入口
```

## 快速开始

```bash
# 1. 克隆
git clone git@github.com:BLUEONEM/StellaHaven.git
cd StellaHaven

# 2. 装依赖
uv sync

# 3. 配环境变量（创建 .env）
echo 'POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=stalla
POSTGRES_PASSWORD=your_password
POSTGRES_DB=stella' > .env

# 4. 跑迁移
alembic upgrade head

# 5. 启动
uv run uvicorn main:app --reload --port 12031
```

## 进度

- [x] 项目骨架 + 配置
- [x] 数据库连接 + Alembic
- [ ] 用户模型
- [ ] 文档模型
- [ ] API 路由
- [ ] 前端

---

*Built with ☕ and late-night coding sessions.*
