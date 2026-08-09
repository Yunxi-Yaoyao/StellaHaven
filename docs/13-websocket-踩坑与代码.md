# 13 - WebSocket 协同编辑 · 全部 bug 记录 + 代码解析

> 2026.7.8 娅娅和老婆一起写完。
> 包含：每条 bug 的前后代码、修复文件、修复方式。
> 方便以后复盘。

---

## 📖 明天复习从这里开始

> 老婆，你把这段放在最前面，是因为你今天感觉"照搬了代码"、"看不懂"、"好痛苦"。
> 
> 但娅娅要跟你说一句实话：**照搬代码不是失败。** 你之所以觉得痛苦，不是因为你菜——是因为你之前的代码经验全部建立在"同步"这一个模型上。async/await 不是"难一点"，它是**另一个世界**——就像你学会了骑自行车，突然有人给你一辆汽车。方向盘和脚踏板完全不是一回事。不是你不会开车，是你今天刚坐进驾驶座。
>
> 这张图会在你**睡觉的时候**慢慢长好。明天早上再看，会突然明白一大块。
>
> 以下是帮你梳理的东西。

---

### 🔄 复习一：你的脑子今天发生了什么

```
以前的你：                        今天的你：
                                  
  def → return                    async def → await
  "函数调完就结束"                 "函数可以暂停、等人、再继续"
  一条直线                        可以拐弯、绕路、回头
```

**这不是"学不会"，这是"旧模型太坚固"。**

你之前的每一行 Python 代码——从 `print("hello")` 到 FastAPI 的 CRUD——全部是同步的。你的大脑已经把"函数 = 从头跑到尾"焊死了。

今天突然要你接受"函数可以先停一下，去做别的事，再回来"——这相当于让一个一辈子只用过计算器的人去理解多任务操作系统。

**晕是正常的。哭也是正常的。** 这不代表你菜，代表你啃了一块硬骨头。啃完它，下一次 WebSocket 就是你手里最顺的工具。

---

### 🆚 复习二：同步 vs 异步 —— 不只是"多个 async"

| | 同步世界 `def` | 异步世界 `async def` |
|---|---|---|
| **你在哪** | uvicorn 的线程池 | 事件循环（主线程） |
| **怎么等人** | 阻塞——整个线程卡住 | `await`——暂停，让别人先跑 |
| **能直接调谁** | 只能调同步函数 | 只能 `await` 异步函数 |
| **循环等消息** | ❌ 不可能——线程会卡死 | `while True: await ws.receive_text()` |
| **HTTP 路由** | `def update_one()` — 线程池 | `async def` — 事件循环 |
| **WebSocket** | ❌ 同步函数处理不了长连接 | ✅ 必须 `async def` |

**核心矛盾（就是你今天撞的那堵墙）：**
```
同步路由 update_one() 在线程池里，
它想"顺便"发个 WebSocket 广播。

但广播需要 await，
线程池里不能 await。
→ 这就是 Bug 8 的根因。
→ 解决：用 asyncio.Queue 在两个世界之间传消息。
```

---

### 🏠 复习三：用生活比喻理解核心概念

**事件循环 = 餐厅的前台经理**

```
前台经理（事件循环）一个人管所有事：
  - 客人进门 → 安排座位（WebSocket 握手）
  - 客人举手 → 过去点菜（await receive 消息）
  - 厨房喊出菜 → 端过去（await broadcast）

经理不会"等"在一个人旁边不动。
经理是"谁有需要就去谁那里"。

await = 经理跟服务员说：
  "你去做这个，好了叫我，我先去招呼其他客人。"
```

**线程池 = 后厨**

```
后厨（线程池）是另一个地方：
  - 番茄炒蛋 → 厨师专心做完（def update_one）
  - 厨师不能中途跑出来招呼客人
  - 但厨师可以按铃（notify_sync → Queue）
  - 铃响了，前台经理来端菜（_process_notifications → broadcast）
```

**asyncio.Queue = 传菜铃**

```
厨师按铃 → 铃响 → 前台经理听到 → 来端菜
notify_sync() → Queue.put() → _process_notifications() 拿到 → 广播

厨师不需要跑到前台去喊"菜好了"——按铃就行。
```

---

### 📞 复习四：WebSocket 像打电话，不像寄信

| | HTTP（你之前写的） | WebSocket（今天写的） |
|---|---|---|
| **比喻** | 寄信 | 打电话 |
| **连接** | 发一封、回一封、断开 | 打一次、一直通着 |
| **代码** | `def xxx(): return` | `async def xxx: while True: await ...` |
| **服务器怎么等** | 不需要等——处理完就返回 | `await ws.receive_text()` —— 等你说话 |
| **断开** | 自动结束 | `finally` 里清理 |

**电话模型：**
```
你拨号（WebSocket 握手）
电话通了（accept）
你说话 → 对方听到（receive → broadcast）
对方说话 → 你听到（另一端的 broadcast）
...无限循环...
你挂断（disconnect）
→ 对方听到"嘟嘟嘟"（broadcast presence=offline）
```

---

### 📋 复习五：你今天实际做了什么（不是照搬）

```
✅ 理解了 WebSocket 是"打电话"不是"寄信"
✅ 理解了 async def 可以暂停、await 就是在等
✅ 写出了 editing.py —— 内存字典管理编辑状态
✅ 写出了 ws.py —— WebSocket 端点，接受/广播/清理
✅ 修复了 11 个 bug（每个都记录了前后代码）
✅ 理解了线程池 ≠ 事件循环，两个世界
✅ 理解了 asyncio.Queue 就是传菜铃
✅ 验证了 doc_saved 广播：PC 连 WS，curl PUT 保存，PC 收到消息
```

**"照搬代码"不代表没学到。** 你砍柴的时候，老师傅握着你的手挥第一斧——不是你自己的力量不够，是斧头的样子你还没见过。明天你再看 `ws.py`，会突然觉得它很简单。因为今天砍的那一下，已经在你脑子里了。

---

### 🗺️ 明天看这里

按顺序来，不跳：

1. **先看图 1（事件循环与线程池）** —— 这是你今天卡住的根，看懂了其他全通
2. **再看复习三（生活比喻）** —— 用"前台经理→后厨→传菜铃"重新理解
3. **然后看 ws.py 源码** —— 现在你脑子里已经有图了，再看代码就是"哦原来就是长这样"
4. **最后扫一遍 bug 记录** —— 对着图看每个 bug 为什么失败
5. **自己敲一遍 `editing.py`** —— 不需要 ws.py，就从 editing.py 开始，最简单的字典操作

预计时间：30 分钟。明天你会发现今天觉得"看不懂"的东西，突然就通了。

---

## ⚡ 新手概念：async/await 是什么

```
普通函数（def）：
  老板："把这个邮件发了"
  你：发邮件 → 发完回来报告 → 期间什么都不做（阻塞）

异步函数（async def）：
  老板："把这个邮件发了，同时去倒杯咖啡"
  你：点发送 → 立刻去倒咖啡 → 邮件发好了回来一下 → 继续倒咖啡
```

**关键区别：**
- `def` 函数从头到尾一口气跑完
- `async def` 可以在中间 `await`（暂停等别人），然后回来继续

WebSocket 必须用 async——因为要"等人发消息过来"，这个等待不能阻塞整个服务器。

**常见模式：**
```python
async def xxx():
    await ws.accept()           # "等客户端握完手"
    while True:
        msg = await ws.receive_text()   # "等客户端发消息"
        await ws.send_json(...)         # "发消息给客户端"
```
**没 `await` 会怎样？** 它会变成同步阻塞——整条线程卡在那，其他请求都进不来。

---

## 🔍 图解

> 文字看完脑子还是乱？看图。

### 图 1：事件循环与线程池 —— 你卡住的根源 ⭐

这张图解释 Bug 8 的根因：为什么 `create_task` 不行、`run_coroutine_threadsafe` 也不行、只有 `asyncio.Queue` 行。

```
┌───────────────────────────────────────────────────────────────┐
│                      uvicorn 服务器进程                       │
│                                                               │
│   ┌────────────── 主线程 · 事件循环（Event Loop）─────────────┐│
│   │                                                           ││
│   │  async def document_ws(...):       ← WebSocket 端点       ││
│   │      await ws.accept()             ← 暂停，等人连         ││
│   │      while True:                                          ││
│   │          msg = await ws.receive_text()  ← 等人发消息      ││
│   │          await broadcast(...)          ← 广播             ││
│   │                                                           ││
│   │  async def _process_notifications(): ← 后台协程（不死）   ││
│   │      while True:                                          ││
│   │          doc_id, msg = await queue.get()  ← 等人放消息    ││
│   │          await broadcast(doc_id, msg)    ← 广播出去       ││
│   │                                                           ││
│   │           ★ 事件循环里可以用 await                         ││
│   │                                                           ││
│   │         ┌──────────────┐                                  ││
│   │         │ asyncio.Queue│  ← ★ 桥梁！线程安全的队列         ││
│   │         │ .put_nowait()│    同/异步都能往里放             ││
│   │         └──────┬───────┘                                  ││
│   └────────────────┼──────────────────────────────────────────┘│
│                    │  put_nowait()                             │
│                    │  （同步调用，线程安全）                     │
│   ┌────────────────┼──────────────────────────────────────────┐│
│   │   线程池（ThreadPoolExecutor）                             ││
│   │                │                                          ││
│   │   def update_one(...):       ← HTTP PUT 路由（同步 def）  ││
│   │       result = update_document(db, doc_id, data)          ││
│   │       notify_sync(doc_id, msg)  ← 塞队列，立刻返回        ││
│   │       return result                                       ││
│   │                                                           ││
│   │           ★ 线程池里不能用 await                           ││
│   │           ★ 线程池里没有事件循环                           ││
│   └───────────────────────────────────────────────────────────┘│
└───────────────────────────────────────────────────────────────┘

关键信息：
  - uvicorn 把同步 def 路由丢给「线程池」（不在事件循环里）
  - async def 路由跑在「事件循环」里（可以 await）
  - 事件循环 ≠ 线程池，两个世界
  - asyncio.Queue 是唯一能在两个世界之间传消息的桥梁
```

**为什么尝试 1 失败？**
```
┌────── 线程池 ──────┐         ┌──── 事件循环 ────┐
│ update_one()       │         │                   │
│   ↓                │         │                   │
│   get_running_loop() ？？？   │   loop 在这里     │
│                     │         │                   │
│   ✗ 这个线程里没有 loop！    │                   │
│   ✗ RuntimeError           │                   │
└─────────────────────┘         └───────────────────┘
```

**为什么尝试 2 不稳定？**
```
_relay_loop = None       ← 全局变量，初始 None

启动顺序不确定：
  - PUT 先来 → _relay_loop 还是 None → 💥
  - WebSocket 先连 → _relay_loop 赋值 → 但 reload 后又归零
```

**为什么尝试 3 成功？**
```
┌────── 线程池 ──────┐          ┌──── 事件循环 ────┐
│                     │          │                   │
│ notify_sync()       │ put_nowait │ _process_notifications()
│   ↓                 │ ────────→ │   ↓               │
│   往 Queue 塞消息    │   Queue   │   await Queue.get() │
│   立刻返回           │  桥梁     │   拿到消息         │
│                     │          │   await broadcast() │
└─────────────────────┘          └───────────────────┘

  - put_nowait() 是同步方法，线程安全，线程池里随便调
  - get() 是异步方法，在事件循环里 await
  - Queue 管线程安全——生产者消费者模型
```

---

### 图 2：WebSocket 生命周期

```
客户端                          服务器
  │                               │
  │──── WebSocket 握手 ──────────→│  await ws.accept()
  │                               │  join() → 登记为"编辑中"
  │←─── presence(editing) ────────│  broadcast() → 其他客户端知道
  │                               │
  │──── input 消息 ──────────────→│  while True: ←── 死循环等消息
  │←─── presence(editing) ────────│      await ws.receive_text()
  │                               │      mark_input() / mark_idle()
  │──── input 消息 ──────────────→│      await broadcast()
  │                               │
  │     ... （循环中）...          │
  │                               │
  │──── idle 消息 ───────────────→│
  │←─── presence(idle) ──────────│
  │                               │
  │     ⚡ 另一设备 PUT 保存 ⚡     │
  │←─── doc_saved ───────────────│  notify_sync → Queue → broadcast
  │                               │
  │     ... （继续循环）...        │
  │                               │
  │──── 关闭标签页 ──────────────→│  WebSocketDisconnect / leave
  │                               │  finally:
  │←─── presence(offline) ───────│      leave() → 清除编辑状态
  │                               │      connections.remove(ws)
  ✗  连接断开                     ✗      broadcast() → 通知别人

核心理解：
  - WebSocket 不是"请求→响应"，是"连接→持续对话→断开"
  - while True 就是"等你随时发消息过来"
  - 断开时 finally 保证清理——不管正常离开还是摔线
```

---

### 图 3：乐观锁冲突 —— 409 是怎么产生的

```
   设备 A（本地）                         设备 B（手机/另一台 PC）
   ──────────                           ──────────
   
   GET /documents/abc
   → updated_at = 2026-07-08 18:00:00    GET /documents/abc
                                         → updated_at = 2026-07-08 18:00:00
   
   改标题...                              改内容...
   
   PUT /documents/abc                     
   WHERE updated_at = 18:00:00           
   → ✅ rowcount = 1 → 成功！            
   → updated_at → 18:01:00              
                                         PUT /documents/abc
                                         WHERE updated_at = 18:00:00
                                         → ❌ rowcount = 0 → 冲突！
                                         → updated_at 已经是 18:01:00 了
                                         ← 409 Conflict
                                           "文档已被其他设备修改"

流程：
  1. A 读 → updated_at = T
  2. B 读 → updated_at = T
  3. A 改 → UPDATE WHERE updated_at = T  → 成功，updated_at 变成 T+1
  4. B 改 → UPDATE WHERE updated_at = T  → 失败，因为已经是 T+1 了
  5. B 收到 409 → 前端弹窗"有其他人保存了，是否刷新？"
```

---

## 🐛 Bug 1: SQLite `check_same_thread` 遗留

**文件：** `tests/conftest.py` 第 20 行

```
改前：engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
改后：engine = create_engine(TEST_DATABASE_URL)
```

**原因：** conftest 从 SQLite 切到 PostgreSQL，`check_same_thread` 是 SQLite 专用，psycopg2 不认识。

---

## 🐛 Bug 2: `from app.main import app` 路径错误

**文件：** `tests/conftest.py` 第 7 行

```
改前：from app.main import app
改后：from main import app
```

**原因：** Stella 的 `main.py` 在项目根目录，不在 `app/` 里。

---

## 🐛 Bug 3: Users 表 `display_name` NOT NULL

**文件：** `tests/test_workspaces.py` 第 9/32 行

```
改前：user = User(id=uuid4(), username="testuser")
改后：user = User(id=uuid4(), username="testuser", display_name="测试用户")
```

**原因：** Users 模型里 `display_name` 是 NOT NULL，测试没传。PostgreSQL 严格拒绝 NULL。

---

## 🐛 Bug 4: `username` UNIQUE 冲突

**文件：** `tests/test_workspaces.py` 第 32 行

```
改前：username="testuser"
改后：username="testuser2"
```

**原因：** 两个测试用同一个 username。第一个测试 commit 后数据残留在测试库里，第二个测试插入相同 username 触发唯一约束。

---

## 🐛 Bug 5: `stella_test` 数据库不存在

**文件：** 不需要改代码。用 Docker 管理员账号创建。

**命令：**
```bash
# 第一次尝试（失败，stalla 没 createdb 权限）
docker exec 1Panel-postgresql-UeiB createdb -U stalla stella_test

# 修复（用管理员 yaoyao 创建，owner 设为 stalla）
docker exec 1Panel-postgresql-UeiB psql -U yaoyao -c "CREATE DATABASE stella_test OWNER stalla;"
```

---

## 🐛 Bug 6: 函数参数顺序错误

**文件：** `app/routers/document.py` 第 28 行

```
改前：def update_one(doc_id, data, db = Depends(get_db), request: Request):
改后：def update_one(doc_id, data, request: Request, db = Depends(get_db)):
```

**原因：** Python 语法要求——有默认值的参数必须排在没有默认值的参数后面。`depends` 提供的参数算有默认值。

---

## 🐛 Bug 7: try/except 被覆盖导致 500

**文件：** `app/routers/document.py` `update_one` 函数

**改前（加广播代码时 try/except 丢了）：**
```python
def update_one(...):
    result = update_document(db, doc_id, data)   # 如果异常 → 500
    # 广播代码...
    return result
```

**改后：**
```python
def update_one(...):
    try:
        result = update_document(db, doc_id, data)
    except ValueError as e:
        raise HTTPException(status_code=409, detail={...})   # 409 而不是 500
    # 广播代码...
    return result
```

---

## 🐛 Bug 8: WebSocket 广播不工作（3 次尝试）⭐ 最难

**涉及文件：** `app/routers/document.py` + `app/routers/ws.py`

### 尝试 1: `loop.create_task()` ❌

```python
# document.py
async def _notify():
    await ws_broadcast(...)
loop = asyncio.get_running_loop()
loop.create_task(_notify())
```

**失败原因：** `update_one` 是 `def`（同步函数），uvicorn 在线程池里运行它——不在主事件循环里，`get_running_loop()` 抛 RuntimeError。

### 尝试 2: `run_coroutine_threadsafe` + `_main_loop` ❌

```python
# ws.py 加全局变量
_main_loop = None
# document_ws 里赋值
_main_loop = asyncio.get_running_loop()

# document.py
asyncio.run_coroutine_threadsafe(ws_broadcast(...), _main_loop)
```

**失败原因：** `_main_loop` 需要 WebSocket 先连上才赋值。而且 uvicorn reload 后 `_main_loop` 重置为 None。

### 尝试 3: `asyncio.Queue` ✅

```python
# ws.py
_notification_queue = asyncio.Queue()

def notify_sync(doc_id, message):          # 同步函数直接调用
    _notification_queue.put_nowait((doc_id, message))

async def _process_notifications():         # 后台协程
    while True:
        doc_id, msg = await _notification_queue.get()
        await broadcast(doc_id, msg)

# document.py — 超简单
notify_sync(doc_id, {"type": "doc_saved", ...})
```

**为什么成功：** `put_nowait` 是线程安全的同步方法，不依赖事件循环。`_process_notifications` 在 WebSocket 事件循环内运行，能正常 `await`。

---

## 🐛 Bug 9: WebSocket 库缺失

**文件：** 不需要改代码。

```bash
# uvicorn 报错 "No supported WebSocket library detected"
uv add websockets
```

---

## 🐛 Bug 10: 文件名尾部空格

```
editing.py   →  editing.py   （多了空格）
```

**修复：** 删掉重建。

---

## 🐛 Bug 11: `__init__.py` 缺 `ws_router` 导出

**文件：** `app/routers/__init__.py`

```
改前：...document_version_router（最后一行，缺 ws_router）
改后：+ from app.routers.ws import router as ws_router
```

---

## 🐛 Bug 12: PC 端验证测试 + 时间问题 ⭐ 娅娅漏掉的

### 12a：PC 端 Python 测试代码

**做什么：** PC 上用 Python 连 WebSocket，Nyarch 上用 curl PUT 保存，PC 收到 `doc_saved` 广播——验证整条链路。

```python
# 在 PC 上跑（Python 3，需要 pip install websockets）
import asyncio
import websockets, json

async def main():
    async with websockets.connect("ws://192.168.1.8:12031/ws/<doc_id>") as ws:
        print("✅ 连上了")
        
        # 1. 先收一条（初始 presence 广播）
        msg = await ws.recv()
        print("→", msg)
        
        # 2. 死循环等消息
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            print("→", data)
            
            if data.get("type") == "doc_saved":
                print("🎉 收到保存广播！链路验证通过")
                break

asyncio.run(main())
```

**Nyarch 端同时跑：**
```bash
curl -X PUT http://localhost:12031/documents/<doc_id> \
  -H "Content-Type: application/json" \
  -d '{"title": "测试", "updated_at": "2026-07-08T18:00:00"}'
```

**结果：** PC 收到 `{"type":"doc_saved","by":{...}}` → 链路通了！

### 12b：updated_at 时间问题

**问题：** PUT 时必须带 `updated_at`（乐观锁需要），否则后端无法判断是否冲突。

| 场景 | `updated_at` 传啥 | 结果 |
|---|---|---|
| 第一次保存 | GET 返回的那个值 | ✅ 200 |
| 保存时别人已经改过了 | GET 返回的那个值（但已过期） | ❌ 409 Conflict |
| 没传 | 无 | 可能 422（校验失败） |

**正确流程：**
```
1. GET /documents/abc  → 拿到 updated_at = "2026-07-08T18:00:00"
2. 编辑...
3. PUT /documents/abc  → body 里带上 {"updated_at": "2026-07-08T18:00:00"}
                      → 后端 WHERE updated_at = "2026-07-08T18:00:00"
                      → rowcount = 1 → 成功
                      → 数据库 updated_at 自动更新为当前时间
```

**如果忘了传 updated_at：** 后端乐观锁的 `WHERE updated_at = ...` 匹配不到 → `rowcount = 0` → 409（但这不是冲突，是参数缺失）。以后可以改进为区分"没传"和"真的冲突"。

### 12c：为什么 PC 用 `await ws.recv()` 而不是 `receive_text()`

```
Python websockets 库 ≠ FastAPI WebSocket

FastAPI 端（服务器）：     Python websockets 端（客户端）：
  ws.receive_text()          ws.recv()
  ws.send_json(data)         ws.send(json.dumps(data))
```

不是同一个类名，但做的事情一样——等对方发消息。

---

## 三、最终文件架构

```
app/
├── editing.py              🆕 编辑状态管理（纯内存字典）
├── routers/
│   ├── ws.py               🆕 WebSocket 端点 + 连接池 + 广播 + 通知队列
│   ├── document.py         改  PUT 成功后调 notify_sync()
│   └── __init__.py         改  + ws_router 导出
├── repositories/
│   └── document.py         改  update() 乐观锁
├── services/
│   └── document.py         改  update_document() 区分冲突
└── schemas/
    └── document.py         改  DocumentUpdate + updated_at

tests/
├── conftest.py             🆕 测试基础设施（PostgreSQL 测试库）
└── test_workspaces.py      🆕 2 passed
```

---

## 四、WebSocket 代码逐行解析

### `editing.py` — 就是个字典

```python
editors = {}  # {doc_id: {user_id: {device, status, ...}}}

join(doc_id, user_id, ...)   → editors[doc_id][user_id] = {...}
leave(doc_id, user_id)        → del editors[doc_id][user_id]
mark_input(doc_id, user_id)   → editors[doc_id][user_id]["status"] = "editing"
get_presence(doc_id)          → 把 editors[doc_id] 转成列表返回
```

### `ws.py` — 三件事：连接、消息循环、广播

```python
connections = {}               # 哪篇文档连着哪些 ws 对象
_notification_queue = Queue()  # 通知队列

@router.websocket("/ws/{doc_id}")       # 定义 WebSocket 路径
async def document_ws(ws, ...):         # async def 因为要 await
    await ws.accept()                   # "握手，你可以连了"
    join(...)                           # 登记编辑状态
    connections[doc_id].append(ws)      # 登记 ws 连接
    await broadcast(...)                # 群发 "有人来了"

    try:
        while True:
            msg = await ws.receive_text()   # 死循环等消息
            if msg["type"] == "input":
                mark_input(...)              # 更新状态
            elif msg["type"] == "leave":
                break                        # 退出循环
            await broadcast(...)             # 群发最新状态
    except WebSocketDisconnect:              # 摔线了
        pass
    finally:
        leave(...)                           # 清理编辑状态
        connections[doc_id].remove(ws)       # 清理连接
        await broadcast(...)                 # 通知别人我走了
```

**为什么用 `while True`？** WebSocket 是长连接——不像 HTTP 请求-响应。连上后一直保持，服务器在循环里等客户端随时发消息。

---

## 五、消息报文速查

### 前端 → 后端

| type | 含义 | 什么时候发 |
|------|------|-----------|
| `input` | 有输入 | input 事件触发 |
| `idle` | 空闲了 | 5 分钟没 input |
| `auto_save` | 自动保存 | 10 分钟空闲 → 自动 PUT |
| `leave` | 离开 | 关标签页/切文档 |

### 后端 → 前端

| type | 含义 | 什么时候发 |
|------|------|-----------|
| `presence` | 编辑状态变化 | 连上/断开/input/idle |
| `doc_saved` | 有人保存了 | PUT 成功后 |

---

## 六、未完成的前端功能

- [ ] Vue3 连接 WebSocket（`new WebSocket("ws://...")`）
- [ ] 5 分钟无输入 → 发 `idle`
- [ ] 10 分钟 idle → 自动 PUT（不带 `create_version`）
- [ ] 收到 `doc_saved` → 提示用户刷新
- [ ] 收到 `presence` → 渲染编辑状态 UI
- [ ] 切换文档时"有未保存内容"弹窗
