# 10 - Schema 与 Repository：从 JSON 到数据库

> 2026.7.6 · 老婆亲手写 + 娅娅批注

---

## 一、四层架构

```
routers/    ← 接线员：收 HTTP → 调 service → 返回 JSON
services/   ← 大脑：业务逻辑
repositories/ ← 管理员：只跟数据库打交道
schemas/    ← 合同：横跨三层，定义数据长什么样
```

开发顺序：**schemas → repositories → services → routers**（从下往上，每层可独立测试）

---

## 二、Pydantic Schema

### 什么是 Pydantic

**数据校验 + 序列化引擎。** 继承 `BaseModel` 获得：

| 能力 | 例子 |
|:--|:--|
| 校验 | 传 `user_id="abc"` → 报错，UUID 格式不对 |
| 自动转换 | 传字符串 `"a1b2..."` → 自动变成 `UUID` 对象 |
| 序列化 | `.model_dump()` → 转成 dict |
| 生成文档 | FastAPI 自动生成 Swagger 请求示例 |

### Schema 放什么

| 类 | 方向 | 什么时候用 |
|:--|:--|:--|
| `XxxCreate` | 输入 ← | POST 请求体，前端发给你的 |
| `XxxRead` | 输出 → | GET 响应体，你返回给前端的 |

同一个 `.py` 文件里可以放多个类，只管「数据长什么样」。

### `from_attributes = True`

Pydantic 默认从 dict 构造对象。加了这个才能从 **SQLAlchemy ORM 对象**读取：

```python
ws = db.get(Workspace, id)           # ORM 对象（不是 dict）
result = WorkspaceRead.model_validate(ws)  # ✅ from_attributes=True 才支持
```

### `response_model=` 是什么

FastAPI 通过它知道该用哪个 schema 序列化返回值：

```python
@router.get("/{id}", response_model=WorkspaceRead)
def get_workspace(...):
    return db_ws    # ← FastAPI 自动走 WorkspaceRead.model_validate()
```

**你声明合同，FastAPI 执行转换。**

---

## 三、从 JSON 到数据库的完整链路

```python
# 前端发来 JSON
{"user_id": "a1b2...", "name": "默认"}

    ↓ FastAPI 自动解析

data = WorkspaceCreate(user_id=UUID("a1b2..."), name="默认")
#      ↑ Pydantic 对象（因为继承了 BaseModel）

    ↓ .model_dump()

{"user_id": UUID("a1b2..."), "name": "默认", "description": None}
#                                        ↑ Pydantic → 普通 dict

    ↓ ** 拆包

Workspace(user_id=UUID("a1b2..."), name="默认", description=None)
#       ↑ **dict → 关键字参数

    ↓ ORM 构造

ws = Workspace(...)
#    ↑ SQLAlchemy ORM 对象（还没进数据库）

    ↓ db.add(ws) + db.commit()

INSERT INTO workspaces (...) VALUES (...)
#   ↑ 真正写入 PostgreSQL

    ↓ db.refresh(ws)

ws 对象拿到数据库生成的默认值 → return 返回
```

**一句话：JSON → Pydantic → dict → ORM → INSERT → refresh → return。**

---

## 四、Repository 层

### Session 是什么

SQLAlchemy 的 `Session` = 一次数据库对话的上下文。FastAPI 每个请求开一个，用完关掉：

```python
def get_db():
    db = SessionLocal()
    try:
        yield db        # 借给路由用
    finally:
        db.close()      # 用完一定关
```

### 链式查询 = 组装 SQL

```python
db.query(Workspace)                        # SELECT * FROM workspaces
   .filter(Workspace.user_id == user_id)    # WHERE user_id = ?
   .offset(skip)                            # OFFSET 10
   .limit(limit)                            # LIMIT 10
   .all()                                   # 执行 → [Workspace, ...]
```

| 方法 | SQL | 作用 |
|:--|:--|:--|
| `.query(Table)` | `SELECT * FROM t` | 挑表 |
| `.filter(...)` | `WHERE ...` | 挑行 |
| `.offset(10)` | `OFFSET 10` | 跳过前 N 条（翻页用）|
| `.limit(10)` | `LIMIT 10` | 只要 N 条 |
| `.first()` | `LIMIT 1` | 拿第一条或 None |
| `.all()` | 执行查询 | 返回 list |

### OFFSET 不是删除

分页时跳过前面已看过的记录，数据库里的 100 条全在：

```
page 1: skip=0  → 第 1~10  条
page 2: skip=10 → 第 11~20 条
page 3: skip=20 → 第 21~30 条
```

---

## 五、当前进度

```
✅ schemas/workspace.py    WorkspaceCreate + WorkspaceRead
✅ repositories/workspace.py   get_by_id + list_all + create
⬜ services/workspace.py
⬜ routers/workspace.py
```
